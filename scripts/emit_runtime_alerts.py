#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlmodel import Session as DBSession

from rpg_backend.config.settings import get_settings
from rpg_backend.storage.engine import engine, init_db
from rpg_backend.storage.repositories.observability import (
    aggregate_runtime_error_buckets,
    has_recent_alert_dispatch,
    save_alert_dispatch,
)

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


def _build_snapshot(
    db: DBSession,
    *,
    window_seconds: int,
    limit: int,
) -> dict[str, Any]:
    settings = get_settings()
    aggregated = aggregate_runtime_error_buckets(
        db,
        window_seconds=window_seconds,
        limit=limit,
    )
    triggered_buckets: list[dict[str, Any]] = []
    for bucket in aggregated["buckets"]:
        meets_count = bucket.failed_count >= settings.obs_alert_bucket_min_count
        meets_share = (
            bucket.error_share >= settings.obs_alert_bucket_min_share
            and bucket.failed_count >= BUCKET_MIN_COUNT_FOR_SHARE
        )
        if not (meets_count or meets_share):
            continue
        triggered_buckets.append(_serialize_bucket(bucket))

    global_triggered = (
        float(aggregated["step_error_rate"]) > settings.obs_alert_global_error_rate
        and int(aggregated["failed_total"]) >= GLOBAL_ALERT_MIN_FAILED_TOTAL
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_seconds": int(aggregated["window_seconds"]),
        "window_started_at": aggregated["window_started_at"].isoformat(),
        "window_ended_at": aggregated["window_ended_at"].isoformat(),
        "started_total": int(aggregated["started_total"]),
        "failed_total": int(aggregated["failed_total"]),
        "step_error_rate": float(aggregated["step_error_rate"]),
        "global_triggered": bool(global_triggered),
        "triggered_buckets": triggered_buckets,
        "thresholds": {
            "global_error_rate_gt": settings.obs_alert_global_error_rate,
            "global_min_failed_total": GLOBAL_ALERT_MIN_FAILED_TOTAL,
            "bucket_min_count": settings.obs_alert_bucket_min_count,
            "bucket_min_share": settings.obs_alert_bucket_min_share,
            "bucket_min_count_for_share": BUCKET_MIN_COUNT_FOR_SHARE,
            "cooldown_seconds": settings.obs_alert_cooldown_seconds,
        },
    }


def _send_webhook(webhook_url: str, payload: dict[str, Any]) -> None:
    with httpx.Client(timeout=10.0) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()


def _dispatch_alerts(
    db: DBSession,
    *,
    snapshot: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    settings = get_settings()
    triggered_buckets = list(snapshot["triggered_buckets"])
    if not snapshot["global_triggered"] and not triggered_buckets:
        return {
            "status": "no_alert",
            "sent": False,
            "suppressed_bucket_keys": [],
            "alert_payload": snapshot,
        }

    candidate_keys = [bucket["bucket_key"] for bucket in triggered_buckets]
    if snapshot["global_triggered"]:
        candidate_keys.append("global")

    pending_keys: list[str] = []
    suppressed_bucket_keys: list[str] = []
    for key in candidate_keys:
        if has_recent_alert_dispatch(
            db,
            bucket_key=key,
            cooldown_seconds=settings.obs_alert_cooldown_seconds,
        ):
            suppressed_bucket_keys.append(key)
            continue
        pending_keys.append(key)

    if not pending_keys:
        return {
            "status": "cooldown_suppressed",
            "sent": False,
            "suppressed_bucket_keys": suppressed_bucket_keys,
            "alert_payload": snapshot,
        }

    send_payload = dict(snapshot)
    send_payload["triggered_buckets"] = [
        bucket for bucket in triggered_buckets if bucket["bucket_key"] in set(pending_keys)
    ]
    send_payload["global_triggered"] = bool(snapshot["global_triggered"] and "global" in pending_keys)

    if dry_run:
        return {
            "status": "dry_run",
            "sent": False,
            "suppressed_bucket_keys": suppressed_bucket_keys,
            "pending_bucket_keys": pending_keys,
            "alert_payload": send_payload,
        }

    webhook_url = (settings.obs_alert_webhook_url or "").strip()
    if not webhook_url:
        return {
            "status": "webhook_not_configured",
            "sent": False,
            "suppressed_bucket_keys": suppressed_bucket_keys,
            "pending_bucket_keys": pending_keys,
            "alert_payload": send_payload,
        }

    try:
        _send_webhook(webhook_url, send_payload)
    except Exception as exc:  # noqa: BLE001
        for key in pending_keys:
            save_alert_dispatch(
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
            "suppressed_bucket_keys": suppressed_bucket_keys,
            "pending_bucket_keys": pending_keys,
            "error": str(exc),
            "alert_payload": send_payload,
        }

    for key in pending_keys:
        save_alert_dispatch(
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
        "suppressed_bucket_keys": suppressed_bucket_keys,
        "pending_bucket_keys": pending_keys,
        "alert_payload": send_payload,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit runtime 503 bucket alerts to webhook.")
    parser.add_argument(
        "--window-seconds",
        type=int,
        default=None,
        help="Rolling window in seconds. Defaults to APP_OBS_ALERT_WINDOW_SECONDS.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max number of buckets to aggregate (1..100).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute alerts but do not send webhook.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings = get_settings()
    window_seconds = args.window_seconds or settings.obs_alert_window_seconds
    limit = max(1, min(args.limit, 100))

    init_db()
    with DBSession(engine) as db:
        snapshot = _build_snapshot(
            db,
            window_seconds=window_seconds,
            limit=limit,
        )
        dispatch_result = _dispatch_alerts(
            db,
            snapshot=snapshot,
            dry_run=bool(args.dry_run),
        )

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


if __name__ == "__main__":
    raise SystemExit(main())
