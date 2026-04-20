from __future__ import annotations

from math import sqrt
from typing import Iterable

from rpg_backend.author_v2.contracts import SlotFunctionId
from rpg_backend.author_v3.contracts import RelationshipEdge, RelationshipMatrix, RelationshipStance, WorldConfiguration


def build_relationship_matrix(config: WorldConfiguration) -> RelationshipMatrix:
    edges = list(config.relationship_edges)
    tension_density = _compute_tension_density(edges)
    power_imbalance_score = _compute_power_imbalance_score(edges)
    connectivity_score = _compute_connectivity_score(len(config.characters), len(edges))
    hook_pairs = [(edge.character_a_id, edge.character_b_id) for edge in edges if edge.hooks]
    slot_assignments = _build_slot_assignments(config, edges)
    return RelationshipMatrix(
        edges=edges,
        tension_density=tension_density,
        power_imbalance_score=power_imbalance_score,
        connectivity_score=connectivity_score,
        hook_pairs=hook_pairs,
        slot_assignments=slot_assignments,
    )


def _compute_tension_density(edges: list[RelationshipEdge]) -> float:
    if not edges:
        return 0.0
    return sum(edge.tension_score for edge in edges) / float(len(edges))


def _compute_power_imbalance_score(edges: list[RelationshipEdge]) -> float:
    values: list[float] = []
    for edge in edges:
        values.append(edge.stance_a_to_b.power_asymmetry)
        values.append(edge.stance_b_to_a.power_asymmetry)
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / float(len(values))
    variance = sum((value - mean_value) ** 2 for value in values) / float(len(values))
    return sqrt(variance)


def _compute_connectivity_score(character_count: int, edge_count: int) -> float:
    if character_count < 2:
        return 0.0
    max_possible = character_count * (character_count - 1) / 2
    if max_possible <= 0:
        return 0.0
    return edge_count / float(max_possible)


def _build_slot_assignments(
    config: WorldConfiguration,
    edges: list[RelationshipEdge],
) -> dict[str, SlotFunctionId]:
    ordered_character_ids = [character.character_id for character in config.characters]
    remaining = set(ordered_character_ids)
    assignments: dict[str, SlotFunctionId] = {}

    protagonist_id = config.protagonist_id
    if protagonist_id in remaining:
        assignments[protagonist_id] = "lead_interest"
        remaining.remove(protagonist_id)

    protagonist_links = _links_for_character(protagonist_id, edges)

    rival_id = _select_rival_interest(protagonist_links, remaining)
    if rival_id is not None:
        assignments[rival_id] = "rival_interest"
        remaining.remove(rival_id)

    hidden_ally_id = _select_hidden_ally(protagonist_id, protagonist_links, remaining)
    if hidden_ally_id is not None:
        assignments[hidden_ally_id] = "hidden_ally"
        remaining.remove(hidden_ally_id)

    secret_keeper_id = _select_secret_keeper(remaining, edges)
    if secret_keeper_id is not None:
        assignments[secret_keeper_id] = "secret_keeper"
        remaining.remove(secret_keeper_id)

    remaining_in_order = [character_id for character_id in ordered_character_ids if character_id in remaining]

    if remaining_in_order:
        first_id = remaining_in_order[0]
        assignments[first_id] = "public_witness"

    if len(remaining_in_order) >= 2:
        second_id = remaining_in_order[1]
        assignments[second_id] = "supporting_pressure"

    if len(remaining_in_order) >= 3:
        for character_id in remaining_in_order[2:]:
            assignments[character_id] = "wildcard"

    for character_id in ordered_character_ids:
        assignments.setdefault(character_id, "wildcard")

    return assignments


def _links_for_character(character_id: str, edges: Iterable[RelationshipEdge]) -> list[tuple[str, RelationshipEdge]]:
    links: list[tuple[str, RelationshipEdge]] = []
    for edge in edges:
        if edge.character_a_id == character_id:
            links.append((edge.character_b_id, edge))
        elif edge.character_b_id == character_id:
            links.append((edge.character_a_id, edge))
    return links


def _select_rival_interest(
    protagonist_links: list[tuple[str, RelationshipEdge]],
    remaining: set[str],
) -> str | None:
    candidates = [(other_id, edge.tension_score) for other_id, edge in protagonist_links if other_id in remaining]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[1], item[0]))
    return candidates[0][0]


def _select_hidden_ally(
    protagonist_id: str,
    protagonist_links: list[tuple[str, RelationshipEdge]],
    remaining: set[str],
) -> str | None:
    trust_candidates: list[tuple[str, float, float]] = []
    for other_id, edge in protagonist_links:
        if other_id not in remaining:
            continue
        stance = _stance_toward_protagonist(edge, protagonist_id, other_id)
        trust_value = _extract_trust_value(stance)
        if trust_value is None:
            continue
        trust_candidates.append((other_id, trust_value, edge.tension_score))

    if trust_candidates:
        trust_candidates.sort(key=lambda item: (-item[1], item[2], item[0]))
        return trust_candidates[0][0]

    fallback_candidates = [(other_id, edge.tension_score) for other_id, edge in protagonist_links if other_id in remaining]
    if not fallback_candidates:
        return None
    fallback_candidates.sort(key=lambda item: (item[1], item[0]))
    return fallback_candidates[0][0]


def _stance_toward_protagonist(
    edge: RelationshipEdge,
    protagonist_id: str,
    other_id: str,
) -> RelationshipStance | None:
    if edge.character_a_id == other_id and edge.character_b_id == protagonist_id:
        return edge.stance_a_to_b
    if edge.character_b_id == other_id and edge.character_a_id == protagonist_id:
        return edge.stance_b_to_a
    return None


def _extract_trust_value(stance: RelationshipStance | None) -> float | None:
    if stance is None:
        return None
    if hasattr(stance, "trust"):
        value = getattr(stance, "trust")
        if isinstance(value, (int, float)):
            return float(value)
    if hasattr(stance, "trust_level"):
        value = getattr(stance, "trust_level")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _select_secret_keeper(remaining: set[str], edges: Iterable[RelationshipEdge]) -> str | None:
    if not remaining:
        return None
    hook_counts = {character_id: 0 for character_id in remaining}
    for edge in edges:
        for character_id in remaining:
            if character_id in edge.hooks:
                hook_counts[character_id] += 1
    max_count = max(hook_counts.values())
    candidates = [character_id for character_id, count in hook_counts.items() if count == max_count]
    candidates.sort()
    return candidates[0]
