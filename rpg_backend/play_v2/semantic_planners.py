from __future__ import annotations

import math
import re
from typing import Iterable

from rpg_backend.author.normalize import trim_text, unique_preserve
from rpg_backend.author_v2.contracts import (
    CompiledPlayPlan,
    CompiledSegment,
    NpcStrategicIntent,
)
from rpg_backend.config import get_settings
from rpg_backend.play_v2.contracts import (
    CallbackQueueItem,
    CostQuestionFocus,
    CostRouteRecord,
    NpcUtilityDeltaItem,
    SceneQuestionStateRecord,
    TurnSemanticEventPlan,
    TurnSemanticPayoffPlan,
    TurnSemanticQuestionPlan,
    TurnSemanticStakePlan,
    TurnSemanticStylePlan,
    UnresolvedCostRecord,
    UrbanTurnIntent,
    UrbanWorldState,
)
from rpg_backend.play_v2.shell_propagation import pick_shell_edge

_QUESTION_STATUS_ORDER: tuple[str, ...] = ("open", "tightening", "flip", "resolved")


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _question_status_rank(status: str) -> int:
    try:
        return _QUESTION_STATUS_ORDER.index(status)
    except ValueError:
        return 0


def _next_question_status(status: str) -> str:
    rank = _question_status_rank(status)
    if rank >= len(_QUESTION_STATUS_ORDER) - 1:
        return "resolved"
    return _QUESTION_STATUS_ORDER[rank + 1]


def _target_name(plan: CompiledPlayPlan, target_id: str | None) -> str:
    return next((member.display_name for member in plan.cast if member.character_id == target_id), "对方")


def _resolve_question_cost_rule(*, plan: CompiledPlayPlan, segment: CompiledSegment):
    policy = plan.semantic_strategy_pack.cost_return_policy
    item = policy.by_segment_id.get(segment.segment_id)
    if item is not None:
        return item
    return next(
        (
            rule
            for rule in policy.by_segment_id.values()
            if rule.segment_role == segment.segment_role
        ),
        None,
    )


def _cost_visibility_rule(*, plan: CompiledPlayPlan, segment: CompiledSegment):
    policy = plan.semantic_strategy_pack.cost_visibility_contract
    item = policy.by_segment_id.get(segment.segment_id)
    if item is not None:
        return item
    return next(
        (
            rule
            for rule in policy.by_segment_id.values()
            if rule.segment_role == segment.segment_role
        ),
        None,
    )


def _question_progress_rule_v2(*, plan: CompiledPlayPlan, segment: CompiledSegment):
    policy = plan.semantic_strategy_pack.question_progress_policy_v2
    item = policy.by_segment_id.get(segment.segment_id)
    if item is not None:
        return item
    return next(
        (
            rule
            for rule in policy.by_segment_id.values()
            if rule.segment_role == segment.segment_role
        ),
        None,
    )


def _cost_ladder_rule_for_cost(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    cost: UnresolvedCostRecord,
):
    policy = plan.semantic_strategy_pack.cost_escalation_ladder_policy_v8
    if not policy.enabled:
        return None
    direct = policy.by_segment_id.get(cost.source_segment_id)
    if direct is not None:
        return direct
    source_segment = next((item for item in plan.segments if item.segment_id == cost.source_segment_id), None)
    if source_segment is not None:
        by_role = next(
            (item for item in policy.by_segment_id.values() if item.segment_role == source_segment.segment_role),
            None,
        )
        if by_role is not None:
            return by_role
    return policy.by_segment_id.get(segment.segment_id)


