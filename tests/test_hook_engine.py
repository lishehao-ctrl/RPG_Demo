from __future__ import annotations

import pytest

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import HookState, SemanticEffect, UrbanTurnIntent, UrbanWorldState
from rpg_backend.play_v2.hook_engine import HookTurnEvents, build_initial_hook_states, update_hook_states
from rpg_backend.play_v2.runtime import apply_turn_resolution, build_initial_world_state, build_suggested_actions


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


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


@pytest.fixture(scope="module")
def v2_plan() -> CompiledPlayPlan:
    preview, _ = run_preview_blueprint_graph("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。")
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan


def test_build_initial_hook_states_returns_empty_dict_when_hooks_missing() -> None:
    plan = CompiledPlayPlan.model_construct(hooks=None)
    assert build_initial_hook_states(plan) == {}


def test_build_initial_hook_states_builds_ids_and_leverage_mapping() -> None:
    plan = CompiledPlayPlan.model_construct(
        hooks=[
            {
                "holder_id": "wang_siyu",
                "target_id": "chen_weiming",
                "source_secret_id": "sec_financial_fraud",
                "leverage_type": "blackmail",
            },
            {
                "holder_id": "liu_jianfeng",
                "target_id": "wang_siyu",
                "source_secret_id": "sec_old_debt",
                "leverage_type": "debt",
            },
            {
                "holder_id": "lin_yuxin",
                "target_id": "liu_jianfeng",
                "source_secret_id": "sec_private_note",
                "leverage_type": "knowledge",
            },
            {
                "holder_id": "zhang_hao",
                "target_id": "lin_yuxin",
                "source_secret_id": "sec_misc",
                "leverage_type": "complicity",
            },
        ]
    )

    hook_states = build_initial_hook_states(plan)

    assert set(hook_states) == {
        "wang_siyu__chen_weiming__sec_financial_fraud",
        "liu_jianfeng__wang_siyu__sec_old_debt",
        "lin_yuxin__liu_jianfeng__sec_private_note",
        "zhang_hao__lin_yuxin__sec_misc",
    }
    assert hook_states["wang_siyu__chen_weiming__sec_financial_fraud"].status == "dormant"
    assert hook_states["wang_siyu__chen_weiming__sec_financial_fraud"].leverage_value == pytest.approx(0.7)
    assert hook_states["liu_jianfeng__wang_siyu__sec_old_debt"].leverage_value == pytest.approx(0.5)
    assert hook_states["lin_yuxin__liu_jianfeng__sec_private_note"].leverage_value == pytest.approx(0.4)
    assert hook_states["zhang_hao__lin_yuxin__sec_misc"].leverage_value == pytest.approx(0.3)


def test_update_hook_states_transitions_dormant_to_suspected() -> None:
    hook = _make_hook_state(status="dormant", leverage_value=0.3)
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="player",
            target_id="target_b",
            move_family="probe_secret",
            effect_types=[],
            exposed_secret_ids=[],
            is_public_context=False,
        ),
    )

    assert changed == [hook.hook_id]
    assert state.hook_states[hook.hook_id].status == "suspected"
    assert state.hook_states[hook.hook_id].leverage_value == pytest.approx(0.4)


def test_update_hook_states_transitions_suspected_to_active_via_holder_move() -> None:
    hook = _make_hook_state(status="suspected", leverage_value=0.4, holder_id="holder_a")
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="holder_a",
            target_id="target_b",
            move_family="betray",
            effect_types=[],
            exposed_secret_ids=[],
            is_public_context=False,
        ),
    )

    assert changed == [hook.hook_id]
    assert state.hook_states[hook.hook_id].status == "active"
    assert state.hook_states[hook.hook_id].leverage_value == pytest.approx(0.55)


def test_update_hook_states_transitions_suspected_to_active_via_effect_type() -> None:
    hook = _make_hook_state(status="suspected", leverage_value=0.4, holder_id="someone_else")
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="player",
            target_id="target_b",
            move_family="comfort",
            effect_types=["confrontation"],
            exposed_secret_ids=[],
            is_public_context=False,
        ),
    )

    assert changed == [hook.hook_id]
    assert state.hook_states[hook.hook_id].status == "active"
    assert state.hook_states[hook.hook_id].leverage_value == pytest.approx(0.55)


