from __future__ import annotations

import json
from pathlib import Path

from tools.urban_author_play_benchmarks import five_round_quality_loop_runner as loop_runner


def _write_json(path: Path, payload) -> None:  # noqa: ANN001
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))


def _seed_artifact(
    *,
    output_dir: Path,
    metrics: dict[str, float],
    include_profile: bool,
) -> None:
    persona_dir = output_dir / "deep_play" / "self_play" / "case_a" / "live" / "personas" / "p1"
    persona_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        persona_dir / "turn_logs.jsonl",
        [
            {
                "turn_index": 1,
                "segment_role": "pressure",
                "raw_action_text": "我先逼他在台面上表态。",
                "narration": "他被迫接招，场面开始换手。",
                "progress_summary": "局面继续发酵。",
                "selected_move_family": "accuse",
                "selected_target_id": "npc_1",
                "consequence_tags": ["发酵停滞"],
                "story_shell_id": "office_power",
            }
        ],
    )
    _write_jsonl(
        persona_dir / "turn_play_eval_logs.jsonl",
        [
            {
                "case_id": "case_a",
                "persona_id": "p1",
                "turn_index": 1,
                "story_shell_id": "office_power",
                "segment_role": "pressure",
                "play_eval_status": "completed",
                "scores": {
                    "consequence_impact": 4,
                    "intent_binding": 4,
                    "pressure_exchange": 4,
                    "control_effectiveness": metrics["play_turn.control_effectiveness"],
                    "trigger_conversion": 4,
                    "foreshadow_clarity": 4,
                    "shell_signal_fidelity": 4,
                    "npc_agency_reversal": 4,
                },
                "flags": ["发酵停滞"],
                "main_issue": "交换力度偏弱。",
            }
        ],
    )
    _write_json(
        persona_dir / "session_play_eval_report.json",
        {
            "case_id": "case_a",
            "persona_id": "p1",
            "play_eval_status": "completed",
            "scores": {
                "strategic_tension_curve": 4,
                "consequence_legibility": 4,
                "payoff_realization": 4,
                "npc_interest_divergence": 4,
                "control_tradeoff_quality": metrics["play_session.control_tradeoff_quality"],
                "shell_system_activation": 4,
                "ending_cost_integrity": 4,
                "replay_variance": 4,
            },
            "worst_moment": "代价交换不够明显。",
            "top_issues": ["选择不够痛"],
        },
    )
    _write_jsonl(
        persona_dir / "turn_llm_text_audit_logs.jsonl",
        [
            {
                "case_id": "case_a",
                "persona_id": "p1",
                "turn_index": 1,
                "story_shell_id": "office_power",
                "segment_role": "pressure",
                "llm_audit_status": "completed",
                "scores": {
                    "tone_naturalness": metrics["llm_turn.tone_naturalness"],
                    "character_specificity": metrics["llm_turn.character_specificity"],
                    "dramatic_tension": 4,
                    "shell_fidelity": 4,
                    "consequence_clarity": 4,
                    "anti_template_stiffness": metrics["llm_turn.anti_template_stiffness"],
                },
                "flags": ["角色反应太泛"],
                "main_issue": "口吻同质化。",
            }
        ],
    )
    _write_json(
        persona_dir / "session_llm_text_audit_report.json",
        {
            "case_id": "case_a",
            "persona_id": "p1",
            "llm_audit_status": "completed",
            "scores": {
                "arc_coherence": 4,
                "payoff_strength": 4,
                "npc_presence": 4,
                "style_consistency": metrics["llm_session.style_consistency"],
                "shell_distinctiveness": 4,
                "memorable_moments": 4,
            },
            "worst_moment": "风格不够统一。",
            "top_issues": ["风格漂移"],
        },
    )
    _write_json(persona_dir / "run_summary.json", {"worst_turn_index": 1})
    _write_json(
        output_dir / "performance_summary.json",
        {
            "metric_contract_version": 2,
            "play_turn": {
                "global": {
                    "decision_latency_ms": {"median": 1000, "p90": 1200, "p95": 1400},
                    "runtime_latency_ms": {"median": 2000, "p90": 2400, "p95": 2600},
                    "total_turn_latency_ms": {"median": 3200, "p90": 3600, "p95": 3900},
                },
                "by_input_mode": {
                    "free_input": {
                        "decision_latency_ms": {"median": 1100, "p90": 1300, "p95": 1500, "sample_count": 1},
                        "runtime_latency_ms": {"median": 2100, "p90": 2500, "p95": 2700, "sample_count": 1},
                        "total_turn_latency_ms": {"median": 3300, "p90": 3700, "p95": 4000, "sample_count": 1},
                    },
                    "select_id": {
                        "decision_latency_ms": {"median": 900, "p90": 1000, "p95": 1100, "sample_count": 0},
                        "runtime_latency_ms": {"median": 1800, "p90": 2000, "p95": 2200, "sample_count": 0},
                        "total_turn_latency_ms": {"median": 2900, "p90": 3100, "p95": 3300, "sample_count": 0},
                    },
                },
            },
        },
    )
    if include_profile:
        _write_json(
            output_dir / "deep_play" / "self_play" / "case_a" / "live" / "compiled_play_plan.json",
            {
                "quality_tuning_profile": loop_runner.QualityTuningProfile(
                    round_label="base",
                    note="test_seed",
                ).model_dump(mode="json")
            },
        )


