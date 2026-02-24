from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Story
from app.db.session import get_db
from app.modules.story.author_assist import (
    AuthorAssistError,
    author_assist_stream as stream_author_assist_events,
    author_assist_suggestions,
)
from app.modules.story.authoring import (
    author_v4_required_message,
    looks_like_author_pre_v4_payload,
)
from app.modules.story.constants import AUTHOR_ASSIST_TASKS_V4
from app.modules.story.schemas import (
    AuthorAssistRequest,
    AuthorAssistResponse,
    CompileAuthorResponse,
    StoryListResponse,
    StoryPack,
    ValidateAuthorResponse,
    ValidateResponse,
)
from app.modules.story.service_api import (
    compile_author_payload_with_runtime_checks,
    story_pack_errors,
    validate_story_pack_model,
)

router = APIRouter(prefix="", tags=["stories"])

_AUTHOR_ASSIST_TASKS_V4 = set(AUTHOR_ASSIST_TASKS_V4)


def _sse_encode(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/stories/validate", response_model=ValidateResponse)
def validate_story_pack(pack: StoryPack):
    errors = validate_story_pack_model(pack)
    return {"valid": len(errors) == 0, "errors": errors}


@router.post("/stories/validate-author", response_model=ValidateAuthorResponse)
def validate_author_story_pack(payload: dict):
    if looks_like_author_pre_v4_payload(payload):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "AUTHOR_V4_REQUIRED",
                "message": author_v4_required_message(),
            },
        )
    compiled_pack, errors, warnings, _mappings, playability = compile_author_payload_with_runtime_checks(payload)
    valid = len(errors) == 0
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "compiled_preview": compiled_pack if valid else None,
        "playability": playability,
    }


@router.post("/stories/compile-author", response_model=CompileAuthorResponse)
def compile_author_story_pack(payload: dict):
    if looks_like_author_pre_v4_payload(payload):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "AUTHOR_V4_REQUIRED",
                "message": author_v4_required_message(),
            },
        )
    compiled_pack, errors, warnings, mappings, _playability = compile_author_payload_with_runtime_checks(payload)
    if not isinstance(compiled_pack, dict) or errors:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "AUTHOR_COMPILE_FAILED",
                "valid": False,
                "errors": errors,
                "warnings": warnings,
            },
        )
    return {
        "pack": compiled_pack,
        "diagnostics": {
            "errors": [],
            "warnings": warnings,
            "mappings": mappings,
        },
    }


@router.post("/stories/author-assist", response_model=AuthorAssistResponse)
def author_assist(payload: AuthorAssistRequest, db: Session = Depends(get_db)):
    task = str(payload.task or "").strip()
    if task not in _AUTHOR_ASSIST_TASKS_V4:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ASSIST_TASK_V4_REQUIRED",
                "message": (
                    "author-assist now requires ASF v4 tasks: "
                    "story_ingest, seed_expand, beat_to_scene, scene_deepen, option_weave, "
                    "consequence_balance, ending_design, consistency_check, continue_write, "
                    "trim_content, spice_branch, tension_rebalance."
                ),
            },
        )
    try:
        result = author_assist_suggestions(
            db=db,
            task=task,
            locale=str(payload.locale or "en"),
            context=(payload.context if isinstance(payload.context, dict) else {}),
        )
    except AuthorAssistError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": str(exc.message or "Author assist failed."),
                "retryable": bool(exc.retryable),
                "hint": exc.hint,
            },
        ) from exc
    return {
        "suggestions": (result.get("suggestions") if isinstance(result.get("suggestions"), dict) else {}),
        "patch_preview": (result.get("patch_preview") if isinstance(result.get("patch_preview"), list) else []),
        "warnings": [str(item) for item in (result.get("warnings") or [])],
        "model": str(result.get("model") or "heuristic-v1"),
    }


