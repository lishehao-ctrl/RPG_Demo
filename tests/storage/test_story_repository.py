import asyncio

from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.stories_async import (
    create_story,
    get_latest_story_version,
    publish_story_version,
)


def test_publish_increments_version() -> None:
    async def _run() -> int | None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            async with transactional(db):
                story = await create_story(db, title="Draft", pack_json={"foo": "bar"})
                story_id = story.id
                await publish_story_version(db, story)
                await publish_story_version(db, story)

        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            latest = await get_latest_story_version(db, story_id)
            return latest.version if latest is not None else None

    assert asyncio.run(_run()) == 2