def _cost_ladder_stage_for_turn(
    *,
    turn_index: int,
    cost: UnresolvedCostRecord,
    ladder_rule,
) -> int:  # noqa: ANN001
    if ladder_rule is None:
        return _clamp(int(cost.ladder_stage or 1), 1, 3)
    age = max(0, int(turn_index) - int(cost.source_turn_index))
    stage = 1
    if age >= int(ladder_rule.stage3_turn_offset):
        stage = 3
    elif age >= int(ladder_rule.stage2_turn_offset):
        stage = 2
    elif age >= int(ladder_rule.stage1_turn_offset):
        stage = 1
    retry_bonus = min(1, max(0, int(cost.ladder_retry_bias_steps) // 2))
    stage = min(3, stage + retry_bonus)
    if cost.ladder_defer_once_used and stage < 3 and age >= int(ladder_rule.stage2_turn_offset):
        stage = min(3, stage + 1)
    return _clamp(max(stage, int(cost.ladder_stage or 1)), 1, 3)


def _select_prioritized_unresolved_cost(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    state: UrbanWorldState,
    turn_index: int,
    include_near_due: bool,
) -> UnresolvedCostRecord | None:
    rule = _resolve_question_cost_rule(plan=plan, segment=segment)
    preferred_owner_modes = set(
        list(rule.owner_priority_modes if rule is not None else plan.semantic_strategy_pack.cost_return_policy.default_owner_priority_modes)
    )
    pending = [
        item
        for item in state.unresolved_costs
        if item.status == "pending"
    ]
    if not pending:
        return None
    due_limit = turn_index + (1 if include_near_due else 0)
    ladder_stage_by_cost: dict[str, int] = {}
    for item in pending:
        ladder_rule = _cost_ladder_rule_for_cost(plan=plan, segment=segment, cost=item)
        ladder_stage_by_cost[item.cost_id] = _cost_ladder_stage_for_turn(
            turn_index=turn_index,
            cost=item,
            ladder_rule=ladder_rule,
        )
    candidates = [
        item
        for item in pending
        if item.due_turn <= due_limit
        or int(ladder_stage_by_cost.get(item.cost_id, item.ladder_stage)) >= 2
    ]
    if not candidates and include_near_due:
        candidates = [
            item
            for item in pending
            if item.due_turn <= turn_index + 2
            or int(ladder_stage_by_cost.get(item.cost_id, item.ladder_stage)) >= 2
        ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            int(ladder_stage_by_cost.get(item.cost_id, item.ladder_stage)) * 2,
            2 if item.linked_scene_question_id == segment.segment_id else 0,
            1 if item.beneficiary_character_id in set(segment.rival_target_ids) else 0,
            1 if item.payer_character_id in set(segment.focus_target_ids + segment.rival_target_ids) else 0,
            1 if set(item.owner_character_ids) & set(segment.focus_target_ids + segment.rival_target_ids) else 0,
            1 if item.scene_question_focus == (rule.scene_question_focus if rule is not None else plan.semantic_strategy_pack.cost_return_policy.default_scene_question_focus) else 0,
            1 if item.route_kind == "deferred_cost" else 0,
            1 if "control_target" in preferred_owner_modes and item.beneficiary_character_id else 0,
            -abs(int(item.due_turn) - int(turn_index)),
            -int(item.source_turn_index),
        ),
    )


def _question_focus_sentence(
    *,
    plan: CompiledPlayPlan,
    cost_item: UnresolvedCostRecord,
) -> str:
    payer_name = _target_name(plan, cost_item.payer_character_id)
    beneficiary_name = _target_name(plan, cost_item.beneficiary_character_id)
    if cost_item.scene_question_focus == "who_takes_blame":
        return trim_text(f"这拍要回答：到底谁接锅，{payer_name}还是{beneficiary_name}。", 220)
    if cost_item.scene_question_focus == "who_gets_chased":
        return trim_text(f"这拍要回答：旧账回咬时，谁会先被追着清算，{beneficiary_name}还是{payer_name}。", 220)
    return trim_text(f"这拍要回答：这笔账最终谁来付，{payer_name}还是{beneficiary_name}。", 220)


def _choose_semantic_family(
    *,
    values: Iterable[str],
    turn_index: int,
    slot_name: str,
    recent_values: set[str],
) -> str:
    cleaned = [item for item in values if isinstance(item, str) and item.strip()]
    if not cleaned:
        return "mixed"
    slot_seed = sum(ord(char) for char in f"semantic:{slot_name}:{len(cleaned)}")
    start = (turn_index + slot_seed) % len(cleaned)
    for offset in range(len(cleaned)):
        value = cleaned[(start + offset) % len(cleaned)]
        if value in recent_values:
            continue
        return value
    return cleaned[start]


class QuestionPlanner:
    @staticmethod
    def seed(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
    ) -> TurnSemanticQuestionPlan:
        policy = plan.semantic_strategy_pack.question_progress_policy
        settings = get_settings()
        progress_v2_rule = (
            _question_progress_rule_v2(plan=plan, segment=segment)
            if settings.play_v2_policy_question_progress_v2_enabled
            else None
        )
        arc_policy = plan.semantic_strategy_pack.question_arc_policy_v2
        arc_segment = arc_policy.by_segment_id.get(segment.segment_id)
        record = state.scene_question_states.get(segment.segment_id)
        before_status = record.status if record is not None else "open"
        min_status = (
            progress_v2_rule.minimum_status
            if progress_v2_rule is not None
            else
            arc_segment.minimum_status
            if arc_segment is not None
            else policy.min_status_by_segment_role.get(segment.segment_role, "open")
        )
        turn_index = state.turn_index + 1
        expected_status = _QUESTION_STATUS_ORDER[max(_question_status_rank(before_status), _question_status_rank(min_status))]
        prioritized_cost = _select_prioritized_unresolved_cost(
            plan=plan,
            segment=segment,
            state=state,
            turn_index=turn_index,
            include_near_due=True,
        )
        scene_question_id = arc_segment.scene_question_id if arc_segment is not None else segment.segment_id
        question = trim_text(record.question if record is not None else segment.scene_goal, 220)
        summary = trim_text(f"问题目标：把「{question}」从{before_status}推进到{expected_status}。", 220)
        prioritized_cost_id: str | None = None
        prioritized_cost_focus: CostQuestionFocus | None = None
        prioritized_cost_due_turn: int | None = None
        if prioritized_cost is not None:
            ladder_rule = _cost_ladder_rule_for_cost(plan=plan, segment=segment, cost=prioritized_cost)
            ladder_stage = _cost_ladder_stage_for_turn(
                turn_index=turn_index,
                cost=prioritized_cost,
                ladder_rule=ladder_rule,
            )
            prioritized_cost_id = prioritized_cost.cost_id
            prioritized_cost_focus = prioritized_cost.scene_question_focus
            prioritized_cost_due_turn = int(prioritized_cost.due_turn)
            if progress_v2_rule is None or progress_v2_rule.require_cost_focus_when_due:
                question = _question_focus_sentence(plan=plan, cost_item=prioritized_cost)
            if ladder_stage >= 3:
                expected_status = _QUESTION_STATUS_ORDER[max(_question_status_rank(expected_status), _question_status_rank("flip"))]
            elif prioritized_cost.due_turn <= turn_index:
                expected_status = _QUESTION_STATUS_ORDER[max(_question_status_rank(expected_status), _question_status_rank("flip"))]
            else:
                expected_status = _QUESTION_STATUS_ORDER[max(_question_status_rank(expected_status), _question_status_rank("tightening"))]
            summary = trim_text(
                f"问题目标：优先回钩代价({prioritized_cost.scene_question_focus})[stage-{ladder_stage}]，把局势从{before_status}推进到{expected_status}。",
                220,
            )
        return TurnSemanticQuestionPlan(
            segment_id=scene_question_id,
            question=question,
            before_status=before_status,  # type: ignore[arg-type]
            expected_status=expected_status,  # type: ignore[arg-type]
            final_status=before_status,  # type: ignore[arg-type]
            forced_advance=False,
            advance_reason=None,
            prioritized_cost_id=prioritized_cost_id,
            prioritized_cost_focus=prioritized_cost_focus,
            prioritized_cost_due_turn=prioritized_cost_due_turn,
            summary=summary,
        )

    @staticmethod
    def advance(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
        triggered_kind: str | None,
        key_segment_conversion: bool,
    ) -> tuple[SceneQuestionStateRecord, bool, str | None]:
        policy = plan.semantic_strategy_pack.question_progress_policy
        settings = get_settings()
        progress_v2_rule = (
            _question_progress_rule_v2(plan=plan, segment=segment)
            if settings.play_v2_policy_question_progress_v2_enabled
            else None
        )
        arc_policy = plan.semantic_strategy_pack.question_arc_policy_v2
        arc_segment = arc_policy.by_segment_id.get(segment.segment_id)
        key_segment_roles = set(arc_policy.key_segment_roles or ["reveal", "terminal"])
        record = state.scene_question_states.get(segment.segment_id)
        if record is None:
            record = SceneQuestionStateRecord(
                segment_id=segment.segment_id,
                question=trim_text(segment.scene_goal, 220),
                status="open",
                previous_status=None,
                resolved_by=None,
                updated_turn_index=state.turn_index,
                summary="问题已立起。",
            )
        previous = record.status
        next_status = previous
        forced_advance = False
        advance_reason: str | None = None
        resolved_by: str | None = None
        threshold = max(int(segment.progress_required), 1)
        if previous == "open" and (state.segment_progress >= 1 or state.scene_heat >= 3):
            next_status = "tightening"
        if next_status in {"open", "tightening"} and (
            triggered_kind is not None or state.scene_heat >= 4 or state.segment_progress >= max(threshold - 1, 1)
        ):
            next_status = "flip"
        prioritized_cost = _select_prioritized_unresolved_cost(
            plan=plan,
            segment=segment,
            state=state,
            turn_index=state.turn_index,
            include_near_due=False,
        )
        if prioritized_cost is not None and _question_status_rank(next_status) < _question_status_rank("tightening"):
            next_status = "tightening"
            forced_advance = True
            advance_reason = advance_reason or "cost_return_due"
        if prioritized_cost is not None:
            ladder_rule = _cost_ladder_rule_for_cost(plan=plan, segment=segment, cost=prioritized_cost)
            ladder_stage = _cost_ladder_stage_for_turn(
                turn_index=state.turn_index,
                cost=prioritized_cost,
                ladder_rule=ladder_rule,
            )
            if ladder_stage >= 3 and _question_status_rank(next_status) < _question_status_rank("flip"):
                next_status = "flip"
                forced_advance = True
                advance_reason = advance_reason or "cost_ladder_stage3"
        key_segment = segment.segment_role in key_segment_roles
        force_resolve_secret_exposure = (
            arc_segment.force_resolve_secret_exposure
            if arc_segment is not None
            else policy.key_segment_force_resolve_secret_exposure
        )
        force_resolve_progress_threshold = (
            arc_segment.force_resolve_progress_threshold
            if arc_segment is not None
            else policy.key_segment_force_resolve_progress_threshold
        )
        require_conversion = (
            arc_segment.key_segment_require_conversion_if_no_trigger
            if arc_segment is not None
            else policy.key_segment_force_flip_if_no_trigger
        )
        if key_segment and (
            triggered_kind is not None
            or key_segment_conversion
            or state.segment_progress >= threshold
            or state.secret_exposure >= force_resolve_secret_exposure
        ):
            next_status = "resolved"
            resolved_by = (
                f"latent:{triggered_kind}"
                if triggered_kind is not None
                else "key_segment_conversion"
                if key_segment_conversion
                else "progress_threshold"
            )
        if next_status == previous and (progress_v2_rule is None or progress_v2_rule.require_non_stall_advance):
            next_status = _next_question_status(previous)
            if next_status != previous:
                forced_advance = True
                advance_reason = "same_state_blocked"
        if key_segment and triggered_kind is None and next_status != "resolved":
            if prioritized_cost is not None and _question_status_rank(next_status) < _question_status_rank("flip"):
                next_status = "flip"
                forced_advance = True
                advance_reason = "cost_return_due_key_segment"
            effective_require_conversion = (
                bool(progress_v2_rule.key_segment_force_flip_if_no_trigger)
                if progress_v2_rule is not None
                else bool(require_conversion)
            )
            if effective_require_conversion and _question_status_rank(next_status) < _question_status_rank("flip"):
                next_status = "flip"
                forced_advance = True
                advance_reason = "key_segment_conversion_pass"
            if (
                state.segment_progress >= max(threshold, force_resolve_progress_threshold)
                or state.secret_exposure >= force_resolve_secret_exposure
            ):
                next_status = "resolved"
                forced_advance = True
                advance_reason = "key_segment_forced_resolve"
                resolved_by = resolved_by or "forced_progress_threshold"
        minimum_status = (
            progress_v2_rule.minimum_status
            if progress_v2_rule is not None
            else policy.min_status_by_segment_role.get(segment.segment_role, "open")
        )
        if _question_status_rank(next_status) < _question_status_rank(minimum_status):
            next_status = minimum_status
            forced_advance = True
            advance_reason = advance_reason or "policy_minimum_status"
        summary = {
            "open": f"问题已立起：{record.question}",
            "tightening": f"问题收紧：{record.question}",
            "flip": f"问题翻面：{record.question}",
            "resolved": f"问题落锤：{record.question}",
        }[next_status]
        updated = record.model_copy(
            update={
                "previous_status": previous,
                "status": next_status,
                "resolved_by": resolved_by or record.resolved_by,
                "updated_turn_index": state.turn_index,
                "summary": trim_text(summary, 220),
            }
        )
        state.scene_question_states[segment.segment_id] = updated
        return updated, forced_advance, advance_reason


class StylePlanner:
    @staticmethod
    def seed(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
    ) -> TurnSemanticStylePlan:
        profile = segment.segment_style_profile
        style_register = plan.semantic_strategy_pack.style_register
        register_rule = style_register.by_segment_role.get(segment.segment_role, style_register.default_rule)
        segment_interest = plan.semantic_strategy_pack.segment_interest_policy.by_segment_id.get(segment.segment_id)
        role_divergence = plan.semantic_strategy_pack.role_divergence_matrix.by_segment_id.get(segment.segment_id)
        divergence_policy = plan.semantic_strategy_pack.supporting_divergence_policy
        propagation_policy = plan.semantic_strategy_pack.propagation_priority_by_segment
        recent_clause = {
            item.split(":")[-1]
            for item in state.recent_clause_family_ids[:3]
            if isinstance(item, str) and item
        }
        reason_pool = unique_preserve([*list(register_rule.reason_families or []), *list(profile.reason_families or []), "mixed"])
        signal_pool = unique_preserve([*list(register_rule.signal_families or []), *list(profile.signal_families or []), "mixed"])
        cost_pool = unique_preserve([*list(register_rule.cost_families or []), *list(profile.cost_families or []), "mixed"])
        cadence_pool = unique_preserve([*list(register_rule.cadence_order or []), *list(profile.cadence_order or []), "mixed"])
        primary_reason_pool = unique_preserve(
            [*(list(segment_interest.reason_priority) if segment_interest is not None else []), *reason_pool]
        )
        reason_family = _choose_semantic_family(
            values=primary_reason_pool,
            turn_index=state.turn_index,
            slot_name="reason_primary",
            recent_values=recent_clause,
        )
        counter_priority = (
            list(role_divergence.counter_reason_priority)
            if role_divergence is not None
            else list(divergence_policy.counter_reason_priority_by_segment_role.get(segment.segment_role, []))
        )
        crowd_priority = (
            list(role_divergence.crowd_reason_priority)
            if role_divergence is not None
            else list(divergence_policy.crowd_reason_priority_by_segment_role.get(segment.segment_role, []))
        )
        counter_reason = _choose_semantic_family(
            values=unique_preserve([*counter_priority, *reason_pool]),
            turn_index=state.turn_index,
            slot_name="reason_counter",
            recent_values=recent_clause,
        )
        crowd_reason = _choose_semantic_family(
            values=unique_preserve([*crowd_priority, *reason_pool]),
            turn_index=state.turn_index,
            slot_name="reason_crowd",
            recent_values={*recent_clause, counter_reason},
        )
        if crowd_reason == counter_reason:
            fallback_crowd = next((item for item in crowd_priority if item != counter_reason), None)
            if fallback_crowd:
                crowd_reason = fallback_crowd
            elif counter_reason != "self_preserve":
                crowd_reason = "self_preserve"
            else:
                crowd_reason = "opportunity_window"
        signal_family = _choose_semantic_family(
            values=signal_pool,
            turn_index=state.turn_index,
            slot_name="signal",
            recent_values=recent_clause,
        )
        preferred_signal = propagation_policy.signal_family_bias_by_segment_role.get(segment.segment_role)
        if preferred_signal in set(signal_pool):
            signal_family = preferred_signal
        if plan.story_shell_id == "entertainment_scandal" and "public_wave" in signal_pool:
            signal_family = "public_wave"
        elif plan.story_shell_id == "campus_romance" and "peer_spread" in signal_pool:
            signal_family = "peer_spread"
        cost_family = _choose_semantic_family(
            values=cost_pool,
            turn_index=state.turn_index,
            slot_name="cost",
            recent_values=recent_clause,
        )
        cadence = _choose_semantic_family(
            values=cadence_pool,
            turn_index=state.turn_index,
            slot_name="cadence",
            recent_values=recent_clause,
        )
        return TurnSemanticStylePlan(
            key_segment=segment.segment_role in {"reveal", "terminal"},
            reason_family=reason_family,
            counter_reason_family=counter_reason,
            crowd_reason_family=crowd_reason,
            signal_family=signal_family,
            cost_family=cost_family,
            cadence=cadence,
            shell_anchor_tokens=list(unique_preserve([*list(register_rule.shell_anchor_tokens[:6]), *list(profile.shell_anchor_tokens[:6])])[:6]),
            shell_anchor_hit=False,
            summary=trim_text("文风落地目标：主句先写原因，再写信号，再落代价。", 220),
        )


class PayoffPlanner:
    @staticmethod
    def _cost_return_defaults(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
    ) -> tuple[int, list[str], CostQuestionFocus]:
        settings = get_settings()
        if settings.play_v2_policy_cost_visibility_enabled:
            visibility_rule = _cost_visibility_rule(plan=plan, segment=segment)
            if visibility_rule is not None:
                policy = plan.semantic_strategy_pack.cost_return_policy
                item = policy.by_segment_id.get(segment.segment_id)
                owner_priority = (
                    list(item.owner_priority_modes)
                    if item is not None and item.owner_priority_modes
                    else list(policy.default_owner_priority_modes)
                )
                question_focus = item.scene_question_focus if item is not None else policy.default_scene_question_focus
                return int(visibility_rule.max_return_turns), owner_priority, question_focus
        policy = plan.semantic_strategy_pack.cost_return_policy
        item = policy.by_segment_id.get(segment.segment_id)
        if item is not None:
            return int(item.max_return_turns), list(item.owner_priority_modes), item.scene_question_focus
        return (
            int(policy.default_max_return_turns),
            list(policy.default_owner_priority_modes),
            policy.default_scene_question_focus,
        )

    @staticmethod
    def _route_intensity_multiplier(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
        route_kind: str,
        payoff_family: str,
    ) -> float:
        profile = plan.semantic_strategy_pack.cost_intensity_profile
        segment_mult = float(profile.segment_role_multiplier.get(segment.segment_role, 1.0) or 1.0)
        control_mult = float(profile.control_action_multiplier.get(intent.control_action, 1.0) or 1.0)
        shell_mult = float(profile.shell_multiplier.get(plan.story_shell_id, 1.0) or 1.0)
        payoff_mult = float(profile.payoff_family_multiplier.get(payoff_family, 1.0) or 1.0)
        latent_pressure = max(
            int(state.relationship_debt_pressure),
            int(state.public_wave_pressure),
            int(state.secret_pressure),
            int(state.npc_action_pressure),
        )
        pressure_bonus = min(
            float(profile.latent_pressure_bonus_cap),
            float(profile.latent_pressure_step_bonus) * float(latent_pressure),
        )
        route_bonus = float(profile.deferred_route_bonus) if route_kind in {"deferred_cost", "transferred_cost"} else 0.0
        return max(0.5, min(2.4, segment_mult * control_mult * shell_mult * payoff_mult * (1.0 + pressure_bonus + route_bonus)))

    @staticmethod
    def _scaled_value(*, value: int, multiplier: float, min_non_zero: int, max_abs: int) -> int:
        if value == 0:
            return 0
        scaled_float = float(value) * float(multiplier)
        scaled = int(math.floor(scaled_float)) if scaled_float > 0 else int(math.ceil(scaled_float))
        if scaled == 0:
            scaled = min_non_zero if value > 0 else -min_non_zero
        scaled = max(-max_abs, min(max_abs, scaled))
        return scaled

    @staticmethod
    def _scale_delta_map(
        *,
        delta_map: dict[str, int],
        multiplier: float,
        min_non_zero: int,
        max_abs: int,
    ) -> dict[str, int]:
        output: dict[str, int] = {}
        for key, value in delta_map.items():
            scaled = PayoffPlanner._scaled_value(
                value=int(value),
                multiplier=multiplier,
                min_non_zero=min_non_zero,
                max_abs=max_abs,
            )
            if scaled != 0:
                output[key] = scaled
        return output

    @staticmethod
    def _rule_score(rule, *, intent: UrbanTurnIntent, segment: CompiledSegment) -> int:  # noqa: ANN001
        score = 0
        if rule.control_action == "any":
            score += 1
        elif rule.control_action == intent.control_action:
            score += 3
        else:
            return -1
        if rule.scene_frame == "any":
            score += 1
        elif rule.scene_frame == intent.scene_frame:
            score += 2
        else:
            return -1
        if rule.segment_role == "any":
            score += 1
        elif rule.segment_role == segment.segment_role:
            score += 2
        else:
            return -1
        return score

    @staticmethod
    def _select_cost_rule(*, plan: CompiledPlayPlan, intent: UrbanTurnIntent, segment: CompiledSegment):  # noqa: ANN001
        matrix = plan.semantic_strategy_pack.cost_routing_matrix
        candidates = [rule for rule in matrix.rules if rule.move_family == intent.move_family]
        if not candidates:
            raise ValueError(f"missing cost routing rule for move family: {intent.move_family}")
        return max(candidates, key=lambda rule: (PayoffPlanner._rule_score(rule, intent=intent, segment=segment), rule.rule_id))

    @staticmethod
    def _ownership_rule_score(rule, *, intent: UrbanTurnIntent, segment: CompiledSegment) -> int:  # noqa: ANN001
        score = 0
        if rule.control_action == "any":
            score += 1
        elif rule.control_action == intent.control_action:
            score += 3
        else:
            return -1
        if rule.segment_role == "any":
            score += 1
        elif rule.segment_role == segment.segment_role:
            score += 3
        else:
            return -1
        return score

    @staticmethod
    def _select_cost_ownership_rule(*, plan: CompiledPlayPlan, intent: UrbanTurnIntent, segment: CompiledSegment):  # noqa: ANN001
        policy = plan.semantic_strategy_pack.cost_ownership_matrix_v2
        candidates = [rule for rule in policy.rules if rule.move_family == intent.move_family]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda rule: (
                PayoffPlanner._ownership_rule_score(rule, intent=intent, segment=segment),
                rule.rule_id,
            ),
        )

    @staticmethod
    def _resolve_owner_ids(
        *,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        owner_mode: str | None,
    ) -> list[str]:
        mode = str(owner_mode or "target")
        if mode == "control_target" and intent.control_target_id:
            return [intent.control_target_id]
        if mode == "rival" and segment.rival_target_ids:
            return [segment.rival_target_ids[0]]
        if mode == "focus" and segment.focus_target_ids:
            return [segment.focus_target_ids[0]]
        if mode == "route_target":
            route_target = state.current_route_target_id or (plan.route_target_ids[0] if plan.route_target_ids else None)
            if route_target:
                return [route_target]
        if mode == "active":
            candidate = next((item for item in state.active_character_ids if item != intent.target_id), None)
            if candidate:
                return [candidate]
        if mode == "actor":
            actor = state.current_route_target_id or intent.target_id
            if actor:
                return [actor]
        if intent.target_id:
            return [intent.target_id]
        return []

    @staticmethod
    def _resolve_owner_ids_by_priority(
        *,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        owner_priority_modes: list[str],
    ) -> list[str]:
        for mode in owner_priority_modes[:4]:
            owner_ids = PayoffPlanner._resolve_owner_ids(
                plan=plan,
                state=state,
                segment=segment,
                intent=intent,
                owner_mode=mode,
            )
            if owner_ids:
                return owner_ids
        return []

    @staticmethod
    def _select_callback_rule(*, plan: CompiledPlayPlan, intent: UrbanTurnIntent):  # noqa: ANN001
        policy = plan.semantic_strategy_pack.callback_commit_policy_v2
        candidates = [rule for rule in policy.rules if rule.move_family == intent.move_family and rule.enabled]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda rule: (
                2 if rule.control_action == intent.control_action else 1 if rule.control_action == "any" else 0,
                rule.rule_id,
            ),
        )

    @staticmethod
    def plan_cost_route(
        *,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        intent: UrbanTurnIntent,
        segment: CompiledSegment,
    ) -> CostRouteRecord:
        matrix = plan.semantic_strategy_pack.cost_routing_matrix
        intensity_profile = plan.semantic_strategy_pack.cost_intensity_profile
        max_return_turns, owner_priority_modes, question_focus = PayoffPlanner._cost_return_defaults(
            plan=plan,
            segment=segment,
        )
        rule = PayoffPlanner._select_cost_rule(plan=plan, intent=intent, segment=segment)
        ownership_rule = PayoffPlanner._select_cost_ownership_rule(plan=plan, intent=intent, segment=segment)
        owner_mode = ownership_rule.owner_mode if ownership_rule is not None else plan.semantic_strategy_pack.cost_ownership_matrix_v2.fallback_owner_mode
        owner_ids = PayoffPlanner._resolve_owner_ids(
            plan=plan,
            state=state,
            segment=segment,
            intent=intent,
            owner_mode=owner_mode,
        )
        if not owner_ids:
            owner_ids = PayoffPlanner._resolve_owner_ids_by_priority(
                plan=plan,
                state=state,
                segment=segment,
                intent=intent,
                owner_priority_modes=owner_priority_modes,
            )
        target_member = next((member for member in plan.cast if member.character_id in set(owner_ids)), None)
        payoff_family = target_member.strategic_intent.regression_payoff if target_member is not None else rule.fallback_payoff_family
        beneficiary_id = (
            intent.control_target_id
            if intent.control_action == "redirect" and intent.control_target_id
            else intent.target_id
        )
        payer_id = owner_ids[0] if owner_ids else intent.target_id
        if beneficiary_id == payer_id:
            fallback_beneficiary = next(
                (
                    item
                    for item in unique_preserve(
                        [
                            *segment.rival_target_ids,
                            *segment.focus_target_ids,
                            *state.active_character_ids,
                            *plan.route_target_ids,
                        ]
                    )
                    if item and item != payer_id
                ),
                None,
            )
            if fallback_beneficiary is not None:
                beneficiary_id = fallback_beneficiary
        due_turn = int(state.turn_index + max(1, min(3, int(max_return_turns))))
        intensity = PayoffPlanner._route_intensity_multiplier(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
            route_kind=rule.route_kind,
            payoff_family=payoff_family,
        )
        global_deltas = PayoffPlanner._scale_delta_map(
            delta_map=dict(rule.global_deltas),
            multiplier=intensity,
            min_non_zero=intensity_profile.min_non_zero_delta,
            max_abs=intensity_profile.max_abs_delta_per_key,
        )
        if intent.scene_frame != "private":
            global_deltas["scene_heat"] = int(global_deltas.get("scene_heat", 0)) + int(matrix.public_scene_heat_bonus)
        if segment.segment_role in {"reveal", "terminal"}:
            global_deltas["scene_heat"] = int(global_deltas.get("scene_heat", 0)) + int(matrix.key_segment_heat_bonus)
        global_deltas = PayoffPlanner._scale_delta_map(
            delta_map=global_deltas,
            multiplier=1.0,
            min_non_zero=intensity_profile.min_non_zero_delta,
            max_abs=intensity_profile.max_abs_delta_per_key,
        )
        rel_deltas: dict[str, dict[str, int]] = {}
        if owner_ids and rule.target_relationship_deltas:
            scaled = PayoffPlanner._scale_delta_map(
                delta_map=dict(rule.target_relationship_deltas),
                multiplier=intensity,
                min_non_zero=intensity_profile.min_non_zero_delta,
                max_abs=intensity_profile.max_abs_delta_per_key,
            )
            if scaled:
                for owner_id in owner_ids[:2]:
                    rel_deltas[owner_id] = dict(scaled)
        transferred_target = None
        if intent.control_action == "redirect":
            if ownership_rule is not None and ownership_rule.transferred_owner_mode:
                transferred_ids = PayoffPlanner._resolve_owner_ids(
                    plan=plan,
                    state=state,
                    segment=segment,
                    intent=intent,
                    owner_mode=ownership_rule.transferred_owner_mode,
                )
                transferred_target = transferred_ids[0] if transferred_ids else None
            else:
                transferred_target = intent.control_target_id
        return CostRouteRecord(
            route_id=f"cost_{state.turn_index}_{segment.segment_id}",
            route_kind=rule.route_kind,  # type: ignore[arg-type]
            source_move_family=intent.move_family,
            source_control_action=intent.control_action,
            source_scene_frame=intent.scene_frame,
            source_segment_role=segment.segment_role,
            target_character_ids=owner_ids[:3],
            owner_character_ids=owner_ids[:3],
            payer_character_id=payer_id,
            beneficiary_character_id=beneficiary_id,
            linked_scene_question_id=segment.segment_id,
            scene_question_focus=question_focus,
            return_due_turn=due_turn,
            payoff_family=payoff_family,
            immediate_global_deltas=global_deltas,
            immediate_relationship_deltas=rel_deltas,
            deferred_kind=rule.deferred_kind,  # type: ignore[arg-type]
            deferred_callback_id=None,
            transferred_to_character_id=transferred_target,
        )

    @staticmethod
    def build_callback(
        *,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        intent: UrbanTurnIntent,
        segment: CompiledSegment,
        route: CostRouteRecord,
    ) -> CallbackQueueItem | None:
        if route.route_kind == "immediate_cost" and intent.control_action == "detonate":
            return None
        callback_rule = PayoffPlanner._select_callback_rule(plan=plan, intent=intent)
        if callback_rule is None:
            return None
        if intent.control_action == "detonate":
            return None
        if route.deferred_kind is None:
            return None
        ownership_rule = PayoffPlanner._select_cost_ownership_rule(plan=plan, intent=intent, segment=segment)
        deferred_owner_mode = (
            ownership_rule.deferred_owner_mode
            if ownership_rule is not None and ownership_rule.deferred_owner_mode is not None
            else plan.semantic_strategy_pack.cost_ownership_matrix_v2.fallback_owner_mode
        )
        callback_owner_ids = PayoffPlanner._resolve_owner_ids(
            plan=plan,
            state=state,
            segment=segment,
            intent=intent,
            owner_mode=deferred_owner_mode,
        )
        target_id = callback_owner_ids[0] if callback_owner_ids else route.payer_character_id
        linked_edge = pick_shell_edge(
            shell_id=plan.story_shell_id,
            latent_kind=route.deferred_kind,
            turn_index=state.turn_index,
            segment_role=segment.segment_role,
            graph_policy=plan.semantic_strategy_pack.shell_propagation_graph,
            priority_policy=plan.semantic_strategy_pack.propagation_priority_policy,
        )
        due_min = state.turn_index + callback_rule.due_turn_min_offset
        due_max = state.turn_index + max(callback_rule.due_turn_max_offset, callback_rule.due_turn_min_offset)
        intensity_profile = plan.semantic_strategy_pack.cost_intensity_profile
        intensity = PayoffPlanner._route_intensity_multiplier(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
            route_kind=route.route_kind,
            payoff_family=route.payoff_family,
        )
        if intensity >= 1.25:
            due_min = max(state.turn_index + 1, due_min - 1)
        elif intensity <= 0.9:
            due_max = due_max + 1
        callback_id = f"cb_{state.turn_index}_{segment.segment_id}_{len(state.callback_queue)}"
        cue = trim_text(f"这步动作留下了后账：{_target_name(plan, target_id)}这边还没结清。", 220)
        detonation = trim_text(
            f"你之前这步留下的后账到期了，{_target_name(plan, target_id)}这边开始回咬，{route.payoff_family}成本被迫兑现。",
            220,
        )
        global_deltas = PayoffPlanner._scale_delta_map(
            delta_map=dict(callback_rule.base_global_deltas),
            multiplier=intensity,
            min_non_zero=intensity_profile.min_non_zero_delta,
            max_abs=intensity_profile.max_abs_delta_per_key,
        )
        if route.payoff_family in {"public_shame", "secret_leak"}:
            global_deltas["public_image"] = min(-1, int(global_deltas.get("public_image", 0)) - 1)
        if route.payoff_family in {"status_loss", "social_isolation"}:
            global_deltas["route_lock"] = max(1, int(global_deltas.get("route_lock", 0)) + 1)
        rel_deltas: dict[str, dict[str, int]] = {}
        if target_id:
            rel_deltas[target_id] = PayoffPlanner._scale_delta_map(
                delta_map=dict(callback_rule.base_target_relationship_deltas),
                multiplier=intensity,
                min_non_zero=intensity_profile.min_non_zero_delta,
                max_abs=intensity_profile.max_abs_delta_per_key,
            )
        return CallbackQueueItem(
            callback_id=callback_id,
            status="pending",
            source_turn_index=state.turn_index,
            source_segment_id=segment.segment_id,
            source_move_family=intent.move_family,
            linked_shell_edge_id=linked_edge.edge_id if linked_edge is not None else None,
            linked_scene_question_id=route.linked_scene_question_id or segment.segment_id,
            due_turn_min=due_min,
            due_turn_max=max(due_max, due_min),
            kind=route.deferred_kind,
            payoff_kind=route.payoff_family,
            stake_character_ids=[item for item in [target_id] if item][:3],
            target_character_ids=[item for item in [target_id] if item][:3],
            actor_character_id=target_id,
            cue_text=cue,
            detonation_text=detonation,
            global_deltas=global_deltas,
            relationship_deltas=rel_deltas,
        )

    @staticmethod
    def build_unresolved_cost(
        *,
        state: UrbanWorldState,
        segment: CompiledSegment,
        route: CostRouteRecord,
        callback_item: CallbackQueueItem | None,
    ) -> UnresolvedCostRecord | None:
        if route.route_kind not in {"deferred_cost", "transferred_cost"} and callback_item is None:
            return None
        owner_ids = list(route.owner_character_ids or route.target_character_ids)[:3]
        payer_id = route.payer_character_id or (owner_ids[0] if owner_ids else None)
        beneficiary_id = route.beneficiary_character_id or route.transferred_to_character_id
        due_turn = int(route.return_due_turn if route.return_due_turn is not None else state.turn_index + 3)
        return UnresolvedCostRecord(
            cost_id=f"uc_{state.turn_index}_{segment.segment_id}_{len(state.unresolved_costs)}",
            source_turn_index=state.turn_index,
            source_segment_id=segment.segment_id,
            route_kind=route.route_kind,
            owner_character_ids=owner_ids,
            payer_character_id=payer_id,
            beneficiary_character_id=beneficiary_id,
            linked_scene_question_id=route.linked_scene_question_id or segment.segment_id,
            scene_question_focus=route.scene_question_focus,
            due_turn=max(state.turn_index, due_turn),
            status="pending",
            linked_callback_id=callback_item.callback_id if callback_item is not None else route.deferred_callback_id,
            ladder_stage=1,
            ladder_retry_bias_steps=0,
            ladder_defer_once_used=False,
            ladder_summary=trim_text(
                f"代价挂账(stage-1)：{route.scene_question_focus}，最晚第{max(state.turn_index, due_turn)}回合回钩。",
                220,
            ),
            summary=trim_text(
                f"代价挂账(stage-1)：{route.scene_question_focus}，最晚第{max(state.turn_index, due_turn)}回合回钩。",
                220,
            ),
        )

    @staticmethod
    def finalize(
        *,
        route: CostRouteRecord,
        callback_item: CallbackQueueItem | None,
        global_delta_keys: list[str],
        relationship_delta_ids: list[str],
        fallback_applied: bool,
        unresolved_cost: UnresolvedCostRecord | None,
        control_signature_action: str = "none",
    ) -> TurnSemanticPayoffPlan:
        committed = bool(global_delta_keys or relationship_delta_ids)
        cost_recorded = unresolved_cost is not None
        summary = (
            "后果兑现未命中可观测变化。"
            if not committed
            else trim_text(
                f"后果兑现已提交：route={route.route_kind}"
                + ("（触发了最小痛感兜底）" if fallback_applied else "")
                + ("，并写入延迟回调。" if callback_item is not None else "。")
                + (f" 代价回钩最晚第{unresolved_cost.due_turn}回合。" if unresolved_cost is not None else ""),
                220,
            )
        )
        return TurnSemanticPayoffPlan(
            committed=committed,
            route_kind=route.route_kind,
            global_delta_keys=global_delta_keys[:8],
            relationship_delta_ids=relationship_delta_ids[:8],
            owner_character_ids=list(route.owner_character_ids[:3]),
            payer_character_id=route.payer_character_id,
            beneficiary_character_id=route.beneficiary_character_id,
            linked_scene_question_id=route.linked_scene_question_id,
            return_due_turn=(unresolved_cost.due_turn if unresolved_cost is not None else route.return_due_turn),
            cost_recorded=cost_recorded,
            control_signature_action=control_signature_action,
            control_signature_valid=(control_signature_action == "none"),
            control_signature_fail_safe_applied=False,
            fallback_applied=fallback_applied,
            summary=summary,
        )


