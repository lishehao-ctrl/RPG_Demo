from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import CallbackQueueItem, HookState, SemanticEffect, UrbanTurnIntent, UrbanWorldState
from rpg_backend.play_v2.hook_engine import (
    HookTurnEvents,
    build_hook_callback_question,
    get_hook_callback_hook_id,
    is_hook_callback_item,
    register_hook_callbacks,
    update_hook_states,
)
from rpg_backend.play_v2.runtime import build_initial_world_state, run_turn


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
    hook_states: dict[str, HookState] | None = None,
    callback_queue: list[CallbackQueueItem] | None = None,
    turn_index: int = 0,
    segment_id: str = "seg_test",
) -> UrbanWorldState:
    return UrbanWorldState.model_construct(
        hook_states=dict(hook_states or {}),
        callback_queue=list(callback_queue or []),
        turn_index=turn_index,
        segment_id=segment_id,
        scene_question_states={segment_id: object()},
    )


def _make_hook_callback_item(
    *,
    callback_kind: str,
    hook_id: str,
    due_turn: int,
    holder_id: str = "holder_a",
    target_id: str = "target_b",
    latent_kind: str = "secret_pressure",
) -> CallbackQueueItem:
    return CallbackQueueItem(
        callback_id=f"hookcb_{callback_kind}_{hook_id}",
        status="pending",
        source_turn_index=max(due_turn - 1, 0),
        source_segment_id="seg_test",
        source_move_family="probe_secret",  # type: ignore[arg-type]
        linked_shell_edge_id=None,
        linked_scene_question_id="seg_test",
        due_turn_min=due_turn,
        due_turn_max=due_turn,
        kind=latent_kind,  # type: ignore[arg-type]
        payoff_kind=callback_kind,
        stake_character_ids=[holder_id, target_id],
        target_character_ids=[target_id],
        actor_character_id=holder_id,
        cue_text=f"{holder_id} 那边还有账没清。",
        detonation_text=f"你该怎么面对 {holder_id} 手里的把柄？",
        global_deltas={},
        relationship_deltas={},
    )


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
    if plan.hooks:
        return str(plan.hooks[0].get("target_id") or "").strip()
    raise AssertionError("Expected v3 plan to contain hooks.")


def _prepare_demo_v3_plan(plan: CompiledPlayPlan) -> CompiledPlayPlan:
    demo_plan = plan.model_copy(deep=True)
    matrix = demo_plan.semantic_strategy_pack.cost_routing_matrix
    cost_rules = list(matrix.rules)
    existing_move_families = {rule.move_family for rule in cost_rules}
    prototype = next(rule for rule in cost_rules if rule.move_family == "accuse")
    for move_family in ("probe_secret", "flirt", "betray", "public_reveal"):
        if move_family in existing_move_families:
            continue
        cost_rules.append(
            prototype.model_copy(
                update={
                    "rule_id": f"{prototype.rule_id}_{move_family}",
                    "move_family": move_family,
                }
            )
        )
    return demo_plan.model_copy(
        update={
            "semantic_strategy_pack": demo_plan.semantic_strategy_pack.model_copy(
                update={
                    "cost_routing_matrix": matrix.model_copy(update={"rules": cost_rules})
                }
            )
        }
    )


def _run_scripted_turn(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    *,
    input_text: str,
    move_family: str,
    target_id: str,
    scene_frame: str = "private",
    effect_types: tuple[str, ...] = (),
):
    return run_turn(
        plan,
        state,
        input_text,
        precomputed_intent=UrbanTurnIntent(
            input_text=input_text,
            move_family=move_family,  # type: ignore[arg-type]
            target_id=target_id,
            scene_frame=scene_frame,  # type: ignore[arg-type]
            semantic_effects=[
                SemanticEffect(effect_type=effect_type, target_id=target_id)
                for effect_type in effect_types
            ],
        ),
    )


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


@pytest.fixture(scope="module")
def v2_plan() -> CompiledPlayPlan:
    preview, _ = run_preview_blueprint_graph("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。")
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan


