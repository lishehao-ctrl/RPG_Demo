from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class ChoiceLockReasonOut(BaseModel):
    code: str
    message: str


class ChoiceOut(BaseModel):
    id: str
    text: str
    available: bool = True
    locked_reason: ChoiceLockReasonOut | None = None


class CurrentNodeOut(BaseModel):
    id: str
    title: str
    scene_brief: str
    choices: list[ChoiceOut]


class SessionCreateRequest(BaseModel):
    story_id: str = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)
    user_id: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    story_id: str
    story_version: int
    story_node_id: str
    state_json: dict
    current_node: CurrentNodeOut
    status: str


class SessionStateResponse(BaseModel):
    session_id: str
    story_id: str
    story_version: int
    story_node_id: str
    status: str
    state_json: dict
    current_node: CurrentNodeOut
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class StepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_id: str | None = None
    player_input: str | None = None

    @model_validator(mode="after")
    def check_input(self):
        choice = str(self.choice_id or "").strip()
        player = str(self.player_input or "").strip()
        if not choice and not player:
            raise ValueError("choice_id and player_input cannot both be empty")
        if choice and player:
            raise ValueError("choice_id and player_input cannot both be provided")
        return self


class EndingHighlightOut(BaseModel):
    title: str
    detail: str


class EndingStatsOut(BaseModel):
    total_steps: int
    fallback_count: int
    fallback_rate: float
    explicit_count: int
    rule_count: int
    llm_count: int
    fallback_source_count: int
    energy_delta: float
    money_delta: float
    knowledge_delta: float
    affection_delta: float


class EndingReportOut(BaseModel):
    title: str
    one_liner: str
    life_summary: str
    highlights: list[EndingHighlightOut]
    stats: EndingStatsOut
    persona_tags: list[str]


class StepResponse(BaseModel):
    session_status: Literal["active", "ended"]
    story_node_id: str
    attempted_choice_id: str | None = None
    executed_choice_id: str
    fallback_used: bool
    fallback_reason: str | None = None
    selection_mode: Literal["explicit_choice", "free_input"]
    selection_source: Literal["explicit", "rule", "llm", "fallback"]
    mapping_confidence: float | None = None
    intensity_tier: int | None = None
    mainline_nudge: str | None = None
    nudge_tier: Literal["soft", "neutral", "firm"] | None = None
    narrative_text: str
    choices: list[ChoiceOut]
    range_effects_applied: list[dict] = Field(default_factory=list)
    state_excerpt: dict
    run_ended: bool = False
    ending_id: str | None = None
    ending_outcome: str | None = None
    ending_camp: Literal["player", "enemy", "world"] | None = None
    ending_report: EndingReportOut | None = None
    current_node: CurrentNodeOut
