from __future__ import annotations

from rpg_backend.domain.pack_schema import OpeningGuidance
from rpg_backend.domain.opening_guidance import build_opening_guidance_payload


def test_opening_guidance_payload_builds_observe_ask_act_prompts() -> None:
    payload = build_opening_guidance_payload(
        title='Forest Siege',
        description='A warded city is slipping toward collapse.',
        input_hint='Type anything you want to do, or choose a move.',
        first_beat_title='The First Silence Breaks',
        first_scene_seed='The first ward flickers above a crowded square.',
        first_scene_npcs=['Elira Voss', 'Kaelen Rook'],
        first_scene_moves=[
            {'move_id': 'trace_anomaly', 'label': 'Trace The Anomaly [fast but dirty]'},
            {'move_id': 'convince_guard', 'label': 'Negotiate Passage [politically safe, resource heavy]'},
            {'move_id': 'reroute_power', 'label': 'Reroute Emergency Power [steady but slow]'},
        ],
    )

    prompts = payload['starter_prompts']
    assert len(prompts) == 3
    assert prompts[0].startswith('I begin by observing')
    assert prompts[1].startswith('I ask Elira Voss')
    assert prompts[2].startswith('I take a decisive first action')


def test_opening_guidance_model_clamps_overlong_text_fields() -> None:
    guidance = OpeningGuidance.model_validate(
        {
            "intro_text": "  ".join(["You are stepping into a crisis corridor that keeps widening under public pressure."] * 8),
            "goal_hint": "  ".join(["Start by finding the first break point, the safest ally, and the cost of waiting."] * 6),
            "starter_prompts": [
                "I scan the damage pattern first.",
                "I ask the nearest ally what changed.",
                "I make the safest stabilizing move available.",
            ],
        }
    )

    assert len(guidance.intro_text) <= 320
    assert len(guidance.goal_hint) <= 220
    assert "  " not in guidance.intro_text
    assert "  " not in guidance.goal_hint
