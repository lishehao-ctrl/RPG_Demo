from __future__ import annotations

from typing import Any

from rpg_backend.domain.pack_schema import StoryPack


def initialize_session_state(pack: StoryPack) -> tuple[str, int, dict[str, Any], dict[str, int]]:
    first_beat = pack.beats[0]
    beat_progress = {beat.id: 0 for beat in pack.beats}
    state = {
        "events": [],
        "inventory": [],
        "flags": {},
        "values": {
            "cost_total": 0,
            "public_trust": 0,
            "resource_stress": 0,
            "coordination_noise": 0,
            "time_spent": 0,
            "runtime_turn": 0,
        },
    }
    for profile in pack.npc_profiles:
        state["values"][f"npc_trust::{profile.name}"] = 0
    return first_beat.entry_scene_id, 0, state, beat_progress
