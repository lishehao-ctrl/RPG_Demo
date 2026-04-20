from __future__ import annotations

import json
from pathlib import Path

from tools.urban_author_play_benchmarks.gold_set import native_cn_gold_realistic_14
from tools.urban_author_play_benchmarks.native_cn_live_eval import (
    _case_llm_text_audit_summary,
    _case_play_eval_summary,
    _select_top_cases,
    run_native_cn_live_eval,
)


def test_select_top_cases_prefers_shell_diversity() -> None:
    catalog = native_cn_gold_realistic_14()
    selected = _select_top_cases(
        case_catalog=catalog,
        results=[
            {
                "case_id": "office_flagship_merger",
                "passed": True,
                "content_score": 0.99,
                "live_depth_score": 4,
                "structure_score": 1.0,
                "final_mode_path": "live_gpt_5_4_mini->live_gpt_5_4_mini",
            },
            {
                "case_id": "office_standard_boardroom",
                "passed": True,
                "content_score": 0.98,
                "live_depth_score": 4,
                "structure_score": 1.0,
                "final_mode_path": "live_gpt_5_4_mini->live_gpt_5_4_mini",
            },
            {
                "case_id": "campus_standard_homecoming",
                "passed": True,
                "content_score": 0.97,
                "live_depth_score": 3,
                "structure_score": 1.0,
                "final_mode_path": "live_gpt_5_4_mini->deterministic",
            },
            {
                "case_id": "wealth_short_wedding",
                "passed": True,
                "content_score": 0.96,
                "live_depth_score": 3,
                "structure_score": 1.0,
                "final_mode_path": "live_gpt_5_4_mini->deterministic",
            },
        ],
        top_n=3,
    )

    assert [item["case_id"] for item in selected] == [
        "office_flagship_merger",
        "campus_standard_homecoming",
        "wealth_short_wedding",
    ]


def test_run_native_cn_live_eval_writes_root_artifacts(tmp_path, monkeypatch) -> None:
    case_count = len(native_cn_gold_realistic_14())

    def _fake_benchmark(output_dir, mini_cases=None, *, modes=("pure_gpt",), include_burst=False):  # noqa: ANN001, ANN201
        assert mini_cases is not None
        return {
            "smoke": {
                "mode_summaries": {
                    "pure_gpt": {
                        "total_cases": case_count,
                        "passed_cases": 4,
                        "pass_rate": 0.4,
                        "avg_content_score": 0.91,
                        "avg_structure_score": 1.0,
                        "avg_live_depth_score": 2.7,
                        "fallback_distribution": {
                            "synthesize_preview_blueprint:fallback": 2,
                            "compile_segment_playbooks:repaired": 1,
                        },
                        "results": [
                            {
                                "case_id": "office_flagship_merger",
                                "passed": True,
                                "content_score": 0.99,
                                "live_depth_score": 4,
                                "structure_score": 1.0,
                                "final_mode_path": "gpt->gpt->gpt->gpt",
                            },
                            {
                                "case_id": "office_standard_boardroom",
                                "passed": True,
                                "content_score": 0.98,
                                "live_depth_score": 4,
                                "structure_score": 1.0,
                                "final_mode_path": "gpt->gpt->gpt->deterministic",
                            },
                            {
                                "case_id": "campus_standard_homecoming",
                                "passed": True,
                                "content_score": 0.97,
                                "live_depth_score": 3,
                                "structure_score": 1.0,
                                "final_mode_path": "gpt->gpt->deterministic->deterministic",
                            },
                            {
                                "case_id": "wealth_short_wedding",
                                "passed": True,
                                "content_score": 0.96,
                                "live_depth_score": 2,
                                "structure_score": 1.0,
                                "final_mode_path": "gpt->deterministic->deterministic->deterministic",
                            },
                        ],
                    }
                }
            }
        }

    def _fake_self_play(
        output_dir,
        *,
        case_id,
        live_mode,
        execution_mode,
        enable_turn_play_eval,
        enable_session_play_eval,
        select_id_probability=0.1,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
    ):  # noqa: ANN001, ANN201
        artifact_dir = Path(output_dir) / "self_play" / case_id / live_mode
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "comparison_summary.json").write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "supports_distinct_playstyles": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        personas_dir = artifact_dir / "personas"
        for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou"):
            persona_dir = personas_dir / persona_id
            persona_dir.mkdir(parents=True, exist_ok=True)
            (persona_dir / "turn_play_eval_logs.jsonl").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "turn_index": 1,
                        "story_shell_id": "office_power",
                        "segment_role": "opening",
                        "play_eval_status": "completed",
                        "scores": {
                            "consequence_impact": 4,
                            "intent_binding": 4,
                            "pressure_exchange": 4,
                            "control_effectiveness": 4,
                            "trigger_conversion": 3,
                            "foreshadow_clarity": 4,
                            "shell_signal_fidelity": 4,
                            "npc_agency_reversal": 4,
                        },
                        "strongest_signal": "这一句能记住。",
                        "main_issue": "中段还可以更狠。",
                        "flags": ["发酵停滞"] if persona_id == "baodian" else [],
                    },
                    ensure_ascii=False,
                )
            )
            (persona_dir / "session_play_eval_report.json").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "play_eval_status": "completed",
                        "scores": {
                            "strategic_tension_curve": 4,
                            "consequence_legibility": 4,
                            "payoff_realization": 3,
                            "npc_interest_divergence": 4,
                            "control_tradeoff_quality": 4,
                            "shell_system_activation": 4,
                            "ending_cost_integrity": 4,
                            "replay_variance": 3,
                        },
                        "best_moment": "最好的是公开翻车那下。",
                        "worst_moment": "最弱的是中段略平。",
                        "one_sentence_verdict": "这局能玩，而且像中文。",
                        "top_issues": ["中段张力还能再抬"],
                        "top_strengths": ["人物反应有区分"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return {"artifacts_dir": str(artifact_dir)}

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.native_cn_live_eval.run_benchmark",
        _fake_benchmark,
    )
    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.native_cn_live_eval.run_self_play_pilot",
        _fake_self_play,
    )

    result = run_native_cn_live_eval(tmp_path)

    assert Path(result["artifacts_dir"]) == tmp_path
    assert (tmp_path / "native_cn_gold_realistic_14_summary.json").exists()
    assert (tmp_path / "selected_cases.json").exists()
    assert (tmp_path / "consolidated_report_zh.md").exists()

    selected_payload = json.loads((tmp_path / "selected_cases.json").read_text())
    assert [item["case_id"] for item in selected_payload["selected_cases"]] == [
        "office_flagship_merger",
        "campus_standard_homecoming",
        "wealth_short_wedding",
    ]
    report = (tmp_path / "consolidated_report_zh.md").read_text()
    assert f"{case_count}-case live smoke summary" in report
    assert "top-3 deep play summary" in report
    assert "NPC interest findings" in report


