from __future__ import annotations

import pytest

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.storylet_compiler import Storylet, StoryletCondition, StoryletEffect
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.runtime import build_initial_world_state
from rpg_backend.play_v2.storylet_matcher import find_matching_storylets


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


def _storylet_dict(
    plan: CompiledPlayPlan,
    storylet_id: str,
    *,
    preconditions: StoryletCondition | None = None,
) -> dict[str, object]:
    characters = [member.character_id for member in plan.cast[:2]]
    storylet = Storylet(
        storylet_id=storylet_id,
        narrative_function="hook",
        title=f"Title {storylet_id}",
        scene_text=f"Scene {storylet_id}",
        characters_involved=characters,
        venue_hint="test venue",
        dramatic_weight=0.5,
        preconditions=preconditions or StoryletCondition(),
        effects=StoryletEffect(),
    )
    return storylet.model_dump()


def _plan_with_storylets(
    plan: CompiledPlayPlan,
    storylets: list[dict[str, object]] | None,
) -> CompiledPlayPlan:
    return plan.model_copy(update={"storylet_pool": storylets}, deep=True)


def _state_with_updates(plan: CompiledPlayPlan, **updates: object):
    state = build_initial_world_state(plan, session_id="storylet_matcher_case")
    if updates:
        state = state.model_copy(update=updates, deep=True)
    return state


def test_returns_empty_when_storylet_pool_is_none(v3_plan: CompiledPlayPlan) -> None:
    state = _state_with_updates(v3_plan)
    plan = _plan_with_storylets(v3_plan, None)

    assert find_matching_storylets(state, plan) == []


def test_returns_empty_when_storylet_pool_is_empty(v3_plan: CompiledPlayPlan) -> None:
    state = _state_with_updates(v3_plan)
    plan = _plan_with_storylets(v3_plan, [])

    assert find_matching_storylets(state, plan) == []


def test_all_four_conditions_hit_scores_one(v3_plan: CompiledPlayPlan) -> None:
    current_segment = v3_plan.segments[0]
    target_id = v3_plan.cast[0].character_id
    secret_id = "secret_all_hit"
    storylet = _storylet_dict(
        v3_plan,
        "storylet_all_hit",
        preconditions=StoryletCondition(
            required_secrets_known=[secret_id],
            required_relationships=[target_id],
            min_tension_score=1.0,
            required_segment_roles=[current_segment.segment_role],
        ),
    )
    plan = _plan_with_storylets(v3_plan, [storylet])
    state = _state_with_updates(
        plan,
        known_secret_ids=[secret_id],
        scene_heat=6,
        secret_exposure=6,
        witness_pressure=3,
    )

    matches = find_matching_storylets(state, plan)

    assert len(matches) == 1
    assert matches[0].match_score == pytest.approx(1.0)
    assert matches[0].matched_conditions == [
        "required_secrets_known",
        "required_relationships",
        "min_tension_score",
        "required_segment_roles",
    ]


def test_only_required_secrets_known_hit_scores_point_three_five(v3_plan: CompiledPlayPlan) -> None:
    secret_id = "secret_only_hit"
    storylet = _storylet_dict(
        v3_plan,
        "storylet_secret_only",
        preconditions=StoryletCondition(
            required_secrets_known=[secret_id],
            required_relationships=["missing_character"],
            min_tension_score=0.5,
            required_segment_roles=["terminal"],
        ),
    )
    plan = _plan_with_storylets(v3_plan, [storylet])
    state = _state_with_updates(
        plan,
        known_secret_ids=[secret_id],
        scene_heat=0,
        secret_exposure=0,
        witness_pressure=0,
    )

    matches = find_matching_storylets(state, plan, min_score=0.0)

    assert len(matches) == 1
    assert matches[0].match_score == pytest.approx(0.35)
    assert matches[0].matched_conditions == ["required_secrets_known"]


def test_min_score_filters_low_scoring_storylet(v3_plan: CompiledPlayPlan) -> None:
    target_id = v3_plan.cast[0].character_id
    storylet = _storylet_dict(
        v3_plan,
        "storylet_below_threshold",
        preconditions=StoryletCondition(
            required_secrets_known=["missing_secret"],
            required_relationships=[target_id],
            min_tension_score=0.9,
            required_segment_roles=["terminal"],
        ),
    )
    plan = _plan_with_storylets(v3_plan, [storylet])
    state = _state_with_updates(
        plan,
        scene_heat=0,
        secret_exposure=0,
        witness_pressure=0,
    )

    matches = find_matching_storylets(state, plan, min_score=0.3)

    assert matches == []


def test_max_count_caps_results(v3_plan: CompiledPlayPlan) -> None:
    current_segment = v3_plan.segments[0]
    target_id = v3_plan.cast[0].character_id
    secret_id = "secret_max_count"
    storylets = [
        _storylet_dict(
            v3_plan,
            f"storylet_{index}",
            preconditions=StoryletCondition(
                required_secrets_known=[secret_id],
                required_relationships=[target_id],
                min_tension_score=1.0,
                required_segment_roles=[current_segment.segment_role],
            ),
        )
        for index in range(5)
    ]
    plan = _plan_with_storylets(v3_plan, storylets)
    state = _state_with_updates(
        plan,
        known_secret_ids=[secret_id],
        scene_heat=6,
        secret_exposure=6,
        witness_pressure=3,
    )

    matches = find_matching_storylets(state, plan, max_count=3)

    assert len(matches) == 3
    assert [match.storylet_id for match in matches] == [
        "storylet_0",
        "storylet_1",
        "storylet_2",
    ]
    assert len(find_matching_storylets(state, plan, max_count=1)) <= 1


def test_matched_conditions_are_reported_accurately(v3_plan: CompiledPlayPlan) -> None:
    current_segment = v3_plan.segments[0]
    secret_id = "secret_partial_hit"
    storylet = _storylet_dict(
        v3_plan,
        "storylet_partial_hit",
        preconditions=StoryletCondition(
            required_secrets_known=[secret_id],
            required_relationships=["missing_character"],
            min_tension_score=1.0,
            required_segment_roles=[current_segment.segment_role],
        ),
    )
    plan = _plan_with_storylets(v3_plan, [storylet])
    state = _state_with_updates(
        plan,
        known_secret_ids=[secret_id],
        scene_heat=0,
        secret_exposure=0,
        witness_pressure=0,
    )

    matches = find_matching_storylets(state, plan, min_score=0.0)

    assert len(matches) == 1
    assert matches[0].matched_conditions == [
        "required_secrets_known",
        "required_segment_roles",
    ]


def test_end_to_end_with_v3_plan_and_initial_state(v3_plan: CompiledPlayPlan) -> None:
    assert v3_plan.storylet_pool is not None
    storylets = [Storylet.model_validate(raw_storylet) for raw_storylet in v3_plan.storylet_pool]
    storylet_with_secret = next(
        storylet for storylet in storylets if storylet.preconditions.required_secrets_known
    )
    state = _state_with_updates(
        v3_plan,
        known_secret_ids=storylet_with_secret.preconditions.required_secrets_known,
    )

    matches = find_matching_storylets(state, v3_plan)

    assert len(matches) >= 1
    assert any(
        "required_secrets_known" in match.matched_conditions
        for match in matches
    )
