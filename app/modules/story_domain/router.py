from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Story, StoryVersion
from app.db.session import SessionLocal, get_db
from app.modules.auth.deps import require_author_token
from app.modules.auth.identity import resolve_token_user_id
from app.modules.story_domain.schemas import (
    StoryCatalogItem,
    StoryCatalogResponse,
    StoryAuditRequest,
    StoryAuditResponse,
    StoryCreateRequest,
    StoryCreateResponse,
    StoryDraftCreateRequest,
    StoryDraftUpdateRequest,
    StoryPublishRequest,
    StoryPublishResponse,
    StoryPublishedResponse,
    StoryValidateRequest,
    StoryValidateResponse,
    StoryVersionDetail,
    StoryVersionListResponse,
    StoryVersionSummary,
)
from app.modules.story_domain.service import (
    audit_story_pack,
    create_or_update_story_draft,
    create_story_draft_from_published,
    get_published_story_pack,
    get_story_version_detail,
    list_published_story_catalog,
    list_story_versions,
    publish_story_version,
    update_story_draft_version,
    validate_story_pack,
)

router = APIRouter(prefix="/api/v1/stories", tags=["stories"])


def _actor_user_id(*, author_token: str | None) -> str | None:
    cleaned = str(author_token or "").strip()
    if not cleaned:
        return None

    with SessionLocal() as identity_db:
        user_id = resolve_token_user_id(identity_db, token=cleaned, role="author")
        identity_db.commit()
        return user_id


def _story_title(db: Session, *, story_id: str) -> str:
    title = db.execute(select(Story.title).where(Story.story_id == story_id)).scalar_one_or_none()
    return str(title or story_id)


def _to_version_summary(row: StoryVersion) -> StoryVersionSummary:
    return StoryVersionSummary(
        story_id=row.story_id,
        version=int(row.version),
        status=str(row.status),
        checksum=str(row.checksum),
        created_by=str(row.created_by),
        created_at=row.created_at,
        published_at=row.published_at,
    )


def _to_version_detail(db: Session, row: StoryVersion) -> StoryVersionDetail:
    return StoryVersionDetail(
        **_to_version_summary(row).model_dump(),
        title=_story_title(db, story_id=row.story_id),
        pack=dict(row.pack_json),
    )


@router.post("/validate", response_model=StoryValidateResponse)
def validate_story(
    payload: StoryValidateRequest,
    _: str | None = Depends(require_author_token),
) -> StoryValidateResponse:
    errors = validate_story_pack(payload.pack)
    return StoryValidateResponse(ok=not errors, errors=errors, warnings=[])


@router.post("/audit", response_model=StoryAuditResponse)
def audit_story(
    payload: StoryAuditRequest,
    _: str | None = Depends(require_author_token),
) -> StoryAuditResponse:
    errors, warnings = audit_story_pack(payload.pack)
    return StoryAuditResponse(ok=not errors, errors=errors, warnings=warnings)


@router.post("", response_model=StoryCreateResponse, status_code=status.HTTP_201_CREATED)
def create_story(
    payload: StoryCreateRequest,
    db: Session = Depends(get_db),
    author_token: str | None = Depends(require_author_token),
) -> StoryCreateResponse:
    errors = validate_story_pack(payload.pack)
    if errors:
        raise HTTPException(status_code=422, detail={"code": "INVALID_STORY_PACK", "errors": errors})

    actor_user_id = _actor_user_id(author_token=author_token)
    owner_user_id = payload.owner_user_id
    if actor_user_id:
        if owner_user_id and owner_user_id != actor_user_id:
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "owner mismatch"})
        owner_user_id = actor_user_id

    try:
        with db.begin():
            story_id, version, row_status = create_or_update_story_draft(
                db,
                story_id=payload.story_id,
                title=payload.title,
                pack=payload.pack,
                owner_user_id=owner_user_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)}) from exc

    return StoryCreateResponse(story_id=story_id, version=version, status=row_status)


