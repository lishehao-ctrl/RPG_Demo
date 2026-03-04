from __future__ import annotations

import json
import random
from copy import deepcopy
from pathlib import Path
from typing import Any

from rpg_backend.domain.constants import (
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
)
from rpg_backend.domain.move_library import (
    GLOBAL_MOVE_TEMPLATE_IDS,
    MOVE_STRATEGY_STYLE_BY_ID,
    MOVE_TEMPLATE_BY_ID,
    STORY_MOVE_TEMPLATE_IDS,
    STRATEGY_STYLES,
    MoveTemplate,
    StrategyStyle,
)
from rpg_backend.domain.outcome_palette import OUTCOME_PALETTE_BY_ID, OutcomePalette
from rpg_backend.generator.defaults import default_npc_conflict_tags, default_npc_red_line
from rpg_backend.generator.planner import BeatPlan
from rpg_backend.generator.versioning import PalettePolicy

_BASE_PACK_PATH = Path("sample_data/story_pack_v1.json")
_GLOBAL_MOVES = [
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
]

_MOVE_CONTEXT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "stabilize_reactor": ("reactor", "core", "cooling", "containment"),
    "decode_core": ("core", "telemetry", "signal", "protocol"),
    "jam_sensors": ("sensor", "surveillance", "drone", "scan"),
    "flank_patrol": ("patrol", "checkpoint", "cordon", "guard"),
}

_STYLE_LABEL_HINTS: dict[StrategyStyle, str] = {
    "fast_dirty": "fast but dirty",
    "steady_slow": "steady but slow",
    "political_safe_resource_heavy": "politically safe, resource heavy",
}

_STYLE_COST_HINTS: dict[StrategyStyle, str] = {
    "fast_dirty": "Fast but dirty: coordination noise rises and trust may slip.",
    "steady_slow": "Steady but slow: noise drops, but time pressure increases.",
    "political_safe_resource_heavy": "Politically safe: trust improves, but resource stress climbs.",
}

def _slugify_seed(seed_text: str) -> str:
    lowered = "".join(ch.lower() if ch.isalnum() else "-" for ch in seed_text).strip("-")
    compact = "-".join(part for part in lowered.split("-") if part)
    return compact[:36] or "generated-story"


def _stable_suffix(seed_text: str) -> str:
    val = sum((idx + 1) * ord(ch) for idx, ch in enumerate(seed_text))
    return f"{val % 100000:05d}"


def _random_token(rng: random.Random) -> str:
    return f"{rng.randint(0, 99999):05d}"


def _load_base_pack() -> dict:
    return json.loads(_BASE_PACK_PATH.read_text(encoding="utf-8"))


def _scene_tag_hints(scene_seed: str) -> set[str]:
    lowered = scene_seed.lower()
    hints: set[str] = set()
    keyword_map = {
        "social": ("guard", "director", "crowd", "citizen", "evac", "mayor", "media", "council", "public"),
        "stealth": ("tunnel", "checkpoint", "patrol", "bypass", "quiet", "cordon"),
        "technical": (
            "core",
            "reactor",
            "console",
            "relay",
            "signal",
            "network",
            "comms",
            "infrastructure",
            "pump",
            "valve",
            "substation",
        ),
        "investigate": ("trace", "scan", "clue", "pattern", "anomaly", "audit", "forensic", "logs", "breach"),
        "support": ("evac", "aid", "stabilize", "civilians", "triage", "shelter", "rescue", "hospital"),
        "resource": ("supplies", "power", "cooling", "resource", "ration", "water", "fuel", "medical"),
        "conflict": ("riot", "clash", "standoff", "blame", "strike", "protest", "blackmarket"),
        "mobility": ("route", "transit", "metro", "corridor", "bridge", "port"),
    }
    for tag, keywords in keyword_map.items():
        if any(keyword in lowered for keyword in keywords):
            hints.add(tag)
    if not hints:
        hints.add("investigate")
        hints.add("support")
    return hints


def _compose_scene_seed(original_seed: str, beat_item) -> str:
    scene_intent = beat_item.scene_intent.strip()
    objective = beat_item.objective.strip()
    conflict = beat_item.conflict.strip()
    parts: list[str] = []
    if scene_intent:
        parts.append(scene_intent)
    if objective:
        parts.append(f"Objective: {objective}.")
    if conflict:
        parts.append(f"Conflict: {conflict}.")
    merged = " ".join(parts)
    if not merged:
        return original_seed
    return merged[:220]


def _sample(items: tuple[str, ...], rng: random.Random) -> str:
    return items[rng.randrange(0, len(items))]


def _strategy_style_for_move(move_id: str) -> StrategyStyle:
    return MOVE_STRATEGY_STYLE_BY_ID.get(move_id, "steady_slow")


def _augment_cost_delta_with_style(cost_delta: str, strategy_style: StrategyStyle) -> str:
    return f"{cost_delta} {_STYLE_COST_HINTS[strategy_style]}"


