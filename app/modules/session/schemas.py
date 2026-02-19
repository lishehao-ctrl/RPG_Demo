import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChoiceOut(BaseModel):
    id: str
    text: str
    type: str
    is_available: bool | None = None
    unavailable_reason: str | None = None


class StepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_id: str | None = None
    player_input: str | None = None


class SessionCharacterStateOut(BaseModel):
    id: uuid.UUID
    character_id: uuid.UUID
    score_visible: int
    relation_vector: dict = Field(default_factory=dict)
    personality_drift: dict = Field(default_factory=dict)
    updated_at: datetime


class CurrentNodeOut(BaseModel):
    id: uuid.UUID
    parent_node_id: uuid.UUID | None = None
    narrative_text: str
    choices: list[ChoiceOut]
    created_at: datetime


class SessionStateOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    current_node_id: uuid.UUID | None = None
    story_id: str | None = None
    story_version: int | None = None
    global_flags: dict = Field(default_factory=dict)
    route_flags: dict = Field(default_factory=dict)
    active_characters: list = Field(default_factory=list)
    state_json: dict = Field(default_factory=dict)
    memory_summary: str
    created_at: datetime
    updated_at: datetime
    character_states: list[SessionCharacterStateOut]
    current_node: CurrentNodeOut | None = None


class SessionCreateRequest(BaseModel):
    story_id: str = Field(min_length=1)
    version: int | None = None


class SessionCreateOut(BaseModel):
    id: uuid.UUID
    status: str
    story_id: str | None = None
    story_version: int | None = None


class SnapshotOut(BaseModel):
    snapshot_id: uuid.UUID


class StepResponse(BaseModel):
    node_id: uuid.UUID
    story_node_id: str | None = None
    attempted_choice_id: str | None = None
    executed_choice_id: str | None = None
    resolved_choice_id: str | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    mapping_confidence: float | None = None
    narrative_text: str
    choices: list[ChoiceOut]
    cost: dict
