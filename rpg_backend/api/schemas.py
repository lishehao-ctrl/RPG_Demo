from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StoryCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    pack_json: dict[str, Any] = Field(default_factory=dict)


class StoryCreateResponse(BaseModel):
    story_id: str
    status: Literal["draft"]
    created_at: datetime


class StoryPublishResponse(BaseModel):
    story_id: str
    version: int
    published_at: datetime


class StoryGetResponse(BaseModel):
    story_id: str
    version: int
    pack: dict[str, Any]


class StoryGenerateRequest(BaseModel):
    seed_text: str | None = None
    prompt_text: str | None = None
    target_minutes: int = Field(default=10, ge=8, le=12)
    npc_count: int = Field(default=4, ge=3, le=5)
    style: str | None = None
    variant_seed: str | int | None = None
    candidate_parallelism: int | None = Field(default=None, ge=1, le=8)
    generator_version: str | None = None
    palette_policy: Literal["random", "balanced", "fixed"] = "random"
    publish: bool = False

    @model_validator(mode="after")
    def validate_prompt_or_seed(self) -> "StoryGenerateRequest":
        seed = (self.seed_text or "").strip()
        prompt = (self.prompt_text or "").strip()
        if not seed and not prompt:
            raise ValueError("either prompt_text or seed_text must be provided")
        return self


class LintReportPayload(BaseModel):
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StoryGenerateResponse(BaseModel):
    status: Literal["ok"]
    story_id: str
    version: int | None = None
    pack: dict[str, Any] = Field(default_factory=dict)
    pack_hash: str
    generation: "GenerationDiagnostics"


class SessionCreateRequest(BaseModel):
    story_id: str
    version: int = Field(ge=1)


class SessionCreateResponse(BaseModel):
    session_id: str
    story_id: str
    version: int
    scene_id: str
    state_summary: dict[str, Any]


class StepInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str | None = None
    move_id: str | None = None
    text: str | None = None


class SessionStepRequest(BaseModel):
    client_action_id: str = Field(min_length=1)
    input: StepInput | None = None
    dev_mode: bool = False


class SessionRecognizedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interpreted_intent: str
    move_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    route_source: Literal["button", "button_fallback", "llm"]
    llm_duration_ms: int | None = Field(default=None, ge=0)
    llm_gateway_mode: Literal["local", "worker", "unknown"] | None = None


class SessionResolutionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str
    costs_summary: str
    consequences_summary: str


class SessionUiMovePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    move_id: str
    label: str
    risk_hint: str


class SessionUiPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    moves: list[SessionUiMovePayload] = Field(default_factory=list)
    input_hint: str


class SessionStepDebugStancePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support: list[str] = Field(default_factory=list)
    oppose: list[str] = Field(default_factory=list)
    contested: list[str] = Field(default_factory=list)
    red_line_hits: list[str] = Field(default_factory=list)


class SessionStepDebugPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_move: str
    selected_outcome: str
    selected_strategy_style: str
    pressure_recoil_triggered: bool
    stance_snapshot: SessionStepDebugStancePayload
    state: dict[str, Any] = Field(default_factory=dict)
    beat_progress: dict[str, int] = Field(default_factory=dict)


class SessionStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    version: int
    scene_id: str
    narration_text: str
    recognized: SessionRecognizedPayload
    resolution: SessionResolutionPayload
    ui: SessionUiPayload
    debug: SessionStepDebugPayload | None = None


class SessionGetResponse(BaseModel):
    session_id: str
    scene_id: str
    beat_progress: dict[str, Any]
    ended: bool
    state_summary: dict[str, Any]
    state: dict[str, Any] | None = None


class AdminSessionTimelineEvent(BaseModel):
    event_id: str
    turn_index: int
    event_type: Literal["step_started", "step_succeeded", "step_failed", "step_replayed", "step_conflicted"]
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AdminSessionTimelineResponse(BaseModel):
    session_id: str
    events: list[AdminSessionTimelineEvent] = Field(default_factory=list)


class SessionFeedbackCreateRequest(BaseModel):
    verdict: Literal["good", "bad"]
    reason_tags: list[str] = Field(default_factory=list, max_length=8)
    note: str | None = Field(default=None, max_length=2000)
    turn_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def normalize_fields(self) -> "SessionFeedbackCreateRequest":
        tags: list[str] = []
        for raw in self.reason_tags:
            normalized = raw.strip()
            if normalized:
                tags.append(normalized)
        self.reason_tags = tags

        if self.note is not None:
            trimmed = self.note.strip()
            self.note = trimmed or None
        return self


class SessionFeedbackItem(BaseModel):
    feedback_id: str
    session_id: str
    story_id: str
    version: int
    verdict: Literal["good", "bad"]
    reason_tags: list[str] = Field(default_factory=list)
    note: str | None = None
    turn_index: int | None = None
    created_at: datetime


class SessionFeedbackListResponse(BaseModel):
    session_id: str
    items: list[SessionFeedbackItem] = Field(default_factory=list)


