import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import session as db_session
from app.db.models import ActionLog, LLMUsageLog
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "story_engine.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


def _make_pack(story_id: str = "s1", version: int = 1) -> dict:
    n1, n2, n3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "story_id": story_id,
        "version": version,
        "title": "Tiny Story",
        "start_node_id": n1,
        "characters": [{"id": "alice", "name": "Alice"}],
        "initial_state": {"flags": {}},
        "nodes": [
            {
                "node_id": n1,
                "scene_brief": "Start",
                "is_end": False,
                "choices": [
                    {"choice_id": "c1", "display_text": "Study", "action": {"action_id": "study", "params": {}}, "next_node_id": n2, "is_key_decision": False},
                    {"choice_id": "c2", "display_text": "Date", "action": {"action_id": "date", "params": {"target": "alice"}}, "next_node_id": n3, "is_key_decision": True},
                ],
            },
            {
                "node_id": n2,
                "scene_brief": "Middle",
                "is_end": False,
                "choices": [
                    {"choice_id": "c3", "display_text": "Work", "action": {"action_id": "work", "params": {}}, "next_node_id": n3, "is_key_decision": False},
                    {"choice_id": "c4", "display_text": "Rest", "action": {"action_id": "rest", "params": {}}, "next_node_id": n3, "is_key_decision": False},
                ],
            },
            {
                "node_id": n3,
                "scene_brief": "End",
                "is_end": True,
                "choices": [
                    {"choice_id": "c5", "display_text": "Rest", "action": {"action_id": "rest", "params": {}}, "next_node_id": n3, "is_key_decision": False},
                    {"choice_id": "c6", "display_text": "Work", "action": {"action_id": "work", "params": {}}, "next_node_id": n3, "is_key_decision": False},
                ],
            },
        ],
    }


def _publish_pack(client: TestClient, pack: dict) -> None:
    assert client.post("/stories", json=pack).status_code == 200
    assert client.post(f"/stories/{pack['story_id']}/publish", params={"version": pack["version"]}).status_code == 200


def test_story_session_advances_nodes_by_choice_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_adv", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_adv"}).json()["id"]
    state0 = client.get(f"/sessions/{sid}").json()
    assert state0["current_node_id"] == pack["start_node_id"]

    step1 = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step1.status_code == 200
    assert [c["id"] for c in step1.json()["choices"]] == ["c3", "c4"]

    state1 = client.get(f"/sessions/{sid}").json()
    assert state1["current_node_id"] == pack["nodes"][1]["node_id"]


def test_story_step_rejects_invalid_choice_for_node(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_invalid", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_invalid"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"choice_id": "c999"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "INVALID_CHOICE_FOR_NODE"


def test_story_step_player_input_maps_to_choice_or_clarifies(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_input", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_input"}).json()["id"]
    ok = client.post(f"/sessions/{sid}/step", json={"player_input": "study"})
    assert ok.status_code == 200
    assert [c["id"] for c in ok.json()["choices"]] == ["c3", "c4"]

    sid2 = client.post("/sessions", json={"story_id": "s_input"}).json()["id"]
    bad = client.post(f"/sessions/{sid2}/step", json={"player_input": "nonsense ???"})
    assert bad.status_code == 200
    assert "pick" in bad.json()["narrative_text"].lower()
    after = client.get(f"/sessions/{sid2}").json()
    assert after["current_node_id"] == pack["start_node_id"]


def test_replay_includes_story_path_and_key_decisions(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_replay", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_replay"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c2"})
    assert step.status_code == 200

    assert client.post(f"/sessions/{sid}/end").status_code == 200
    replay = client.get(f"/sessions/{sid}/replay")
    assert replay.status_code == 200
    payload = replay.json()
    assert "story_path" in payload
    assert payload["story_path"]
    assert payload["story_path"][0]["choice_id"] == "c2"
    assert payload["key_decisions"]


def test_story_step_returns_story_node_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_story_node", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_story_node"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200

    body = step.json()
    assert "story_node_id" in body
    assert body["story_node_id"] == pack["nodes"][1]["node_id"]
    assert body["node_id"]


def test_story_step_cost_reflects_narration_usage(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    original_table = {k: dict(v) for k, v in settings.llm_price_table.items()}
    original_primary = settings.llm_provider_primary
    settings.llm_provider_primary = "fake"
    settings.llm_price_table = {
        **settings.llm_price_table,
        "fake": {"input_per_1k": 1.0, "output_per_1k": 2.0},
    }

    try:
        client = TestClient(app)
        pack = _make_pack("s_story_cost", 1)
        _publish_pack(client, pack)

        sid = uuid.UUID(client.post("/sessions", json={"story_id": "s_story_cost"}).json()["id"])
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
        assert step.status_code == 200
        cost = step.json()["cost"]

        with db_session.SessionLocal() as db:
            rows = db.execute(
                select(LLMUsageLog).where(LLMUsageLog.session_id == sid)
            ).scalars().all()
            assert rows
            expected_tokens_in = sum(int(r.prompt_tokens or 0) for r in rows)
            expected_tokens_out = sum(int(r.completion_tokens or 0) for r in rows)
            expected_total_cost = round(sum(float(r.cost_estimate or 0.0) for r in rows), 6)
            latest_generate = db.execute(
                select(LLMUsageLog)
                .where(
                    LLMUsageLog.session_id == sid,
                    LLMUsageLog.operation == "generate",
                    LLMUsageLog.status == "success",
                )
                .order_by(LLMUsageLog.created_at.desc())
            ).scalars().first()

        assert latest_generate is not None
        assert cost["provider"] == latest_generate.provider
        assert cost["tokens_in"] == expected_tokens_in
        assert cost["tokens_out"] == expected_tokens_out
        assert round(float(cost["total_cost"]), 6) == expected_total_cost
    finally:
        settings.llm_provider_primary = original_primary
        settings.llm_price_table = original_table


def test_story_step_budget_skip_cost_is_zero_and_provider_none(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    original_total = settings.session_token_budget_total
    settings.session_token_budget_total = 1

    try:
        client = TestClient(app)
        pack = _make_pack("s_story_budget", 1)
        _publish_pack(client, pack)

        sid = uuid.UUID(client.post("/sessions", json={"story_id": "s_story_budget"}).json()["id"])
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
        assert step.status_code == 200
        assert step.json()["cost"] == {
            "provider": "none",
            "tokens_in": 0,
            "tokens_out": 0,
            "total_cost": 0,
        }

        with db_session.SessionLocal() as db:
            usage_rows = db.execute(
                select(LLMUsageLog).where(LLMUsageLog.session_id == sid)
            ).scalars().all()
            assert usage_rows == []
            log = db.execute(
                select(ActionLog)
                .where(ActionLog.session_id == sid)
                .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
            ).scalars().first()
            assert log is not None
            assert log.fallback_used is True
            assert "LLM_SKIPPED_BUDGET" in (log.fallback_reasons or [])
    finally:
        settings.session_token_budget_total = original_total
