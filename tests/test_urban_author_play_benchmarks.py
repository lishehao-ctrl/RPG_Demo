from __future__ import annotations

import json

import pytest

from tools.urban_author_play_benchmarks.gold_set import (
    burst_pressure_set,
    burst_pressure_realistic_20,
    mini_gold_set,
    mini_gold_realistic_6,
    native_cn_gold_10,
    native_cn_gold_realistic_14,
    promo_realistic_case_set,
    v1_topic_gold_14,
    v1_topic_gold_realistic_10,
)
from tools.urban_author_play_benchmarks.native_cn_live_eval import _normalize_live_mode, main as native_cn_live_eval_main
from tools.urban_author_play_benchmarks.runner import run_benchmark, run_case, summarize_results


def test_gold_set_runner_writes_artifacts_and_summary(tmp_path) -> None:
    summary = run_benchmark(tmp_path, mini_gold_set(), modes=("deterministic",), include_burst=False, repeat_top=0)

    assert summary["smoke"]["total_cases"] == 8
    assert summary["smoke"]["mode_summaries"]["deterministic"]["passed_cases"] >= 6
    assert (tmp_path / "summary.json").exists()

    first_case = mini_gold_set()[0].case_id
    case_dir = tmp_path / "smoke" / first_case / "deterministic"
    assert (case_dir / "seed.json").exists()
    assert (case_dir / "preview_blueprint.json").exists()
    assert (case_dir / "accepted_blueprint.json").exists()
    assert (case_dir / "cast_slots.json").exists()
    assert (case_dir / "bound_cast.json").exists()
    assert (case_dir / "segment_contracts.json").exists()
    assert (case_dir / "segment_playbooks.json").exists()
    assert (case_dir / "ending_matrix.json").exists()
    assert (case_dir / "urban_bundle.json").exists()
    assert (case_dir / "compiled_play_plan.json").exists()
    assert (case_dir / "smoke_results.json").exists()
    assert (case_dir / "llm_call_trace.json").exists()
    assert (case_dir / "quality_trace.json").exists()

    payload = json.loads((tmp_path / "summary.json").read_text())
    assert payload["smoke"]["mode_summaries"]["deterministic"]["passed_cases"] == summary["smoke"]["mode_summaries"]["deterministic"]["passed_cases"]


def test_burst_pressure_set_has_expected_size() -> None:
    assert len(burst_pressure_set()) == 40


def test_realistic_gold_sets_have_expected_sizes_and_unique_ids() -> None:
    mini_cases = mini_gold_realistic_6()
    native_cases = native_cn_gold_realistic_14()
    full_cases = v1_topic_gold_realistic_10()
    heavy_cases = burst_pressure_realistic_20()

    assert len(mini_cases) == 6
    assert len(native_cases) == 14
    assert len(full_cases) == 10
    assert len(heavy_cases) == 20
    assert len({case.case_id for case in mini_cases}) == len(mini_cases)
    assert len({case.case_id for case in native_cases}) == len(native_cases)
    assert len({case.case_id for case in full_cases}) == len(full_cases)
    assert len({case.case_id for case in heavy_cases}) == len(heavy_cases)


def test_native_cn_gold_10_has_expected_size_and_shell_spread() -> None:
    cases = native_cn_gold_10()

    assert len(cases) == 10
    assert sum(1 for case in cases if case.expected_shell == "campus_romance") == 2
    assert sum(1 for case in cases if case.expected_shell == "urban_supernatural") == 2
    assert any("导师评审周" in case.seed for case in cases)
    assert any("深夜会所外" in case.seed for case in cases)


def test_native_cn_live_eval_normalizes_openai_prompted_alias() -> None:
    assert _normalize_live_mode("openai_prompted") == "pure_gpt"


def test_native_cn_live_eval_rejects_unknown_live_mode_before_run(tmp_path) -> None:
    with pytest.raises(SystemExit, match="已下线"):
        native_cn_live_eval_main(["--output-dir", str(tmp_path), "--live-mode", "unknown_mode"])


def test_promo_realistic_case_set_has_expected_cases() -> None:
    cases = promo_realistic_case_set()

    assert [case.case_id for case in cases] == [
        "wealth_short_wedding",
        "office_standard_boardroom",
        "campus_standard_homecoming",
        "entertainment_standard_awards",
        "wealth_flagship_succession",
        "office_flagship_merger",
    ]


def test_v1_topic_gold_14_has_expected_distribution_and_templates() -> None:
    cases = v1_topic_gold_14()

    assert len(cases) == 14
    assert sum(1 for case in cases if case.expected_shell == "wealth_families") == 4
    assert sum(1 for case in cases if case.expected_shell == "office_power") == 4
    assert sum(1 for case in cases if case.expected_shell == "entertainment_scandal") == 3
    assert sum(1 for case in cases if case.expected_shell == "campus_romance") == 3
    assert all(case.expected_template_id is not None for case in cases)
    assert all(case.expected_band == "8_15" for case in cases)


def test_runner_accepts_play_length_preset_override(tmp_path) -> None:
    case = mini_gold_set()[2]

    result = run_case(case, tmp_path, mode="deterministic", play_length_preset="20_25")

    assert result["play_length_preset"] == "20_25"
    assert result["arc_template_id"] == "flagship_6"
    assert result["segment_count"] == 6
    assert result["progress_required_by_segment"] == [4, 5, 6, 6, 5, 4]
    assert result["max_turns"] == 40


def test_benchmark_summary_tracks_live_depth_separately_from_content() -> None:
    summary = summarize_results(
        [
            {
                "passed": True,
                "structure_passed": True,
                "stage": "completed",
                "failure_category": None,
                "assertions": [],
                "content_score": 1.0,
                "structure_score": 1.0,
                "llm_call_count": 4,
                "llm_call_trace": [],
                "quality_trace": [],
                "live_depth_score": 3,
                "stage_live_attempt_count": {"synthesize_preview_blueprint": 3},
                "stage_live_success_count": {"synthesize_preview_blueprint": 1},
                "stage_provider_failure_count": {"synthesize_preview_blueprint": 2},
            },
            {
                "passed": False,
                "structure_passed": True,
                "stage": "gold_assertions",
                "failure_category": "segment incoherence",
                "assertions": [{"name": "route_promise_has_temptation", "passed": False}],
                "content_score": 0.8,
                "structure_score": 1.0,
                "llm_call_count": 0,
                "llm_call_trace": [],
                "quality_trace": [],
                "live_depth_score": 0,
                "stage_live_attempt_count": {"synthesize_preview_blueprint": 0},
                "stage_live_success_count": {"synthesize_preview_blueprint": 0},
                "stage_provider_failure_count": {"synthesize_preview_blueprint": 0},
            },
        ]
    )

    assert summary["avg_live_depth_score"] == 1.5
    assert summary["content_failure_case_count"] == 1
    assert summary["provider_hit_depth_case_count"] == 1
    assert summary["stage_live_attempt_count"]["synthesize_preview_blueprint"] == 3
    assert summary["stage_provider_failure_count"]["synthesize_preview_blueprint"] == 2