def _build_narration_slots(palette: OutcomePalette, rng: random.Random, strategy_style: StrategyStyle) -> dict[str, str]:
    return {
        "npc_reaction": _sample(palette.npc_reactions, rng),
        "world_shift": _sample(palette.world_shifts, rng),
        "clue_delta": _sample(palette.clue_deltas, rng),
        "cost_delta": _augment_cost_delta_with_style(_sample(palette.cost_deltas, rng), strategy_style),
        "next_hook": _sample(palette.next_hooks, rng),
    }


def _palette_for(
    result: str,
    template: MoveTemplate,
    rng: random.Random,
    palette_policy: PalettePolicy,
    palette_usage: dict[str, int],
) -> tuple[str, OutcomePalette]:
    candidate_ids = template.outcome_palette_ids[result]
    if palette_policy == "fixed":
        palette_id = candidate_ids[0]
    elif palette_policy == "balanced":
        min_usage = min(palette_usage.get(candidate_id, 0) for candidate_id in candidate_ids)
        least_used = [candidate_id for candidate_id in candidate_ids if palette_usage.get(candidate_id, 0) == min_usage]
        palette_id = least_used[rng.randrange(0, len(least_used))]
    else:
        palette_id = candidate_ids[rng.randrange(0, len(candidate_ids))]
    palette_usage[palette_id] = palette_usage.get(palette_id, 0) + 1
    return palette_id, OUTCOME_PALETTE_BY_ID[palette_id]


def _style_effect_profile(strategy_style: StrategyStyle, result: str) -> list[dict[str, Any]]:
    if strategy_style == "fast_dirty":
        noise_delta = 2 if result != "success" else 1
        return [
            {"type": "inc_state", "key": "coordination_noise", "value": noise_delta},
            {"type": "inc_state", "key": "public_trust", "value": -1},
        ]

    if strategy_style == "steady_slow":
        time_delta = 2 if result == "fail_forward" else 1
        return [
            {"type": "inc_state", "key": "coordination_noise", "value": -1},
            {"type": "inc_state", "key": "time_spent", "value": time_delta},
        ]

    stress_delta = 2 if result != "success" else 1
    return [
        {"type": "inc_state", "key": "public_trust", "value": 1},
        {"type": "inc_state", "key": "resource_stress", "value": stress_delta},
    ]


def _build_outcome(
    move_id: str,
    result: str,
    template: MoveTemplate,
    rng: random.Random,
    palette_policy: PalettePolicy,
    palette_usage: dict[str, int],
    strategy_style: StrategyStyle,
) -> dict[str, Any]:
    palette_id, palette = _palette_for(result, template, rng, palette_policy, palette_usage)
    effects = [dict(effect) for effect in palette.effect_profile]
    effects.extend(_style_effect_profile(strategy_style, result))
    if result == "fail_forward":
        if not any(effect.get("type") in {"advance_beat_progress", "add_event"} for effect in effects):
            effects.append({"type": "advance_beat_progress", "value": 1})
        if not any(effect.get("type") == "add_event" for effect in effects):
            effects.append({"type": "add_event", "key": f"{move_id}.fail_forward"})
        if not any(effect.get("type") == "cost" for effect in effects):
            effects.append({"type": "cost", "value": 1})

    return {
        "id": f"{move_id}.{result}.{palette_id}",
        "result": result,
        "preconditions": [],
        "effects": effects,
        "narration_slots": _build_narration_slots(palette, rng, strategy_style),
    }


def _materialize_move(
    template: MoveTemplate,
    npcs: list[str],
    rng: random.Random,
    palette_policy: PalettePolicy,
    palette_usage: dict[str, int],
) -> dict[str, Any]:
    strategy_style = _strategy_style_for_move(template.id)
    label = template.label_template
    if "{target_npc}" in label:
        label = label.format(target_npc=npcs[rng.randrange(0, len(npcs))])
    label = f"{label} [{_STYLE_LABEL_HINTS[strategy_style]}]"

    intents = list(dict.fromkeys((template.id, *template.intent_patterns)))
    synonyms = list(dict.fromkeys(template.synonym_bank))
    if npcs:
        first_npc = npcs[rng.randrange(0, len(npcs))]
        synonyms.append(first_npc.lower())

    return {
        "id": template.id,
        "label": label,
        "strategy_style": strategy_style,
        "intents": intents,
        "synonyms": list(dict.fromkeys(synonyms)),
        "args_schema": dict(template.args_schema),
        "resolution_policy": template.resolution_policy,
        "outcomes": [
            _build_outcome(template.id, "success", template, rng, palette_policy, palette_usage, strategy_style),
            _build_outcome(template.id, "partial", template, rng, palette_policy, palette_usage, strategy_style),
            _build_outcome(template.id, "fail_forward", template, rng, palette_policy, palette_usage, strategy_style),
        ],
    }


