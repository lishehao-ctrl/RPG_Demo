import asyncio
import json
import random
import re
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import LLMUsageLog
from app.modules.llm.base import LLMProvider
from app.modules.llm.prompts import (
    build_narrative_repair_prompt,
    build_selection_repair_prompt,
)
from app.modules.llm.providers import DoubaoProvider, FakeProvider
from app.modules.llm.schemas import NarrativeOutput, StorySelectionOutput


class LLMUnavailableError(RuntimeError):
    """Raised when narrative generation fails across the full provider chain."""


class NarrativeParseError(ValueError):
    """Raised when narrative payload cannot be parsed/validated."""

    def __init__(self, message: str, *, error_kind: str, raw_snippet: str | None = None):
        super().__init__(message)
        self.error_kind = str(error_kind)
        self.raw_snippet = raw_snippet


_NARRATIVE_ERROR_TIMEOUT = "NARRATIVE_TIMEOUT"
_NARRATIVE_ERROR_NETWORK = "NARRATIVE_NETWORK"
_NARRATIVE_ERROR_HTTP_STATUS = "NARRATIVE_HTTP_STATUS"
_NARRATIVE_ERROR_JSON_PARSE = "NARRATIVE_JSON_PARSE"
_NARRATIVE_ERROR_SCHEMA_VALIDATE = "NARRATIVE_SCHEMA_VALIDATE"

_TOKEN_REDACTION_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", re.IGNORECASE)


@dataclass(slots=True)
class _CircuitState:
    failure_timestamps: deque[float] = field(default_factory=deque)
    open_until: float = 0.0


class LLMRuntime:
    def __init__(self):
        doubao_provider = DoubaoProvider(
            api_key=settings.llm_doubao_api_key,
            base_url=settings.llm_doubao_base_url,
            temperature=settings.llm_doubao_temperature,
            max_tokens=settings.llm_doubao_max_tokens,
        )
        self.providers: dict[str, LLMProvider] = {
            "fake": FakeProvider(),
            "doubao": doubao_provider,
            # Alias for clarity when using Alibaba Qwen via OpenAI-compatible gateways.
            "alibaba_qwen": doubao_provider,
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
            created_at=datetime.now(timezone.utc),
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

    @staticmethod
    def _sanitize_raw_snippet(raw: object, max_len: int = 200) -> str | None:
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            try:
                text = json.dumps(raw, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                text = str(raw)
        else:
            text = str(raw)
        text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        text = _TOKEN_REDACTION_RE.sub("[REDACTED_KEY]", text)
        text = " ".join(text.split())
        text = text.replace("|", "/")
        if not text:
            return None
        return text[:max_len]

    @staticmethod
    def _extract_json_fragment(raw_text: str) -> str | None:
        if not raw_text:
            return None
        fenced = _FENCED_JSON_RE.search(raw_text)
        if fenced:
            return fenced.group(1).strip()
        left = raw_text.find("{")
        right = raw_text.rfind("}")
        if left == -1 or right == -1 or right <= left:
            return None
        return raw_text[left : right + 1].strip()

    @staticmethod
    def _narrative_error_kind(exc: Exception) -> str:
        if isinstance(exc, NarrativeParseError):
            return exc.error_kind
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return _NARRATIVE_ERROR_TIMEOUT
        if isinstance(exc, httpx.HTTPStatusError):
            return _NARRATIVE_ERROR_HTTP_STATUS
        if isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ReadError,
                httpx.WriteError,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ),
        ):
            return _NARRATIVE_ERROR_NETWORK
        return _NARRATIVE_ERROR_NETWORK

    @staticmethod
    def _narrative_raw_snippet(exc: Exception, raw: object | None) -> str | None:
        if isinstance(exc, NarrativeParseError) and exc.raw_snippet:
            return exc.raw_snippet
        return LLMRuntime._sanitize_raw_snippet(raw)

    @staticmethod
    def _format_narrative_chain_error(
        last_error: Exception | None,
        *,
        error_kind: str | None,
        raw_snippet: str | None,
    ) -> str:
        detail = f": {last_error}" if last_error else ""
        message = f"narrative provider chain exhausted{detail}"
        if error_kind:
            message = f"{message} | kind={error_kind}"
        if raw_snippet:
            message = f"{message} | raw={raw_snippet}"
        return message

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
        last_error_kind: str | None = None
        last_raw_snippet: str | None = None

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
                    last_error_kind = self._narrative_error_kind(exc)
                    last_raw_snippet = self._narrative_raw_snippet(exc, raw)
                    if raw is None:
                        continue
                    repair_raw = None
                    try:
                        repair_raw = self._call_with_network_retries(
                            db,
                            provider_name=provider_name,
                            payload=build_narrative_repair_prompt(str(raw)),
                            model=settings.llm_model_generate,
                            session_id=session_id,
                            step_id=step_id,
                            deadline_at=deadline_at,
                        )
                        parsed = self._parse_narrative(repair_raw)
                        return parsed, True
                    except Exception as repair_exc:  # noqa: BLE001
                        last_error = repair_exc
                        last_error_kind = self._narrative_error_kind(repair_exc)
                        last_raw_snippet = self._narrative_raw_snippet(repair_exc, repair_raw)
                        continue

        raise LLMUnavailableError(
            self._format_narrative_chain_error(
                last_error,
                error_kind=last_error_kind,
                raw_snippet=last_raw_snippet,
            )
        )

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
                            payload=build_selection_repair_prompt(str(raw)),
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
        parsed_payload: object = raw
        original_raw_snippet = LLMRuntime._sanitize_raw_snippet(raw)

        if isinstance(parsed_payload, str):
            raw_text = parsed_payload.strip()
            if not raw_text:
                raise NarrativeParseError(
                    "narrative json parse error: empty response",
                    error_kind=_NARRATIVE_ERROR_JSON_PARSE,
                    raw_snippet=original_raw_snippet,
                )
            try:
                parsed_payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                fragment = LLMRuntime._extract_json_fragment(raw_text)
                if fragment:
                    try:
                        parsed_payload = json.loads(fragment)
                    except json.JSONDecodeError as fragment_exc:
                        raise NarrativeParseError(
                            f"narrative json parse error: {fragment_exc}",
                            error_kind=_NARRATIVE_ERROR_JSON_PARSE,
                            raw_snippet=original_raw_snippet,
                        ) from exc
                else:
                    raise NarrativeParseError(
                        f"narrative json parse error: {exc}",
                        error_kind=_NARRATIVE_ERROR_JSON_PARSE,
                        raw_snippet=original_raw_snippet,
                    ) from exc

        try:
            return NarrativeOutput.model_validate(parsed_payload)
        except ValidationError as exc:
            raise NarrativeParseError(
                f"narrative schema validate error: {exc}",
                error_kind=_NARRATIVE_ERROR_SCHEMA_VALIDATE,
                raw_snippet=LLMRuntime._sanitize_raw_snippet(parsed_payload),
            ) from exc


_runtime: LLMRuntime | None = None


def get_llm_runtime() -> LLMRuntime:
    global _runtime
    if _runtime is None:
        _runtime = LLMRuntime()
    return _runtime
