import uuid
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session as db_session
from app.db.models import ActionLog, Branch, DialogueNode, Session, SessionCharacterState
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "integration.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


def test_step_applies_affection_and_selects_branch(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    sid = uuid.UUID(client.post("/sessions").json()["id"])

    # step once to create a current node to branch from
    first = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert first.status_code == 200
    current_node_id = uuid.UUID(first.json()["node_id"])

    # seed two branches for current node
    with db_session.SessionLocal() as db:
        sess = db.get(Session, sid)
        cs = db.execute(select(SessionCharacterState).where(SessionCharacterState.session_id == sid)).scalars().first()
        assert cs is not None
        b1 = Branch(
            from_node_id=current_node_id,
            priority=20,
            is_exclusive=True,
            is_default=False,
            route_type="romance",
            rule_expr={"op": "gte", "left": f"characters.{cs.character_id}.score_visible", "right": 55},
        )
        b2 = Branch(
            from_node_id=current_node_id,
            priority=0,
            is_exclusive=False,
            is_default=True,
            route_type="default",
            rule_expr={"op": "eq", "left": "flags.none", "right": True},
        )
        db.add_all([b1, b2])
        db.commit()

    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "please I love you"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["affection_delta"]) >= 1

    with db_session.SessionLocal() as db:
        node = db.get(DialogueNode, uuid.UUID(body["node_id"]))
        assert node is not None
        assert node.branch_decision["chosen_branch_id"] is not None

        log = db.execute(
            select(ActionLog).where(ActionLog.node_id == node.id)
        ).scalars().one()
        tags = set(log.classification["behavior_tags"])
        assert "kind" in tags
        assert "flirt" in tags
        assert len(log.affection_delta) >= 1
        assert len(log.matched_rules) >= 1
        assert len(log.branch_evaluation) == 2
        assert all("trace" in item for item in log.branch_evaluation)
