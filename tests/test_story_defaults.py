from __future__ import annotations

import pytest

from app.modules.story_domain.schemas import StoryPackV1, resolve_effective_fallbacks_endings


def _minimal_pack() -> dict:
    return {
        "schema_version": "2.0",
        "story_id": "s_defaults",
        "title": "Defaults",
        "start_node_id": "n1",
        "nodes": [
            {
                "node_id": "n1",
                "title": "Node1",
                "scene_brief": "scene",
                "choices": [
                    {
                        "choice_id": "c1",
                        "text": "go",
                        "intent_tags": ["go"],
                        "next_node_id": "n1",
                        "range_effects": [
                            {
                                "target_type": "player",
                                "metric": "energy",
                                "center": -1,
                                "intensity": 1,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_default_fallbacks_and_endings_loaded() -> None:
    pack = StoryPackV1.model_validate(_minimal_pack())
    fallbacks, endings = resolve_effective_fallbacks_endings(pack)
    reason_codes = {item.reason_code for item in fallbacks if item.reason_code is not None}
    ending_ids = {item.ending_id for item in endings}

    assert reason_codes == {"NO_MATCH", "LOW_CONF", "INPUT_POLICY", "OFF_TOPIC"}
    assert {"ending_forced_fail", "ending_neutral_default", "ending_success_default"}.issubset(ending_ids)


def test_story_override_precedence_on_default_fallback() -> None:
    raw = _minimal_pack()
    raw["fallback_policy"] = {
        "fallback_overrides": [
            {
                "fallback_id": "fb_no_match",
                "reason_code": "NO_MATCH",
                "text": "override text",
                "mainline_nudge": "override nudge",
                "range_effects": [
                    {
                        "target_type": "player",
                        "metric": "energy",
                        "center": 0,
                        "intensity": 1,
                    }
                ],
            }
        ]
    }
    pack = StoryPackV1.model_validate(raw)
    fallbacks, _ = resolve_effective_fallbacks_endings(pack)
    no_match = next(item for item in fallbacks if item.fallback_id == "fb_no_match")

    assert no_match.text == "override text"
    assert no_match.mainline_nudge == "override nudge"


def test_forced_ending_id_must_exist() -> None:
    raw = _minimal_pack()
    raw["fallback_policy"] = {
        "forced_fallback_ending_id": "missing_ending",
        "forced_fallback_threshold": 3,
    }

    with pytest.raises(Exception):
        StoryPackV1.model_validate(raw)
