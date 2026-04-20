from __future__ import annotations

import pytest

from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import SemanticEffect, UrbanTurnIntent
from rpg_backend.play_v2.runtime import apply_turn_resolution, build_initial_world_state


def _hook_id(raw_hook: dict[str, str]) -> str:
    return f"{raw_hook['holder_id']}__{raw_hook['target_id']}__{raw_hook['source_secret_id']}"


def _first_hook(plan: CompiledPlayPlan) -> tuple[dict[str, str], str]:
    raw_hook = dict((plan.hooks or [])[0])
    return raw_hook, _hook_id(raw_hook)


def _isolated_v3_state(plan: CompiledPlayPlan, *, session_id: str):
    raw_hook, hook_id = _first_hook(plan)
    state = build_initial_world_state(plan, session_id=session_id)
    state.hook_states = {hook_id: state.hook_states[hook_id]}
    return state, raw_hook, hook_id


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


@pytest.fixture(scope="module")
def v2_plan() -> CompiledPlayPlan:
    preview, _ = run_preview_blueprint_graph("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。")
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan


def test_v3_probe_secret_three_times_moves_hook_out_of_dormant(v3_plan: CompiledPlayPlan) -> None:
    state, raw_hook, hook_id = _isolated_v3_state(v3_plan, session_id="hook_lifecycle_probe_three")

    for idx in range(3):
        state, _ = apply_turn_resolution(
            v3_plan,
            state,
            UrbanTurnIntent(
                input_text=f"我第 {idx + 1} 次追问她手里那张牌到底是什么。",
                move_family="probe_secret",
                target_id=raw_hook["holder_id"],
                scene_frame="private",
                semantic_effects=[SemanticEffect(effect_type="secret_reveal", target_id=raw_hook["holder_id"])],
            ),
        )

    assert state.hook_states[hook_id].status in {"suspected", "active", "leveraged", "detonated"}


def test_v3_repeated_probe_secret_upgrades_hook_to_active_and_marks_secret_known(v3_plan: CompiledPlayPlan) -> None:
    state, raw_hook, hook_id = _isolated_v3_state(v3_plan, session_id="hook_lifecycle_probe_active")

    for _ in range(2):
        state, _ = apply_turn_resolution(
            v3_plan,
            state,
            UrbanTurnIntent(
                input_text="我继续追问她到底扣着谁的把柄。",
                move_family="probe_secret",
                target_id=raw_hook["holder_id"],
                scene_frame="private",
                semantic_effects=[SemanticEffect(effect_type="secret_reveal", target_id=raw_hook["holder_id"])],
            ),
        )

    assert state.hook_states[hook_id].status == "active"
    assert raw_hook["source_secret_id"] in state.known_secret_ids


def test_v3_accuse_detonates_existing_leveraged_hook(v3_plan: CompiledPlayPlan) -> None:
    state, raw_hook, hook_id = _isolated_v3_state(v3_plan, session_id="hook_lifecycle_accuse_detonate")
    state.hook_states[hook_id] = state.hook_states[hook_id].model_copy(update={"status": "leveraged", "leverage_value": 0.75})

    next_state, _ = apply_turn_resolution(
        v3_plan,
        state,
        UrbanTurnIntent(
            input_text="我当面点破这件事，逼她认下来。",
            move_family="accuse",
            target_id=raw_hook["target_id"],
            scene_frame="private",
            semantic_effects=[SemanticEffect(effect_type="confrontation", target_id=raw_hook["target_id"])],
        ),
    )

    assert next_state.hook_states[hook_id].status == "detonated"
    assert raw_hook["source_secret_id"] in next_state.last_turn_revealed_secret_ids


def test_v3_public_reveal_marks_secret_revealed_and_detonates_hook(v3_plan: CompiledPlayPlan) -> None:
    state, raw_hook, hook_id = _isolated_v3_state(v3_plan, session_id="hook_lifecycle_public_reveal")

    next_state, _ = apply_turn_resolution(
        v3_plan,
        state,
        UrbanTurnIntent(
            input_text="我直接把她压着的那件事当众说破。",
            move_family="public_reveal",
            target_id=raw_hook["target_id"],
            scene_frame="public",
            semantic_effects=[SemanticEffect(effect_type="public_exposure", target_id=raw_hook["target_id"])],
        ),
    )

    assert next_state.last_turn_revealed_secret_ids
    assert raw_hook["source_secret_id"] in next_state.last_turn_revealed_secret_ids
    assert next_state.hook_states[hook_id].status == "detonated"


def test_v2_plan_without_hooks_leaves_hook_states_empty(v2_plan: CompiledPlayPlan) -> None:
    state = build_initial_world_state(v2_plan, session_id="hook_lifecycle_v2_compat")
    target_id = next(iter(state.relationships))

    next_state, _ = apply_turn_resolution(
        v2_plan,
        state,
        UrbanTurnIntent(
            input_text="我先试探她有没有把真相往外放。",
            move_family="probe_secret",
            target_id=target_id,
            scene_frame="private",
            semantic_effects=[SemanticEffect(effect_type="secret_reveal", target_id=target_id)],
        ),
    )

    assert next_state.hook_states == {}
