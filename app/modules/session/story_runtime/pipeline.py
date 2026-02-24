from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Session as StorySession
from app.modules.llm.prompts import build_fallback_polish_prompt, build_story_narration_envelope
from app.modules.narrative.state_engine import normalize_state
from app.modules.session.story_runtime.decisions import build_fallback_reasons, build_fallback_text_plan
from app.modules.session.story_runtime.models import EndingResolution, EventResolution, QuestUpdateResult
from app.modules.session.story_runtime.phases.context import phase_load_runtime_context
from app.modules.session.story_runtime.phases.narration import phase_build_polish_inputs, phase_generate_narrative
from app.modules.session.story_runtime.phases.progression import (
    phase_apply_quest_updates,
    phase_apply_runtime_events,
    phase_resolve_ending,
)
from app.modules.session.story_runtime.phases.response import phase_finalize_step_response
from app.modules.session.story_runtime.phases.selection import phase_resolve_choice, resolve_input_mode_for_prompt
from app.modules.session.story_runtime.phases.transition import phase_compute_state_transition


@dataclass(slots=True)
class StoryRuntimePipelineDeps:
    load_story_pack: Callable[[Session, str, int | None], Any]
    normalize_pack_for_runtime: Callable[[dict | None], dict]
    story_node: Callable[[dict, str], dict | None]
    resolve_runtime_fallback: Callable[[dict, str, set[str]], tuple[dict, str, list[str]]]
    select_story_choice: Callable[..., Any]
    fallback_executed_choice_id: Callable[[dict, str], str]
    select_fallback_text_variant: Callable[[dict, str | None, str | None], str | None]
    apply_choice_effects: Callable[[dict, dict | None], dict]
    compute_state_delta: Callable[[dict, dict], dict]
    format_effects_suffix: Callable[[dict | None], str]
    story_choices_for_response: Callable[[dict, dict | None], list[dict]]
    advance_quest_state: Callable[..., QuestUpdateResult]
    advance_runtime_events: Callable[..., EventResolution]
    resolve_run_ending: Callable[..., EndingResolution]
    summarize_quest_for_narration: Callable[[list[dict], dict | None], dict]
    llm_runtime_getter: Callable[[], Any]


