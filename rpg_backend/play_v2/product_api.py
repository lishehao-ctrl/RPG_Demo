from __future__ import annotations

from dataclasses import asdict, dataclass

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v2.product_adapters import product_protagonist_from_plan, public_ending_from_v2
from rpg_backend.play.contracts import (
    PlayCallbackStatusDebug,
    PlayControlAction,
    PlayControlResolution,
    PlayCostRouteDebug,
    PlayEnding,
    PlayFeedbackSnapshot,
    PlayLatentRadarItem,
    PlayPropagationEdgeDebug,
    PlayLedgerSnapshot,
    PlayRelationshipStateSnapshot,
    PlayRelationshipTargetState,
    PlaySceneQuestionDebug,
    PlaySessionProgress,
    PlaySessionSnapshot,
    PlayStoryDebug,
    PlayStateBar,
    PlaySuggestedAction,
    PlaySuccessLedger,
    PlayUtilityShiftItem,
    PlayCostLedger,
    PlayTurnTrace,
    PlayResolutionEffect,
    PlayQuestionStepDebug,
    PlayEventDecisionDebug,
    PlayPayoffCommitDebug,
    PlayStyleCommitDebug,
)
from rpg_backend.play_v2.contracts import UrbanTurnResult, UrbanWorldState


@dataclass(frozen=True)
class ProductV2TurnTracePayload:
    ending_family: str | None
    lane_id: str | None


def build_v2_latent_radar(state: UrbanWorldState) -> list[PlayLatentRadarItem]:
    if state.latent_radar:
        return [
            PlayLatentRadarItem(kind=item.kind, pressure=item.pressure, trend=item.trend, note=item.note)
            for item in state.latent_radar
        ][:4]
    return [
        PlayLatentRadarItem(kind="relationship_debt", pressure=state.relationship_debt_pressure, trend="steady", note="关系旧账目前维持可控。"),
        PlayLatentRadarItem(kind="public_wave", pressure=state.public_wave_pressure, trend="steady", note="公开风向目前维持可控。"),
        PlayLatentRadarItem(kind="secret_pressure", pressure=state.secret_pressure, trend="steady", note="秘密压力目前维持可控。"),
        PlayLatentRadarItem(kind="npc_action", pressure=state.npc_action_pressure, trend="steady", note="人物动作目前维持可控。"),
    ]


def build_v2_state_bars(plan: CompiledPlayPlan, state: UrbanWorldState) -> list[PlayStateBar]:
    bars = [
        PlayStateBar(bar_id="scene_heat", label="场面热度", category="global", current_value=state.scene_heat, min_value=0, max_value=6),
        PlayStateBar(bar_id="public_image", label="公众风评", category="global", current_value=state.public_image, min_value=0, max_value=6),
        PlayStateBar(bar_id="route_lock", label="路线锁定", category="global", current_value=state.route_lock, min_value=0, max_value=6),
        PlayStateBar(bar_id="relationship_debt_pressure", label="关系旧账", category="global", current_value=state.relationship_debt_pressure, min_value=0, max_value=6),
        PlayStateBar(bar_id="public_wave_pressure", label="场外风向", category="global", current_value=state.public_wave_pressure, min_value=0, max_value=6),
        PlayStateBar(bar_id="secret_pressure", label="秘密积压", category="global", current_value=state.secret_pressure, min_value=0, max_value=6),
        PlayStateBar(bar_id="npc_action_pressure", label="人物动作", category="global", current_value=state.npc_action_pressure, min_value=0, max_value=6),
    ]
    for target_id in plan.route_target_ids[:3]:
        target = state.relationships.get(target_id)
        mind = state.npc_mind_states.get(target_id)
        if target is None:
            continue
        bars.extend(
            [
                PlayStateBar(bar_id=f"{target_id}:affection", label=f"{target.name}·亲密", category="relationship", current_value=target.affection, min_value=-3, max_value=6),
                PlayStateBar(bar_id=f"{target_id}:trust", label=f"{target.name}·信任", category="relationship", current_value=target.trust, min_value=-3, max_value=6),
                PlayStateBar(bar_id=f"{target_id}:tension", label=f"{target.name}·拉扯", category="relationship", current_value=target.tension, min_value=0, max_value=6),
                PlayStateBar(bar_id=f"{target_id}:suspicion", label=f"{target.name}·怀疑", category="relationship", current_value=target.suspicion, min_value=0, max_value=6),
            ]
        )
        if mind is not None:
            bars.extend(
                [
                    PlayStateBar(bar_id=f"{target_id}:mask_integrity", label=f"{target.name}·面具完整度", category="relationship", current_value=mind.mask_integrity, min_value=0, max_value=6),
                    PlayStateBar(bar_id=f"{target_id}:pressure_load", label=f"{target.name}·心理压力", category="relationship", current_value=mind.pressure_load, min_value=0, max_value=6),
                    PlayStateBar(bar_id=f"{target_id}:humiliation_risk", label=f"{target.name}·失态风险", category="relationship", current_value=mind.humiliation_risk, min_value=0, max_value=6),
                ]
            )
    return bars[:16]


