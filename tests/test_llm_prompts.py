from app.modules.llm.prompts import (
    build_fallback_polish_prompt,
    build_narrative_repair_prompt,
    build_story_narration_prompt,
    build_story_selection_prompt,
)


def test_build_story_narration_prompt_requires_json_only_schema() -> None:
    prompt = build_story_narration_prompt(
        {
            "input_mode": "free_input",
            "player_input_raw": "study hard tonight",
            "causal_policy": "strict_separation",
            "intent_action_alignment": "mismatch",
            "node_transition": {"from_node_id": "n1", "to_node_id": "n2", "from_scene": "start", "to_scene": "class"},
            "selection_resolution": {
                "attempted_choice_id": "c1",
                "executed_choice_id": "c1",
                "resolved_choice_id": "c1",
                "selected_choice_label": "Study at library",
                "selected_action_id": "study",
                "fallback_used": False,
                "mapping_confidence": 0.9,
            },
            "state_snapshot_before": {"energy": 80},
            "state_snapshot_after": {"energy": 70},
            "state_delta": {"energy": -10, "knowledge": 2},
            "impact_brief": ["energy -10", "knowledge +2"],
            "impact_sources": {
                "action_effects": {"energy": -15, "money": 20},
                "event_effects": {"money": 6, "energy": -5},
                "total_effects": {"energy": -20, "money": 26},
            },
            "event_present": True,
            "runtime_event": {
                "event_id": "ev_side_job",
                "title": "Flash Side Job",
                "effects": {"money": 6, "energy": -5},
            },
            "quest_nudge": {
                "enabled": False,
                "mode": "off",
                "mainline_hint": "the week's plan still has a clear next step",
                "sideline_hint": "a smaller opportunity still lingers at the edge of your day",
            },
            "quest_nudge_suppressed_by_event": True,
        }
    )
    assert "Return JSON only" in prompt
    assert '{"narrative_text":"string"}' in prompt
    assert "No markdown code fences" in prompt
    assert "Use grounded cinematic second-person voice" in prompt
    assert '"impact_sources"' in prompt


def test_build_narrative_repair_prompt_requires_json_only_schema() -> None:
    prompt = build_narrative_repair_prompt("bad raw")
    assert "Narrative repair task" in prompt
    assert '{"narrative_text":"string"}' in prompt
    assert "Return JSON only" in prompt


def test_build_fallback_polish_prompt_narrative_only_acknowledge_redirect() -> None:
    prompt = build_fallback_polish_prompt(
        {
            "locale": "en",
            "fallback_reason": "FALLBACK",
            "node_id": "n1",
            "player_input": "play rpg with alice",
            "mapping_note": "selector_fallback",
            "causal_policy": "strict_separation",
            "intent_action_alignment": "mismatch",
            "event_present": True,
            "quest_nudge_suppressed_by_event": True,
            "attempted_choice_id": None,
            "attempted_choice_label": None,
            "visible_choices": [{"id": "c1", "label": "Walk with Alice before class"}],
            "impact_sources": {
                "action_effects": {"money": 20, "energy": -15},
                "event_effects": {"money": 6, "energy": -5},
                "total_effects": {"money": 26, "energy": -20},
            },
            "runtime_event": {"event_id": "ev_side_job", "title": "Flash Side Job"},
            "quest_nudge": {
                "enabled": True,
                "mode": "event_driven",
                "mainline_hint": "the week's plan still has a clear next step",
                "sideline_hint": "a smaller opportunity still lingers at the edge of your day",
            },
            "state_snippet": {"energy": 72},
            "short_recent_summary": [],
        },
        "You keep moving through the scene.",
    )
    assert '{"narrative_text":"string"}' in prompt
    assert "exactly 2 concise sentences" in prompt
    assert '"impact_sources"' in prompt


def test_build_story_selection_prompt_compacts_state_and_patterns() -> None:
    prompt = build_story_selection_prompt(
        player_input="study in library",
        valid_choice_ids=["c1", "c2"],
        visible_choices=[
            {"choice_id": "c1", "display_text": "Study"},
            {"choice_id": "c2", "display_text": "Rest"},
        ],
        intents=[
            {
                "intent_id": "INTENT_STUDY",
                "alias_choice_id": "c1",
                "description": "study intent",
                "patterns": ["study", "learn", "library", "notes", "extra_pattern_should_be_trimmed"],
            }
        ],
        state_snippet={
            "story_node_id": "n_day_start",
            "day": 2,
            "slot": "morning",
            "energy": 75,
            "money": 60,
            "knowledge": 5,
            "affection": 0,
            "quest_state": {"large": "ignored"},
            "unknown_field": "ignored",
        },
    )
    assert "extra_pattern_should_be_trimmed" not in prompt
    assert "quest_state" not in prompt
    assert "unknown_field" not in prompt
    assert '"story_node_id":"n_day_start"' in prompt


def test_build_story_selection_prompt_length_is_bounded_for_large_inputs() -> None:
    huge_patterns = [f"pattern_{idx}_{'x' * 80}" for idx in range(20)]
    huge_intents = [
        {
            "intent_id": f"INTENT_{idx}",
            "alias_choice_id": "c1",
            "description": "desc " + ("y" * 120),
            "patterns": huge_patterns,
        }
        for idx in range(20)
    ]
    prompt = build_story_selection_prompt(
        player_input="study hard with long input text",
        valid_choice_ids=[f"c{idx}" for idx in range(50)],
        visible_choices=[
            {"choice_id": f"c{idx}", "display_text": "choice text " + ("z" * 120)}
            for idx in range(50)
        ],
        intents=huge_intents,
        state_snippet={
            "story_node_id": "n_big",
            "day": 3,
            "slot": "afternoon",
            "energy": 70,
            "money": 60,
            "knowledge": 10,
            "affection": 2,
            "quest_state": {"huge": "ignored"},
        },
    )
    assert len(prompt) < 4500
