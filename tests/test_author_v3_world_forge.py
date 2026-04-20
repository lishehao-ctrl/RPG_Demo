from __future__ import annotations

from collections import deque

import pytest

from rpg_backend.author_v3.contracts import ForgedCharacter, RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.relationship_matrix import build_relationship_matrix
from rpg_backend.author_v3.world_forge import forge_world


@pytest.fixture
def config() -> WorldConfiguration:
    return forge_world("董事会权力斗争")


def test_forge_world_deterministic_returns_world_configuration(config: WorldConfiguration) -> None:
    assert isinstance(config, WorldConfiguration)


def test_forge_world_deterministic_has_5_characters(config: WorldConfiguration) -> None:
    assert len(config.characters) == 5


def test_forge_world_deterministic_character_ids_unique(config: WorldConfiguration) -> None:
    character_ids = [character.character_id for character in config.characters]
    assert len(character_ids) == len(set(character_ids))


def test_forge_world_deterministic_has_protagonist(config: WorldConfiguration) -> None:
    character_ids = {character.character_id for character in config.characters}
    assert config.protagonist_id in character_ids


def test_forge_world_deterministic_shell_is_office_power(config: WorldConfiguration) -> None:
    assert config.seed.detected_shell == "office_power"


def test_forge_world_deterministic_all_characters_have_required_fields(config: WorldConfiguration) -> None:
    for character in config.characters:
        assert isinstance(character, ForgedCharacter)
        assert character.character_id.strip()
        assert character.display_name.strip()
        assert character.public_identity.strip()
        assert character.hidden_need.strip()
        assert character.worldly_desire.strip()
        assert character.fear.strip()


def test_forge_world_deterministic_relationship_edges_count(config: WorldConfiguration) -> None:
    assert len(config.relationship_edges) == 10


def test_forge_world_deterministic_tension_scores_in_range(config: WorldConfiguration) -> None:
    scores = [edge.tension_score for edge in config.relationship_edges]
    assert all(0.0 <= score <= 1.0 for score in scores)


def test_forge_world_deterministic_edge_characters_exist(config: WorldConfiguration) -> None:
    character_ids = {character.character_id for character in config.characters}
    for edge in config.relationship_edges:
        assert edge.character_a_id in character_ids
        assert edge.character_b_id in character_ids


def test_forge_world_deterministic_connected_graph(config: WorldConfiguration) -> None:
    adjacency: dict[str, set[str]] = {character.character_id: set() for character in config.characters}
    for edge in config.relationship_edges:
        adjacency[edge.character_a_id].add(edge.character_b_id)
        adjacency[edge.character_b_id].add(edge.character_a_id)

    visited: set[str] = set()
    queue: deque[str] = deque([config.protagonist_id])

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                queue.append(neighbor)

    assert visited == set(adjacency.keys())


def test_forge_world_deterministic_min_two_edges_per_char(config: WorldConfiguration) -> None:
    edge_count_by_character = {character.character_id: 0 for character in config.characters}
    for edge in config.relationship_edges:
        edge_count_by_character[edge.character_a_id] += 1
        edge_count_by_character[edge.character_b_id] += 1
    assert all(edge_count >= 2 for edge_count in edge_count_by_character.values())


def test_forge_world_deterministic_desire_conflict_exists(config: WorldConfiguration) -> None:
    desire_counts: dict[str, int] = {}
    for character in config.characters:
        desire_counts[character.worldly_desire] = desire_counts.get(character.worldly_desire, 0) + 1
    assert any(count >= 2 for count in desire_counts.values())


def test_build_relationship_matrix_returns_matrix(config: WorldConfiguration) -> None:
    matrix = build_relationship_matrix(config)
    assert isinstance(matrix, RelationshipMatrix)


def test_relationship_matrix_tension_density_range(config: WorldConfiguration) -> None:
    matrix = build_relationship_matrix(config)
    assert 0.0 <= matrix.tension_density <= 1.0


def test_relationship_matrix_connectivity_score(config: WorldConfiguration) -> None:
    matrix = build_relationship_matrix(config)
    assert matrix.connectivity_score == 1.0


def test_relationship_matrix_slot_assignments_cover_all_chars(config: WorldConfiguration) -> None:
    matrix = build_relationship_matrix(config)
    assert set(matrix.slot_assignments.keys()) == {character.character_id for character in config.characters}


def test_relationship_matrix_protagonist_is_lead_interest(config: WorldConfiguration) -> None:
    matrix = build_relationship_matrix(config)
    assert matrix.slot_assignments[config.protagonist_id] == "lead_interest"


def test_relationship_matrix_has_rival(config: WorldConfiguration) -> None:
    matrix = build_relationship_matrix(config)
    assert "rival_interest" in matrix.slot_assignments.values()


def test_relationship_matrix_hook_pairs(config: WorldConfiguration) -> None:
    matrix = build_relationship_matrix(config)
    has_hooks = any(edge.hooks for edge in config.relationship_edges)
    if has_hooks:
        assert matrix.hook_pairs
