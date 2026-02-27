from __future__ import annotations

import json

from app.modules.llm_boundary.prompt_profiles import render_prompt


def test_ending_default_v2_uses_english_language_slot() -> None:
    _, user_prompt = render_prompt(
        "ending_default_v2",
        slots={
            "ending_id": "ending_forced_fail",
            "ending_outcome": "fail",
            "tone": "somber",
            "epilogue": "The run closed.",
            "language": "English",
            "session_stats_json": '{"total_steps":3}',
            "recent_action_beats_json": '[{"step_index":1}]',
        },
    )
    assert "Language=English" in user_prompt


def test_selection_mapping_v3_profile_renders_required_slots() -> None:
    system_prompt, user_prompt = render_prompt(
        "selection_mapping_v3",
        slots={
            "scene_brief": "Library hall",
            "player_input": "I want to study",
            "input_policy_flag": False,
            "visible_choices_json": json.dumps([{"choice_id": "c1", "text": "Study"}]),
            "available_fallbacks_json": json.dumps([{"fallback_id": "fb_no_match", "reason_code": "NO_MATCH"}]),
            "confidence_policy_json": '{"high":0.65,"low":0.45}',
            "retry_context_json": "{}",
        },
    )
    assert "strict RPG free-input selector" in system_prompt
    assert "visible_choices=" in user_prompt
    assert "available_fallbacks=" in user_prompt
