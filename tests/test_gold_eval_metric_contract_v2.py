from __future__ import annotations

import json
from pathlib import Path

from tools.urban_author_play_benchmarks.gold_eval_v2_metrics import _quantiles, build_gold_eval_v2_outputs
from tools.urban_author_play_benchmarks.gold_set import mini_gold_set


def test_gold_eval_v2_quantiles_use_nearest_rank() -> None:
    payload = _quantiles([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert payload["sample_count"] == 10
    assert payload["median"] == 5.5
    assert payload["p90"] == 9.0
    assert payload["p95"] == 10.0


def test_gold_eval_v2_outputs_include_quantiles_fail_rates_and_performance(tmp_path: Path) -> None:
    case = mini_gold_set()[0]
    artifact_dir = tmp_path / "deep_play" / case.case_id / "live"
    persona_dir = artifact_dir / "personas" / "baodian"
    persona_dir.mkdir(parents=True, exist_ok=True)

    (persona_dir / "turn_play_eval_logs.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "persona_id": "baodian",
                        "turn_index": 1,
                        "story_shell_id": case.expected_shell,
                        "segment_role": "pressure",
                        "play_eval_status": "completed",
                        "scores": {
                            "consequence_impact": 4,
                            "intent_binding": 5,
                            "pressure_exchange": 4,
                            "control_effectiveness": 3,
                            "trigger_conversion": 4,
                            "foreshadow_clarity": 4,
                            "shell_signal_fidelity": 5,
                            "npc_agency_reversal": 4,
                        },
                        "flags": ["发酵停滞"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "persona_id": "baodian",
                        "turn_index": 2,
                        "story_shell_id": case.expected_shell,
                        "segment_role": "reveal",
                        "play_eval_status": "failed",
                        "flags": ["选择不够痛"],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    (persona_dir / "session_play_eval_report.json").write_text(
        json.dumps(
            {
                "case_id": case.case_id,
                "persona_id": "baodian",
                "play_eval_status": "completed",
                "scores": {
                    "strategic_tension_curve": 4,
                    "consequence_legibility": 4,
                    "payoff_realization": 3,
                    "npc_interest_divergence": 4,
                    "control_tradeoff_quality": 3,
                    "shell_system_activation": 4,
                    "ending_cost_integrity": 4,
                    "replay_variance": 3,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (persona_dir / "turn_logs.jsonl").write_text(
        json.dumps(
            {
                "turn_index": 1,
                "turn_input_mode": "free_input",
                "submitted_with_selected_ids": False,
                "decision_latency_ms": 25.0,
                "runtime_latency_ms": 40.0,
                "total_turn_latency_ms": 65.0,
                "intent_stage_latency_ms": 22.0,
                "intent_stage_input_tokens": 80,
                "intent_stage_output_tokens": 30,
                "intent_stage_total_tokens": 110,
                "intent_llm_total_tokens": 90,
                "micro_sim_total_tokens": 20,
                "draft_call_count": 3,
                "draft_input_tokens": 44,
                "draft_output_tokens": 22,
                "draft_total_tokens": 66,
                "pre_submit_total_tokens": 66,
                "post_submit_total_tokens": 144,
                "play_turn_total_tokens": 210,
                "compose_prewarm_total_tokens": 24,
                "read_phase_prewarm_tokens": 9,
                "typing_phase_prewarm_tokens": 15,
                "submit_phase_tokens": 144,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (persona_dir / "turn_llm_text_audit_logs.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "persona_id": "baodian",
                        "turn_index": 1,
                        "story_shell_id": case.expected_shell,
                        "segment_role": "reveal",
                        "llm_audit_status": "completed",
                        "scores": {
                            "tone_naturalness": 4.2,
                            "character_specificity": 4.0,
                            "dramatic_tension": 4.1,
                            "shell_fidelity": 4.4,
                            "consequence_clarity": 3.9,
                            "anti_template_stiffness": 3.8,
                        },
                        "flags": ["角色反应太泛"],
                        "endpoint_results": [
                            {
                                "status": "completed",
                                "input_tokens": 150,
                                "output_tokens": 90,
                                "latency_ms": 480.0,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "persona_id": "baodian",
                        "turn_index": 2,
                        "story_shell_id": case.expected_shell,
                        "segment_role": "terminal",
                        "llm_audit_status": "failed",
                        "endpoint_results": [
                            {
                                "status": "failed",
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "latency_ms": 1000.0,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    (persona_dir / "session_llm_text_audit_report.json").write_text(
        json.dumps(
            {
                "case_id": case.case_id,
                "persona_id": "baodian",
                "llm_audit_status": "completed",
                "scores": {
                    "arc_coherence": 4.0,
                    "payoff_strength": 3.9,
                    "npc_presence": 4.1,
                    "style_consistency": 4.0,
                    "shell_distinctiveness": 4.2,
                    "memorable_moments": 3.7,
                },
                "endpoint_results": [
                    {
                        "status": "completed",
                        "input_tokens": 200,
                        "output_tokens": 120,
                        "latency_ms": 820.0,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = build_gold_eval_v2_outputs(
        case_catalog=[case],
        author_summary={
            "benchmark_results": [
                {
                    "case_id": case.case_id,
                    "llm_call_trace": [
                        {
                            "duration_seconds": 0.55,
                            "usage": {"input_tokens": 300, "output_tokens": 200, "total_tokens": 500},
                        }
                    ],
                }
            ]
        },
        case_summaries=[{"case_id": case.case_id, "artifacts_dir": str(artifact_dir)}],
        llm_text_case_summaries=[],
        persona_coverage_summary={
            "expected_persona_count": 5,
            "invalid_case_count": 0,
            "quality_invalid_case_count": 0,
            "cases": [{"case_id": case.case_id, "successful_persona_count": 4}],
        },
        case_failures={},
    )

    play_summary = outputs["play_eval_summary"]
    llm_summary = outputs["llm_text_audit_summary"]
    performance_summary = outputs["performance_summary"]

    assert play_summary["metric_contract_version"] == 2
    assert llm_summary["metric_contract_version"] == 2
    assert performance_summary["metric_contract_version"] == 2
    assert "quality_quantiles" in play_summary
    assert "quality_quantiles" in llm_summary
    assert "performance_summary" not in play_summary
    assert "author_generation" in performance_summary
    assert "play_turn" in performance_summary
    assert "llm_judge" in performance_summary
    assert "by_input_mode" in performance_summary["play_turn"]
    assert set(performance_summary["play_turn"]["by_input_mode"].keys()) == {"free_input", "select_id"}
    assert play_summary["quality_quantiles"]["global"]["turn"]["intent_binding"]["sample_count"] == 1
    assert llm_summary["quality_quantiles"]["global"]["turn"]["character_specificity"]["sample_count"] == 1
    assert performance_summary["play_turn"]["by_input_mode"]["free_input"]["decision_latency_ms"]["sample_count"] == 1
    assert performance_summary["play_turn"]["by_input_mode"]["select_id"]["decision_latency_ms"]["sample_count"] == 0
    assert performance_summary["play_turn"]["global"]["draft_total_tokens"]["sample_count"] == 1
    assert performance_summary["play_turn"]["by_input_mode"]["free_input"]["play_turn_total_tokens"]["sample_count"] == 1
    assert performance_summary["play_turn"]["global"]["compose_prewarm_total_tokens"]["sample_count"] == 1
    assert performance_summary["play_turn"]["global"]["read_phase_prewarm_tokens"]["sample_count"] == 1
    assert performance_summary["play_turn"]["global"]["typing_phase_prewarm_tokens"]["sample_count"] == 1
    assert performance_summary["play_turn"]["global"]["submit_phase_tokens"]["sample_count"] == 1
    assert play_summary["fail_rates"]["play_eval_failed_turn_rate"]["denominator"] == 2
    assert llm_summary["fail_rates"]["llm_audit_failed_turn_rate"]["denominator"] == 2
    assert play_summary["risk_tags"]["global"]["tags"]["发酵停滞"]["count"] == 1
    assert "avg_" not in json.dumps(play_summary, ensure_ascii=False)
    assert "avg_" not in json.dumps(llm_summary, ensure_ascii=False)
