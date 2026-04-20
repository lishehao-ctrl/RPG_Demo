from __future__ import annotations

import json
import os
from pathlib import Path

from tools.urban_author_play_benchmarks.gold_eval_mini_runner import (
    DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS,
    DEFAULT_CASE_MAX_WORKERS,
    DEFAULT_CASE_TIMEOUT_SECONDS,
    DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS,
    DEFAULT_TOTAL_RPM_LIMIT,
    parse_args,
    run_gold_eval_mini,
)
from tools.urban_author_play_benchmarks.gold_set import mini_gold_realistic_6


def test_gold_eval_mini_runner_forces_llm_audit_and_writes_manifest(tmp_path, monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _fake_run_case_catalog_live_eval(
        output_dir,
        *,
        case_catalog,
        case_set_filename,
        blockers_filename,
        blockers_title,
        enable_llm_text_audit=True,
        case_max_workers=None,
        case_timeout_seconds=None,
        case_aggregate_timeout_seconds=None,
        session_play_eval_timeout_seconds=None,
        **kwargs,
    ):  # noqa: ANN001, ANN201
        observed["enable_llm_text_audit"] = enable_llm_text_audit
        observed["case_count"] = len(case_catalog)
        observed["case_max_workers"] = case_max_workers
        observed["case_timeout_seconds"] = case_timeout_seconds
        observed["case_aggregate_timeout_seconds"] = case_aggregate_timeout_seconds
        observed["session_play_eval_timeout_seconds"] = session_play_eval_timeout_seconds
        observed["rpm_env"] = (
            os.environ.get("APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE"),
            os.environ.get("APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE"),
            os.environ.get("APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE"),
            os.environ.get("APP_RESPONSES_GLOBAL_REQUESTS_PER_MINUTE"),
            os.environ.get("APP_RESPONSES_GLOBAL_RATE_LIMIT_SCOPE"),
        )
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / case_set_filename).write_text("[]")
        (Path(output_dir) / blockers_filename).write_text(f"# {blockers_title}\n")
        return {
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": {"cases": [{"case_id": "c1", "avg_turn_intent_binding": 4.0}]},
            "llm_text_audit_summary": {"cases": [{"case_id": "c1", "avg_turn_character_specificity": 4.0}]},
            "persona_coverage_summary": {
                "invalid_case_count": 0,
                "quality_invalid_case_count": 0,
                "avg_successful_persona_count": 5.0,
                "avg_turns_successful_personas": 13.0,
            },
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.gold_eval_runner_common.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    result = run_gold_eval_mini(tmp_path)

    assert result["run_manifest"]["suite_type"] == "mini"
    assert result["run_manifest"]["profile"] == "mini"
    assert result["run_manifest"]["case_count"] == len(mini_gold_realistic_6())
    assert result["run_manifest"]["workers"] == DEFAULT_CASE_MAX_WORKERS
    assert result["run_manifest"]["rpm"] == DEFAULT_TOTAL_RPM_LIMIT
    assert result["run_manifest"]["timeout_seconds"] == DEFAULT_CASE_TIMEOUT_SECONDS
    assert result["run_manifest"]["total_rpm_limit"] == DEFAULT_TOTAL_RPM_LIMIT
    assert result["run_manifest"]["case_timeout_seconds"] == DEFAULT_CASE_TIMEOUT_SECONDS
    assert result["run_manifest"]["case_aggregate_timeout_seconds"] == DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS
    assert result["run_manifest"]["session_play_eval_timeout_seconds"] == DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS
    assert result["run_manifest"]["llm_text_audit_forced"] is True
    assert result["run_manifest"]["intent_compiler_llm_enabled"] is True
    assert result["run_manifest"]["micro_sim_llm_enabled"] is True
    assert result["run_manifest"]["micro_sim_max_candidates"] == 5
    assert result["run_manifest"]["gold_set_profile_version"] == "super_flagship_v3"
    assert result["run_manifest"]["gold_set_band_distribution"] == {"15_20": 1, "20_25": 2, "30_45": 3}
    assert result["run_manifest"]["gold_set_experience_band_distribution"] == {"5_8": 0, "8_15": 0, "15_25": 6}
    assert set(result["run_manifest"]["gold_set_shell_distribution"].keys()) == {
        "campus_romance",
        "entertainment_scandal",
        "office_power",
        "urban_supernatural",
        "wealth_families",
    }
    assert result["run_manifest"]["metric_contract_version"] == 2
    assert result["run_manifest"]["quantile_granularity"] == "global_and_shell"
    assert result["run_manifest"]["strict_no_repair_fallback_enabled"] is True
    assert observed["enable_llm_text_audit"] is True
    assert observed["case_count"] == len(mini_gold_realistic_6())
    assert observed["case_max_workers"] == DEFAULT_CASE_MAX_WORKERS
    assert observed["case_timeout_seconds"] == DEFAULT_CASE_TIMEOUT_SECONDS
    assert observed["case_aggregate_timeout_seconds"] == DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS
    assert observed["session_play_eval_timeout_seconds"] == DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS
    assert observed["rpm_env"] == ("300", "300", "300", None, None)
    assert (tmp_path / "run_manifest.json").exists()
    assert (tmp_path / "effect_report.md").exists()
    assert (tmp_path / "performance_summary.json").exists()
    persisted = json.loads((tmp_path / "run_manifest.json").read_text())
    assert persisted["llm_text_audit_forced"] is True
    assert persisted["gold_set_profile_version"] == "super_flagship_v3"
    play_eval_summary = json.loads((tmp_path / "play_eval_summary.json").read_text())
    assert "quality_quantiles" in play_eval_summary
    assert "avg_turn_intent_binding" not in json.dumps(play_eval_summary, ensure_ascii=False)
    llm_summary = json.loads((tmp_path / "llm_text_audit_summary.json").read_text())
    assert "quality_quantiles" in llm_summary
    persona_coverage_summary = json.loads((tmp_path / "persona_coverage_summary.json").read_text())
    assert persona_coverage_summary["avg_turns_successful_personas_target"] == 12
    assert persona_coverage_summary["avg_turns_successful_personas_target_met"] is True


def test_gold_eval_mini_runner_rejects_legacy_llm_switch(tmp_path) -> None:
    try:
        parse_args(
            [
                "--output-dir",
                str(tmp_path),
                "--enable-llm-text-audit",
            ]
        )
        assert False, "expected argparse failure for legacy flag"
    except SystemExit:
        pass


def test_gold_eval_mini_runner_rejects_legacy_narration_profile_switch(tmp_path) -> None:
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
