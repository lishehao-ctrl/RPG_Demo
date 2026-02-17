import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import session as db_session
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "stories.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
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


def test_validate_rejects_unknown_action_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()
    pack["nodes"][0]["choices"][0]["action"] = {"action_id": "dance", "params": {}}

    resp = client.post("/stories/validate", json=pack)
    assert resp.status_code == 422


def test_store_and_fetch_story_pack_roundtrip(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _pack()

    store = client.post("/stories", json=pack)
    assert store.status_code == 200

    got = client.get("/stories/campus_life", params={"version": 1})
    assert got.status_code == 200
    assert got.json()["pack"] == pack


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
