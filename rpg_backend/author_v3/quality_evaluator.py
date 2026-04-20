from __future__ import annotations

from statistics import pstdev
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.storylet_compiler import StoryletPool
from rpg_backend.author_v3.tension_weaver import TensionWeb


QualityDimension = Literal[
    "character_motivation_credibility",
    "secret_lethality",
    "reversal_surprise",
    "relationship_chemistry",
    "venue_permeation",
    "continuity",
]

QualityTrend = Literal["converging", "stagnating", "diverging"]


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: QualityDimension
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=400)


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[DimensionScore] = Field(min_length=6, max_length=6)
    overall_score: float = Field(ge=0.0, le=1.0)
    trend: QualityTrend
    weakest_dimension: QualityDimension
    improvement_suggestion: str = Field(min_length=1, max_length=300)
    passed: bool


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _score_character_motivation_credibility(config: WorldConfiguration) -> DimensionScore:
    total = len(config.characters)
    if total == 0:
        return DimensionScore(
            dimension="character_motivation_credibility",
            score=0.0,
            rationale="No characters available for motivation credibility scoring.",
        )

    differentiated = sum(
        1
        for character in config.characters
        if character.hidden_need.strip() != character.public_identity.strip()
    )
    score = _clamp01(differentiated / total)
    return DimensionScore(
        dimension="character_motivation_credibility",
        score=round(score, 4),
        rationale=(
            f"{differentiated}/{total} characters have hidden_need distinct from public_identity."
        ),
    )


def _score_secret_lethality(web: TensionWeb) -> DimensionScore:
    if not web.secrets:
        return DimensionScore(
            dimension="secret_lethality",
            score=0.0,
            rationale="No secrets available; lethality defaults to 0.",
        )

    lethality_values = [secret.lethality_score for secret in web.secrets]
    avg = sum(lethality_values) / len(lethality_values)
    deviation = pstdev(lethality_values) if len(lethality_values) > 1 else 0.0
    score = avg + (0.05 if deviation > 0.1 else 0.0)
    score = _clamp01(score)
    return DimensionScore(
        dimension="secret_lethality",
        score=round(score, 4),
        rationale=(
            f"Average lethality is {avg:.3f}; std dev is {deviation:.3f}. "
            f"Bonus applied: {'yes' if deviation > 0.1 else 'no'}."
        ),
    )


def _score_reversal_surprise(pool: StoryletPool) -> DimensionScore:
    total = len(pool.storylets)
    if total == 0:
        return DimensionScore(
            dimension="reversal_surprise",
            score=0.0,
            rationale="No storylets available for reversal surprise scoring.",
        )

    use_narrative_function = all(hasattr(storylet, "narrative_function") for storylet in pool.storylets)
    if use_narrative_function:
        hits = sum(1 for storylet in pool.storylets if storylet.narrative_function == "reversal")
        rule_used = "narrative_function == reversal"
    else:
        hits = sum(1 for storylet in pool.storylets if storylet.dramatic_weight > 0.7)
        rule_used = "dramatic_weight > 0.7"

    score = _clamp01(hits / total)
    return DimensionScore(
        dimension="reversal_surprise",
        score=round(score, 4),
        rationale=f"{hits}/{total} storylets matched rule: {rule_used}.",
    )


def _score_relationship_chemistry(config: WorldConfiguration) -> DimensionScore:
    total = len(config.relationship_edges)
    if total == 0:
        return DimensionScore(
            dimension="relationship_chemistry",
            score=0.0,
            rationale="No relationship edges available for chemistry scoring.",
        )

    qualifying = 0
    for edge in config.relationship_edges:
        avg_trust = (edge.stance_a_to_b.trust_level + edge.stance_b_to_a.trust_level) / 2.0
        if edge.tension_score > 0.4 and avg_trust < 0.5:
            qualifying += 1

    score = _clamp01(qualifying / total)
    return DimensionScore(
        dimension="relationship_chemistry",
        score=round(score, 4),
        rationale=(
            f"{qualifying}/{total} edges pass tension_score > 0.4 and average trust_level < 0.5."
        ),
    )