def build_v2_relationship_snapshot(state: UrbanWorldState) -> PlayRelationshipStateSnapshot:
    return PlayRelationshipStateSnapshot(
        scene_heat=state.scene_heat,
        public_image=state.public_image,
        secret_exposure=state.secret_exposure,
        route_lock=state.route_lock,
        current_route_target_id=state.current_route_target_id,
        targets=[
            PlayRelationshipTargetState(
                character_id=target.character_id,
                name=target.name,
                affection=target.affection,
                trust=target.trust,
                tension=target.tension,
                suspicion=target.suspicion,
                dependency=target.dependency,
                is_route_focus=target.is_route_focus,
            )
            for target in state.relationships.values()
        ][:8],
    )


def build_v2_feedback(state: UrbanWorldState) -> PlayFeedbackSnapshot:
    return PlayFeedbackSnapshot(
        ledgers=PlayLedgerSnapshot(
            success=PlaySuccessLedger(proof_progress=0, coalition_progress=0, order_progress=0, settlement_progress=0),
            cost=PlayCostLedger(public_cost=0, relationship_cost=0, procedural_cost=0, coercion_cost=0),
        ),
        last_turn_axis_deltas={},
        last_turn_stance_deltas={},
        last_turn_global_deltas=dict(state.last_turn_global_deltas),
        last_turn_relationship_deltas={key: dict(value) for key, value in state.last_turn_relationship_deltas.items()},
        last_turn_tags=list(state.last_turn_tags),
        last_turn_consequences=list(state.last_turn_consequences),
        last_turn_revealed_secret_ids=list(state.last_turn_revealed_secret_ids),
    )


def build_v2_progress(plan: CompiledPlayPlan, state: UrbanWorldState) -> PlaySessionProgress:
    current_segment = plan.segments[min(state.segment_index, len(plan.segments) - 1)]
    completed_segments = min(state.segment_index, len(plan.segments))
    completion_ratio = min((completed_segments + (state.segment_progress / max(current_segment.progress_required, 1))) / len(plan.segments), 1.0)
    return PlaySessionProgress(
        completed_beats=completed_segments,
        total_beats=len(plan.segments),
        current_beat_progress=state.segment_progress,
        current_beat_goal=current_segment.progress_required,
        turn_index=state.turn_index,
        max_turns=plan.max_turns,
        completion_ratio=completion_ratio,
        display_percent=min(int(completion_ratio * 100), 100),
    )


def build_v2_snapshot(plan: CompiledPlayPlan, state: UrbanWorldState) -> PlaySessionSnapshot:
    protagonist = product_protagonist_from_plan(plan)
    segment = plan.segments[min(state.segment_index, len(plan.segments) - 1)]
    ending = public_ending_from_v2(state.ending_id, state.ending_summary)
    story_actions = state.story_actions or state.suggested_actions
    control_actions = state.control_actions
    latent_radar = build_v2_latent_radar(state)
    return PlaySessionSnapshot(
        session_id=state.session_id,
        story_id=state.story_id,
        story_mode="relationship_drama",
        story_shell_id=plan.story_shell_id,
        status=("expired" if state.status == "expired" else "completed" if state.status == "completed" else "active"),
        turn_index=state.turn_index,
        beat_index=state.segment_index + 1,
        beat_title=segment.scene_goal[:120],
        story_title=plan.title,
        narration=state.narration or plan.opening_narration,
        protagonist=protagonist,
        feedback=build_v2_feedback(state),
        progress=build_v2_progress(plan, state),
        support_surfaces=None,
        state_bars=build_v2_state_bars(plan, state),
        current_route_target_id=state.current_route_target_id,
        relationship_state=build_v2_relationship_snapshot(state),
        suggested_actions=[
            PlaySuggestedAction(suggestion_id=item.suggestion_id, action_type="story", label=item.label, prompt=item.prompt)
            for item in story_actions
        ][:3],
        story_actions=[
            PlaySuggestedAction(suggestion_id=item.suggestion_id, action_type="story", label=item.label, prompt=item.prompt)
            for item in story_actions
        ][:3],
        control_actions=[
            PlayControlAction(
                action_id=item.action_id,
                action_type=item.action_type,
                target_mode=item.target_mode,
                target_kind=item.target_kind,
                target_id=item.target_id,
                label=item.label,
                prompt=item.prompt,
            )
            for item in control_actions
        ][:3],
        latent_radar=latent_radar[:4],
        ending=ending,
    )


