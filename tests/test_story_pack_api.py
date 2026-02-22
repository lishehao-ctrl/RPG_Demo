import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import session as db_session
from app.db.models import Story
from app.main import app
from tests.support.db_runtime import prepare_sqlite_db

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "stories.db")


def _pack() -> dict:
    return {
        "story_id": "campus_life",
        "version": 1,
        "title": "Campus Life",
        "start_node_id": "n1",
        "characters": [{"id": "alice", "name": "Alice"}],
        "initial_state": {"flags": {}},
        "default_fallback": {
            "id": "fb_default",
            "action": {"action_id": "rest", "params": {}},
            "next_node_id_policy": "stay",
            "text_variants": {"DEFAULT": "You pause and regain composure.", "FALLBACK": "You pause."},
        },
        "nodes": [
            {
                "node_id": "n1",
                "scene_brief": "Morning",
                "is_end": False,
                "choices": [
                    {
                        "choice_id": "c1",
                        "display_text": "Study",
                        "action": {"action_id": "study", "params": {}},
                        "next_node_id": "n2",
                        "effects": {"knowledge": 3, "energy": -1},
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c2",
                        "display_text": "Work",
                        "action": {"action_id": "work", "params": {}},
                        "next_node_id": "n2",
                        "is_key_decision": False,
                    },
                ],
            },
            {
                "node_id": "n2",
                "scene_brief": "Evening",
                "is_end": True,
                "choices": [
                    {
                        "choice_id": "c3",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": "n2",
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c4",
                        "display_text": "Date",
                        "action": {"action_id": "date", "params": {"target": "alice"}},
                        "next_node_id": "n2",
                        "is_key_decision": True,
                    },
                ],
            },
        ],
        "fallback_executors": [
            {
                "id": "fb_global",
                "action_id": "rest",
                "action_params": {},
                "effects": {"energy": 1},
                "next_node_id": "n1",
            }
        ],
        "global_fallback_choice_id": "fb_global",
    }


