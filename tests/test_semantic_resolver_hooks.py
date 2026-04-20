from __future__ import annotations

from types import SimpleNamespace

import pytest

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import HookState, SemanticEffect, UrbanRelationshipTargetState, UrbanTurnIntent, UrbanWorldState
from rpg_backend.play_v2.hook_engine import HookContext, build_hook_context
from rpg_backend.play_v2.runtime import apply_turn_resolution, build_initial_world_state
from rpg_backend.play_v2.semantic_resolver import _effect_multiplier, resolve_semantic_effects


def _make_hook_state(
    *,
    status: str = "dormant",
    leverage_value: float = 0.3,
    holder_id: str = "holder_a",
    target_id: str = "target_b",
    source_secret_id: str = "sec_1",
    leverage_type: str = "pressure",
) -> HookState:
    hook_id = f"{holder_id}__{target_id}__{source_secret_id}"
    return HookState(
        hook_id=hook_id,
        holder_id=holder_id,
        target_id=target_id,
        source_secret_id=source_secret_id,
        leverage_type=leverage_type,
        status=status,  # type: ignore[arg-type]
        leverage_value=leverage_value,
    )


def _make_state(
    *,
    target_id: str = "target_b",
    hook_states: dict[str, HookState] | None = None,
    known_secret_ids: list[str] | None = None,
) -> UrbanWorldState:
    return UrbanWorldState.model_construct(
        segment_index=0,
        relationships={
            target_id: UrbanRelationshipTargetState(
                character_id=target_id,
                name="Target",
            )
        },
        hook_states=dict(hook_states or {}),
        known_secret_ids=list(known_secret_ids or []),
    )


def _make_plan(*, allocated_secret_ids: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        segments=[
            SimpleNamespace(
                allocated_secret_ids=list(allocated_secret_ids or []),
            )
        ]
    )


def _resolve(
    effect_type: str,
    *,
    hook_context: HookContext | None,
    target_id: str = "target_b",
) -> dict[str, object]:
    return resolve_semantic_effects(
        _make_plan(),
        _make_state(target_id=target_id),
        [SemanticEffect(effect_type=effect_type, target_id=target_id)],
        hook_context=hook_context,
    )


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


def test_build_hook_context_empty_hook_states_returns_defaults() -> None:
    state = UrbanWorldState.model_construct(hook_states={})

    context = build_hook_context(state, actor_id="player", target_id="target_b")

    assert context == HookContext(
        target_has_active_hook=False,
        target_has_leveraged_hook=False,
        max_leverage_on_target=0.0,
        actor_is_hook_holder=False,
    )


def test_build_hook_context_with_active_hook_on_target_marks_active_only() -> None:
    hook = _make_hook_state(status="active", leverage_value=0.55)
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    context = build_hook_context(state, actor_id="player", target_id="target_b")

    assert context.target_has_active_hook is True
    assert context.target_has_leveraged_hook is False
    assert context.max_leverage_on_target == pytest.approx(0.55)


def test_build_hook_context_with_leveraged_hook_on_target_marks_both_flags() -> None:
    hook = _make_hook_state(status="leveraged", leverage_value=0.8)
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    context = build_hook_context(state, actor_id="player", target_id="target_b")

    assert context.target_has_active_hook is True
    assert context.target_has_leveraged_hook is True
    assert context.max_leverage_on_target == pytest.approx(0.8)


def test_build_hook_context_detects_actor_as_hook_holder_even_without_target() -> None:
    hook = _make_hook_state(holder_id="player", target_id="target_b")
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    context = build_hook_context(state, actor_id="player", target_id=None)

    assert context.target_has_active_hook is False
    assert context.target_has_leveraged_hook is False
    assert context.max_leverage_on_target == pytest.approx(0.0)
    assert context.actor_is_hook_holder is True


def test_betrayal_uses_no_hook_vs_leveraged_weighted_deltas() -> None:
    no_hook_context = HookContext(
        target_has_active_hook=False,
        target_has_leveraged_hook=False,
        max_leverage_on_target=0.0,
        actor_is_hook_holder=False,
    )
    leveraged_context = HookContext(
        target_has_active_hook=True,
        target_has_leveraged_hook=True,
        max_leverage_on_target=0.9,
        actor_is_hook_holder=False,
    )

    no_hook = _resolve("betrayal", hook_context=no_hook_context)
    leveraged = _resolve("betrayal", hook_context=leveraged_context)

    assert no_hook["relationship_deltas"]["target_b"]["trust"] == pytest.approx(-2.5)
    assert no_hook["relationship_deltas"]["target_b"]["suspicion"] == pytest.approx(1.5)
    assert no_hook["global_deltas"]["scene_heat"] == pytest.approx(1.0)
    assert leveraged["relationship_deltas"]["target_b"]["trust"] == pytest.approx(-3.0)
    assert leveraged["relationship_deltas"]["target_b"]["suspicion"] == pytest.approx(3.5)
    assert leveraged["global_deltas"]["scene_heat"] == pytest.approx(2.0)


