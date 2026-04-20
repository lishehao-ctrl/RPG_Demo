from __future__ import annotations

import json
from pathlib import Path

from tools.urban_author_play_benchmarks.gold_eval_full_runner import (
    DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS,
    DEFAULT_HEAVY_TIMEOUT_SECONDS,
    DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS,
    DEFAULT_STANDARD_TIMEOUT_SECONDS,
    parse_args,
    run_gold_eval_full,
)
from tools.urban_author_play_benchmarks.gold_set import burst_pressure_realistic_20, v1_topic_gold_realistic_10


def test_gold_eval_full_runner_uses_standard_profile_defaults(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _fake_run_case_catalog_live_eval(
        output_dir,
        *,
        case_catalog,
        enable_llm_text_audit=True,
        case_timeout_seconds=None,
        case_aggregate_timeout_seconds=None,
        session_play_eval_timeout_seconds=None,
        **kwargs,
    ):  # noqa: ANN001, ANN201
        observed["case_count"] = len(case_catalog)
        observed["timeout"] = case_timeout_seconds
        observed["aggregate_timeout"] = case_aggregate_timeout_seconds
        observed["session_eval_timeout"] = session_play_eval_timeout_seconds
        observed["llm"] = enable_llm_text_audit
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return {
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": {"cases": [{"case_id": "c1", "avg_turn_intent_binding": 4.0}]},
            "llm_text_audit_summary": {"cases": [{"case_id": "c1", "avg_turn_character_specificity": 4.0}]},
            "persona_coverage_summary": {
                "invalid_case_count": 0,
                "quality_invalid_case_count": 0,
                "avg_successful_persona_count": 5.0,
                "avg_turns_successful_personas": 15.0,
            },
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.gold_eval_runner_common.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    result = run_gold_eval_full(tmp_path, profile="standard")

    assert observed["case_count"] == len(v1_topic_gold_realistic_10())
    assert observed["timeout"] == DEFAULT_STANDARD_TIMEOUT_SECONDS
    assert observed["llm"] is True
    assert result["run_manifest"]["suite_type"] == "full"
    assert result["run_manifest"]["profile"] == "standard"
    assert result["run_manifest"]["case_count"] == len(v1_topic_gold_realistic_10())
    assert result["run_manifest"]["timeout_seconds"] == DEFAULT_STANDARD_TIMEOUT_SECONDS
    assert result["run_manifest"]["case_aggregate_timeout_seconds"] == DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS
    assert result["run_manifest"]["session_play_eval_timeout_seconds"] == DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS
    assert result["run_manifest"]["gold_set_profile_version"] == "super_flagship_v3"
    assert result["run_manifest"]["gold_set_band_distribution"] == {"15_20": 2, "20_25": 3, "30_45": 5}
    assert result["run_manifest"]["gold_set_experience_band_distribution"] == {"5_8": 0, "8_15": 0, "15_25": 10}
    assert result["run_manifest"]["metric_contract_version"] == 2
    assert result["run_manifest"]["quantile_granularity"] == "global_and_shell"
    assert result["run_manifest"]["strict_no_repair_fallback_enabled"] is True
    assert observed["aggregate_timeout"] == DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS
    assert observed["session_eval_timeout"] == DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS
    assert (tmp_path / "performance_summary.json").exists()
    persona_coverage_summary = json.loads((tmp_path / "persona_coverage_summary.json").read_text())
    assert persona_coverage_summary["avg_turns_successful_personas_target"] == 14
    assert persona_coverage_summary["avg_turns_successful_personas_target_met"] is True


def test_gold_eval_full_runner_heavy_profile_uses_20_cases_and_default_timeout(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _fake_run_case_catalog_live_eval(
        output_dir,
        *,
        case_catalog,
        enable_llm_text_audit=True,
        case_timeout_seconds=None,
        case_aggregate_timeout_seconds=None,
        session_play_eval_timeout_seconds=None,
        **kwargs,
    ):  # noqa: ANN001, ANN201
        observed["case_count"] = len(case_catalog)
        observed["timeout"] = case_timeout_seconds
        observed["aggregate_timeout"] = case_aggregate_timeout_seconds
        observed["session_eval_timeout"] = session_play_eval_timeout_seconds
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return {
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": {"cases": [{"case_id": "c1", "avg_turn_intent_binding": 4.0}]},
            "llm_text_audit_summary": {"cases": [{"case_id": "c1", "avg_turn_character_specificity": 4.0}]},
            "persona_coverage_summary": {
                "invalid_case_count": 0,
                "quality_invalid_case_count": 0,
                "avg_successful_persona_count": 5.0,
                "avg_turns_successful_personas": 14.0,
            },
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.gold_eval_runner_common.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    result = run_gold_eval_full(tmp_path, profile="heavy")

    assert observed["case_count"] == len(burst_pressure_realistic_20())
    assert observed["timeout"] == DEFAULT_HEAVY_TIMEOUT_SECONDS
    assert result["run_manifest"]["profile"] == "heavy"
    assert result["run_manifest"]["case_count"] == len(burst_pressure_realistic_20())
    assert result["run_manifest"]["timeout_seconds"] == DEFAULT_HEAVY_TIMEOUT_SECONDS
    assert result["run_manifest"]["case_aggregate_timeout_seconds"] == DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS
    assert result["run_manifest"]["session_play_eval_timeout_seconds"] == DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS
    assert result["run_manifest"]["gold_set_profile_version"] == "super_flagship_v3"
    assert result["run_manifest"]["gold_set_band_distribution"] == {"15_20": 4, "20_25": 6, "30_45": 10}
    assert result["run_manifest"]["gold_set_experience_band_distribution"] == {"5_8": 0, "8_15": 0, "15_25": 20}
    assert result["run_manifest"]["metric_contract_version"] == 2
    assert result["run_manifest"]["quantile_granularity"] == "global_and_shell"
    assert result["run_manifest"]["strict_no_repair_fallback_enabled"] is True
    assert observed["aggregate_timeout"] == DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS
    assert observed["session_eval_timeout"] == DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS
    persisted = json.loads((tmp_path / "run_manifest.json").read_text())
    assert persisted["profile"] == "heavy"
    play_eval_summary = json.loads((tmp_path / "play_eval_summary.json").read_text())
    assert "quality_quantiles" in play_eval_summary
    assert "avg_turn_intent_binding" not in json.dumps(play_eval_summary, ensure_ascii=False)
    persona_coverage_summary = json.loads((tmp_path / "persona_coverage_summary.json").read_text())
    assert persona_coverage_summary["avg_turns_successful_personas_target"] == 15
    assert persona_coverage_summary["avg_turns_successful_personas_target_met"] is False


def test_gold_eval_full_runner_rejects_legacy_narration_profile_switch(tmp_path) -> None:
    try:
        parse_args(
            [
                "--output-dir",
                str(tmp_path),
                "--narration-profile",
                "baseline",
            ]
        )
        assert False, "expected argparse failure for legacy narration-profile flag"
    except SystemExit:
        pass
