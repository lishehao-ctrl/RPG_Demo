from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from rpg_backend.api.schemas import (
    StoryCreateRequest,
    StoryCreateResponse,
    StoryGenerateRequest,
    StoryGenerateResponse,
    StoryGetResponse,
    StoryPublishResponse,
)
from rpg_backend.generator import GeneratorBuildError, GeneratorService
from rpg_backend.observability.context import get_request_id
from rpg_backend.observability.logging import log_event
from rpg_backend.domain.linter import lint_story_pack
from rpg_backend.storage.engine import get_session
from rpg_backend.storage.repositories.stories import (
    create_story,
    get_latest_story_version,
    get_story,
    get_story_version,
    publish_story_version,
)

router = APIRouter(prefix="/stories", tags=["stories"])


@router.post("", response_model=StoryCreateResponse)
def create_story_endpoint(payload: StoryCreateRequest, db: Session = Depends(get_session)) -> StoryCreateResponse:
    story = create_story(db, title=payload.title, pack_json=payload.pack_json)
    return StoryCreateResponse(story_id=story.id, status="draft", created_at=story.created_at)


@router.post("/{story_id}/publish", response_model=StoryPublishResponse)
def publish_story_endpoint(story_id: str, db: Session = Depends(get_session)) -> StoryPublishResponse:
    story = get_story(db, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="story not found")

    report = lint_story_pack(story.draft_pack_json)
    if not report.ok:
        raise HTTPException(status_code=422, detail={"errors": report.errors, "warnings": report.warnings})

    version = publish_story_version(db, story)
    return StoryPublishResponse(story_id=story_id, version=version.version, published_at=version.created_at)


@router.post("/generate", response_model=StoryGenerateResponse)
def generate_story_endpoint(
    payload: StoryGenerateRequest,
    request: Request,
    db: Session = Depends(get_session),
) -> StoryGenerateResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    service = GeneratorService()
    try:
        result = service.generate_pack(
            seed_text=payload.seed_text,
            prompt_text=payload.prompt_text,
            target_minutes=payload.target_minutes,
            npc_count=payload.npc_count,
            style=payload.style,
            variant_seed=payload.variant_seed,
            generator_version=payload.generator_version,
            palette_policy=payload.palette_policy,
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
            has_prompt=bool((payload.prompt_text or "").strip()),
            has_seed=bool((payload.seed_text or "").strip()),
            prompt_text_len=len(payload.prompt_text or ""),
            seed_text_len=len(payload.seed_text or ""),
        )
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": exc.error_code or "generation_failed_after_regenerates",
                "errors": exc.lint_report.errors,
                "warnings": exc.lint_report.warnings,
                "generation_attempts": exc.generation_attempts,
                "regenerate_count": exc.regenerate_count,
                "notes": exc.notes,
                "generator_version": exc.generator_version,
                "variant_seed": exc.variant_seed,
                "palette_policy": exc.palette_policy,
            },
        ) from exc

    fallback_title_source = (payload.seed_text or payload.prompt_text or "generated story").strip()
    title = result.pack.get("title") or f"Generated: {fallback_title_source[:48]}"
    story = create_story(db, title=title, pack_json=result.pack)
    version: int | None = None
    if payload.publish:
        published = publish_story_version(db, story)
        version = published.version

    response = StoryGenerateResponse(
        status="ok",
        story_id=story.id,
        version=version,
        generation_mode=result.generation_mode,
        pack=result.pack,
        pack_hash=result.pack_hash,
        generator_version=result.generator_version,
        variant_seed=result.variant_seed,
        palette_policy=result.palette_policy,
        spec_hash=result.spec_hash,
        spec_summary=result.spec_summary,
        lint_report={"errors": result.lint_report.errors, "warnings": result.lint_report.warnings},
        generation_attempts=result.generation_attempts,
        regenerate_count=result.regenerate_count,
        notes=result.notes,
    )
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
        has_prompt=bool((payload.prompt_text or "").strip()),
        has_seed=bool((payload.seed_text or "").strip()),
        prompt_text_len=len(payload.prompt_text or ""),
        seed_text_len=len(payload.seed_text or ""),
    )
    return response


@router.get("/{story_id}", response_model=StoryGetResponse)
def get_story_endpoint(
    story_id: str,
    version: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_session),
) -> StoryGetResponse:
    story = get_story(db, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="story not found")

    resolved = get_story_version(db, story_id, version) if version else get_latest_story_version(db, story_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="published version not found")

    return StoryGetResponse(story_id=story_id, version=resolved.version, pack=resolved.pack_json)
