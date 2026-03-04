from __future__ import annotations

from fastapi.testclient import TestClient

from rpg_backend.llm_worker.main import app, service
from rpg_backend.llm_worker.route_paths import (
    WORKER_JSON_OBJECT_TASK_PATH,
    WORKER_RENDER_NARRATION_TASK_PATH,
    WORKER_ROUTE_INTENT_TASK_PATH,
)
from rpg_backend.llm_worker.schemas import (
    WorkerTaskJsonObjectResponse,
    WorkerTaskNarrationResponse,
    WorkerTaskRouteIntentResponse,
)


def test_worker_route_intent_uses_internal_path_and_v2_is_removed(monkeypatch) -> None:
    async def _fake_route_intent(_payload) -> WorkerTaskRouteIntentResponse:  # noqa: ANN001
        return WorkerTaskRouteIntentResponse(
            move_id="global.help_me_progress",
            args={},
            confidence=0.92,
            interpreted_intent="help me progress",
            model="test-model",
            attempts=1,
            retry_count=0,
            duration_ms=5,
        )

    monkeypatch.setattr(service, "route_intent", _fake_route_intent)
    with TestClient(app) as client:
        response = client.post(
            WORKER_ROUTE_INTENT_TASK_PATH,
            json={
                "scene_context": {"moves": [], "fallback_move": "global.help_me_progress"},
                "text": "help me progress",
                "model": "test-model",
                "temperature": 0.1,
                "max_retries": 1,
                "timeout_seconds": 2.0,
            },
        )
        assert response.status_code == 200
        assert response.json()["move_id"] == "global.help_me_progress"

        legacy = client.post(
            "/v2/llm/tasks/route-intent",
            json={
                "scene_context": {"moves": [], "fallback_move": "global.help_me_progress"},
                "text": "help me progress",
                "model": "test-model",
            },
        )
        assert legacy.status_code == 404


def test_worker_render_narration_uses_internal_path_and_v2_is_removed(monkeypatch) -> None:
    async def _fake_render_narration(_payload) -> WorkerTaskNarrationResponse:  # noqa: ANN001
        return WorkerTaskNarrationResponse(
            narration_text="narration ok",
            model="test-model",
            attempts=1,
            retry_count=0,
            duration_ms=5,
        )

    monkeypatch.setattr(service, "render_narration", _fake_render_narration)
    with TestClient(app) as client:
        response = client.post(
            WORKER_RENDER_NARRATION_TASK_PATH,
            json={
                "slots": {"echo": "x"},
                "style_guard": "neutral",
                "model": "test-model",
                "temperature": 0.1,
                "max_retries": 1,
                "timeout_seconds": 2.0,
            },
        )
        assert response.status_code == 200
        assert response.json()["narration_text"] == "narration ok"

        legacy = client.post(
            "/v2/llm/tasks/render-narration",
            json={
                "slots": {"echo": "x"},
                "style_guard": "neutral",
                "model": "test-model",
            },
        )
        assert legacy.status_code == 404


def test_worker_json_object_uses_internal_path_and_v2_is_removed(monkeypatch) -> None:
    async def _fake_json_object(_payload) -> WorkerTaskJsonObjectResponse:  # noqa: ANN001
        return WorkerTaskJsonObjectResponse(
            payload={"ok": True},
            model="test-model",
            attempts=1,
            retry_count=0,
            duration_ms=5,
        )

    monkeypatch.setattr(service, "json_object", _fake_json_object)
    with TestClient(app) as client:
        response = client.post(
            WORKER_JSON_OBJECT_TASK_PATH,
            json={
                "system_prompt": "return json",
                "user_prompt": "{\"ok\":true}",
                "model": "test-model",
                "temperature": 0.1,
                "max_retries": 1,
                "timeout_seconds": 2.0,
            },
        )
        assert response.status_code == 200
        assert response.json()["payload"] == {"ok": True}

        legacy = client.post(
            "/v2/llm/tasks/json-object",
            json={
                "system_prompt": "return json",
                "user_prompt": "{\"ok\":true}",
                "model": "test-model",
            },
        )
        assert legacy.status_code == 404
