from __future__ import annotations

from typing import Any

from pydantic import ValidationError

MAX_STAGE_REGEN_ATTEMPTS = 3


def append_quality_trace(
    current_trace: list[dict[str, Any]],
    *,
    stage: str,
    outcome: str,
    reasons: list[str] | None = None,
    source: str = "deterministic",
    metrics: dict[str, Any] | None = None,
    strict_enabled: bool = False,
) -> list[dict[str, Any]]:
    if strict_enabled and outcome == "retry_exhausted":
        normalized_reasons: list[str] = []
        for item in (reasons or [])[:6]:
            text = str(item)
            if text.startswith("retry_exhausted:"):
                text = text.split(":", 1)[1]
            normalized_reasons.append(text)
        joined_reasons = ",".join(normalized_reasons) or "none"
        raise RuntimeError(f"strict_no_repair_fallback:{stage}:{outcome}:{joined_reasons}")
    record = {
        "stage": stage,
        "source": source,
        "outcome": outcome,
        "reasons": reasons or [],
    }
    if metrics:
        record.update(metrics)
    return [*current_trace, record]


def extend_llm_trace(
    current_trace: list[dict[str, Any]],
    *,
    gateway: Any,
    start_index: int,
    stage: str,
    duration_seconds: float,
    retry_count: int = 0,
    extra_fields: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    appended: list[dict[str, Any]] = []
    for entry in gateway.call_trace[start_index:]:
        merged = {
            **entry,
            "stage": stage,
            "mode": gateway.profile_id,
            "model": gateway.model,
            "duration_seconds": round(duration_seconds, 4),
            "retry_count": retry_count,
        }
        if extra_fields:
            merged.update(extra_fields)
        appended.append(merged)
    return [*current_trace, *appended]


def fallback_reason(exc: Exception | None) -> str:
    if exc is None:
        return "live_gateway_unavailable"
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(exc, ValidationError):
        errors = list(exc.errors() or [])
        if not errors:
            return "schema_invalid"
        first = errors[0]
        loc_tokens = [str(token) for token in list(first.get("loc") or []) if str(token)]
        loc = ".".join(loc_tokens) if loc_tokens else "root"
        err_type = str(first.get("type") or "invalid")
        return f"schema_invalid:{loc}:{err_type}"
    if isinstance(exc, ValueError):
        text = " ".join(str(exc).split()).strip()
        return f"business_invalid:{text[:120]}" if text else "business_invalid"
    return exc.__class__.__name__.casefold()


def is_provider_failure(exc: Exception) -> bool:
    return fallback_reason(exc) == "llm_provider_failed"


def retry_exhausted_outcome(
    *,
    strict_enabled: bool,
    last_reason: str,
) -> tuple[str, list[str]]:
    normalized_reason = f"retry_exhausted:{last_reason}"
    if strict_enabled:
        return "retry_exhausted", [normalized_reason]
    return "fallback", [normalized_reason]
