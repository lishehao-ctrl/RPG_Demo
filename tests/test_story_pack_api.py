import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import session as db_session
from app.db.models import Story
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "stories.db"
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
