import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import func, select

from app.db import session as db_session
from app.db.models import Story
from tests.support.db_runtime import prepare_sqlite_db

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> str:
    return prepare_sqlite_db(tmp_path, "seed_script.db")


def test_seed_script_populates_and_publishes_default_story(tmp_path: Path) -> None:
    _prepare_db(tmp_path)

    env = os.environ.copy()
    env["DATABASE_URL"] = str(db_session.engine.url)

    first = subprocess.run(
        [sys.executable, "scripts/seed.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr

    second = subprocess.run(
        [sys.executable, "scripts/seed.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr

    with db_session.SessionLocal() as db:
        row = db.execute(
            select(Story).where(Story.story_id == "campus_week_v1", Story.version == 1)
        ).scalar_one_or_none()
        assert row is not None
        assert row.is_published is True

        count = db.execute(
            select(func.count()).select_from(Story).where(Story.story_id == "campus_week_v1", Story.version == 1)
        ).scalar_one()
        assert count == 1
