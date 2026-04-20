from __future__ import annotations

import json
from pathlib import Path

from tools.urban_author_play_benchmarks.gold_set import promo_realistic_case_set
from tools.urban_author_play_benchmarks.live_eval_common import run_case_catalog_live_eval


class _FakeSettings:
    author_product_run_mode = "live_gpt_5_4_mini"
    play_v2_narration_profile = "npc_texture_v2"

    @staticmethod
    def resolved_author_responses_model() -> str:
        return "gpt-5.4-mini"

    @staticmethod
    def resolved_play_responses_model() -> str:
        return "gpt-5.4-mini"

    @staticmethod
    def resolved_helper_responses_base_url() -> str:
        return "https://api.xcode.best/v1"

    @staticmethod
    def resolved_helper_responses_model() -> str:
        return "gpt-5.4-mini"


def test_live_eval_writes_llm_text_audit_summary(tmp_path, monkeypatch) -> None:
    case = promo_realistic_case_set()[0]

    def _fake_helper_probe():  # noqa: ANN202
        return {
            "base_url": "https://api.xcode.best/v1",
            "model": "gpt-5.4-mini",
            "probes": [{"probe": "small", "success_count": 2, "failure_count": 0}],
            "primary_helper": {"role": "primary"},
            "backup_helpers": [{"role": "backup"}],
        }

    def _fake_benchmark(output_dir, mini_cases=None, *, modes=("live_gpt_5_4_mini",), include_burst=False):  # noqa: ANN001, ANN201
        assert mini_cases is not None
        result_rows = [
            {
                "case_id": case.case_id,
                "passed": True,
                "structure_passed": True,
                "content_score": 0.92,
                "structure_score": 1.0,
                "live_depth_score": 4,
                "final_mode_path": "live_gpt_5_4_mini->live_gpt_5_4_mini",
                "failure_category": None,
                "stage": "completed",
                "assertions": [],
                "llm_call_trace": [],
            }
            for case in mini_cases
        ]
        return {
            "smoke": {
                "mode_summaries": {
                    "live_gpt_5_4_mini": {
                        "total_cases": len(result_rows),
                        "passed_cases": len(result_rows),
                        "pass_rate": 1.0,
                        "avg_content_score": 0.92,
                        "avg_structure_score": 1.0,
                        "avg_live_depth_score": 4.0,
                        "failing_assertions": {},
                        "fallback_distribution": {},
                        "results": result_rows,
                    }
                }
            }
        }

    def _fake_self_play(
        output_dir,
        *,
        case_id,
        case_catalog=None,
        source_artifacts_dir=None,
        live_mode,
        execution_mode,
        enable_turn_play_eval,
        enable_session_play_eval,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        max_case_runtime_seconds=None,
        select_id_probability=0.1,
    ):  # noqa: ANN001, ANN201
        artifact_dir = Path(output_dir) / "self_play" / case_id / live_mode
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "comparison_summary.json").write_text(
            json.dumps({"case_id": case_id, "supports_distinct_playstyles": True}, ensure_ascii=False, indent=2)
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
                        "story_shell_id": "wealth_families",
                        "segment_role": "opening",
                        "play_eval_status": "completed",
                        "scores": {
                            "consequence_impact": 4,
                            "intent_binding": 4,
                            "pressure_exchange": 4,
                            "control_effectiveness": 4,
                            "trigger_conversion": 4,
                            "foreshadow_clarity": 4,
                            "shell_signal_fidelity": 4,
                            "npc_agency_reversal": 4,
                        },
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
                            "payoff_realization": 4,
                            "npc_interest_divergence": 4,
                            "control_tradeoff_quality": 4,
                            "shell_system_activation": 4,
                            "ending_cost_integrity": 4,
                            "replay_variance": 3,
                        },
                    },
                    ensure_ascii=False,
                )
            )
            (persona_dir / "turn_llm_text_audit_logs.jsonl").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "turn_index": 1,
                        "story_shell_id": "wealth_families",
                        "segment_role": "opening",
                        "llm_audit_status": "completed",
                        "scores": {
                            "tone_naturalness": 4,
                            "character_specificity": 4,
                            "dramatic_tension": 4,
                            "shell_fidelity": 4,
                            "consequence_clarity": 4,
                            "anti_template_stiffness": 4,
                        },
                        "flags": ["角色反应太泛"] if persona_id == "baodian" else [],
                    },
                    ensure_ascii=False,
                )
            )
            (persona_dir / "session_llm_text_audit_report.json").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "llm_audit_status": "completed",
                        "scores": {
                            "arc_coherence": 4,
                            "payoff_strength": 4,
                            "npc_presence": 4,
                            "style_consistency": 4,
                            "shell_distinctiveness": 4,
                            "memorable_moments": 3,
                        },
                        "top_issues": ["中段张力还能再抬"],
                        "top_strengths": ["语气自然"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return {"artifacts_dir": str(artifact_dir)}

    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.helper_probe", _fake_helper_probe)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_benchmark", _fake_benchmark)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_self_play_pilot", _fake_self_play)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.get_settings", lambda: _FakeSettings())

    result = run_case_catalog_live_eval(
        tmp_path,
        case_catalog=[case],
        case_set_filename="case_set.json",
        blockers_filename="blockers.md",
        blockers_title="Blockers",
        enable_llm_text_audit=True,
        llm_text_audit_max_workers=2,
    )

    assert Path(result["artifacts_dir"]) == tmp_path
    assert (tmp_path / "llm_text_audit_summary.json").exists()
    assert (tmp_path / "persona_coverage_summary.json").exists()
    summary = json.loads((tmp_path / "llm_text_audit_summary.json").read_text())
    assert summary["cases"][0]["avg_turn_character_specificity"] > 0
    assert summary["top_flags"]["角色反应太泛"] == 1
    play_summary = json.loads((tmp_path / "play_eval_summary.json").read_text())
    assert "avg_key_segment_shell_anchor_hit_rate" in play_summary["cases"][0]
    coverage = json.loads((tmp_path / "persona_coverage_summary.json").read_text())
    assert coverage["invalid_case_count"] == 0
    assert coverage["cases"][0]["successful_persona_count"] == 5