@pytest.mark.parametrize(
    ("status", "callback_kind", "due_offset", "latent_kind", "source_move_family"),
    [
        ("suspected", "hook_probe_callback", 3, "secret_pressure", "probe_secret"),
        ("active", "hook_pressure_callback", 2, "npc_action", "accuse"),
        ("leveraged", "hook_leverage_cash_callback", 2, "relationship_debt", "betray"),
        ("detonated", "hook_aftermath_callback", 1, "public_wave", "public_reveal"),
    ],
)
def test_register_hook_callbacks_emits_correct_queue_shape_for_each_transition(
    status: str,
    callback_kind: str,
    due_offset: int,
    latent_kind: str,
    source_move_family: str,
) -> None:
    hook = _make_hook_state(status=status, holder_id="liu_jianfeng", target_id="wang_siyu", source_secret_id="sec_board")
    state = _make_state(hook_states={hook.hook_id: hook}, turn_index=4)

    register_hook_callbacks(state, [hook.hook_id], 4)

    assert len(state.callback_queue) == 1
    callback = state.callback_queue[0]
    assert callback.payoff_kind == callback_kind
    assert callback.kind == latent_kind
    assert callback.source_move_family == source_move_family
    assert callback.due_turn_min == 4 + due_offset
    assert callback.due_turn_max == 4 + due_offset
    assert callback.actor_character_id == "liu_jianfeng"
    assert callback.target_character_ids == ["wang_siyu"]
    assert callback.callback_id.endswith(hook.hook_id)
    assert callback.detonation_text == "你该怎么面对 liu_jianfeng 手里的把柄？"


def test_register_hook_callbacks_deduplicates_same_kind_and_hook_id() -> None:
    hook = _make_hook_state(status="suspected", holder_id="zhang_hao", target_id="chen_weiming", source_secret_id="sec_patent")
    existing = _make_hook_callback_item(
        callback_kind="hook_probe_callback",
        hook_id=hook.hook_id,
        due_turn=7,
        holder_id=hook.holder_id,
        target_id=hook.target_id,
    )
    state = _make_state(hook_states={hook.hook_id: hook}, callback_queue=[existing], turn_index=4)

    register_hook_callbacks(state, [hook.hook_id], 4)

    assert len(state.callback_queue) == 1
    assert state.callback_queue[0].callback_id == existing.callback_id


def test_register_hook_callbacks_drops_oldest_entries_on_queue_overflow() -> None:
    hook = _make_hook_state(status="suspected", holder_id="wang_siyu", target_id="chen_weiming", source_secret_id="sec_financial")
    existing_queue = [
        _make_hook_callback_item(
            callback_kind="hook_probe_callback",
            hook_id=f"hook_{index}",
            due_turn=index + 1,
        )
        for index in range(8)
    ]
    state = _make_state(hook_states={hook.hook_id: hook}, callback_queue=existing_queue, turn_index=10)

    register_hook_callbacks(state, [hook.hook_id], 10)

    assert len(state.callback_queue) == 8
    assert all(item.due_turn_min != 1 for item in state.callback_queue)
    assert any(item.callback_id.endswith(hook.hook_id) for item in state.callback_queue)


def test_update_hook_states_with_none_turn_index_skips_callback_registration_without_error() -> None:
    hook = _make_hook_state(status="dormant", holder_id="holder_a", target_id="target_b", source_secret_id="sec_hidden")
    state = SimpleNamespace(
        hook_states={hook.hook_id: hook},
        callback_queue=[],
    )

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
        turn_index=None,
    )

    assert changed == [hook.hook_id]
    assert state.hook_states[hook.hook_id].status == "suspected"
    assert state.callback_queue == []


def test_hook_callback_helper_functions_round_trip_identity() -> None:
    callback = _make_hook_callback_item(
        callback_kind="hook_pressure_callback",
        hook_id="liu_jianfeng__wang_siyu__sec_board",
        due_turn=5,
        holder_id="liu_jianfeng",
        target_id="wang_siyu",
        latent_kind="npc_action",
    )

    assert is_hook_callback_item(callback) is True
    assert get_hook_callback_hook_id(callback) == "liu_jianfeng__wang_siyu__sec_board"
    assert build_hook_callback_question(callback) == "你该怎么面对 liu_jianfeng 手里的把柄？"