def test_update_hook_states_transitions_active_to_leveraged() -> None:
    hook = _make_hook_state(status="active", leverage_value=0.55)
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="player",
            target_id="target_b",
            move_family="public_reveal",
            effect_types=["secret_reveal"],
            exposed_secret_ids=["sec_1"],
            is_public_context=False,
        ),
    )

    assert changed == [hook.hook_id]
    assert state.hook_states[hook.hook_id].status == "leveraged"
    assert state.hook_states[hook.hook_id].leverage_value == pytest.approx(0.75)


def test_update_hook_states_transitions_leveraged_to_detonated() -> None:
    hook = _make_hook_state(status="leveraged", leverage_value=0.75)
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="player",
            target_id="target_b",
            move_family="public_reveal",
            effect_types=["public_exposure"],
            exposed_secret_ids=["sec_1"],
            is_public_context=True,
        ),
    )

    assert changed == [hook.hook_id]
    assert state.hook_states[hook.hook_id].status == "detonated"
    assert state.hook_states[hook.hook_id].leverage_value == pytest.approx(0.0)


def test_update_hook_states_short_circuits_any_state_to_detonated() -> None:
    hook = _make_hook_state(status="active", leverage_value=0.55)
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="player",
            target_id="target_b",
            move_family="comfort",
            effect_types=[],
            exposed_secret_ids=["sec_1"],
            is_public_context=True,
        ),
    )

    assert changed == [hook.hook_id]
    assert state.hook_states[hook.hook_id].status == "detonated"
    assert state.hook_states[hook.hook_id].leverage_value == pytest.approx(0.0)


def test_update_hook_states_is_monotonic_for_detonated_hook() -> None:
    hook = _make_hook_state(status="detonated", leverage_value=0.0)
    state = UrbanWorldState.model_construct(hook_states={hook.hook_id: hook})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="holder_a",
            target_id="target_b",
            move_family="betray",
            effect_types=["secret_reveal"],
            exposed_secret_ids=["sec_1"],
            is_public_context=False,
        ),
    )

    assert changed == []
    assert state.hook_states[hook.hook_id].status == "detonated"
    assert state.hook_states[hook.hook_id].leverage_value == pytest.approx(0.0)


def test_update_hook_states_gracefully_handles_empty_state() -> None:
    state = UrbanWorldState.model_construct(hook_states={})

    changed = update_hook_states(
        state,
        HookTurnEvents(
            actor_id="player",
            target_id=None,
            move_family="comfort",
            effect_types=[],
            exposed_secret_ids=[],
            is_public_context=False,
        ),
    )

    assert changed == []
    assert state.hook_states == {}


def test_runtime_integration_v3_plan_initializes_non_empty_hook_states(v3_plan: CompiledPlayPlan) -> None:
    state = build_initial_world_state(v3_plan, session_id="hook_v3_init")

    assert v3_plan.hooks
    assert state.hook_states
    assert len(state.hook_states) == len(v3_plan.hooks)


def test_runtime_integration_v2_plan_initializes_empty_hook_states(v2_plan: CompiledPlayPlan) -> None:
    state = build_initial_world_state(v2_plan, session_id="hook_v2_init")

    assert v2_plan.hooks is None
    assert state.hook_states == {}


def test_apply_turn_resolution_updates_hook_states_and_tags(v2_plan: CompiledPlayPlan) -> None:
    state = build_initial_world_state(v2_plan, session_id="hook_turn_transition")
    suggestion = build_suggested_actions(v2_plan, state)[0]
    seeded_hook = _make_hook_state(
        status="suspected",
        leverage_value=0.4,
        holder_id="npc_holder",
        target_id=suggestion.target_id or v2_plan.cast[0].character_id,
        source_secret_id="sec_runtime_injected",
        leverage_type="knowledge",
    )
    state.hook_states = {seeded_hook.hook_id: seeded_hook}
    intent = UrbanTurnIntent(
        input_text="我把矛盾挑明。",
        move_family=suggestion.move_family,
        target_id=suggestion.target_id,
        scene_frame=suggestion.scene_frame,
        semantic_effects=[SemanticEffect(effect_type="confrontation")],
    )

    next_state, _ = apply_turn_resolution(v2_plan, state, intent)

    assert next_state.hook_states[seeded_hook.hook_id].status == "active"
    assert f"hook_transition:{seeded_hook.hook_id}" in next_state.last_turn_tags