def test_live_eval_marks_case_invalid_when_persona_coverage_below_threshold(tmp_path, monkeypatch) -> None:
    case = promo_realistic_case_set()[0]

    def _fake_helper_probe():  # noqa: ANN202
        return {"base_url": "https://api.xcode.best/v1", "model": "gpt-5.4-mini", "probes": []}

    def _fake_benchmark(output_dir, mini_cases=None, *, modes=("live_gpt_5_4_mini",), include_burst=False):  # noqa: ANN001, ANN201
        assert mini_cases is not None
        return {
            "smoke": {
                "mode_summaries": {
                    "live_gpt_5_4_mini": {
                        "total_cases": len(mini_cases),
                        "passed_cases": len(mini_cases),
                        "pass_rate": 1.0,
                        "avg_content_score": 0.92,
                        "avg_structure_score": 1.0,
                        "avg_live_depth_score": 4.0,
                        "failing_assertions": {},
                        "fallback_distribution": {},
                        "results": [
                            {
                                "case_id": case.case_id,
                                "passed": True,
                                "structure_passed": True,
                                "content_score": 0.92,
                                "structure_score": 1.0,
                                "live_depth_score": 4,
                                "final_mode_path": "live_gpt_5_4_mini->live_gpt_5_4_mini",
                                "failure_category": None,
                                "stage": "completed",
                                "assertions": [],
                                "llm_call_trace": [],
                            }
                        ],
                    }
                }
            }
        }

    def _fake_self_play(
        output_dir,
        *,
        case_id,
        case_catalog=None,
        source_artifacts_dir=None,
        live_mode,
        execution_mode,
        enable_turn_play_eval,
        enable_session_play_eval,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        max_case_runtime_seconds=None,
        select_id_probability=0.1,
    ):  # noqa: ANN001, ANN201
        artifact_dir = Path(output_dir) / "self_play" / case_id / live_mode
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "comparison_summary.json").write_text(json.dumps({"case_id": case_id}, ensure_ascii=False))
        personas_dir = artifact_dir / "personas"
        for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou"):
            persona_dir = personas_dir / persona_id
            persona_dir.mkdir(parents=True, exist_ok=True)
            status = "completed" if persona_id in {"baodian", "qinggan", "wenjian"} else "failed"
            (persona_dir / "turn_play_eval_logs.jsonl").write_text("")
            (persona_dir / "session_play_eval_report.json").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "play_eval_status": status,
                        "scores": {
                            "strategic_tension_curve": 4,
                            "consequence_legibility": 4,
                            "payoff_realization": 4,
                            "npc_interest_divergence": 4,
                            "control_tradeoff_quality": 4,
                            "shell_system_activation": 4,
                            "ending_cost_integrity": 4,
                            "replay_variance": 3,
                        }
                        if status == "completed"
                        else None,
                    },
                    ensure_ascii=False,
                )
            )
        return {"artifacts_dir": str(artifact_dir)}

    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.helper_probe", _fake_helper_probe)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_benchmark", _fake_benchmark)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_self_play_pilot", _fake_self_play)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.get_settings", lambda: _FakeSettings())

    result = run_case_catalog_live_eval(
        tmp_path,
        case_catalog=[case],
        case_set_filename="case_set.json",
        blockers_filename="blockers.md",
        blockers_title="Blockers",
        enable_llm_text_audit=False,
    )

    coverage = result["persona_coverage_summary"]
    assert coverage["invalid_case_count"] == 1
    assert coverage["invalid_case_ids"] == [case.case_id]


