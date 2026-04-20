from __future__ import annotations

import json
from pathlib import Path

from tools.urban_author_play_benchmarks.light_ab_baseline_refresh_runner import (
    run_light_ab_baseline_refresh,
)
from tools.urban_author_play_benchmarks.light_ab_eval_runner import run_light_ab_eval
from tools.urban_author_play_benchmarks.light_ab_shared import (
    BASELINE_LOCK_SCHEMA_VERSION,
    play_eval_signature,
)


def _play_eval_summary(case_ids: list[str], *, score: float) -> dict[str, object]:
    return {
        "cases": [
            {
                "case_id": case_id,
                "avg_strategic_tension_curve": score,
                "avg_consequence_legibility": score,
                "avg_payoff_realization": score,
                "avg_npc_interest_divergence": score,
                "avg_control_tradeoff_quality": score,
                "avg_shell_system_activation": score,
                "avg_ending_cost_integrity": score,
                "avg_replay_variance": score,
                "avg_turn_consequence_impact": score,
                "avg_turn_intent_binding": score,
                "avg_key_segment_shell_anchor_hit_rate": score,
                "turn_flag_counts": {"角色反应太泛": 0},
            }
            for case_id in case_ids
        ],
        "top_flags": {"角色反应太泛": 0},
    }


def _persona_coverage_summary(case_ids: list[str], *, success: int = 5) -> dict[str, object]:
    return {
        "min_success_personas_required": 4,
        "expected_persona_count": 5,
        "case_count": len(case_ids),
        "invalid_case_count": 0 if success >= 4 else len(case_ids),
        "invalid_case_ids": [] if success >= 4 else list(case_ids),
        "avg_successful_persona_count": float(success),
        "avg_turns_successful_personas": 8.0,
        "cases": [
            {
                "case_id": case_id,
                "expected_persona_count": 5,
                "known_persona_count": 5,
                "successful_persona_count": success,
                "successful_persona_ids": ["baodian", "qinggan", "wenjian", "zhandui", "fuchou"][:success],
                "failed_persona_ids": [] if success == 5 else ["zhandui", "fuchou"],
                "avg_turns_successful_personas": 8.0,
                "is_valid": success >= 4,
            }
            for case_id in case_ids
        ],
    }


def _llm_text_audit_summary(case_ids: list[str], *, score: float) -> dict[str, object]:
    return {
        "cases": [
            {
                "case_id": case_id,
                "avg_arc_coherence": score,
                "avg_payoff_strength": score,
                "avg_npc_presence": score,
                "avg_style_consistency": score,
                "avg_shell_distinctiveness": score,
                "avg_memorable_moments": score,
                "avg_turn_tone_naturalness": score,
                "avg_turn_character_specificity": score,
                "avg_turn_dramatic_tension": score,
                "avg_turn_shell_fidelity": score,
                "avg_turn_consequence_clarity": score,
                "avg_turn_anti_template_stiffness": score,
                "turn_flag_counts": {"模板味偏重": 0},
            }
            for case_id in case_ids
        ],
        "top_flags": {"模板味偏重": 0},
    }


def _fake_live_eval_payload(
    output_dir: Path,
    *,
    case_ids: list[str],
    profile: str,
    score: float,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "author_summary.json").write_text(
        json.dumps({"config": {"play_v2_narration_profile": profile}}, ensure_ascii=False, indent=2)
    )
    (output_dir / "play_eval_summary.json").write_text(
        json.dumps(_play_eval_summary(case_ids, score=score), ensure_ascii=False, indent=2)
    )
    (output_dir / "persona_coverage_summary.json").write_text(
        json.dumps(_persona_coverage_summary(case_ids), ensure_ascii=False, indent=2)
    )
    (output_dir / "llm_text_audit_summary.json").write_text(
        json.dumps(_llm_text_audit_summary(case_ids, score=score), ensure_ascii=False, indent=2)
    )
    return {
        "artifacts_dir": str(output_dir),
        "author_summary": {"config": {"play_v2_narration_profile": profile}},
        "play_eval_summary": _play_eval_summary(case_ids, score=score),
        "persona_coverage_summary": _persona_coverage_summary(case_ids),
        "llm_text_audit_summary": _llm_text_audit_summary(case_ids, score=score),
    }


