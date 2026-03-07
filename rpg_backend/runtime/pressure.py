from __future__ import annotations

from typing import Any

from rpg_backend.domain.pack_schema import StoryPack


def apply_pressure_recoil(
    *,
    pack: StoryPack,
    beat_index: int,
    state: dict[str, Any],
    costs: list[str],
    consequences: list[str],
) -> bool:
    if beat_index < max(len(pack.beats) - 2, 0):
        return False

    values = state.setdefault("values", {})
    events = state.setdefault("events", [])
    turn = int(values.get("runtime_turn", 0))
    triggered = False

    recoil_specs = (
        (
            "public_trust",
            lambda val: int(val) <= -3,
            "pressure_recoil.public_trust",
            "Pressure recoil: public trust backlash limits your maneuvering room.",
        ),
        (
            "resource_stress",
            lambda val: int(val) >= 4,
            "pressure_recoil.resource_stress",
            "Pressure recoil: resource stress forces emergency rationing.",
        ),
        (
            "coordination_noise",
            lambda val: int(val) >= 4,
            "pressure_recoil.coordination_noise",
            "Pressure recoil: coordination noise creates command drift.",
        ),
    )

    for track_key, predicate, event_key, message in recoil_specs:
        current_val = int(values.get(track_key, 0))
        if not predicate(current_val):
            continue

        cooldown_key = f"recoil_last_turn::{track_key}"
        last_turn = int(values.get(cooldown_key, -999))
        if turn - last_turn < 2:
            continue

        values[cooldown_key] = turn
        if event_key not in events:
            events.append(event_key)
        values["cost_total"] = int(values.get("cost_total", 0)) + 1
        costs.append("Pressure recoil +1")
        consequences.append(message)
        triggered = True

    return triggered
