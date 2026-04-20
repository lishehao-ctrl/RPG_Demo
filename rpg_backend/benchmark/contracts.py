from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import (
    AuthorCacheMetrics,
    AuthorStorySummary,
    AuthorTokenCostEstimate,
)


class BenchmarkAuthorJobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    event: str = Field(min_length=1, max_length=64)
    emitted_at: datetime
    status: str | None = Field(default=None, max_length=32)
    stage: str | None = Field(default=None, max_length=64)
    stage_index: int | None = Field(default=None, ge=1)
    stage_total: int | None = Field(default=None, ge=1)


class BenchmarkStageTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=64)
    started_at: datetime
    ended_at: datetime | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)


class BenchmarkAuthorJobDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: Literal["queued", "running", "completed", "failed"]
    prompt_seed: str = Field(min_length=1, max_length=4000)
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    summary: AuthorStorySummary | None = None
    error: dict[str, str] | None = None
    cache_metrics: AuthorCacheMetrics | None = None
    token_cost_estimate: AuthorTokenCostEstimate | None = None
    llm_call_trace: list[dict[str, Any]] = Field(default_factory=list)
    quality_trace: list[dict[str, Any]] = Field(default_factory=list)
    source_summary: dict[str, str] = Field(default_factory=dict)
    stage_timings: list[BenchmarkStageTiming] = Field(default_factory=list)
    events: list[BenchmarkAuthorJobEvent] = Field(default_factory=list)


class BenchmarkPlayTraceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_count: int = Field(ge=0)
    total_turn_elapsed_ms: int = Field(ge=0)
    total_interpret_elapsed_ms: int = Field(ge=0)
    total_ending_judge_elapsed_ms: int = Field(ge=0)
    total_pyrrhic_critic_elapsed_ms: int = Field(ge=0)
    total_render_elapsed_ms: int = Field(ge=0)
    interpret_source_distribution: dict[str, int] = Field(default_factory=dict)
    ending_judge_source_distribution: dict[str, int] = Field(default_factory=dict)
    pyrrhic_critic_source_distribution: dict[str, int] = Field(default_factory=dict)
    render_source_distribution: dict[str, int] = Field(default_factory=dict)
    heuristic_interpret_turn_count: int = Field(ge=0)
    render_fallback_turn_count: int = Field(ge=0)
    repair_turn_count: int = Field(ge=0)
    used_previous_response_turn_count: int = Field(ge=0)
    session_cache_enabled: bool = False
    usage_totals: dict[str, int] = Field(default_factory=dict)
    lane_usage_distribution: dict[str, int] = Field(default_factory=dict)
    input_mode_distribution: dict[str, int] = Field(default_factory=dict)
    ending_id: str | None = None
    ending_family: str | None = Field(default=None, max_length=80)
    end_reason: str | None = Field(default=None, max_length=120)


class BenchmarkPlaySessionDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    status: Literal["active", "completed", "expired"]
    created_at: datetime
    expires_at: datetime
    finished_at: datetime | None = None
    turn_traces: list[dict[str, Any]] = Field(default_factory=list)
    summary: BenchmarkPlayTraceSummary