def test_hook_callback_helpers_ignore_non_hook_callbacks() -> None:
    callback = CallbackQueueItem(
        callback_id="cb_1_seg_test_0",
        status="pending",
        source_turn_index=1,
        source_segment_id="seg_test",
        source_move_family="comfort",
        linked_shell_edge_id=None,
        linked_scene_question_id="seg_test",
        due_turn_min=3,
        due_turn_max=4,
        kind="relationship_debt",
        payoff_kind="public_shame",
        stake_character_ids=["target_b"],
        target_character_ids=["target_b"],
        actor_character_id="target_b",
        cue_text="这步动作留下了后账。",
        detonation_text="后账到期了。",
        global_deltas={},
        relationship_deltas={},
    )

    assert is_hook_callback_item(callback) is False
    assert get_hook_callback_hook_id(callback) is None
    assert build_hook_callback_question(callback) == "你该怎么面对 target_b 手里的把柄？"


def test_runtime_hook_callback_tag_and_diagnostics_helpers_fire_within_five_turns(v3_plan: CompiledPlayPlan) -> None:
    demo_plan = _prepare_demo_v3_plan(v3_plan)
    target_id = _find_demo_hook_target(demo_plan)
    state = build_initial_world_state(demo_plan, session_id="hook_callbacks_v3_e2e")
    turn_specs = [
        ("probe_secret", "我先试探她到底藏了什么。", "private", ()),
        ("flirt", "我先贴近一步，看看谁先露怯。", "private", ()),
        ("accuse", "我先把话挑明，逼她正面回应。", "private", ("confrontation",)),
        ("betray", "我准备反手切割，把风险先丢回去。", "private", ("betrayal",)),
        ("public_reveal", "我直接把证据摔到台面上。", "public", ("secret_reveal", "public_exposure")),
    ]
    results = []
    for move_family, input_text, scene_frame, effect_types in turn_specs:
        result = _run_scripted_turn(
            demo_plan,
            state,
            input_text=input_text,
            move_family=move_family,
            target_id=target_id,
            scene_frame=scene_frame,
            effect_types=effect_types,
        )
        results.append(result.model_copy(deep=True))
        state = result.state

    assert results[-1].state.callback_queue
    fired_results = [
        result
        for result in results
        if any(tag.startswith("callback_fired:hook_") for tag in result.state.last_turn_tags)
    ]
    assert fired_results
    diagnostic_payload = fired_results[0].intent_stage_diagnostics.get("hook_callbacks_fired")
    assert diagnostic_payload
    fired_entries = json.loads(str(diagnostic_payload))
    assert fired_entries
    assert fired_entries[0].startswith("callback_fired:hook_")
    assert any("你该怎么面对" in consequence for consequence in fired_results[0].state.last_turn_consequences)


def test_runtime_hook_callback_diagnostics_record_json_list_strings(v3_plan: CompiledPlayPlan) -> None:
    demo_plan = _prepare_demo_v3_plan(v3_plan)
    target_id = _find_demo_hook_target(demo_plan)
    state = build_initial_world_state(demo_plan, session_id="hook_callbacks_v3_diag_shape")

    first = _run_scripted_turn(
        demo_plan,
        state,
        input_text="我先追问她手里到底扣着什么。",
        move_family="probe_secret",
        target_id=target_id,
    )
    second = _run_scripted_turn(
        demo_plan,
        first.state,
        input_text="我先稳住气氛。",
        move_family="flirt",
        target_id=target_id,
    )
    third = _run_scripted_turn(
        demo_plan,
        second.state,
        input_text="我再往前压一步。",
        move_family="accuse",
        target_id=target_id,
        effect_types=("confrontation",),
    )
    fourth = _run_scripted_turn(
        demo_plan,
        third.state,
        input_text="我准备切割她。",
        move_family="betray",
        target_id=target_id,
        effect_types=("betrayal",),
    )

    payload = fourth.intent_stage_diagnostics.get("hook_callbacks_fired")

    assert isinstance(payload, str)
    assert json.loads(payload)
    assert fourth.intent_stage_diagnostics.get("hook_callbacks_fired_count") == 1


def test_v2_plan_without_hooks_runs_same_path_without_hook_side_effects(v2_plan: CompiledPlayPlan) -> None:
    state = build_initial_world_state(v2_plan, session_id="hook_callbacks_v2_regression")
    result = run_turn(v2_plan, state, "我先稳住她，不让这件事立刻炸开。")

    assert result.state.hook_states == {}
    assert not any(tag.startswith("callback_fired:hook_") for tag in result.state.last_turn_tags)
    assert "hook_callbacks_fired" not in result.intent_stage_diagnostics
    assert result.state.last_turn_callback_status is not None
