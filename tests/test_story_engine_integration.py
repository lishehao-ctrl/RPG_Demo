import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import session as db_session
from app.db.models import ActionLog, LLMUsageLog, Story
from app.main import app
from app.modules.llm.schemas import NarrativeOutput
from tests.support.story_narrative_assertions import (
    assert_no_internal_story_tokens,
    assert_no_system_error_style_phrases,
)

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "story_engine.db"
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
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


def _seed_story_pack_raw(story_id: str, version: int, pack: dict, is_published: bool = True) -> None:
    with db_session.SessionLocal() as db:
        with db.begin():
            db.add(
                Story(
                    story_id=story_id,
                    version=version,
                    is_published=is_published,
                    pack_json=pack,
                    created_at=datetime.utcnow(),
                )
            )


def _make_pack(
    story_id: str = "s1",
    version: int = 1,
    *,
    blocked_choice_requires: dict | None = None,
    node_fallback_choice_id: str | None = None,
    node_fallback_choice_requires: dict | None = None,
    include_global_executor: bool = False,
    node_intents: list[dict] | None = None,
    quests: list[dict] | None = None,
) -> dict:
    n1, n2, n3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    choice_c1 = {
        "choice_id": "c1",
        "display_text": "Study",
        "action": {"action_id": "study", "params": {}},
        "next_node_id": n2,
        "is_key_decision": False,
    }
    if blocked_choice_requires is not None:
        choice_c1["requires"] = blocked_choice_requires

    choice_c2 = {
        "choice_id": "c2",
        "display_text": "Rest",
        "action": {"action_id": "rest", "params": {}},
        "next_node_id": n2,
        "is_key_decision": False,
    }
    if node_fallback_choice_requires is not None:
        choice_c2["requires"] = node_fallback_choice_requires

    pack: dict = {
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
                "choices": [choice_c1, choice_c2],
                "intents": node_intents or [],
                "fallback": {
                    "id": "fb_n1",
                    "action": {"action_id": "rest", "params": {}},
                    "next_node_id_policy": "explicit_next",
                    "next_node_id": n2,
                    "text_variants": {
                        "NO_INPUT": "You hesitate and lose your timing.",
                        "BLOCKED": "That path is blocked for now, so you steady yourself.",
                        "FALLBACK": "Your intent is unclear, so you hold position.",
                        "DEFAULT": "You pause to reassess.",
                    },
                },
                "node_fallback_choice_id": node_fallback_choice_id,
            },
            {
                "node_id": n2,
                "scene_brief": "Middle",
                "is_end": False,
                "choices": [
                    {
                        "choice_id": "c3",
                        "display_text": "Work",
                        "action": {"action_id": "work", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c4",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                ],
                "fallback": {
                    "id": "fb_n2",
                    "action": {"action_id": "rest", "params": {}},
                    "next_node_id_policy": "explicit_next",
                    "next_node_id": n3,
                    "text_variants": {"DEFAULT": "You pause."},
                },
            },
            {
                "node_id": n3,
                "scene_brief": "End",
                "is_end": True,
                "choices": [
                    {
                        "choice_id": "c5",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c6",
                        "display_text": "Work",
                        "action": {"action_id": "work", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                ],
            },
        ],
    }
    if include_global_executor:
        pack["fallback_executors"] = [
            {
                "id": "fb_global",
                "action_id": "rest",
                "action_params": {},
                "effects": {"energy": 1},
                "prereq": {"min_energy": 999},
                "next_node_id": n2,
                "narration": {"skeleton": "You slow down and regroup."},
            }
        ]
        pack["global_fallback_choice_id"] = "fb_global"
    if quests is not None:
        pack["quests"] = quests
    return pack


def _publish_pack(client: TestClient, pack: dict) -> None:
    assert client.post("/stories", json=pack).status_code == 200
    assert client.post(f"/stories/{pack['story_id']}/publish", params={"version": pack["version"]}).status_code == 200


def _latest_action_log(session_id: str | uuid.UUID) -> ActionLog:
    sid = uuid.UUID(str(session_id))
    with db_session.SessionLocal() as db:
        log = db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == sid)
            .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
        ).scalars().first()
        assert log is not None
        return log


def _usage_operations_for_session(session_id: str | uuid.UUID) -> set[str]:
    sid = uuid.UUID(str(session_id))
    with db_session.SessionLocal() as db:
        rows = db.execute(
            select(LLMUsageLog.operation).where(LLMUsageLog.session_id == sid)
        ).all()
    return {str(row[0]) for row in rows if row and row[0] is not None}


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
    body = step1.json()
    assert body["executed_choice_id"] == "c1"
    assert body["resolved_choice_id"] == "c1"
    assert body["fallback_used"] is False
    assert body["fallback_reason"] is None
    assert set(body["cost"].keys()) == {"tokens_in", "tokens_out", "provider"}

    state1 = client.get(f"/sessions/{sid}").json()
    assert state1["current_node_id"] == pack["nodes"][1]["node_id"]


def test_story_step_invalid_choice_soft_falls_back_with_200(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_invalid", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_invalid"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"choice_id": "bad"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempted_choice_id"] == "bad"
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "FALLBACK"
    assert_no_internal_story_tokens(body["narrative_text"])
    assert_no_system_error_style_phrases(body["narrative_text"])


def test_story_step_player_input_no_match_falls_back_with_200(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_no_match", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_no_match"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "FALLBACK"
    assert_no_internal_story_tokens(body["narrative_text"])

    log = _latest_action_log(sid)
    assert "NO_MATCH" in list(log.fallback_reasons or []) or "LLM_PARSE_ERROR" in list(log.fallback_reasons or [])


def test_story_step_player_input_intent_alias_executes_visible_choice(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_intent_alias",
        1,
        node_intents=[
            {
                "intent_id": "INTENT_ASK_INFO",
                "alias_choice_id": "c1",
                "description": "Gather information before committing.",
                "patterns": ["ask around", "gather intel"],
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_intent_alias"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"player_input": "i want to gather intel first"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_used"] is False
    assert body["executed_choice_id"] == "c1"
    assert body["fallback_reason"] is None


def test_story_step_usage_logs_are_generate_only(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_usage_ops", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_usage_ops"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert step.status_code == 200

    operations = _usage_operations_for_session(sid)
    assert operations
    assert operations == {"generate"}


def test_story_step_no_input_maps_to_fallback_with_200(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_no_input", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_no_input"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "NO_INPUT"
    assert_no_internal_story_tokens(body["narrative_text"])


def test_story_step_parse_error_maps_to_fallback(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_parse_error", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _Runtime:
        def select_story_choice_with_fallback(self, *_args, **_kwargs):
            raise ValueError("forced parse error")

        def narrative_with_fallback(self, _db, *, prompt: str, session_id, step_id=None):
            return (
                NarrativeOutput(
                    narrative_text="[fallback] The scene advances quietly. Choose the next move.",
                    choices=[
                        {"id": "c1", "text": "Reply", "type": "dialog"},
                        {"id": "c2", "text": "Wait", "type": "action"},
                    ],
                ),
                True,
            )

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: _Runtime())

    sid = client.post("/sessions", json={"story_id": "s_parse_error"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "FALLBACK"
    assert_no_internal_story_tokens(body["narrative_text"])

    log = _latest_action_log(sid)
    assert "LLM_PARSE_ERROR" in list(log.fallback_reasons or [])


def test_story_step_prereq_blocked_prefers_node_fallback_choice(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_blocked_pref",
        1,
        blocked_choice_requires={"min_money": 999},
        node_fallback_choice_id="c2",
        include_global_executor=True,
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_blocked_pref"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "BLOCKED"
    assert body["executed_choice_id"] == "c2"


def test_story_step_rerouted_target_prereq_fail_degrades_without_second_reroute(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_blocked_degraded",
        1,
        blocked_choice_requires={"min_money": 999},
        node_fallback_choice_id="c2",
        node_fallback_choice_requires={"min_energy": 999},
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_blocked_degraded"}).json()["id"]
    state_before = client.get(f"/sessions/{sid}").json()

    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "BLOCKED"

    state_after = client.get(f"/sessions/{sid}").json()
    assert state_after["state_json"] == state_before["state_json"]
    assert state_after["current_node_id"] == state_before["current_node_id"]

    log = _latest_action_log(sid)
    markers = list(log.fallback_reasons or [])
    assert "REROUTE_LIMIT_REACHED_DEGRADED" in markers
    assert "REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED" in markers


def test_story_step_updates_quest_progress_and_rewards_once(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_quest_progress",
        1,
        quests=[
            {
                "quest_id": "q_first_study",
                "title": "First Study",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "Opening",
                        "milestones": [
                            {
                                "milestone_id": "m_c1",
                                "title": "Choose Study",
                                "when": {"executed_choice_id_is": "c1"},
                                "rewards": {"money": 4},
                            }
                        ],
                        "stage_rewards": {"knowledge": 2},
                    },
                    {
                        "stage_id": "s2",
                        "title": "Work Follow-up",
                        "milestones": [
                            {
                                "milestone_id": "m_c3",
                                "title": "Choose Work",
                                "when": {"executed_choice_id_is": "c3"},
                                "rewards": {"money": 1},
                            }
                        ],
                        "stage_rewards": {"affection": 1},
                    },
                ],
                "completion_rewards": {"money": 2},
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_quest_progress"}).json()["id"]
    state_before = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_before["money"] == 50
    assert state_before["knowledge"] == 0

    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert first.status_code == 200
    assert first.json()["fallback_used"] is False
    state_after_first = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_first["money"] == 54
    assert state_after_first["knowledge"] == 4

    quest_state = state_after_first.get("quest_state") or {}
    assert "q_first_study" in (quest_state.get("active_quests") or [])
    assert "q_first_study" not in (quest_state.get("completed_quests") or [])
    q1_state = (quest_state.get("quests") or {}).get("q_first_study") or {}
    assert q1_state.get("current_stage_id") == "s2"
    recent_event_types = [str(item.get("type")) for item in (quest_state.get("recent_events") or [])]
    assert "milestone_completed" in recent_event_types
    assert "stage_completed" in recent_event_types
    assert "stage_activated" in recent_event_types

    log = _latest_action_log(sid)
    quest_rules = [item for item in (log.matched_rules or []) if isinstance(item, dict) and item.get("type") == "quest_progress"]
    assert quest_rules

    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert second.status_code == 200
    state_after_second = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_second["money"] == 77
    assert state_after_second["knowledge"] == 4
    assert state_after_second["affection"] == 1
    quest_state_second = state_after_second.get("quest_state") or {}
    assert "q_first_study" in (quest_state_second.get("completed_quests") or [])

    third = client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"})
    assert third.status_code == 200
    state_after_third = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_third["money"] == 77


def test_story_fallback_step_can_advance_quest_from_fallback_flag(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_quest_fallback",
        1,
        quests=[
            {
                "quest_id": "q_fallback",
                "title": "Recover Composure",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "Fallback Stage",
                        "milestones": [
                            {
                                "milestone_id": "m_fallback_once",
                                "title": "Trigger one fallback",
                                "when": {"fallback_used_is": True},
                                "rewards": {"affection": 2},
                            }
                        ],
                    }
                ],
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_quest_fallback"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={})
    assert resp.status_code == 200
    assert resp.json()["fallback_used"] is True
    assert resp.json()["fallback_reason"] == "NO_INPUT"

    state_after = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after["affection"] == 2
    quest_state = state_after.get("quest_state") or {}
    assert "q_fallback" in (quest_state.get("completed_quests") or [])


def test_story_later_stage_trigger_does_not_fire_early(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_stage_order_guard",
        1,
        quests=[
            {
                "quest_id": "q_stage_guard",
                "title": "Order Matters",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "Open",
                        "milestones": [
                            {
                                "milestone_id": "m_open",
                                "title": "Choose c1 first",
                                "when": {"executed_choice_id_is": "c1"},
                            }
                        ],
                    },
                    {
                        "stage_id": "s2",
                        "title": "Then Work",
                        "milestones": [
                            {
                                "milestone_id": "m_work",
                                "title": "Choose c3",
                                "when": {"executed_choice_id_is": "c3"},
                            }
                        ],
                    },
                ],
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_stage_order_guard"}).json()["id"]
    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c2"})
    assert first.status_code == 200
    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert second.status_code == 200

    quest_state = client.get(f"/sessions/{sid}").json()["state_json"].get("quest_state") or {}
    q_state = (quest_state.get("quests") or {}).get("q_stage_guard") or {}
    assert q_state.get("current_stage_id") == "s1"
    s2 = ((q_state.get("stages") or {}).get("s2") or {})
    m_work = ((s2.get("milestones") or {}).get("m_work") or {})
    assert m_work.get("done") is False
    assert "q_stage_guard" not in (quest_state.get("completed_quests") or [])


def test_story_fallback_narrative_leak_guard(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_leak_guard", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _Runtime:
        def narrative_with_fallback(self, _db, *, prompt: str, session_id, step_id=None):
            if "fallback rewrite" in prompt.lower():
                return (
                    NarrativeOutput(
                        narrative_text="This leaks NO_MATCH and next_node_id.",
                        choices=[
                            {"id": "c1", "text": "Reply", "type": "dialog"},
                            {"id": "c2", "text": "Wait", "type": "action"},
                        ],
                    ),
                    True,
                )
            return (
                NarrativeOutput(
                    narrative_text="[llm] baseline",
                    choices=[
                        {"id": "c1", "text": "Reply", "type": "dialog"},
                        {"id": "c2", "text": "Wait", "type": "action"},
                    ],
                ),
                True,
            )

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: _Runtime())

    original_flag = settings.story_fallback_llm_enabled
    settings.story_fallback_llm_enabled = True
    try:
        sid = client.post("/sessions", json={"story_id": "s_leak_guard"}).json()["id"]
        resp = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["fallback_used"] is True
        assert_no_internal_story_tokens(body["narrative_text"])
    finally:
        settings.story_fallback_llm_enabled = original_flag


def test_story_step_inactive_session_returns_409_session_not_active(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_inactive_story", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_inactive_story"}).json()["id"]
    assert client.post(f"/sessions/{sid}/end").status_code == 200

    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 409
    assert step.json()["detail"]["code"] == "SESSION_NOT_ACTIVE"


def test_get_story_returns_raw_pack_json_wrapper_unchanged(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    raw_pack = _make_pack("s_raw", 1)
    raw_pack["nodes"][0]["fallback"]["text_variants"]["FALLBACK"] = {
        "en": "Fallback EN",
        "zh": "Fallback ZH",
    }
    _seed_story_pack_raw("s_raw", 1, raw_pack, is_published=True)

    got = client.get("/stories/s_raw", params={"version": 1})
    assert got.status_code == 200
    assert got.json()["pack"] == raw_pack


def test_replay_keeps_missed_routes_and_what_if_empty_lists(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_replay_contract", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_replay_contract"}).json()["id"]
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}).status_code == 200
    assert client.post(f"/sessions/{sid}/end").status_code == 200

    replay = client.get(f"/sessions/{sid}/replay")
    assert replay.status_code == 200
    body = replay.json()
    assert "missed_routes" in body
    assert "what_if" in body
    assert isinstance(body["missed_routes"], list)
    assert isinstance(body["what_if"], list)
    assert body["missed_routes"] == []
    assert body["what_if"] == []
