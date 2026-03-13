from __future__ import annotations

import hashlib
import random
from typing import Any

from rpg_backend.domain.constants import GLOBAL_CLARIFY_MOVE_ID, GLOBAL_HELP_ME_PROGRESS_MOVE_ID, GLOBAL_LOOK_MOVE_ID
from rpg_backend.domain.move_library import MOVE_STRATEGY_STYLE_BY_ID, MOVE_TEMPLATE_BY_ID, STORY_MOVE_TEMPLATE_IDS, STRATEGY_STYLES, StrategyStyle
from rpg_backend.generator.author_workflow_models import BeatBlueprint, BeatDraft, BeatOutlineLLM, BeatOverviewContext
from rpg_backend.generator.move_materialization import materialize_local_move_from_template


_FIXED_GLOBAL_MOVES = [
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
]


def _scene_id_for(beat_id: str, entry_scene_id: str, index: int) -> str:
    if index == 0:
        return entry_scene_id
    return f"{beat_id}.sc{index + 1}"


def _move_id_for(beat_id: str, index: int) -> str:
    return f"{beat_id}.m{index + 1}"


def _progression_exit_condition(*, beat_id: str, scene_id: str, threshold: int, next_scene_id: str) -> dict[str, Any]:
    return {
        "id": f"{scene_id}.progress",
        "condition_kind": "beat_progress_gte",
        "key": beat_id,
        "value": threshold,
        "next_scene_id": next_scene_id,
        "end_story": False,
    }


def _selection_index(*, seed: str, size: int) -> int:
    if size <= 1:
        return 0
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % size


def _template_score(
    *,
    template_id: str,
    bias_weights: dict[str, int],
    context_text: str,
) -> int:
    template = MOVE_TEMPLATE_BY_ID[template_id]
    score = 0
    for tag in template.tags:
        score += bias_weights.get(tag, 0) * 4
        if tag in context_text:
            score += 1
    return score


def _select_template_id_for_style(
    *,
    style: StrategyStyle,
    blueprint: BeatBlueprint,
    outline: BeatOutlineLLM,
    overview_context: BeatOverviewContext | None,
) -> str:
    candidates = [
        template_id
        for template_id in STORY_MOVE_TEMPLATE_IDS
        if MOVE_STRATEGY_STYLE_BY_ID.get(template_id) == style
    ]
    if not candidates:
        raise ValueError(f"no move templates available for strategy style '{style}'")

    move_bias = list(overview_context.move_bias) if overview_context is not None else []
    bias_weights = {tag: max(1, len(move_bias) - index) for index, tag in enumerate(move_bias)}
    context_parts = [
        blueprint.title,
        blueprint.objective,
        blueprint.conflict,
        blueprint.scene_intent,
        *outline.present_npcs,
        *(scene.scene_seed for scene in outline.scene_plans),
    ]
    context_text = " ".join(part.strip().casefold() for part in context_parts if isinstance(part, str) and part.strip())
    scored_candidates = [
        (template_id, _template_score(template_id=template_id, bias_weights=bias_weights, context_text=context_text))
        for template_id in candidates
    ]
    best_score = max(score for _, score in scored_candidates)
    top_candidates = sorted(template_id for template_id, score in scored_candidates if score == best_score)
    selection_seed = "|".join(
        [
            blueprint.beat_id,
            style,
            str(len(outline.scene_plans)),
            *outline.present_npcs,
        ]
    )
    return top_candidates[_selection_index(seed=selection_seed, size=len(top_candidates))]


def select_story_move_template_ids(
    *,
    blueprint: BeatBlueprint,
    outline: BeatOutlineLLM,
    overview_context: BeatOverviewContext | None = None,
) -> list[str]:
    return [
        _select_template_id_for_style(
            style=style,
            blueprint=blueprint,
            outline=outline,
            overview_context=overview_context,
        )
        for style in STRATEGY_STYLES
    ]


def select_move_surface_overrides(outline: BeatOutlineLLM) -> list[dict[str, Any]]:
    surfaces = list(outline.move_surfaces)
    if len(surfaces) != len(STRATEGY_STYLES):
        raise ValueError("move_surfaces must contain exactly three style slots")
    return [
        {
            "label": surface.label,
            "intents": list(surface.intents),
            "synonyms": list(surface.synonyms),
            "roleplay_examples": list(surface.roleplay_examples),
        }
        for surface in surfaces
    ]


def materialize_beat_outline(
    *,
    overview_context: BeatOverviewContext | None = None,
    blueprint: BeatBlueprint,
    outline: BeatOutlineLLM,
) -> BeatDraft:
    scene_count = len(outline.scene_plans)
    template_ids = select_story_move_template_ids(
        blueprint=blueprint,
        outline=outline,
        overview_context=overview_context,
    )
    surface_overrides = select_move_surface_overrides(outline)
    move_count = len(template_ids)
    scene_ids = [_scene_id_for(blueprint.beat_id, blueprint.entry_scene_id, index) for index in range(scene_count)]
    move_ids = [_move_id_for(blueprint.beat_id, index) for index in range(move_count)]

    palette_usage: dict[str, int] = {}
    rng = random.Random(f"{blueprint.beat_id}|{'|'.join(outline.present_npcs)}")

    normalized_moves: list[dict[str, Any]] = []
    for move_index, template_id in enumerate(template_ids):
        template = MOVE_TEMPLATE_BY_ID[template_id]
        surface_override = surface_overrides[move_index]
        normalized_moves.append(
            materialize_local_move_from_template(
                template=template,
                local_move_id=move_ids[move_index],
                npcs=list(outline.present_npcs),
                rng=rng,
                palette_policy="balanced",
                palette_usage=palette_usage,
                surface_label=str(surface_override.get("label") or ""),
                surface_intents=list(surface_override.get("intents") or []),
                surface_synonyms=list(surface_override.get("synonyms") or []),
                surface_roleplay_examples=list(surface_override.get("roleplay_examples") or []),
            )
        )

    normalized_scenes: list[dict[str, Any]] = []
    for index, scene in enumerate(outline.scene_plans):
        exit_conditions: list[dict[str, Any]] = []
        if index < scene_count - 1:
            exit_conditions.append(
                _progression_exit_condition(
                    beat_id=blueprint.beat_id,
                    scene_id=scene_ids[index],
                    threshold=index + 1,
                    next_scene_id=scene_ids[index + 1],
                )
            )
        normalized_scenes.append(
            {
                "id": scene_ids[index],
                "beat_id": blueprint.beat_id,
                "scene_seed": scene.scene_seed.strip(),
                "present_npcs": list(scene.present_npcs),
                "enabled_moves": [move_ids[0], move_ids[1], move_ids[2]],
                "always_available_moves": list(_FIXED_GLOBAL_MOVES),
                "exit_conditions": exit_conditions,
                "is_terminal": bool(scene.is_terminal and index == scene_count - 1),
            }
        )

    normalized_events = list(dict.fromkeys([*(outline.events_produced or []), blueprint.required_event]))
    normalized_present_npcs = list(
        dict.fromkeys([*(outline.present_npcs or []), *[npc for scene in outline.scene_plans for npc in scene.present_npcs]])
    )

    return BeatDraft.model_validate(
        {
            "beat_id": blueprint.beat_id,
            "title": blueprint.title,
            "objective": blueprint.objective,
            "conflict": blueprint.conflict,
            "required_event": blueprint.required_event,
            "entry_scene_id": blueprint.entry_scene_id,
            "scenes": normalized_scenes,
            "moves": normalized_moves,
            "present_npcs": normalized_present_npcs,
            "events_produced": normalized_events,
        }
    )
