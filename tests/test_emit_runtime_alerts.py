from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from tests.helpers.route_paths import session_step_path


def _load_alerts_module():
    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(scripts_dir))
    script_path = scripts_dir / "emit_runtime_alerts.py"
    spec = importlib.util.spec_from_file_location("emit_runtime_alerts", script_path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("failed to load emit_runtime_alerts module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


alerts = _load_alerts_module()


def _sample_snapshot() -> dict:
    return {
        "generated_at": "2026-03-02T00:00:00+00:00",
        "window_seconds": 300,
        "window_started_at": "2026-03-01T23:55:00+00:00",
        "window_ended_at": "2026-03-02T00:00:00+00:00",
        "started_total": 10,
        "failed_total": 4,
        "step_error_rate": 0.4,
        "global_triggered": True,
        "signals": [],
        "triggered_buckets": [
            {
                "error_code": "llm_route_failed",
                "stage": "route",
                "model": "gpt-test",
                "failed_count": 4,
                "error_share": 0.4,
                "last_seen_at": "2026-03-02T00:00:00+00:00",
                "sample_session_ids": ["s1"],
                "sample_request_ids": ["r1"],
                "bucket_key": "llm_route_failed|route|gpt-test",
            }
        ],
        "thresholds": {
            "global_error_rate_gt": 0.05,
            "global_min_failed_total": 3,
            "bucket_min_count": 3,
            "bucket_min_share": 0.1,
            "bucket_min_count_for_share": 2,
            "cooldown_seconds": 900,
            "http_5xx_rate_gt": 0.05,
            "http_5xx_min_count": 10,
            "ready_fail_streak": 2,
            "worker_fail_rate_gt": 0.05,
            "worker_fail_min_count": 20,
            "llm_call_p95_ms_gt": 3000,
            "llm_call_min_count": 30,
        },
    }


def test_dispatch_alerts_dry_run_skips_webhook_and_dispatch_write(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    async def _has_recent_alert_dispatch(*_args, **_kwargs):  # noqa: ANN202
        return False

    async def _save_alert_dispatch(*_args, **_kwargs):  # noqa: ANN202
        raise AssertionError("dispatch must not be saved in dry-run")

    monkeypatch.setattr(
        alerts,
        "get_settings",
        lambda: SimpleNamespace(
            obs_alert_cooldown_seconds=900,
            obs_alert_webhook_url="https://hooks.example/obs",
        ),
    )
    monkeypatch.setattr(alerts, "has_recent_alert_dispatch", _has_recent_alert_dispatch)
    monkeypatch.setattr(
        alerts,
        "_send_webhook",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("webhook must not be called in dry-run")),
    )
    monkeypatch.setattr(alerts, "save_alert_dispatch", _save_alert_dispatch)

    result = alerts._dispatch_alerts(
        db=object(),
        snapshot=snapshot,
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert result["sent"] is False
    assert set(result["pending_bucket_keys"]) == {"llm_route_failed|route|gpt-test", "global"}
    assert result["pending_signal_keys"] == []


def test_dispatch_alerts_sends_webhook_and_writes_dispatch(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    sent_payloads: list[dict] = []
    dispatch_rows: list[tuple[str, str]] = []
    async def _has_recent_alert_dispatch(*_args, **_kwargs):  # noqa: ANN202
        return False

    async def _save_alert_dispatch(*_args, **kwargs):  # noqa: ANN202
        dispatch_rows.append((kwargs["bucket_key"], kwargs["status"]))

    monkeypatch.setattr(
        alerts,
        "get_settings",
        lambda: SimpleNamespace(
            obs_alert_cooldown_seconds=900,
            obs_alert_webhook_url="https://hooks.example/obs",
        ),
    )
    monkeypatch.setattr(alerts, "has_recent_alert_dispatch", _has_recent_alert_dispatch)
    monkeypatch.setattr(alerts, "_send_webhook", lambda _url, payload: sent_payloads.append(payload))
    monkeypatch.setattr(alerts, "save_alert_dispatch", _save_alert_dispatch)

    result = alerts._dispatch_alerts(
        db=object(),
        snapshot=snapshot,
        dry_run=False,
    )
    assert result["status"] == "sent"
    assert result["sent"] is True
    assert len(sent_payloads) == 1
    assert ("llm_route_failed|route|gpt-test", "sent") in dispatch_rows
    assert ("global", "sent") in dispatch_rows
    assert result["pending_signal_keys"] == []


def test_dispatch_alerts_respects_cooldown(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    async def _has_recent_alert_dispatch(*_args, **_kwargs):  # noqa: ANN202
        return True

    monkeypatch.setattr(
        alerts,
        "get_settings",
        lambda: SimpleNamespace(
            obs_alert_cooldown_seconds=900,
            obs_alert_webhook_url="https://hooks.example/obs",
        ),
    )
    monkeypatch.setattr(alerts, "has_recent_alert_dispatch", _has_recent_alert_dispatch)
    monkeypatch.setattr(
        alerts,
        "_send_webhook",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("webhook should be suppressed by cooldown")),
    )

    result = alerts._dispatch_alerts(
        db=object(),
        snapshot=snapshot,
        dry_run=False,
    )
    assert result["status"] == "cooldown_suppressed"
    assert result["sent"] is False
    assert "global" in result["suppressed_bucket_keys"]
    assert result["suppressed_signal_keys"] == []


def test_build_snapshot_emits_all_new_signals(monkeypatch) -> None:
    settings = SimpleNamespace(
        obs_alert_bucket_min_count=3,
        obs_alert_bucket_min_share=0.1,
        obs_alert_global_error_rate=0.05,
        obs_alert_cooldown_seconds=900,
        obs_alert_http_5xx_rate=0.05,
        obs_alert_http_5xx_min_count=10,
        obs_alert_ready_fail_streak=2,
        obs_alert_worker_fail_rate=0.05,
        obs_alert_worker_fail_min_count=20,
        obs_alert_llm_call_p95_ms=3000,
        obs_alert_llm_call_min_count=30,
    )
    async def _aggregate_runtime_error_buckets(*_args, **_kwargs):  # noqa: ANN202
        return {
            "window_seconds": 300,
            "window_started_at": alerts.datetime(2026, 3, 1, 23, 55, tzinfo=alerts.UTC),
            "window_ended_at": alerts.datetime(2026, 3, 2, 0, 0, tzinfo=alerts.UTC),
            "started_total": 100,
            "failed_total": 12,
            "step_error_rate": 0.12,
            "buckets": [
                SimpleNamespace(
                    error_code="llm_route_failed",
                    stage="route",
                    model="gpt-test",
                    failed_count=8,
                    error_share=0.08,
                    last_seen_at=alerts.datetime(2026, 3, 2, 0, 0, tzinfo=alerts.UTC),
                    sample_session_ids=["s1"],
                    sample_request_ids=["r1"],
                )
            ],
        }

    async def _aggregate_http_health(*_args, **_kwargs):  # noqa: ANN202
        return {
            "total_requests": 100,
            "failed_5xx": 9,
            "error_rate": 0.09,
            "p95_ms": 1200,
            "top_5xx_paths": [{"path": session_step_path("x"), "failed_count": 6, "sample_request_ids": ["r1"]}],
        }

    async def _aggregate_llm_call_health(*_args, **_kwargs):  # noqa: ANN202
        return {
            "total_calls": 120,
            "failed_calls": 10,
            "failure_rate": 0.0833,
            "p95_ms": 3450,
            "by_stage": {
                "route": {"total_calls": 70, "failed_calls": 7, "failure_rate": 0.1, "p95_ms": 3600},
                "narration": {"total_calls": 50, "failed_calls": 3, "failure_rate": 0.06, "p95_ms": 3200},
            },
            "by_gateway_mode": {
                "worker": {"total_calls": 80, "failed_calls": 6, "failure_rate": 0.075, "p95_ms": 3500},
                "unknown": {"total_calls": 40, "failed_calls": 4, "failure_rate": 0.1, "p95_ms": 3300},
            },
        }

    async def _aggregate_readiness_health(*_args, **_kwargs):  # noqa: ANN202
        return {
            "backend_ready_fail_count": 4,
            "worker_ready_fail_count": 1,
            "backend_fail_streak": 3,
            "worker_fail_streak": 1,
            "last_failures": [
                {
                    "service": "backend",
                    "error_code": "llm_probe_timeout",
                    "request_id": "rb-1",
                    "created_at": "2026-03-02T00:00:00+00:00",
                }
            ],
        }

    monkeypatch.setattr(alerts, "get_settings", lambda: settings)
    monkeypatch.setattr(alerts, "aggregate_runtime_error_buckets", _aggregate_runtime_error_buckets)
    monkeypatch.setattr(alerts, "aggregate_http_health", _aggregate_http_health)
    monkeypatch.setattr(alerts, "aggregate_llm_call_health", _aggregate_llm_call_health)
    monkeypatch.setattr(alerts, "aggregate_readiness_health", _aggregate_readiness_health)

    snapshot = alerts._build_snapshot(db=object(), window_seconds=300, limit=20)
    assert snapshot["global_triggered"] is True
    signal_names = {item["signal"] for item in snapshot["signals"]}
    assert signal_names == {
        "http_5xx_rate_high",
        "backend_ready_unhealthy",
        "worker_failure_rate_high",
        "llm_call_p95_high",
    }
    severities = {item["signal"]: item["severity"] for item in snapshot["signals"]}
    assert severities["http_5xx_rate_high"] == "critical"
    assert severities["backend_ready_unhealthy"] == "critical"
    assert severities["worker_failure_rate_high"] == "warning"
    assert severities["llm_call_p95_high"] == "warning"


def test_dispatch_alerts_persists_signal_dispatch_keys(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    snapshot["global_triggered"] = False
    snapshot["signals"] = [
        {
            "signal": "http_5xx_rate_high",
            "dispatch_key": "signal:http_5xx_rate",
            "severity": "critical",
            "value": {"error_rate": 0.5},
            "threshold": {"error_rate_gt": 0.05},
            "window_seconds": 300,
            "samples": {"top_5xx_paths": []},
            "runbook_hint": "docs/oncall_sop.md#http_5xx_rate_high",
        }
    ]

    sent_payloads: list[dict] = []
    dispatch_rows: list[tuple[str, str]] = []
    async def _has_recent_alert_dispatch(*_args, **_kwargs):  # noqa: ANN202
        return False

    async def _save_alert_dispatch(*_args, **kwargs):  # noqa: ANN202
        dispatch_rows.append((kwargs["bucket_key"], kwargs["status"]))

    monkeypatch.setattr(
        alerts,
        "get_settings",
        lambda: SimpleNamespace(
            obs_alert_cooldown_seconds=900,
            obs_alert_webhook_url="https://hooks.example/obs",
        ),
    )
    monkeypatch.setattr(alerts, "has_recent_alert_dispatch", _has_recent_alert_dispatch)
    monkeypatch.setattr(alerts, "_send_webhook", lambda _url, payload: sent_payloads.append(payload))
    monkeypatch.setattr(alerts, "save_alert_dispatch", _save_alert_dispatch)

    result = alerts._dispatch_alerts(
        db=object(),
        snapshot=snapshot,
        dry_run=False,
    )
    assert result["status"] == "sent"
    assert "signal:http_5xx_rate" in result["pending_signal_keys"]
    assert ("signal:http_5xx_rate", "sent") in dispatch_rows
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["severity"] == "critical"
