from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session as DBSession
from sqlmodel import desc, func, select

from rpg_backend.storage.models import RuntimeAlertDispatch, RuntimeEvent


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RuntimeErrorBucket:
    error_code: str
    stage: str
    model: str
    failed_count: int
    error_share: float
    last_seen_at: datetime | None
    sample_session_ids: list[str]
    sample_request_ids: list[str]


def _normalize_stage(stage: str | None) -> str:
    value = (stage or "").strip().lower()
    if value in {"route", "narration"}:
        return value
    return "unknown"


def _resolve_model(stage: str, payload_json: dict[str, Any]) -> str:
    route_model = payload_json.get("route_model")
    narration_model = payload_json.get("narration_model")
    if stage == "route":
        return str(route_model or narration_model or "unknown")
    if stage == "narration":
        return str(narration_model or route_model or "unknown")
    return str(route_model or narration_model or "unknown")


def aggregate_runtime_error_buckets(
    db: DBSession,
    *,
    window_seconds: int,
    limit: int,
    stage: str | None = None,
    error_code: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_value = now or utc_now()
    window_start = now_value - timedelta(seconds=window_seconds)
    stage_filter = _normalize_stage(stage) if stage else None
    error_code_filter = (error_code or "").strip() or None

    started_stmt = select(func.count()).select_from(RuntimeEvent).where(
        RuntimeEvent.event_type == "step_started",
        RuntimeEvent.created_at >= window_start,
    )
    started_total = int(db.exec(started_stmt).one())

    failed_stmt = (
        select(RuntimeEvent)
        .where(
            RuntimeEvent.event_type == "step_failed",
            RuntimeEvent.created_at >= window_start,
        )
        .order_by(desc(RuntimeEvent.created_at))
    )
    failed_events = list(db.exec(failed_stmt).all())

    grouped: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "failed_count": 0,
            "last_seen_at": None,
            "sample_session_ids": [],
            "sample_request_ids": [],
            "_session_seen": set(),
            "_request_seen": set(),
        }
    )

    filtered_failed_total = 0
    for event in failed_events:
        payload = event.payload_json or {}
        event_stage = _normalize_stage(payload.get("stage"))
        event_error_code = str(payload.get("error_code") or "unknown_error")

        if stage_filter and event_stage != stage_filter:
            continue
        if error_code_filter and event_error_code != error_code_filter:
            continue

        filtered_failed_total += 1
        model = _resolve_model(event_stage, payload)
        key = (event_error_code, event_stage, model)
        bucket = grouped[key]
        bucket["failed_count"] += 1
        if bucket["last_seen_at"] is None:
            bucket["last_seen_at"] = event.created_at

        session_id = str(event.session_id)
        if session_id and session_id not in bucket["_session_seen"] and len(bucket["sample_session_ids"]) < 5:
            bucket["_session_seen"].add(session_id)
            bucket["sample_session_ids"].append(session_id)

        request_id = str(payload.get("request_id") or "")
        if request_id and request_id not in bucket["_request_seen"] and len(bucket["sample_request_ids"]) < 5:
            bucket["_request_seen"].add(request_id)
            bucket["sample_request_ids"].append(request_id)

    denominator = max(started_total, 1)
    buckets: list[RuntimeErrorBucket] = []
    for (event_error_code, event_stage, model), bucket in grouped.items():
        buckets.append(
            RuntimeErrorBucket(
                error_code=event_error_code,
                stage=event_stage,
                model=model,
                failed_count=int(bucket["failed_count"]),
                error_share=float(bucket["failed_count"]) / denominator,
                last_seen_at=bucket["last_seen_at"],
                sample_session_ids=list(bucket["sample_session_ids"]),
                sample_request_ids=list(bucket["sample_request_ids"]),
            )
        )

    buckets.sort(
        key=lambda item: (
            -item.failed_count,
            -(item.last_seen_at.timestamp() if item.last_seen_at else 0),
            item.error_code,
            item.stage,
            item.model,
        )
    )
    limited_buckets = buckets[:limit]
    step_error_rate = filtered_failed_total / denominator if started_total else 0.0

    return {
        "generated_at": now_value,
        "window_started_at": window_start,
        "window_ended_at": now_value,
        "window_seconds": window_seconds,
        "started_total": started_total,
        "failed_total": filtered_failed_total,
        "step_error_rate": step_error_rate,
        "buckets": limited_buckets,
    }


def has_recent_alert_dispatch(
    db: DBSession,
    *,
    bucket_key: str,
    cooldown_seconds: int,
    now: datetime | None = None,
) -> bool:
    now_value = now or utc_now()
    since = now_value - timedelta(seconds=cooldown_seconds)
    stmt = (
        select(RuntimeAlertDispatch)
        .where(
            RuntimeAlertDispatch.bucket_key == bucket_key,
            RuntimeAlertDispatch.sent_at >= since,
            RuntimeAlertDispatch.status == "sent",
        )
        .order_by(desc(RuntimeAlertDispatch.sent_at))
        .limit(1)
    )
    return db.exec(stmt).first() is not None


def save_alert_dispatch(
    db: DBSession,
    *,
    bucket_key: str,
    window_started_at: datetime,
    window_ended_at: datetime,
    status: str,
    payload_json: dict[str, Any],
    sent_at: datetime | None = None,
) -> RuntimeAlertDispatch:
    dispatch = RuntimeAlertDispatch(
        bucket_key=bucket_key,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        sent_at=sent_at or utc_now(),
        status=status,
        payload_json=payload_json,
    )
    db.add(dispatch)
    db.commit()
    db.refresh(dispatch)
    return dispatch
