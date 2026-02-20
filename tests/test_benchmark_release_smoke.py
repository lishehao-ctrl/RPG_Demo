from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path


def _load_benchmark_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_release.py"
    spec = importlib.util.spec_from_file_location("benchmark_release", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _base_report() -> dict:
    return {
        "global": {
            "llm_calls_total": 200,
            "tokens_total": 320000,
            "stop_reason": "CALL_TARGET_REACHED",
        },
        "scenarios": [
            {
                "name": "local_fake_baseline",
                "step_success_rate": 1.0,
                "status_code_counts": {"200": 30, "503": 0},
                "detail_code_counts": {},
                "llm_unavailable_state_advance_violations": 0,
                "uncertain_duplicate_violation": 0,
                "idempotency_reused_checks_expected": 1,
                "idempotency_reused_checks_passed": 1,
            },
            {
                "name": "remote_clean",
                "step_success_rate": 0.99,
                "status_code_counts": {"200": 58, "503": 2},
                "detail_code_counts": {"LLM_UNAVAILABLE": 2},
                "llm_unavailable_state_advance_violations": 0,
                "uncertain_duplicate_violation": 0,
                "idempotency_reused_checks_expected": 1,
                "idempotency_reused_checks_passed": 1,
            },
            {
                "name": "remote_jitter_mild",
                "step_success_rate": 0.96,
                "status_code_counts": {"200": 48, "503": 2},
                "detail_code_counts": {"LLM_UNAVAILABLE": 2},
                "llm_unavailable_state_advance_violations": 0,
                "uncertain_duplicate_violation": 0,
                "idempotency_reused_checks_expected": 1,
                "idempotency_reused_checks_passed": 1,
            },
            {
                "name": "remote_jitter_severe",
                "step_success_rate": 0.9,
                "status_code_counts": {"200": 45, "503": 5},
                "detail_code_counts": {"LLM_UNAVAILABLE": 5},
                "llm_unavailable_state_advance_violations": 0,
                "uncertain_duplicate_violation": 0,
                "idempotency_reused_checks_expected": 1,
                "idempotency_reused_checks_passed": 1,
            },
        ],
        "aggregated_input_metrics": {
            "free_input_clear": {"fallback_rate": 0.25},
            "free_input_noise": {"fallback_rate": 0.75},
        },
    }


def test_project_token_budget_for_200_calls():
    module = _load_benchmark_module()
    projection = module.project_token_budget_for_calls(200)
    assert projection.calls == 200
    assert projection.avg_total_tokens == 207098
    assert projection.p95_total_tokens == 299200
    assert projection.p99_total_tokens == 365600
    assert projection.max_envelope_tokens == 464200


def test_default_scenarios_are_200_call_budget():
    module = _load_benchmark_module()
    scenarios = module.build_default_scenarios()
    assert [item.name for item in scenarios] == [
        "local_fake_baseline",
        "remote_clean",
        "remote_jitter_mild",
        "remote_jitter_severe",
    ]
    assert sum(item.call_quota for item in scenarios) == 200


def test_release_gate_passes_and_fails_as_expected():
    module = _load_benchmark_module()

    passing_report = _base_report()
    assert module.evaluate_release_v1(passing_report) == []

    failing_report = copy.deepcopy(passing_report)
    failing_report["scenarios"][1]["step_success_rate"] = 0.9
    failing_report["aggregated_input_metrics"]["free_input_clear"]["fallback_rate"] = 0.8
    failing_report["scenarios"][3]["idempotency_reused_checks_passed"] = 0

    errors = module.evaluate_release_v1(failing_report)
    assert any("remote_clean.step_success_rate < 0.98" in item for item in errors)
    assert any("input gradient invalid" in item for item in errors)
    assert any("idempotency_reused_checks_passed=0 < expected=1" in item for item in errors)
