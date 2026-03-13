from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from rpg_backend.application.author_runs.beat_context_builder import (
    BeatGenerationContext,
    build_beat_generation_context,
)
from rpg_backend.application.author_runs.workflow_retry import AuthorWorkflowNodeHandler
from rpg_backend.application.author_runs.workflow_state import (
    AuthorWorkflowState,
    build_beat_outline_update,
    build_beat_phase_seed_update,
    build_beat_plan_update,
    build_overview_generation_update,
    get_beat_phase,
    get_overview_phase,
)
from rpg_backend.application.author_runs.workflow_vocabulary import AuthorWorkflowNode, AuthorWorkflowStatus
from rpg_backend.domain.linter import lint_story_pack
from rpg_backend.domain.story_pack_normalizer import try_normalize_story_pack_payload
from rpg_backend.generator.author_workflow_assembler import assemble_story_pack
from rpg_backend.generator.author_workflow_chains import BeatGenerationChain, StoryOverviewChain
from rpg_backend.generator.author_workflow_normalizer import materialize_beat_outline
from rpg_backend.generator.author_workflow_planner import (
    check_beat_blueprints,
    plan_beat_blueprints_from_overview,
)
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy
from rpg_backend.generator.author_workflow_validators import (
    check_story_overview,
    lint_beat_draft,
)


def _build_chain(factory: Callable[..., Any], *, policy: AuthorWorkflowPolicy) -> Any:
    signature = inspect.signature(factory)
    if "policy" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    ):
        return factory(policy=policy)
    return factory()


def _accepts_kwarg(func: Callable[..., Any], name: str) -> bool:
    signature = inspect.signature(func)
    if name in signature.parameters:
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )


