from __future__ import annotations

from rpg_backend.author.normalize import trim_text, unique_preserve
from rpg_backend.author_v2.contracts import CompiledPlayPlan, CompiledSegment
from rpg_backend.play_v2.contracts import UnresolvedCostRecord, UrbanWorldState


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _forced_anchor_tail(*, shell_id: str, anchor: str) -> str:
    picker = (sum(ord(ch) for ch in f"{shell_id}:{anchor}") % 3)
    if shell_id == "entertainment_scandal":
        options = (
            f"{anchor}和外面风向已经把这一下记成公开切割，后面只会更快滚成版本战。",
            f"{anchor}那边已经开始替这一下分版本，接下来只会越传越硬。",
            f"{anchor}已经先把这一步定成公开代价，后面想说轻都来不及。",
        )
        return options[picker]
    if shell_id == "campus_romance":
        options = (
            f"{anchor}已经把这一下记成公开站队，名额和熟人圈的账会立刻跟着动。",
            f"{anchor}那边已经把你们这一步当成认边信号，后续名单会先变脸。",
            f"{anchor}已经先记下这次站位，熟人圈和名额压力会一起压上来。",
        )
        return options[picker]
    if shell_id == "office_power":
        options = (
            f"{anchor}那边已经把这一下记进背锅顺序，后续发言权会先掉一截。",
            f"{anchor}那边已经把责任排位改了一轮，后面谁先开口都要先付账。",
            f"{anchor}已经把这一步记成锅位变化，后续口风会更快偏过去。",
        )
        return options[picker]
    if shell_id == "wealth_families":
        options = (
            f"{anchor}那边已经把这一下记成顺位信号，后续认边会更难回撤。",
            f"{anchor}已经先把这一步写进家族账本，谁想装中立都会更难看。",
            f"{anchor}那边已经按新站位开始记账，后续认边只会更硬。",
        )
        return options[picker]
    fallback = (
        f"{anchor}那边已经把这一下记进后续账本。",
        f"{anchor}那边已经先记下这一步，后续代价会顺着这条线追上来。",
        f"{anchor}那边已经把这次动作挂到账上，后面不会轻轻过去。",
    )
    return fallback[picker]


def _character_name(*, plan: CompiledPlayPlan, state: UrbanWorldState, character_id: str | None) -> str:
    if not character_id:
        return "当事人"
    relationship = state.relationships.get(character_id)
    if relationship is not None and relationship.name:
        return relationship.name
    member = next((item for item in plan.cast if item.character_id == character_id), None)
    if member is not None:
        return member.display_name
    return "当事人"


