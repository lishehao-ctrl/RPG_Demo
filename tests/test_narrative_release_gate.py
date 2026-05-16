from __future__ import annotations

from tools.narrative_release_gate import (
    DEFAULT_FIRST_TURN_INPUT,
    DEFAULT_SEED,
    NarrativeReleaseGateConfig,
    parse_args,
    run_release_gate,
)


def test_parse_narrative_release_gate_defaults() -> None:
    config = parse_args([])

    assert config.mode == "fake"
    assert config.seed == DEFAULT_SEED
    assert config.first_turn_input == DEFAULT_FIRST_TURN_INPUT
    assert config.db_path.name == "narrative.sqlite3"


def test_fake_narrative_release_gate_covers_current_core(tmp_path) -> None:
    summary = run_release_gate(
        NarrativeReleaseGateConfig(
            mode="fake",
            db_path=tmp_path / "narrative.sqlite3",
            seed=DEFAULT_SEED,
            first_turn_input=DEFAULT_FIRST_TURN_INPUT,
            output_path=None,
        )
    )

    assert summary["ok"] is True
    assert all(summary["contracts"].values())
    assert summary["replay"]["completed"] is True
    assert summary["replay"]["message_count"] >= 9
    assert summary["replay"]["advisor_message_count"] == 2
    assert summary["replay"]["highlight_count"] >= 2
    assert summary["replay"]["branch_count"] >= 2
    assert summary["distribution"]["total_completed"] == 1

    operations = summary["llm_operations"]
    assert operations[0] == "narrative.opening"
    assert operations.count("narrative.advance_turn") == 4
    assert "narrative.advisor" in operations
    assert "narrative.ending" in operations
    assert "narrative.highlights" in operations
    assert "narrative.branches" in operations
