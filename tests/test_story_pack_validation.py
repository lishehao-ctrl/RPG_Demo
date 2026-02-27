from __future__ import annotations

import pytest

from app.modules.story_domain.schemas import StoryPackV1


def _player_effect(metric: str, center: int) -> dict:
    return {
        "target_type": "player",
        "metric": metric,
        "center": center,
        "intensity": 1,
    }


def _valid_pack() -> dict:
    return {
        "schema_version": "2.0",
        "story_id": "s1",
        "title": "Demo",
        "start_node_id": "n1",
        "npc_defs": [
            {
                "npc_id": "npc_alex",
                "name": "Alex",
                "initial_affection": 0,
                "initial_trust": 0,
            }
        ],
        "global_fallbacks": [
            {
                "fallback_id": "fb1",
                "text": "fallback one",
                "target_node_id": "n1",
                "range_effects": [_player_effect("energy", -1)],
            },
            {
                "fallback_id": "fb2",
                "text": "fallback two",
                "target_node_id": "n2",
                "range_effects": [_player_effect("knowledge", 1)],
            },
        ],
        "nodes": [
            {
                "node_id": "n1",
                "title": "N1",
                "scene_brief": "s1",
                "node_fallback_id": "fb1",
                "choices": [
                    {
                        "choice_id": "c1",
                        "text": "study",
                        "intent_tags": ["study"],
                        "next_node_id": "n2",
                        "range_effects": [_player_effect("knowledge", 1)],
                        "gate_rules": [
                            {
                                "npc_id": "npc_alex",
                                "min_trust_tier": "Neutral",
                            }
                        ],
                    }
                ],
            },
            {
                "node_id": "n2",
                "title": "N2",
                "scene_brief": "s2",
                "choices": [
                    {
                        "choice_id": "c2",
                        "text": "back",
                        "intent_tags": ["back"],
                        "next_node_id": "n1",
                        "range_effects": [_player_effect("energy", 1)],
                    }
                ],
            },
        ],
    }


def test_story_pack_validates_successfully() -> None:
    pack = StoryPackV1.model_validate(_valid_pack())
    assert pack.story_id == "s1"
    assert pack.schema_version == "2.0"


def test_story_pack_rejects_legacy_schema_version() -> None:
    raw = _valid_pack()
    raw["schema_version"] = "1.1"
    with pytest.raises(Exception):
        StoryPackV1.model_validate(raw)


def test_story_pack_rejects_invalid_next_node() -> None:
    raw = _valid_pack()
    raw["nodes"][0]["choices"][0]["next_node_id"] = "missing"
    with pytest.raises(Exception) as exc:
        StoryPackV1.model_validate(raw)
    assert "choice.next_node_id not found" in str(exc.value)


def test_story_pack_rejects_fallback_without_range_effect() -> None:
    raw = _valid_pack()
    raw["global_fallbacks"][0]["range_effects"] = []
    with pytest.raises(Exception):
        StoryPackV1.model_validate(raw)


def test_story_pack_rejects_gate_rule_with_unknown_npc() -> None:
    raw = _valid_pack()
    raw["nodes"][0]["choices"][0]["gate_rules"] = [{"npc_id": "missing", "min_affection_tier": "Warm"}]
    with pytest.raises(Exception) as exc:
        StoryPackV1.model_validate(raw)
    assert "choice gate npc_id not found" in str(exc.value)


def test_story_pack_rejects_choice_with_missing_ending_ref() -> None:
    raw = _valid_pack()
    raw["nodes"][0]["choices"][0]["ending_id"] = "missing_ending"
    with pytest.raises(Exception) as exc:
        StoryPackV1.model_validate(raw)
    assert "choice ending_id not found in effective endings" in str(exc.value)


def test_story_pack_rejects_unknown_reactive_npc_id() -> None:
    raw = _valid_pack()
    raw["nodes"][0]["choices"][0]["reactive_npc_ids"] = ["missing_npc"]
    with pytest.raises(Exception) as exc:
        StoryPackV1.model_validate(raw)
    assert "choice reactive_npc_id not found" in str(exc.value)


def test_story_pack_rejects_duplicate_npc_reaction_rule_key() -> None:
    raw = _valid_pack()
    raw["npc_reaction_policies"] = [
        {
            "npc_id": "npc_alex",
            "rules": [
                {
                    "tier": "Neutral",
                    "source": "choice",
                    "effects": [_player_effect("energy", -1)],
                },
                {
                    "tier": "Neutral",
                    "source": "choice",
                    "effects": [_player_effect("knowledge", 1)],
                },
            ],
        }
    ]
    with pytest.raises(Exception) as exc:
        StoryPackV1.model_validate(raw)
    assert "duplicate npc reaction rule key" in str(exc.value)
