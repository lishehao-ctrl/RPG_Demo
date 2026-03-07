#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.application.admin_console.observability_queries import (
    query_http_health,
    query_llm_health,
    query_readiness_health,
    query_runtime_errors,
)
from rpg_backend.config.settings import get_settings
from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.observability_async import (
    has_recent_alert_dispatch,
    save_alert_dispatch,
)
from rpg_backend.storage.engine import init_db

GLOBAL_ALERT_MIN_FAILED_TOTAL = 3
BUCKET_MIN_COUNT_FOR_SHARE = 2

def _bucket_key(error_code: str, stage: str, model: str) -> str:
    return f"{error_code}|{stage}|{model}"


def _serialize_bucket(bucket: Any) -> dict[str, Any]:
    return {
        "error_code": bucket.error_code,
        "stage": bucket.stage,
        "model": bucket.model,
        "failed_count": int(bucket.failed_count),
        "error_share": float(bucket.error_share),
        "last_seen_at": bucket.last_seen_at.isoformat() if bucket.last_seen_at else None,
        "sample_session_ids": list(bucket.sample_session_ids),
        "sample_request_ids": list(bucket.sample_request_ids),
        "bucket_key": _bucket_key(bucket.error_code, bucket.stage, bucket.model),
    }


def _build_signal(
    *,
    signal: str,
    dispatch_key: str,
    severity: str,
    value: Any,
    threshold: Any,
    window_seconds: int,
    samples: dict[str, Any],
    runbook_hint: str,
) -> dict[str, Any]:
    return {
        "signal": signal,
        "dispatch_key": dispatch_key,
        "severity": severity,
        "value": value,
        "threshold": threshold,
        "window_seconds": window_seconds,
        "samples": samples,
        "runbook_hint": runbook_hint,
    }


async def aggregate_runtime_error_buckets(db: AsyncSession, *, window_seconds: int, limit: int) -> dict[str, Any]:
    return await query_runtime_errors(db, window_seconds=window_seconds, limit=limit)


async def aggregate_http_health(
    db: AsyncSession,
    *,
    window_seconds: int,
    service: str,
    exclude_paths: list[str] | None = None,
) -> dict[str, Any]:
    return await query_http_health(
        db,
        window_seconds=window_seconds,
        service=service,
        exclude_paths=exclude_paths,
    )


async def aggregate_llm_call_health(db: AsyncSession, *, window_seconds: int) -> dict[str, Any]:
    return await query_llm_health(db, window_seconds=window_seconds)


async def aggregate_readiness_health(db: AsyncSession, *, window_seconds: int) -> dict[str, Any]:
    return await query_readiness_health(db, window_seconds=window_seconds)


