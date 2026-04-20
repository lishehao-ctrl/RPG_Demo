from __future__ import annotations

from pathlib import Path

import pytest

from tools.urban_author_play_benchmarks.play_eval_recompute_runner import (
    _build_play_eval_ab_summary,
    parse_args,
    recompute_v1_topic_play_eval,
)


def _assembled_v2_payload() -> dict[str, dict[str, object]]:
    return {
        "npc_texture_v2": {
            "author_summary": {
                "config": {
                    "play_v2_narration_profile": "npc_texture_v2",
                }
            },
            "play_eval_summary": {
                "cases": [
                    {
                        "case_id": "case_001",
                        "avg_strategic_tension_curve": 3.0,
                        "avg_consequence_legibility": 3.1,
                        "avg_payoff_realization": 3.2,
                        "avg_npc_interest_divergence": 3.3,
                        "avg_control_tradeoff_quality": 3.4,
                        "avg_shell_system_activation": 3.5,
                        "avg_ending_cost_integrity": 3.6,
                        "avg_replay_variance": 3.7,
                        "avg_turn_consequence_impact": 3.8,
                        "avg_turn_intent_binding": 3.9,
                    }
                ],
                "top_flags": {"模板味偏重": 1},
            },
        }
    }


def test_play_eval_recompute_summary_is_mainline_only() -> None:
    summary = _build_play_eval_ab_summary(_assembled_v2_payload())

    assert summary["mainline_variant"] == "npc_texture_v2"
    assert summary["comparisons"] == {}
    assert summary["mainline"]["play_v2_narration_profile"] == "npc_texture_v2"
    assert summary["mainline"]["avg_control_tradeoff_quality"] == 3.4


def test_play_eval_recompute_runner_rejects_legacy_variant_cli_flag(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--output-dir", str(tmp_path), "--variant", "baseline"])


def test_play_eval_recompute_runner_rejects_non_v2_variant_programmatic(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported variants"):
        recompute_v1_topic_play_eval(
            tmp_path,
            case_catalog=[],
            variants=("baseline",),
        )
