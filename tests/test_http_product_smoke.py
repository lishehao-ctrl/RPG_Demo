from __future__ import annotations

from tools import http_product_smoke


def test_parse_http_product_smoke_args_defaults() -> None:
    config = http_product_smoke.parse_args([])

    assert config.base_url == "http://127.0.0.1:8000"
    assert config.prompt_seed == http_product_smoke.DEFAULT_SEED
    assert config.first_turn_input == http_product_smoke.DEFAULT_TURN_INPUT
    assert config.poll_timeout_seconds == http_product_smoke.DEFAULT_POLL_TIMEOUT_SECONDS
    assert config.include_benchmark_diagnostics is False
    assert config.turn_budget == http_product_smoke.DEFAULT_TURN_BUDGET
    assert config.advisor_question == http_product_smoke.DEFAULT_ADVISOR_QUESTION


def test_stage_timings_summary_handles_missing_payload() -> None:
    assert http_product_smoke._stage_timings_summary(None) == []
    assert http_product_smoke._stage_timings_summary({"stage_timings": []}) == []


def test_stage_timings_summary_extracts_stage_and_elapsed_ms() -> None:
    summary = http_product_smoke._stage_timings_summary(
        {
            "stage_timings": [
                {"stage": "running", "elapsed_ms": 120},
                {"stage": "beat_plan_ready", "elapsed_ms": 480},
            ]
        }
    )

    assert summary == [
        {"stage": "running", "elapsed_ms": 120},
        {"stage": "beat_plan_ready", "elapsed_ms": 480},
    ]
