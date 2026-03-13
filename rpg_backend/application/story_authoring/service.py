from __future__ import annotations

from rpg_backend.application.author_runs.errors import AuthorStoryNotReadyForPublishError
from rpg_backend.application.author_runs.workflow_vocabulary import AuthorWorkflowStatus
from rpg_backend.application.story_authoring.errors import (
    PublishedStoryVersionNotFoundError,
    StoryLintFailedError,
    StoryNotFoundError,
)
from rpg_backend.application.story_authoring.models import (
    CreateStoryCommand,
    StoryCreateView,
    StoryGetView,
    StoryPublishView,
    StorySummaryView,
)
from rpg_backend.application.story_draft import DraftPatchChange, apply_story_draft_changes, build_story_draft_view
from rpg_backend.domain.linter import lint_story_pack
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.author_runs_async import get_latest_author_run_for_story
from rpg_backend.infrastructure.repositories.stories_async import (
    create_story,
    get_latest_story_version,
    get_story,
    get_story_version,
    list_stories,
    publish_story_version,
    update_story_draft,
)


async def create_story_draft(*, db, command: CreateStoryCommand) -> StoryCreateView:
    async with transactional(db):
        story = await create_story(db, title=command.title, pack_json=command.pack_json)
    return StoryCreateView(story_id=story.id, status="draft", created_at=story.created_at)


async def list_story_summaries(*, db, limit: int) -> list[StorySummaryView]:
    stories = await list_stories(db, limit=limit)
    items: list[StorySummaryView] = []
    for story in stories:
        latest_version = await get_latest_story_version(db, story.id)
        items.append(
            StorySummaryView(
                story_id=story.id,
                title=story.title,
                created_at=story.created_at,
                has_draft=bool(story.draft_pack_json),
                latest_published_version=latest_version.version if latest_version else None,
                latest_published_at=latest_version.created_at if latest_version else None,
            )
        )
    return items


async def get_story_draft_view(*, db, story_id: str):
    story = await get_story(db, story_id)
    if story is None:
        raise StoryNotFoundError(story_id=story_id)
    latest_version = await get_latest_story_version(db, story_id)
    return build_story_draft_view(story=story, latest_version=latest_version)


async def patch_story_draft_view(*, db, story_id: str, changes: list[DraftPatchChange]):
    story = await get_story(db, story_id)
    if story is None:
        raise StoryNotFoundError(story_id=story_id)

    updated_pack, updated_title = apply_story_draft_changes(
        pack_json=story.draft_pack_json,
        story_title=story.title,
        changes=changes,
    )
    async with transactional(db):
        story = await update_story_draft(
            db,
            story,
            title=updated_title,
            draft_pack_json=updated_pack,
        )
    latest_version = await get_latest_story_version(db, story_id)
    return build_story_draft_view(story=story, latest_version=latest_version)


async def publish_story(*, db, story_id: str) -> StoryPublishView:
    story = await get_story(db, story_id)
    if story is None:
        raise StoryNotFoundError(story_id=story_id)

    latest_run = await get_latest_author_run_for_story(db, story_id)
    if latest_run is not None and latest_run.status != AuthorWorkflowStatus.REVIEW_READY:
        raise AuthorStoryNotReadyForPublishError(
            story_id=story_id,
            latest_run_status=latest_run.status,
        )

    report = lint_story_pack(story.draft_pack_json)
    if not report.ok:
        raise StoryLintFailedError(errors=report.errors, warnings=report.warnings)

    async with transactional(db):
        version = await publish_story_version(db, story)
    return StoryPublishView(story_id=story_id, version=version.version, published_at=version.created_at)


async def get_story_version_view(*, db, story_id: str, version: int | None) -> StoryGetView:
    story = await get_story(db, story_id)
    if story is None:
        raise StoryNotFoundError(story_id=story_id)

    resolved = await get_story_version(db, story_id, version) if version else await get_latest_story_version(db, story_id)
    if resolved is None:
        raise PublishedStoryVersionNotFoundError(story_id=story_id, version=version)

    return StoryGetView(story_id=story_id, version=resolved.version, pack=resolved.pack_json)
