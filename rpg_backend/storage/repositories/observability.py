from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any

from sqlmodel import Session as DBSession
from sqlmodel import desc, func, select

from rpg_backend.storage.models import (
    HttpRequestEvent,
    LLMCallEvent,
    ReadinessProbeEvent,
    RuntimeAlertDispatch,
    RuntimeEvent,
)


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


@dataclass
class Http5xxPathBucket:
    path: str
    failed_count: int
    sample_request_ids: list[str]


@dataclass
class ReadinessFailureRecord:
    service: str
    error_code: str | None
    request_id: str | None
    created_at: datetime


def _normalize_stage(stage: str | None) -> str:
    value = (stage or "").strip().lower()
    if value in {"route", "narration"}:
        return value
    if value in {"json"}:
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


def _nearest_rank_percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    bounded = max(0.0, min(100.0, float(percentile)))
    ordered = sorted(int(v) for v in values)
    rank = int(ceil((bounded / 100.0) * len(ordered)))
    index = max(0, min(len(ordered) - 1, rank - 1))
    return ordered[index]


def save_http_request_event(
    db: DBSession,
    *,
    service: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    request_id: str | None,
    created_at: datetime | None = None,
) -> HttpRequestEvent:
    event = HttpRequestEvent(
        service=str(service or "backend"),
        method=str(method or "GET"),
        path=str(path or ""),
        status_code=int(status_code),
        duration_ms=max(0, int(duration_ms)),
        request_id=(request_id or None),
        created_at=created_at or utc_now(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def save_llm_call_event(
    db: DBSession,
    *,
    session_id: str | None,
    turn_index: int | None,
    stage: str,
    gateway_mode: str,
    model: str,
    success: bool,
    error_code: str | None,
    duration_ms: int,
    request_id: str | None,
    created_at: datetime | None = None,
) -> LLMCallEvent:
    event = LLMCallEvent(
        session_id=session_id,
        turn_index=turn_index,
        stage=_normalize_stage(stage),
        gateway_mode=str(gateway_mode or "unknown").strip().lower() or "unknown",
        model=str(model or "unknown"),
        success=bool(success),
        error_code=(str(error_code).strip() if error_code else None),
        duration_ms=max(0, int(duration_ms)),
        request_id=(request_id or None),
        created_at=created_at or utc_now(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def save_readiness_probe_event(
    db: DBSession,
    *,
    service: str,
    ok: bool,
    error_code: str | None,
    latency_ms: int | None,
    request_id: str | None,
    created_at: datetime | None = None,
) -> ReadinessProbeEvent:
    event = ReadinessProbeEvent(
        service=str(service or "backend").strip().lower() or "backend",
        ok=bool(ok),
        error_code=(str(error_code).strip() if error_code else None),
        latency_ms=int(latency_ms) if latency_ms is not None else None,
        request_id=(request_id or None),
        created_at=created_at or utc_now(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


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


def aggregate_http_health(
    db: DBSession,
    *,
    window_seconds: int,
    service: str,
    path_prefix: str | None = None,
    exclude_paths: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_value = now or utc_now()
    window_start = now_value - timedelta(seconds=window_seconds)

    stmt = select(HttpRequestEvent).where(
        HttpRequestEvent.created_at >= window_start,
        HttpRequestEvent.service == str(service or "backend"),
    )
    events = list(db.exec(stmt).all())

    prefix = (path_prefix or "").strip()
    excluded = [item for item in (exclude_paths or []) if item]

    filtered: list[HttpRequestEvent] = []
    for event in events:
        path = event.path or ""
        if prefix and not path.startswith(prefix):
            continue
        if any(path.startswith(item) for item in excluded):
            continue
        filtered.append(event)

    total_requests = len(filtered)
    failed_events = [event for event in filtered if int(event.status_code) >= 500]
    failed_5xx = len(failed_events)
    error_rate = (failed_5xx / total_requests) if total_requests else 0.0
    p95_ms = _nearest_rank_percentile([event.duration_ms for event in filtered], 95.0)

    grouped_paths: dict[str, Http5xxPathBucket] = {}
    for event in failed_events:
        path = str(event.path or "unknown")
        bucket = grouped_paths.get(path)
        if bucket is None:
            bucket = Http5xxPathBucket(path=path, failed_count=0, sample_request_ids=[])
            grouped_paths[path] = bucket
        bucket.failed_count += 1
        rid = str(event.request_id or "")
        if rid and rid not in bucket.sample_request_ids and len(bucket.sample_request_ids) < 5:
            bucket.sample_request_ids.append(rid)

    top_5xx_paths = sorted(
        [
            {
                "path": bucket.path,
                "failed_count": bucket.failed_count,
                "sample_request_ids": list(bucket.sample_request_ids),
            }
            for bucket in grouped_paths.values()
        ],
        key=lambda item: (-int(item["failed_count"]), item["path"]),
    )[:10]

    return {
        "generated_at": now_value,
        "window_started_at": window_start,
        "window_ended_at": now_value,
        "window_seconds": window_seconds,
        "service": str(service),
        "total_requests": total_requests,
        "failed_5xx": failed_5xx,
        "error_rate": error_rate,
        "p95_ms": p95_ms,
        "top_5xx_paths": top_5xx_paths,
    }


def aggregate_llm_call_health(
    db: DBSession,
    *,
    window_seconds: int,
    stage: str | None = None,
    gateway_mode: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_value = now or utc_now()
    window_start = now_value - timedelta(seconds=window_seconds)

    stmt = select(LLMCallEvent).where(LLMCallEvent.created_at >= window_start)
    if stage:
        stmt = stmt.where(LLMCallEvent.stage == _normalize_stage(stage))
    if gateway_mode:
        stmt = stmt.where(LLMCallEvent.gateway_mode == str(gateway_mode).strip().lower())
    events = list(db.exec(stmt).all())

    total_calls = len(events)
    failed_calls = sum(1 for event in events if not event.success)
    failure_rate = (failed_calls / total_calls) if total_calls else 0.0
    p95_ms = _nearest_rank_percentile([event.duration_ms for event in events], 95.0)

    by_stage: dict[str, dict[str, Any]] = {}
    stage_grouped: dict[str, list[LLMCallEvent]] = defaultdict(list)
    for event in events:
        stage_grouped[event.stage].append(event)
    for key, grouped_events in stage_grouped.items():
        total = len(grouped_events)
        failed = sum(1 for item in grouped_events if not item.success)
        by_stage[key] = {
            "total_calls": total,
            "failed_calls": failed,
            "failure_rate": (failed / total) if total else 0.0,
            "p95_ms": _nearest_rank_percentile([item.duration_ms for item in grouped_events], 95.0),
        }

    by_gateway_mode: dict[str, dict[str, Any]] = {}
    gateway_grouped: dict[str, list[LLMCallEvent]] = defaultdict(list)
    for event in events:
        gateway_grouped[event.gateway_mode].append(event)
    for key, grouped_events in gateway_grouped.items():
        total = len(grouped_events)
        failed = sum(1 for item in grouped_events if not item.success)
        by_gateway_mode[key] = {
            "total_calls": total,
            "failed_calls": failed,
            "failure_rate": (failed / total) if total else 0.0,
            "p95_ms": _nearest_rank_percentile([item.duration_ms for item in grouped_events], 95.0),
        }

    return {
        "generated_at": now_value,
        "window_started_at": window_start,
        "window_ended_at": now_value,
        "window_seconds": window_seconds,
        "total_calls": total_calls,
        "failed_calls": failed_calls,
        "failure_rate": failure_rate,
        "p95_ms": p95_ms,
        "by_stage": by_stage,
        "by_gateway_mode": by_gateway_mode,
    }


def compute_ready_fail_streak(
    db: DBSession,
    *,
    service: str,
    max_lookback: int = 100,
) -> int:
    stmt = (
        select(ReadinessProbeEvent)
        .where(ReadinessProbeEvent.service == str(service).strip().lower())
        .order_by(desc(ReadinessProbeEvent.created_at))
        .limit(max(1, int(max_lookback)))
    )
    events = list(db.exec(stmt).all())

    streak = 0
    for event in events:
        if event.ok:
            break
        streak += 1
    return streak


def aggregate_readiness_health(
    db: DBSession,
    *,
    window_seconds: int,
    service: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_value = now or utc_now()
    window_start = now_value - timedelta(seconds=window_seconds)

    stmt = select(ReadinessProbeEvent).where(ReadinessProbeEvent.created_at >= window_start)
    if service:
        stmt = stmt.where(ReadinessProbeEvent.service == str(service).strip().lower())
    events = list(db.exec(stmt).all())

    backend_fail = 0
    worker_fail = 0
    failures: list[ReadinessFailureRecord] = []
    for event in events:
        if event.ok:
            continue
        if event.service == "backend":
            backend_fail += 1
        elif event.service == "worker":
            worker_fail += 1
        failures.append(
            ReadinessFailureRecord(
                service=event.service,
                error_code=event.error_code,
                request_id=event.request_id,
                created_at=event.created_at,
            )
        )

    failures.sort(key=lambda item: item.created_at, reverse=True)

    return {
        "generated_at": now_value,
        "window_started_at": window_start,
        "window_ended_at": now_value,
        "window_seconds": window_seconds,
        "backend_ready_fail_count": backend_fail,
        "worker_ready_fail_count": worker_fail,
        "backend_fail_streak": compute_ready_fail_streak(db, service="backend", max_lookback=100),
        "worker_fail_streak": compute_ready_fail_streak(db, service="worker", max_lookback=100),
        "last_failures": [
            {
                "service": record.service,
                "error_code": record.error_code,
                "request_id": record.request_id,
                "created_at": record.created_at,
            }
            for record in failures[:20]
        ],
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