def build_v2_turn_trace(
    *,
    plan: CompiledPlayPlan,
    before_state: UrbanWorldState,
    result: UrbanTurnResult,
    player_input: str,
    selected_suggestion_id: str | None,
    turn_elapsed_ms: int,
    selected_story_action_id: str | None = None,
    selected_control_action_id: str | None = None,
) -> tuple[PlayTurnTrace, ProductV2TurnTracePayload]:
    ending = public_ending_from_v2(result.state.ending_id, result.state.ending_summary)
    diagnostics = dict(result.intent_stage_diagnostics or {})

    def _diag_int(key: str) -> int:
        value = diagnostics.get(key, 0)
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return max(int(round(float(value))), 0)
        return 0

    def _diag_bool(key: str) -> bool:
        value = diagnostics.get(key, False)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    intent_llm_input_tokens = _diag_int("intent_llm_input_tokens")
    intent_llm_output_tokens = _diag_int("intent_llm_output_tokens")
    intent_llm_total_tokens = _diag_int("intent_llm_total_tokens")
    micro_sim_input_tokens = _diag_int("micro_sim_input_tokens")
    micro_sim_output_tokens = _diag_int("micro_sim_output_tokens")
    micro_sim_total_tokens = _diag_int("micro_sim_total_tokens")
    compose_input_tokens = _diag_int("compose_input_tokens")
    compose_output_tokens = _diag_int("compose_output_tokens")
    compose_total_tokens = _diag_int("compose_total_tokens")
    intent_stage_input_tokens = max(intent_llm_input_tokens + micro_sim_input_tokens, 0)
    intent_stage_output_tokens = max(intent_llm_output_tokens + micro_sim_output_tokens, 0)
    intent_stage_total_tokens = max(
        _diag_int("intent_stage_total_tokens")
        or (intent_stage_input_tokens + intent_stage_output_tokens),
        0,
    )
    intent_stage_latency_ms = _diag_int("intent_stage_latency_ms")
    intent_parse_latency_ms = _diag_int("intent_parse_latency_ms")
    intent_micro_sim_stage_latency_ms = _diag_int("intent_micro_sim_stage_latency_ms")
    micro_sim_latency_ms = _diag_int("micro_sim_latency_ms")
    compose_latency_ms = _diag_int("compose_latency_ms")
    compose_pass_count = _diag_int("compose_pass_count")
    compose_pass2_retry_count = _diag_int("compose_pass2_retry_count")
    compose_pass1_latency_ms = _diag_int("compose_pass1_latency_ms")
    compose_pass2_latency_ms = _diag_int("compose_pass2_latency_ms")
    compose_pass2_invalid_reason = str(diagnostics.get("compose_pass2_invalid_reason") or "")
    compose_pass2_gate_reason = str(diagnostics.get("compose_pass2_gate_reason") or "")
    compose_budget_hit = _diag_bool("compose_budget_hit")
    delta_pack_hit = _diag_bool("delta_pack_hit")
    compose_pass2_applied = _diag_bool("compose_pass2_applied")
    compose_prewarm_status = str(diagnostics.get("compose_prewarm_status") or "")
    compose_prewarm_hit = _diag_bool("compose_prewarm_hit")
    compose_prewarm_wait_ms = _diag_int("compose_prewarm_wait_ms")
    compose_prewarm_source = str(diagnostics.get("compose_prewarm_source") or "")
    compose_prewarm_total_tokens = _diag_int("compose_prewarm_total_tokens")
    typing_final_draft_seen = _diag_bool("typing_final_draft_seen")
    typing_scope_cleared_count = _diag_int("typing_scope_cleared_count")
    compose_prewarm_stale_fragment_count = _diag_int("compose_prewarm_stale_fragment_count")
    read_phase_prewarm_tokens = _diag_int("read_phase_prewarm_tokens")
    typing_phase_prewarm_tokens = _diag_int("typing_phase_prewarm_tokens")
    submit_phase_tokens = _diag_int("submit_phase_tokens")
    turn_complexity = str(diagnostics.get("turn_complexity") or "normal")
    gateway_acquire_wait_ms = _diag_int("gateway_acquire_wait_ms")
    draft_call_count = _diag_int("draft_call_count")
    draft_input_tokens = _diag_int("draft_input_tokens")
    draft_output_tokens = _diag_int("draft_output_tokens")
    draft_total_tokens = _diag_int("draft_total_tokens")
    pre_submit_total_tokens = _diag_int("pre_submit_total_tokens")
    post_submit_total_tokens = _diag_int("post_submit_total_tokens")
    play_turn_total_tokens = _diag_int("play_turn_total_tokens")
    draft_intent_status = str(diagnostics.get("draft_intent_status") or "not_requested")
    diversity_guard_hits = _diag_int("diversity_guard_hits")
    compose_retry_count = _diag_int("compose_retry_count")
    selected_style_case_ids = str(
        diagnostics.get("selected_style_case_ids")
        or diagnostics.get("style_case_ids")
        or ""
    )
    blocked_stems = str(diagnostics.get("blocked_stems") or "")
    blocked_stems_hit = _diag_bool("blocked_stems_hit")
    soft_avoid_stems = str(diagnostics.get("soft_avoid_stems") or "")
    control_bias_applied = _diag_bool("control_bias_applied")
    control_bias_reason = str(diagnostics.get("control_bias_reason") or "")
    control_bias_from_move = str(diagnostics.get("control_bias_from_move") or "")
    control_bias_to_move = str(diagnostics.get("control_bias_to_move") or "")
    beat_delta_pack_applied = _diag_bool("beat_delta_pack_applied")
    beat_delta_pack_source = str(diagnostics.get("beat_delta_pack_source") or "")
    beat_delta_pack_snapshot_id = str(diagnostics.get("beat_delta_pack_snapshot_id") or "")
    beat_delta_pack_job_ms = _diag_int("beat_delta_pack_job_ms")
    beat_delta_pack_job_status = str(diagnostics.get("beat_delta_pack_job_status") or "")
    compose_invalid_reason = str(diagnostics.get("compose_invalid_reason") or "")
    post_submit_llm_calls = _diag_int("post_submit_llm_calls")
    single_llm_call_after_submit = _diag_bool("single_llm_call_after_submit")
    intent_llm_gate_reason = str(diagnostics.get("intent_llm_gate_reason") or "")
    micro_sim_llm_gate_reason = str(diagnostics.get("micro_sim_llm_gate_reason") or "")
    narration_compose_source = str(
        diagnostics.get("narration_compose_source")
        or diagnostics.get("narration_rewrite_source")
        or ""
    )
    submitted_with_selected_ids = bool((selected_suggestion_id or "").strip() or (selected_story_action_id or "").strip())
    submission_input_mode = "select_id" if submitted_with_selected_ids else "free_input"
    semantic_plan = result.state.last_turn_semantic_plan
    utility_top = list(semantic_plan.stake_plan.top_shifts) if semantic_plan is not None else []
    stake_top = utility_top[0] if utility_top else None
    story_debug = PlayStoryDebug(
        utility_top_shift=[
            PlayUtilityShiftItem(
                character_id=item.character_id,
                name=item.display_name,
                delta=item.utility_delta,
                reason_family=item.reason_family,
                reason_text=item.reason_text,
            )
            for item in utility_top[:3]
        ],
        stake_shift_top=(
            PlayUtilityShiftItem(
                character_id=stake_top.character_id,
                name=stake_top.display_name,
                delta=stake_top.utility_delta,
                reason_family=stake_top.reason_family,
                reason_text=stake_top.reason_text,
            )
            if stake_top is not None
            else None
        ),
        question_step=(
            PlayQuestionStepDebug(
                segment_id=semantic_plan.question_plan.segment_id,
                before_status=semantic_plan.question_plan.before_status,
                expected_status=semantic_plan.question_plan.expected_status,
                final_status=semantic_plan.question_plan.final_status,
                forced_advance=semantic_plan.question_plan.forced_advance,
                advance_reason=semantic_plan.question_plan.advance_reason,
                resolved_by=semantic_plan.question_plan.resolved_by,
                summary=semantic_plan.question_plan.summary,
            )
            if semantic_plan is not None
            else None
        ),
        event_decision=(
            PlayEventDecisionDebug(
                top_event_id=semantic_plan.event_plan.top_event_id,
                top_event_kind=semantic_plan.event_plan.top_event_kind,
                top_event_transition=semantic_plan.event_plan.top_event_transition,
                triggered_event_id=semantic_plan.event_plan.triggered_event_id,
                triggered_kind=semantic_plan.event_plan.triggered_kind,
                primary_driver=semantic_plan.event_plan.primary_driver,
                due_cost_primary_eligible=semantic_plan.event_plan.due_cost_primary_eligible,
                due_cost_forces_primary_driver_applied=semantic_plan.event_plan.due_cost_forces_primary_driver_applied,
                cost_ladder_stage=semantic_plan.event_plan.cost_ladder_stage,
                cost_ladder_primary_applies=semantic_plan.event_plan.cost_ladder_primary_applies,
                player_override_applied=semantic_plan.event_plan.player_override_applied,
                secondary_due_cost_pressure=semantic_plan.event_plan.secondary_due_cost_pressure,
                key_segment_conversion=semantic_plan.event_plan.key_segment_conversion,
                prioritized_cost_id=semantic_plan.event_plan.prioritized_cost_id,
                prioritized_cost_due_turn=semantic_plan.event_plan.prioritized_cost_due_turn,
                cost_return_priority_applied=semantic_plan.event_plan.cost_return_priority_applied,
                summary=semantic_plan.event_plan.summary,
            )
            if semantic_plan is not None
            else None
        ),
        payoff_commit=(
            PlayPayoffCommitDebug(
                committed=semantic_plan.payoff_plan.committed,
                route_kind=semantic_plan.payoff_plan.route_kind,
                global_delta_keys=list(semantic_plan.payoff_plan.global_delta_keys),
                relationship_delta_ids=list(semantic_plan.payoff_plan.relationship_delta_ids),
                owner_character_ids=list(semantic_plan.payoff_plan.owner_character_ids),
                payer_character_id=semantic_plan.payoff_plan.payer_character_id,
                beneficiary_character_id=semantic_plan.payoff_plan.beneficiary_character_id,
                linked_scene_question_id=semantic_plan.payoff_plan.linked_scene_question_id,
                return_due_turn=semantic_plan.payoff_plan.return_due_turn,
                cost_recorded=semantic_plan.payoff_plan.cost_recorded,
                control_signature_action=semantic_plan.payoff_plan.control_signature_action,
                control_signature_valid=semantic_plan.payoff_plan.control_signature_valid,
                control_signature_fail_safe_applied=semantic_plan.payoff_plan.control_signature_fail_safe_applied,
                fallback_applied=semantic_plan.payoff_plan.fallback_applied,
                summary=semantic_plan.payoff_plan.summary,
            )
            if semantic_plan is not None
            else None
        ),
        style_commit=(
            PlayStyleCommitDebug(
                key_segment=semantic_plan.style_plan.key_segment,
                reason_family=semantic_plan.style_plan.reason_family,
                signal_family=semantic_plan.style_plan.signal_family,
                cost_family=semantic_plan.style_plan.cost_family,
                cadence=semantic_plan.style_plan.cadence,
                counter_function_role=semantic_plan.style_plan.counter_function_role,
                crowd_function_role=semantic_plan.style_plan.crowd_function_role,
                counter_action_verb=semantic_plan.style_plan.counter_action_verb,
                crowd_action_verb=semantic_plan.style_plan.crowd_action_verb,
                role_lexicon_hit=semantic_plan.style_plan.role_lexicon_hit,
                force_main_clause_cost_subject=semantic_plan.style_plan.force_main_clause_cost_subject,
                payer_character_id=semantic_plan.style_plan.payer_character_id,
                beneficiary_character_id=semantic_plan.style_plan.beneficiary_character_id,
                cost_subject_focus=semantic_plan.style_plan.cost_subject_focus,
                shell_anchor_tokens=list(semantic_plan.style_plan.shell_anchor_tokens),
                shell_anchor_hit=semantic_plan.style_plan.shell_anchor_hit,
                summary=semantic_plan.style_plan.summary,
            )
            if semantic_plan is not None
            else None
        ),
        cost_route=(
            PlayCostRouteDebug(
                route_id=result.state.last_turn_cost_route.route_id,
                route_kind=result.state.last_turn_cost_route.route_kind,
                source_move_family=result.state.last_turn_cost_route.source_move_family,
                source_control_action=result.state.last_turn_cost_route.source_control_action,
                source_scene_frame=result.state.last_turn_cost_route.source_scene_frame,
                source_segment_role=result.state.last_turn_cost_route.source_segment_role,
                target_character_ids=list(result.state.last_turn_cost_route.target_character_ids),
                owner_character_ids=list(result.state.last_turn_cost_route.owner_character_ids),
                payer_character_id=result.state.last_turn_cost_route.payer_character_id,
                beneficiary_character_id=result.state.last_turn_cost_route.beneficiary_character_id,
                linked_scene_question_id=result.state.last_turn_cost_route.linked_scene_question_id,
                scene_question_focus=result.state.last_turn_cost_route.scene_question_focus,
                return_due_turn=result.state.last_turn_cost_route.return_due_turn,
                payoff_family=result.state.last_turn_cost_route.payoff_family,
                deferred_kind=result.state.last_turn_cost_route.deferred_kind,
                deferred_callback_id=result.state.last_turn_cost_route.deferred_callback_id,
                transferred_to_character_id=result.state.last_turn_cost_route.transferred_to_character_id,
            )
            if result.state.last_turn_cost_route is not None
            else None
        ),
        propagation_edge=(
            PlayPropagationEdgeDebug(
                edge_id=result.state.last_turn_propagation_edge.edge_id,
                shell_id=result.state.last_turn_propagation_edge.shell_id,
                from_node=result.state.last_turn_propagation_edge.from_node,
                to_node=result.state.last_turn_propagation_edge.to_node,
                anchor_token=result.state.last_turn_propagation_edge.anchor_token,
                signal_family=result.state.last_turn_propagation_edge.signal_family,
                note=result.state.last_turn_propagation_edge.note,
            )
            if result.state.last_turn_propagation_edge is not None
            else None
        ),
        scene_question_state=(
            PlaySceneQuestionDebug(
                segment_id=result.state.last_turn_scene_question_state.segment_id,
                question=result.state.last_turn_scene_question_state.question,
                status=result.state.last_turn_scene_question_state.status,
                previous_status=result.state.last_turn_scene_question_state.previous_status,
                resolved_by=result.state.last_turn_scene_question_state.resolved_by,
                updated_turn_index=result.state.last_turn_scene_question_state.updated_turn_index,
                summary=result.state.last_turn_scene_question_state.summary,
            )
            if result.state.last_turn_scene_question_state is not None
            else None
        ),
        callback_status=(
            PlayCallbackStatusDebug(
                created_count=result.state.last_turn_callback_status.created_count,
                matured_count=result.state.last_turn_callback_status.matured_count,
                consumed_count=result.state.last_turn_callback_status.consumed_count,
                pending_count=result.state.last_turn_callback_status.pending_count,
                triggered_callback_id=result.state.last_turn_callback_status.triggered_callback_id,
                triggered_kind=result.state.last_turn_callback_status.triggered_kind,
                summary=result.state.last_turn_callback_status.summary,
            )
            if result.state.last_turn_callback_status is not None
            else None
        ),
        summary=result.state.last_turn_story_debug_summary or "",
    )
    resolution = PlayResolutionEffect(
        tactic_summary=result.progress_summary,
        move_family=result.intent.move_family,
        scene_frame=result.intent.scene_frame,
        target_character_ids=[result.intent.target_id] if result.intent.target_id else [],
        global_state_changes=dict(result.state.last_turn_global_deltas),
        relationship_state_changes={key: dict(value) for key, value in result.state.last_turn_relationship_deltas.items()},
        revealed_secret_ids=list(result.state.last_turn_revealed_secret_ids),
        ending_id=ending.ending_id if ending else None,
        ending_trigger_reason="v2_direct" if result.ending_triggered else None,
        pressure_note=result.progress_summary,
        control_action=result.intent.control_action,
        control_source=result.intent.control_source,
        control_target_kind=result.intent.control_target_kind,
        control_target_id=result.intent.control_target_id,
        intent_compile_source=result.intent.intent_compile_source,
        intent_confidence=result.intent.intent_confidence,
        deviation_type=result.intent.deviation_type,
        deviation_note=result.intent.deviation_note,
        alternatives=list(result.intent.alternatives),
        control_resolution=(
            PlayControlResolution(
                action_type=result.control_resolution.action_type,
                target_mode=result.control_resolution.target_mode,
                target_kind=result.control_resolution.target_kind,
                target_id=result.control_resolution.target_id,
                target_event_id=result.control_resolution.target_event_id,
                applied=result.control_resolution.applied,
                summary=result.control_resolution.summary,
                tags=list(result.control_resolution.tags),
            )
            if result.control_resolution is not None
            else None
        ),
        latent_radar=build_v2_latent_radar(result.state)[:4],
        story_debug=story_debug,
    )
    resolved_story_action_id = result.intent.mapped_suggestion_id or selected_story_action_id or selected_suggestion_id
    trace = PlayTurnTrace(
        turn_index=result.state.turn_index,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        player_input=player_input,
        selected_suggestion_id=selected_suggestion_id,
        selected_story_action_id=resolved_story_action_id,
        submission_input_mode=submission_input_mode,
        selected_control_action_id=selected_control_action_id,
        turn_tags=list(result.state.last_turn_tags),
        interpret_source="heuristic",
        render_source="heuristic",
        execution_frame="public" if result.intent.scene_frame == "public" else "procedural",
        interpret_attempts=1,
        ending_judge_source="heuristic" if result.ending_triggered else "skipped",
        pyrrhic_critic_source="skipped",
        ending_judge_attempts=1 if result.ending_triggered else 0,
        pyrrhic_critic_attempts=0,
        render_attempts=1,
        turn_elapsed_ms=turn_elapsed_ms,
        interpret_elapsed_ms=intent_stage_latency_ms,
        ending_judge_elapsed_ms=0,
        pyrrhic_critic_elapsed_ms=0,
        render_elapsed_ms=0,
        session_cache_enabled=False,
        used_previous_response_id=False,
        input_tokens=intent_stage_input_tokens,
        output_tokens=intent_stage_output_tokens,
        total_tokens=intent_stage_total_tokens,
        interpret_usage={
            "intent_stage_input_tokens": intent_stage_input_tokens,
            "intent_stage_output_tokens": intent_stage_output_tokens,
            "intent_stage_total_tokens": intent_stage_total_tokens,
            "intent_stage_latency_ms": intent_stage_latency_ms,
            "intent_parse_latency_ms": intent_parse_latency_ms,
            "intent_micro_sim_stage_latency_ms": intent_micro_sim_stage_latency_ms,
            "intent_llm_input_tokens": intent_llm_input_tokens,
            "intent_llm_output_tokens": intent_llm_output_tokens,
            "intent_llm_total_tokens": intent_llm_total_tokens,
            "micro_sim_input_tokens": micro_sim_input_tokens,
            "micro_sim_output_tokens": micro_sim_output_tokens,
            "micro_sim_total_tokens": micro_sim_total_tokens,
            "micro_sim_latency_ms": micro_sim_latency_ms,
            "compose_input_tokens": compose_input_tokens,
            "compose_output_tokens": compose_output_tokens,
            "compose_total_tokens": compose_total_tokens,
            "compose_latency_ms": compose_latency_ms,
            "compose_pass_count": compose_pass_count,
            "compose_pass2_retry_count": compose_pass2_retry_count,
            "compose_pass1_latency_ms": compose_pass1_latency_ms,
            "compose_pass2_latency_ms": compose_pass2_latency_ms,
            "compose_pass2_invalid_reason": compose_pass2_invalid_reason,
            "compose_pass2_gate_reason": compose_pass2_gate_reason,
            "compose_budget_hit": 1 if compose_budget_hit else 0,
            "delta_pack_hit": 1 if delta_pack_hit else 0,
            "compose_pass2_applied": 1 if compose_pass2_applied else 0,
            "compose_prewarm_status": compose_prewarm_status,
            "compose_prewarm_hit": 1 if compose_prewarm_hit else 0,
            "compose_prewarm_wait_ms": compose_prewarm_wait_ms,
            "compose_prewarm_source": compose_prewarm_source,
            "compose_prewarm_total_tokens": compose_prewarm_total_tokens,
            "typing_final_draft_seen": 1 if typing_final_draft_seen else 0,
            "typing_scope_cleared_count": typing_scope_cleared_count,
            "compose_prewarm_stale_fragment_count": compose_prewarm_stale_fragment_count,
            "read_phase_prewarm_tokens": read_phase_prewarm_tokens,
            "typing_phase_prewarm_tokens": typing_phase_prewarm_tokens,
            "submit_phase_tokens": submit_phase_tokens,
            "turn_complexity": turn_complexity,
            "gateway_acquire_wait_ms": gateway_acquire_wait_ms,
            "draft_call_count": draft_call_count,
            "draft_input_tokens": draft_input_tokens,
            "draft_output_tokens": draft_output_tokens,
            "draft_total_tokens": draft_total_tokens,
            "pre_submit_total_tokens": pre_submit_total_tokens,
            "post_submit_total_tokens": post_submit_total_tokens,
            "play_turn_total_tokens": play_turn_total_tokens,
            "draft_intent_status": draft_intent_status,
            "intent_compile_source": str(result.intent.intent_compile_source),
            "micro_sim_status": str(diagnostics.get("micro_sim_status") or ""),
            "selected_style_case_ids": selected_style_case_ids,
            "diversity_guard_hits": diversity_guard_hits,
            "compose_retry_count": compose_retry_count,
            "blocked_stems": blocked_stems,
            "blocked_stems_hit": blocked_stems_hit,
            "soft_avoid_stems": soft_avoid_stems,
            "post_submit_llm_calls": post_submit_llm_calls,
            "single_llm_call_after_submit": 1 if single_llm_call_after_submit else 0,
            "intent_llm_gate_reason": intent_llm_gate_reason,
            "micro_sim_llm_gate_reason": micro_sim_llm_gate_reason,
            "compose_invalid_reason": compose_invalid_reason,
            "control_bias_applied": 1 if control_bias_applied else 0,
            "control_bias_reason": control_bias_reason,
            "control_bias_from_move": control_bias_from_move,
            "control_bias_to_move": control_bias_to_move,
            "beat_delta_pack_applied": 1 if beat_delta_pack_applied else 0,
            "beat_delta_pack_source": beat_delta_pack_source,
            "beat_delta_pack_snapshot_id": beat_delta_pack_snapshot_id,
            "beat_delta_pack_job_ms": beat_delta_pack_job_ms,
            "beat_delta_pack_job_status": beat_delta_pack_job_status,
            "narration_compose_source": narration_compose_source,
            "storylet_matches_count": _diag_int("storylet_matches_count"),
            "storylet_matches_ids": ",".join(
                str(item).strip()
                for item in (diagnostics.get("storylet_matches_ids") or [])
                if str(item).strip()
            ),
            "memory_context_active_hooks": _diag_int("memory_context_active_hooks"),
            "memory_context_revealed_secrets": _diag_int("memory_context_revealed_secrets"),
            "memory_context_total_chars_sent": _diag_int("memory_context_total_chars_sent"),
            "memory_context_npc_pressure_count": _diag_int("memory_context_npc_pressure_count"),
            "submission_input_mode": submission_input_mode,
            "submitted_with_selected_ids": 1 if submitted_with_selected_ids else 0,
        },
        render_usage={"render_elapsed_ms": 0, "semantic_contract": "v2"},
        beat_index_before=before_state.segment_index + 1,
        beat_title_before=plan.segments[min(before_state.segment_index, len(plan.segments) - 1)].scene_goal[:120],
        beat_index_after=result.state.segment_index + 1,
        beat_title_after=plan.segments[min(result.state.segment_index, len(plan.segments) - 1)].scene_goal[:120],
        status_after="completed" if result.state.status == "completed" else "active",
        lane_id=result.intent.lane_id,
        intent_compile_source=result.intent.intent_compile_source,
        intent_confidence=result.intent.intent_confidence,
        control_source=result.intent.control_source,
        deviation_type=result.intent.deviation_type,
        move_family=result.intent.move_family,
        scene_frame=result.intent.scene_frame,
        target_character_ids=[result.intent.target_id] if result.intent.target_id else [],
        global_state_changes=dict(result.state.last_turn_global_deltas),
        relationship_state_changes={key: dict(value) for key, value in result.state.last_turn_relationship_deltas.items()},
        revealed_secret_ids=list(result.state.last_turn_revealed_secret_ids),
        resolution=resolution,
        story_debug=story_debug,
    )
    return trace, ProductV2TurnTracePayload(
        ending_family=ending.ending_id if ending is not None else None,
        lane_id=result.intent.lane_id,
    )