class StakePlanner:
    @staticmethod
    def _utility_reason_family(
        *,
        intent_frame: NpcStrategicIntent | None,
        delta: int,
        cause_tags: tuple[str, ...],
        preferred_reason_priority: list[str] | None = None,
    ) -> str:
        if any(tag in cause_tags for tag in ("sacrifice_window", "forced_alignment", "blame_shift")):
            reason = "blame_shift"
        elif any(tag in cause_tags for tag in ("debt_due", "kept_score", "owes_debt")):
            reason = "old_debt"
        elif delta <= -2:
            if intent_frame and intent_frame.public_survival_mode in {"self_preserve", "cut_off", "claim_narrative"}:
                reason = "self_preserve"
            else:
                reason = "loss_position"
        elif delta >= 2:
            reason = "opportunity_window"
        else:
            reason = "mixed"
        if preferred_reason_priority:
            preferred = [item for item in preferred_reason_priority if item and item != "mixed"]
            if reason == "mixed" and preferred:
                return preferred[0]
            if reason not in set(preferred) and abs(delta) >= 3 and preferred:
                return preferred[0]
        return reason

    @staticmethod
    def compute_utility(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        before_state: UrbanWorldState,
        state: UrbanWorldState,
        micro_bias_by_character: dict[str, int] | None = None,
        micro_reason_by_character: dict[str, str] | None = None,
    ) -> tuple[dict[str, int], list[NpcUtilityDeltaItem], TurnSemanticStakePlan]:
        rows: list[NpcUtilityDeltaItem] = []
        output: dict[str, int] = {}
        members_by_id = {member.character_id: member for member in plan.cast}
        bias_map = dict(micro_bias_by_character or {})
        reason_hint_map = dict(micro_reason_by_character or {})
        segment_interest = plan.semantic_strategy_pack.segment_interest_policy
        segment_interest_item = segment_interest.by_segment_id.get(segment.segment_id)
        reason_priority = (
            list(segment_interest_item.reason_priority)
            if segment_interest_item is not None
            else list(segment_interest.default_reason_priority)
        )
        stake_priority = (
            list(segment_interest_item.stake_priority)
            if segment_interest_item is not None
            else list(segment_interest.default_stake_priority)
        )
        stake_rank = {value: index for index, value in enumerate(stake_priority)}
        for character_id in unique_preserve([*state.active_character_ids, *plan.route_target_ids]):
            member = members_by_id.get(character_id)
            before_rel = before_state.relationships.get(character_id)
            after_rel = state.relationships.get(character_id)
            if member is None or before_rel is None or after_rel is None:
                continue
            rel_shift = (
                (after_rel.trust - before_rel.trust) * 2
                + (after_rel.affection - before_rel.affection)
                - (after_rel.suspicion - before_rel.suspicion) * 2
                - (after_rel.tension - before_rel.tension)
            )
            global_shift = 0
            if member.strategic_intent.primary_stake in {"reputation", "narrative_control"}:
                global_shift += (state.public_image - before_state.public_image) * 2
            if member.strategic_intent.primary_stake in {"position", "lineage", "eligibility"}:
                global_shift += (state.route_lock - before_state.route_lock) * 2
            if member.strategic_intent.primary_stake in {"relationship", "normal_life"}:
                global_shift += (state.scene_heat - before_state.scene_heat) * -1
            latent_touch = 0
            for event in state.latent_events:
                if character_id == event.actor_character_id:
                    latent_touch += 1
                if character_id in set(event.target_character_ids):
                    latent_touch -= 1
                if character_id in set(event.stake_character_ids):
                    latent_touch += 1
            stake_bonus = 0
            stake_index = stake_rank.get(member.strategic_intent.primary_stake)
            if stake_index is not None:
                stake_bonus = max(0, 3 - int(stake_index))
            micro_bias = int(bias_map.get(character_id, 0))
            delta = _clamp(rel_shift + global_shift + latent_touch + stake_bonus + micro_bias, -12, 12)
            output[character_id] = delta
            cause_tags = tuple(state.last_turn_reaction_causes.get(character_id, []))
            family = StakePlanner._utility_reason_family(
                intent_frame=member.strategic_intent,
                delta=delta,
                cause_tags=cause_tags,
                preferred_reason_priority=reason_priority,
            )
            hinted_family = str(reason_hint_map.get(character_id, "")).strip()
            if hinted_family not in {"loss_position", "self_preserve", "old_debt", "opportunity_window", "blame_shift", "mixed"}:
                hinted_family = ""
            if hinted_family and hinted_family != "mixed":
                if family == "mixed" or abs(delta) >= 2:
                    family = hinted_family
            reason_text = {
                "loss_position": f"{member.display_name}这回合在失位。",
                "self_preserve": f"{member.display_name}这回合在优先自保。",
                "old_debt": f"{member.display_name}这回合在借旧账动手。",
                "blame_shift": f"{member.display_name}这回合在重排锅位，想把账甩给别人扛。",
                "opportunity_window": f"{member.display_name}这回合在等机会反扑。",
                "mixed": f"{member.display_name}这回合的效用变化较弱。",
            }[family]
            rows.append(
                NpcUtilityDeltaItem(
                    character_id=character_id,
                    display_name=member.display_name,
                    utility_delta=delta,
                    reason_family=family,  # type: ignore[arg-type]
                    reason_text=reason_text,
                )
            )
        rows = sorted(rows, key=lambda item: (abs(item.utility_delta), item.utility_delta, item.character_id), reverse=True)
        top = rows[:3]
        summary = "利益面本回合变化较弱。"
        if top:
            head = top[0]
            summary = trim_text(f"{head.display_name}的利益变化最大（{head.utility_delta:+d}），反应理由={head.reason_family}。", 220)
        return output, top, TurnSemanticStakePlan(top_shifts=top, summary=summary)