def test_trust_action_uses_weaker_leveraged_multiplier() -> None:
    leveraged_context = HookContext(
        target_has_active_hook=True,
        target_has_leveraged_hook=True,
        max_leverage_on_target=0.9,
        actor_is_hook_holder=False,
    )

    assert _effect_multiplier("trust_action", leveraged_context) == pytest.approx(0.9)


def test_confrontation_stacks_actor_hook_holder_bonus() -> None:
    active_holder_context = HookContext(
        target_has_active_hook=True,
        target_has_leveraged_hook=False,
        max_leverage_on_target=0.55,
        actor_is_hook_holder=True,
    )

    result = _resolve("confrontation", hook_context=active_holder_context)

    assert _effect_multiplier("confrontation", active_holder_context) == pytest.approx(1.56)
    assert result["relationship_deltas"]["target_b"]["tension"] == pytest.approx(3.0)
    assert result["relationship_deltas"]["target_b"]["suspicion"] == pytest.approx(1.5)
    assert result["global_deltas"]["scene_heat"] == pytest.approx(3.0)


def test_betrayal_multiplier_respects_stacking_cap_at_two() -> None:
    capped_context = HookContext(
        target_has_active_hook=True,
        target_has_leveraged_hook=True,
        max_leverage_on_target=1.0,
        actor_is_hook_holder=True,
    )

    result = _resolve("betrayal", hook_context=capped_context)

    assert _effect_multiplier("betrayal", capped_context) == pytest.approx(2.0)
    assert result["relationship_deltas"]["target_b"]["trust"] == pytest.approx(-3.0)
    assert result["relationship_deltas"]["target_b"]["suspicion"] == pytest.approx(4.0)
    assert result["global_deltas"]["scene_heat"] == pytest.approx(2.0)


def test_hook_context_none_preserves_pre_phase_c_resolution_snapshot() -> None:
    result = resolve_semantic_effects(
        _make_plan(allocated_secret_ids=["sec_hidden"]),
        _make_state(known_secret_ids=[]),
        [
            SemanticEffect(effect_type="secret_reveal", target_id="target_b"),
            SemanticEffect(effect_type="betrayal", target_id="target_b"),
        ],
        hook_context=None,
    )

    assert result == {
        "global_deltas": {"secret_exposure": 2, "scene_heat": 2},
        "relationship_deltas": {"target_b": {"trust": -3, "suspicion": 2}},
        "known_secret_ids_to_add": ["sec_hidden"],
        "tags": ["semantic:secret_reveal", "semantic:betrayal"],
    }


def test_apply_turn_resolution_amplifies_betrayal_for_leveraged_hook_target(v3_plan: CompiledPlayPlan) -> None:
    baseline_state = build_initial_world_state(v3_plan, session_id="semantic_no_hook")
    leveraged_state = build_initial_world_state(v3_plan, session_id="semantic_leveraged_hook")
    target_id = next(iter(v3_plan.segments[0].focus_target_ids + v3_plan.segments[0].rival_target_ids))
    for state in (baseline_state, leveraged_state):
        state.hook_states = {}
        state.relationships[target_id].trust = 5
        state.relationships[target_id].suspicion = 0
    leveraged_hook = _make_hook_state(
        status="leveraged",
        leverage_value=0.9,
        holder_id="npc_holder",
        target_id=target_id,
        source_secret_id="sec_semantic_betrayal",
        leverage_type="blackmail",
    )
    leveraged_state.hook_states = {leveraged_hook.hook_id: leveraged_hook}

    baseline_next, _ = apply_turn_resolution(
        v3_plan,
        baseline_state,
        UrbanTurnIntent(
            input_text="我决定直接切割她。",
            move_family="accuse",
            target_id=target_id,
            scene_frame="private",
            semantic_effects=[SemanticEffect(effect_type="betrayal", target_id=target_id)],
        ),
    )
    leveraged_next, _ = apply_turn_resolution(
        v3_plan,
        leveraged_state,
        UrbanTurnIntent(
            input_text="我决定直接切割她。",
            move_family="accuse",
            target_id=target_id,
            scene_frame="private",
            semantic_effects=[SemanticEffect(effect_type="betrayal", target_id=target_id)],
        ),
    )

    assert leveraged_next.relationships[target_id].trust < baseline_next.relationships[target_id].trust
    assert leveraged_next.relationships[target_id].suspicion > baseline_next.relationships[target_id].suspicion
