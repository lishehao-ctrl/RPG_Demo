from __future__ import annotations

from typing import Any

from rpg_backend.application.story_authoring.errors import (
    PublishedStoryVersionNotFoundError,
    StoryGenerationFailedError,
    StoryLintFailedError,
    StoryNotFoundError,
)
from rpg_backend.application.story_authoring.models import (
    CreateStoryCommand,
    GenerateStoryCommand,
    StoryCreateView,
    StoryGenerateView,
    StoryGetView,
    StoryPublishView,
    StorySummaryView,
)
from rpg_backend.application.story_draft import DraftPatchChange, apply_story_draft_changes, build_story_draft_view
from rpg_backend.domain.linter import lint_story_pack
from rpg_backend.generator.errors import GeneratorBuildError
from rpg_backend.generator.pipeline import GeneratorPipeline
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.stories_async import (
    create_story,
    get_latest_story_version,
    get_story,
    get_story_version,
    list_stories,
    publish_story_version,
    update_story_draft,
)
from rpg_backend.observability.logging import log_event


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

    report = lint_story_pack(story.draft_pack_json)
    if not report.ok:
        raise StoryLintFailedError(errors=report.errors, warnings=report.warnings)

    async with transactional(db):
        version = await publish_story_version(db, story)
    return StoryPublishView(story_id=story_id, version=version.version, published_at=version.created_at)


async def generate_story(
    *,
    db,
    command: GenerateStoryCommand,
    request_id: str,
    pipeline_factory: type[GeneratorPipeline] = GeneratorPipeline,
) -> StoryGenerateView:
    pipeline = pipeline_factory()
    try:
        result = await pipeline.run(
            seed_text=command.seed_text,
            prompt_text=command.prompt_text,
            target_minutes=command.target_minutes,
            npc_count=command.npc_count,
            style=command.style,
            variant_seed=command.variant_seed,
            candidate_parallelism=command.candidate_parallelism,
            generator_version=command.generator_version,
            palette_policy=command.palette_policy,
        )
    except GeneratorBuildError as exc:
        log_event(
            "story_generate_failed",
            level="ERROR",
            request_id=request_id,
            error_code=exc.error_code or "generation_failed_after_regenerates",
            generation_attempts=exc.generation_attempts,
            regenerate_count=exc.regenerate_count,
            generator_version=exc.generator_version,
            variant_seed=exc.variant_seed,
            palette_policy=exc.palette_policy,
            lint_errors_count=len(exc.lint_report.errors),
            lint_warnings_count=len(exc.lint_report.warnings),
            has_prompt=bool((command.prompt_text or "").strip()),
            has_seed=bool((command.seed_text or "").strip()),
            prompt_text_len=len(command.prompt_text or ""),
            seed_text_len=len(command.seed_text or ""),
            candidate_parallelism=command.candidate_parallelism,
        )
        raise StoryGenerationFailedError(
            error_code=exc.error_code or "generation_failed",
            details={
                "errors": exc.lint_report.errors,
                "warnings": exc.lint_report.warnings,
                "generation_attempts": exc.generation_attempts,
                "regenerate_count": exc.regenerate_count,
                "generator_version": exc.generator_version,
                "variant_seed": exc.variant_seed,
                "palette_policy": exc.palette_policy,
                "candidate_parallelism": exc.candidate_parallelism,
                "attempt_history": exc.attempt_history,
                "notes": exc.notes,
            },
        ) from exc

    fallback_title_source = (command.seed_text or command.prompt_text or "generated story").strip()
    title = result.pack.get("title") or f"Generated: {fallback_title_source[:48]}"
    version: int | None = None
    async with transactional(db):
        story = await create_story(db, title=title, pack_json=result.pack)
        if command.publish:
            published = await publish_story_version(db, story)
            version = published.version

    generation = {
        "mode": result.generation_mode,
        "generator_version": result.generator_version,
        "variant_seed": result.variant_seed,
        "palette_policy": result.palette_policy,
        "attempts": result.generation_attempts,
        "regenerate_count": result.regenerate_count,
        "candidate_parallelism": result.candidate_parallelism,
        "compile": {
            "spec_hash": result.spec_hash,
            "spec_summary": result.spec_summary,
        },
        "lint": {"errors": result.lint_report.errors, "warnings": result.lint_report.warnings},
        "attempt_history": result.attempt_history,
    }
    log_event(
        "story_generate_succeeded",
        level="INFO",
        request_id=request_id,
        story_id=story.id,
        version=version,
        generation_mode=result.generation_mode,
        pack_hash=result.pack_hash,
        generator_version=result.generator_version,
        variant_seed=result.variant_seed,
        palette_policy=result.palette_policy,
        generation_attempts=result.generation_attempts,
        regenerate_count=result.regenerate_count,
        lint_errors_count=len(result.lint_report.errors),
        lint_warnings_count=len(result.lint_report.warnings),
        has_prompt=bool((command.prompt_text or "").strip()),
        has_seed=bool((command.seed_text or "").strip()),
        prompt_text_len=len(command.prompt_text or ""),
        seed_text_len=len(command.seed_text or ""),
        candidate_parallelism=command.candidate_parallelism,
    )
    return StoryGenerateView(
        status="ok",
        story_id=story.id,
        version=version,
        pack=result.pack,
        pack_hash=result.pack_hash,
        generation=generation,
    )


async def get_story_version_view(*, db, story_id: str, version: int | None) -> StoryGetView:
    story = await get_story(db, story_id)
    if story is None:
        raise StoryNotFoundError(story_id=story_id)

    resolved = await get_story_version(db, story_id, version) if version else await get_latest_story_version(db, story_id)
    if resolved is None:
        raise PublishedStoryVersionNotFoundError(story_id=story_id, version=version)

    return StoryGetView(story_id=story_id, version=resolved.version, pack=resolved.pack_json)
