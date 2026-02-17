import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import session as db_session

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "demo_ui.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


def test_demo_ui_smoke(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert "RPG Demo UI" in resp.text
