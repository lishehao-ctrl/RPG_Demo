from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient

from rpg_backend.main import app
from tests.helpers.route_paths import (
    READY_PATH,
    admin_http_health_path,
    admin_llm_call_health_path,
    admin_readiness_health_path,
    admin_runtime_errors_path,
    admin_session_feedback_path,
    admin_session_timeline_path,
    session_step_path,
    sessions_path,
    story_publish_path,
    stories_path,
)
from tests.helpers.providers import BarrierDeterministicProvider, DeterministicProvider, RouteFailureProvider

PACK_PATH = Path("sample_data/story_pack_v1.json")


def _bootstrap_story(client):
    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    created = client.post(stories_path(), json={"title": "Admin Session Story", "pack_json": pack})
    story_id = created.json()["story_id"]
    published = client.post(story_publish_path(story_id), json={})
    version = published.json()["version"]
    return story_id, version


def _create_session(client, monkeypatch) -> str:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    story_id, version = _bootstrap_story(client)
    session_resp = client.post(sessions_path(), json={"story_id": story_id, "version": version})
    assert session_resp.status_code == 200
    return session_resp.json()["session_id"]


def test_admin_timeline_contains_started_and_succeeded_events(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    session_id = _create_session(client, monkeypatch)
    step = client.post(
        session_step_path(session_id),
        json={
            "client_action_id": "admin-step-1",
            "input": {"type": "text", "text": "help me progress"},
            "dev_mode": False,
        },
    )
    assert step.status_code == 200

    timeline = client.get(admin_session_timeline_path(session_id))
    assert timeline.status_code == 200
    body = timeline.json()
    event_types = [event["event_type"] for event in body["events"]]
    assert "step_started" in event_types
    assert "step_succeeded" in event_types


def test_admin_timeline_contains_step_failed_on_openai_strict_error(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    session_id = _create_session(client, monkeypatch)
    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: RouteFailureProvider())

    step = client.post(
        session_step_path(session_id),
        json={
            "client_action_id": "admin-step-fail-1",
            "input": {"type": "text", "text": "nonsense"},
            "dev_mode": False,
        },
    )
    assert step.status_code == 503

    timeline = client.get(admin_session_timeline_path(session_id))
    assert timeline.status_code == 200
    failed_events = [event for event in timeline.json()["events"] if event["event_type"] == "step_failed"]
    assert failed_events
    assert failed_events[-1]["payload"]["error_code"] == "llm_route_failed"
    assert failed_events[-1]["payload"]["request_id"]
    assert "route_model" in failed_events[-1]["payload"]
    assert "narration_model" in failed_events[-1]["payload"]


def test_admin_timeline_contains_step_replayed_for_idempotent_call(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    session_id = _create_session(client, monkeypatch)
    payload = {
        "client_action_id": "admin-replay-1",
        "input": {"type": "text", "text": "help me progress"},
        "dev_mode": False,
    }
    first = client.post(session_step_path(session_id), json=payload)
    second = client.post(session_step_path(session_id), json=payload)
    assert first.status_code == 200
    assert second.status_code == 200

    timeline = client.get(admin_session_timeline_path(session_id))
    assert timeline.status_code == 200
    event_types = [event["event_type"] for event in timeline.json()["events"]]
    assert "step_replayed" in event_types


def test_admin_timeline_contains_step_conflicted_event(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    session_id = _create_session(client, monkeypatch)
    barrier = Barrier(2)
    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: BarrierDeterministicProvider(barrier))
    request_url = session_step_path(session_id)
    auth_headers = dict(client.headers)
    payloads = [
        {
            "client_action_id": "admin-conflict-a",
            "input": {"type": "text", "text": "advance A"},
            "dev_mode": False,
        },
        {
            "client_action_id": "admin-conflict-b",
            "input": {"type": "text", "text": "advance B"},
            "dev_mode": False,
        },
    ]

    def _post(payload: dict) -> int:
        with TestClient(app) as local_client:
            response = local_client.post(request_url, json=payload, headers=auth_headers)
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        status_codes = sorted([future.result() for future in [pool.submit(_post, payload) for payload in payloads]])

    assert status_codes == [200, 409]
    timeline = client.get(admin_session_timeline_path(session_id))
    assert timeline.status_code == 200
    conflicted_events = [event for event in timeline.json()["events"] if event["event_type"] == "step_conflicted"]
    assert conflicted_events
    assert conflicted_events[-1]["payload"]["note"] == "optimistic_write_conflict"
    assert conflicted_events[-1]["payload"]["request_id"]

    aggregated = client.get(f"{admin_runtime_errors_path()}?window_seconds=300&limit=20")
    assert aggregated.status_code == 200
    body = aggregated.json()
    assert body["failed_total"] == 0
    assert body["buckets"] == []


def test_admin_feedback_create_and_list(client, monkeypatch) -> None:
    session_id = _create_session(client, monkeypatch)
    created = client.post(
        admin_session_feedback_path(session_id),
        json={
            "verdict": "bad",
            "reason_tags": ["pacing", "choice_clarity"],
            "note": "midgame feels flat",
            "turn_index": 6,
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["session_id"] == session_id
    assert body["verdict"] == "bad"
    assert body["reason_tags"] == ["pacing", "choice_clarity"]
    assert body["turn_index"] == 6

    listed = client.get(admin_session_feedback_path(session_id))
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items
    assert items[0]["feedback_id"] == body["feedback_id"]


def test_admin_endpoints_return_404_for_missing_session(client) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    timeline = client.get(admin_session_timeline_path(missing))
    assert timeline.status_code == 404

    create_feedback = client.post(
        admin_session_feedback_path(missing),
        json={"verdict": "bad", "reason_tags": [], "note": "n/a"},
    )
    assert create_feedback.status_code == 404

    list_feedback = client.get(admin_session_feedback_path(missing))
    assert list_feedback.status_code == 404


def test_admin_runtime_errors_aggregate_endpoint(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    session_id = _create_session(client, monkeypatch)
    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: RouteFailureProvider())

    collected_request_ids: list[str] = []
    for index in range(1, 4):
        step = client.post(
            session_step_path(session_id),
            json={
                "client_action_id": f"admin-error-{index}",
                "input": {"type": "text", "text": f"noise-{index}"},
                "dev_mode": False,
            },
        )
        assert step.status_code == 503
        collected_request_ids.append(step.headers["X-Request-ID"])

    aggregated = client.get(f"{admin_runtime_errors_path()}?window_seconds=300&limit=20")
    assert aggregated.status_code == 200
    body = aggregated.json()
    assert body["started_total"] >= 3
    assert body["failed_total"] >= 3
    assert body["step_error_rate"] > 0
    assert body["buckets"]
    first = body["buckets"][0]
    assert first["error_code"] == "llm_route_failed"
    assert first["stage"] == "route"
    assert isinstance(first["model"], str)
    assert first["model"]
    assert first["sample_request_ids"]
    assert set(first["sample_request_ids"]).issubset(set(collected_request_ids))

    filtered = client.get(
        f"{admin_runtime_errors_path()}?window_seconds=300&limit=20&stage=route&error_code=llm_route_failed"
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["buckets"]
    assert all(bucket["error_code"] == "llm_route_failed" for bucket in filtered_body["buckets"])
    assert all(bucket["stage"] == "route" for bucket in filtered_body["buckets"])


def test_admin_http_health_endpoint(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    session_id = _create_session(client, monkeypatch)
    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: RouteFailureProvider())

    for index in range(1, 4):
        response = client.post(
            session_step_path(session_id),
            json={
                "client_action_id": f"http-health-{index}",
                "input": {"type": "text", "text": f"fail-{index}"},
                "dev_mode": False,
            },
        )
        assert response.status_code == 503

    aggregated = client.get(f"{admin_http_health_path()}?window_seconds=300")
    assert aggregated.status_code == 200
    body = aggregated.json()
    assert body["window_started_at"]
    assert body["window_ended_at"]
    assert body["total_requests"] >= 3
    assert body["failed_5xx"] >= 3
    assert body["error_rate"] > 0
    assert body["p95_ms"] is not None
    assert body["top_5xx_paths"]


def test_admin_llm_call_health_endpoint(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    session_id = _create_session(client, monkeypatch)

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    ok = client.post(
        session_step_path(session_id),
        json={
            "client_action_id": "llm-call-ok-1",
            "input": {"type": "text", "text": "progress"},
            "dev_mode": False,
        },
    )
    assert ok.status_code == 200

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: RouteFailureProvider())
    failed = client.post(
        session_step_path(session_id),
        json={
            "client_action_id": "llm-call-fail-1",
            "input": {"type": "text", "text": "bad input"},
            "dev_mode": False,
        },
    )
    assert failed.status_code == 503

    aggregated = client.get(f"{admin_llm_call_health_path()}?window_seconds=300")
    assert aggregated.status_code == 200
    body = aggregated.json()
    assert body["window_started_at"]
    assert body["window_ended_at"]
    assert body["total_calls"] >= 2
    assert body["failed_calls"] >= 1
    assert body["p95_ms"] is not None
    assert set(body["by_stage"].keys()) == {"route", "narration", "json", "unknown"}
    assert set(body["by_gateway_mode"].keys()) == {"worker", "unknown"}

    route_only = client.get(f"{admin_llm_call_health_path()}?window_seconds=300&stage=route")
    assert route_only.status_code == 200
    assert route_only.json()["total_calls"] >= 1

    local_filtered = client.get(f"{admin_llm_call_health_path()}?window_seconds=300&gateway_mode=local")
    assert local_filtered.status_code == 422


def test_admin_readiness_health_endpoint(client, monkeypatch) -> None:
    from rpg_backend.observability import readiness as readiness_obs

    def _ok_sync_check():
        return {
            "ok": True,
            "latency_ms": 1,
            "checked_at": "2026-03-01T00:00:00+00:00",
            "error_code": None,
            "message": None,
            "meta": {},
        }

    async def _ok_async_check():
        return _ok_sync_check()

    async def _failed_probe(*, refresh: bool = False):  # noqa: ARG001
        return {
            "ok": False,
            "latency_ms": 2,
            "checked_at": "2026-03-01T00:00:01+00:00",
            "error_code": "llm_probe_timeout",
            "message": "timeout",
            "meta": {"cached": False},
        }

    monkeypatch.setattr(readiness_obs, "check_db", _ok_async_check)
    monkeypatch.setattr(readiness_obs, "check_llm_config", _ok_sync_check)
    monkeypatch.setattr(readiness_obs, "check_llm_probe", _failed_probe)

    first = client.get(READY_PATH)
    second = client.get(READY_PATH)
    assert first.status_code == 503
    assert second.status_code == 503

    aggregated = client.get(f"{admin_readiness_health_path()}?window_seconds=300")
    assert aggregated.status_code == 200
    body = aggregated.json()
    assert body["window_started_at"]
    assert body["window_ended_at"]
    assert body["backend_ready_fail_count"] >= 2
    assert body["backend_fail_streak"] >= 2
    assert body["last_failures"]
