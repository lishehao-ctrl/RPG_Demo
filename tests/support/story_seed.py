from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from app.db import session as db_session
from app.db.models import Story


def seed_story_pack(*, pack: dict, is_published: bool = True) -> None:
    story_id = str(pack.get("story_id") or "").strip()
    version = int(pack.get("version") or 0)
    if not story_id or version <= 0:
        raise ValueError("pack must include valid story_id and version")

    now = datetime.now(timezone.utc)
    with db_session.SessionLocal() as db:
        with db.begin():
            existing = db.execute(
                select(Story).where(Story.story_id == story_id, Story.version == version)
            ).scalar_one_or_none()
            if existing is None:
                existing = Story(
                    story_id=story_id,
                    version=version,
                    is_published=False,
                    pack_json=pack,
                    created_at=now,
                )
                db.add(existing)
            else:
                existing.pack_json = pack

            if is_published:
                db.execute(update(Story).where(Story.story_id == story_id).values(is_published=False))
                existing.is_published = True


def clear_story(story_id: str) -> None:
    with db_session.SessionLocal() as db:
        with db.begin():
            db.execute(delete(Story).where(Story.story_id == str(story_id)))