class EventPlanner:
    @staticmethod
    def finalize(
        *,
        latent_outcome,
        triggered_record,
        causal_pending_count: int = 0,
        causal_resolved_this_turn: int = 0,
        causal_fail_safe_applied: bool = False,
        stale_escalations_this_turn: int = 0,
        prioritized_cost: UnresolvedCostRecord | None = None,
        due_cost_primary_eligible: bool = False,
        due_cost_forces_primary_driver_applied: bool = False,
        cost_ladder_stage: int = 0,
        player_override_applied: bool = False,
        secondary_due_cost_pressure: bool = False,
    ) -> TurnSemanticEventPlan:
        event_transition = str(getattr(latent_outcome, "top_event_transition", "none") or "none")
        triggered_kind = triggered_record.kind if triggered_record is not None else None
        key_segment_conversion = bool(getattr(latent_outcome, "key_segment_conversion", False))
        cost_return_priority_applied = prioritized_cost is not None
        primary_driver: str = "none"
        if due_cost_forces_primary_driver_applied:
            primary_driver = "cost_return"
        elif triggered_kind is not None or event_transition in {"rising", "cooling", "triggered"}:
            primary_driver = "latent"
        if triggered_kind:
            summary = f"事件推进已落锤：{triggered_kind}触发，transition={event_transition}。"
        elif event_transition in {"rising", "cooling"}:
            summary = f"事件推进保持流动：top latent transition={event_transition}。"
        else:
            summary = "事件推进未形成明确流动。"
        if prioritized_cost is not None:
            summary = (
                f"{summary} 本回合优先回钩代价({prioritized_cost.scene_question_focus})，"
                f"最晚第{prioritized_cost.due_turn}回合。"
            )
        if due_cost_forces_primary_driver_applied:
            summary = f"{summary} 事件主驱动已切到cost_return。"
        elif secondary_due_cost_pressure:
            summary = f"{summary} 玩家显式控雷优先，这笔到期代价被压到次驱动并保留追击权重。"
        if key_segment_conversion:
            summary = f"{summary}关键段启用了conversion补锤。"
        if causal_resolved_this_turn > 0:
            summary = f"{summary}因果合同本回合结清{causal_resolved_this_turn}条。"
        if stale_escalations_this_turn > 0:
            summary = f"{summary}未结清合同触发了{stale_escalations_this_turn}次发酵加压。"
        if causal_fail_safe_applied:
            summary = f"{summary}其中包含强制落锤。"
        return TurnSemanticEventPlan(
            top_event_id=getattr(latent_outcome, "top_event_id", None),
            top_event_kind=getattr(latent_outcome, "top_event_kind", None),
            top_event_transition=event_transition,
            triggered_event_id=triggered_record.event_id if triggered_record is not None else None,
            triggered_kind=triggered_kind,
            primary_driver=primary_driver,  # type: ignore[arg-type]
            due_cost_primary_eligible=due_cost_primary_eligible,
            due_cost_forces_primary_driver_applied=due_cost_forces_primary_driver_applied,
            cost_ladder_stage=max(0, min(3, int(cost_ladder_stage))),
            cost_ladder_primary_applies=bool(due_cost_forces_primary_driver_applied and int(cost_ladder_stage) >= 2),
            player_override_applied=player_override_applied,
            secondary_due_cost_pressure=secondary_due_cost_pressure,
            key_segment_conversion=key_segment_conversion,
            prioritized_cost_id=prioritized_cost.cost_id if prioritized_cost is not None else None,
            prioritized_cost_due_turn=prioritized_cost.due_turn if prioritized_cost is not None else None,
            cost_return_priority_applied=cost_return_priority_applied,
            causal_pending_count=max(0, int(causal_pending_count)),
            causal_resolved_this_turn=max(0, int(causal_resolved_this_turn)),
            causal_fail_safe_applied=bool(causal_fail_safe_applied),
            stale_escalations_this_turn=max(0, int(stale_escalations_this_turn)),
            summary=trim_text(summary, 220),
        )
