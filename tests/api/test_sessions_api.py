from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient
from sqlmodel import Session as DBSession
from sqlmodel import select

from rpg_backend.config.settings import get_settings
from rpg_backend.main import app
from rpg_backend.storage.engine import engine
from rpg_backend.storage.models import SessionAction
from tests.helpers.providers import (
    BarrierDeterministicProvider,
    DeterministicProvider,
    InvalidMoveProvider,
    LowConfidenceProvider,
    NarrationFailureProvider,
    RouteFailureProvider,
)

PACK_PATH = Path("sample_data/story_pack_v1.json")


def _bootstrap_story(client):
    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    created = client.post("/v2/stories", json={"title": "Session Story", "pack_json": pack})
    story_id = created.json()["story_id"]
    published = client.post(f"/v2/stories/{story_id}/publish", json={})
    version = published.json()["version"]
    return story_id, version


def _error_payload(response) -> dict:
    return response.json()["error"]


def _get_timeline_events(client, session_id: str) -> list[dict]:
    response = client.get(f"/v2/admin/sessions/{session_id}/timeline")
    assert response.status_code == 200
    return response.json()["events"]


def _get_last_event(events: list[dict], event_type: str) -> dict:
    filtered = [event for event in events if event["event_type"] == event_type]
    assert filtered, f"missing event type: {event_type}"
    return filtered[-1]


def _count_session_actions(session_id: str) -> int:
    with DBSession(engine) as db:
        stmt = select(SessionAction).where(SessionAction.session_id == session_id)
        return len(list(db.exec(stmt).all()))


