from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from rpg_backend.domain.conflict_tags import NPCConflictTag
from rpg_backend.generator.defaults import default_npc_conflict_tags, default_npc_red_line
from rpg_backend.generator.spec_schema import StorySpec


@dataclass
class BeatPlanItem:
    beat_id: str
    title: str
    step_budget: int
    required_events: list[str]
    npc_quota: int
    entry_scene_id: str
    objective: str = ""
    conflict: str = ""
    scene_intent: str = ""


@dataclass
class BeatPlan:
    seed_text: str
    target_minutes: int
    target_steps: int
    npc_names: list[str]
    beats: list[BeatPlanItem]
    story_title: str | None = None
    premise: str | None = None
    stakes: str | None = None
    tone: str | None = None
    move_bias: list[str] = field(default_factory=list)
    spec_summary: dict[str, Any] | None = None
    npc_red_lines: dict[str, str] = field(default_factory=dict)
    npc_conflict_tags: dict[str, list[NPCConflictTag]] = field(default_factory=dict)


_NAME_POOL = [
    "Mara",
    "Jex",
    "Ivo",
    "Director Vale",
    "Sera",
    "Kael",
    "Niko",
    "Tamsin",
    "Rook",
    "Lina",
]

def _stable_seed_value(seed_text: str) -> int:
    return sum(ord(ch) for ch in seed_text)


def _select_npc_names(seed_text: str, npc_count: int) -> list[str]:
    start = _stable_seed_value(seed_text) % len(_NAME_POOL)
    ordered = _NAME_POOL[start:] + _NAME_POOL[:start]
    return ordered[:npc_count]


def _target_steps_from_minutes(target_minutes: int) -> int:
    # Keep generation deterministic and constrained to architecture pacing.
    guessed = int(round(target_minutes * 1.5))
    return max(14, min(16, guessed))


def _distribute_step_budget(target_steps: int, beat_count: int = 4) -> list[int]:
    budgets = [3 for _ in range(beat_count)]
    remaining = target_steps - sum(budgets)
    idx = 0
    while remaining > 0:
        if budgets[idx] < 4:
            budgets[idx] += 1
            remaining -= 1
        idx = (idx + 1) % beat_count
    return budgets


def _slug(text: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return compact[:28] or "milestone"


def _normalized_npc_profiles_from_spec(
    spec: StorySpec,
    npc_count: int,
    fallback_seed: str,
) -> tuple[list[str], dict[str, str], dict[str, list[NPCConflictTag]]]:
    desired = max(3, min(5, npc_count))
    profiles: list[tuple[str, str, list[NPCConflictTag]]] = []
    seen: set[str] = set()

    for npc in spec.npcs:
        name = npc.name.strip()
        red_line = npc.red_line.strip()
        conflict_tags = list(dict.fromkeys(npc.conflict_tags))
        if not name or not red_line or not conflict_tags:
            continue
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        profiles.append((name, red_line, conflict_tags))

    if len(profiles) < desired:
        for candidate in _select_npc_names(fallback_seed or spec.title, desired * 2):
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            profiles.append(
                (
                    candidate,
                    default_npc_red_line(candidate, len(profiles)),
                    default_npc_conflict_tags(len(profiles)),
                )
            )
            if len(profiles) >= desired:
                break

    npc_names = [name for name, _, _ in profiles[:desired]]
    npc_red_lines = {name: red_line for name, red_line, _ in profiles[:desired]}
    npc_conflict_tags = {name: list(conflict_tags) for name, _, conflict_tags in profiles[:desired]}
    return npc_names, npc_red_lines, npc_conflict_tags


def plan_beats(seed_text: str, target_minutes: int, npc_count: int) -> BeatPlan:
    target_steps = _target_steps_from_minutes(target_minutes)
    beat_ids = ["b1", "b2", "b3", "b4"]
    beat_titles = [
        "Inciting Signal",
        "Crossfire Corridor",
        "Core Descent",
        "Dawn Resolution",
    ]
    entry_scene_ids = ["sc1", "sc5", "sc8", "sc12"]
    budgets = _distribute_step_budget(target_steps, beat_count=4)

    beats = [
        BeatPlanItem(
            beat_id=beat_id,
            title=beat_titles[i],
            step_budget=budgets[i],
            required_events=[f"{beat_id}.milestone"],
            npc_quota=2,
            entry_scene_id=entry_scene_ids[i],
            objective=f"Advance {beat_titles[i].lower()}",
            conflict="Escalating pressure from the city-wide signal breach.",
            scene_intent=f"Push toward {beat_titles[i].lower()} without stalling momentum.",
        )
        for i, beat_id in enumerate(beat_ids)
    ]

    npc_names = _select_npc_names(seed_text, npc_count)
    npc_red_lines = {name: default_npc_red_line(name, idx) for idx, name in enumerate(npc_names)}
    npc_conflict_tags = {name: default_npc_conflict_tags(idx) for idx, name in enumerate(npc_names)}

    return BeatPlan(
        seed_text=seed_text,
        target_minutes=target_minutes,
        target_steps=target_steps,
        npc_names=npc_names,
        beats=beats,
        npc_red_lines=npc_red_lines,
        npc_conflict_tags=npc_conflict_tags,
    )


def plan_beats_from_spec(
    *,
    spec: StorySpec,
    seed_text: str,
    target_minutes: int,
    npc_count: int,
) -> BeatPlan:
    target_steps = _target_steps_from_minutes(target_minutes)
    beat_ids = ["b1", "b2", "b3", "b4"]
    entry_scene_ids = ["sc1", "sc5", "sc8", "sc12"]
    budgets = _distribute_step_budget(target_steps, beat_count=4)

    selected_beats = list(spec.beats[:4])
    selected_scene_constraints = list(spec.scene_constraints[:4])
    if len(selected_beats) < 4 or len(selected_scene_constraints) < 4:
        raise ValueError("StorySpec must contain at least 4 beats and 4 scene_constraints")

    beats: list[BeatPlanItem] = []
    for idx, beat_id in enumerate(beat_ids):
        spec_beat = selected_beats[idx]
        scene_intent = selected_scene_constraints[idx]
        event = spec_beat.required_event or f"{beat_id}.{_slug(spec_beat.objective)}"
        beats.append(
            BeatPlanItem(
                beat_id=beat_id,
                title=spec_beat.title.strip()[:90],
                step_budget=budgets[idx],
                required_events=[event],
                npc_quota=2,
                entry_scene_id=entry_scene_ids[idx],
                objective=spec_beat.objective.strip(),
                conflict=spec_beat.conflict.strip(),
                scene_intent=scene_intent.strip(),
            )
        )

    npc_names, npc_red_lines, npc_conflict_tags = _normalized_npc_profiles_from_spec(spec, npc_count, seed_text or spec.title)
    return BeatPlan(
        seed_text=seed_text,
        target_minutes=target_minutes,
        target_steps=target_steps,
        npc_names=npc_names,
        beats=beats,
        story_title=spec.title.strip(),
        premise=spec.premise.strip(),
        stakes=spec.stakes.strip(),
        tone=spec.tone.strip(),
        move_bias=list(dict.fromkeys(spec.move_bias)),
        spec_summary=spec.compact_summary(),
        npc_red_lines=npc_red_lines,
        npc_conflict_tags=npc_conflict_tags,
    )
