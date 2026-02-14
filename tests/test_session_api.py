import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.db.models import ActionLog, DialogueNode
from app.db import session as db_session
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


def test_create_and_get_session(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    created = client.post("/sessions")
    assert created.status_code == 200
    sid = created.json()["id"]

    got = client.get(f"/sessions/{sid}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "active"
    assert body["token_budget_remaining"] == settings.session_token_budget_total
    assert len(body["character_states"]) >= 1


def test_snapshot_rollback_restores_exact_state(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    sid = client.post("/sessions").json()["id"]
    state_before = client.get(f"/sessions/{sid}").json()

    step1 = client.post(f"/sessions/{sid}/step", json={"input_text": "hello world"})
    assert step1.status_code == 200
    snap = client.post(f"/sessions/{sid}/snapshot")
    assert snap.status_code == 200
    snap_id = snap.json()["snapshot_id"]
    state_at_snapshot = client.get(f"/sessions/{sid}").json()

    step2 = client.post(f"/sessions/{sid}/step", json={"input_text": "second message"})
    assert step2.status_code == 200

    rb = client.post(f"/sessions/{sid}/rollback", params={"snapshot_id": snap_id})
    assert rb.status_code == 200

    state_after = client.get(f"/sessions/{sid}").json()

    assert state_after["current_node_id"] == step1.json()["node_id"]
    step_cost = step1.json()["cost"]["tokens_in"] + step1.json()["cost"]["tokens_out"]
    assert state_after["token_budget_remaining"] == state_before["token_budget_remaining"] - step_cost
    assert state_after["token_budget_used"] == step_cost
    assert state_after["character_states"] == state_at_snapshot["character_states"]


def test_rollback_prunes_nodes_and_logs(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    sid = client.post("/sessions").json()["id"]
    client.post(f"/sessions/{sid}/step", json={"input_text": "first"})
    snap_id = client.post(f"/sessions/{sid}/snapshot").json()["snapshot_id"]
    client.post(f"/sessions/{sid}/step", json={"input_text": "second"})
    client.post(f"/sessions/{sid}/step", json={"input_text": "third"})

    with db_session.SessionLocal() as db:
        nodes_before = db.execute(select(func.count()).select_from(DialogueNode)).scalar_one()
        logs_before = db.execute(select(func.count()).select_from(ActionLog)).scalar_one()
    assert nodes_before >= 3
    assert logs_before >= 3

    rb = client.post(f"/sessions/{sid}/rollback", params={"snapshot_id": snap_id})
    assert rb.status_code == 200

    with db_session.SessionLocal() as db:
        nodes_after = db.execute(select(func.count()).select_from(DialogueNode)).scalar_one()
        logs_after = db.execute(select(func.count()).select_from(ActionLog)).scalar_one()
    assert nodes_after == 1
    assert logs_after == 1


def test_token_budget_hard_limit(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    original_total = settings.session_token_budget_total
    settings.session_token_budget_total = 120
    client = TestClient(app)
    try:
        sid = client.post("/sessions").json()["id"]
        ok = None
        for _ in range(30):
            ok = client.post(f"/sessions/{sid}/step", json={"input_text": "abcd"})
            if ok.status_code == 409:
                break
            assert ok.status_code == 200

        assert ok is not None
        assert ok.status_code == 409
        assert ok.json()["detail"]["code"] == "TOKEN_BUDGET_EXCEEDED"
    finally:
        settings.session_token_budget_total = original_total
