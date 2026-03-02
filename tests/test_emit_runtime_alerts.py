from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


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
        },
    }


def test_dispatch_alerts_dry_run_skips_webhook_and_dispatch_write(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    monkeypatch.setattr(
        alerts,
        "get_settings",
        lambda: SimpleNamespace(
            obs_alert_cooldown_seconds=900,
            obs_alert_webhook_url="https://hooks.example/obs",
        ),
    )
    monkeypatch.setattr(alerts, "has_recent_alert_dispatch", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        alerts,
        "_send_webhook",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("webhook must not be called in dry-run")),
    )
    monkeypatch.setattr(
        alerts,
        "save_alert_dispatch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dispatch must not be saved in dry-run")),
    )

    result = alerts._dispatch_alerts(
        db=object(),
        snapshot=snapshot,
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert result["sent"] is False
    assert set(result["pending_bucket_keys"]) == {"llm_route_failed|route|gpt-test", "global"}


def test_dispatch_alerts_sends_webhook_and_writes_dispatch(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    sent_payloads: list[dict] = []
    dispatch_rows: list[tuple[str, str]] = []

    monkeypatch.setattr(
        alerts,
        "get_settings",
        lambda: SimpleNamespace(
            obs_alert_cooldown_seconds=900,
            obs_alert_webhook_url="https://hooks.example/obs",
        ),
    )
    monkeypatch.setattr(alerts, "has_recent_alert_dispatch", lambda *args, **kwargs: False)
    monkeypatch.setattr(alerts, "_send_webhook", lambda _url, payload: sent_payloads.append(payload))
    monkeypatch.setattr(
        alerts,
        "save_alert_dispatch",
        lambda *_args, **kwargs: dispatch_rows.append((kwargs["bucket_key"], kwargs["status"])),
    )

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


def test_dispatch_alerts_respects_cooldown(monkeypatch) -> None:
    snapshot = _sample_snapshot()
    monkeypatch.setattr(
        alerts,
        "get_settings",
        lambda: SimpleNamespace(
            obs_alert_cooldown_seconds=900,
            obs_alert_webhook_url="https://hooks.example/obs",
        ),
    )
    monkeypatch.setattr(alerts, "has_recent_alert_dispatch", lambda *args, **kwargs: True)
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