def test_validate_rejects_dangling_next_node(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["nodes"][0]["choices"][0]["next_node_id"] = "missing"

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DANGLING_NEXT_NODE:c1->missing" in resp.json()["errors"]


def test_validate_rejects_duplicate_choice_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["nodes"][1]["choices"][0]["choice_id"] = "c1"

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DUPLICATE_CHOICE_ID:c1" in resp.json()["errors"]


def test_validate_rejects_is_fallback_field_hard_cut(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["nodes"][0]["choices"][0]["is_fallback"] = True

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 422


def test_validate_rejects_legacy_reason_keys_hard_cut(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["default_fallback"]["text_variants"] = {"UNSUPPORTED_REASON": "legacy text"}

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 422


def test_validate_rejects_window_effects_hard_cut(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["nodes"][0]["choices"][0]["effects"] = {"money": [1, 3]}

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 422

    pack2 = _pack()
    pack2["nodes"][0]["choices"][0]["effects"] = {"money": {"min": 1, "max": 3}}
    resp2 = client.post("/stories/validate", json=pack2)
    assert resp2.status_code == 422


def test_validate_rejects_missing_non_end_fallback_coverage(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack.pop("default_fallback")
    pack.pop("global_fallback_choice_id")
    pack.pop("fallback_executors")

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "MISSING_NODE_FALLBACK:n1" in resp.json()["errors"]


def test_validate_optional_packwide_fallback_id_uniqueness(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["nodes"][0]["fallback"] = {
        "id": "fb_default",
        "action": {"action_id": "rest", "params": {}},
        "next_node_id_policy": "stay",
    }

    original = settings.story_fallback_id_unique_packwide
    settings.story_fallback_id_unique_packwide = True
    try:
        resp = client.post("/stories/validate", json=pack)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
        assert "DUPLICATE_FALLBACK_ID:fb_default" in resp.json()["errors"]
    finally:
        settings.story_fallback_id_unique_packwide = original


def test_store_and_fetch_story_pack_roundtrip_keeps_raw_pack(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()

    store = client.post("/stories", json=pack)
    assert store.status_code == 200

    got = client.get("/stories/campus_life", params={"version": 1})
    assert got.status_code == 200
    assert got.json()["pack"] == pack

    with db_session.SessionLocal() as db:
        row = db.execute(select(Story).where(Story.story_id == "campus_life", Story.version == 1)).scalar_one()
        assert row.pack_json == pack


def test_publish_and_fetch_published_version(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    p1 = _pack()
    p2 = _pack()
    p2["version"] = 2
    p2["title"] = "Campus Life v2"

    assert client.post("/stories", json=p1).status_code == 200
    assert client.post("/stories", json=p2).status_code == 200

    pub = client.post("/stories/campus_life/publish", params={"version": 2})
    assert pub.status_code == 200
    assert pub.json()["published_version"] == 2

    got = client.get("/stories/campus_life")
    assert got.status_code == 200
    assert got.json()["version"] == 2
    assert got.json()["pack"]["title"] == "Campus Life v2"


def test_list_stories_defaults_to_published_playable_only(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    pack = _pack()
    assert client.post("/stories", json=pack).status_code == 200
    assert client.post("/stories/campus_life/publish", params={"version": 1}).status_code == 200

    with db_session.SessionLocal() as db:
        with db.begin():
            db.add(
                Story(
                    story_id="broken_story",
                    version=1,
                    is_published=True,
                    pack_json={"story_id": "broken_story", "version": 1, "title": "Broken"},
                    created_at=datetime.now(timezone.utc),
                )
            )

    listed = client.get("/stories")
    assert listed.status_code == 200
    rows = listed.json()["stories"]
    assert any(row["story_id"] == "campus_life" for row in rows)
    assert all(row["story_id"] != "broken_story" for row in rows)

    listed_all = client.get("/stories", params={"playable_only": "false"})
    assert listed_all.status_code == 200
    by_id = {row["story_id"]: row for row in listed_all.json()["stories"]}
    assert by_id["campus_life"]["is_playable"] is True
    assert by_id["broken_story"]["is_playable"] is False


def test_publish_rejects_invalid_story_pack(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    with db_session.SessionLocal() as db:
        with db.begin():
            db.add(
                Story(
                    story_id="invalid_publish_story",
                    version=1,
                    is_published=False,
                    pack_json={"story_id": "invalid_publish_story", "version": 1},
                    created_at=datetime.now(timezone.utc),
                )
            )

    publish = client.post("/stories/invalid_publish_story/publish", params={"version": 1})
    assert publish.status_code == 400
    detail = publish.json()["detail"]
    assert detail["code"] == "STORY_INVALID_FOR_PUBLISH"
    assert isinstance(detail.get("errors"), list)
    assert detail["errors"]


def test_validate_accepts_valid_quests_schema(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["quests"] = [
        {
            "quest_id": "q_study",
            "title": "First Study",
            "description": "Complete one study action.",
            "auto_activate": True,
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Opening",
                    "milestones": [
                        {
                            "milestone_id": "m_study_c1",
                            "title": "Study once",
                            "when": {"executed_choice_id_is": "c1"},
                            "rewards": {"knowledge": 1},
                        }
                    ],
                    "stage_rewards": {"money": 1},
                }
            ],
            "completion_rewards": {"money": 2},
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_validate_rejects_dangling_quest_trigger_node(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["quests"] = [
        {
            "quest_id": "q_bad_node",
            "title": "Invalid Node Trigger",
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Only Stage",
                    "milestones": [
                        {
                            "milestone_id": "m1",
                            "title": "Impossible milestone",
                            "when": {"node_id_is": "missing_node"},
                        }
                    ],
                }
            ],
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DANGLING_QUEST_TRIGGER_NODE:q_bad_node:s1:m1:missing_node" in resp.json()["errors"]


def test_validate_rejects_dangling_quest_executed_choice(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["quests"] = [
        {
            "quest_id": "q_bad_choice",
            "title": "Invalid Choice Trigger",
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Only Stage",
                    "milestones": [
                        {
                            "milestone_id": "m1",
                            "title": "Impossible milestone",
                            "when": {"executed_choice_id_is": "c_missing"},
                        }
                    ],
                }
            ],
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DANGLING_QUEST_TRIGGER_EXECUTED_CHOICE:q_bad_choice:s1:m1:c_missing" in resp.json()["errors"]


def test_validate_rejects_duplicate_stage_id_within_quest(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["quests"] = [
        {
            "quest_id": "q_dup_stage",
            "title": "Duplicate Stage",
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Stage 1",
                    "milestones": [{"milestone_id": "m1", "title": "One", "when": {}}],
                },
                {
                    "stage_id": "s1",
                    "title": "Stage 1 Again",
                    "milestones": [{"milestone_id": "m2", "title": "Two", "when": {}}],
                },
            ],
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DUPLICATE_QUEST_STAGE_ID:q_dup_stage:s1" in resp.json()["errors"]


def test_validate_rejects_duplicate_milestone_id_within_stage(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["quests"] = [
        {
            "quest_id": "q_dup_milestone",
            "title": "Duplicate Milestone",
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Stage 1",
                    "milestones": [
                        {"milestone_id": "m1", "title": "One", "when": {}},
                        {"milestone_id": "m1", "title": "One Again", "when": {}},
                    ],
                }
            ],
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DUPLICATE_QUEST_STAGE_MILESTONE_ID:q_dup_milestone:s1:m1" in resp.json()["errors"]


def test_validate_accepts_events_endings_and_run_config(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["run_config"] = {"max_days": 5, "max_steps": 12, "default_timeout_outcome": "fail"}
    pack["events"] = [
        {
            "event_id": "ev_library_bonus",
            "title": "Library Bonus",
            "weight": 2,
            "once_per_run": True,
            "cooldown_steps": 1,
            "trigger": {"node_id_is": "n1", "day_in": [1], "slot_in": ["morning"]},
            "effects": {"knowledge": 1},
            "narration_hint": "A quiet insight appears.",
        }
    ]
    pack["endings"] = [
        {
            "ending_id": "end_success",
            "title": "Good Ending",
            "priority": 10,
            "outcome": "success",
            "trigger": {"node_id_is": "n2", "knowledge_at_least": 1},
            "epilogue": "You close the week with confidence.",
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_validate_rejects_duplicate_event_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["events"] = [
        {
            "event_id": "ev_dup",
            "title": "First",
            "trigger": {"node_id_is": "n1"},
        },
        {
            "event_id": "ev_dup",
            "title": "Second",
            "trigger": {"node_id_is": "n2"},
        },
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DUPLICATE_EVENT_ID:ev_dup" in resp.json()["errors"]


def test_validate_rejects_duplicate_ending_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["endings"] = [
        {
            "ending_id": "end_dup",
            "title": "Ending A",
            "outcome": "neutral",
            "trigger": {"node_id_is": "n2"},
            "epilogue": "A",
        },
        {
            "ending_id": "end_dup",
            "title": "Ending B",
            "outcome": "fail",
            "trigger": {"node_id_is": "n2"},
            "epilogue": "B",
        },
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DUPLICATE_ENDING_ID:end_dup" in resp.json()["errors"]


def test_validate_rejects_dangling_event_trigger_node(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["events"] = [
        {
            "event_id": "ev_bad_node",
            "title": "Bad Event",
            "trigger": {"node_id_is": "missing_node"},
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DANGLING_EVENT_TRIGGER_NODE:ev_bad_node:missing_node" in resp.json()["errors"]


def test_validate_rejects_dangling_ending_trigger_node(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["endings"] = [
        {
            "ending_id": "end_bad_node",
            "title": "Bad Ending",
            "outcome": "neutral",
            "trigger": {"node_id_is": "missing_node"},
            "epilogue": "Nope",
        }
    ]

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert "DANGLING_ENDING_TRIGGER_NODE:end_bad_node:missing_node" in resp.json()["errors"]


def test_sample_storypack_campus_week_v1_is_valid(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    sample_path = ROOT / "examples" / "storypacks" / "campus_week_v1.json"
    pack = json.loads(sample_path.read_text(encoding="utf-8"))

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