def test_session_create_and_get(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    story_id, version = _bootstrap_story(client)

    created = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    assert created.status_code == 200
    body = created.json()
    session_id = body["session_id"]
    assert body["scene_id"] == "sc1"

    fetched = client.get(f"/v2/sessions/{session_id}?dev_mode=true")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["session_id"] == session_id
    assert "state" in fetched_body


def test_step_is_idempotent_by_client_action_id(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    payload = {
        "client_action_id": "action-1",
        "input": {"type": "text", "text": "random noise"},
        "dev_mode": False,
    }
    first = client.post(f"/v2/sessions/{session_id}/step", json=payload)
    second = client.post(f"/v2/sessions/{session_id}/step", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    events = _get_timeline_events(client, session_id)
    event_types = [event["event_type"] for event in events]
    assert "step_started" in event_types
    assert "step_succeeded" in event_types
    assert "step_replayed" in event_types
    started = _get_last_event(events, "step_started")
    succeeded = _get_last_event(events, "step_succeeded")
    replayed = _get_last_event(events, "step_replayed")
    assert started["payload"]["request_id"]
    assert "route_model" in started["payload"]
    assert "narration_model" in started["payload"]
    assert succeeded["payload"]["request_id"]
    assert "route_model" in succeeded["payload"]
    assert "narration_model" in succeeded["payload"]
    assert replayed["payload"]["request_id"]


def test_step_conflict_returns_409_and_preserves_single_commit(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    barrier = Barrier(2)
    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: BarrierDeterministicProvider(barrier))
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    request_url = f"/v2/sessions/{session_id}/step"
    payloads = [
        {
            "client_action_id": "concurrent-a",
            "input": {"type": "text", "text": "route A"},
            "dev_mode": False,
        },
        {
            "client_action_id": "concurrent-b",
            "input": {"type": "text", "text": "route B"},
            "dev_mode": False,
        },
    ]

    def _post(payload: dict) -> tuple[int, dict]:
        with TestClient(app) as local_client:
            response = local_client.post(request_url, json=payload)
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in [pool.submit(_post, payload) for payload in payloads]]

    status_codes = sorted([status_code for status_code, _ in results])
    assert status_codes == [200, 409]

    conflict_detail = next(body["error"] for status_code, body in results if status_code == 409)
    assert conflict_detail["code"] == "session_conflict_retry"
    assert conflict_detail["details"]["session_id"] == session_id
    assert conflict_detail["retryable"] is True
    assert (
        conflict_detail["details"]["actual_turn_index"]
        > conflict_detail["details"]["expected_turn_index"]
    )

    assert _count_session_actions(session_id) == 1
    events = _get_timeline_events(client, session_id)
    assert len([event for event in events if event["event_type"] == "step_succeeded"]) == 1
    conflicted = _get_last_event(events, "step_conflicted")
    assert conflicted["payload"]["note"] == "optimistic_write_conflict"
    assert conflicted["payload"]["request_id"]


def test_step_same_action_concurrent_requests_replay_without_500(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    barrier = Barrier(2)
    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: BarrierDeterministicProvider(barrier))
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]
    request_url = f"/v2/sessions/{session_id}/step"
    payload = {
        "client_action_id": "same-action-race",
        "input": {"type": "text", "text": "same action"},
        "dev_mode": False,
    }

    def _post() -> tuple[int, dict]:
        with TestClient(app) as local_client:
            response = local_client.post(request_url, json=payload)
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(_post)
        second_future = pool.submit(_post)
        first = first_future.result()
        second = second_future.result()

    assert first[0] == 200
    assert second[0] == 200
    assert first[1] == second[1]

    assert _count_session_actions(session_id) == 1
    events = _get_timeline_events(client, session_id)
    assert len([event for event in events if event["event_type"] == "step_succeeded"]) == 1
    assert len([event for event in events if event["event_type"] == "step_replayed"]) >= 1


def test_step_tolerates_button_without_move_id(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    payload = {
        "client_action_id": "shape-1",
        "input": {"type": "button"},
    }
    response = client.post(f"/v2/sessions/{session_id}/step", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recognized"]["move_id"] == "global.help_me_progress"


def test_step_tolerates_missing_or_invalid_input_shape(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    missing_input = client.post(
        f"/v2/sessions/{session_id}/step",
        json={"client_action_id": "shape-2"},
    )
    assert missing_input.status_code == 200
    assert missing_input.json()["recognized"]["move_id"] in {
        "global.help_me_progress",
        "global.clarify",
    }

    invalid_type = client.post(
        f"/v2/sessions/{session_id}/step",
        json={"client_action_id": "shape-3", "input": {"type": "nonsense", "text": ""}},
    )
    assert invalid_type.status_code == 200
    assert invalid_type.json()["recognized"]["move_id"] in {
        "global.help_me_progress",
        "global.clarify",
    }


def test_step_response_strict_shape_and_debug_only_in_dev_mode(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: DeterministicProvider())
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    normal = client.post(
        f"/v2/sessions/{session_id}/step",
        json={
            "client_action_id": "strict-shape-1",
            "input": {"type": "text", "text": "advance story"},
            "dev_mode": False,
        },
    )
    assert normal.status_code == 200
    normal_body = normal.json()
    assert set(normal_body["recognized"].keys()) == {
        "interpreted_intent",
        "move_id",
        "confidence",
        "route_source",
        "llm_duration_ms",
        "llm_gateway_mode",
    }
    assert set(normal_body["resolution"].keys()) == {"result", "costs_summary", "consequences_summary"}
    assert set(normal_body["ui"].keys()) == {"moves", "input_hint"}
    assert "debug" not in normal_body
    assert all(set(move.keys()) == {"move_id", "label", "risk_hint"} for move in normal_body["ui"]["moves"])

    dev = client.post(
        f"/v2/sessions/{session_id}/step",
        json={
            "client_action_id": "strict-shape-2",
            "input": {"type": "text", "text": "advance again"},
            "dev_mode": True,
        },
    )
    assert dev.status_code == 200
    dev_body = dev.json()
    assert "debug" in dev_body
    assert set(dev_body["debug"].keys()) == {
        "selected_move",
        "selected_outcome",
        "selected_strategy_style",
        "pressure_recoil_triggered",
        "stance_snapshot",
        "state",
        "beat_progress",
    }
    assert set(dev_body["debug"]["stance_snapshot"].keys()) == {
        "support",
        "oppose",
        "contested",
        "red_line_hits",
    }


def test_session_create_returns_503_when_openai_provider_misconfigured(client, monkeypatch) -> None:
    story_id, version = _bootstrap_story(client)
    monkeypatch.setenv("APP_LLM_OPENAI_BASE_URL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_API_KEY", "")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_ROUTE_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_NARRATION_MODEL", "")
    get_settings.cache_clear()

    response = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    assert response.status_code == 503
    err = _error_payload(response)
    assert err["code"] == "service_unavailable"
    assert "llm provider misconfigured" in err["message"]
    get_settings.cache_clear()


def test_session_create_succeeds_when_only_route_model_configured(client, monkeypatch) -> None:
    story_id, version = _bootstrap_story(client)
    monkeypatch.setenv("APP_LLM_OPENAI_BASE_URL", "https://example.com/compatible-mode")
    monkeypatch.setenv("APP_LLM_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_ROUTE_MODEL", "route-only-model")
    monkeypatch.setenv("APP_LLM_OPENAI_NARRATION_MODEL", "")
    get_settings.cache_clear()

    response = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    assert response.status_code == 200
    body = response.json()
    assert body["story_id"] == story_id
    assert body["version"] == version
    get_settings.cache_clear()


def test_session_create_succeeds_when_only_narration_model_configured(client, monkeypatch) -> None:
    story_id, version = _bootstrap_story(client)
    monkeypatch.setenv("APP_LLM_OPENAI_BASE_URL", "https://example.com/compatible-mode")
    monkeypatch.setenv("APP_LLM_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_ROUTE_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_NARRATION_MODEL", "narration-only-model")
    get_settings.cache_clear()

    response = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    assert response.status_code == 200
    body = response.json()
    assert body["story_id"] == story_id
    assert body["version"] == version
    get_settings.cache_clear()


def test_step_returns_503_when_provider_route_throws(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]
    before = client.get(f"/v2/sessions/{session_id}?dev_mode=true").json()

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: RouteFailureProvider())
    response = client.post(
        f"/v2/sessions/{session_id}/step",
        json={
            "client_action_id": "route-fail-1",
            "input": {"type": "text", "text": "nonsense input"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = _error_payload(response)
    assert body["code"] == "llm_route_failed"
    assert body["details"]["stage"] == "route"
    assert body["details"]["provider"] == "openai"
    request_id = response.headers["X-Request-ID"]

    after = client.get(f"/v2/sessions/{session_id}?dev_mode=true").json()
    assert after["scene_id"] == before["scene_id"]
    assert after["beat_progress"] == before["beat_progress"]
    assert after["state"] == before["state"]

    events = _get_timeline_events(client, session_id)
    failed = [event for event in events if event["event_type"] == "step_failed"]
    assert failed
    assert failed[-1]["payload"]["error_code"] == "llm_route_failed"
    assert failed[-1]["payload"]["request_id"] == request_id
    assert "route_model" in failed[-1]["payload"]
    assert "narration_model" in failed[-1]["payload"]


def test_step_returns_503_on_low_confidence_for_openai_strict(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: LowConfidenceProvider())
    response = client.post(
        f"/v2/sessions/{session_id}/step",
        json={
            "client_action_id": "low-confidence-1",
            "input": {"type": "text", "text": "???"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = _error_payload(response)
    assert body["code"] == "llm_route_low_confidence"
    assert body["details"]["stage"] == "route"
    assert body["details"]["provider"] == "openai"


def test_step_returns_503_on_invalid_move_for_openai_strict(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: InvalidMoveProvider())
    response = client.post(
        f"/v2/sessions/{session_id}/step",
        json={
            "client_action_id": "invalid-move-1",
            "input": {"type": "text", "text": "use hidden move"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = _error_payload(response)
    assert body["code"] == "llm_route_invalid_move"
    assert body["details"]["stage"] == "route"
    assert body["details"]["provider"] == "openai"


def test_step_returns_503_when_narration_fails_for_openai_strict(client, monkeypatch) -> None:
    from rpg_backend.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/v2/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: NarrationFailureProvider())
    response = client.post(
        f"/v2/sessions/{session_id}/step",
        json={
            "client_action_id": "narration-fail-1",
            "input": {"type": "text", "text": "help me progress"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = _error_payload(response)
    assert body["code"] == "llm_narration_failed"
    assert body["details"]["stage"] == "narration"
    assert body["details"]["provider"] == "openai"
