from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import event

from app.db import session as db_session

ROOT = Path(__file__).resolve().parents[2]


def prepare_sqlite_db(tmp_path: Path, filename: str) -> str:
    db_path = tmp_path / filename
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


def enable_sqlite_fk_per_connection() -> None:
    @event.listens_for(db_session.engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
