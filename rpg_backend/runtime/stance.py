from __future__ import annotations

from typing import Any

from rpg_backend.domain.pack_schema import NPCProfile

STYLE_CONFLICT_TAG: dict[str, str] = {
    "fast_dirty": "anti_noise",
    "steady_slow": "anti_speed",
    "political_safe_resource_heavy": "anti_resource_burn",
}


def npc_profile_map(npc_profiles: list[NPCProfile]) -> dict[str, NPCProfile]:
    return {profile.name: profile for profile in npc_profiles}


def classify_stance(trust_value: int) -> str:
    if trust_value >= 2:
        return "support"
    if trust_value <= -2:
        return "oppose"
    return "contested"


def style_conflicts_profile(strategy_style: str, conflict_tags: list[str]) -> bool:
    required_tag = STYLE_CONFLICT_TAG.get(strategy_style)
    if not required_tag:
        return False
    return required_tag in set(conflict_tags)


def apply_npc_stance_effects(
    *,
    state: dict[str, Any],
    present_npcs: list[str],
    strategy_style: str,
    npc_profiles: dict[str, NPCProfile],
) -> dict[str, Any]:
    state.setdefault("values", {})
    state.setdefault("events", [])
    values = state["values"]

    support: list[str] = []
    oppose: list[str] = []
    contested: list[str] = []
    red_line_hits: list[str] = []

    for npc_name in present_npcs:
        profile = npc_profiles.get(npc_name)
        if profile is None:
            continue
        trust_key = f"npc_trust::{npc_name}"
        current = int(values.get(trust_key, 0))
        conflict = style_conflicts_profile(strategy_style, list(profile.conflict_tags))
        delta = -2 if conflict else 1
        values[trust_key] = current + delta
        if conflict:
            red_line_hits.append(npc_name)
            event_key = f"redline_hit::{npc_name}"
            if event_key not in state["events"]:
                state["events"].append(event_key)

        stance = classify_stance(int(values[trust_key]))
        if stance == "support":
            support.append(npc_name)
        elif stance == "oppose":
            oppose.append(npc_name)
        else:
            contested.append(npc_name)

    return {
        "support": support,
        "oppose": oppose,
        "contested": contested,
        "red_line_hits": red_line_hits,
    }


def build_stance_summary(stance_snapshot: dict[str, Any]) -> str:
    support = stance_snapshot.get("support", [])
    oppose = stance_snapshot.get("oppose", [])
    red_line_hits = stance_snapshot.get("red_line_hits", [])

    support_text = ", ".join(support[:2]) if support else "none"
    oppose_text = ", ".join(oppose[:2]) if oppose else "none"
    redline_text = ", ".join(red_line_hits[:2]) if red_line_hits else "none"
    return (
        f"Stance update: supporters={support_text}; opponents={oppose_text}; "
        f"red-line pressure={redline_text}."
    )