@router.post("/{story_id}/publish", response_model=StoryPublishResponse)
def publish_story(
    story_id: str,
    payload: StoryPublishRequest,
    db: Session = Depends(get_db),
    author_token: str | None = Depends(require_author_token),
) -> StoryPublishResponse:
    actor_user_id = _actor_user_id(author_token=author_token)
    try:
        row = get_story_version_detail(
            db,
            story_id=story_id,
            version=payload.version,
            actor_user_id=actor_user_id,
        )
        pack = dict(row.pack_json)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    audit_errors, audit_warnings = audit_story_pack(pack)
    if audit_errors:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_STORY_AUDIT",
                "errors": [item.model_dump() for item in audit_errors],
                "warnings": [item.model_dump() for item in audit_warnings],
            },
        )

    try:
        sid, ver, row_status = publish_story_version(
            db,
            story_id=story_id,
            version=payload.version,
            actor_user_id=actor_user_id,
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    return StoryPublishResponse(story_id=sid, version=ver, status=row_status, warnings=audit_warnings)


@router.get("/catalog/published", response_model=StoryCatalogResponse)
def get_published_story_catalog(db: Session = Depends(get_db)) -> StoryCatalogResponse:
    items = list_published_story_catalog(db)
    return StoryCatalogResponse(stories=[StoryCatalogItem.model_validate(item) for item in items])


@router.get("/{story_id}/published", response_model=StoryPublishedResponse)
def get_published_story(story_id: str, db: Session = Depends(get_db)) -> StoryPublishedResponse:
    try:
        version, pack = get_published_story_pack(db, story_id=story_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
    return StoryPublishedResponse(story_id=story_id, version=version, pack=pack)


@router.get("/{story_id}/versions", response_model=StoryVersionListResponse)
def get_story_versions(
    story_id: str,
    db: Session = Depends(get_db),
    author_token: str | None = Depends(require_author_token),
) -> StoryVersionListResponse:
    actor_user_id = _actor_user_id(author_token=author_token)
    try:
        rows = list_story_versions(db, story_id=story_id, actor_user_id=actor_user_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    return StoryVersionListResponse(story_id=story_id, versions=[_to_version_summary(row) for row in rows])


@router.get("/{story_id}/versions/{version}", response_model=StoryVersionDetail)
def get_story_version(
    story_id: str,
    version: int,
    db: Session = Depends(get_db),
    author_token: str | None = Depends(require_author_token),
) -> StoryVersionDetail:
    actor_user_id = _actor_user_id(author_token=author_token)
    try:
        row = get_story_version_detail(
            db,
            story_id=story_id,
            version=version,
            actor_user_id=actor_user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    return _to_version_detail(db, row)


@router.post("/{story_id}/drafts", response_model=StoryVersionDetail, status_code=status.HTTP_201_CREATED)
def create_story_draft(
    story_id: str,
    payload: StoryDraftCreateRequest,
    db: Session = Depends(get_db),
    author_token: str | None = Depends(require_author_token),
) -> StoryVersionDetail:
    actor_user_id = _actor_user_id(author_token=author_token)
    try:
        with db.begin():
            _, version, _ = create_story_draft_from_published(
                db,
                story_id=story_id,
                title=payload.title,
                actor_user_id=actor_user_id,
            )
            row = get_story_version_detail(
                db,
                story_id=story_id,
                version=version,
                actor_user_id=actor_user_id,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    return _to_version_detail(db, row)


@router.put("/{story_id}/versions/{version}", response_model=StoryVersionDetail)
def update_story_draft(
    story_id: str,
    version: int,
    payload: StoryDraftUpdateRequest,
    db: Session = Depends(get_db),
    author_token: str | None = Depends(require_author_token),
) -> StoryVersionDetail:
    actor_user_id = _actor_user_id(author_token=author_token)
    errors = validate_story_pack(payload.pack)
    if errors:
        raise HTTPException(status_code=422, detail={"code": "INVALID_STORY_PACK", "errors": errors})

    try:
        with db.begin():
            update_story_draft_version(
                db,
                story_id=story_id,
                version=version,
                pack=payload.pack,
                title=payload.title,
                actor_user_id=actor_user_id,
            )
            row = get_story_version_detail(
                db,
                story_id=story_id,
                version=version,
                actor_user_id=actor_user_id,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail={"code": "VERSION_NOT_DRAFT", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc

    return _to_version_detail(db, row)
