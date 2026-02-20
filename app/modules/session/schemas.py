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
    run_ended: bool = False
    ending_id: str | None = None
    ending_outcome: str | None = None


class LLMTraceCallOut(BaseModel):
    id: str
    created_at: str
    provider: str
    model: str
    operation: str
    status: str
    step_id: str | None = None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    error_message: str | None = None
    phase_guess: str


class IdempotencyDebugOut(BaseModel):
    idempotency_key: str
    status: str
    error_code: str | None = None
    updated_at: str
    request_hash_prefix: str
    response_present: bool


class RuntimeLimitsOut(BaseModel):
    llm_timeout_s: float
    llm_total_deadline_s: float
    llm_retry_attempts_network: int
    llm_max_retries: int
    circuit_window_s: float
    circuit_fail_threshold: int
    circuit_open_s: float


class LLMTraceSummaryOut(BaseModel):
    total_calls: int
    success_calls: int
    error_calls: int
    providers: dict[str, int] = Field(default_factory=dict)
    errors_by_message_prefix: dict[str, int] = Field(default_factory=dict)


class LLMTraceOut(BaseModel):
    session_id: str
    env: str
    provider_chain: list[str]
    model_generate: str
    runtime_limits: RuntimeLimitsOut
    latest_idempotency: IdempotencyDebugOut | None = None
    summary: LLMTraceSummaryOut
    llm_calls: list[LLMTraceCallOut] = Field(default_factory=list)
