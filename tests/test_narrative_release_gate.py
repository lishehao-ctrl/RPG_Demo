from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
    assert config.db_path is None


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


def test_documented_narrative_release_gate_script_runs_from_repo_root(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output_path = tmp_path / "release_gate.json"

    result = subprocess.run(
        [
            sys.executable,
            "tools/narrative_release_gate.py",
            "--mode",
            "fake",
            "--output-path",
            str(output_path),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text())
    assert payload["ok"] is True
