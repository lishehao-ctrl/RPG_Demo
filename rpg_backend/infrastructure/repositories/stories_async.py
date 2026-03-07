from __future__ import annotations

from sqlmodel import desc, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.storage.models import Story, StoryVersion


async def create_story(db: AsyncSession, *, title: str, pack_json: dict) -> Story:
    story = Story(title=title, draft_pack_json=pack_json)
    db.add(story)
    await db.flush()
    return story


async def update_story_draft(
    db: AsyncSession,
    story: Story,
    *,
    title: str,
    draft_pack_json: dict,
) -> Story:
    story.title = title
    story.draft_pack_json = draft_pack_json
    db.add(story)
    await db.flush()
    return story


async def list_stories(db: AsyncSession, *, limit: int = 100) -> list[Story]:
    stmt = select(Story).order_by(desc(Story.created_at)).limit(limit)
    return list((await db.exec(stmt)).all())


async def get_story(db: AsyncSession, story_id: str) -> Story | None:
    return await db.get(Story, story_id)


async def get_story_version(db: AsyncSession, story_id: str, version: int) -> StoryVersion | None:
    stmt = select(StoryVersion).where(StoryVersion.story_id == story_id, StoryVersion.version == version)
    return (await db.exec(stmt)).first()


async def get_latest_story_version(db: AsyncSession, story_id: str) -> StoryVersion | None:
    stmt = (
        select(StoryVersion)
        .where(StoryVersion.story_id == story_id)
        .order_by(desc(StoryVersion.version))
        .limit(1)
    )
    return (await db.exec(stmt)).first()


async def publish_story_version(db: AsyncSession, story: Story) -> StoryVersion:
    next_version_stmt = select(func.coalesce(func.max(StoryVersion.version), 0)).where(StoryVersion.story_id == story.id)
    max_version = (await db.exec(next_version_stmt)).one()
    next_version = int(max_version) + 1

    version = StoryVersion(story_id=story.id, version=next_version, status="published", pack_json=story.draft_pack_json)
    db.add(version)
    await db.flush()
    return version
