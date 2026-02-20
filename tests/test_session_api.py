import os
import subprocess
import sys
import uuid
import hashlib
import json
from datetime import datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text

from app.config import settings
from app.db import session as db_session
from app.db.models import ActionLog, Session as StorySession, SessionSnapshot, SessionStepIdempotency
from app.modules.llm.adapter import LLMRuntime
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> str:
    db_path = tmp_path / "session_api.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    runtime_url = f"sqlite+pysqlite:///{db_path}"
    db_session.rebind_engine(runtime_url)
    return runtime_url


def _enable_sqlite_fk_per_connection() -> None:
    @event.listens_for(db_session.engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _make_story_pack(story_id: str, version: int = 1) -> dict:
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "story_id": story_id,
        "version": version,
        "title": "Session API Story",
        "start_node_id": n1,
        "characters": [{"id": "alice", "name": "Alice"}],
        "initial_state": {"flags": {}},
        "default_fallback": {
            "id": "fb_default",
            "action": {"action_id": "rest", "params": {}},
            "next_node_id_policy": "stay",
            "text_variants": {"DEFAULT": "You pause and observe."},
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


def _publish_story(client: TestClient, story_id: str = "session_api_story", pack: dict | None = None) -> dict:
    pack = pack or _make_story_pack(story_id)
    assert client.post("/stories", json=pack).status_code == 200
    assert client.post(f"/stories/{story_id}/publish", params={"version": 1}).status_code == 200
    return pack


def _create_story_session(client: TestClient, story_id: str = "session_api_story") -> str:
    created = client.post("/sessions", json={"story_id": story_id})
    assert created.status_code == 200
    return created.json()["id"]


def _step_request_hash(*, choice_id: str | None, player_input: str | None) -> str:
    canonical = json.dumps(
        {"choice_id": choice_id, "player_input": player_input},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_create_session_requires_story_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    created = client.post("/sessions")
    assert created.status_code == 422


def test_create_and_get_session(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    got = client.get(f"/sessions/{sid}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "active"
    assert body["story_id"] == "session_api_story"
    assert isinstance(body["current_node_id"], str)
    assert body["current_node"] is not None
    assert body["current_node"]["id"] == body["current_node_id"]
    assert "user_id" not in body
    assert len(body["character_states"]) >= 1


def test_create_session_initializes_quest_state(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_story_pack("session_api_story_with_quest")
    pack["quests"] = [
        {
            "quest_id": "q1",
            "title": "Open Move",
            "auto_activate": True,
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Stage One",
                    "milestones": [
                        {
                            "milestone_id": "m1",
                            "title": "Pick c1",
                            "when": {"executed_choice_id_is": "c1"},
                            "rewards": {"money": 3},
                        }
                    ],
                }
            ],
            "completion_rewards": {"knowledge": 1},
        }
    ]
    _publish_story(client, story_id="session_api_story_with_quest", pack=pack)

    sid = _create_story_session(client, story_id="session_api_story_with_quest")
    got = client.get(f"/sessions/{sid}")
    assert got.status_code == 200
    quest_state = got.json()["state_json"].get("quest_state")
    assert isinstance(quest_state, dict)
    assert "q1" in (quest_state.get("active_quests") or [])
    q1 = (quest_state.get("quests") or {}).get("q1") or {}
    assert q1.get("current_stage_id") == "s1"


def test_create_session_initializes_run_state(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client, story_id="session_api_story_run_state")

    sid = _create_story_session(client, story_id="session_api_story_run_state")
    got = client.get(f"/sessions/{sid}")
    assert got.status_code == 200
    run_state = (got.json().get("state_json") or {}).get("run_state")
    assert isinstance(run_state, dict)
    assert run_state.get("step_index") == 0
    assert run_state.get("triggered_event_ids") == []
    assert run_state.get("event_cooldowns") == {}
    assert run_state.get("ending_id") is None
    assert run_state.get("ending_outcome") is None
    assert run_state.get("ended_at_step") is None
    assert run_state.get("fallback_count") == 0


def test_create_session_accepts_non_uuid_story_node_ids(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = {
        "story_id": "session_api_non_uuid_nodes",
        "version": 1,
        "title": "String Node Story",
        "start_node_id": "n_start",
        "characters": [{"id": "alice", "name": "Alice"}],
        "initial_state": {"flags": {}},
        "default_fallback": {
            "id": "fb_default",
            "action": {"action_id": "rest", "params": {}},
            "next_node_id_policy": "stay",
            "text_variants": {"DEFAULT": "You pause."},
        },
        "nodes": [
            {
                "node_id": "n_start",
                "scene_brief": "Start",
                "is_end": False,
                "choices": [
                    {
                        "choice_id": "c1",
                        "display_text": "Study",
                        "action": {"action_id": "study", "params": {}},
                        "next_node_id": "n_mid",
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c2",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": "n_mid",
                        "is_key_decision": False,
                    },
                ],
            },
            {
                "node_id": "n_mid",
                "scene_brief": "Mid",
                "is_end": True,
                "choices": [
                    {
                        "choice_id": "c3",
                        "display_text": "Work",
                        "action": {"action_id": "work", "params": {}},
                        "next_node_id": "n_mid",
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c4",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": "n_mid",
                        "is_key_decision": False,
                    },
                ],
            },
        ],
    }
    _publish_story(client, story_id="session_api_non_uuid_nodes", pack=pack)

    created = client.post("/sessions", json={"story_id": "session_api_non_uuid_nodes"})
    assert created.status_code == 200
    sid = created.json()["id"]

    got = client.get(f"/sessions/{sid}")
    assert got.status_code == 200
    assert got.json()["current_node_id"] == "n_start"
    assert got.json()["current_node"]["id"] == "n_start"
    assert (got.json().get("route_flags") or {}).get("story_node_id") == "n_start"


def test_snapshot_rollback_restores_exact_state(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)

    step1 = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step1.status_code == 200
    snap = client.post(f"/sessions/{sid}/snapshot")
    assert snap.status_code == 200
    snap_id = snap.json()["snapshot_id"]
    state_at_snapshot = client.get(f"/sessions/{sid}").json()

    step2 = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert step2.status_code == 200

    rb = client.post(f"/sessions/{sid}/rollback", params={"snapshot_id": snap_id})
    assert rb.status_code == 200

    state_after = client.get(f"/sessions/{sid}").json()

    assert state_after["current_node_id"] == state_at_snapshot["current_node_id"]
    assert state_after["character_states"] == state_at_snapshot["character_states"]


def test_snapshot_rollback_restores_quest_state(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_story_pack("session_api_story_quest_rb")
    pack["quests"] = [
        {
            "quest_id": "q1",
            "title": "First Study",
            "auto_activate": True,
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Stage One",
                    "milestones": [
                        {
                            "milestone_id": "m1",
                            "title": "Study once",
                            "when": {"executed_choice_id_is": "c1"},
                            "rewards": {"money": 4},
                        }
                    ],
                }
            ],
            "completion_rewards": {"knowledge": 2},
        }
    ]
    _publish_story(client, story_id="session_api_story_quest_rb", pack=pack)

    sid = _create_story_session(client, story_id="session_api_story_quest_rb")
    first_step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert first_step.status_code == 200
    snap = client.post(f"/sessions/{sid}/snapshot")
    assert snap.status_code == 200
    snap_id = snap.json()["snapshot_id"]
    state_at_snapshot = client.get(f"/sessions/{sid}").json()["state_json"]

    second_step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert second_step.status_code == 200
    rb = client.post(f"/sessions/{sid}/rollback", params={"snapshot_id": snap_id})
    assert rb.status_code == 200
    state_after = client.get(f"/sessions/{sid}").json()["state_json"]

    assert state_after.get("quest_state") == state_at_snapshot.get("quest_state")


def test_rollback_prunes_nodes_and_logs(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    snap_id = client.post(f"/sessions/{sid}/snapshot").json()["snapshot_id"]
    client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})

    with db_session.SessionLocal() as db:
        logs_before = db.execute(
            select(func.count()).select_from(ActionLog).where(ActionLog.session_id == uuid.UUID(sid))
        ).scalar_one()
    assert logs_before >= 3

    rb = client.post(f"/sessions/{sid}/rollback", params={"snapshot_id": snap_id})
    assert rb.status_code == 200

    with db_session.SessionLocal() as db:
        logs_after = db.execute(
            select(func.count()).select_from(ActionLog).where(ActionLog.session_id == uuid.UUID(sid))
        ).scalar_one()
    assert logs_after == 1


def test_rollback_trim_uses_snapshot_membership_not_timestamp_only(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    _enable_sqlite_fk_per_connection()
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert first.status_code == 200

    snap_id = client.post(f"/sessions/{sid}/snapshot").json()["snapshot_id"]

    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert second.status_code == 200
    with db_session.SessionLocal() as db:
        snap = db.get(SessionSnapshot, uuid.UUID(snap_id))
        cutoff = datetime.fromisoformat(snap.state_blob["cutoff_ts"])
        second_log = db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == uuid.UUID(sid))
            .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
        ).scalars().first()
        assert second_log is not None
        db.execute(
            text("UPDATE action_logs SET created_at=:cutoff WHERE id=:id"),
            {"cutoff": cutoff, "id": str(second_log.id)},
        )
        db.commit()

    rb = client.post(f"/sessions/{sid}/rollback", params={"snapshot_id": snap_id})
    assert rb.status_code == 200

    with db_session.SessionLocal() as db:
        logs_after = db.execute(
            select(func.count()).select_from(ActionLog).where(ActionLog.session_id == uuid.UUID(sid))
        ).scalar_one()
    assert logs_after == 1


def test_step_cost_payload_is_token_only(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200
    step_body = step.json()
    assert "affection_delta" not in step_body
    cost = step_body["cost"]
    assert set(cost.keys()) == {"tokens_in", "tokens_out", "provider"}
    assert step_body["run_ended"] is False
    assert step_body["ending_id"] is None
    assert step_body["ending_outcome"] is None


def test_end_session_response_has_no_route_type(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    end_resp = client.post(f"/sessions/{sid}/end")
    assert end_resp.status_code == 200
    body = end_resp.json()
    assert body["ended"] is True
    assert "replay_report_id" in body
    assert "route_type" not in body


def test_step_rejects_unknown_payload_field(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    step = client.post(f"/sessions/{sid}/step", json={"legacy_input": "legacy"})
    assert step.status_code == 422


def test_step_rejects_dual_choice_and_text_input(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    step = client.post(
        f"/sessions/{sid}/step",
        json={"choice_id": "c1", "player_input": "i choose study"},
    )
    assert step.status_code == 422
    assert step.json()["detail"]["code"] == "INPUT_CONFLICT"


def test_step_idempotency_replays_same_payload_without_duplicate_logs(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    headers = {"X-Idempotency-Key": "idem-step-1"}
    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers=headers)
    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()

    with db_session.SessionLocal() as db:
        log_count = db.execute(
            select(func.count()).select_from(ActionLog).where(ActionLog.session_id == uuid.UUID(sid))
        ).scalar_one()
        assert log_count == 1
        idem_row = db.execute(
            select(SessionStepIdempotency).where(
                SessionStepIdempotency.session_id == uuid.UUID(sid),
                SessionStepIdempotency.idempotency_key == "idem-step-1",
            )
        ).scalar_one_or_none()
        assert idem_row is not None
        assert idem_row.status == "succeeded"
        assert isinstance(idem_row.response_json, dict)


def test_step_idempotency_reused_key_with_different_payload_returns_409(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    headers = {"X-Idempotency-Key": "idem-step-2"}
    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers=headers)
    assert first.status_code == 200

    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c2"}, headers=headers)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_step_idempotency_in_progress_returns_409(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = _create_story_session(client)
    key = "idem-step-3"
    now = datetime.utcnow()
    with db_session.SessionLocal() as db:
        with db.begin():
            db.add(
                SessionStepIdempotency(
                    session_id=uuid.UUID(sid),
                    idempotency_key=key,
                    request_hash=_step_request_hash(choice_id="c1", player_input=None),
                    status="in_progress",
                    response_json=None,
                    error_code=None,
                    created_at=now,
                    updated_at=now,
                    expires_at=now,
                )
            )

    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers={"X-Idempotency-Key": key})
    assert step.status_code == 409
    assert step.json()["detail"]["code"] == "REQUEST_IN_PROGRESS"


def test_step_idempotency_failed_llm_unavailable_can_retry_same_key(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    from app.modules.session import service as session_service

    class _ToggleProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.fail = True

        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        ):
            self.calls += 1
            if self.fail:
                raise httpx.ReadTimeout("forced read timeout", request=httpx.Request("POST", "https://example.com"))
            return (
                {
                    "narrative_text": "[llm] recovered narrative",
                    "choices": [
                        {"id": "c1", "text": "Reply", "type": "dialog"},
                        {"id": "c2", "text": "Wait", "type": "action"},
                    ],
                },
                {
                    "provider": "fake",
                    "model": model,
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "latency_ms": 1,
                    "status": "success",
                    "error_message": None,
                },
            )

    runtime = LLMRuntime()
    provider = _ToggleProvider()
    runtime.providers["fake"] = provider

    original_primary = settings.llm_provider_primary
    original_fallbacks = list(settings.llm_provider_fallbacks)
    original_network_retries = settings.llm_retry_attempts_network
    original_llm_retries = settings.llm_max_retries
    original_deadline = settings.llm_total_deadline_s
    settings.llm_provider_primary = "fake"
    settings.llm_provider_fallbacks = []
    settings.llm_retry_attempts_network = 1
    settings.llm_max_retries = 1
    settings.llm_total_deadline_s = 1.0

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = _create_story_session(client)
        before = client.get(f"/sessions/{sid}").json()
        headers = {"X-Idempotency-Key": "idem-step-llm-unavailable"}
        first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers=headers)
        assert first.status_code == 503
        assert first.json()["detail"]["code"] == "LLM_UNAVAILABLE"

        after_failed = client.get(f"/sessions/{sid}").json()
        assert after_failed["current_node_id"] == before["current_node_id"]
        assert after_failed["state_json"] == before["state_json"]

        with db_session.SessionLocal() as db:
            idem_row = db.execute(
                select(SessionStepIdempotency).where(
                    SessionStepIdempotency.session_id == uuid.UUID(sid),
                    SessionStepIdempotency.idempotency_key == "idem-step-llm-unavailable",
                )
            ).scalar_one()
            assert idem_row.status == "failed"
            assert idem_row.error_code == "LLM_UNAVAILABLE"

            log_count = db.execute(
                select(func.count()).select_from(ActionLog).where(ActionLog.session_id == uuid.UUID(sid))
            ).scalar_one()
            assert log_count == 0

        provider.fail = False
        second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers=headers)
        assert second.status_code == 200

        with db_session.SessionLocal() as db:
            idem_row = db.execute(
                select(SessionStepIdempotency).where(
                    SessionStepIdempotency.session_id == uuid.UUID(sid),
                    SessionStepIdempotency.idempotency_key == "idem-step-llm-unavailable",
                )
            ).scalar_one()
            assert idem_row.status == "succeeded"
            assert idem_row.error_code is None
            assert isinstance(idem_row.response_json, dict)

            log_count = db.execute(
                select(func.count()).select_from(ActionLog).where(ActionLog.session_id == uuid.UUID(sid))
            ).scalar_one()
            assert log_count == 1
    finally:
        settings.llm_provider_primary = original_primary
        settings.llm_provider_fallbacks = original_fallbacks
        settings.llm_retry_attempts_network = original_network_retries
        settings.llm_max_retries = original_llm_retries
        settings.llm_total_deadline_s = original_deadline


def test_legacy_session_without_story_returns_story_required(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    _publish_story(client)

    sid = uuid.uuid4()
    with db_session.SessionLocal() as db:
        with db.begin():
            db.add(
                StorySession(
                    id=sid,
                    status="active",
                    current_node_id=None,
                    story_id=None,
                    story_version=None,
                    global_flags={},
                    route_flags={},
                    active_characters=[],
                    state_json={},
                    memory_summary="",
                )
            )

    step = client.post(f"/sessions/{sid}/step", json={"player_input": "hello"})
    assert step.status_code == 400
    assert step.json()["detail"]["code"] == "STORY_REQUIRED"
