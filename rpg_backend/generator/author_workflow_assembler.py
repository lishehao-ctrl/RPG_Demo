from __future__ import annotations

import random
from typing import Any

from rpg_backend.domain.move_library import GLOBAL_MOVE_TEMPLATE_IDS, MOVE_TEMPLATE_BY_ID
from rpg_backend.domain.opening_guidance import build_opening_guidance_payload
from rpg_backend.generator.author_workflow_models import BeatBlueprint, BeatDraft, StoryOverview
from rpg_backend.generator.move_materialization import materialize_move_from_template


def assemble_story_pack(
    *,
    story_id: str,
    overview: StoryOverview,
    beat_blueprints: list[BeatBlueprint],
    beat_drafts: list[BeatDraft],
) -> dict[str, Any]:
    overview_npcs = [npc.name for npc in overview.npc_roster]
    scene_map = {scene.id: scene.model_dump(mode="json") for beat in beat_drafts for scene in beat.scenes}

    ordered_scenes: list[dict[str, Any]] = []
    for index, beat in enumerate(beat_drafts):
        local_scenes = [scene_map[scene.id] for scene in beat.scenes]
        if local_scenes:
            last_scene = local_scenes[-1]
            local_scenes[-1] = dict(last_scene)
            exit_conditions = list(last_scene.get("exit_conditions") or [])
            if index < len(beat_blueprints) - 1:
                exit_conditions.append(
                    {
                        "id": f"{beat.beat_id}.to_next",
                        "condition_kind": "event_present",
                        "key": beat.required_event,
                        "next_scene_id": beat_blueprints[index + 1].entry_scene_id,
                        "end_story": False,
                    }
                )
            else:
                exit_conditions.append(
                    {
                        "id": f"{beat.beat_id}.finale",
                        "condition_kind": "event_present",
                        "key": beat.required_event,
                        "next_scene_id": None,
                        "end_story": True,
                    }
                )
                local_scenes[-1]["is_terminal"] = True
            local_scenes[-1]["exit_conditions"] = exit_conditions
        ordered_scenes.extend(local_scenes)

    local_moves = [move.model_dump(mode="json") for beat in beat_drafts for move in beat.moves]
    palette_usage: dict[str, int] = {}
    rng = random.Random(story_id)
    global_moves = [
        materialize_move_from_template(template=MOVE_TEMPLATE_BY_ID[move_id], npcs=overview_npcs, rng=rng, palette_policy="random", palette_usage=palette_usage)
        for move_id in GLOBAL_MOVE_TEMPLATE_IDS
    ]
    move_map = {move["id"]: move for move in global_moves}
    move_map.update({move["id"]: move for move in local_moves})

    first_beat = beat_blueprints[0] if beat_blueprints else None
    first_scene = ordered_scenes[0] if ordered_scenes else None
    first_scene_move_ids = [
        *[move_id for move_id in (first_scene or {}).get("enabled_moves", []) if isinstance(move_id, str)],
        *[move_id for move_id in (first_scene or {}).get("always_available_moves", []) if isinstance(move_id, str)],
    ]
    first_scene_moves = [
        {"move_id": move_id, "label": str(move_map.get(move_id, {}).get("label") or move_id)}
        for move_id in first_scene_move_ids
    ]

    return {
        "story_id": story_id,
        "title": overview.title,
        "description": f"{overview.premise} Stakes: {overview.stakes}".strip(),
        "ending_shape_note": overview.ending_shape_note,
        "move_bias_note": overview.move_bias_note,
        "npcs": overview_npcs,
        "npc_profiles": [
            {
                "name": npc.name,
                "red_line": npc.red_line,
                "conflict_tags": list(npc.conflict_tags),
                "pressure_signature": npc.pressure_signature,
            }
            for npc in overview.npc_roster
        ],
        "beats": [
            {
                "id": beat.beat_id,
                "title": beat.title,
                "step_budget": beat.step_budget,
                "required_events": [beat.required_event],
                "npc_quota": beat.npc_quota,
                "entry_scene_id": beat.entry_scene_id,
            }
            for beat in beat_blueprints
        ],
        "scenes": ordered_scenes,
        "moves": list(move_map.values()),
        "input_hint": "Describe what you do next.",
        "style_guard": f"Tone: {overview.tone}. Keep narration concise, concrete, and forward-moving.",
        "opening_guidance": build_opening_guidance_payload(
            title=overview.title,
            description=f"{overview.premise} Stakes: {overview.stakes}".strip(),
            input_hint="Describe what you do next.",
            first_beat_title=first_beat.title if first_beat else "the opening beat",
            first_scene_seed=str((first_scene or {}).get("scene_seed") or "The opening scene is already unstable."),
            first_scene_npcs=[npc for npc in (first_scene or {}).get("present_npcs", []) if isinstance(npc, str)],
            first_scene_moves=first_scene_moves,
        ),
    }