def test_case_summaries_tolerate_null_session_scores(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "self_play" / "case_x" / "live_gpt_5_4_mini"
    personas_dir = artifact_dir / "personas"
    personas_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "comparison_summary.json").write_text(
        json.dumps({"case_id": "case_x", "persona_summaries": {}, "supports_distinct_playstyles": True}, ensure_ascii=False)
    )

    for persona_id, with_scores in (("baodian", True), ("wenjian", False)):
        persona_dir = personas_dir / persona_id
        persona_dir.mkdir(parents=True, exist_ok=True)
        (persona_dir / "turn_play_eval_logs.jsonl").write_text(
            json.dumps(
                {
                    "play_eval_status": "completed",
                    "scores": {
                        "consequence_impact": 4,
                        "intent_binding": 4,
                        "pressure_exchange": 3,
                        "control_effectiveness": 4,
                        "trigger_conversion": 3,
                        "foreshadow_clarity": 3,
                        "shell_signal_fidelity": 4,
                        "npc_agency_reversal": 3,
                    },
                    "flags": [],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        (persona_dir / "session_play_eval_report.json").write_text(
            json.dumps(
                {
                    "play_eval_status": "completed",
                    "scores": (
                        {
                            "strategic_tension_curve": 4,
                            "consequence_legibility": 4,
                            "payoff_realization": 3,
                            "npc_interest_divergence": 4,
                            "control_tradeoff_quality": 4,
                            "shell_system_activation": 4,
                            "ending_cost_integrity": 3,
                            "replay_variance": 3,
                        }
                        if with_scores
                        else None
                    ),
                    "top_issues": ["中段可再提压"],
                    "top_strengths": ["角色反馈有分化"],
                },
                ensure_ascii=False,
            )
        )
        (persona_dir / "turn_llm_text_audit_logs.jsonl").write_text(
            json.dumps(
                {
                    "llm_audit_status": "completed",
                    "scores": {
                        "tone_naturalness": 4,
                        "character_specificity": 4,
                        "dramatic_tension": 3,
                        "shell_fidelity": 4,
                        "consequence_clarity": 4,
                        "anti_template_stiffness": 4,
                    },
                    "endpoint_results": [],
                    "flags": [],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        (persona_dir / "session_llm_text_audit_report.json").write_text(
            json.dumps(
                {
                    "llm_audit_status": "completed",
                    "scores": (
                        {
                            "arc_coherence": 4,
                            "payoff_strength": 4,
                            "npc_presence": 4,
                            "style_consistency": 4,
                            "shell_distinctiveness": 4,
                            "memorable_moments": 3,
                        }
                        if with_scores
                        else None
                    ),
                    "endpoint_results": [],
                    "top_issues": ["还可更锋利"],
                    "top_strengths": ["台词自然"],
                },
                ensure_ascii=False,
            )
        )

    play_summary = _case_play_eval_summary("case_x", artifact_dir)
    assert play_summary["session_play_eval_total_count"] == 2
    assert play_summary["session_play_eval_completed_count"] == 1
    assert play_summary["avg_control_tradeoff_quality"] == 4.0

    llm_summary = _case_llm_text_audit_summary("case_x", artifact_dir)
    assert llm_summary["avg_style_consistency"] == 4.0