def test_live_eval_does_not_mark_case_invalid_when_persona_runs_complete_but_session_eval_incomplete(tmp_path, monkeypatch) -> None:
    case = promo_realistic_case_set()[0]

    def _fake_helper_probe():  # noqa: ANN202
        return {"base_url": "https://api.xcode.best/v1", "model": "gpt-5.4-mini", "probes": []}

    def _fake_benchmark(output_dir, mini_cases=None, *, modes=("live_gpt_5_4_mini",), include_burst=False):  # noqa: ANN001, ANN201
        assert mini_cases is not None
        return {
            "smoke": {
                "mode_summaries": {
                    "live_gpt_5_4_mini": {
                        "total_cases": len(mini_cases),
                        "passed_cases": len(mini_cases),
                        "pass_rate": 1.0,
                        "avg_content_score": 0.92,
                        "avg_structure_score": 1.0,
                        "avg_live_depth_score": 4.0,
                        "failing_assertions": {},
                        "fallback_distribution": {},
                        "results": [
                            {
                                "case_id": case.case_id,
                                "passed": True,
                                "structure_passed": True,
                                "content_score": 0.92,
                                "structure_score": 1.0,
                                "live_depth_score": 4,
                                "final_mode_path": "live_gpt_5_4_mini->live_gpt_5_4_mini",
                                "failure_category": None,
                                "stage": "completed",
                                "assertions": [],
                                "llm_call_trace": [],
                            }
                        ],
                    }
                }
            }
        }

    def _fake_self_play(
        output_dir,
        *,
        case_id,
        case_catalog=None,
        source_artifacts_dir=None,
        live_mode,
        execution_mode,
        enable_turn_play_eval,
        enable_session_play_eval,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        max_case_runtime_seconds=None,
        select_id_probability=0.1,
    ):  # noqa: ANN001, ANN201
        artifact_dir = Path(output_dir) / "self_play" / case_id / live_mode
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "comparison_summary.json").write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "persona_summaries": {
                        persona_id: {
                            "persona_id": persona_id,
                            "worker_status": "completed",
                            "turn_count": 5,
                        }
                        for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou")
                    },
                },
                ensure_ascii=False,
            )
        )
        personas_dir = artifact_dir / "personas"
        for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou"):
            persona_dir = personas_dir / persona_id
            persona_dir.mkdir(parents=True, exist_ok=True)
            (persona_dir / "turn_play_eval_logs.jsonl").write_text("")
            (persona_dir / "session_play_eval_report.json").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "play_eval_status": "failed",
                        "play_eval_error": "eval_incomplete:session_play_eval_deadline_exceeded",
                        "scores": None,
                    },
                    ensure_ascii=False,
                )
            )
        return {"artifacts_dir": str(artifact_dir)}

    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.helper_probe", _fake_helper_probe)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_benchmark", _fake_benchmark)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_self_play_pilot", _fake_self_play)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.get_settings", lambda: _FakeSettings())

    result = run_case_catalog_live_eval(
        tmp_path,
        case_catalog=[case],
        case_set_filename="case_set.json",
        blockers_filename="blockers.md",
        blockers_title="Blockers",
        enable_llm_text_audit=False,
    )

    coverage = result["persona_coverage_summary"]
    assert coverage["invalid_case_count"] == 0
    assert coverage["quality_invalid_case_count"] == 1
    assert coverage["quality_eval_incomplete_case_count"] == 1


