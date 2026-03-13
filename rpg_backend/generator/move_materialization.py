from __future__ import annotations

import random
from typing import Any

from rpg_backend.domain.move_library import MOVE_STRATEGY_STYLE_BY_ID, MoveTemplate, StrategyStyle
from rpg_backend.domain.outcome_palette import OUTCOME_PALETTE_BY_ID, OutcomePalette
from rpg_backend.generator.outcome_materialization import build_outcome_from_palette_id
from rpg_backend.generator.versioning import PalettePolicy

_STYLE_LABEL_HINTS: dict[StrategyStyle, str] = {
    "fast_dirty": "fast but dirty",
    "steady_slow": "steady but slow",
    "political_safe_resource_heavy": "politically safe, resource heavy",
}


def strategy_style_for_move(move_id: str) -> StrategyStyle:
    return MOVE_STRATEGY_STYLE_BY_ID.get(move_id, "steady_slow")


def choose_outcome_palette(
    *,
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


def build_template_outcome(
    *,
    move_id: str,
    result: str,
    template: MoveTemplate,
    rng: random.Random,
    palette_policy: PalettePolicy,
    palette_usage: dict[str, int],
    strategy_style: StrategyStyle,
) -> dict[str, Any]:
    palette_id, _palette = choose_outcome_palette(
        result=result,
        template=template,
        rng=rng,
        palette_policy=palette_policy,
        palette_usage=palette_usage,
    )
    return build_outcome_from_palette_id(
        move_id=move_id,
        outcome_index=0,
        result=result,
        palette_id=palette_id,
        strategy_style=strategy_style,
        next_scene_id=None,
        rng=rng,
        outcome_id=f"{move_id}.{result}.{palette_id}",
    )


def materialize_move_from_template(
    *,
    template: MoveTemplate,
    npcs: list[str],
    rng: random.Random,
    palette_policy: PalettePolicy,
    palette_usage: dict[str, int],
) -> dict[str, Any]:
    strategy_style = strategy_style_for_move(template.id)
    label = template.label_template
    if "{target_npc}" in label and npcs:
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
            build_template_outcome(
                move_id=template.id,
                result="success",
                template=template,
                rng=rng,
                palette_policy=palette_policy,
                palette_usage=palette_usage,
                strategy_style=strategy_style,
            ),
            build_template_outcome(
                move_id=template.id,
                result="partial",
                template=template,
                rng=rng,
                palette_policy=palette_policy,
                palette_usage=palette_usage,
                strategy_style=strategy_style,
            ),
            build_template_outcome(
                move_id=template.id,
                result="fail_forward",
                template=template,
                rng=rng,
                palette_policy=palette_policy,
                palette_usage=palette_usage,
                strategy_style=strategy_style,
            ),
        ],
    }


def materialize_local_move_from_template(
    *,
    template: MoveTemplate,
    local_move_id: str,
    npcs: list[str],
    rng: random.Random,
    palette_policy: PalettePolicy,
    palette_usage: dict[str, int],
    surface_label: str | None = None,
    surface_intents: list[str] | None = None,
    surface_synonyms: list[str] | None = None,
    surface_roleplay_examples: list[str] | None = None,
) -> dict[str, Any]:
    strategy_style = strategy_style_for_move(template.id)
    default_label = template.label_template
    if "{target_npc}" in default_label and npcs:
        default_label = default_label.format(target_npc=npcs[rng.randrange(0, len(npcs))])
    default_label = f"{default_label} [{_STYLE_LABEL_HINTS[strategy_style]}]"
    label = " ".join((surface_label or default_label).strip().split())

    intents = list(dict.fromkeys((template.id, *(surface_intents or template.intent_patterns), *(surface_roleplay_examples or []))))
    synonyms = list(dict.fromkeys((surface_synonyms or template.synonym_bank)))
    synonyms.extend(surface_roleplay_examples or [])
    label_tokens = [item.lower() for item in label.replace("/", " ").split() if item.isalpha()]
    synonyms.extend(label_tokens[:2])
    if npcs:
        first_npc = npcs[rng.randrange(0, len(npcs))]
        synonyms.append(first_npc.lower())

    outcomes: list[dict[str, Any]] = []
    for outcome_index, result in enumerate(("success", "partial", "fail_forward")):
        outcomes.append(
            build_template_outcome(
                move_id=local_move_id,
                result=result,
                template=template,
                rng=rng,
                palette_policy=palette_policy,
                palette_usage=palette_usage,
                strategy_style=strategy_style,
            )
        )
        outcomes[-1]["id"] = f"{local_move_id}.o{outcome_index + 1}.{result}"

    return {
        "id": local_move_id,
        "label": label,
        "strategy_style": strategy_style,
        "intents": intents,
        "synonyms": list(dict.fromkeys(synonyms)),
        "args_schema": dict(template.args_schema),
        "resolution_policy": template.resolution_policy,
        "outcomes": outcomes,
    }
