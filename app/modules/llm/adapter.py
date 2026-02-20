import asyncio
import json
import random
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import LLMUsageLog
from app.modules.llm.base import LLMProvider
from app.modules.llm.prompts import build_repair_prompt
from app.modules.llm.providers import DoubaoProvider, FakeProvider
from app.modules.llm.schemas import NarrativeOutput, StorySelectionOutput


class LLMUnavailableError(RuntimeError):
    """Raised when narrative generation fails across the full provider chain."""


@dataclass(slots=True)
class _CircuitState:
    failure_timestamps: deque[float] = field(default_factory=deque)
    open_until: float = 0.0


class LLMRuntime:
    def __init__(self):
        self.providers: dict[str, LLMProvider] = {
            "fake": FakeProvider(),
            "doubao": DoubaoProvider(api_key=settings.llm_doubao_api_key, base_url=settings.llm_doubao_base_url),
        }
        self._circuits: dict[str, _CircuitState] = defaultdict(_CircuitState)

    def _log_usage(
        self,
        db: Session,
        *,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None,
        operation: str,
        usage: dict,
    ):
        row = LLMUsageLog(
            session_id=session_id,
            provider=usage.get("provider", "unknown"),
            model=usage.get("model", "unknown"),
            operation=operation,
            step_id=step_id,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=int(usage.get("latency_ms", 0) or 0),
            status=usage.get("status", "success"),
            error_message=usage.get("error_message"),
            created_at=datetime.utcnow(),
        )
        db.add(row)

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
            return status_code == 429 or status_code >= 500
        return False

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

    def _sleep_backoff(self, attempt_index: int, *, deadline_at: float) -> None:
        base_ms = max(1, int(settings.llm_retry_backoff_base_ms))
        cap_ms = max(base_ms, int(settings.llm_retry_backoff_max_ms))
        backoff_ms = min(cap_ms, base_ms * (2 ** max(0, attempt_index)))
        jitter_ms = random.randint(0, max(1, backoff_ms // 4))
        wait_s = (backoff_ms + jitter_ms) / 1000.0
        wait_s = min(wait_s, self._deadline_remaining_s(deadline_at))
        if wait_s > 0:
            time.sleep(wait_s)

    def _call_once(
        self,
        db: Session,
        *,
        provider_name: str,
        payload: str,
        model: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None,
        deadline_at: float,
    ):
        remaining = self._deadline_remaining_s(deadline_at)
        if remaining <= 0:
            raise TimeoutError("llm total deadline exceeded")

        provider = self.providers[provider_name]
        call_timeout_s = min(float(settings.llm_timeout_s), remaining)
        call_timeout_s = max(0.1, call_timeout_s)
        read_timeout_s = min(float(settings.llm_read_timeout_s), call_timeout_s)
        write_timeout_s = min(float(settings.llm_write_timeout_s), call_timeout_s)
        pool_timeout_s = min(float(settings.llm_pool_timeout_s), call_timeout_s)
        connect_timeout_s = min(float(settings.llm_connect_timeout_s), call_timeout_s)
        try:
            result, usage = self._run(
                provider.generate(
                    payload,
                    request_id=str(uuid.uuid4()),
                    timeout_s=call_timeout_s,
                    model=model,
                    connect_timeout_s=connect_timeout_s,
                    read_timeout_s=read_timeout_s,
                    write_timeout_s=write_timeout_s,
                    pool_timeout_s=pool_timeout_s,
                )
            )
            usage["provider"] = provider_name
            usage["model"] = model
            usage["status"] = usage.get("status", "success")
            self._log_usage(db, session_id=session_id, step_id=step_id, operation="generate", usage=usage)
            self._record_success(provider_name)
            return result
        except Exception as exc:  # noqa: BLE001
            self._log_usage(
                db,
                session_id=session_id,
                step_id=step_id,
                operation="generate",
                usage={
                    "provider": provider_name,
                    "model": model,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "latency_ms": 0,
                    "status": "error",
                    "error_message": str(exc),
                },
            )
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
        deadline_at: float,
    ):
        attempts = max(1, int(settings.llm_retry_attempts_network))
        last_exc: Exception | None = None
        for attempt_index in range(attempts):
            try:
                return self._call_once(
                    db,
                    provider_name=provider_name,
                    payload=payload,
                    model=model,
                    session_id=session_id,
                    step_id=step_id,
                    deadline_at=deadline_at,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not self._is_retryable_network_error(exc):
                    raise
                if attempt_index >= attempts - 1:
                    raise
                if self._deadline_remaining_s(deadline_at) <= 0:
                    raise
                self._sleep_backoff(attempt_index, deadline_at=deadline_at)
        raise RuntimeError(str(last_exc) if last_exc else "llm call failed")

    def narrative_with_fallback(
        self,
        db: Session,
        *,
        prompt: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None = None,
    ) -> tuple[NarrativeOutput, bool]:
        provider_chain = [settings.llm_provider_primary] + list(settings.llm_provider_fallbacks)
        deadline_at = time.monotonic() + max(0.1, float(settings.llm_total_deadline_s))
        last_error: Exception | None = None

        for idx, provider_name in enumerate(provider_chain):
            if provider_name not in self.providers:
                continue
            if self._is_circuit_open(provider_name):
                continue
            retries = settings.llm_max_retries if idx == 0 else 1
            for _ in range(retries):
                raw = None
                try:
                    raw = self._call_with_network_retries(
                        db,
                        provider_name=provider_name,
                        payload=prompt,
                        model=settings.llm_model_generate,
                        session_id=session_id,
                        step_id=step_id,
                        deadline_at=deadline_at,
                    )
                    parsed = self._parse_narrative(raw)
                    return parsed, True
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if raw is None:
                        continue
                    try:
                        repair_raw = self._call_with_network_retries(
                            db,
                            provider_name=provider_name,
                            payload=build_repair_prompt(str(raw)),
                            model=settings.llm_model_generate,
                            session_id=session_id,
                            step_id=step_id,
                            deadline_at=deadline_at,
                        )
                        parsed = self._parse_narrative(repair_raw)
                        return parsed, True
                    except Exception as repair_exc:  # noqa: BLE001
                        last_error = repair_exc
                        continue

        detail = f": {last_error}" if last_error else ""
        raise LLMUnavailableError(f"narrative provider chain exhausted{detail}")

    def select_story_choice_with_fallback(
        self,
        db: Session,
        *,
        prompt: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None = None,
    ) -> tuple[StorySelectionOutput, bool]:
        provider_chain = [settings.llm_provider_primary] + list(settings.llm_provider_fallbacks)
        deadline_at = time.monotonic() + max(0.1, float(settings.llm_total_deadline_s))
        for idx, provider_name in enumerate(provider_chain):
            if provider_name not in self.providers:
                continue
            if self._is_circuit_open(provider_name):
                continue
            retries = settings.llm_max_retries if idx == 0 else 1
            for _ in range(retries):
                raw = None
                try:
                    raw = self._call_with_network_retries(
                        db,
                        provider_name=provider_name,
                        payload=prompt,
                        model=settings.llm_model_generate,
                        session_id=session_id,
                        step_id=step_id,
                        deadline_at=deadline_at,
                    )
                    if isinstance(raw, str):
                        raw = json.loads(raw)
                    parsed = StorySelectionOutput.model_validate(raw)
                    return parsed, True
                except Exception:
                    if raw is None:
                        continue
                    try:
                        repair_raw = self._call_with_network_retries(
                            db,
                            provider_name=provider_name,
                            payload=build_repair_prompt(str(raw)),
                            model=settings.llm_model_generate,
                            session_id=session_id,
                            step_id=step_id,
                            deadline_at=deadline_at,
                        )
                        if isinstance(repair_raw, str):
                            repair_raw = json.loads(repair_raw)
                        parsed = StorySelectionOutput.model_validate(repair_raw)
                        return parsed, True
                    except Exception:
                        continue

        fallback = StorySelectionOutput(
            choice_id=None,
            use_fallback=True,
            confidence=0.0,
            intent_id=None,
            notes="selector_fallback",
        )
        return fallback, False

    @staticmethod
    def _parse_narrative(raw) -> NarrativeOutput:
        if isinstance(raw, str):
            raw = json.loads(raw)
        return NarrativeOutput.model_validate(raw)


_runtime: LLMRuntime | None = None


def get_llm_runtime() -> LLMRuntime:
    global _runtime
    if _runtime is None:
        _runtime = LLMRuntime()
    return _runtime
