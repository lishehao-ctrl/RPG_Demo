from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.api.contracts.stories import (
    StoryCreateRequest,
    StoryCreateResponse,
    StoryDraftGetResponse,
    StoryDraftPatchChange,
    StoryDraftPatchRequest,
    StoryGenerateRequest,
    StoryGenerateResponse,
    StoryGetResponse,
    StoryListItem,
    StoryListResponse,
    StoryPublishResponse,
)
from rpg_backend.api.error_mapping import api_error_from_application_error
from rpg_backend.api.route_paths import API_STORIES_PREFIX
from rpg_backend.application.errors import ApplicationError
from rpg_backend.application.story_authoring.models import CreateStoryCommand, GenerateStoryCommand
from rpg_backend.application.story_authoring.service import (
    create_story_draft,
    generate_story,
    get_story_draft_view,
    get_story_version_view,
    list_story_summaries,
    patch_story_draft_view,
    publish_story,
)
from rpg_backend.application.story_draft import DraftPatchChange
from rpg_backend.generator.pipeline import GeneratorPipeline
from rpg_backend.infrastructure.db.async_session import get_async_session
from rpg_backend.observability.context import get_request_id
from rpg_backend.security.deps import require_current_user

router = APIRouter(
    prefix=API_STORIES_PREFIX,
    tags=["stories"],
    dependencies=[Depends(require_current_user)],
)


def _patch_change_from_contract(change: StoryDraftPatchChange) -> DraftPatchChange:
    return DraftPatchChange(
        target_type=change.target_type,
        field=change.field,
        target_id=change.target_id,
        value=change.value,
    )


@router.post("", response_model=StoryCreateResponse)
async def create_story_endpoint(
    payload: StoryCreateRequest,
    db: AsyncSession = Depends(get_async_session),
) -> StoryCreateResponse:
    try:
        view = await create_story_draft(
            db=db,
            command=CreateStoryCommand(title=payload.title, pack_json=payload.pack_json),
        )
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return StoryCreateResponse(story_id=view.story_id, status=view.status, created_at=view.created_at)


@router.get("", response_model=StoryListResponse)
async def list_stories_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_async_session),
) -> StoryListResponse:
    items = await list_story_summaries(db=db, limit=limit)
    return StoryListResponse(
        stories=[
            StoryListItem(
                story_id=item.story_id,
                title=item.title,
                created_at=item.created_at,
                has_draft=item.has_draft,
                latest_published_version=item.latest_published_version,
                latest_published_at=item.latest_published_at,
            )
            for item in items
        ]
    )


@router.get("/{story_id}/draft", response_model=StoryDraftGetResponse)
async def get_story_draft_endpoint(
    story_id: str,
    db: AsyncSession = Depends(get_async_session),
) -> StoryDraftGetResponse:
    try:
        view = await get_story_draft_view(db=db, story_id=story_id)
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return StoryDraftGetResponse(
        story_id=view.story_id,
        title=view.title,
        created_at=view.created_at,
        draft_pack=view.draft_pack,
        latest_published_version=view.latest_published_version,
        latest_published_at=view.latest_published_at,
    )


@router.patch("/{story_id}/draft", response_model=StoryDraftGetResponse)
async def patch_story_draft_endpoint(
    story_id: str,
    payload: StoryDraftPatchRequest,
    db: AsyncSession = Depends(get_async_session),
) -> StoryDraftGetResponse:
    try:
        view = await patch_story_draft_view(
            db=db,
            story_id=story_id,
            changes=[_patch_change_from_contract(change) for change in payload.changes],
        )
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return StoryDraftGetResponse(
        story_id=view.story_id,
        title=view.title,
        created_at=view.created_at,
        draft_pack=view.draft_pack,
        latest_published_version=view.latest_published_version,
        latest_published_at=view.latest_published_at,
    )


@router.post("/{story_id}/publish", response_model=StoryPublishResponse)
async def publish_story_endpoint(
    story_id: str,
    db: AsyncSession = Depends(get_async_session),
) -> StoryPublishResponse:
    try:
        view = await publish_story(db=db, story_id=story_id)
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return StoryPublishResponse(story_id=view.story_id, version=view.version, published_at=view.published_at)


@router.post("/generate", response_model=StoryGenerateResponse)
async def generate_story_endpoint(
    payload: StoryGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> StoryGenerateResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    command = GenerateStoryCommand(
        seed_text=payload.seed_text,
        prompt_text=payload.prompt_text,
        target_minutes=payload.target_minutes,
        npc_count=payload.npc_count,
        style=payload.style,
        variant_seed=payload.variant_seed,
        candidate_parallelism=payload.candidate_parallelism,
        generator_version=payload.generator_version,
        palette_policy=payload.palette_policy,
        publish=payload.publish,
    )
    try:
        view = await generate_story(
            db=db,
            command=command,
            request_id=request_id,
            pipeline_factory=GeneratorPipeline,
        )
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return StoryGenerateResponse(
        status=view.status,
        story_id=view.story_id,
        version=view.version,
        pack=view.pack,
        pack_hash=view.pack_hash,
        generation=view.generation,
    )


@router.get("/{story_id}", response_model=StoryGetResponse)
async def get_story_endpoint(
    story_id: str,
    version: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_async_session),
) -> StoryGetResponse:
    try:
        view = await get_story_version_view(db=db, story_id=story_id, version=version)
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return StoryGetResponse(story_id=view.story_id, version=view.version, pack=view.pack)
