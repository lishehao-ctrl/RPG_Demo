"""Storylet engine tests — verify fire / cooldown / chain / preconditions.

The engine is the bridge between author's storylet pool and play state.
Until Phase 1c the storylets sat dormant in `plan.storylet_pool` and only
seasoned narration prompts as background; these tests pin the new behaviour
that storylets actually mutate state when fired.
"""

from __future__ import annotations

import pytest

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.storylet_compiler import (
    Storylet,
    StoryletCondition,
    StoryletEffect,
)
from rpg_backend.author_v3.tension_weaver import SecretChain
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import UrbanWorldState
from rpg_backend.play_v2.runtime import build_initial_world_state
from rpg_backend.play_v2.storylet_engine import (
    fire_storylet,
    is_in_cooldown,
    preconditions_satisfied,
    reset_turn_storylet_state,
    storylet_pool_iter,
)


# ---------------- fixtures ----------------


@pytest.fixture(scope="module")
def _shared_v3_plan() -> CompiledPlayPlan:
    """Module-scoped: running the author pipeline once is enough — tests then
    deep-copy via `fresh_plan` to keep mutations isolated."""
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


@pytest.fixture()
def fresh_plan(_shared_v3_plan: CompiledPlayPlan) -> CompiledPlayPlan:
    """Function-scoped deep copy — mutations to storylet_pool / secret_chains
    in one test don't leak to others."""
    return _shared_v3_plan.model_copy(deep=True)


@pytest.fixture()
def fresh_state(fresh_plan: CompiledPlayPlan) -> UrbanWorldState:
    return build_initial_world_state(fresh_plan, session_id="storylet_test")


def _make_storylet(
    storylet_id: str,
    *,
    narrative_function: str = "escalation",
    cooldown_turns: int = 0,
    secrets_revealed: list[str] | None = None,
    relationship_shifts: dict[str, float] | None = None,
    tension_delta: float = 0.0,
    required_secrets_known: list[str] | None = None,
    required_segment_roles: list[str] | None = None,
    min_tension_score: float = 0.0,
    characters_involved: list[str] | None = None,
) -> Storylet:
    return Storylet(
        storylet_id=storylet_id,
        narrative_function=narrative_function,  # type: ignore[arg-type]
        title=f"测试 storylet {storylet_id}",
        scene_text="测试场景描述",
        characters_involved=characters_involved or ["protagonist"],
        venue_hint="测试地点",
        dramatic_weight=0.5,
        cooldown_turns=cooldown_turns,
        preconditions=StoryletCondition(
            required_secrets_known=required_secrets_known or [],
            required_relationships=[],
            min_tension_score=min_tension_score,
            required_segment_roles=required_segment_roles or [],  # type: ignore[arg-type]
        ),
        effects=StoryletEffect(
            secrets_revealed=secrets_revealed or [],
            relationship_shifts=relationship_shifts or {},
            tension_delta=tension_delta,
            triggers_chain=None,
        ),
    )


def _inject_storylet_pool(plan: CompiledPlayPlan, storylets: list[Storylet]) -> None:
    plan.storylet_pool = [s.model_dump(mode="json") for s in storylets]


def _inject_chains(plan: CompiledPlayPlan, chains: list[SecretChain]) -> None:
    plan.secret_chains = [c.model_dump() for c in chains]


# ---------------- core fire behaviour ----------------


