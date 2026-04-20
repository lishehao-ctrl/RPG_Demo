from __future__ import annotations

import pytest

from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.relationship_matrix import build_relationship_matrix
from rpg_backend.author_v3.storylet_compiler import (
    MappedSegment,
    Storylet,
    StoryletCompilerError,
    StoryletPool,
    compile_storylet_pool,
    map_storylets_to_segments,
)
from rpg_backend.author_v3.tension_weaver import TensionWeb, weave_secrets
from rpg_backend.author_v3.world_forge import forge_world


@pytest.fixture
def config() -> WorldConfiguration:
    return forge_world("董事会权力斗争")


@pytest.fixture
def matrix(config: WorldConfiguration) -> RelationshipMatrix:
    return build_relationship_matrix(config)


@pytest.fixture
def web(config: WorldConfiguration, matrix: RelationshipMatrix) -> TensionWeb:
    return weave_secrets(config, matrix)


@pytest.fixture
def pool(config: WorldConfiguration, web: TensionWeb, matrix: RelationshipMatrix) -> StoryletPool:
    return compile_storylet_pool(config, web, matrix)


class TestCompileStoryletPool:
    def test_returns_storylet_pool(self, pool: StoryletPool) -> None:
        assert isinstance(pool, StoryletPool)

    def test_has_enough_storylets(self, pool: StoryletPool) -> None:
        assert len(pool.storylets) >= 10

    def test_storylet_ids_unique(self, pool: StoryletPool) -> None:
        ids = [s.storylet_id for s in pool.storylets]
        assert len(ids) == len(set(ids))

    def test_all_narrative_functions_present(self, pool: StoryletPool) -> None:
        functions = {s.narrative_function for s in pool.storylets}
        assert "hook" in functions
        assert "escalation" in functions
        assert "reversal" in functions
        assert "revelation" in functions
        assert "resolution" in functions
        assert "cost" in functions

    def test_function_counts_match(self, pool: StoryletPool) -> None:
        from collections import Counter
        actual = Counter(s.narrative_function for s in pool.storylets)
        for func, count in pool.function_counts.items():
            assert actual[func] == count

    def test_characters_involved_valid(
        self, pool: StoryletPool, config: WorldConfiguration
    ) -> None:
        char_ids = {c.character_id for c in config.characters}
        for storylet in pool.storylets:
            for cid in storylet.characters_involved:
                assert cid in char_ids, f"storylet {storylet.storylet_id}: {cid!r} not in characters"

    def test_dramatic_weight_in_range(self, pool: StoryletPool) -> None:
        for s in pool.storylets:
            assert 0.0 <= s.dramatic_weight <= 1.0

    def test_protagonist_involved_in_most(
        self, pool: StoryletPool, config: WorldConfiguration
    ) -> None:
        protagonist = config.protagonist_id
        involved_count = sum(
            1 for s in pool.storylets if protagonist in s.characters_involved
        )
        assert involved_count >= len(pool.storylets) * 0.5

    def test_venue_hints_non_empty(self, pool: StoryletPool) -> None:
        for s in pool.storylets:
            assert s.venue_hint.strip()


class TestMapStoryletToSegments:
    def test_flagship_6_produces_6_segments(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        segments = map_storylets_to_segments(pool, "flagship_6", config, web, matrix)
        assert len(segments) == 6

    def test_short_3_produces_3_segments(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        segments = map_storylets_to_segments(pool, "short_3", config, web, matrix)
        assert len(segments) == 3

    def test_segment_roles_match_arc(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        segments = map_storylets_to_segments(pool, "flagship_6", config, web, matrix)
        roles = [s.segment_role for s in segments]
        assert roles == ["opening", "misread", "pressure", "reversal", "reveal", "terminal"]

    def test_terminal_segment_is_terminal(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        segments = map_storylets_to_segments(pool, "flagship_6", config, web, matrix)
        assert segments[-1].is_terminal is True
        for s in segments[:-1]:
            assert s.is_terminal is False

    def test_segments_have_move_families(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        segments = map_storylets_to_segments(pool, "flagship_6", config, web, matrix)
        for s in segments:
            assert len(s.allowed_move_families) >= 2

    def test_segment_ids_unique(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        segments = map_storylets_to_segments(pool, "flagship_6", config, web, matrix)
        ids = [s.segment_id for s in segments]
        assert len(ids) == len(set(ids))

    def test_unknown_arc_raises(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        with pytest.raises(StoryletCompilerError):
            map_storylets_to_segments(pool, "nonexistent_99", config, web, matrix)

    def test_segments_have_goals(
        self, pool: StoryletPool, config: WorldConfiguration,
        web: TensionWeb, matrix: RelationshipMatrix,
    ) -> None:
        segments = map_storylets_to_segments(pool, "flagship_6", config, web, matrix)
        for s in segments:
            assert s.scene_goal.strip()
            assert s.emotional_goal.strip()
            assert s.public_pressure_cue.strip()
            assert s.private_pressure_cue.strip()


class TestStoryletPoolValidation:
    def test_rejects_too_few_storylets(self) -> None:
        with pytest.raises(Exception):
            StoryletPool(storylets=[], function_counts={})