@router.post("/stories/author-assist/stream")
def author_assist_stream(payload: AuthorAssistRequest, db: Session = Depends(get_db)):
    task = str(payload.task or "").strip()
    if task not in _AUTHOR_ASSIST_TASKS_V4:
        detail = {
            "code": "ASSIST_TASK_V4_REQUIRED",
            "message": (
                "author-assist now requires ASF v4 tasks: "
                "story_ingest, seed_expand, beat_to_scene, scene_deepen, option_weave, "
                "consequence_balance, ending_design, consistency_check, continue_write, "
                "trim_content, spice_branch, tension_rebalance."
            ),
        }

        def _invalid_task_stream():
            yield _sse_encode("error", {"status": 422, "detail": detail})

        return StreamingResponse(_invalid_task_stream(), media_type="text/event-stream")

    def _event_stream():
        for event_name, data in stream_author_assist_events(
            db=db,
            task=task,  # type: ignore[arg-type]
            locale=str(payload.locale or "en"),
            context=(payload.context if isinstance(payload.context, dict) else {}),
        ):
            if event_name == "result":
                payload_out = {
                    "suggestions": (data.get("suggestions") if isinstance(data.get("suggestions"), dict) else {}),
                    "patch_preview": (data.get("patch_preview") if isinstance(data.get("patch_preview"), list) else []),
                    "warnings": [str(item) for item in (data.get("warnings") or [])],
                    "model": str(data.get("model") or "heuristic-v1"),
                }
                yield _sse_encode("result", payload_out)
                continue
            if event_name == "error":
                status = int(data.get("status") or 503) if isinstance(data, dict) else 503
                detail = data.get("detail") if isinstance(data, dict) else None
                detail_payload = detail if isinstance(detail, dict) else {"code": "ASSIST_LLM_UNAVAILABLE"}
                yield _sse_encode("error", {"status": status, "detail": detail_payload})
                continue
            if event_name == "stage":
                stage_payload = data if isinstance(data, dict) else {}
                yield _sse_encode("stage", stage_payload)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/stories")
async def store_story_pack(pack: StoryPack, request: Request, db: Session = Depends(get_db)):
    errors = validate_story_pack_model(pack)
    if errors:
        raise HTTPException(status_code=400, detail={"valid": False, "errors": errors})

    raw_pack = await request.json()
    if not isinstance(raw_pack, dict):
        raw_pack = pack.model_dump(mode="json", exclude_none=True)

    with db.begin():
        existing = db.execute(
            select(Story).where(Story.story_id == pack.story_id, Story.version == pack.version)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail={"code": "STORY_VERSION_EXISTS"})

        row = Story(
            story_id=pack.story_id,
            version=pack.version,
            is_published=False,
            pack_json=raw_pack,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)

    return {"stored": True, "story_id": pack.story_id, "version": pack.version}


@router.get("/stories", response_model=StoryListResponse)
def list_story_packs(
    published_only: bool = Query(default=True),
    playable_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    stmt = select(Story).order_by(Story.story_id.asc(), Story.version.desc())
    if published_only:
        stmt = stmt.where(Story.is_published.is_(True))

    rows = db.execute(stmt).scalars().all()
    stories: list[dict] = []
    for row in rows:
        raw_pack = row.pack_json if isinstance(row.pack_json, dict) else {}
        title = str(raw_pack.get("title") or row.story_id).strip() or row.story_id
        summary_value = raw_pack.get("summary") if isinstance(raw_pack, dict) else None
        if summary_value is None and isinstance(raw_pack, dict):
            summary_value = raw_pack.get("description")
        summary = str(summary_value).strip() if summary_value is not None else None
        if summary == "":
            summary = None

        errors = story_pack_errors(raw_pack)
        is_playable = len(errors) == 0
        if playable_only and not is_playable:
            continue

        stories.append(
            {
                "story_id": row.story_id,
                "version": int(row.version),
                "title": title,
                "is_published": bool(row.is_published),
                "is_playable": is_playable,
                "summary": summary,
            }
        )
    return {"stories": stories}


@router.get("/stories/{story_id}")
def get_story_pack(story_id: str, version: int | None = Query(default=None), db: Session = Depends(get_db)):
    if version is not None:
        row = db.execute(select(Story).where(Story.story_id == story_id, Story.version == version)).scalar_one_or_none()
    else:
        row = db.execute(
            select(Story)
            .where(Story.story_id == story_id, Story.is_published.is_(True))
            .order_by(Story.version.desc())
        ).scalars().first()

    if not row:
        raise HTTPException(status_code=404, detail={"code": "STORY_NOT_FOUND"})

    return {"story_id": row.story_id, "version": row.version, "is_published": row.is_published, "pack": row.pack_json}


@router.post("/stories/{story_id}/publish")
def publish_story_pack(story_id: str, version: int = Query(...), db: Session = Depends(get_db)):
    with db.begin():
        target = db.execute(select(Story).where(Story.story_id == story_id, Story.version == version)).scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail={"code": "STORY_NOT_FOUND"})
        errors = story_pack_errors(target.pack_json if isinstance(target.pack_json, dict) else {})
        if errors:
            raise HTTPException(status_code=400, detail={"code": "STORY_INVALID_FOR_PUBLISH", "errors": errors})

        db.execute(
            update(Story)
            .where(Story.story_id == story_id)
            .values(is_published=False)
        )
        target.is_published = True

    return {"published": True, "story_id": story_id, "published_version": version}
