import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session as db_session
from app.db.models import ActionLog
from app.main import app
from tests.support.db_runtime import prepare_sqlite_db


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "integration.db")


def _make_story_pack(story_id: str, version: int = 1) -> dict:
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "story_id": story_id,
        "version": version,
        "title": "Step Integration Story",
        "start_node_id": n1,
        "characters": [{"id": "alice", "name": "Alice"}],
        "initial_state": {"flags": {}},
        "default_fallback": {
            "id": "fb_default",
            "action": {"action_id": "rest", "params": {}},
            "next_node_id_policy": "stay",
            "text_variants": {
                "NO_INPUT": "You pause before acting.",
                "BLOCKED": "You hold back and reassess.",
                "FALLBACK": "Your intention is unclear, so you wait.",
                "DEFAULT": "You wait for a better chance.",
            },
        },
        "nodes": [
            {
                "node_id": n1,
                "scene_brief": "Start",
                "is_end": False,
                "choices": [
                    {
                        "choice_id": "c1",
                        "display_text": "Study",
                        "action": {"action_id": "study", "params": {}},
                        "next_node_id": n2,
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c2",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": n2,
                        "is_key_decision": False,
                    },
                ],
            },
            {
                "node_id": n2,
                "scene_brief": "End",
                "is_end": True,
                "choices": [
                    {
                        "choice_id": "c3",
                        "display_text": "Work",
                        "action": {"action_id": "work", "params": {}},
                        "next_node_id": n2,
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c4",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": n2,
                        "is_key_decision": False,
                    },
                ],
            },
        ],
    }


def _publish_story(client: TestClient, story_id: str = "step_integration_story") -> None:
    pack = _make_story_pack(story_id)
    assert client.post("/stories", json=pack).status_code == 200
    assert client.post(f"/stories/{story_id}/publish", params={"version": 1}).status_code == 200


def _create_story_session(client: TestClient, story_id: str = "step_integration_story") -> str:
    out = client.post("/sessions", json={"story_id": story_id})
    assert out.status_code == 200
    return out.json()["id"]


def test_story_step_accepts_choice_and_text_inputs(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)

    by_choice = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert by_choice.status_code == 200
    body_choice = by_choice.json()
    assert body_choice["fallback_used"] is False
    assert body_choice["executed_choice_id"] == "c1"
    assert "affection_delta" not in body_choice

    by_text = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert by_text.status_code == 503
    assert by_text.json()["detail"]["code"] == "LLM_UNAVAILABLE"

    with db_session.SessionLocal() as db:
        logs = db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == uuid.UUID(sid))
            .order_by(ActionLog.created_at.asc(), ActionLog.id.asc())
        ).scalars().all()
        assert len(logs) >= 1
        assert logs[-1].fallback_used is False


def test_story_step_text_clear_input_maps_to_choice(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client, story_id="step_integration_story_text_map")

    sid = _create_story_session(client, story_id="step_integration_story_text_map")
    step = client.post(f"/sessions/{sid}/step", json={"player_input": "study"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is False
    assert body["executed_choice_id"] == "c1"


def test_story_step_empty_payload_maps_to_no_input_fallback(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    step = client.post(f"/sessions/{sid}/step", json={})
    assert step.status_code == 200
    assert step.json()["fallback_reason"] == "NO_INPUT"


def test_story_step_rejects_dual_choice_and_text_payload(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    step = client.post(
        f"/sessions/{sid}/step",
        json={"choice_id": "c1", "player_input": "study"},
    )
    assert step.status_code == 422
    assert step.json()["detail"]["code"] == "INPUT_CONFLICT"
