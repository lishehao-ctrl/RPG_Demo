from __future__ import annotations

from typing import Any

from rpg_backend.domain.pack_schema import Move, Scene, StoryPack

STRATEGY_RISK_HINTS = {
    "fast_dirty": "fast but dirty: raises noise and trust risk",
    "steady_slow": "steady but slow: lowers noise but spends time",
    "political_safe_resource_heavy": "politically safe: spends resources to preserve trust",
}


def scene_map(pack: StoryPack) -> dict[str, Scene]:
    return {scene.id: scene for scene in pack.scenes}


def move_map(pack: StoryPack) -> dict[str, Move]:
    return {move.id: move for move in pack.moves}


def list_ui_moves(pack: StoryPack, scene_id: str) -> list[dict[str, Any]]:
    scenes = scene_map(pack)
    moves = move_map(pack)
    scene = scenes[scene_id]
    move_ids = list(dict.fromkeys(scene.enabled_moves + scene.always_available_moves))
    ui_moves = []
    for move_id in move_ids:
        move = moves.get(move_id)
        if move is None:
            continue
        ui_moves.append(
            {
                "move_id": move.id,
                "label": move.label,
                "risk_hint": STRATEGY_RISK_HINTS.get(move.strategy_style, "has fail-forward consequences"),
            }
        )
    return ui_moves
