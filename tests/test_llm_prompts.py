from app.config import settings
from app.modules.llm.prompts import (
    build_author_assist_envelope,
    build_author_cast_expand_envelope,
    build_author_cast_expand_prompt,
    build_author_idea_expand_prompt,
    build_author_idea_expand_envelope,
    build_author_idea_repair_prompt,
    build_author_assist_prompt,
    build_author_assist_repair_prompt,
    build_author_story_build_prompt,
    build_author_story_build_envelope,
    build_fallback_polish_prompt,
    build_narrative_repair_prompt,
    build_story_narration_envelope,
    build_story_narration_prompt,
    build_story_selection_envelope,
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
            "state_snapshot_before": {"energy": 80, "quest_state": {"huge": "blob"}},
            "state_snapshot_after": {"energy": 70},
            "state_delta": {"energy": -10, "knowledge": 2, "quest_state": {"x": 1}},
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
    assert "sentence 1 should paraphrase player_input_raw in world language" in prompt
    assert "Use grounded cinematic second-person voice" in prompt
    assert "Use cause -> consequence ordering" in prompt
    assert "Causal policy is strict_separation" in prompt
    assert "Mismatch rule: do not frame intent as fully completed" in prompt
    assert "Event layering rule: if runtime_event is present" in prompt
    assert "Quest nudge suppression rule: skip quest-direction hints on event-present turns" in prompt
    assert "Soft-avoid system jargon in narrative_text" in prompt
    assert "Do not quote player_input_raw verbatim" in prompt
    assert "use at most one short numeric mention" in prompt
    assert '"quest_nudge"' in prompt
    assert '"impact_sources"' in prompt
    assert '"event_present":true' in prompt
    assert "maps to selected_action_id" not in prompt
    assert '"input_mode":"free_input"' in prompt
    assert '"impact_brief"' in prompt
    assert "quest_state" not in prompt
    assert "Context:" in prompt


def test_build_narrative_repair_prompt_requires_json_only_schema() -> None:
    prompt = build_narrative_repair_prompt("bad raw")
    assert "Narrative repair task" in prompt
    assert '{"narrative_text":"string"}' in prompt
    assert "Return JSON only" in prompt
    assert "Source:" in prompt


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
    assert "Sentence 1 should acknowledge the player's attempted intent in-world" in prompt
    assert "Sentence 2 should describe the action that actually happens and its immediate consequence" in prompt
    assert "Keep strict separation between intent acknowledgment and executed-result causality" in prompt
    assert "If event_present is true, treat runtime_event as an additional beat" in prompt
    assert "When intent_action_alignment is mismatch, use a bridge phrase" in prompt
    assert "Use clear cause -> consequence flow" in prompt
    assert "keep at most one subtle in-world hint and avoid task-log narration" in prompt
    assert "Do NOT use labels like main quest, side quest, objective, stage, or milestone" in prompt
    assert "Do not quote or copy the player input verbatim" in prompt
    assert "Soft-avoid system-like phrasing such as for this turn, the scene, and story keeps moving" in prompt
    assert "Narrative-first numbers rule: use world-language first and at most one short numeric mention" in prompt
    assert "Do NOT use rejecting phrasing such as fuzzy, unclear, invalid" in prompt
    assert '"impact_sources"' in prompt
    assert "choices:[{id,text,type(dialog|action)}]" not in prompt


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


def test_build_author_assist_prompt_mentions_incremental_tasks_and_context_controls() -> None:
    prompt = build_author_assist_prompt(
        task="continue_write",
        locale="en",
        context={
            "operation": "append",
            "target_scope": "scene",
            "target_scene_key": "scene_intro",
            "target_option_key": "opt_1",
            "preserve_existing": True,
        },
    )
    assert '{"suggestions":object,"patch_preview":array,"warnings":array}' in prompt
    assert "Task=continue_write: append one playable follow-up scene after decision gate" in prompt
    assert "Return JSON only, no markdown fences, no extra top-level keys." in prompt
    assert "Treat suggestions as patch candidates only; never assume persistence." in prompt
    assert "Honor context.operation, context.target_scope, context.target_scene_key, context.target_option_key" in prompt


def test_build_author_assist_prompt_compacts_large_context_payload() -> None:
    huge_note = "x" * 6000
    prompt = build_author_assist_prompt(
        task="seed_expand",
        locale="en",
        context={
            "operation": "append",
            "target_scope": "scene",
            "target_scene_key": "scene_04",
            "seed_text": huge_note,
            "global_brief": huge_note,
            "source_text": huge_note,
            "writer_journal": [
                {"turn_id": f"turn_{idx}", "phase": "expand", "author_text": huge_note, "assistant_text": huge_note}
                for idx in range(12)
            ],
            "draft": {
                "meta": {"story_id": "s1", "title": huge_note, "locale": "en"},
                "plot": {"mainline_goal": huge_note},
                "flow": {
                    "start_scene_key": "scene_01",
                    "scenes": [
                        {
                            "scene_key": f"scene_{idx:02d}",
                            "title": huge_note,
                            "setup": huge_note,
                            "options": [
                                {"option_key": f"opt_{opt_idx}", "label": huge_note, "action_type": "study", "go_to": "scene_02"}
                                for opt_idx in range(8)
                            ],
                        }
                        for idx in range(16)
                    ],
                },
            },
        },
    )
    assert len(prompt) < 20000
    assert '"target_scene_key":"scene_04"' in prompt
    assert '"writer_journal"' in prompt
    # The full 6000-char source should be compacted.
    assert huge_note not in prompt


def test_build_author_assist_repair_prompt_requires_assist_schema() -> None:
    prompt = build_author_assist_repair_prompt("raw payload")
    assert "Author-assist repair task" in prompt
    assert '{"suggestions":object,"patch_preview":array,"warnings":array}' in prompt
    assert "patch_preview entries must contain keys: id, path, label, value" in prompt


def test_build_author_idea_expand_prompt_requires_blueprint_schema() -> None:
    prompt = build_author_idea_expand_prompt(
        task="seed_expand",
        locale="en",
        context={"seed_text": "Roommate conflict and scholarship deadline."},
    )
    assert "Author idea expansion task." in prompt
    assert '{"core_conflict":object,"tension_loop_plan":object,"branch_design":object,"lexical_anchors":object}' in prompt
    assert "pressure_open, pressure_escalation, recovery_window, decision_gate" in prompt
    assert "branch_design must include high_risk_push and recovery_stabilize" in prompt


def test_build_author_cast_expand_prompt_requires_cast_schema() -> None:
    prompt = build_author_cast_expand_prompt(
        task="seed_expand",
        locale="en",
        context={
            "seed_text": "Roommate conflict and scholarship deadline.",
            "draft": {
                "characters": {
                    "protagonist": {"name": "You", "role": "student", "traits": ["driven"]},
                    "npcs": [{"name": "Alice", "role": "friend", "traits": ["kind"]}],
                    "relationship_axes": {"trust": "kept promises"},
                }
            },
        },
        idea_blueprint={
            "core_conflict": {
                "protagonist": "student",
                "opposition_actor": "roommate",
                "scarce_resource": "scholarship",
                "deadline": "one week",
                "irreversible_risk": "lose funding",
            },
            "tension_loop_plan": {},
            "branch_design": {},
            "lexical_anchors": {},
        },
    )
    assert "Author cast expansion task." in prompt
    assert '{"target_npc_count":integer,"npc_roster":array,"beat_presence":object}' in prompt
    assert "Role mix must include at least two of: support, rival, gatekeeper." in prompt
    assert '"characters"' in prompt
    assert '"npcs"' in prompt


def test_build_author_idea_repair_prompt_requires_blueprint_schema() -> None:
    prompt = build_author_idea_repair_prompt("raw blueprint")
    assert "Author idea repair task." in prompt
    assert '{"core_conflict":object,"tension_loop_plan":object,"branch_design":object,"lexical_anchors":object}' in prompt
    assert "Required beats in tension_loop_plan" in prompt


def test_build_author_story_build_prompt_embeds_blueprint_and_structure_contract() -> None:
    prompt = build_author_story_build_prompt(
        task="seed_expand",
        locale="en",
        context={"seed_text": "Roommate conflict and scholarship deadline."},
        idea_blueprint={
            "core_conflict": {
                "protagonist": "student",
                "opposition_actor": "roommate",
                "scarce_resource": "scholarship",
                "deadline": "one week",
                "irreversible_risk": "lose funding",
            },
            "tension_loop_plan": {
                "pressure_open": {"objective": "open", "stakes": "high", "required_entities": ["student"], "risk_level": 3},
                "pressure_escalation": {"objective": "escalate", "stakes": "higher", "required_entities": ["roommate"], "risk_level": 4},
                "recovery_window": {"objective": "recover", "stakes": "tempo", "required_entities": ["student"], "risk_level": 2},
                "decision_gate": {"objective": "decide", "stakes": "final", "required_entities": ["scholarship"], "risk_level": 5},
            },
            "branch_design": {
                "high_risk_push": {
                    "short_term_gain": "fast clarity",
                    "long_term_cost": "relationship damage",
                    "signature_action_type": "study",
                },
                "recovery_stabilize": {
                    "short_term_gain": "stability",
                    "long_term_cost": "lost tempo",
                    "signature_action_type": "rest",
                },
            },
            "lexical_anchors": {
                "must_include_terms": ["roommate", "scholarship"],
                "avoid_generic_labels": ["Option A"],
            },
        },
    )
    assert "Author story build task." in prompt
    assert '{"suggestions":object,"patch_preview":array,"warnings":array}' in prompt
    assert "Use idea_blueprint as mandatory creative constraints" in prompt
    assert "preserve existing NPC names" in prompt
    assert "Task context:" in prompt
    assert '"idea_blueprint"' in prompt


def test_story_selection_envelope_includes_messages_and_schema() -> None:
    envelope = build_story_selection_envelope(
        player_input="study now",
        valid_choice_ids=["c1", "c2"],
        visible_choices=[{"choice_id": "c1", "display_text": "Study"}, {"choice_id": "c2", "display_text": "Rest"}],
        intents=[],
        state_snippet={"day": 1, "energy": 80},
    )
    assert envelope.schema_name == "story_selection_v1"
    messages = envelope.to_messages()
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "Story selection task." in messages[1]["content"]


def test_story_narration_envelope_includes_messages_and_schema() -> None:
    envelope = build_story_narration_envelope(
        {
            "input_mode": "choice_click",
            "selection_resolution": {"fallback_used": False, "selected_action_id": "study", "executed_choice_id": "c1"},
            "node_transition": {"from_node_id": "n1", "to_node_id": "n2"},
        }
    )
    assert envelope.schema_name == "story_narrative_v1"
    assert isinstance(envelope.schema_payload, dict)
    messages = envelope.to_messages()
    assert len(messages) == 2
    assert messages[0]["role"] == "system"


def test_author_envelopes_include_expected_schema() -> None:
    idea = build_author_idea_expand_envelope(task="seed_expand", locale="en", context={"seed_text": "deadline conflict"})
    build = build_author_story_build_envelope(
        task="continue_write",
        locale="en",
        context={"continue_input": "add fallout"},
        idea_blueprint={"core_conflict": {}, "tension_loop_plan": {}, "branch_design": {}, "lexical_anchors": {}},
    )
    cast = build_author_cast_expand_envelope(
        task="seed_expand",
        locale="en",
        context={"seed_text": "deadline conflict"},
        idea_blueprint={"core_conflict": {}, "tension_loop_plan": {}, "branch_design": {}, "lexical_anchors": {}},
    )
    assist = build_author_assist_envelope(task="trim_content", locale="en", context={"target_scope": "scene"})
    assert idea.schema_name == "author_idea_blueprint_v1"
    assert cast.schema_name == "author_cast_blueprint_v1"
    assert build.schema_name == "author_assist_payload_v1"
    assert assist.schema_name == "author_assist_payload_v1"
    assert "Task=continue_write" in build.user_text
    assert "Task=trim_content" in assist.user_text


def test_two_stage_author_prompts_respect_char_budget() -> None:
    huge_text = "x" * 10000
    context = {
        "seed_text": huge_text,
        "global_brief": huge_text,
        "source_text": huge_text,
        "writer_journal": [{"turn_id": "t1", "phase": "expand", "author_text": huge_text, "assistant_text": huge_text}] * 12,
        "draft": {
            "flow": {
                "start_scene_key": "s1",
                "scenes": [
                    {
                        "scene_key": f"s{i}",
                        "title": huge_text,
                        "setup": huge_text,
                        "options": [
                            {"option_key": f"o{j}", "label": huge_text, "action_type": "study", "go_to": "s2"}
                            for j in range(8)
                        ],
                    }
                    for i in range(20)
                ],
            }
        },
    }
    stage1 = build_author_idea_expand_prompt(task="seed_expand", locale="en", context=context)
    stage2 = build_author_story_build_prompt(
        task="seed_expand",
        locale="en",
        context=context,
        idea_blueprint={"core_conflict": {}, "tension_loop_plan": {}, "branch_design": {}, "lexical_anchors": {}},
    )
    assert len(stage1) <= int(settings.llm_prompt_author_max_chars)
    assert len(stage2) <= int(settings.llm_prompt_author_max_chars)