def _score_venue_permeation(pool: StoryletPool) -> DimensionScore:
    total = len(pool.storylets)
    if total == 0:
        return DimensionScore(
            dimension="venue_permeation",
            score=0.0,
            rationale="No storylets available for venue permeation scoring.",
        )

    unique_venues = {storylet.venue_hint for storylet in pool.storylets if storylet.venue_hint.strip()}
    score = _clamp01(len(unique_venues) / max(total, 1))
    return DimensionScore(
        dimension="venue_permeation",
        score=round(score, 4),
        rationale=f"{len(unique_venues)} unique venues across {total} storylets.",
    )


def _score_continuity(web: TensionWeb, pool: StoryletPool) -> DimensionScore:
    valid_secret_ids = {secret.secret_id for secret in web.secrets}
    referenced_secret_ids: list[str] = []
    for storylet in pool.storylets:
        referenced_secret_ids.extend(storylet.effects.secrets_revealed)
        if storylet.effects.triggers_chain:
            referenced_secret_ids.append(storylet.effects.triggers_chain)

    total_refs = len(referenced_secret_ids)
    if total_refs == 0:
        return DimensionScore(
            dimension="continuity",
            score=1.0,
            rationale="No secret references in storylet effects; continuity treated as fully consistent.",
        )

    valid_refs = sum(1 for secret_id in referenced_secret_ids if secret_id in valid_secret_ids)
    score = _clamp01(valid_refs / total_refs)
    return DimensionScore(
        dimension="continuity",
        score=round(score, 4),
        rationale=f"{valid_refs}/{total_refs} secret references resolve to existing secrets.",
    )


def _trend_from_score(overall_score: float) -> QualityTrend:
    if overall_score >= 0.7:
        return "converging"
    if overall_score >= 0.5:
        return "stagnating"
    return "diverging"


def _improvement_suggestion_for(dimension: QualityDimension) -> str:
    suggestions: dict[QualityDimension, str] = {
        "character_motivation_credibility": (
            "character_motivation_credibility: rewrite character public_identity lines so each clearly masks a conflicting hidden_need."
        ),
        "secret_lethality": (
            "secret_lethality: raise consequence severity on low-impact secrets and add one high-stakes exposure chain."
        ),
        "reversal_surprise": (
            "reversal_surprise: add more reversal storylets at midpoint and late beats to increase expectation breaks."
        ),
        "relationship_chemistry": (
            "relationship_chemistry: increase high-tension/low-trust pairings by sharpening distrust in key relationship edges."
        ),
        "venue_permeation": (
            "venue_permeation: diversify venue_hint usage so pivotal storylets occur across more distinct locations."
        ),
        "continuity": (
            "continuity: audit storylet effects and replace dangling secret references with valid secret_ids from the current web."
        ),
    }
    return suggestions[dimension]


def evaluate_quality_deterministic(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
    matrix: RelationshipMatrix | None = None,
    *,
    pass_threshold: float = 0.6,
) -> QualityReport:
    dimensions = [
        _score_character_motivation_credibility(config),
        _score_secret_lethality(web),
        _score_reversal_surprise(pool),
        _score_relationship_chemistry(config),
        _score_venue_permeation(pool),
        _score_continuity(web, pool),
    ]

    overall_score = _clamp01(sum(dimension.score for dimension in dimensions) / len(dimensions))
    overall_score = round(overall_score, 4)

    weakest = min(dimensions, key=lambda dimension: dimension.score).dimension

    return QualityReport(
        dimensions=dimensions,
        overall_score=overall_score,
        trend=_trend_from_score(overall_score),
        weakest_dimension=weakest,
        improvement_suggestion=_improvement_suggestion_for(weakest),
        passed=overall_score >= pass_threshold,
    )


def evaluate_quality(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
    matrix: RelationshipMatrix | None = None,
    *,
    gateway: Any = None,
    pass_threshold: float = 0.6,
) -> QualityReport:
    if gateway is not None:
        # TODO: Add LLM-assisted evaluation logic when gateway prompts/schemas are defined.
        return evaluate_quality_deterministic(config, web, pool, matrix, pass_threshold=pass_threshold)
    return evaluate_quality_deterministic(config, web, pool, matrix, pass_threshold=pass_threshold)
