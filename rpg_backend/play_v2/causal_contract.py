from __future__ import annotations

from dataclasses import dataclass

from rpg_backend.author.normalize import trim_text, unique_preserve
from rpg_backend.author_v2.contracts import CompiledPlayPlan, CompiledSegment
from rpg_backend.play_v2.contracts import (
    CausalContractStateRecord,
    CallbackTurnStatusRecord,
    LatentEventKind,
    TurnEscalationRecord,
    TurnSemanticPayoffPlan,
    UrbanWorldState,
)

_ROLE_ORDER: tuple[str, ...] = ("opening", "misread", "pressure", "reversal", "reveal", "terminal")
_CLAMPED_GLOBAL_KEYS = {
    "scene_heat",
    "public_image",
    "relationship_debt_pressure",
    "public_wave_pressure",
    "secret_pressure",
    "npc_action_pressure",
    "secret_exposure",
    "route_lock",
}


def _role_rank(role: str) -> int:
    try:
        return _ROLE_ORDER.index(role)
    except ValueError:
        return 0


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _apply_global_delta(state: UrbanWorldState, key: str, delta: int) -> bool:
    if not hasattr(state, key):
        return False
    current = int(getattr(state, key))
    if key in _CLAMPED_GLOBAL_KEYS:
        updated = _clamp(current + int(delta), 0, 6)
    else:
        updated = current + int(delta)
    if updated == current:
        return False
    setattr(state, key, updated)
    return True


def _rule_match_kind(required_kind: str, actual_kind: LatentEventKind | None) -> bool:
    if required_kind == "any":
        return True
    if actual_kind is None:
        return False
    return required_kind == actual_kind


@dataclass(frozen=True)
class CausalContractOutcome:
    tags: tuple[str, ...]
    receipts: tuple[str, ...]
    resolved_this_turn: int
    pending_count: int
    fail_safe_applied: bool
    stale_escalations_this_turn: int


