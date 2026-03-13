from __future__ import annotations

import json
from pathlib import Path

from rpg_backend.domain.story_pack_normalizer import normalize_story_pack_payload


FIXTURE = Path("sample_data/story_pack_v1.json")


def test_normalize_story_pack_payload_backfills_opening_guidance() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack.pop("opening_guidance", None)

    normalized = normalize_story_pack_payload(pack)

    assert normalized["opening_guidance"]["intro_text"]
    assert normalized["opening_guidance"]["goal_hint"]
    assert len(normalized["opening_guidance"]["starter_prompts"]) == 3


def test_normalize_story_pack_payload_clamps_existing_guidance() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack["opening_guidance"] = {
        "intro_text": "  ".join(["You are stepping into a citywide emergency corridor under mounting public pressure."] * 8),
        "goal_hint": "  ".join(["Understand what is breaking, what gets worse if you wait, and who can open the safest path."] * 5),
        "starter_prompts": [
            "I scan the scene first.",
            "I ask the nearest ally what changed.",
            "I commit to the safest stabilizing move.",
        ],
    }

    normalized = normalize_story_pack_payload(pack)

    assert len(normalized["opening_guidance"]["intro_text"]) <= 320
    assert len(normalized["opening_guidance"]["goal_hint"]) <= 220
