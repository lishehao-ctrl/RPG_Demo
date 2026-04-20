from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rpg_backend.author_v3.storylet_compiler import Storylet
from rpg_backend.play_v2.contracts import CompiledPlayPlan, UrbanWorldState


_REQUIRED_SECRETS_WEIGHT = 0.35
_REQUIRED_RELATIONSHIPS_WEIGHT = 0.25
_MIN_TENSION_WEIGHT = 0.20
_REQUIRED_SEGMENT_ROLES_WEIGHT = 0.20


class StoryletMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storylet_id: str
    narrative_function: str
    scene_text: str
    venue_hint: str
    match_score: float
    matched_conditions: list[str]


def _normalized_tension(state: UrbanWorldState) -> float:
    components = (
        state.scene_heat / 6.0,
        state.secret_exposure / 6.0,
        state.witness_pressure / 3.0,
    )
    return max(0.0, min(1.0, sum(components) / len(components)))


def _current_segment_role(state: UrbanWorldState, plan: CompiledPlayPlan) -> str:
    for segment in plan.segments:
        if segment.segment_id == state.segment_id:
            return segment.segment_role
    return ""


def _relationship_ids(state: UrbanWorldState) -> set[str]:
    ids = set(state.relationships.keys())
    ids.update(target.character_id for target in state.relationships.values())
    return {character_id.lower() for character_id in ids if character_id}


def _relationship_condition_hit(required_relationships: list[str], state: UrbanWorldState) -> bool:
    if not required_relationships:
        return True

    relationship_ids = _relationship_ids(state)
    if not relationship_ids:
        return False

    for entry in required_relationships:
        entry_text = entry.lower()
        if not any(character_id in entry_text for character_id in relationship_ids):
            return False
    return True


def _score_storylet(
    storylet: Storylet,
    state: UrbanWorldState,
    plan: CompiledPlayPlan,
) -> tuple[float, list[str]]:
    preconditions = storylet.preconditions
    if (
        not preconditions.required_secrets_known
        and not preconditions.required_relationships
        and preconditions.min_tension_score == 0.0
        and not preconditions.required_segment_roles
    ):
        return 0.3, []

    score = 0.0
    matched_conditions: list[str] = []

    if set(preconditions.required_secrets_known).issubset(set(state.known_secret_ids)):
        score += _REQUIRED_SECRETS_WEIGHT
        matched_conditions.append("required_secrets_known")

    if _relationship_condition_hit(preconditions.required_relationships, state):
        score += _REQUIRED_RELATIONSHIPS_WEIGHT
        matched_conditions.append("required_relationships")

    if _normalized_tension(state) >= preconditions.min_tension_score:
        score += _MIN_TENSION_WEIGHT
        matched_conditions.append("min_tension_score")

    current_segment_role = _current_segment_role(state, plan)
    if (
        not preconditions.required_segment_roles
        or current_segment_role in preconditions.required_segment_roles
    ):
        score += _REQUIRED_SEGMENT_ROLES_WEIGHT
        matched_conditions.append("required_segment_roles")

    return min(score, 1.0), matched_conditions


def find_matching_storylets(
    state: UrbanWorldState,
    plan: CompiledPlayPlan,
    *,
    max_count: int = 3,
    min_score: float = 0.4,
) -> list[StoryletMatch]:
    if max_count <= 0 or not plan.storylet_pool:
        return []

    matches: list[StoryletMatch] = []
    for raw_storylet in plan.storylet_pool:
        storylet = Storylet.model_validate(raw_storylet)
        match_score, matched_conditions = _score_storylet(storylet, state, plan)
        if match_score < min_score:
            continue
        matches.append(
            StoryletMatch(
                storylet_id=storylet.storylet_id,
                narrative_function=storylet.narrative_function,
                scene_text=storylet.scene_text,
                venue_hint=getattr(storylet, "venue_hint", ""),
                match_score=match_score,
                matched_conditions=matched_conditions,
            )
        )

    matches.sort(key=lambda match: (-match.match_score, match.storylet_id))
    return matches[:max_count]
