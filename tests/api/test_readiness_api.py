from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlmodel import Session as DBSession
from sqlmodel import select

from rpg_backend.observability import readiness as readiness_obs
from rpg_backend.storage.engine import engine
from rpg_backend.storage.models import ReadinessProbeEvent


def _now() -> datetime:
    return datetime.now(UTC)


def _check(
    *,
    ok: bool,
    error_code: str | None = None,
    message: str | None = None,
    meta: dict | None = None,
) -> dict:
    return {
        "ok": ok,
        "latency_ms": 1,
        "checked_at": _now(),
        "error_code": error_code,
        "message": message,
        "meta": meta or {},
    }


def _async_check(
    *,
    ok: bool,
    error_code: str | None = None,
    message: str | None = None,
    meta: dict | None = None,
    include_refresh_meta: bool = False,
):
    async def _runner(*, refresh: bool = False) -> dict:
        payload_meta = dict(meta or {})
        if include_refresh_meta:
            payload_meta["refresh"] = refresh
        return _check(ok=ok, error_code=error_code, message=message, meta=payload_meta)

    return _runner


def _install_ready_settings(monkeypatch, *, ttl_seconds: int = 30) -> None:
    settings = SimpleNamespace(
        llm_openai_base_url="https://upstream.example/compatible-mode",
        llm_openai_api_key="test-key",
        llm_openai_model="model-default",
        llm_openai_route_model="",
        llm_openai_narration_model="",
        llm_openai_generator_model="",
        llm_worker_base_url="http://worker.internal",
        internal_worker_token="worker-secret",
        ready_llm_probe_enabled=True,
        ready_llm_probe_cache_ttl_seconds=ttl_seconds,
        ready_llm_probe_timeout_seconds=5.0,
    )
    monkeypatch.setattr(readiness_obs, "get_settings", lambda: settings)


def test_health_unchanged_returns_ok(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_all_checks_ok(client, monkeypatch) -> None:
    monkeypatch.setattr(readiness_obs, "check_db", _async_check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True, meta={"probe_model": "m"}))
    monkeypatch.setattr(readiness_obs, "check_llm_probe", _async_check(ok=True, meta={"cached": False}, include_refresh_meta=True))

    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["db"]["ok"] is True
    assert body["checks"]["llm_config"]["ok"] is True
    assert body["checks"]["llm_probe"]["ok"] is True


def test_ready_returns_503_when_db_fails(client, monkeypatch) -> None:
    monkeypatch.setattr(
        readiness_obs,
        "check_db",
        _async_check(ok=False, error_code="db_unavailable", message="db down"),
    )
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_probe", _async_check(ok=True))

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["db"]["ok"] is False
    assert body["checks"]["db"]["error_code"] == "db_unavailable"


def test_ready_returns_503_when_llm_config_missing(client, monkeypatch) -> None:
    monkeypatch.setattr(readiness_obs, "check_db", _async_check(ok=True))
    monkeypatch.setattr(
        readiness_obs,
        "check_llm_config",
        lambda: _check(ok=False, error_code="llm_config_invalid", message="missing model"),
    )

    async def _unexpected_probe(*, refresh: bool = False):  # noqa: ARG001
        raise AssertionError("llm probe should be skipped when llm_config is invalid")

    monkeypatch.setattr(readiness_obs, "check_llm_probe", _unexpected_probe)

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["llm_config"]["ok"] is False
    assert body["checks"]["llm_config"]["error_code"] == "llm_config_invalid"
    assert body["checks"]["llm_probe"]["error_code"] == "llm_probe_misconfigured"


def test_ready_returns_503_when_llm_probe_fails(client, monkeypatch) -> None:
    monkeypatch.setattr(readiness_obs, "check_db", _async_check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True))
    monkeypatch.setattr(
        readiness_obs,
        "check_llm_probe",
        _async_check(ok=False, error_code="llm_probe_timeout", message="timed out"),
    )

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["llm_probe"]["ok"] is False
    assert body["checks"]["llm_probe"]["error_code"] == "llm_probe_timeout"


