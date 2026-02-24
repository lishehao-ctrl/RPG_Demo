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
    id: str
    parent_node_id: str | None = None
    narrative_text: str
    choices: list[ChoiceOut]
    created_at: datetime


class SessionStateOut(BaseModel):
    id: uuid.UUID
    status: str
    current_node_id: str | None = None
    story_id: str | None = None
    story_version: int | None = None
    global_flags: dict = Field(default_factory=dict)
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
    story_node_id: str | None = None
    attempted_choice_id: str | None = None
    executed_choice_id: str | None = None
    resolved_choice_id: str | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    mapping_confidence: float | None = None
    narrative_text: str
    choices: list[ChoiceOut]
    run_ended: bool = False
    ending_id: str | None = None
    ending_outcome: str | None = None


class LayerInspectorStepOut(BaseModel):
    step_index: int
    world_layer: dict = Field(default_factory=dict)
    characters_layer: dict = Field(default_factory=dict)
    plot_layer: dict = Field(default_factory=dict)
    scene_layer: dict = Field(default_factory=dict)
    action_layer: dict = Field(default_factory=dict)
    consequence_layer: dict = Field(default_factory=dict)
    ending_layer: dict = Field(default_factory=dict)
    raw_refs: dict = Field(default_factory=dict)


class LayerInspectorSummaryOut(BaseModel):
    fallback_rate: float
    mismatch_count: int
    event_turns: int
    guard_all_blocked_turns: int = 0
    guard_stall_turns: int = 0
    dominant_route_alerts: int = 0
    low_recovery_turns: int = 0
    ending_state: str


class LayerInspectorOut(BaseModel):
    session_id: str
    env: str
    steps: list[LayerInspectorStepOut] = Field(default_factory=list)
    summary: LayerInspectorSummaryOut
