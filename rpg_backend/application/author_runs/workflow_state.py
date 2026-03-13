from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from typing_extensions import TypedDict

from rpg_backend.application.author_runs.workflow_vocabulary import AuthorWorkflowStatus
from rpg_backend.generator.author_workflow_models import (
    AuthorMemory,
    BeatBlueprint,
    BeatDraft,
    BeatOverviewContext,
    BeatPrefixSummary,
    StoryOverview,
)
from rpg_backend.generator.author_workflow_validators import build_author_memory, build_structured_prefix_summary


class AuthorWorkflowState(TypedDict, total=False):
    story_id: str
    run_id: str
    raw_brief: str
    overview: StoryOverview
    overview_errors: list[str]
    overview_attempts: int
    beat_blueprints: list[BeatBlueprint]
    beat_plan_errors: list[str]
    beat_plan_attempts: int
    current_beat_index: int
    current_beat_attempts: int
    beat_overview_context: BeatOverviewContext | None
    current_beat_draft: BeatDraft | None
    beat_drafts: list[BeatDraft]
    beat_generation_errors: list[str]
    beat_lint_errors: list[str]
    beat_lint_warnings: list[str]
    prefix_summary: BeatPrefixSummary
    author_memory: AuthorMemory
    story_pack: dict[str, Any]
    story_pack_normalization_errors: list[str]
    final_lint_errors: list[str]
    final_lint_warnings: list[str]
    status: str


@dataclass(frozen=True)
class OverviewPhaseState:
    attempts: int
    errors: list[str]


@dataclass(frozen=True)
class BeatPhaseState:
    index: int
    attempts: int
    drafts: list[BeatDraft]
    lint_errors: list[str]
    generation_errors: list[str]


@dataclass(frozen=True)
class PackPhaseState:
    normalization_errors: list[str]
    final_lint_errors: list[str]


def get_overview_phase(state: AuthorWorkflowState) -> OverviewPhaseState:
    return OverviewPhaseState(
        attempts=int(state.get("overview_attempts", 0)),
        errors=list(state.get("overview_errors") or []),
    )


def get_beat_phase(state: AuthorWorkflowState) -> BeatPhaseState:
    return BeatPhaseState(
        index=int(state.get("current_beat_index", 0)),
        attempts=int(state.get("current_beat_attempts", 0)),
        drafts=list(state.get("beat_drafts") or []),
        lint_errors=list(state.get("beat_lint_errors") or []),
        generation_errors=list(state.get("beat_generation_errors") or []),
    )


def get_pack_phase(state: AuthorWorkflowState) -> PackPhaseState:
    return PackPhaseState(
        normalization_errors=list(state.get("story_pack_normalization_errors") or []),
        final_lint_errors=list(state.get("final_lint_errors") or []),
    )


def build_overview_generation_update(
    *,
    overview: StoryOverview,
    overview_errors: list[str],
    prior_attempts: int,
) -> dict[str, Any]:
    return {
        "overview": overview,
        "overview_attempts": prior_attempts + 1,
        "overview_errors": list(overview_errors),
        "beat_plan_errors": [],
        "beat_plan_attempts": 0,
    }


def build_beat_plan_update(
    *,
    beat_blueprints: list[BeatBlueprint],
    beat_plan_errors: list[str],
    prior_attempts: int,
) -> dict[str, Any]:
    return {
        "beat_blueprints": beat_blueprints,
        "beat_plan_attempts": prior_attempts + 1,
        "beat_plan_errors": list(beat_plan_errors),
    }


def build_beat_phase_seed_update() -> dict[str, Any]:
    return {
        "current_beat_index": 0,
        "current_beat_attempts": 0,
        "beat_drafts": [],
        "beat_generation_errors": [],
        "current_beat_draft": None,
        "prefix_summary": build_structured_prefix_summary([]),
        "author_memory": build_author_memory([]),
    }


def build_beat_generation_update(
    *,
    overview_context: BeatOverviewContext,
    draft: BeatDraft,
    prefix_summary: BeatPrefixSummary,
    author_memory: AuthorMemory,
    prior_attempts: int,
    current_beat_index: int,
) -> dict[str, Any]:
    return {
        "current_beat_index": current_beat_index,
        "beat_overview_context": overview_context,
        "current_beat_draft": draft,
        "current_beat_attempts": prior_attempts + 1,
        "beat_generation_errors": [],
        "prefix_summary": prefix_summary,
        "author_memory": author_memory,
        "beat_lint_errors": [],
        "beat_lint_warnings": [],
    }


def build_initial_author_workflow_state(*, story_id: str, run_id: str, raw_brief: str) -> AuthorWorkflowState:
    return {
        "story_id": story_id,
        "run_id": run_id,
        "raw_brief": raw_brief,
        "overview_attempts": 0,
        "beat_plan_attempts": 0,
        "current_beat_index": 0,
        "current_beat_attempts": 0,
        "beat_drafts": [],
        "beat_generation_errors": [],
        "current_beat_draft": None,
        "prefix_summary": build_structured_prefix_summary([]),
        "author_memory": build_author_memory([]),
        "story_pack_normalization_errors": [],
        "status": AuthorWorkflowStatus.RUNNING,
    }


def resolve_workflow_failure_errors(final_state: AuthorWorkflowState) -> list[str]:
    return list(
        final_state.get("final_lint_errors")
        or final_state.get("story_pack_normalization_errors")
        or final_state.get("beat_lint_errors")
        or final_state.get("beat_generation_errors")
        or final_state.get("overview_errors")
        or final_state.get("beat_plan_errors")
        or ["workflow failed"]
    )