def test_ready_uses_cached_llm_probe_within_ttl(client, monkeypatch) -> None:
    asyncio.run(readiness_obs.reset_llm_probe_cache())
    _install_ready_settings(monkeypatch, ttl_seconds=30)
    clock = {"value": 1000.0}
    monkeypatch.setattr(readiness_obs, "_monotonic", lambda: clock["value"])

    class _FakeWorkerClient:
        def __init__(self) -> None:
            self.calls = 0

        async def probe_ready(self, *, refresh: bool = False):  # noqa: ANN201
            del refresh
            self.calls += 1
            return (
                200,
                {
                    "status": "ready",
                    "checks": {
                        "llm_probe": {"ok": True, "meta": {"cached": False}},
                    },
                },
            )

    fake_client = _FakeWorkerClient()
    monkeypatch.setattr(readiness_obs, "get_worker_client", lambda: fake_client)

    first = client.get("/ready")
    clock["value"] = 1005.0
    second = client.get("/ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake_client.calls == 1
    assert first.json()["checks"]["llm_probe"]["meta"]["cached"] is False
    assert second.json()["checks"]["llm_probe"]["meta"]["cached"] is True


def test_ready_refresh_true_bypasses_cache(client, monkeypatch) -> None:
    asyncio.run(readiness_obs.reset_llm_probe_cache())
    _install_ready_settings(monkeypatch, ttl_seconds=30)
    clock = {"value": 2000.0}
    monkeypatch.setattr(readiness_obs, "_monotonic", lambda: clock["value"])

    class _FakeWorkerClient:
        def __init__(self) -> None:
            self.calls = 0

        async def probe_ready(self, *, refresh: bool = False):  # noqa: ANN201
            del refresh
            self.calls += 1
            return (
                200,
                {
                    "status": "ready",
                    "checks": {
                        "llm_probe": {"ok": True, "meta": {"cached": False}},
                    },
                },
            )

    fake_client = _FakeWorkerClient()
    monkeypatch.setattr(readiness_obs, "get_worker_client", lambda: fake_client)

    first = client.get("/ready")
    clock["value"] = 2001.0
    second = client.get("/ready?refresh=true")

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake_client.calls == 2
    assert first.json()["checks"]["llm_probe"]["meta"]["cached"] is False
    assert second.json()["checks"]["llm_probe"]["meta"]["cached"] is False


def test_ready_cache_expires_after_ttl(client, monkeypatch) -> None:
    asyncio.run(readiness_obs.reset_llm_probe_cache())
    _install_ready_settings(monkeypatch, ttl_seconds=10)
    clock = {"value": 3000.0}
    monkeypatch.setattr(readiness_obs, "_monotonic", lambda: clock["value"])

    class _FakeWorkerClient:
        def __init__(self) -> None:
            self.calls = 0

        async def probe_ready(self, *, refresh: bool = False):  # noqa: ANN201
            del refresh
            self.calls += 1
            return (
                200,
                {
                    "status": "ready",
                    "checks": {
                        "llm_probe": {"ok": True, "meta": {"cached": False}},
                    },
                },
            )

    fake_client = _FakeWorkerClient()
    monkeypatch.setattr(readiness_obs, "get_worker_client", lambda: fake_client)

    first = client.get("/ready")
    clock["value"] = 3011.0
    second = client.get("/ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake_client.calls == 2
    assert first.json()["checks"]["llm_probe"]["meta"]["cached"] is False
    assert second.json()["checks"]["llm_probe"]["meta"]["cached"] is False


def test_ready_response_contains_x_request_id(client, monkeypatch) -> None:
    monkeypatch.setattr(readiness_obs, "check_db", _async_check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_probe", _async_check(ok=True))

    response = client.get("/ready")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_ready_uses_worker_probe(client, monkeypatch) -> None:
    asyncio.run(readiness_obs.reset_llm_probe_cache())
    _install_ready_settings(monkeypatch, ttl_seconds=30)
    monkeypatch.setattr(readiness_obs, "check_db", _async_check(ok=True))

    class _FakeWorkerClient:
        async def probe_ready(self, *, refresh: bool = False):  # noqa: ANN001, ANN201
            del refresh
            return (
                200,
                {
                    "status": "ready",
                    "checks": {
                        "llm_probe": {"ok": True, "meta": {"cached": False}},
                    },
                },
            )

    monkeypatch.setattr(readiness_obs, "get_worker_client", lambda: _FakeWorkerClient())
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["llm_config"]["meta"]["gateway_mode"] == "worker"


def test_ready_persists_backend_probe_events(client, monkeypatch) -> None:
    monkeypatch.setattr(readiness_obs, "check_db", _async_check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True))
    monkeypatch.setattr(
        readiness_obs,
        "check_llm_probe",
        _async_check(ok=False, error_code="llm_probe_timeout", message="timed out"),
    )

    failed = client.get("/ready")
    assert failed.status_code == 503

    monkeypatch.setattr(readiness_obs, "check_llm_probe", _async_check(ok=True))
    success = client.get("/ready")
    assert success.status_code == 200

    with DBSession(engine) as db:
        events = list(
            db.exec(
                select(ReadinessProbeEvent)
                .where(ReadinessProbeEvent.service == "backend")
                .order_by(ReadinessProbeEvent.created_at)
            ).all()
        )
    assert len(events) >= 2
    assert events[-2].ok is False
    assert events[-2].error_code == "llm_probe_timeout"
    assert events[-1].ok is True
