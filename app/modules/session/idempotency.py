from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import LLMUsageLog, SessionStepIdempotency

IDEMPOTENCY_STATUS_IN_PROGRESS = "in_progress"
IDEMPOTENCY_STATUS_SUCCEEDED = "succeeded"
IDEMPOTENCY_STATUS_FAILED = "failed"


def normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalized_optional_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def request_hash(*, choice_id: str | None, player_input: str | None) -> str:
    canonical = json.dumps(
        {"choice_id": choice_id, "player_input": player_input},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_response_payload(payload: dict) -> dict:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def idempotency_expiry(now: datetime | None = None) -> datetime:
    base = as_utc_datetime(now) or datetime.now(timezone.utc)
    ttl = max(1, int(settings.step_idempotency_ttl_s))
    return base + timedelta(seconds=ttl)


def is_stale_in_progress(row: SessionStepIdempotency, now: datetime | None = None) -> bool:
    current = as_utc_datetime(now) or datetime.now(timezone.utc)
    threshold = max(1, int(settings.step_idempotency_in_progress_stale_s))
    anchor = as_utc_datetime(row.updated_at) or as_utc_datetime(row.created_at) or current
    return (current - anchor).total_seconds() > threshold


def extract_http_error_code(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return f"HTTP_{int(exc.status_code)}"


def extract_http_error_message(exc: HTTPException) -> str | None:
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return None


def persist_idempotency_failed(
    db: Session,
    *,
    session_id: uuid.UUID,
    idempotency_key: str,
    request_hash_value: str,
    error_code: str,
    error_message: str | None = None,
) -> None:
    db.rollback()
    with db.begin():
        row = db.execute(
            select(SessionStepIdempotency).where(
                SessionStepIdempotency.session_id == session_id,
                SessionStepIdempotency.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        expiry = idempotency_expiry(now)
        if row is None:
            db.add(
                SessionStepIdempotency(
                    session_id=session_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash_value,
                    status=IDEMPOTENCY_STATUS_FAILED,
                    response_json=None,
                    error_code=error_code,
                    created_at=now,
                    updated_at=now,
                    expires_at=expiry,
                )
            )
            return
        if row.request_hash != request_hash_value:
            return
        row.status = IDEMPOTENCY_STATUS_FAILED
        row.error_code = error_code
        row.updated_at = now
        row.expires_at = expiry
        if error_code == "LLM_UNAVAILABLE":
            db.add(
                LLMUsageLog(
                    session_id=session_id,
                    provider=str(settings.llm_provider_primary),
                    model=str(settings.llm_model_generate),
                    operation="generate",
                    step_id=uuid.uuid4(),
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                    status="error",
                    error_message=(error_message or error_code)[:500],
                    created_at=now,
                )
            )
