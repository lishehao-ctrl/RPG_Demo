from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from collections.abc import Callable

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.llm.runtime.chat_completions_client import LLMOutputValidationError
from app.modules.llm.runtime.errors import NarrativeParseError
from app.modules.llm.runtime.progress import StageEmitter, emit_stage
from app.modules.llm.runtime.types import CircuitState, LLMTimeoutProfile


class TransportOps:
    providers: dict

    def __init__(self) -> None:
        self._circuits: dict[str, CircuitState] = defaultdict(CircuitState)

    def _run(self, coro):
        return asyncio.run(coro)

    @staticmethod
    def _is_retryable_network_error(exc: Exception) -> bool:
        if isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ReadError,
                httpx.WriteError,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = int(exc.response.status_code)
            return status_code >= 400
        return False

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        if isinstance(exc, (NarrativeParseError, LLMOutputValidationError)):
            return True
        return TransportOps._is_retryable_network_error(exc)

    @staticmethod
    def _deadline_remaining_s(deadline_at: float) -> float:
        return max(0.0, deadline_at - time.monotonic())

    def _prune_circuit_failures(self, provider_name: str, *, now: float) -> None:
        state = self._circuits[provider_name]
        window = max(1.0, float(settings.llm_circuit_breaker_window_s))
        while state.failure_timestamps and now - state.failure_timestamps[0] > window:
            state.failure_timestamps.popleft()

    def _is_circuit_open(self, provider_name: str) -> bool:
        now = time.monotonic()
        state = self._circuits[provider_name]
        self._prune_circuit_failures(provider_name, now=now)
        return bool(state.open_until > now)

    def _record_network_failure(self, provider_name: str) -> None:
        now = time.monotonic()
        state = self._circuits[provider_name]
        state.failure_timestamps.append(now)
        self._prune_circuit_failures(provider_name, now=now)
        threshold = max(1, int(settings.llm_circuit_breaker_fail_threshold))
        if len(state.failure_timestamps) >= threshold:
            state.open_until = now + max(1.0, float(settings.llm_circuit_breaker_open_s))

    def _record_success(self, provider_name: str) -> None:
        state = self._circuits[provider_name]
        state.failure_timestamps.clear()
        state.open_until = 0.0

    def _sleep_backoff(self, attempt_index: int, *, deadline_at: float | None) -> None:
        if attempt_index <= 0:
            wait_s = 0.5
        elif attempt_index == 1:
            wait_s = 1.0
        else:
            wait_s = 0.0
        if deadline_at is not None:
            wait_s = min(wait_s, self._deadline_remaining_s(deadline_at))
        if wait_s > 0:
            time.sleep(wait_s)

    @staticmethod
    def _normalize_timeout_value(value: float | None) -> float | None:
        if value is None:
            return None
        return max(0.1, float(value))

    def _resolve_timeout_profile(self, timeout_profile: LLMTimeoutProfile | None) -> LLMTimeoutProfile:
        if timeout_profile is not None:
            return timeout_profile
        return LLMTimeoutProfile(
            disable_total_deadline=False,
            call_timeout_s=float(settings.llm_timeout_s),
            connect_timeout_s=float(settings.llm_connect_timeout_s),
            read_timeout_s=float(settings.llm_read_timeout_s),
            write_timeout_s=float(settings.llm_write_timeout_s),
            pool_timeout_s=float(settings.llm_pool_timeout_s),
        )

    def _call_once(
        self,
        db: Session,
        *,
        provider_name: str,
        payload: str,
        model: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None,
        deadline_at: float | None,
        timeout_profile: LLMTimeoutProfile | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
    ):
        remaining: float | None = None
        if deadline_at is not None:
            remaining = self._deadline_remaining_s(deadline_at)
            if remaining <= 0:
                raise TimeoutError("llm total deadline exceeded")

        profile = self._resolve_timeout_profile(timeout_profile)
        provider = self.providers[provider_name]
        call_timeout_s = self._normalize_timeout_value(profile.call_timeout_s)
        if remaining is not None and call_timeout_s is not None:
            call_timeout_s = max(0.1, min(call_timeout_s, remaining))

        def clamp_sub_timeout(value: float | None) -> float | None:
            timeout_value = self._normalize_timeout_value(value)
            if timeout_value is None:
                return None
            if call_timeout_s is not None:
                timeout_value = min(timeout_value, call_timeout_s)
            return max(0.1, timeout_value)

        read_timeout_s = clamp_sub_timeout(profile.read_timeout_s)
        write_timeout_s = clamp_sub_timeout(profile.write_timeout_s)
        pool_timeout_s = clamp_sub_timeout(profile.pool_timeout_s)
        connect_timeout_s = clamp_sub_timeout(profile.connect_timeout_s)
        try:
            provider_kwargs = {
                "request_id": str(uuid.uuid4()),
                "timeout_s": call_timeout_s,
                "model": model,
                "connect_timeout_s": connect_timeout_s,
                "read_timeout_s": read_timeout_s,
                "write_timeout_s": write_timeout_s,
                "pool_timeout_s": pool_timeout_s,
                "temperature_override": 0.0,
            }
            if max_tokens_override is not None:
                provider_kwargs["max_tokens_override"] = int(max_tokens_override)
            if messages_override is not None:
                provider_kwargs["messages_override"] = messages_override
            result, _usage = self._run(provider.generate(payload, **provider_kwargs))
            self._record_success(provider_name)
            return result
        except Exception as exc:  # noqa: BLE001
            if self._is_retryable_network_error(exc):
                self._record_network_failure(provider_name)
            raise

    def _call_with_network_retries(
        self,
        db: Session,
        *,
        provider_name: str,
        payload: str,
        model: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None,
        deadline_at: float | None,
        timeout_profile: LLMTimeoutProfile | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        validator: Callable[[object], object] | None = None,
        stage_emitter: StageEmitter | None = None,
        stage_locale: str | None = None,
        stage_task: str | None = None,
        stage_request_kind: str | None = None,
    ):
        attempts = 3
        last_exc: Exception | None = None
        for attempt_index in range(attempts):
            try:
                raw = self._call_once(
                    db,
                    provider_name=provider_name,
                    payload=payload,
                    model=model,
                    session_id=session_id,
                    step_id=step_id,
                    deadline_at=deadline_at,
                    timeout_profile=timeout_profile,
                    max_tokens_override=max_tokens_override,
                    temperature_override=temperature_override,
                    messages_override=messages_override,
                )
                if validator is not None:
                    validator(raw)
                return raw
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not self._is_retryable_error(exc):
                    raise
                if attempt_index >= attempts - 1:
                    raise
                if deadline_at is not None and self._deadline_remaining_s(deadline_at) <= 0:
                    raise
                emit_stage(
                    stage_emitter,
                    stage_code="llm.retry",
                    locale=stage_locale,
                    task=stage_task,
                    request_kind=stage_request_kind,
                )
                self._sleep_backoff(attempt_index, deadline_at=deadline_at)
        raise RuntimeError(str(last_exc) if last_exc else "llm call failed")

    def _call_with_protocol_fallback(
        self,
        db: Session,
        *,
        provider_name: str,
        payload: str,
        model: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None,
        deadline_at: float | None,
        timeout_profile: LLMTimeoutProfile | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        validator: Callable[[object], object] | None = None,
        stage_emitter: StageEmitter | None = None,
        stage_locale: str | None = None,
        stage_task: str | None = None,
        stage_request_kind: str | None = None,
    ):
        return self._call_with_network_retries(
            db,
            provider_name=provider_name,
            payload=payload,
            model=model,
            session_id=session_id,
            step_id=step_id,
            deadline_at=deadline_at,
            timeout_profile=timeout_profile,
            max_tokens_override=max_tokens_override,
            temperature_override=temperature_override,
            messages_override=messages_override,
            validator=validator,
            stage_emitter=stage_emitter,
            stage_locale=stage_locale,
            stage_task=stage_task,
            stage_request_kind=stage_request_kind,
        )
