from __future__ import annotations

import pytest

from rpg_backend.author_v3.contracts import RelationshipEdge, RelationshipStance, WorldConfiguration
from rpg_backend.author_v3.quality_evaluator import DimensionScore, QualityReport, evaluate_quality
from rpg_backend.author_v3.relationship_matrix import build_relationship_matrix
from rpg_backend.author_v3.storylet_compiler import StoryletPool, compile_storylet_pool
from rpg_backend.author_v3.tension_weaver import OrganicSecret, TensionWeb, weave_secrets
from rpg_backend.author_v3.world_forge import forge_world


def _score_for(report: QualityReport, dimension: str) -> float:
    return next(item.score for item in report.dimensions if item.dimension == dimension)


def _high_quality_inputs(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> tuple[WorldConfiguration, TensionWeb, StoryletPool]:
    boosted_characters = [
        character.model_copy(update={"hidden_need": f"{character.public_identity} (hidden conflict)"})
        for character in config.characters
    ]

    boosted_edges: list[RelationshipEdge] = []
    for edge in config.relationship_edges:
        stance_a = edge.stance_a_to_b.model_copy(update={"trust_level": 0.2})
        stance_b = edge.stance_b_to_a.model_copy(update={"trust_level": 0.2})
        boosted_edges.append(
            edge.model_copy(
                update={
                    "tension_score": 0.95,
                    "stance_a_to_b": stance_a,
                    "stance_b_to_a": stance_b,
                }
            )
        )

    boosted_config = config.model_copy(
        update={"characters": boosted_characters, "relationship_edges": boosted_edges}
    )

    boosted_secrets: list[OrganicSecret] = [
        secret.model_copy(update={"lethality_score": 0.9}) for secret in web.secrets
    ]
    boosted_web = web.model_copy(update={"secrets": boosted_secrets})

    valid_secret_ids = [secret.secret_id for secret in boosted_web.secrets]
    boosted_storylets = []
    for idx, storylet in enumerate(pool.storylets):
        effects = storylet.effects.model_copy(
            update={
                "secrets_revealed": [valid_secret_ids[idx % len(valid_secret_ids)]],
                "triggers_chain": valid_secret_ids[(idx + 1) % len(valid_secret_ids)],
            }
        )
        boosted_storylets.append(
            storylet.model_copy(
                update={
                    "narrative_function": "reversal",
                    "dramatic_weight": 0.95,
                    "venue_hint": f"venue_{idx}",
                    "effects": effects,
                }
            )
        )

    boosted_pool = pool.model_copy(update={"storylets": boosted_storylets})
    return boosted_config, boosted_web, boosted_pool


def _low_quality_inputs(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> tuple[WorldConfiguration, TensionWeb, StoryletPool]:
    flattened_characters = [
        character.model_copy(update={"hidden_need": character.public_identity})
        for character in config.characters
    ]

    flattened_edges: list[RelationshipEdge] = []
    for edge in config.relationship_edges:
        stance_a = edge.stance_a_to_b.model_copy(update={"trust_level": 0.95})
        stance_b = edge.stance_b_to_a.model_copy(update={"trust_level": 0.95})
        flattened_edges.append(
            edge.model_copy(
                update={
                    "tension_score": 0.1,
                    "stance_a_to_b": stance_a,
                    "stance_b_to_a": stance_b,
                }
            )
        )

    low_config = config.model_copy(
        update={"characters": flattened_characters, "relationship_edges": flattened_edges}
    )

    low_secrets = [secret.model_copy(update={"lethality_score": 0.1}) for secret in web.secrets]
    low_web = web.model_copy(update={"secrets": low_secrets})

    degraded_storylets = []
    for storylet in pool.storylets:
        effects = storylet.effects.model_copy(
            update={
                "secrets_revealed": ["missing_secret_ref"],
                "triggers_chain": "missing_secret_ref",
            }
        )
        degraded_storylets.append(
            storylet.model_copy(
                update={
                    "narrative_function": "hook",
                    "dramatic_weight": 0.1,
                    "venue_hint": "single_venue",
                    "effects": effects,
                }
            )
        )

    low_pool = pool.model_copy(update={"storylets": degraded_storylets})
    return low_config, low_web, low_pool


@pytest.fixture
def config() -> WorldConfiguration:
    return forge_world("董事会权力斗争")


@pytest.fixture
def matrix(config: WorldConfiguration):
    return build_relationship_matrix(config)


@pytest.fixture
def web(config: WorldConfiguration, matrix) -> TensionWeb:
    return weave_secrets(config, matrix)


@pytest.fixture
def pool(config: WorldConfiguration, web: TensionWeb, matrix) -> StoryletPool:
    return compile_storylet_pool(config, web, matrix)


@pytest.fixture
def report(config: WorldConfiguration, web: TensionWeb, pool: StoryletPool) -> QualityReport:
    return evaluate_quality(config, web, pool, gateway=None)


def test_quality_report_and_dimension_count(report: QualityReport) -> None:
    assert isinstance(report, QualityReport)
    assert len(report.dimensions) == 6
    assert all(isinstance(item, DimensionScore) for item in report.dimensions)


def test_overall_score_between_zero_and_one(report: QualityReport) -> None:
    assert 0.0 <= report.overall_score <= 1.0


def test_passed_flag_matches_default_threshold(report: QualityReport) -> None:
    assert report.passed == (report.overall_score >= 0.6)


def test_weakest_dimension_matches_lowest_score(report: QualityReport) -> None:
    score_map = {item.dimension: item.score for item in report.dimensions}
    expected_weakest = min(score_map, key=score_map.get)
    assert report.weakest_dimension == expected_weakest


def test_trend_is_valid_literal_value(report: QualityReport) -> None:
    assert report.trend in {"converging", "stagnating", "diverging"}


def test_each_dimension_score_between_zero_and_one(report: QualityReport) -> None:
    for item in report.dimensions:
        assert 0.0 <= item.score <= 1.0


def test_continuity_score_is_one_when_all_effect_refs_exist(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> None:
    secret_ids = [secret.secret_id for secret in web.secrets]
    adjusted_storylets = []
    for idx, storylet in enumerate(pool.storylets):
        effects = storylet.effects.model_copy(
            update={
                "secrets_revealed": [secret_ids[idx % len(secret_ids)]],
                "triggers_chain": secret_ids[(idx + 1) % len(secret_ids)],
            }
        )
        adjusted_storylets.append(storylet.model_copy(update={"effects": effects}))

    adjusted_pool = pool.model_copy(update={"storylets": adjusted_storylets})
    adjusted_report = evaluate_quality(config, web, adjusted_pool, gateway=None)
    assert _score_for(adjusted_report, "continuity") == 1.0


def test_continuity_score_drops_when_broken_ref_introduced(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> None:
    storylets = list(pool.storylets)
    broken_effects = storylets[0].effects.model_copy(
        update={
            "secrets_revealed": ["broken_secret_id"],
            "triggers_chain": "broken_chain_id",
        }
    )
    storylets[0] = storylets[0].model_copy(update={"effects": broken_effects})
    broken_pool = pool.model_copy(update={"storylets": storylets})

    broken_report = evaluate_quality(config, web, broken_pool, gateway=None)
    assert _score_for(broken_report, "continuity") < 1.0


def test_venue_permeation_increases_with_more_unique_venues(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> None:
    same_venue_storylets = [storylet.model_copy(update={"venue_hint": "fixed_venue"}) for storylet in pool.storylets]
    varied_venue_storylets = [
        storylet.model_copy(update={"venue_hint": f"venue_{idx}"})
        for idx, storylet in enumerate(pool.storylets)
    ]

    same_venue_pool = pool.model_copy(update={"storylets": same_venue_storylets})
    varied_venue_pool = pool.model_copy(update={"storylets": varied_venue_storylets})

    same_report = evaluate_quality(config, web, same_venue_pool, gateway=None)
    varied_report = evaluate_quality(config, web, varied_venue_pool, gateway=None)

    assert _score_for(varied_report, "venue_permeation") > _score_for(
        same_report, "venue_permeation"
    )


def test_character_motivation_credibility_reflects_hidden_need_difference(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> None:
    unchanged_report = evaluate_quality(config, web, pool, gateway=None)

    identical_chars = [
        character.model_copy(update={"hidden_need": character.public_identity})
        for character in config.characters
    ]
    identical_config = config.model_copy(update={"characters": identical_chars})
    identical_report = evaluate_quality(identical_config, web, pool, gateway=None)

    assert _score_for(unchanged_report, "character_motivation_credibility") > _score_for(
        identical_report, "character_motivation_credibility"
    )
    assert _score_for(identical_report, "character_motivation_credibility") == 0.0


def test_secret_lethality_bonus_fires_when_std_dev_exceeds_threshold(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> None:
    flat_secrets = [secret.model_copy(update={"lethality_score": 0.5}) for secret in web.secrets]
    varied_values = [0.1 if idx % 2 == 0 else 0.9 for idx in range(len(web.secrets))]
    varied_secrets = [
        secret.model_copy(update={"lethality_score": varied_values[idx]})
        for idx, secret in enumerate(web.secrets)
    ]

    flat_web = web.model_copy(update={"secrets": flat_secrets})
    varied_web = web.model_copy(update={"secrets": varied_secrets})

    flat_report = evaluate_quality(config, flat_web, pool, gateway=None)
    varied_report = evaluate_quality(config, varied_web, pool, gateway=None)

    assert _score_for(varied_report, "secret_lethality") == pytest.approx(
        _score_for(flat_report, "secret_lethality") + 0.05,
        abs=1e-6,
    )


def test_improvement_suggestion_is_non_empty(report: QualityReport) -> None:
    assert report.improvement_suggestion.strip()
    assert report.weakest_dimension in report.improvement_suggestion


def test_passed_true_when_overall_is_at_least_point_six(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> None:
    high_config, high_web, high_pool = _high_quality_inputs(config, web, pool)
    high_report = evaluate_quality(high_config, high_web, high_pool, gateway=None)

    assert high_report.overall_score >= 0.6
    assert high_report.passed is True


def test_passed_false_when_overall_is_below_point_six(
    config: WorldConfiguration,
    web: TensionWeb,
    pool: StoryletPool,
) -> None:
    low_config, low_web, low_pool = _low_quality_inputs(config, web, pool)
    low_report = evaluate_quality(low_config, low_web, low_pool, gateway=None)

    assert low_report.overall_score < 0.6
    assert low_report.passed is False