def test_light_ab_baseline_refresh_writes_lock_and_artifacts(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def _fake_run_case_catalog_live_eval(
        output_dir,
        *,
        case_catalog,
        case_set_filename,
        blockers_filename,
        blockers_title,
        live_mode="live_gpt_5_4_mini",
        execution_mode="parallel",
        source_author_artifacts=True,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        case_max_workers=None,
        **kwargs,
    ):  # noqa: ANN001, ANN201
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        case_ids = [case.case_id for case in case_catalog]
        calls.append(case_ids)
        return _fake_live_eval_payload(
            output_path,
            case_ids=case_ids,
            profile="npc_texture_v2",
            score=2.2 if "holdout" not in str(output_path) else 2.0,
        )

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_baseline_refresh_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    lock_path = tmp_path / "baseline.lock.json"
    result = run_light_ab_baseline_refresh(
        tmp_path / "refresh",
        baseline_lock=lock_path,
        case_max_workers=20,
        total_rpm_limit=200,
    )

    assert len(calls) == 2
    assert lock_path.exists()
    lock_payload = json.loads(lock_path.read_text())
    assert lock_payload["baseline_name"] == "baseline"
    assert lock_payload["baseline_profile"] == "npc_texture_v2"
    assert lock_payload["schema_version"] == BASELINE_LOCK_SCHEMA_VERSION
    assert lock_payload["generated_at_utc"]
    assert Path(lock_payload["baseline_artifacts_dir"]).exists()
    assert Path(lock_payload["baseline_holdout_artifacts_dir"]).exists()
    assert (tmp_path / "refresh" / "light_baseline_refresh_manifest.json").exists()
    assert result["manifest"]["rpm_budget"] == {"author": 200, "helper": 200, "play": 200, "total": 200}


def test_light_ab_baseline_refresh_writes_holdout_and_llm_audit_signatures(tmp_path, monkeypatch) -> None:
    def _fake_run_case_catalog_live_eval(
        output_dir,
        *,
        case_catalog,
        case_set_filename,
        blockers_filename,
        blockers_title,
        live_mode="live_gpt_5_4_mini",
        execution_mode="parallel",
        source_author_artifacts=True,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        case_max_workers=None,
        **kwargs,
    ):  # noqa: ANN001, ANN201
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        case_ids = [case.case_id for case in case_catalog]
        return _fake_live_eval_payload(
            output_path,
            case_ids=case_ids,
            profile="npc_texture_v2",
            score=2.4 if "holdout" not in str(output_path) else 2.1,
        )

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_baseline_refresh_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    lock_path = tmp_path / "baseline.lock.json"
    run_light_ab_baseline_refresh(
        tmp_path / "refresh",
        baseline_lock=lock_path,
    )
    lock_payload = json.loads(lock_path.read_text())
    baseline_summary = json.loads((Path(lock_payload["baseline_artifacts_dir"]) / "play_eval_summary.json").read_text())
    holdout_summary = json.loads((Path(lock_payload["baseline_holdout_artifacts_dir"]) / "play_eval_summary.json").read_text())

    baseline_case_ids = [str(row["case_id"]) for row in list(baseline_summary.get("cases") or [])]
    holdout_case_ids = [str(row["case_id"]) for row in list(holdout_summary.get("cases") or [])]
    assert lock_payload["baseline_signature"] == play_eval_signature(
        baseline_summary,
        expected_case_ids=baseline_case_ids,
    )
    assert lock_payload["baseline_holdout_signature"] == play_eval_signature(
        holdout_summary,
        expected_case_ids=holdout_case_ids,
    )
    assert (Path(lock_payload["baseline_artifacts_dir"]) / "llm_text_audit_summary.json").exists()


def test_light_ab_eval_consumes_refreshed_lock_without_manual_patch(tmp_path, monkeypatch) -> None:
    def _fake_run_case_catalog_live_eval_for_refresh(
        output_dir,
        *,
        case_catalog,
        case_set_filename,
        blockers_filename,
        blockers_title,
        live_mode="live_gpt_5_4_mini",
        execution_mode="parallel",
        source_author_artifacts=True,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        case_max_workers=None,
        **kwargs,
    ):  # noqa: ANN001, ANN201
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        case_ids = [case.case_id for case in case_catalog]
        return _fake_live_eval_payload(output_path, case_ids=case_ids, profile="npc_texture_v2", score=2.0)

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_baseline_refresh_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval_for_refresh,
    )
    lock_path = tmp_path / "baseline.lock.json"
    run_light_ab_baseline_refresh(
        tmp_path / "refresh",
        baseline_lock=lock_path,
    )

    def _fake_run_case_catalog_live_eval_for_eval(
        output_dir,
        *,
        case_catalog,
        case_set_filename,
        blockers_filename,
        blockers_title,
        live_mode="live_gpt_5_4_mini",
        execution_mode="parallel",
        source_author_artifacts=True,
        enable_llm_text_audit=False,
        llm_text_audit_max_workers=None,
        case_max_workers=None,
        **kwargs,
    ):  # noqa: ANN001, ANN201
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        case_ids = [case.case_id for case in case_catalog]
        return _fake_live_eval_payload(output_path, case_ids=case_ids, profile="npc_texture_v2", score=2.5)

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_eval_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval_for_eval,
    )
    result = run_light_ab_eval(
        tmp_path / "eval",
        candidate_name="mainline_v2",
        run_seq=1,
        baseline_lock=lock_path,
    )

    assert (tmp_path / "eval" / "light_play_eval_ab_summary.json").exists()
    assert result["run_manifest"]["baseline_lock_schema_version"] == BASELINE_LOCK_SCHEMA_VERSION
