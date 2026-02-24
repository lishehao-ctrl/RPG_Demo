from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ActionLog, Session as StorySession
from app.modules.narrative.state_engine import normalize_state
from app.modules.session.story_runtime.models import (
    EndingResolution,
    EventResolution,
    QuestUpdateResult,
    StoryChoiceResolution,
    StoryRuntimeContext,
)
from app.modules.session.story_runtime.phases.narration import NarrationPhaseResult, sanitize_fallback_narrative_text
from app.modules.session.story_runtime.phases.observability import (
    build_layer_debug_payload,
    compact_state_delta_for_prompt,
    estimate_turn_intensity,
    recovery_offered_from_choices,
    safe_int,
)
from app.modules.session.story_runtime.translate import build_choice_resolution_matched_rules, build_story_step_response_payload


def phase_finalize_step_response(
    *,
    db: Session,
    sess: StorySession,
    deps: Any,
    context: StoryRuntimeContext,
    next_node: dict,
    resolution: StoryChoiceResolution,
    event_update: EventResolution,
    ending_resolution: EndingResolution,
    quest_update: QuestUpdateResult,
    state_before: dict,
    state_after: dict,
    state_delta: dict,
    narration_result: NarrationPhaseResult,
    narrative_text: str,
    fallback_skeleton_text: str | None,
    fallback_builtin_text: str,
    fallback_reasons: list[str],
    input_mode_for_prompt: str,
    player_input: str | None,
) -> dict:
    if resolution.using_fallback and settings.story_fallback_show_effects_in_text:
        effects_suffix = deps.format_effects_suffix(resolution.effects_for_state)
        if effects_suffix:
            narrative_text = f"{narrative_text}{effects_suffix}"
    if resolution.using_fallback:
        narrative_text = sanitize_fallback_narrative_text(
            narrative_text=narrative_text,
            fallback_skeleton_text=fallback_skeleton_text,
            fallback_builtin_text=fallback_builtin_text,
        )

    response_choices = [] if ending_resolution.run_ended else deps.story_choices_for_response(next_node, state_after)

    run_state_after = (state_after or {}).get("run_state") if isinstance(state_after, dict) else {}
    run_state_after = dict(run_state_after or {})
    progress_keypoints = compact_state_delta_for_prompt(state_delta, max_items=6)
    has_progress = any(key in progress_keypoints for key in ("energy", "money", "knowledge", "affection"))
    route_choice_id = str(resolution.executed_choice_id or resolution.resolved_choice_id or "").strip()
    previous_route_choice_id = str(run_state_after.get("last_route_choice_id") or "").strip()
    previous_route_streak = safe_int(run_state_after.get("dominant_route_streak"), 0)
    dominant_route_streak = 0
    if route_choice_id:
        dominant_route_streak = previous_route_streak + 1 if route_choice_id == previous_route_choice_id else 1
        run_state_after["last_route_choice_id"] = route_choice_id
        run_state_after["dominant_route_streak"] = dominant_route_streak

    stall_turns = safe_int(run_state_after.get("stall_turns"), 0)
    stall_turns = 0 if has_progress else stall_turns + 1
    guard_stall_triggered = False
    if not ending_resolution.run_ended and stall_turns >= 2:
        guard_stall_triggered = True
        run_state_after["guard_stall_hits"] = safe_int(run_state_after.get("guard_stall_hits"), 0) + 1
        stall_turns = 0
        narrative_text = (
            f"{narrative_text} You force a small forward step instead of letting the pace stall."
        )
    run_state_after["stall_turns"] = stall_turns

    guard_all_blocked_triggered = False
    if not ending_resolution.run_ended and not response_choices:
        guard_all_blocked_triggered = True
        run_state_after["guard_all_blocked_hits"] = safe_int(run_state_after.get("guard_all_blocked_hits"), 0) + 1
        global_fallback_choice_id = str(context.runtime_pack.get("global_fallback_choice_id") or "").strip()
        if global_fallback_choice_id:
            response_choices = [
                {
                    "id": global_fallback_choice_id,
                    "text": "Take a stabilizing pause and reset your pace",
                    "type": "rest",
                    "is_available": True,
                    "unavailable_reason": None,
                }
            ]
        narrative_text = (
            f"{narrative_text} The pressure tightens, but you keep control and reset your footing."
        )

    recovery_offered = recovery_offered_from_choices(response_choices)
    turn_intensity = estimate_turn_intensity(
        state_delta,
        fallback_used=bool(resolution.using_fallback),
        event_present=bool(event_update.selected_event_id),
    )
    tension_note = "steady"
    if guard_all_blocked_triggered:
        tension_note = "all_blocked_guard_recovery"
    elif guard_stall_triggered:
        tension_note = "stall_guard_push"
    elif turn_intensity >= 0.7 and not recovery_offered:
        tension_note = "high_pressure_no_recovery"
    elif turn_intensity >= 0.7 and recovery_offered:
        tension_note = "high_pressure_with_recovery"

    state_after["run_state"] = run_state_after
    state_after = normalize_state(state_after)
    state_delta = deps.compute_state_delta(state_before, state_after)
    sess.state_json = state_after

    sess.story_node_id = resolution.next_node_id
    if ending_resolution.run_ended:
        sess.status = "ended"
    sess.updated_at = datetime.now(timezone.utc)

    matched_rules = build_choice_resolution_matched_rules(
        attempted_choice_id=resolution.attempted_choice_id,
        executed_choice_id=resolution.executed_choice_id,
        resolved_choice_id=resolution.resolved_choice_id,
        fallback_reason_code=resolution.internal_reason,
        mapping_confidence=resolution.mapping_confidence,
        mapping_note=resolution.mapping_note,
    )
    matched_rules.extend(quest_update.matched_rules or [])
    matched_rules.extend(event_update.matched_rules or [])
    matched_rules.extend(ending_resolution.matched_rules or [])

    layer_debug = build_layer_debug_payload(
        input_mode_for_prompt=input_mode_for_prompt,
        player_input=player_input,
        resolution=resolution,
        event_present=bool(event_update.selected_event_id),
        ending_resolution=ending_resolution,
        state_after=state_after,
        state_delta=state_delta,
        turn_intensity=turn_intensity,
        recovery_offered=recovery_offered,
        dominant_route_streak=dominant_route_streak,
        tension_note=tension_note,
        guard_all_blocked_triggered=guard_all_blocked_triggered,
        guard_stall_triggered=guard_stall_triggered,
    )

    log = ActionLog(
        session_id=sess.id,
        story_node_id=context.current_node_id,
        story_choice_id=resolution.executed_choice_id,
        player_input=(player_input or ""),
        user_raw_input=(player_input or ""),
        proposed_action={},
        final_action=resolution.final_action_for_state,
        fallback_used=resolution.using_fallback,
        fallback_reasons=fallback_reasons,
        action_confidence=resolution.mapping_confidence,
        key_decision=resolution.key_decision,
        classification={"layer_debug": layer_debug},
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        matched_rules=matched_rules,
    )
    db.add(log)

    response_payload = build_story_step_response_payload(
        story_node_id=resolution.next_node_id,
        attempted_choice_id=resolution.attempted_choice_id,
        executed_choice_id=resolution.executed_choice_id,
        resolved_choice_id=resolution.resolved_choice_id,
        fallback_used=resolution.using_fallback,
        fallback_reason=resolution.fallback_reason_code,
        mapping_confidence=resolution.mapping_confidence,
        narrative_text=narrative_text,
        choices=response_choices,
        run_ended=bool(ending_resolution.run_ended),
        ending_id=ending_resolution.ending_id,
        ending_outcome=ending_resolution.ending_outcome,
    )
    return response_payload