def run_story_runtime_pipeline(
    *,
    db: Session,
    sess: StorySession,
    choice_id: str | None,
    player_input: str | None,
    fallback_builtin_text: str,
    deps: StoryRuntimePipelineDeps,
    stage_emitter: Callable[[object], None] | None = None,
) -> dict:
    context = phase_load_runtime_context(db=db, sess=sess, deps=deps)
    resolution = phase_resolve_choice(
        sess=sess,
        player_input=player_input,
        choice_id=choice_id,
        context=context,
        deps=deps,
    )

    next_node = deps.story_node(context.runtime_pack, resolution.next_node_id)
    if not next_node:
        raise HTTPException(status_code=400, detail={"code": "INVALID_NEXT_NODE"})

    locale = settings.story_default_locale
    fallback_text_plan = build_fallback_text_plan(
        using_fallback=resolution.using_fallback,
        fallback_spec=context.fallback_spec,
        fallback_reason_code=(resolution.internal_reason or resolution.fallback_reason_code),
        locale=locale,
        fallback_builtin_text=fallback_builtin_text,
        select_fallback_text_variant=deps.select_fallback_text_variant,
        executor_skeleton_text=resolution.fallback_executor_skeleton_text,
    )
    fallback_skeleton_text = fallback_text_plan.fallback_skeleton_text

    fallback_reasons = build_fallback_reasons(
        using_fallback=resolution.using_fallback,
        internal_reason=resolution.internal_reason,
        fallback_markers=context.fallback_markers,
        extra_markers=resolution.markers,
    )
    state_before, state_after, state_delta = phase_compute_state_transition(
        sess=sess,
        final_action_for_state=resolution.final_action_for_state,
        effects_for_state=resolution.effects_for_state,
        deps=deps,
    )
    action_state_delta = dict(state_delta or {})

    quest_update = phase_apply_quest_updates(
        context=context,
        resolution=resolution,
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        deps=deps,
    )
    state_after = normalize_state(quest_update.state_after)
    state_delta = deps.compute_state_delta(state_before, state_after)

    event_update = phase_apply_runtime_events(
        sess=sess,
        context=context,
        resolution=resolution,
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        deps=deps,
    )
    state_after = normalize_state(event_update.state_after)
    run_state = dict(event_update.run_state or {})
    if resolution.using_fallback:
        run_state["fallback_count"] = int(run_state.get("fallback_count", 0)) + 1
    state_after["run_state"] = run_state
    state_after = normalize_state(state_after)
    state_delta = deps.compute_state_delta(state_before, state_after)

    ending_resolution = phase_resolve_ending(
        context=context,
        resolution=resolution,
        state_after=state_after,
        run_state=(state_after or {}).get("run_state") or {},
        deps=deps,
    )
    state_after["run_state"] = dict(ending_resolution.run_state or {})
    state_after = normalize_state(state_after)
    state_delta = deps.compute_state_delta(state_before, state_after)
    sess.state_json = state_after

    quest_summary = deps.summarize_quest_for_narration(
        context.runtime_pack.get("quests") or [],
        (state_after or {}).get("quest_state"),
    )

    fallback_narration_ctx, fallback_anchor_tokens = phase_build_polish_inputs(
        using_fallback=resolution.using_fallback,
        fallback_skeleton_text=fallback_skeleton_text,
        locale=locale,
        current_node_id=context.current_node_id,
        fallback_reason_code=resolution.fallback_reason_code,
        player_input=player_input,
        mapping_note=resolution.mapping_note,
        attempted_choice_id=resolution.attempted_choice_id,
        selected_choice=resolution.selected_choice,
        visible_choices=context.visible_choices,
        state_after=state_after,
    )

    input_mode_for_prompt = resolve_input_mode_for_prompt(resolution, player_input)
    narration_result = phase_generate_narrative(
        db=db,
        sess=sess,
        deps=deps,
        using_fallback=resolution.using_fallback,
        fallback_skeleton_text=fallback_skeleton_text,
        fallback_builtin_text=fallback_builtin_text,
        current_node_id=context.current_node_id,
        next_node_id=resolution.next_node_id,
        node=context.node,
        next_node=next_node,
        attempted_choice_id=resolution.attempted_choice_id,
        executed_choice_id=resolution.executed_choice_id,
        resolved_choice_id=resolution.resolved_choice_id,
        fallback_reason_code=resolution.fallback_reason_code,
        mapping_confidence=resolution.mapping_confidence,
        input_mode=input_mode_for_prompt,
        player_input_raw=player_input,
        selected_choice_label=(
            str(resolution.selected_choice.get("display_text"))
            if resolution.selected_choice is not None and resolution.selected_choice.get("display_text") is not None
            else None
        ),
        selected_action_id=(
            str((resolution.final_action_for_state or {}).get("action_id"))
            if (resolution.final_action_for_state or {}).get("action_id") is not None
            else None
        ),
        state_before=state_before,
        action_state_delta=action_state_delta,
        state_delta=state_delta,
        state_after=state_after,
        quest_summary=quest_summary,
        event_resolution=event_update,
        ending_resolution=ending_resolution,
        fallback_narration_ctx=fallback_narration_ctx,
        fallback_anchor_tokens=fallback_anchor_tokens,
        build_story_narration_envelope_fn=build_story_narration_envelope,
        build_fallback_polish_prompt_fn=build_fallback_polish_prompt,
        stage_emitter=stage_emitter,
        locale=locale,
    )

    return phase_finalize_step_response(
        db=db,
        sess=sess,
        deps=deps,
        context=context,
        next_node=next_node,
        resolution=resolution,
        event_update=event_update,
        ending_resolution=ending_resolution,
        quest_update=quest_update,
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        narration_result=narration_result,
        narrative_text=narration_result.narrative_text,
        fallback_skeleton_text=fallback_skeleton_text,
        fallback_builtin_text=fallback_builtin_text,
        fallback_reasons=fallback_reasons,
        input_mode_for_prompt=input_mode_for_prompt,
        player_input=player_input,
    )