def _candidate_story_moves(scene_seed: str, preferred_tags: set[str] | None = None) -> list[str]:
    lowered_seed = scene_seed.lower()
    hints = _scene_tag_hints(scene_seed)
    preferred = preferred_tags or set()
    scored: list[tuple[int, str]] = []
    for move_id in STORY_MOVE_TEMPLATE_IDS:
        template = MOVE_TEMPLATE_BY_ID[move_id]
        tags = set(template.tags)
        score = 0
        if hints.intersection(tags):
            score += 2
        if preferred.intersection(tags):
            score += 3
        required_keywords = _MOVE_CONTEXT_REQUIREMENTS.get(move_id)
        if required_keywords and not any(keyword in lowered_seed for keyword in required_keywords):
            score -= 3
        scored.append((score, move_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [move_id for _, move_id in scored]


def _pick_story_moves(
    scene_seed: str,
    target_count: int,
    rng: random.Random,
    preferred_tags: set[str],
    previous_scene_moves: set[str] | None = None,
) -> list[str]:
    candidates = _candidate_story_moves(scene_seed, preferred_tags)
    previous = previous_scene_moves or set()

    selected: list[str] = []
    for style in STRATEGY_STYLES:
        for move_id in candidates:
            if _strategy_style_for_move(move_id) != style:
                continue
            if move_id in selected:
                continue
            selected.append(move_id)
            break

    fresh_candidates = [move_id for move_id in candidates if move_id not in previous and move_id not in selected]
    reused_candidates = [move_id for move_id in candidates if move_id in previous and move_id not in selected]
    ordered_candidates = fresh_candidates + reused_candidates

    for move_id in ordered_candidates:
        selected.append(move_id)
        if len(selected) >= target_count:
            break

    if len(selected) > 1:
        head = selected[:1]
        tail = selected[1:]
        rng.shuffle(tail)
        selected = head + tail
    return selected[:target_count]


def build_pack(
    plan: BeatPlan,
    style: str | None = None,
    rng: random.Random | None = None,
    palette_policy: PalettePolicy = "random",
) -> dict:
    working_rng = rng or random.Random()
    pack = deepcopy(_load_base_pack())
    slug = _slugify_seed(plan.seed_text)
    suffix = _stable_suffix(plan.seed_text)
    token = _random_token(working_rng)

    pack["story_id"] = f"generated-{slug}-{suffix}-{token}"
    pack["title"] = plan.story_title or f"Generated Story: {plan.seed_text[:48]}"
    if plan.premise:
        stakes_suffix = f" Stakes: {plan.stakes}" if plan.stakes else ""
        pack["description"] = f"{plan.premise}{stakes_suffix}".strip()
    else:
        pack["description"] = (
            f"Deterministic v3 pack generated from seed '{plan.seed_text[:80]}', "
            f"target_minutes={plan.target_minutes}, target_steps={plan.target_steps}, random_token={token}."
        )
    pack["npcs"] = list(plan.npc_names)
    pack["npc_profiles"] = [
        {
            "name": name,
            "red_line": plan.npc_red_lines.get(name) or default_npc_red_line(name, idx),
            "conflict_tags": list(plan.npc_conflict_tags.get(name) or default_npc_conflict_tags(idx)),
        }
        for idx, name in enumerate(plan.npc_names)
    ]
    if style:
        pack["style_guard"] = style
    elif plan.tone:
        pack["style_guard"] = f"Tone: {plan.tone}. Keep narration concise, concrete, and forward-moving."

    beat_by_id = {item.beat_id: item for item in plan.beats}
    for beat in pack["beats"]:
        plan_item = beat_by_id[beat["id"]]
        beat["title"] = plan_item.title
        beat["step_budget"] = plan_item.step_budget
        beat["required_events"] = list(plan_item.required_events)
        beat["npc_quota"] = plan_item.npc_quota
        beat["entry_scene_id"] = plan_item.entry_scene_id

    npcs = plan.npc_names
    npc_len = len(npcs)
    used_move_ids = set(GLOBAL_MOVE_TEMPLATE_IDS)
    palette_usage: dict[str, int] = {}
    preferred_tags = {tag.strip().lower() for tag in plan.move_bias if tag.strip()}
    previous_scene_moves: set[str] = set()
    for index, scene in enumerate(pack["scenes"]):
        plan_item = beat_by_id.get(scene["beat_id"])
        if plan_item is not None:
            scene["scene_seed"] = _compose_scene_seed(scene["scene_seed"], plan_item)
        first = npcs[index % npc_len]
        second = npcs[(index + 1) % npc_len]
        scene["present_npcs"] = [first] if npc_len == 1 else [first, second]
        scene["always_available_moves"] = list(_GLOBAL_MOVES)
        move_count = working_rng.randint(4, 5)
        selected_story_moves = _pick_story_moves(
            scene["scene_seed"],
            move_count,
            working_rng,
            preferred_tags,
            previous_scene_moves=previous_scene_moves,
        )
        scene["enabled_moves"] = selected_story_moves[:5]
        previous_scene_moves = set(scene["enabled_moves"])
        used_move_ids.update(scene["enabled_moves"])

    pack["moves"] = [
        _materialize_move(
            MOVE_TEMPLATE_BY_ID[move_id],
            npcs,
            working_rng,
            palette_policy,
            palette_usage,
        )
        for move_id in MOVE_TEMPLATE_BY_ID
        if move_id in used_move_ids
    ]

    return pack
