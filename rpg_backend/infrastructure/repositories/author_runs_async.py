from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.storage.models import AuthorRun, AuthorRunArtifact, AuthorRunEvent, Story


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def create_author_run(
    db: AsyncSession,
    *,
    story_id: str,
    raw_brief: str,
    status: str,
) -> AuthorRun:
    run = AuthorRun(story_id=story_id, raw_brief=raw_brief, status=status, current_node=None)
    db.add(run)
    await db.flush()
    return run


async def get_author_run(db: AsyncSession, run_id: str) -> AuthorRun | None:
    return await db.get(AuthorRun, run_id)


async def get_latest_author_run_for_story(db: AsyncSession, story_id: str) -> AuthorRun | None:
    stmt = select(AuthorRun).where(AuthorRun.story_id == story_id).order_by(desc(AuthorRun.created_at)).limit(1)
    return (await db.exec(stmt)).first()


async def update_author_run_status(
    db: AsyncSession,
    run: AuthorRun,
    *,
    status: str,
    current_node: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    completed: bool = False,
) -> AuthorRun:
    run.status = status
    run.current_node = current_node
    run.error_code = error_code
    run.error_message = error_message
    run.updated_at = utc_now()
    run.completed_at = utc_now() if completed else None
    db.add(run)
    await db.flush()
    return run


async def upsert_author_run_artifact(
    db: AsyncSession,
    *,
    run_id: str,
    artifact_type: str,
    payload_json: dict,
    artifact_key: str = "",
) -> AuthorRunArtifact:
    stmt = select(AuthorRunArtifact).where(
        AuthorRunArtifact.run_id == run_id,
        AuthorRunArtifact.artifact_type == artifact_type,
        AuthorRunArtifact.artifact_key == artifact_key,
    )
    existing = (await db.exec(stmt)).first()
    now = utc_now()
    if existing is None:
        existing = AuthorRunArtifact(
            run_id=run_id,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            payload_json=payload_json,
            created_at=now,
            updated_at=now,
        )
    else:
        existing.payload_json = payload_json
        existing.updated_at = now
    db.add(existing)
    await db.flush()
    return existing


async def list_author_run_artifacts(db: AsyncSession, run_id: str) -> list[AuthorRunArtifact]:
    stmt = (
        select(AuthorRunArtifact)
        .where(AuthorRunArtifact.run_id == run_id)
        .order_by(AuthorRunArtifact.artifact_type, AuthorRunArtifact.artifact_key)
    )
    return list((await db.exec(stmt)).all())


async def create_author_run_event(
    db: AsyncSession,
    *,
    run_id: str,
    node_name: str,
    event_type: str,
    payload_json: dict,
) -> AuthorRunEvent:
    event = AuthorRunEvent(run_id=run_id, node_name=node_name, event_type=event_type, payload_json=payload_json)
    db.add(event)
    await db.flush()
    return event


async def list_author_run_events(db: AsyncSession, run_id: str) -> list[AuthorRunEvent]:
    stmt = select(AuthorRunEvent).where(AuthorRunEvent.run_id == run_id).order_by(AuthorRunEvent.created_at)
    return list((await db.exec(stmt)).all())


async def list_author_stories(db: AsyncSession, *, limit: int = 100) -> list[Story]:
    stmt = select(Story).order_by(desc(Story.created_at)).limit(limit)
    return list((await db.exec(stmt)).all())
