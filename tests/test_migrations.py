import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REQUIRED_TABLES = {
    "users",
    "sessions",
    "session_snapshots",
    "characters",
    "session_character_state",
    "dialogue_nodes",
    "branches",
    "action_logs",
    "replay_reports",
    "llm_usage_logs",
    "audit_logs",
    "alembic_version",
}


def test_alembic_upgrade_head_smoke(tmp_path: Path) -> None:
    db_path = tmp_path / "migration_smoke.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"

    cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    proc = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()

    names = {r[0] for r in rows}
    missing = REQUIRED_TABLES - names
    assert not missing, f"Missing tables: {missing}"
