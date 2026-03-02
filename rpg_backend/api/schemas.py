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
    generation_mode: Literal["prompt", "seed"]
    pack: dict[str, Any] = Field(default_factory=dict)
    pack_hash: str
    generator_version: str
    variant_seed: str
    palette_policy: Literal["random", "balanced", "fixed"]
    spec_hash: str | None = None
    spec_summary: dict[str, Any] | None = None
    lint_report: LintReportPayload = Field(default_factory=LintReportPayload)
    generation_attempts: int = Field(default=1, ge=1, le=4)
    regenerate_count: int = Field(default=0, ge=0, le=3)
    notes: list[str] = Field(default_factory=list)


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


class SessionStepResponse(BaseModel):
    session_id: str
    version: int
    scene_id: str
    narration_text: str
    recognized: dict[str, Any]
    resolution: dict[str, Any]
    ui: dict[str, Any]
    debug: dict[str, Any] | None = None


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
    event_type: Literal["step_started", "step_succeeded", "step_failed", "step_replayed"]
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
