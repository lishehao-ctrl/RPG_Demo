from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Story
from app.db.session import get_db
from app.modules.story.validation import validate_story_pack_structural

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


class StoryChoiceRequires(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_money: int | None = None
    min_energy: int | None = None
    min_affection: int | None = None
    day_at_least: int | None = None
    slot_in: list[Literal["morning", "afternoon", "night"]] | None = None


class StoryChoiceEffects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy: int | float | None = None
    money: int | float | None = None
    knowledge: int | float | None = None
    affection: int | float | None = None

    @staticmethod
    def _validate_effect_value(value: Any, field_name: str) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError(f"{field_name} cannot be bool")
        if isinstance(value, (int, float)):
            return value
        raise ValueError(f"{field_name} has invalid effect value type")

    @model_validator(mode="after")
    def validate_effects(self):
        for field_name in ("energy", "money", "knowledge", "affection"):
            self._validate_effect_value(getattr(self, field_name), field_name)
        return self


class StoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_id: str
    display_text: str
    action: StoryAction
    requires: StoryChoiceRequires | None = None
    effects: StoryChoiceEffects | None = None
    next_node_id: str
    is_key_decision: bool = False


class QuestTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id_is: str | None = None
    next_node_id_is: str | None = None
    executed_choice_id_is: str | None = None
    action_id_is: str | None = None
    fallback_used_is: bool | None = None
    state_at_least: dict[str, int | float] = Field(default_factory=dict)
    state_delta_at_least: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_threshold_maps(self):
        for attr in ("state_at_least", "state_delta_at_least"):
            data = getattr(self, attr)
            for key, value in data.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{attr}.{key} must be numeric")
        return self


class QuestStageMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone_id: str
    title: str
    description: str | None = None
    when: QuestTrigger = Field(default_factory=QuestTrigger)
    rewards: StoryChoiceEffects | None = None


class QuestStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str
    title: str
    description: str | None = None
    milestones: list[QuestStageMilestone] = Field(min_length=1)
    stage_rewards: StoryChoiceEffects | None = None


class StoryQuest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str
    title: str
    description: str | None = None
    auto_activate: bool = True
    stages: list[QuestStage] = Field(min_length=1)
    completion_rewards: StoryChoiceEffects | None = None


class StoryRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_days: int = Field(default=7, ge=1)
    max_steps: int = Field(default=24, ge=1)
    default_timeout_outcome: Literal["neutral", "fail"] = "neutral"


class StoryEventTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id_is: str | None = None
    day_in: list[int] | None = None
    slot_in: list[Literal["morning", "afternoon", "night"]] | None = None
    fallback_used_is: bool | None = None
    state_at_least: dict[str, int | float] = Field(default_factory=dict)
    state_delta_at_least: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_trigger(self):
        if self.day_in is not None:
            normalized_days: list[int] = []
            for value in self.day_in:
                if isinstance(value, bool):
                    raise ValueError("day_in values must be integers")
                ivalue = int(value)
                if ivalue < 1:
                    raise ValueError("day_in values must be >= 1")
                normalized_days.append(ivalue)
            self.day_in = normalized_days

        for attr in ("state_at_least", "state_delta_at_least"):
            data = getattr(self, attr)
            for key, value in data.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{attr}.{key} must be numeric")
        return self


class StoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    title: str
    weight: int = Field(default=1, ge=1)
    once_per_run: bool = True
    cooldown_steps: int = Field(default=2, ge=0)
    trigger: StoryEventTrigger = Field(default_factory=StoryEventTrigger)
    effects: StoryChoiceEffects | None = None
    narration_hint: str | None = None


class StoryEndingTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id_is: str | None = None
    day_at_least: int | None = None
    day_at_most: int | None = None
    energy_at_most: int | None = None
    money_at_least: int | None = None
    knowledge_at_least: int | None = None
    affection_at_least: int | None = None
    completed_quests_include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trigger(self):
        for attr in ("day_at_least", "day_at_most"):
            value = getattr(self, attr)
            if value is not None and value < 1:
                raise ValueError(f"{attr} must be >= 1")
        return self


class StoryEnding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str
    title: str
    priority: int = 100
    outcome: Literal["success", "neutral", "fail"]
    trigger: StoryEndingTrigger = Field(default_factory=StoryEndingTrigger)
    epilogue: str


class StoryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str
    alias_choice_id: str
    description: str | None = None
    patterns: list[str] = Field(default_factory=list)


class StoryFallbackTextVariants(BaseModel):
    model_config = ConfigDict(extra="forbid")

    NO_INPUT: str | None = None
    BLOCKED: str | None = None
    FALLBACK: str | None = None
    DEFAULT: str | None = None


class StoryFallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    action: StoryAction
    next_node_id_policy: str
    next_node_id: str | None = None
    effects: StoryChoiceEffects | None = None
    text_variants: StoryFallbackTextVariants | None = None


class FallbackExecutorNarration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skeleton: str | None = None


class FallbackExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    action_id: str | None = None
    action_params: dict = Field(default_factory=dict)
    effects: StoryChoiceEffects = Field(default_factory=StoryChoiceEffects)
    prereq: StoryChoiceRequires | None = None
    next_node_id: str | None = None
    narration: FallbackExecutorNarration | None = None

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action_id is None:
            return self
        if self.action_id not in {"study", "work", "rest", "date", "gift", "clarify"}:
            raise ValueError("fallback executor action_id is invalid")
        if not isinstance(self.action_params, dict):
            raise ValueError("fallback executor action_params must be an object")
        return self


class StoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    scene_brief: str
    choices: list[StoryChoice]
    intents: list[StoryIntent] = Field(default_factory=list)
    node_fallback_choice_id: str | None = None
    fallback: StoryFallback | None = None
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
    default_fallback: StoryFallback | None = None
    fallback_executors: list[FallbackExecutor] = Field(default_factory=list)
    global_fallback_choice_id: str | None = None
    quests: list[StoryQuest] = Field(default_factory=list)
    events: list[StoryEvent] = Field(default_factory=list)
    endings: list[StoryEnding] = Field(default_factory=list)
    run_config: StoryRunConfig | None = None


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class StoryListItem(BaseModel):
    story_id: str
    version: int
    title: str
    is_published: bool
    is_playable: bool
    summary: str | None = None


class StoryListResponse(BaseModel):
    stories: list[StoryListItem] = Field(default_factory=list)


def _validate_story_pack(pack: StoryPack) -> list[str]:
    return validate_story_pack_structural(pack)


def _story_pack_errors(raw_pack: dict | None) -> list[str]:
    payload = raw_pack if isinstance(raw_pack, dict) else {}
    try:
        pack = StoryPack.model_validate(payload)
    except ValidationError as exc:
        rendered: list[str] = []
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", ()))
            message = str(item.get("msg") or "validation error")
            rendered.append(f"SCHEMA:{location}:{message}")
        return sorted(set(rendered))
    return _validate_story_pack(pack)


@router.post("/stories/validate", response_model=ValidateResponse)
def validate_story_pack(pack: StoryPack):
    errors = _validate_story_pack(pack)
    return {"valid": len(errors) == 0, "errors": errors}


@router.post("/stories")
async def store_story_pack(pack: StoryPack, request: Request, db: Session = Depends(get_db)):
    errors = _validate_story_pack(pack)
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
            created_at=datetime.utcnow(),
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

        errors = _story_pack_errors(raw_pack)
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
        errors = _story_pack_errors(target.pack_json if isinstance(target.pack_json, dict) else {})
        if errors:
            raise HTTPException(status_code=400, detail={"code": "STORY_INVALID_FOR_PUBLISH", "errors": errors})

        db.execute(
            update(Story)
            .where(Story.story_id == story_id)
            .values(is_published=False)
        )
        target.is_published = True

    return {"published": True, "story_id": story_id, "published_version": version}
