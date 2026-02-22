from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.support.db_runtime import prepare_sqlite_db


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "health.db")


def test_health(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
