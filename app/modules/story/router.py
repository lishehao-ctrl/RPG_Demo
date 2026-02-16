from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Story
from app.db.session import get_db

router = APIRouter(prefix="", tags=["stories"])


class StoryAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_params(self):
        allowed = {"study", "work", "rest", "date", "gift"}
        if self.action_id not in allowed:
            raise ValueError("unknown action_id")

        if self.action_id in {"study", "work", "rest"}:
            if self.params not in ({},):
                raise ValueError("params must be empty for simple actions")

        if self.action_id == "date":
            if not isinstance(self.params.get("target"), str) or not self.params.get("target"):
                raise ValueError("date requires target")

        if self.action_id == "gift":
            if not isinstance(self.params.get("target"), str) or not self.params.get("target"):
                raise ValueError("gift requires target")
            if not isinstance(self.params.get("gift_type"), str) or not self.params.get("gift_type"):
                raise ValueError("gift requires gift_type")

        return self


class StoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_id: str
    display_text: str
    action: StoryAction
    next_node_id: str
    is_key_decision: bool = False


class StoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    scene_brief: str
    choices: list[StoryChoice]
    is_end: bool = False


class StoryPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    version: int
    title: str
    start_node_id: str
    nodes: list[StoryNode]
    characters: list[dict] = Field(default_factory=list)
    initial_state: dict = Field(default_factory=dict)


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


def _validate_story_pack(pack: StoryPack) -> list[str]:
    errors: list[str] = []
    node_ids = {n.node_id for n in pack.nodes}

    if pack.start_node_id not in node_ids:
        errors.append(f"MISSING_START_NODE:{pack.start_node_id}")

    seen_choice_ids: set[str] = set()
    for node in pack.nodes:
        if not node.is_end and not (2 <= len(node.choices) <= 4):
            errors.append(f"INVALID_CHOICE_COUNT:{node.node_id}")

        for c in node.choices:
            if c.next_node_id not in node_ids:
                errors.append(f"DANGLING_NEXT_NODE:{c.choice_id}->{c.next_node_id}")
            if c.choice_id in seen_choice_ids:
                errors.append(f"DUPLICATE_CHOICE_ID:{c.choice_id}")
            seen_choice_ids.add(c.choice_id)

    return sorted(set(errors))


@router.post("/stories/validate", response_model=ValidateResponse)
def validate_story_pack(pack: StoryPack):
    errors = _validate_story_pack(pack)
    return {"valid": len(errors) == 0, "errors": errors}


@router.post("/stories")
def store_story_pack(pack: StoryPack, db: Session = Depends(get_db)):
    errors = _validate_story_pack(pack)
    if errors:
        raise HTTPException(status_code=400, detail={"valid": False, "errors": errors})

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
            pack_json=pack.model_dump(mode="json"),
            created_at=datetime.utcnow(),
        )
        db.add(row)

    return {"stored": True, "story_id": pack.story_id, "version": pack.version}


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

        db.execute(
            update(Story)
            .where(Story.story_id == story_id)
            .values(is_published=False)
        )
        target.is_published = True

    return {"published": True, "story_id": story_id, "published_version": version}
