from __future__ import annotations

from collections import Counter
from typing import get_args

import pytest

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author_v2.contracts import CompiledPlayPlan, SemanticCostRouteKind
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import SemanticEffect, UrbanTurnIntent, UrbanWorldState
from rpg_backend.play_v2.runtime import apply_turn_resolution, build_initial_world_state

HOOK_STATUSES = ("dormant", "suspected", "active", "leveraged", "detonated")
DEMO_TURN_SEQUENCE = (
    ("probe_secret", "我先试探她到底藏了什么。", ()),
    ("flirt", "我先贴近一步，看看谁先露怯。", ()),
    ("accuse", "我先把话挑明，逼她正面回应。", ()),
    ("betray", "我准备反手切割，把风险先丢回去。", ()),
    ("public_reveal", "我直接把证据摔到台面上。", ("secret_reveal", "public_exposure")),
    ("comfort", "我先把她的情绪稳住。", ()),
    ("ally_with", "我先把她拉到同一阵线。", ()),
    ("jealousy_trigger", "我故意让她看见这一步的站队。", ("confrontation",)),
)


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


def _find_demo_hook_target(plan: CompiledPlayPlan) -> str:
    opening_targets = set(plan.segments[0].focus_target_ids + plan.segments[0].rival_target_ids)
    reveal_secret_ids = {
        secret_id
        for segment in plan.segments
        for secret_id in getattr(segment, "allocated_secret_ids", [])
    }
    for raw_hook in plan.hooks or []:
        target_id = str(raw_hook.get("target_id") or "").strip()
        source_secret_id = str(raw_hook.get("source_secret_id") or "").strip()
        if target_id in opening_targets and source_secret_id in reveal_secret_ids:
            return target_id
    if opening_targets:
        return sorted(opening_targets)[0]
    if plan.route_target_ids:
        return plan.route_target_ids[0]
    raise AssertionError("Expected v3 plan to contain at least one target for cost-routing coverage.")


def _build_intent(
    *,
    move_family: RelationshipMoveFamily,
    target_id: str,
    input_text: str | None = None,
    effect_types: tuple[str, ...] | None = None,
) -> UrbanTurnIntent:
    scene_frame_by_move_family = {
        "ally_with": "semi_public",
        "jealousy_trigger": "semi_public",
        "public_reveal": "public",
    }
    semantic_effect_types_by_move_family = {
        "accuse": ("confrontation",),
        "betray": ("betrayal",),
        "public_reveal": ("secret_reveal", "public_exposure"),
    }
    resolved_effect_types = effect_types
    if resolved_effect_types is None:
        resolved_effect_types = semantic_effect_types_by_move_family.get(move_family, ())
    return UrbanTurnIntent(
        input_text=input_text or f"scripted {move_family}",
        move_family=move_family,
        target_id=target_id,
        scene_frame=scene_frame_by_move_family.get(move_family, "private"),  # type: ignore[arg-type]
        confidence="high",
        semantic_effects=[
            SemanticEffect(effect_type=effect_type, target_id=target_id)
            for effect_type in resolved_effect_types
        ],
    )


def _hook_status_distribution(state: UrbanWorldState) -> dict[str, int]:
    counts = Counter(hook.status for hook in state.hook_states.values())
    return {status: counts.get(status, 0) for status in HOOK_STATUSES}


def _run_demo_sequence(plan: CompiledPlayPlan) -> tuple[list[str], bool, bool, UrbanWorldState]:
    target_id = _find_demo_hook_target(plan)
    state = build_initial_world_state(plan, session_id="v3_cost_routing_demo")
    prior_statuses = {hook_id: hook.status for hook_id, hook in state.hook_states.items()}
    dormant_to_suspected_seen = False
    hook_callback_fired_seen = False
    output_lines: list[str] = []

    for turn_number, (move_family, input_text, effect_types) in enumerate(DEMO_TURN_SEQUENCE, start=1):
        intent = _build_intent(
            move_family=move_family,  # type: ignore[arg-type]
            target_id=target_id,
            input_text=input_text,
            effect_types=effect_types,
        )
        state, _ = apply_turn_resolution(plan, state, intent)
        current_statuses = {hook_id: hook.status for hook_id, hook in state.hook_states.items()}
        if any(
            prior_statuses.get(hook_id) == "dormant" and status == "suspected"
            for hook_id, status in current_statuses.items()
        ):
            dormant_to_suspected_seen = True
        prior_statuses = current_statuses
        hooks_fired_this_turn = [
            tag
            for tag in state.last_turn_tags
            if tag.startswith("callback_fired:hook_")
        ]
        if hooks_fired_this_turn:
            hook_callback_fired_seen = True
        line = (
            f"Turn {turn_number}: move_family={move_family} "
            f"target={target_id} "
            f"hook_status_distribution={_hook_status_distribution(state)} "
            f"callback_queue_size={len(state.callback_queue)} "
            f"hooks_fired_this_turn={hooks_fired_this_turn}"
        )
        print(line)
        output_lines.append(line)

    return output_lines, dormant_to_suspected_seen, hook_callback_fired_seen, state


def test_v3_plan_cost_routing_matrix_has_one_rule_per_move_family(v3_plan: CompiledPlayPlan) -> None:
    rules = v3_plan.semantic_strategy_pack.cost_routing_matrix.rules
    expected_move_families = set(get_args(RelationshipMoveFamily))
    legal_route_kinds = set(get_args(SemanticCostRouteKind))
    by_move_family = Counter(rule.move_family for rule in rules)

    assert len(rules) == len(expected_move_families)
    assert set(by_move_family) == expected_move_families
    assert all(count == 1 for count in by_move_family.values())
    assert len({rule.rule_id for rule in rules}) == len(rules)
    assert all(rule.rule_id == f"v3_default_{rule.move_family}" for rule in rules)
    assert all(rule.route_kind in legal_route_kinds for rule in rules)


@pytest.mark.parametrize("move_family", get_args(RelationshipMoveFamily))
def test_apply_turn_resolution_supports_each_move_family_in_v3_plan(
    v3_plan: CompiledPlayPlan,
    move_family: RelationshipMoveFamily,
) -> None:
    target_id = _find_demo_hook_target(v3_plan)
    state = build_initial_world_state(v3_plan, session_id=f"v3_cost_route_{move_family}")
    intent = _build_intent(move_family=move_family, target_id=target_id)

    next_state, _ = apply_turn_resolution(v3_plan, state, intent)

    assert next_state.last_turn_cost_route is not None
    assert next_state.last_turn_cost_route.source_move_family == move_family


def test_v3_cost_routing_demo_sequence_prints_and_keeps_runtime_paths_alive(
    v3_plan: CompiledPlayPlan,
) -> None:
    output_lines, dormant_to_suspected_seen, hook_callback_fired_seen, final_state = _run_demo_sequence(v3_plan)

    assert len(output_lines) == len(DEMO_TURN_SEQUENCE)
    assert dormant_to_suspected_seen
    assert final_state.callback_queue
    assert hook_callback_fired_seen
