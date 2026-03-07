from __future__ import annotations

from typing import Any

from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.llm.base import LLMProvider
from rpg_backend.runtime.effects import apply_effects
from rpg_backend.runtime.narration import render_echo_commit_hook
from rpg_backend.runtime.pressure import apply_pressure_recoil
from rpg_backend.runtime.resolver import choose_outcome, resolve_next_scene
from rpg_backend.runtime.results import RuntimeStepResult
from rpg_backend.runtime.router import route_player_action
from rpg_backend.runtime.stance import apply_npc_stance_effects, build_stance_summary, npc_profile_map
from rpg_backend.runtime.ui import list_ui_moves, move_map, scene_map


def _beat_index_by_id(pack: StoryPack) -> dict[str, int]:
    return {beat.id: idx for idx, beat in enumerate(pack.beats)}


async def process_runtime_step(
    *,
    provider: LLMProvider,
    pack: StoryPack,
    current_scene_id: str,
    beat_index: int,
    state: dict[str, Any],
    beat_progress: dict[str, int],
    action_input: dict[str, Any],
    dev_mode: bool = False,
) -> RuntimeStepResult:
    scenes = scene_map(pack)
    moves = move_map(pack)
    beat_index_map = _beat_index_by_id(pack)
    profiles = npc_profile_map(pack.npc_profiles)

    scene = scenes[current_scene_id]
    current_beat = pack.beats[beat_index] if 0 <= beat_index < len(pack.beats) else None
    recognized = await route_player_action(
        provider,
        scene,
        moves,
        action_input,
        state=state,
        beat_progress=beat_progress,
        beat=current_beat,
        beat_index=beat_index,
    )
    chosen_move = moves[recognized["move_id"]]

    state.setdefault("values", {})
    state["values"]["last_move"] = chosen_move.id
    state["values"]["runtime_turn"] = int(state["values"].get("runtime_turn", 0)) + 1
    runtime_turn = int(state["values"]["runtime_turn"])

    current_beat_id = scene.beat_id
    outcome = choose_outcome(chosen_move, state, beat_progress, current_beat_id)
    costs, consequences, _ = apply_effects(outcome.effects, state, beat_progress, current_beat_id)

    stance_snapshot = apply_npc_stance_effects(
        state=state,
        present_npcs=list(scene.present_npcs),
        strategy_style=chosen_move.strategy_style,
        npc_profiles=profiles,
    )
    pressure_recoil_triggered = apply_pressure_recoil(
        pack=pack,
        beat_index=beat_index,
        state=state,
        costs=costs,
        consequences=consequences,
    )

    next_scene_id, ended = resolve_next_scene(scene, outcome, state, beat_progress, current_beat_id)
    if next_scene_id is not None:
        current_scene_id = next_scene_id

    next_scene = scenes[current_scene_id]
    beat_index = beat_index_map[next_scene.beat_id]

    stance_summary = build_stance_summary(stance_snapshot) if runtime_turn % 2 == 0 else None
    narration_result = await render_echo_commit_hook(
        provider,
        outcome.narration_slots,
        recognized["interpreted_intent"],
        outcome.result,
        pack.style_guard,
        strategy_style=chosen_move.strategy_style,
        stance_summary=stance_summary,
    )
    narration_text = str(narration_result["text"])

    debug = None
    if dev_mode:
        debug = {
            "selected_move": chosen_move.id,
            "selected_outcome": outcome.id,
            "selected_strategy_style": chosen_move.strategy_style,
            "pressure_recoil_triggered": pressure_recoil_triggered,
            "stance_snapshot": stance_snapshot,
            "state": state,
            "beat_progress": beat_progress,
        }

    return RuntimeStepResult(
        scene_id=current_scene_id,
        beat_index=beat_index,
        ended=ended,
        narration_text=narration_text,
        recognized=recognized,
        resolution={
            "result": outcome.result,
            "costs_summary": "; ".join(costs) if costs else "none",
            "consequences_summary": "; ".join(consequences) if consequences else "none",
        },
        ui={
            "moves": list_ui_moves(pack, current_scene_id),
            "input_hint": pack.input_hint,
        },
        runtime_metrics={
            "route_llm_duration_ms": recognized.get("llm_duration_ms"),
            "route_llm_gateway_mode": recognized.get("llm_gateway_mode"),
            "narration_llm_duration_ms": narration_result.get("llm_duration_ms"),
            "narration_llm_gateway_mode": narration_result.get("llm_gateway_mode"),
        },
        debug=debug,
    )
