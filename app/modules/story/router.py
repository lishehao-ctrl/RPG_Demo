from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Story
from app.db.session import get_db
from app.modules.story.schemas import StoryListResponse, StoryPack, ValidateResponse
from app.modules.story.service_api import story_pack_errors, validate_story_pack_model

router = APIRouter(prefix="", tags=["stories"])


@router.post("/stories/validate", response_model=ValidateResponse)
def validate_story_pack(pack: StoryPack):
    errors = validate_story_pack_model(pack)
    return {"valid": len(errors) == 0, "errors": errors}


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