class InvariantValidator:
    @staticmethod
    def validate_and_patch(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
        narration: str,
    ) -> tuple[str, list[str]]:
        policy = plan.semantic_strategy_pack.invariant_policy
        tags: list[str] = []
        if policy.max_main_triggers_per_turn >= 1 and len(state.last_turn_escalations) > policy.max_main_triggers_per_turn:
            state.last_turn_escalations = state.last_turn_escalations[: policy.max_main_triggers_per_turn]
            tags.append(f"{policy.trace_tag_prefix}:max_main_trigger_enforced")
        if policy.require_question_progress and state.last_turn_semantic_plan is not None:
            question_plan = state.last_turn_semantic_plan.question_plan
            if question_plan.before_status == question_plan.final_status:
                tags.append(f"{policy.trace_tag_prefix}:question_progress_fail_safe")
                question_plan.forced_advance = True
                question_plan.advance_reason = question_plan.advance_reason or "invariant_question_progress"
                question_plan.summary = trim_text(
                    f"问题推进：{question_plan.before_status} -> {question_plan.final_status}（invariant 标记为强制推进）。",
                    220,
                )
        if policy.require_observable_cost and not state.last_turn_global_deltas and not state.last_turn_relationship_deltas:
            key = policy.fallback_global_delta_key
            delta = int(policy.fallback_global_delta_value)
            if hasattr(state, key):
                current = int(getattr(state, key))
                if key in {
                    "scene_heat",
                    "public_image",
                    "relationship_debt_pressure",
                    "public_wave_pressure",
                    "secret_pressure",
                    "npc_action_pressure",
                    "secret_exposure",
                    "route_lock",
                }:
                    setattr(state, key, _clamp(current + delta, 0, 6))
                else:
                    setattr(state, key, current + delta)
                state.last_turn_global_deltas[key] = delta
                if state.last_turn_semantic_plan is not None:
                    payoff = state.last_turn_semantic_plan.payoff_plan
                    payoff.committed = True
                    payoff.fallback_applied = True
                    payoff.global_delta_keys = unique_preserve([key, *payoff.global_delta_keys])[:8]
                    payoff.summary = trim_text("后果兑现通过 invariant fail-safe 补齐了最小可观测代价。", 220)
                tags.append(f"{policy.trace_tag_prefix}:observable_cost_fail_safe")
        if policy.require_divergence_reason_family_split and state.last_turn_semantic_plan is not None:
            style_plan = state.last_turn_semantic_plan.style_plan
            if (
                style_plan.counter_reason_family
                and style_plan.crowd_reason_family
                and style_plan.counter_reason_family == style_plan.crowd_reason_family
                and style_plan.counter_reason_family != "mixed"
            ):
                style_plan.crowd_reason_family = (
                    "self_preserve" if style_plan.counter_reason_family != "self_preserve" else "opportunity_window"
                )
                style_plan.summary = trim_text(
                    "文风提交触发了 invariant 分化修正：counter/crowd 原因族已强制拆分。",
                    220,
                )
                tags.append(f"{policy.trace_tag_prefix}:divergence:reason_family_split")
        if policy.require_cost_ownership_committed:
            route = state.last_turn_cost_route
            has_owner = bool(
                route is not None
                and (
                    route.owner_character_ids
                    or route.target_character_ids
                    or route.payer_character_id is not None
                )
            )
            if not has_owner:
                fallback_owner = next(iter(state.last_turn_relationship_deltas.keys()), None)
                if fallback_owner is None:
                    fallback_owner = next((item for item in state.active_character_ids if item), None)
                if fallback_owner is not None:
                    rel = state.relationships.get(fallback_owner)
                    if rel is not None:
                        rel.tension = _clamp(rel.tension + 1, 0, 6)
                    if route is not None:
                        route.target_character_ids = [fallback_owner]
                        route.owner_character_ids = [fallback_owner]
                        route.payer_character_id = route.payer_character_id or fallback_owner
                    rel_deltas = dict(state.last_turn_relationship_deltas.get(fallback_owner) or {})
                    rel_deltas["tension"] = int(rel_deltas.get("tension", 0)) + 1
                    state.last_turn_relationship_deltas[fallback_owner] = rel_deltas
                    if state.last_turn_semantic_plan is not None:
                        payoff = state.last_turn_semantic_plan.payoff_plan
                        payoff.committed = True
                        payoff.relationship_delta_ids = unique_preserve([fallback_owner, *payoff.relationship_delta_ids])[:8]
                        payoff.owner_character_ids = unique_preserve([fallback_owner, *payoff.owner_character_ids])[:3]
                        payoff.payer_character_id = payoff.payer_character_id or fallback_owner
                        payoff.summary = trim_text("后果兑现通过 invariant fail-safe 补齐了明确代价受体。", 220)
                    tags.append(f"{policy.trace_tag_prefix}:cost:ownership_committed")
        if policy.require_cost_return_within_window:
            overdue_item = next(
                (
                    item
                    for item in state.unresolved_costs
                    if item.status == "pending"
                    and (
                        state.turn_index - int(item.source_turn_index)
                    )
                    > int(
                        (
                            plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id.get(item.source_segment_id).max_return_turns
                            if plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id.get(item.source_segment_id) is not None
                            else 3
                        )
                    )
                ),
                None,
            )
            if overdue_item is not None:
                overdue_item.status = "returned"
                overdue_item.resolved_turn_index = state.turn_index
                payer_id = overdue_item.payer_character_id
                if payer_id and payer_id in state.relationships:
                    rel = state.relationships[payer_id]
                    rel.tension = _clamp(rel.tension + 1, 0, 6)
                    rel_delta = dict(state.last_turn_relationship_deltas.get(payer_id) or {})
                    rel_delta["tension"] = int(rel_delta.get("tension", 0)) + 1
                    state.last_turn_relationship_deltas[payer_id] = rel_delta
                else:
                    state.scene_heat = _clamp(state.scene_heat + 1, 0, 6)
                    state.last_turn_global_deltas["scene_heat"] = int(state.last_turn_global_deltas.get("scene_heat", 0)) + 1
                if state.last_turn_semantic_plan is not None:
                    payoff = state.last_turn_semantic_plan.payoff_plan
                    payoff.committed = True
                    payoff.cost_recorded = True
                    payoff.return_due_turn = overdue_item.due_turn
                    payoff.owner_character_ids = list(overdue_item.owner_character_ids[:3])
                    payoff.payer_character_id = overdue_item.payer_character_id
                    payoff.beneficiary_character_id = overdue_item.beneficiary_character_id
                    payoff.linked_scene_question_id = overdue_item.linked_scene_question_id
                    if payer_id:
                        payoff.relationship_delta_ids = unique_preserve([payer_id, *payoff.relationship_delta_ids])[:8]
                    else:
                        payoff.global_delta_keys = unique_preserve(["scene_heat", *payoff.global_delta_keys])[:8]
                    payoff.summary = trim_text("逾期代价已被 invariant 强制回钩并落到账面。", 220)
                owner_name = _character_name(plan=plan, state=state, character_id=overdue_item.payer_character_id)
                state.last_turn_consequences = unique_preserve(
                    [f"这笔旧账已逾期，系统强制回钩到{owner_name}身上，谁都不能再拖。", *state.last_turn_consequences]
                )[:8]
                tags.append(f"{policy.trace_tag_prefix}:cost_return_within_window")
        if policy.require_cost_primary_driver_committed and state.last_turn_semantic_plan is not None:
            event_plan = state.last_turn_semantic_plan.event_plan
            if (
                event_plan.due_cost_primary_eligible
                and not event_plan.player_override_applied
                and event_plan.primary_driver != "cost_return"
            ):
                event_plan.primary_driver = "cost_return"
                event_plan.due_cost_forces_primary_driver_applied = True
                event_plan.summary = trim_text(
                    f"{event_plan.summary} invariant 已强制把到期成本绑定为主驱动。",
                    220,
                )
                tags.append(f"{policy.trace_tag_prefix}:cost_primary_driver_committed")
        if policy.require_cost_two_sided_exchange and state.last_turn_semantic_plan is not None:
            semantic = state.last_turn_semantic_plan
            needs_two_sided = bool(
                semantic.event_plan.primary_driver == "cost_return"
                or semantic.question_plan.prioritized_cost_id is not None
            )
            if needs_two_sided:
                route = state.last_turn_cost_route
                payer_id = semantic.payoff_plan.payer_character_id or (route.payer_character_id if route is not None else None)
                beneficiary_id = semantic.payoff_plan.beneficiary_character_id or (route.beneficiary_character_id if route is not None else None)
                rel_deltas = dict(state.last_turn_relationship_deltas)
                min_payer_loss = 1
                min_beneficiary_gain = 1
                visibility_rule = plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id.get(segment.segment_id)
                if visibility_rule is not None:
                    min_payer_loss = max(1, int(visibility_rule.min_payer_loss))
                    min_beneficiary_gain = max(1, int(visibility_rule.min_beneficiary_gain))

                def _payer_loss_score(deltas: dict[str, int]) -> int:
                    return max(
                        0,
                        int(deltas.get("tension", 0)),
                        int(deltas.get("suspicion", 0)),
                        max(0, -int(deltas.get("trust", 0))),
                        max(0, -int(deltas.get("affection", 0))),
                    )

                def _beneficiary_gain_score(deltas: dict[str, int]) -> int:
                    return max(
                        0,
                        int(deltas.get("trust", 0)),
                        int(deltas.get("affection", 0)),
                        int(deltas.get("dependency", 0)),
                        max(0, -int(deltas.get("tension", 0))),
                        max(0, -int(deltas.get("suspicion", 0))),
                    )

                payer_score = _payer_loss_score(dict(rel_deltas.get(payer_id) or {})) if payer_id else 0
                beneficiary_score = _beneficiary_gain_score(dict(rel_deltas.get(beneficiary_id) or {})) if beneficiary_id else 0
                patched = False
                if payer_id and payer_score < min_payer_loss and payer_id in state.relationships:
                    rel = state.relationships[payer_id]
                    rel.tension = _clamp(rel.tension + (min_payer_loss - payer_score), 0, 6)
                    payer_delta = dict(rel_deltas.get(payer_id) or {})
                    payer_delta["tension"] = int(payer_delta.get("tension", 0)) + (min_payer_loss - payer_score)
                    rel_deltas[payer_id] = payer_delta
                    patched = True
                if beneficiary_id and beneficiary_score < min_beneficiary_gain and beneficiary_id in state.relationships:
                    rel = state.relationships[beneficiary_id]
                    rel.trust = _clamp(rel.trust + (min_beneficiary_gain - beneficiary_score), -3, 6)
                    beneficiary_delta = dict(rel_deltas.get(beneficiary_id) or {})
                    beneficiary_delta["trust"] = int(beneficiary_delta.get("trust", 0)) + (min_beneficiary_gain - beneficiary_score)
                    rel_deltas[beneficiary_id] = beneficiary_delta
                    patched = True
                if patched:
                    state.last_turn_relationship_deltas = rel_deltas
                    semantic.payoff_plan.committed = True
                    if payer_id:
                        semantic.payoff_plan.payer_character_id = payer_id
                    if beneficiary_id:
                        semantic.payoff_plan.beneficiary_character_id = beneficiary_id
                    semantic.payoff_plan.relationship_delta_ids = unique_preserve(
                        [*semantic.payoff_plan.relationship_delta_ids, *( [payer_id] if payer_id else []), *( [beneficiary_id] if beneficiary_id else [])]
                    )[:8]
                    semantic.payoff_plan.summary = trim_text(
                        "后果兑现已按 invariant 补齐双侧交换：payer受损且beneficiary获利。",
                        220,
                    )
                    tags.append(f"{policy.trace_tag_prefix}:cost_two_sided_exchange")
        if policy.require_cost_linked_to_question and state.last_turn_semantic_plan is not None:
            semantic = state.last_turn_semantic_plan
            question = semantic.question_plan
            payoff = semantic.payoff_plan
            expected_question_id = question.segment_id
            linked_id = payoff.linked_scene_question_id
            if linked_id is None and state.last_turn_cost_route is not None:
                linked_id = state.last_turn_cost_route.linked_scene_question_id
            if linked_id != expected_question_id:
                payoff.linked_scene_question_id = expected_question_id
                if state.last_turn_cost_route is not None:
                    state.last_turn_cost_route.linked_scene_question_id = expected_question_id
                if question.prioritized_cost_id is None:
                    due_cost = next(
                        (
                            item
                            for item in state.unresolved_costs
                            if item.status == "pending"
                            and (
                                item.linked_scene_question_id == expected_question_id
                                or int(item.due_turn) <= int(state.turn_index) + 1
                            )
                        ),
                        None,
                    )
                    if due_cost is not None:
                        question.prioritized_cost_id = due_cost.cost_id
                        question.prioritized_cost_focus = due_cost.scene_question_focus
                        question.prioritized_cost_due_turn = due_cost.due_turn
                question.summary = trim_text(f"{question.summary} 本回合问题已强制绑定代价回钩。", 220)
                payoff.summary = trim_text("后果兑现已被 invariant 绑定到本回合主问题。", 220)
                tags.append(f"{policy.trace_tag_prefix}:cost_linked_to_question")
        if (
            policy.require_control_signature_distinct
            and state.last_turn_semantic_plan is not None
            and state.last_turn_control_resolution is not None
        ):
            semantic = state.last_turn_semantic_plan
            payoff = semantic.payoff_plan
            action = state.last_turn_control_resolution.action_type
            payoff.control_signature_action = action
            if action in {"press", "redirect", "detonate"}:
                signature_rule = plan.semantic_strategy_pack.control_signature_policy_v8.by_action.get(action)
                route = state.last_turn_cost_route
                valid = True
                fail_safe_applied = False
                if signature_rule is not None and route is not None:
                    if route.route_kind != signature_rule.expected_route_kind:
                        valid = False
                    if signature_rule.require_owner_beneficiary_split:
                        if (
                            not payoff.payer_character_id
                            or not payoff.beneficiary_character_id
                            or payoff.payer_character_id == payoff.beneficiary_character_id
                        ):
                            valid = False
                    if signature_rule.require_pending_signal:
                        pending_count = len([item for item in state.unresolved_costs if item.status == "pending"])
                        if pending_count <= 0:
                            valid = False
                    if signature_rule.require_immediate_impact and not (
                        state.last_turn_global_deltas or state.last_turn_relationship_deltas
                    ):
                        valid = False
                    if signature_rule.require_uncertainty_drop_signal:
                        uncertainty_drop = bool(
                            (state.last_turn_callback_status is not None and state.last_turn_callback_status.triggered_callback_id)
                            or state.last_turn_escalations
                            or any(
                                item.status in {"returned", "resolved"}
                                and item.resolved_turn_index == state.turn_index
                                for item in state.unresolved_costs
                            )
                        )
                        if not uncertainty_drop:
                            valid = False
                if not valid:
                    if action == "press":
                        if route is not None and route.route_kind != "deferred_cost":
                            route.route_kind = "deferred_cost"
                            payoff.route_kind = "deferred_cost"
                            fail_safe_applied = True
                        if not any(item.status == "pending" for item in state.unresolved_costs):
                            owner_ids = list(unique_preserve(route.owner_character_ids if route is not None else []))[:3] if route is not None else []
                            payer_id = payoff.payer_character_id or (route.payer_character_id if route is not None else None)
                            beneficiary_id = payoff.beneficiary_character_id or (
                                route.beneficiary_character_id if route is not None else None
                            )
                            due_turn = state.turn_index + 2
                            state.unresolved_costs = [
                                *state.unresolved_costs,
                                UnresolvedCostRecord(
                                    cost_id=f"uc_inv_press_{state.turn_index}",
                                    source_turn_index=state.turn_index,
                                    source_segment_id=segment.segment_id,
                                    route_kind="deferred_cost",
                                    owner_character_ids=owner_ids,
                                    payer_character_id=payer_id,
                                    beneficiary_character_id=beneficiary_id,
                                    linked_scene_question_id=segment.segment_id,
                                    scene_question_focus="who_pays",
                                    due_turn=due_turn,
                                    status="pending",
                                    ladder_stage=1,
                                    ladder_retry_bias_steps=0,
                                    ladder_defer_once_used=False,
                                    ladder_summary=trim_text(f"代价挂账(stage-1)：who_pays，最晚第{due_turn}回合回钩。", 220),
                                    summary=trim_text(f"代价挂账(stage-1)：who_pays，最晚第{due_turn}回合回钩。", 220),
                                ),
                            ][:12]
                            fail_safe_applied = True
                    elif action == "redirect":
                        payer_id = payoff.payer_character_id or (route.payer_character_id if route is not None else None)
                        beneficiary_id = payoff.beneficiary_character_id or (route.beneficiary_character_id if route is not None else None)
                        if not beneficiary_id or beneficiary_id == payer_id:
                            fallback = next((item for item in state.active_character_ids if item and item != payer_id), None)
                            if fallback is not None:
                                beneficiary_id = fallback
                        if beneficiary_id and payer_id and beneficiary_id != payer_id:
                            payoff.payer_character_id = payer_id
                            payoff.beneficiary_character_id = beneficiary_id
                            if route is not None:
                                route.payer_character_id = payer_id
                                route.beneficiary_character_id = beneficiary_id
                                route.owner_character_ids = unique_preserve([payer_id, *route.owner_character_ids])[:3]
                                route.target_character_ids = unique_preserve([beneficiary_id, *route.target_character_ids])[:3]
                            fail_safe_applied = True
                    elif action == "detonate":
                        if not state.last_turn_global_deltas and not state.last_turn_relationship_deltas:
                            state.scene_heat = _clamp(state.scene_heat + 1, 0, 6)
                            state.last_turn_global_deltas["scene_heat"] = int(state.last_turn_global_deltas.get("scene_heat", 0)) + 1
                            payoff.global_delta_keys = unique_preserve(["scene_heat", *payoff.global_delta_keys])[:8]
                            fail_safe_applied = True
                        pending_item = next((item for item in state.unresolved_costs if item.status == "pending"), None)
                        if pending_item is not None:
                            pending_item.status = "returned"
                            pending_item.resolved_turn_index = state.turn_index
                            fail_safe_applied = True
                    valid = valid or fail_safe_applied
                payoff.control_signature_valid = bool(valid)
                payoff.control_signature_fail_safe_applied = bool(fail_safe_applied)
                if fail_safe_applied:
                    payoff.summary = trim_text(f"{payoff.summary} invariant 已补齐控雷签名后果。", 220)
                    tags.append(f"{policy.trace_tag_prefix}:control_signature_distinct")
            else:
                payoff.control_signature_valid = True
                payoff.control_signature_fail_safe_applied = False
        if (policy.require_cost_owner_visible or policy.require_cost_owner_visible_main_clause) and state.last_turn_cost_route is not None:
            route = state.last_turn_cost_route
            owner_ids = list(unique_preserve([*route.owner_character_ids, *route.target_character_ids])[:3])
            if not owner_ids and route.payer_character_id:
                owner_ids = [route.payer_character_id]
            owner_names = [_character_name(plan=plan, state=state, character_id=item) for item in owner_ids]
            owner_visible = bool(owner_names) and any(name in narration for name in owner_names if name)
            if not owner_visible and owner_names:
                payer_name = _character_name(plan=plan, state=state, character_id=route.payer_character_id)
                beneficiary_name = _character_name(plan=plan, state=state, character_id=route.beneficiary_character_id)
                visibility_line = trim_text(
                    f"这笔代价先落在{payer_name}身上，{beneficiary_name}拿到了这回合的缓冲。",
                    120,
                )
                narration = trim_text(f"{visibility_line}{narration}", 4000)
                state.last_turn_consequences = unique_preserve([visibility_line, *state.last_turn_consequences])[:8]
                if state.last_turn_semantic_plan is not None:
                    payoff = state.last_turn_semantic_plan.payoff_plan
                    payoff.owner_character_ids = unique_preserve([*owner_ids, *payoff.owner_character_ids])[:3]
                    payoff.payer_character_id = route.payer_character_id or payoff.payer_character_id
                    payoff.beneficiary_character_id = route.beneficiary_character_id or payoff.beneficiary_character_id
                    payoff.summary = trim_text("后果兑现已补齐主叙事可见的代价受体。", 220)
                tags.append(f"{policy.trace_tag_prefix}:cost_owner_visible")
                tags.append(f"{policy.trace_tag_prefix}:cost_owner_visible_main_clause")
        key_segment = segment.segment_role in set(policy.key_segment_roles)
        if policy.require_propagation_edge_commit and key_segment and state.last_turn_propagation_edge is None:
            from rpg_backend.play_v2.shell_propagation import pick_shell_edge

            triggered_kind = state.last_turn_escalations[0].kind if state.last_turn_escalations else None
            edge = pick_shell_edge(
                shell_id=plan.story_shell_id,
                latent_kind=triggered_kind,
                turn_index=state.turn_index,
                segment_role=segment.segment_role,
                graph_policy=plan.semantic_strategy_pack.shell_propagation_graph,
                priority_policy=plan.semantic_strategy_pack.propagation_priority_policy,
            )
            if edge is not None:
                state.last_turn_propagation_edge = edge
                tags.append(f"{policy.trace_tag_prefix}:propagation:edge_committed")
        if policy.require_key_segment_shell_anchor and key_segment and state.last_turn_semantic_plan is not None:
            style_plan = state.last_turn_semantic_plan.style_plan
            if not style_plan.shell_anchor_hit and style_plan.shell_anchor_tokens:
                anchor = style_plan.shell_anchor_tokens[0]
                narration = trim_text(f"{narration}{_forced_anchor_tail(shell_id=plan.story_shell_id, anchor=anchor)}", 4000)
                style_plan.shell_anchor_hit = anchor in narration
                style_plan.summary = trim_text("文风提交由 invariant fail-safe 补齐壳子锚点。", 220)
                tags.append(f"{policy.trace_tag_prefix}:shell_anchor_fail_safe")
        return narration, tags
