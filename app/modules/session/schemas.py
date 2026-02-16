import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ChoiceOut(BaseModel):
    id: str
    text: str
    type: str


class StepRequest(BaseModel):
    input_text: str | None = None
    choice_id: str | None = None
    player_input: str | None = None

    @model_validator(mode="after")
    def validate_any_input(self):
        if not self.input_text and not self.choice_id and not self.player_input:
            raise ValueError("input_text, choice_id, or player_input is required")
        return self


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
    global_flags: dict = Field(default_factory=dict)
    route_flags: dict = Field(default_factory=dict)
    active_characters: list = Field(default_factory=list)
    memory_summary: str
    token_budget_used: int
    token_budget_remaining: int
    created_at: datetime
    updated_at: datetime
    character_states: list[SessionCharacterStateOut]
    current_node: CurrentNodeOut | None = None


class SessionCreateOut(BaseModel):
    id: uuid.UUID
    status: str
    token_budget_remaining: int


class SnapshotOut(BaseModel):
    snapshot_id: uuid.UUID


class StepResponse(BaseModel):
    node_id: uuid.UUID
    narrative_text: str
    choices: list[ChoiceOut]
    affection_delta: list = Field(default_factory=list)
    cost: dict
