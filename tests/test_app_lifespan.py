from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module


def test_create_app_health_endpoint() -> None:
    with TestClient(main_module.create_app()) as client:
        res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_lifespan_calls_init_db(monkeypatch) -> None:
    calls = {"count": 0}

    def _fake_init_db() -> None:
        calls["count"] += 1

    monkeypatch.setattr(main_module, "init_db", _fake_init_db)

    with TestClient(main_module.create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200

    assert calls["count"] == 1

