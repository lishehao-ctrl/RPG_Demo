from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_serializer

from app.modules.runtime.schemas import CurrentNodeOut
from app.modules.story_domain.schemas import StoryVersionSummary


class DebugSessionSummaryOut(BaseModel):
    session_id: str
    story_id: str
    story_version: int
    status: str
    story_node_id: str
    step_index: int
    fallback_count: int
    run_ended: bool
    last_step_index: int | None = None
    last_executed_choice_id: str | None = None
    last_fallback_reason: str | None = None
    last_selection_source: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class DebugSessionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    sessions: list[DebugSessionSummaryOut] = Field(default_factory=list)


class DebugSessionOverviewOut(BaseModel):
    session_id: str
    story_id: str
    story_version: int
    status: str
    story_node_id: str
    state_json: dict
    run_state: dict
    current_node: CurrentNodeOut
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class DebugStepSummaryOut(BaseModel):
    step_index: int
    created_at: datetime
    attempted_choice_id: str | None = None
    executed_choice_id: str
    fallback_used: bool
    fallback_reason: str | None = None
    selection_source: str | None = None
    run_ended: bool = False
    ending_id: str | None = None

    @field_serializer("created_at")
    def serialize_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class DebugTimelineResponse(BaseModel):
    session_id: str
    total: int
    limit: int
    offset: int
    steps: list[DebugStepSummaryOut] = Field(default_factory=list)


class RuntimeTelemetrySummaryOut(BaseModel):
    total_step_requests: int
    successful_steps: int
    failed_steps: int
    avg_step_latency_ms: float
    p95_step_latency_ms: float
    fallback_rate: float
    ending_distribution: dict[str, int] = Field(default_factory=dict)
    llm_unavailable_errors: int
    llm_unavailable_ratio: float


class DebugStepDetailOut(BaseModel):
    session_id: str
    step_index: int
    created_at: datetime
    request_payload_json: dict
    selection_result_json: dict
    state_before: dict
    state_delta: dict
    state_after: dict
    llm_trace_json: dict
    classification_json: dict

    @field_serializer("created_at")
    def serialize_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class DebugBundleIncludeFlagsOut(BaseModel):
    telemetry: bool = False
    versions: bool = False
    latest_step_detail: bool = False


class DebugSessionBundleOut(BaseModel):
    session_id: str
    include: DebugBundleIncludeFlagsOut
    overview: DebugSessionOverviewOut
    timeline: DebugTimelineResponse
    telemetry: RuntimeTelemetrySummaryOut | None = None
    versions: list[StoryVersionSummary] = Field(default_factory=list)
    latest_step_detail: DebugStepDetailOut | None = None