def build_workflow_nodes(
    *,
    overview_chain_factory: Callable[..., StoryOverviewChain],
    beat_chain_factory: Callable[..., BeatGenerationChain],
    policy: AuthorWorkflowPolicy,
    beat_context_builder: Callable[..., BeatGenerationContext] = build_beat_generation_context,
) -> dict[str, AuthorWorkflowNodeHandler]:
    async def generate_story_overview(state: AuthorWorkflowState) -> dict[str, Any]:
        overview_phase = get_overview_phase(state)
        raw_brief = state["raw_brief"]
        if overview_phase.errors:
            raw_brief = f"{raw_brief}\n\nPrevious feedback to fix:\n- " + "\n- ".join(overview_phase.errors)
        chain = _build_chain(overview_chain_factory, policy=policy)
        overview_kwargs: dict[str, Any] = {
            "raw_brief": raw_brief,
            "timeout_seconds": policy.timeout_seconds,
        }
        if _accepts_kwarg(chain.compile, "run_id"):
            overview_kwargs["run_id"] = state["run_id"]
        overview = await chain.compile(**overview_kwargs)
        overview_errors = check_story_overview(overview)
        return build_overview_generation_update(
            overview=overview,
            overview_errors=overview_errors,
            prior_attempts=overview_phase.attempts,
        )

    def plan_beats(state: AuthorWorkflowState) -> dict[str, Any]:
        blueprints = plan_beat_blueprints_from_overview(state["overview"])
        beat_plan_errors = check_beat_blueprints(blueprints)
        update = build_beat_plan_update(
            beat_blueprints=blueprints,
            beat_plan_errors=beat_plan_errors,
            prior_attempts=int(state.get("beat_plan_attempts", 0)),
        )
        if beat_plan_errors:
            return update
        update.update(build_beat_phase_seed_update())
        return update

    async def generate_beat_outline(state: AuthorWorkflowState) -> dict[str, Any]:
        beat_phase = get_beat_phase(state)
        beat_index = beat_phase.index
        context = beat_context_builder(
            overview=state["overview"],
            prior_beats=beat_phase.drafts,
        )
        chain = _build_chain(beat_chain_factory, policy=policy)
        outline_kwargs: dict[str, Any] = {
            "story_id": state["story_id"],
            "overview_context": context.overview_context,
            "blueprint": state["beat_blueprints"][beat_index].model_dump(mode="json"),
            "last_accepted_beat": context.last_accepted_beat,
            "prefix_summary": context.prefix_summary,
            "author_memory": context.author_memory,
            "lint_feedback": list(state.get("beat_lint_errors") or []),
            "timeout_seconds": policy.timeout_seconds,
        }
        if _accepts_kwarg(chain.compile_outline, "run_id"):
            outline_kwargs["run_id"] = state["run_id"]
        outline = await chain.compile_outline(**outline_kwargs)
        return build_beat_outline_update(
            overview_context=context.overview_context,
            outline=outline,
            prefix_summary=context.prefix_summary,
            author_memory=context.author_memory,
            prior_attempts=beat_phase.attempts,
        )

    def materialize_beat(state: AuthorWorkflowState) -> dict[str, Any]:
        beat_index = int(state.get("current_beat_index", 0))
        outline = state.get("current_beat_outline")
        if outline is None:
            return {
                "current_beat_draft": None,
                "beat_materialization_errors": ["current beat outline missing"],
            }
        try:
            draft = materialize_beat_outline(
                overview_context=state.get("beat_overview_context"),
                blueprint=state["beat_blueprints"][beat_index],
                outline=outline,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "current_beat_draft": None,
                "beat_materialization_errors": [str(exc)],
            }
        return {
            "current_beat_draft": draft,
            "beat_materialization_errors": [],
        }

    def beat_lint(state: AuthorWorkflowState) -> dict[str, Any]:
        beat_phase = get_beat_phase(state)
        beat_index = beat_phase.index
        draft = state.get("current_beat_draft")
        if draft is None:
            return {"beat_lint_errors": ["current beat draft missing"], "beat_lint_warnings": []}
        report = lint_beat_draft(
            overview=state["overview"],
            blueprint=state["beat_blueprints"][beat_index],
            draft=draft,
            prior_beats=beat_phase.drafts,
        )
        update: dict[str, Any] = {
            "beat_lint_errors": list(report.errors),
            "beat_lint_warnings": list(report.warnings),
        }
        if report.ok:
            accepted = [*beat_phase.drafts, draft]
            accepted_context = beat_context_builder(
                overview=state["overview"],
                prior_beats=accepted,
            )
            update.update(
                {
                    "beat_drafts": accepted,
                    "current_beat_index": beat_index + 1,
                    "current_beat_attempts": 0,
                    "beat_overview_context": None,
                    "current_beat_outline": None,
                    "current_beat_draft": None,
                    "prefix_summary": accepted_context.prefix_summary,
                    "author_memory": accepted_context.author_memory,
                }
            )
        return update

    def assemble_story_pack_node(state: AuthorWorkflowState) -> dict[str, Any]:
        pack = assemble_story_pack(
            story_id=state["story_id"],
            overview=state["overview"],
            beat_blueprints=list(state.get("beat_blueprints") or []),
            beat_drafts=list(state.get("beat_drafts") or []),
        )
        return {
            "story_pack": pack,
        }

    def normalize_story_pack(state: AuthorWorkflowState) -> dict[str, Any]:
        normalized_pack, normalization_errors = try_normalize_story_pack_payload(state["story_pack"])
        return {
            "story_pack": normalized_pack,
            "story_pack_normalization_errors": normalization_errors,
        }

    def final_lint(state: AuthorWorkflowState) -> dict[str, Any]:
        report = lint_story_pack(state["story_pack"])
        return {"final_lint_errors": list(report.errors), "final_lint_warnings": list(report.warnings)}

    def review_ready(_: AuthorWorkflowState) -> dict[str, Any]:
        return {"status": AuthorWorkflowStatus.REVIEW_READY}

    def workflow_failed(_: AuthorWorkflowState) -> dict[str, Any]:
        return {"status": AuthorWorkflowStatus.FAILED}

    return {
        AuthorWorkflowNode.GENERATE_STORY_OVERVIEW: generate_story_overview,
        AuthorWorkflowNode.PLAN_BEATS: plan_beats,
        AuthorWorkflowNode.GENERATE_BEAT_OUTLINE: generate_beat_outline,
        AuthorWorkflowNode.MATERIALIZE_BEAT: materialize_beat,
        AuthorWorkflowNode.BEAT_LINT: beat_lint,
        AuthorWorkflowNode.ASSEMBLE_STORY_PACK: assemble_story_pack_node,
        AuthorWorkflowNode.NORMALIZE_STORY_PACK: normalize_story_pack,
        AuthorWorkflowNode.FINAL_LINT: final_lint,
        AuthorWorkflowNode.REVIEW_READY: review_ready,
        AuthorWorkflowNode.WORKFLOW_FAILED: workflow_failed,
    }