def test_live_eval_quality_gate_respects_session_eval_persona_limit(tmp_path, monkeypatch) -> None:
    case = promo_realistic_case_set()[0]

    def _fake_helper_probe():  # noqa: ANN202
        return {"base_url": "https://api.xcode.best/v1", "model": "gpt-5.4-mini", "probes": []}

    def _fake_benchmark(output_dir, mini_cases=None, *, modes=("live_gpt_5_4_mini",), include_burst=False):  # noqa: ANN001, ANN201
        assert mini_cases is not None
        return {
            "smoke": {
                "mode_summaries": {
                    "live_gpt_5_4_mini": {
                        "total_cases": len(mini_cases),
                        "passed_cases": len(mini_cases),
                        "pass_rate": 1.0,
                        "avg_content_score": 0.92,
                        "avg_structure_score": 1.0,
                        "avg_live_depth_score": 4.0,
                        "failing_assertions": {},
                        "fallback_distribution": {},
                        "results": [
                            {
                                "case_id": case.case_id,
                                "passed": True,
                                "structure_passed": True,
                                "content_score": 0.92,
                                "structure_score": 1.0,
                                "live_depth_score": 4,
                                "final_mode_path": "live_gpt_5_4_mini->live_gpt_5_4_mini",
                                "failure_category": None,
                                "stage": "completed",
                                "assertions": [],
                                "llm_call_trace": [],
                            }
                        ],
                    }
                }
            }
        }

    def _fake_self_play(
        output_dir,
        *,
        case_id,
        case_catalog=None,
        source_artifacts_dir=None,
        live_mode,
        execution_mode,
        enable_turn_play_eval,
        enable_session_play_eval,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        max_case_runtime_seconds=None,
        select_id_probability=0.1,
    ):  # noqa: ANN001, ANN201
        artifact_dir = Path(output_dir) / "self_play" / case_id / live_mode
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "comparison_summary.json").write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "persona_summaries": {
                        persona_id: {
                            "persona_id": persona_id,
                            "worker_status": "completed",
                            "turn_count": 6,
                        }
                        for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou")
                    },
                },
                ensure_ascii=False,
            )
        )
        personas_dir = artifact_dir / "personas"
        valid_session_eval_ids = {"baodian", "qinggan", "wenjian"}
        for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou"):
            persona_dir = personas_dir / persona_id
            persona_dir.mkdir(parents=True, exist_ok=True)
            (persona_dir / "turn_play_eval_logs.jsonl").write_text("")
            (persona_dir / "session_play_eval_report.json").write_text(
                json.dumps(
                    {
                        "case_id": case_id,
                        "persona_id": persona_id,
                        "play_eval_status": "completed",
                        "scores": (
                            {
                                "strategic_tension_curve": 4,
                                "consequence_legibility": 4,
                                "payoff_realization": 4,
                                "npc_interest_divergence": 4,
                                "control_tradeoff_quality": 4,
                                "shell_system_activation": 4,
                                "ending_cost_integrity": 4,
                                "replay_variance": 3,
                            }
                            if persona_id in valid_session_eval_ids
                            else None
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        return {"artifacts_dir": str(artifact_dir)}

    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.helper_probe", _fake_helper_probe)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_benchmark", _fake_benchmark)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_self_play_pilot", _fake_self_play)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.get_settings", lambda: _FakeSettings())

    result = run_case_catalog_live_eval(
        tmp_path,
        case_catalog=[case],
        case_set_filename="case_set.json",
        blockers_filename="blockers.md",
        blockers_title="Blockers",
        enable_llm_text_audit=False,
        session_play_eval_persona_limit=3,
    )

    coverage = result["persona_coverage_summary"]
    assert coverage["invalid_case_count"] == 0
    assert coverage["quality_invalid_case_count"] == 0
    assert coverage["quality_min_success_personas_required"] == 3


def test_live_eval_skips_failed_case_and_continues_aggregation(tmp_path, monkeypatch) -> None:
    cases = promo_realistic_case_set()[:2]
    failed_case_id = cases[0].case_id

    def _fake_helper_probe():  # noqa: ANN202
        return {"base_url": "https://api.xcode.best/v1", "model": "gpt-5.4-mini", "probes": []}

    def _fake_benchmark(output_dir, mini_cases=None, *, modes=("live_gpt_5_4_mini",), include_burst=False):  # noqa: ANN001, ANN201
        assert mini_cases is not None
        result_rows = [
            {
                "case_id": case.case_id,
                "passed": True,
                "structure_passed": True,
                "content_score": 0.9,
                "structure_score": 1.0,
                "live_depth_score": 4,
                "final_mode_path": "live_gpt_5_4_mini->live_gpt_5_4_mini",
                "failure_category": None,
                "stage": "completed",
                "assertions": [],
                "llm_call_trace": [],
            }
            for case in mini_cases
        ]
        return {
            "smoke": {
                "mode_summaries": {
                    "live_gpt_5_4_mini": {
                        "total_cases": len(result_rows),
                        "passed_cases": len(result_rows),
                        "pass_rate": 1.0,
                        "avg_content_score": 0.9,
                        "avg_structure_score": 1.0,
                        "avg_live_depth_score": 4.0,
                        "failing_assertions": {},
                        "fallback_distribution": {},
                        "results": result_rows,
                    }
                }
            }
        }

    def _fake_self_play(
        output_dir,
        *,
        case_id,
        case_catalog=None,
        source_artifacts_dir=None,
        live_mode,
        execution_mode,
        enable_turn_play_eval,
        enable_session_play_eval,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        max_case_runtime_seconds=None,
        select_id_probability=0.1,
    ):  # noqa: ANN001, ANN201
        if case_id == failed_case_id:
            raise RuntimeError("synthetic_case_failure")
        artifact_dir = Path(output_dir) / "self_play" / case_id / live_mode
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "comparison_summary.json").write_text(
            json.dumps({"case_id": case_id, "persona_summaries": {}}, ensure_ascii=False)
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
                            "trigger_conversion": 4,
                            "foreshadow_clarity": 4,
                            "shell_signal_fidelity": 4,
                            "npc_agency_reversal": 4,
                        },
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
                            "payoff_realization": 4,
                            "npc_interest_divergence": 4,
                            "control_tradeoff_quality": 4,
                            "shell_system_activation": 4,
                            "ending_cost_integrity": 4,
                            "replay_variance": 3,
                        },
                    },
                    ensure_ascii=False,
                )
            )
        return {"artifacts_dir": str(artifact_dir)}

    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.helper_probe", _fake_helper_probe)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_benchmark", _fake_benchmark)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.run_self_play_pilot", _fake_self_play)
    monkeypatch.setattr("tools.urban_author_play_benchmarks.live_eval_common.get_settings", lambda: _FakeSettings())

    result = run_case_catalog_live_eval(
        tmp_path,
        case_catalog=cases,
        case_set_filename="case_set.json",
        blockers_filename="blockers.md",
        blockers_title="Blockers",
        enable_llm_text_audit=False,
        case_timeout_seconds=10.0,
    )

    assert (tmp_path / "case_failures.json").exists()
    failures_payload = json.loads((tmp_path / "case_failures.json").read_text())
    assert failed_case_id in failures_payload["cases"]
    play_summary = result["play_eval_summary"]
    assert len(play_summary["cases"]) == 2
    failed_row = next(row for row in play_summary["cases"] if row["case_id"] == failed_case_id)
    assert failed_row["avg_turn_intent_binding"] == 0.0