def test_lowest_metric_tie_break_uses_priority_order() -> None:
    metrics = {
        key: {"mean": 2.0, "sample_count": 1}
        for key in loop_runner.METRIC_PRIORITY
    }
    lowest = loop_runner._lowest_metric(metrics)
    assert lowest["metric_key"] == loop_runner.METRIC_PRIORITY[0]


def test_select_case_study_samples_respects_case_and_persona_limits() -> None:
    candidates = []
    for idx in range(30):
        candidates.append(
            {
                "case_id": f"case_{idx % 3}",
                "persona_id": f"p_{idx % 4}",
                "story_shell_id": "office_power",
                "segment_role": "pressure",
                "turn_index": idx + 1,
                "score": 1.0 + idx * 0.01,
            }
        )
    selected = loop_runner._select_case_study_samples(
        candidates=candidates,
        limit=20,
        max_per_case=2,
        max_per_persona=2,
    )
    case_counter = {}
    persona_counter = {}
    for row in selected:
        case_counter[row["case_id"]] = case_counter.get(row["case_id"], 0) + 1
        persona_counter[row["persona_id"]] = persona_counter.get(row["persona_id"], 0) + 1
    assert len(selected) <= 20
    assert all(value <= 2 for value in case_counter.values())
    assert all(value <= 2 for value in persona_counter.values())


def test_propose_tuning_candidate_expands_prompt_profile_weights_for_control_metrics() -> None:
    base_profile = loop_runner.QualityTuningProfile().model_dump(mode="json")
    candidate, notes = loop_runner._propose_tuning_candidate(
        base_profile=base_profile,
        metric_key="play_turn.control_effectiveness",
        root_causes={"top_segment_roles": [{"segment_role": "pressure", "count": 3}]},
        round_index=1,
    )

    assert candidate["play"]["intent_control_contract_hint_weight"] > base_profile["play"]["intent_control_contract_hint_weight"]
    assert candidate["play"]["compose_control_contract_hint_weight"] > base_profile["play"]["compose_control_contract_hint_weight"]
    assert candidate["author"]["control_contract_hint_weight"] > base_profile["author"]["control_contract_hint_weight"]
    assert notes


def test_five_round_loop_applies_rollback_gate(tmp_path, monkeypatch) -> None:
    call_index = {"value": 0}
    run_metrics = [
        {
            "play_turn.control_effectiveness": 2.0,
            "play_session.control_tradeoff_quality": 3.0,
            "llm_turn.anti_template_stiffness": 3.0,
            "llm_session.style_consistency": 3.0,
            "llm_turn.tone_naturalness": 3.0,
            "llm_turn.character_specificity": 3.0,
        },
        {
            "play_turn.control_effectiveness": 2.05,
            "play_session.control_tradeoff_quality": 2.8,
            "llm_turn.anti_template_stiffness": 3.0,
            "llm_session.style_consistency": 3.0,
            "llm_turn.tone_naturalness": 3.0,
            "llm_turn.character_specificity": 3.0,
        },
        {
            "play_turn.control_effectiveness": 2.0,
            "play_session.control_tradeoff_quality": 3.0,
            "llm_turn.anti_template_stiffness": 3.0,
            "llm_session.style_consistency": 3.0,
            "llm_turn.tone_naturalness": 3.0,
            "llm_turn.character_specificity": 3.0,
        },
        {
            "play_turn.control_effectiveness": 2.2,
            "play_session.control_tradeoff_quality": 2.95,
            "llm_turn.anti_template_stiffness": 3.0,
            "llm_session.style_consistency": 3.0,
            "llm_turn.tone_naturalness": 3.0,
            "llm_turn.character_specificity": 3.0,
        },
    ]

    def _fake_run_suite(*, output_dir: Path, **kwargs):  # noqa: ANN003, ANN201
        idx = call_index["value"]
        call_index["value"] += 1
        _seed_artifact(
            output_dir=output_dir,
            metrics=run_metrics[idx],
            include_profile=(idx == 0),
        )
        return {"artifacts_dir": str(output_dir)}

    monkeypatch.setattr(loop_runner, "_run_suite", _fake_run_suite)

    summary = loop_runner.run_five_round_quality_loop(
        tmp_path / "loop",
        rounds=2,
        mini_rounds=2,
        case_max_workers=1,
        total_rpm_limit=1,
        case_timeout_seconds=30.0,
        case_aggregate_timeout_seconds=60.0,
        session_play_eval_timeout_seconds=30.0,
        select_id_probability=0.1,
        improve_threshold=0.1,
        guardrail_drop_threshold=0.15,
    )

    assert summary["rounds"] == 2
    assert summary["round_results"][0]["rolled_back"] is True
    assert summary["round_results"][1]["rolled_back"] is False
    assert (tmp_path / "loop" / "round_01_mini" / "rollback_decision.json").exists()
    assert (tmp_path / "loop" / "round_02_mini" / "proposed_tuning_patch.json").exists()
