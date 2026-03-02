from __future__ import annotations

import json
from pathlib import Path

from app.config.settings import get_settings
from app.llm.base import LLMProvider, RouteIntentResult

PACK_PATH = Path("sample_data/story_pack_v1.json")


def _bootstrap_story(client):
    pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    created = client.post("/stories", json={"title": "Session Story", "pack_json": pack})
    story_id = created.json()["story_id"]
    published = client.post(f"/stories/{story_id}/publish", json={})
    version = published.json()["version"]
    return story_id, version


def test_session_create_and_get(client) -> None:
    story_id, version = _bootstrap_story(client)

    created = client.post("/sessions", json={"story_id": story_id, "version": version})
    assert created.status_code == 200
    body = created.json()
    session_id = body["session_id"]
    assert body["scene_id"] == "sc1"

    fetched = client.get(f"/sessions/{session_id}?dev_mode=true")
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    assert fetched_body["session_id"] == session_id
    assert "state" in fetched_body


def test_step_is_idempotent_by_client_action_id(client) -> None:
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    payload = {
        "client_action_id": "action-1",
        "input": {"type": "text", "text": "random noise"},
        "dev_mode": False,
    }
    first = client.post(f"/sessions/{session_id}/step", json=payload)
    second = client.post(f"/sessions/{session_id}/step", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_step_tolerates_button_without_move_id(client) -> None:
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    payload = {
        "client_action_id": "shape-1",
        "input": {"type": "button"},
    }
    response = client.post(f"/sessions/{session_id}/step", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["recognized"]["move_id"] == "global.help_me_progress"


def test_step_tolerates_missing_or_invalid_input_shape(client) -> None:
    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    missing_input = client.post(
        f"/sessions/{session_id}/step",
        json={"client_action_id": "shape-2"},
    )
    assert missing_input.status_code == 200
    assert missing_input.json()["recognized"]["move_id"] in {
        "global.help_me_progress",
        "global.clarify",
    }

    invalid_type = client.post(
        f"/sessions/{session_id}/step",
        json={"client_action_id": "shape-3", "input": {"type": "nonsense", "text": ""}},
    )
    assert invalid_type.status_code == 200
    assert invalid_type.json()["recognized"]["move_id"] in {
        "global.help_me_progress",
        "global.clarify",
    }


def test_session_create_returns_503_when_openai_provider_misconfigured(client, monkeypatch) -> None:
    story_id, version = _bootstrap_story(client)
    monkeypatch.setenv("APP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("APP_LLM_OPENAI_BASE_URL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_API_KEY", "")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "")
    get_settings.cache_clear()

    response = client.post("/sessions", json={"story_id": story_id, "version": version})
    assert response.status_code == 503
    assert "llm provider misconfigured" in response.json()["detail"]
    get_settings.cache_clear()


def test_session_create_succeeds_when_only_route_model_configured(client, monkeypatch) -> None:
    story_id, version = _bootstrap_story(client)
    monkeypatch.setenv("APP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("APP_LLM_OPENAI_BASE_URL", "https://example.com/compatible-mode")
    monkeypatch.setenv("APP_LLM_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_ROUTE_MODEL", "route-only-model")
    monkeypatch.setenv("APP_LLM_OPENAI_NARRATION_MODEL", "")
    get_settings.cache_clear()

    response = client.post("/sessions", json={"story_id": story_id, "version": version})
    assert response.status_code == 200
    body = response.json()
    assert body["story_id"] == story_id
    assert body["version"] == version
    get_settings.cache_clear()


def test_session_create_succeeds_when_only_narration_model_configured(client, monkeypatch) -> None:
    story_id, version = _bootstrap_story(client)
    monkeypatch.setenv("APP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("APP_LLM_OPENAI_BASE_URL", "https://example.com/compatible-mode")
    monkeypatch.setenv("APP_LLM_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("APP_LLM_OPENAI_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_ROUTE_MODEL", "")
    monkeypatch.setenv("APP_LLM_OPENAI_NARRATION_MODEL", "narration-only-model")
    get_settings.cache_clear()

    response = client.post("/sessions", json={"story_id": story_id, "version": version})
    assert response.status_code == 200
    body = response.json()
    assert body["story_id"] == story_id
    assert body["version"] == version
    get_settings.cache_clear()


class _RouteFailureProvider(LLMProvider):
    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return True

    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        raise RuntimeError("route failed")

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class _LowConfidenceProvider(LLMProvider):
    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return True

    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.1,
            interpreted_intent=text or "unclear intent",
        )

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class _NarrationFailureProvider(LLMProvider):
    @property
    def runtime_failfast_on_narration_error(self) -> bool:
        return True

    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.9,
            interpreted_intent=text or "unclear intent",
        )

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        raise RuntimeError("narration failed")


class _InvalidMoveProvider(LLMProvider):
    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return True

    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        return RouteIntentResult(
            move_id="move.not.available",
            args={},
            confidence=0.95,
            interpreted_intent=text or "invalid move intent",
        )

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


def test_step_returns_503_when_provider_route_throws(client, monkeypatch) -> None:
    from app.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]
    before = client.get(f"/sessions/{session_id}?dev_mode=true").json()

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: _RouteFailureProvider())
    response = client.post(
        f"/sessions/{session_id}/step",
        json={
            "client_action_id": "route-fail-1",
            "input": {"type": "text", "text": "nonsense input"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["error_code"] == "llm_route_failed"
    assert body["stage"] == "route"
    assert body["provider"] == "openai"

    after = client.get(f"/sessions/{session_id}?dev_mode=true").json()
    assert after["scene_id"] == before["scene_id"]
    assert after["beat_progress"] == before["beat_progress"]
    assert after["state"] == before["state"]


def test_step_returns_503_on_low_confidence_for_openai_strict(client, monkeypatch) -> None:
    from app.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: _LowConfidenceProvider())
    response = client.post(
        f"/sessions/{session_id}/step",
        json={
            "client_action_id": "low-confidence-1",
            "input": {"type": "text", "text": "???"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["error_code"] == "llm_route_low_confidence"
    assert body["stage"] == "route"
    assert body["provider"] == "openai"


def test_step_returns_503_on_invalid_move_for_openai_strict(client, monkeypatch) -> None:
    from app.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: _InvalidMoveProvider())
    response = client.post(
        f"/sessions/{session_id}/step",
        json={
            "client_action_id": "invalid-move-1",
            "input": {"type": "text", "text": "use hidden move"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["error_code"] == "llm_route_invalid_move"
    assert body["stage"] == "route"
    assert body["provider"] == "openai"


def test_step_returns_503_when_narration_fails_for_openai_strict(client, monkeypatch) -> None:
    from app.api import sessions as sessions_api

    story_id, version = _bootstrap_story(client)
    session_resp = client.post("/sessions", json={"story_id": story_id, "version": version})
    session_id = session_resp.json()["session_id"]

    monkeypatch.setattr(sessions_api, "get_llm_provider", lambda: _NarrationFailureProvider())
    response = client.post(
        f"/sessions/{session_id}/step",
        json={
            "client_action_id": "narration-fail-1",
            "input": {"type": "text", "text": "help me progress"},
            "dev_mode": False,
        },
    )
    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["error_code"] == "llm_narration_failed"
    assert body["stage"] == "narration"
    assert body["provider"] == "openai"
