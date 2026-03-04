from __future__ import annotations

import json
from pathlib import Path

import pytest

from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.runtime.errors import RuntimeNarrationError, RuntimeRouteError
from rpg_backend.runtime.service import RuntimeService
from tests.helpers.providers import (
    AlwaysGlobalHelpProvider,
    DeterministicProvider,
    InvalidMoveProvider,
    LowConfidenceProvider,
    NarrationFailureProvider,
    RouteFailureProvider,
)

PACK_PATH = Path("sample_data/story_pack_v1.json")


def _load_pack() -> StoryPack:
    return StoryPack.model_validate(json.loads(PACK_PATH.read_text(encoding="utf-8")))


def _move_id_for_style(pack: StoryPack, scene_id: str, strategy_style: str) -> str:
    move_map = {move.id: move for move in pack.moves}
    scene_map = {scene.id: scene for scene in pack.scenes}
    scene = scene_map[scene_id]
    for move_id in scene.enabled_moves:
        move = move_map.get(move_id)
        if move is not None and move.strategy_style == strategy_style:
            return move_id
    raise AssertionError(f"missing move for strategy_style={strategy_style} in scene={scene_id}")


def _set_present_npc_conflict_tags(pack: StoryPack, scene_id: str, tags: list[str]) -> None:
    scene_map = {scene.id: scene for scene in pack.scenes}
    present = set(scene_map[scene_id].present_npcs)
    for profile in pack.npc_profiles:
        if profile.name in present:
            profile.conflict_tags = list(tags)


def test_fail_forward_for_always_fail_forward_move() -> None:
    pack = _load_pack()
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "button", "move_id": "global.help_me_progress"},
        dev_mode=True,
    )

    assert result["recognized"]["move_id"] == "global.help_me_progress"
    assert result["resolution"]["result"] == "fail_forward"
    assert result["resolution"]["consequences_summary"] != "none"


def test_empty_text_can_progress_when_route_returns_confident_move() -> None:
    pack = _load_pack()
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "text", "text": ""},
    )

    assert result["recognized"]["move_id"]
    assert result["recognized"]["route_source"] == "llm"
    assert result["scene_id"] != scene_id


def test_route_failure_raises_runtime_route_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(RouteFailureProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeRouteError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "do something risky"},
        )

    assert exc_info.value.error_code == "llm_route_failed"
    assert exc_info.value.stage == "route"


def test_low_confidence_raises_runtime_route_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(LowConfidenceProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeRouteError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "???"},
        )

    assert exc_info.value.error_code == "llm_route_low_confidence"
    assert exc_info.value.stage == "route"


def test_narration_failure_raises_runtime_narration_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(NarrationFailureProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeNarrationError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "help me progress"},
        )

    assert exc_info.value.error_code == "llm_narration_failed"
    assert exc_info.value.stage == "narration"


def test_invalid_move_raises_runtime_route_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(InvalidMoveProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeRouteError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "do a hidden action"},
        )

    assert exc_info.value.error_code == "llm_route_invalid_move"
    assert exc_info.value.stage == "route"


def test_non_help_text_disallows_global_help_route() -> None:
    pack = _load_pack()
    runtime = RuntimeService(AlwaysGlobalHelpProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeRouteError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "stabilize corridor and keep trust high"},
        )

    assert exc_info.value.error_code == "llm_route_invalid_move"
    assert exc_info.value.stage == "route"


def test_explicit_help_text_allows_global_help_route() -> None:
    pack = _load_pack()
    runtime = RuntimeService(AlwaysGlobalHelpProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "text", "text": "help, I am stuck and need the next step"},
    )

    assert result["recognized"]["move_id"] == "global.help_me_progress"
    assert result["recognized"]["route_source"] == "llm"


def test_pressure_recoil_and_stance_summary_visible_in_late_beats() -> None:
    pack = _load_pack()
    runtime = RuntimeService(DeterministicProvider())
    move_style = {move.id: move.strategy_style for move in pack.moves}
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    pressure_recoil_seen = False
    stance_line_seen = False

    for _ in range(16):
        ui_moves = runtime.list_ui_moves(pack, scene_id)
        chosen_move_id = ui_moves[0]["move_id"] if ui_moves else "global.clarify"
        for ui_move in ui_moves:
            move_id = ui_move["move_id"]
            if move_style.get(move_id) == "fast_dirty":
                chosen_move_id = move_id
                break

        result = runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "button", "move_id": chosen_move_id},
            dev_mode=True,
        )
        scene_id = result["scene_id"]
        beat_index = result["beat_index"]

        if result.get("debug", {}).get("pressure_recoil_triggered"):
            pressure_recoil_seen = True
            assert "Pressure recoil:" in result["resolution"]["consequences_summary"]
        if "Stance update:" in result["narration_text"]:
            stance_line_seen = True

        if result["ended"]:
            break

    assert pressure_recoil_seen is True
    assert stance_line_seen is True


def test_style_conflict_uses_anti_noise_tag() -> None:
    pack = _load_pack()
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    _set_present_npc_conflict_tags(pack, scene_id, ["anti_noise"])
    move_id = _move_id_for_style(pack, scene_id, "fast_dirty")
    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "button", "move_id": move_id},
        dev_mode=True,
    )
    assert result["debug"]["stance_snapshot"]["red_line_hits"]

    pack = _load_pack()
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)
    _set_present_npc_conflict_tags(pack, scene_id, ["anti_noise"])
    move_id = _move_id_for_style(pack, scene_id, "steady_slow")
    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "button", "move_id": move_id},
        dev_mode=True,
    )
    assert result["debug"]["stance_snapshot"]["red_line_hits"] == []


def test_style_conflict_uses_anti_speed_tag() -> None:
    pack = _load_pack()
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)
    _set_present_npc_conflict_tags(pack, scene_id, ["anti_speed"])
    move_id = _move_id_for_style(pack, scene_id, "steady_slow")
    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "button", "move_id": move_id},
        dev_mode=True,
    )
    assert result["debug"]["stance_snapshot"]["red_line_hits"]


def test_style_conflict_uses_anti_resource_burn_tag() -> None:
    pack = _load_pack()
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)
    _set_present_npc_conflict_tags(pack, scene_id, ["anti_resource_burn"])
    move_id = _move_id_for_style(pack, scene_id, "political_safe_resource_heavy")
    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "button", "move_id": move_id},
        dev_mode=True,
    )
    assert result["debug"]["stance_snapshot"]["red_line_hits"]
