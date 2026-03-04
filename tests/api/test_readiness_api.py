from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from rpg_backend.observability import readiness as readiness_obs


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


def _install_ready_settings(monkeypatch, *, ttl_seconds: int = 30, gateway_mode: str = "local") -> None:
    settings = SimpleNamespace(
        llm_gateway_mode=gateway_mode,
        llm_openai_base_url="https://probe.example/compatible-mode",
        llm_openai_api_key="test-key",
        llm_openai_model="model-default",
        llm_openai_route_model="",
        llm_openai_narration_model="",
        llm_openai_generator_model="",
        llm_worker_base_url="http://worker.internal",
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
    monkeypatch.setattr(readiness_obs, "check_db", lambda: _check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True, meta={"probe_model": "m"}))
    monkeypatch.setattr(
        readiness_obs,
        "check_llm_probe",
        lambda *, refresh=False: _check(ok=True, meta={"cached": False, "refresh": refresh}),
    )

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
        lambda: _check(ok=False, error_code="db_unavailable", message="db down"),
    )
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_probe", lambda *, refresh=False: _check(ok=True))

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["db"]["ok"] is False
    assert body["checks"]["db"]["error_code"] == "db_unavailable"


def test_ready_returns_503_when_llm_config_missing(client, monkeypatch) -> None:
    monkeypatch.setattr(readiness_obs, "check_db", lambda: _check(ok=True))
    monkeypatch.setattr(
        readiness_obs,
        "check_llm_config",
        lambda: _check(ok=False, error_code="llm_config_invalid", message="missing model"),
    )

    def _unexpected_probe(*, refresh: bool = False):  # noqa: ARG001
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
    monkeypatch.setattr(readiness_obs, "check_db", lambda: _check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True))
    monkeypatch.setattr(
        readiness_obs,
        "check_llm_probe",
        lambda *, refresh=False: _check(ok=False, error_code="llm_probe_timeout", message="timed out"),
    )

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["llm_probe"]["ok"] is False
    assert body["checks"]["llm_probe"]["error_code"] == "llm_probe_timeout"


def test_ready_uses_cached_llm_probe_within_ttl(client, monkeypatch) -> None:
    readiness_obs.reset_llm_probe_cache()
    _install_ready_settings(monkeypatch, ttl_seconds=30)
    clock = {"value": 1000.0}
    monkeypatch.setattr(readiness_obs, "_monotonic", lambda: clock["value"])

    calls: list[dict] = []

    def _fake_probe_request(*, base_url: str, api_key: str, probe_model: str, timeout_seconds: float) -> dict:
        calls.append(
            {
                "base_url": base_url,
                "api_key": api_key,
                "probe_model": probe_model,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"ok": True, "who": "readiness-probe"}

    monkeypatch.setattr(readiness_obs, "_perform_llm_probe_request", _fake_probe_request)

    first = client.get("/ready")
    clock["value"] = 1005.0
    second = client.get("/ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert first.json()["checks"]["llm_probe"]["meta"]["cached"] is False
    assert second.json()["checks"]["llm_probe"]["meta"]["cached"] is True


def test_ready_refresh_true_bypasses_cache(client, monkeypatch) -> None:
    readiness_obs.reset_llm_probe_cache()
    _install_ready_settings(monkeypatch, ttl_seconds=30)
    clock = {"value": 2000.0}
    monkeypatch.setattr(readiness_obs, "_monotonic", lambda: clock["value"])

    call_count = {"value": 0}

    def _fake_probe_request(*, base_url: str, api_key: str, probe_model: str, timeout_seconds: float) -> dict:  # noqa: ARG001
        call_count["value"] += 1
        return {"ok": True, "who": "readiness-probe"}

    monkeypatch.setattr(readiness_obs, "_perform_llm_probe_request", _fake_probe_request)

    first = client.get("/ready")
    clock["value"] = 2001.0
    second = client.get("/ready?refresh=true")

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count["value"] == 2
    assert first.json()["checks"]["llm_probe"]["meta"]["cached"] is False
    assert second.json()["checks"]["llm_probe"]["meta"]["cached"] is False


def test_ready_cache_expires_after_ttl(client, monkeypatch) -> None:
    readiness_obs.reset_llm_probe_cache()
    _install_ready_settings(monkeypatch, ttl_seconds=10)
    clock = {"value": 3000.0}
    monkeypatch.setattr(readiness_obs, "_monotonic", lambda: clock["value"])

    call_count = {"value": 0}

    def _fake_probe_request(*, base_url: str, api_key: str, probe_model: str, timeout_seconds: float) -> dict:  # noqa: ARG001
        call_count["value"] += 1
        return {"ok": True, "who": "readiness-probe"}

    monkeypatch.setattr(readiness_obs, "_perform_llm_probe_request", _fake_probe_request)

    first = client.get("/ready")
    clock["value"] = 3011.0
    second = client.get("/ready")

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count["value"] == 2
    assert first.json()["checks"]["llm_probe"]["meta"]["cached"] is False
    assert second.json()["checks"]["llm_probe"]["meta"]["cached"] is False


def test_ready_response_contains_x_request_id(client, monkeypatch) -> None:
    monkeypatch.setattr(readiness_obs, "check_db", lambda: _check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_config", lambda: _check(ok=True))
    monkeypatch.setattr(readiness_obs, "check_llm_probe", lambda *, refresh=False: _check(ok=True))

    response = client.get("/ready")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_ready_worker_mode_uses_worker_probe(client, monkeypatch) -> None:
    readiness_obs.reset_llm_probe_cache()
    _install_ready_settings(monkeypatch, ttl_seconds=30, gateway_mode="worker")
    monkeypatch.setattr(readiness_obs, "check_db", lambda: _check(ok=True))

    class _FakeWorkerClient:
        def probe_ready(self, *, refresh: bool = False):  # noqa: ANN001, ANN201
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