async def _build_snapshot_async(
    db: AsyncSession,
    *,
    window_seconds: int,
    limit: int,
) -> dict[str, Any]:
    settings = get_settings()
    runtime_agg = await aggregate_runtime_error_buckets(db, window_seconds=window_seconds, limit=limit)
    http_agg = await aggregate_http_health(
        db,
        window_seconds=window_seconds,
        service="backend",
        exclude_paths=["/health"],
    )
    llm_agg = await aggregate_llm_call_health(db, window_seconds=window_seconds)
    readiness_agg = await aggregate_readiness_health(db, window_seconds=window_seconds)

    triggered_buckets: list[dict[str, Any]] = []
    for bucket in runtime_agg["buckets"]:
        meets_count = bucket.failed_count >= settings.obs_alert_bucket_min_count
        meets_share = (
            bucket.error_share >= settings.obs_alert_bucket_min_share
            and bucket.failed_count >= BUCKET_MIN_COUNT_FOR_SHARE
        )
        if meets_count or meets_share:
            triggered_buckets.append(_serialize_bucket(bucket))

    global_triggered = (
        float(runtime_agg["step_error_rate"]) > settings.obs_alert_global_error_rate
        and int(runtime_agg["failed_total"]) >= GLOBAL_ALERT_MIN_FAILED_TOTAL
    )

    worker_group = llm_agg.get("by_gateway_mode", {}).get("worker", {})
    worker_total = int(worker_group.get("total_calls") or 0)
    worker_failed = int(worker_group.get("failed_calls") or 0)
    worker_failure_rate = float(worker_group.get("failure_rate") or 0.0)
    llm_total = int(llm_agg["total_calls"])
    llm_p95 = llm_agg.get("p95_ms")
    signals: list[dict[str, Any]] = []

    if int(http_agg["total_requests"]) >= settings.obs_alert_http_5xx_min_count and float(http_agg["error_rate"]) > float(
        settings.obs_alert_http_5xx_rate
    ):
        signals.append(
            _build_signal(
                signal="http_5xx_rate_high",
                dispatch_key="signal:http_5xx_rate",
                severity="critical",
                value={
                    "error_rate": float(http_agg["error_rate"]),
                    "failed_5xx": int(http_agg["failed_5xx"]),
                    "total_requests": int(http_agg["total_requests"]),
                },
                threshold={
                    "error_rate_gt": float(settings.obs_alert_http_5xx_rate),
                    "min_total_requests": int(settings.obs_alert_http_5xx_min_count),
                },
                window_seconds=window_seconds,
                samples={"top_5xx_paths": list(http_agg["top_5xx_paths"][:5])},
                runbook_hint="docs/oncall_sop.md#http_5xx_rate_high",
            )
        )

    if int(readiness_agg["backend_fail_streak"]) >= int(settings.obs_alert_ready_fail_streak):
        signals.append(
            _build_signal(
                signal="backend_ready_unhealthy",
                dispatch_key="signal:backend_ready",
                severity="critical",
                value={
                    "backend_fail_streak": int(readiness_agg["backend_fail_streak"]),
                    "backend_ready_fail_count": int(readiness_agg["backend_ready_fail_count"]),
                },
                threshold={"ready_fail_streak_gte": int(settings.obs_alert_ready_fail_streak)},
                window_seconds=window_seconds,
                samples={
                    "last_failures": [item for item in readiness_agg["last_failures"] if item.get("service") == "backend"][
                        :5
                    ]
                },
                runbook_hint="docs/oncall_sop.md#backend_ready_unhealthy",
            )
        )

    if worker_total >= int(settings.obs_alert_worker_fail_min_count) and worker_failure_rate > float(
        settings.obs_alert_worker_fail_rate
    ):
        signals.append(
            _build_signal(
                signal="worker_failure_rate_high",
                dispatch_key="signal:worker_failure_rate",
                severity="warning",
                value={
                    "worker_failure_rate": worker_failure_rate,
                    "worker_failed_calls": worker_failed,
                    "worker_total_calls": worker_total,
                },
                threshold={
                    "worker_failure_rate_gt": float(settings.obs_alert_worker_fail_rate),
                    "min_worker_calls": int(settings.obs_alert_worker_fail_min_count),
                },
                window_seconds=window_seconds,
                samples={"by_stage": llm_agg.get("by_stage", {}), "worker_group": worker_group},
                runbook_hint="docs/oncall_sop.md#worker_failure_rate_high",
            )
        )

    if llm_total >= int(settings.obs_alert_llm_call_min_count) and isinstance(llm_p95, int) and llm_p95 > int(
        settings.obs_alert_llm_call_p95_ms
    ):
        signals.append(
            _build_signal(
                signal="llm_call_p95_high",
                dispatch_key="signal:llm_call_p95",
                severity="warning",
                value={"llm_call_p95_ms": int(llm_p95), "total_calls": llm_total},
                threshold={
                    "llm_call_p95_ms_gt": int(settings.obs_alert_llm_call_p95_ms),
                    "min_total_calls": int(settings.obs_alert_llm_call_min_count),
                },
                window_seconds=window_seconds,
                samples={
                    "by_stage": llm_agg.get("by_stage", {}),
                    "by_gateway_mode": llm_agg.get("by_gateway_mode", {}),
                },
                runbook_hint="docs/oncall_sop.md#llm_call_p95_high",
            )
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_seconds": int(runtime_agg["window_seconds"]),
        "window_started_at": runtime_agg["window_started_at"].isoformat(),
        "window_ended_at": runtime_agg["window_ended_at"].isoformat(),
        "started_total": int(runtime_agg["started_total"]),
        "failed_total": int(runtime_agg["failed_total"]),
        "step_error_rate": float(runtime_agg["step_error_rate"]),
        "global_triggered": bool(global_triggered),
        "triggered_buckets": triggered_buckets,
        "http_health": {
            "total_requests": int(http_agg["total_requests"]),
            "failed_5xx": int(http_agg["failed_5xx"]),
            "error_rate": float(http_agg["error_rate"]),
            "p95_ms": http_agg.get("p95_ms"),
            "top_5xx_paths": list(http_agg["top_5xx_paths"]),
        },
        "llm_call_health": {
            "total_calls": llm_total,
            "failed_calls": int(llm_agg["failed_calls"]),
            "failure_rate": float(llm_agg["failure_rate"]),
            "p95_ms": llm_p95,
            "by_stage": dict(llm_agg.get("by_stage", {})),
            "by_gateway_mode": dict(llm_agg.get("by_gateway_mode", {})),
        },
        "readiness_health": {
            "backend_ready_fail_count": int(readiness_agg["backend_ready_fail_count"]),
            "worker_ready_fail_count": int(readiness_agg["worker_ready_fail_count"]),
            "backend_fail_streak": int(readiness_agg["backend_fail_streak"]),
            "worker_fail_streak": int(readiness_agg["worker_fail_streak"]),
            "last_failures": list(readiness_agg["last_failures"]),
        },
        "signals": signals,
        "thresholds": {
            "global_error_rate_gt": settings.obs_alert_global_error_rate,
            "global_min_failed_total": GLOBAL_ALERT_MIN_FAILED_TOTAL,
            "bucket_min_count": settings.obs_alert_bucket_min_count,
            "bucket_min_share": settings.obs_alert_bucket_min_share,
            "bucket_min_count_for_share": BUCKET_MIN_COUNT_FOR_SHARE,
            "cooldown_seconds": settings.obs_alert_cooldown_seconds,
            "http_5xx_rate_gt": settings.obs_alert_http_5xx_rate,
            "http_5xx_min_count": settings.obs_alert_http_5xx_min_count,
            "ready_fail_streak": settings.obs_alert_ready_fail_streak,
            "worker_fail_rate_gt": settings.obs_alert_worker_fail_rate,
            "worker_fail_min_count": settings.obs_alert_worker_fail_min_count,
            "llm_call_p95_ms_gt": settings.obs_alert_llm_call_p95_ms,
            "llm_call_min_count": settings.obs_alert_llm_call_min_count,
        },
    }