class RuntimeErrorBucketPayload(BaseModel):
    error_code: str
    stage: str
    model: str
    failed_count: int = Field(ge=0)
    error_share: float = Field(ge=0.0, le=1.0)
    last_seen_at: datetime | None = None
    sample_session_ids: list[str] = Field(default_factory=list)
    sample_request_ids: list[str] = Field(default_factory=list)


class RuntimeErrorsAggregateResponse(BaseModel):
    generated_at: datetime
    window_seconds: int = Field(ge=60, le=3600)
    started_total: int = Field(ge=0)
    failed_total: int = Field(ge=0)
    step_error_rate: float = Field(ge=0.0, le=1.0)
    buckets: list[RuntimeErrorBucketPayload] = Field(default_factory=list)


class Http5xxPathBucketPayload(BaseModel):
    path: str
    failed_count: int = Field(ge=0)
    sample_request_ids: list[str] = Field(default_factory=list)


class ObservabilityWindowPayload(BaseModel):
    generated_at: datetime
    window_started_at: datetime
    window_ended_at: datetime
    window_seconds: int = Field(ge=60, le=3600)


class HttpHealthAggregateResponse(ObservabilityWindowPayload):
    service: Literal["backend", "worker"]
    total_requests: int = Field(ge=0)
    failed_5xx: int = Field(ge=0)
    error_rate: float = Field(ge=0.0, le=1.0)
    p95_ms: int | None = Field(default=None, ge=0)
    top_5xx_paths: list[Http5xxPathBucketPayload] = Field(default_factory=list)


class LLMCallGroupHealthPayload(BaseModel):
    total_calls: int = Field(default=0, ge=0)
    failed_calls: int = Field(default=0, ge=0)
    failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    p95_ms: int | None = Field(default=None, ge=0)


class LLMCallByStagePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    route: LLMCallGroupHealthPayload = Field(default_factory=LLMCallGroupHealthPayload)
    narration: LLMCallGroupHealthPayload = Field(default_factory=LLMCallGroupHealthPayload)
    json_stage: LLMCallGroupHealthPayload = Field(default_factory=LLMCallGroupHealthPayload, alias="json")
    unknown: LLMCallGroupHealthPayload = Field(default_factory=LLMCallGroupHealthPayload)


class LLMCallByGatewayModePayload(BaseModel):
    local: LLMCallGroupHealthPayload = Field(default_factory=LLMCallGroupHealthPayload)
    worker: LLMCallGroupHealthPayload = Field(default_factory=LLMCallGroupHealthPayload)
    unknown: LLMCallGroupHealthPayload = Field(default_factory=LLMCallGroupHealthPayload)


class LLMCallHealthAggregateResponse(ObservabilityWindowPayload):
    total_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    failure_rate: float = Field(ge=0.0, le=1.0)
    p95_ms: int | None = Field(default=None, ge=0)
    by_stage: LLMCallByStagePayload = Field(default_factory=LLMCallByStagePayload)
    by_gateway_mode: LLMCallByGatewayModePayload = Field(default_factory=LLMCallByGatewayModePayload)


class ReadinessFailurePayload(BaseModel):
    service: Literal["backend", "worker"]
    error_code: str | None = None
    request_id: str | None = None
    created_at: datetime


class ReadinessHealthAggregateResponse(ObservabilityWindowPayload):
    backend_ready_fail_count: int = Field(ge=0)
    worker_ready_fail_count: int = Field(ge=0)
    backend_fail_streak: int = Field(ge=0)
    worker_fail_streak: int = Field(ge=0)
    last_failures: list[ReadinessFailurePayload] = Field(default_factory=list)


class ReadinessCheckPayload(BaseModel):
    ok: bool
    latency_ms: int | None = None
    checked_at: datetime | None = None
    error_code: str | None = None
    message: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ReadinessChecksPayload(BaseModel):
    db: ReadinessCheckPayload
    llm_config: ReadinessCheckPayload
    llm_probe: ReadinessCheckPayload


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checked_at: datetime
    checks: ReadinessChecksPayload


class GenerationCompilePayload(BaseModel):
    spec_hash: str | None = None
    spec_summary: dict[str, Any] | None = None


class GenerationAttemptRecord(BaseModel):
    attempt_index: int = Field(ge=1, le=4)
    variant_seed: str
    winner_candidate_index: int | None = Field(default=None, ge=0)
    winner_candidate_seed: str | None = None
    best_candidate_index: int | None = Field(default=None, ge=0)
    best_candidate_seed: str | None = None
    lint_ok: bool
    candidate_count: int = Field(ge=1, le=8)


class GenerationDiagnostics(BaseModel):
    mode: Literal["prompt", "seed"]
    generator_version: str
    variant_seed: str
    palette_policy: Literal["random", "balanced", "fixed"]
    attempts: int = Field(default=1, ge=1, le=4)
    regenerate_count: int = Field(default=0, ge=0, le=3)
    candidate_parallelism: int = Field(default=1, ge=1, le=8)
    compile: GenerationCompilePayload = Field(default_factory=GenerationCompilePayload)
    lint: LintReportPayload = Field(default_factory=LintReportPayload)
    attempt_history: list[GenerationAttemptRecord] = Field(default_factory=list)


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorPayload


StoryGenerateResponse.model_rebuild()
