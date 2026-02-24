import json
from pathlib import Path

from app.modules.llm.prompts import (
    build_author_assist_prompt,
    build_author_cast_expand_prompt,
    build_author_story_build_prompt,
    build_story_narration_prompt,
    build_story_selection_prompt,
)


def test_narration_prompt_has_no_sentence_count_conflict() -> None:
    prompt = build_story_narration_prompt({"input_mode": "free_input", "selection_resolution": {"fallback_used": False}})
    assert "2-4 concise sentences" in prompt
    assert "exactly 2 concise sentences" not in prompt


def test_author_prompt_includes_only_task_specific_rule_for_continue_write() -> None:
    prompt = build_author_assist_prompt(
        task="continue_write",
        locale="en",
        context={"continue_input": "add one follow-up", "target_scene_key": "decision_gate"},
    )
    assert "Task=continue_write" in prompt
    assert "Task=trim_content" not in prompt
    assert "Task=spice_branch" not in prompt


def test_author_build_prompt_includes_only_task_specific_rule_for_seed_expand() -> None:
    prompt = build_author_story_build_prompt(
        task="seed_expand",
        locale="en",
        context={"seed_text": "deadline conflict"},
        idea_blueprint={"core_conflict": {}, "tension_loop_plan": {}, "branch_design": {}, "lexical_anchors": {}},
    )
    assert "Task=seed_expand" in prompt
    assert "Task=continue_write" not in prompt
    assert "Task=trim_content" not in prompt


def test_author_cast_prompt_mentions_strict_cast_contract() -> None:
    prompt = build_author_cast_expand_prompt(
        task="seed_expand",
        locale="en",
        context={"seed_text": "deadline conflict"},
        idea_blueprint={"core_conflict": {}, "tension_loop_plan": {}, "branch_design": {}, "lexical_anchors": {}},
    )
    assert "Author cast expansion task." in prompt
    assert "target_npc_count must be between 3 and 6." in prompt
    assert "beat_presence must include pressure_open" in prompt


def test_selection_prompt_keeps_schema_contract_keyword() -> None:
    prompt = build_story_selection_prompt(
        player_input="study",
        valid_choice_ids=["c1", "c2"],
        visible_choices=[{"choice_id": "c1", "display_text": "Study"}, {"choice_id": "c2", "display_text": "Rest"}],
        intents=[],
        state_snippet={"story_node_id": "n1"},
    )
    assert "Return JSON only with schema" in prompt
    assert "use_fallback" in prompt


def test_prompt_fixture_case_counts_are_locked() -> None:
    author_cases = json.loads(Path("tests/prompt_fixtures/author_cases.json").read_text(encoding="utf-8"))
    play_cases = json.loads(Path("tests/prompt_fixtures/play_cases.json").read_text(encoding="utf-8"))
    assert isinstance(author_cases, list)
    assert isinstance(play_cases, list)
    assert len(author_cases) == 30
    assert len(play_cases) == 30
