from __future__ import annotations

from app.modules.narrative.ending_engine import resolve_run_ending
from app.modules.narrative.state_engine import default_initial_state, normalize_state


def test_ending_priority_and_tie_break_are_deterministic() -> None:
    endings = [
        {
            "ending_id": "ending_b",
            "title": "B",
            "priority": 10,
            "outcome": "neutral",
            "trigger": {"node_id_is": "n2"},
            "epilogue": "B epilogue",
        },
        {
            "ending_id": "ending_a",
            "title": "A",
            "priority": 10,
            "outcome": "success",
            "trigger": {"node_id_is": "n2"},
            "epilogue": "A epilogue",
        },
    ]

    result = resolve_run_ending(
        endings_def=endings,
        run_config={"max_days": 7, "max_steps": 24, "default_timeout_outcome": "neutral"},
        run_state={"step_index": 3},
        next_node_id="n2",
        state_after=normalize_state(default_initial_state()),
        quest_state={"completed_quests": []},
    )
    assert result.run_ended is True
    assert result.ending_id == "ending_a"
    assert result.ending_outcome == "success"


def test_ending_timeout_fallback_uses_run_config() -> None:
    result = resolve_run_ending(
        endings_def=[],
        run_config={"max_days": 7, "max_steps": 2, "default_timeout_outcome": "fail"},
        run_state={"step_index": 2},
        next_node_id="n2",
        state_after=normalize_state(default_initial_state()),
        quest_state={"completed_quests": []},
    )
    assert result.run_ended is True
    assert result.ending_id == "__timeout__"
    assert result.ending_outcome == "fail"


def test_ending_trigger_requires_completed_quests() -> None:
    endings = [
        {
            "ending_id": "ending_secret",
            "title": "Secret",
            "priority": 1,
            "outcome": "success",
            "trigger": {"completed_quests_include": ["q_secret"]},
            "epilogue": "Secret ending",
        }
    ]

    missing = resolve_run_ending(
        endings_def=endings,
        run_config={"max_days": 10, "max_steps": 50, "default_timeout_outcome": "neutral"},
        run_state={"step_index": 1},
        next_node_id="n2",
        state_after=normalize_state(default_initial_state()),
        quest_state={"completed_quests": []},
    )
    assert missing.run_ended is False

    hit = resolve_run_ending(
        endings_def=endings,
        run_config={"max_days": 10, "max_steps": 50, "default_timeout_outcome": "neutral"},
        run_state={"step_index": 1},
        next_node_id="n2",
        state_after=normalize_state(default_initial_state()),
        quest_state={"completed_quests": ["q_secret"]},
    )
    assert hit.run_ended is True
    assert hit.ending_id == "ending_secret"