def test_fire_storylet_reveals_secrets_into_state(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    storylet = _make_storylet("st_reveal_a", secrets_revealed=["secret_alpha", "secret_beta"])
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    assert result.fired is True
    assert "secret_alpha" in fresh_state.known_secret_ids
    assert "secret_beta" in fresh_state.known_secret_ids
    assert sorted(result.revealed_secret_ids) == ["secret_alpha", "secret_beta"]
    assert "secret_alpha" in fresh_state.last_turn_revealed_secret_ids
    assert storylet.storylet_id in fresh_state.fired_storylet_ids


def test_fire_storylet_relationship_shifts_quantize_to_affection_delta(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    target_char = next(iter(fresh_state.relationships.keys()), None)
    if not target_char:
        pytest.skip("no relationship targets in fresh state — author pipeline didn't seed any")

    initial_affection = fresh_state.relationships[target_char].affection
    storylet = _make_storylet(
        "st_shift",
        relationship_shifts={target_char: 1.0},  # +1.0 → +3 affection delta
    )
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    assert result.fired is True
    expected_max_delta = min(3, 6 - initial_affection)
    assert fresh_state.relationships[target_char].affection >= initial_affection
    assert result.relationship_changes.get(target_char, 0) > 0
    assert result.relationship_changes.get(target_char, 0) <= expected_max_delta


def test_fire_storylet_tension_delta_moves_scene_heat(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    fresh_state.scene_heat = 2
    storylet = _make_storylet("st_tension", tension_delta=0.5)
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    assert result.fired is True
    assert result.scene_heat_delta == 1
    assert fresh_state.scene_heat == 3


def test_fire_storylet_clamps_scene_heat_to_max(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    fresh_state.scene_heat = 6  # already at cap
    storylet = _make_storylet("st_overheat", tension_delta=1.0)
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    assert result.fired is True
    assert fresh_state.scene_heat == 6  # clamped
    assert result.scene_heat_delta == 0


# ---------------- cooldown ----------------


def test_storylet_cooldown_blocks_consecutive_fire(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    storylet = _make_storylet("st_cd", cooldown_turns=3, secrets_revealed=["x"])
    _inject_storylet_pool(fresh_plan, [storylet])

    fresh_state.turn_index = 5
    first = fire_storylet(storylet, fresh_state, fresh_plan)
    assert first.fired is True

    # Same turn → cooldown blocks it.
    second = fire_storylet(storylet, fresh_state, fresh_plan)
    assert second.fired is False
    assert second.skipped_reason == "cooldown"

    # Two turns later → still cooled down (turn_diff=2 < 3).
    fresh_state.turn_index = 7
    third = fire_storylet(storylet, fresh_state, fresh_plan)
    assert third.fired is False
    assert third.skipped_reason == "cooldown"

    # Three turns later → cooldown elapsed.
    fresh_state.turn_index = 8
    fourth = fire_storylet(storylet, fresh_state, fresh_plan)
    assert fourth.fired is True


def test_zero_cooldown_storylet_can_refire_same_turn(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    storylet = _make_storylet("st_no_cd", cooldown_turns=0, secrets_revealed=["y"])
    _inject_storylet_pool(fresh_plan, [storylet])

    first = fire_storylet(storylet, fresh_state, fresh_plan)
    second = fire_storylet(storylet, fresh_state, fresh_plan)
    assert first.fired is True
    # second fires too — preconditions still pass and cooldown=0
    assert second.fired is True


# ---------------- preconditions ----------------


def test_storylet_with_unmet_required_secrets_does_not_fire(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    storylet = _make_storylet(
        "st_gated",
        required_secrets_known=["unobtainable_secret"],
        secrets_revealed=["payoff"],
    )
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    assert result.fired is False
    assert result.skipped_reason == "preconditions_unmet"
    assert "payoff" not in fresh_state.known_secret_ids


def test_bypass_preconditions_lets_player_pick_fire(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    """When the player picks a storylet card, we trust their choice and skip
    the strict precondition gate (cooldown still blocks)."""
    storylet = _make_storylet(
        "st_player_pick",
        required_secrets_known=["nonexistent"],
        secrets_revealed=["picked_payoff"],
    )
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan, bypass_preconditions=True)

    assert result.fired is True
    assert "picked_payoff" in fresh_state.known_secret_ids


def test_min_tension_threshold_gates_fire(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    fresh_state.scene_heat = 0
    fresh_state.secret_exposure = 0
    fresh_state.witness_pressure = 0
    storylet = _make_storylet(
        "st_high_tension", min_tension_score=0.7, secrets_revealed=["explosion"]
    )
    _inject_storylet_pool(fresh_plan, [storylet])
    assert preconditions_satisfied(storylet, fresh_state, fresh_plan) is False

    # Crank tension up to 1.0 (heat 6 / 6 + exposure 6 / 6 + witness 3 / 3 → ~1.0).
    fresh_state.scene_heat = 6
    fresh_state.secret_exposure = 6
    fresh_state.witness_pressure = 3
    assert preconditions_satisfied(storylet, fresh_state, fresh_plan) is True


# ---------------- chain triggers ----------------


def test_chain_cascades_unlock_secrets_after_fire(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    """Reveal A → SecretChain says A unlocks B → B should appear in known_secret_ids."""
    chains = [
        SecretChain(
            trigger_secret_id="secret_root",
            unlocks_secret_id="secret_branch",
            narrative_logic="When the root secret is exposed, the branch follows.",
        ),
        SecretChain(
            trigger_secret_id="secret_branch",
            unlocks_secret_id="secret_leaf",
            narrative_logic="The branch reveal trips the leaf.",
        ),
    ]
    _inject_chains(fresh_plan, chains)

    storylet = _make_storylet("st_root", secrets_revealed=["secret_root"])
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    assert result.fired is True
    assert "secret_root" in fresh_state.known_secret_ids
    # BFS cascade: root → branch → leaf
    assert "secret_branch" in fresh_state.known_secret_ids
    assert "secret_leaf" in fresh_state.known_secret_ids
    assert "secret_branch" in result.chained_secret_ids
    assert "secret_leaf" in result.chained_secret_ids


def test_chain_cycle_does_not_loop_forever(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    """Defensive: A unlocks B, B unlocks A — engine must not infinite-loop."""
    chains = [
        SecretChain(
            trigger_secret_id="cycle_a",
            unlocks_secret_id="cycle_b",
            narrative_logic="loop-1",
        ),
        SecretChain(
            trigger_secret_id="cycle_b",
            unlocks_secret_id="cycle_a",
            narrative_logic="loop-2",
        ),
    ]
    _inject_chains(fresh_plan, chains)

    storylet = _make_storylet("st_cycle", secrets_revealed=["cycle_a"])
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    assert result.fired is True
    assert "cycle_a" in fresh_state.known_secret_ids
    assert "cycle_b" in fresh_state.known_secret_ids
    # Engine completed without hanging — implicit pass


# ---------------- helpers ----------------


def test_reset_turn_storylet_state_clears_per_turn_buffer(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    storylet = _make_storylet("st_reset", secrets_revealed=["s"])
    _inject_storylet_pool(fresh_plan, [storylet])

    fire_storylet(storylet, fresh_state, fresh_plan)
    assert "st_reset" in fresh_state.last_turn_fired_storylet_ids

    reset_turn_storylet_state(fresh_state)
    assert fresh_state.last_turn_fired_storylet_ids == []
    # But long-term cooldown record persists across resets.
    assert "st_reset" in fresh_state.fired_storylet_ids


def test_storylet_pool_iter_skips_malformed_records(
    fresh_plan: CompiledPlayPlan,
) -> None:
    fresh_plan.storylet_pool = [
        {"this": "is", "not": "a valid storylet"},
        _make_storylet("st_valid").model_dump(mode="json"),
    ]
    storylets = list(storylet_pool_iter(fresh_plan))
    assert len(storylets) == 1
    assert storylets[0].storylet_id == "st_valid"


def test_known_secrets_cap_prevents_overflow(
    fresh_plan: CompiledPlayPlan, fresh_state: UrbanWorldState
) -> None:
    fresh_state.known_secret_ids = [f"existing_{i}" for i in range(8)]  # already at cap=8
    storylet = _make_storylet("st_overflow", secrets_revealed=["new_secret"])
    _inject_storylet_pool(fresh_plan, [storylet])

    result = fire_storylet(storylet, fresh_state, fresh_plan)

    # The fire reports as completed but new_secret didn't make it (cap reached).
    assert result.fired is True
    assert "new_secret" not in fresh_state.known_secret_ids
    assert len(fresh_state.known_secret_ids) == 8


# ---------------- is_in_cooldown helper ----------------


def test_is_in_cooldown_returns_false_for_never_fired(fresh_state: UrbanWorldState) -> None:
    storylet = _make_storylet("st_unfired", cooldown_turns=5)
    assert is_in_cooldown(storylet, fresh_state) is False


def test_is_in_cooldown_returns_false_when_cooldown_zero(fresh_state: UrbanWorldState) -> None:
    storylet = _make_storylet("st_zero_cd", cooldown_turns=0)
    fresh_state.fired_storylet_ids[storylet.storylet_id] = fresh_state.turn_index
    assert is_in_cooldown(storylet, fresh_state) is False