class CausalContractEngine:
    @staticmethod
    def enforce(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
        triggered_record: TurnEscalationRecord | None,
        callback_status: CallbackTurnStatusRecord | None,
        payoff_plan: TurnSemanticPayoffPlan | None,
    ) -> CausalContractOutcome:
        policy = plan.semantic_strategy_pack.causal_contract_policy
        current_rank = _role_rank(segment.segment_role)
        tags: list[str] = []
        receipts: list[str] = []
        resolved_this_turn = 0
        fail_safe_applied = False
        stale_escalations_this_turn = 0
        records = {key: value.model_copy(deep=True) for key, value in state.causal_contract_records.items()}
        by_rule_id = {rule.rule_id: rule for rule in policy.rules}

        # Activate pending obligations once the segment role reaches the open threshold.
        for rule in policy.rules:
            if rule.rule_id in records:
                continue
            if current_rank < _role_rank(rule.open_by_role):
                continue
            records[rule.rule_id] = CausalContractStateRecord(
                rule_id=rule.rule_id,
                source_kind=rule.source_kind,
                required_kind=rule.required_kind,  # type: ignore[arg-type]
                open_by_role=rule.open_by_role,
                resolve_by_role=rule.resolve_by_role,
                min_resolution_count=rule.min_resolution_count,
                status="pending",
                opened_turn_index=state.turn_index,
                resolved_turn_index=None,
                resolution_count=0,
                fail_safe_applied=False,
                summary=trim_text(rule.summary_hint or f"{rule.rule_id} 已激活，等待兑现。", 220),
            )
            tags.append(f"causal:{rule.rule_id}:opened")

        for rule_id, record in list(records.items()):
            if record.status == "resolved":
                continue
            rule = by_rule_id.get(rule_id)
            if rule is None:
                continue
            matched = False
            if record.source_kind == "callback":
                consumed = int(callback_status.consumed_count) if callback_status is not None else 0
                kind = callback_status.triggered_kind if callback_status is not None else None
                matched = consumed >= record.min_resolution_count and _rule_match_kind(record.required_kind, kind)
            elif record.source_kind == "latent":
                kind = triggered_record.kind if triggered_record is not None else None
                matched = triggered_record is not None and _rule_match_kind(record.required_kind, kind)
            elif record.source_kind == "payoff":
                matched = bool(payoff_plan is not None and payoff_plan.committed)
            if matched:
                record.status = "resolved"
                record.resolved_turn_index = state.turn_index
                record.resolution_count = max(record.resolution_count + 1, 1)
                record.summary = trim_text(f"{rule.summary_hint or rule.rule_id} 已在本回合兑现。", 220)
                records[rule_id] = record
                resolved_this_turn += 1
                tags.append(f"causal:{rule_id}:resolved")
                continue

            pending_age = max(0, int(state.turn_index) - int(record.opened_turn_index))
            can_escalate_stale = (
                pending_age >= int(policy.stale_pending_turns_threshold)
                and int(record.stale_escalation_count) < int(policy.stale_pending_max_escalations_per_rule)
                and int(record.last_stale_turn_index or -1) != int(state.turn_index)
            )
            if can_escalate_stale:
                stale_applied = _apply_global_delta(
                    state,
                    policy.stale_pending_global_delta_key,
                    int(policy.stale_pending_global_delta_value),
                )
                if stale_applied:
                    record.stale_escalation_count = _clamp(record.stale_escalation_count + 1, 0, 6)
                    record.last_stale_turn_index = state.turn_index
                    record.summary = trim_text(
                        f"{rule.summary_hint or rule.rule_id} 仍未兑现，系统追加了发酵压力。",
                        220,
                    )
                    records[rule_id] = record
                    stale_escalations_this_turn += 1
                    tags.extend([f"causal:{rule_id}:stale_escalated", "invariant:causal_pending_escalated"])
                    receipts.append(record.summary)

            resolve_due = current_rank >= _role_rank(record.resolve_by_role)
            if policy.force_resolve_on_terminal and segment.segment_role == "terminal":
                resolve_due = True
            if not resolve_due:
                continue
            applied = _apply_global_delta(state, rule.fail_safe_delta_key, int(rule.fail_safe_delta_value))
            if applied and payoff_plan is not None:
                payoff_plan.committed = True
                payoff_plan.fallback_applied = True
                payoff_plan.global_delta_keys = unique_preserve([rule.fail_safe_delta_key, *payoff_plan.global_delta_keys])[:8]
                payoff_plan.summary = trim_text("后果兑现由因果合同 fail-safe 强制提交。", 220)
            record.status = "resolved"
            record.resolved_turn_index = state.turn_index
            record.resolution_count = max(record.resolution_count, 1)
            record.fail_safe_applied = True
            record.summary = trim_text(f"{rule.summary_hint or rule.rule_id} 未自然达成，系统已强制落锤。", 220)
            records[rule_id] = record
            resolved_this_turn += 1
            fail_safe_applied = True
            tags.extend([f"causal:{rule_id}:forced", "invariant:causal_contract_fail_safe"])
            receipts.append(record.summary)

        pending_ids = [key for key, item in records.items() if item.status == "pending"]
        if len(pending_ids) > policy.max_open_rules:
            overflow = pending_ids[policy.max_open_rules :]
            for rule_id in overflow:
                item = records[rule_id]
                item.status = "resolved"
                item.resolved_turn_index = state.turn_index
                item.fail_safe_applied = True
                item.summary = trim_text(f"{item.rule_id} 超出并发上限，已强制结清。", 220)
                records[rule_id] = item
                resolved_this_turn += 1
                fail_safe_applied = True
                tags.append(f"causal:{rule_id}:overflow_forced")
            pending_ids = pending_ids[: policy.max_open_rules]

        state.causal_contract_records = records
        state.last_turn_causal_receipts = receipts[:6]
        return CausalContractOutcome(
            tags=tuple(unique_preserve(tags)[:8]),
            receipts=tuple(receipts[:6]),
            resolved_this_turn=resolved_this_turn,
            pending_count=len(pending_ids),
            fail_safe_applied=fail_safe_applied,
            stale_escalations_this_turn=stale_escalations_this_turn,
        )
