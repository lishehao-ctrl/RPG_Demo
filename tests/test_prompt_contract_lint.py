import json
from pathlib import Path

from app.modules.llm.prompts import (
    build_story_narration_prompt,
    build_story_selection_prompt,
)


def test_narration_prompt_has_no_sentence_count_conflict() -> None:
    prompt = build_story_narration_prompt({"input_mode": "free_input", "selection_resolution": {"fallback_used": False}})
    assert "2-4 concise sentences" in prompt
    assert "exactly 2 concise sentences" not in prompt


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
    play_cases = json.loads(Path("tests/prompt_fixtures/play_cases.json").read_text(encoding="utf-8"))
    assert isinstance(play_cases, list)
    assert len(play_cases) == 30
