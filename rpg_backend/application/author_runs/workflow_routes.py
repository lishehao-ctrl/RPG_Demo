from __future__ import annotations

from collections.abc import Callable

from rpg_backend.application.author_runs.workflow_state import (
    AuthorWorkflowState,
    get_beat_phase,
    get_overview_phase,
)
from rpg_backend.application.author_runs.workflow_vocabulary import AuthorWorkflowNode
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy


AuthorWorkflowRoute = Callable[[AuthorWorkflowState], str]


def build_workflow_routes(*, policy: AuthorWorkflowPolicy) -> dict[str, AuthorWorkflowRoute]:
    def route_after_generate_story_overview(state: AuthorWorkflowState) -> str:
        phase = get_overview_phase(state)
        if phase.errors:
            if phase.attempts < policy.max_attempts:
                return AuthorWorkflowNode.GENERATE_STORY_OVERVIEW
            return AuthorWorkflowNode.WORKFLOW_FAILED
        return AuthorWorkflowNode.PLAN_BEATS

    def route_after_plan_beats(state: AuthorWorkflowState) -> str:
        if not state.get("beat_plan_errors"):
            return AuthorWorkflowNode.GENERATE_BEAT
        if int(state.get("beat_plan_attempts", 0)) < policy.max_attempts:
            return AuthorWorkflowNode.PLAN_BEATS
        return AuthorWorkflowNode.WORKFLOW_FAILED

    def route_after_generate_beat(state: AuthorWorkflowState) -> str:
        del state
        return AuthorWorkflowNode.BEAT_LINT

    def route_after_beat_lint(state: AuthorWorkflowState) -> str:
        phase = get_beat_phase(state)
        if phase.lint_errors:
            if phase.attempts < policy.max_attempts:
                return AuthorWorkflowNode.GENERATE_BEAT
            return AuthorWorkflowNode.WORKFLOW_FAILED
        if phase.index < len(state.get("beat_blueprints") or []):
            return AuthorWorkflowNode.GENERATE_BEAT
        return AuthorWorkflowNode.ASSEMBLE_STORY_PACK

    def route_after_final_lint(state: AuthorWorkflowState) -> str:
        if not state.get("final_lint_errors"):
            return AuthorWorkflowNode.REVIEW_READY
        return AuthorWorkflowNode.WORKFLOW_FAILED

    return {
        AuthorWorkflowNode.GENERATE_STORY_OVERVIEW: route_after_generate_story_overview,
        AuthorWorkflowNode.PLAN_BEATS: route_after_plan_beats,
        AuthorWorkflowNode.GENERATE_BEAT: route_after_generate_beat,
        AuthorWorkflowNode.BEAT_LINT: route_after_beat_lint,
        AuthorWorkflowNode.FINAL_LINT: route_after_final_lint,
    }