def _send_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    with httpx.Client(timeout=10.0) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()


def _highest_severity(*, signals: list[dict[str, Any]], global_triggered: bool) -> str:
    if global_triggered or any(str(signal.get("severity")) == "critical" for signal in signals):
        return "critical"
    return "warning"


async def _dispatch_alerts_async(
    db: AsyncSession,
    *,
    snapshot: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    settings = get_settings()
    triggered_buckets = list(snapshot.get("triggered_buckets") or [])
    triggered_signals = list(snapshot.get("signals") or [])
    has_any_alert = bool(snapshot.get("global_triggered") or triggered_buckets or triggered_signals)
    if not has_any_alert:
        return {
            "status": "no_alert",
            "sent": False,
            "suppressed_bucket_keys": [],
            "suppressed_signal_keys": [],
            "alert_payload": snapshot,
        }

    candidate_keys = [bucket["bucket_key"] for bucket in triggered_buckets]
    if snapshot.get("global_triggered"):
        candidate_keys.append("global")
    candidate_keys.extend(str(signal.get("dispatch_key")) for signal in triggered_signals if signal.get("dispatch_key"))

    pending_keys: list[str] = []
    suppressed_keys: list[str] = []
    for key in candidate_keys:
        in_cooldown = await has_recent_alert_dispatch(
            db,
            bucket_key=key,
            cooldown_seconds=settings.obs_alert_cooldown_seconds,
        )
        if in_cooldown:
            suppressed_keys.append(key)
        else:
            pending_keys.append(key)

    if not pending_keys:
        return {
            "status": "cooldown_suppressed",
            "sent": False,
            "suppressed_bucket_keys": [key for key in suppressed_keys if not key.startswith("signal:")],
            "suppressed_signal_keys": [key for key in suppressed_keys if key.startswith("signal:")],
            "alert_payload": snapshot,
        }

    pending_key_set = set(pending_keys)
    send_payload = dict(snapshot)
    send_payload["triggered_buckets"] = [
        bucket for bucket in triggered_buckets if bucket["bucket_key"] in pending_key_set
    ]
    send_payload["global_triggered"] = bool(snapshot.get("global_triggered") and "global" in pending_key_set)
    send_payload["signals"] = [
        signal for signal in triggered_signals if str(signal.get("dispatch_key")) in pending_key_set
    ]
    send_payload["severity"] = _highest_severity(
        signals=send_payload["signals"],
        global_triggered=bool(send_payload["global_triggered"]),
    )
    send_payload["source"] = "rpg-observability-alerts"

    if dry_run:
        return {
            "status": "dry_run",
            "sent": False,
            "suppressed_bucket_keys": [key for key in suppressed_keys if not key.startswith("signal:")],
            "suppressed_signal_keys": [key for key in suppressed_keys if key.startswith("signal:")],
            "pending_bucket_keys": [key for key in pending_keys if not key.startswith("signal:")],
            "pending_signal_keys": [key for key in pending_keys if key.startswith("signal:")],
            "alert_payload": send_payload,
        }

    webhook_url = (settings.obs_alert_webhook_url or "").strip()
    if not webhook_url:
        return {
            "status": "webhook_not_configured",
            "sent": False,
            "suppressed_bucket_keys": [key for key in suppressed_keys if not key.startswith("signal:")],
            "suppressed_signal_keys": [key for key in suppressed_keys if key.startswith("signal:")],
            "pending_bucket_keys": [key for key in pending_keys if not key.startswith("signal:")],
            "pending_signal_keys": [key for key in pending_keys if key.startswith("signal:")],
            "alert_payload": send_payload,
        }

    try:
        await asyncio.to_thread(_send_webhook, webhook_url, send_payload)
    except Exception as exc:  # noqa: BLE001
        for key in pending_keys:
            async with transactional(db):
                await save_alert_dispatch(
                    db,
                    bucket_key=key,
                    window_started_at=datetime.fromisoformat(snapshot["window_started_at"]),
                    window_ended_at=datetime.fromisoformat(snapshot["window_ended_at"]),
                    status="failed",
                    payload_json={"error": str(exc), "payload": send_payload},
                )
        return {
            "status": "send_failed",
            "sent": False,
            "suppressed_bucket_keys": [key for key in suppressed_keys if not key.startswith("signal:")],
            "suppressed_signal_keys": [key for key in suppressed_keys if key.startswith("signal:")],
            "pending_bucket_keys": [key for key in pending_keys if not key.startswith("signal:")],
            "pending_signal_keys": [key for key in pending_keys if key.startswith("signal:")],
            "error": str(exc),
            "alert_payload": send_payload,
        }

    for key in pending_keys:
        async with transactional(db):
            await save_alert_dispatch(
                db,
                bucket_key=key,
                window_started_at=datetime.fromisoformat(snapshot["window_started_at"]),
                window_ended_at=datetime.fromisoformat(snapshot["window_ended_at"]),
                status="sent",
                payload_json=send_payload,
            )
    return {
        "status": "sent",
        "sent": True,
        "suppressed_bucket_keys": [key for key in suppressed_keys if not key.startswith("signal:")],
        "suppressed_signal_keys": [key for key in suppressed_keys if key.startswith("signal:")],
        "pending_bucket_keys": [key for key in pending_keys if not key.startswith("signal:")],
        "pending_signal_keys": [key for key in pending_keys if key.startswith("signal:")],
        "alert_payload": send_payload,
    }


def _build_snapshot(
    db: Any,
    *,
    window_seconds: int,
    limit: int,
) -> dict[str, Any]:
    return asyncio.run(_build_snapshot_async(db, window_seconds=window_seconds, limit=limit))


def _dispatch_alerts(
    db: Any,
    *,
    snapshot: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    return asyncio.run(_dispatch_alerts_async(db, snapshot=snapshot, dry_run=dry_run))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit runtime 503 bucket alerts to webhook.")
    parser.add_argument("--window-seconds", type=int, default=None, help="Rolling window in seconds.")
    parser.add_argument("--limit", type=int, default=20, help="Max runtime error buckets to aggregate (1..100).")
    parser.add_argument("--dry-run", action="store_true", help="Compute alerts but do not send webhook.")
    return parser


async def _async_main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings = get_settings()
    window_seconds = args.window_seconds or settings.obs_alert_window_seconds
    limit = max(1, min(args.limit, 100))

    init_db()
    async with AsyncSession(async_engine, expire_on_commit=False) as db:
        snapshot = await _build_snapshot_async(db, window_seconds=window_seconds, limit=limit)
        dispatch_result = await _dispatch_alerts_async(db, snapshot=snapshot, dry_run=bool(args.dry_run))

    output = {
        "window_seconds": window_seconds,
        "limit": limit,
        "dry_run": bool(args.dry_run),
        "snapshot": snapshot,
        "dispatch": dispatch_result,
    }
    print(json.dumps(output, ensure_ascii=True, indent=2))

    if dispatch_result["status"] in {"send_failed", "webhook_not_configured"}:
        return 1
    return 0


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
