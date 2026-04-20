from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.urban_author_play_benchmarks.gold_set import v1_topic_gold_14
from tools.urban_author_play_benchmarks.light_ab_eval_runner import (
    _build_failure_pack,
    _play_eval_signature,
    _select_chaos_shadow_case_ids,
    _select_light_case_catalog,
    _should_run_holdout,
    _should_run_llm_text_audit,
    run_light_ab_eval,
)
from tools.urban_author_play_benchmarks.holdout_case_catalog import build_holdout_case_catalog


def _play_eval_summary(case_ids: list[str], *, score: float, flag_count: int = 0) -> dict[str, object]:
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
                "turn_flag_counts": {"角色反应太泛": flag_count},
            }
            for case_id in case_ids
        ],
        "top_flags": {"角色反应太泛": flag_count},
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
                "turn_flag_counts": {"模板味偏重": 1},
            }
            for case_id in case_ids
        ],
        "top_flags": {"模板味偏重": 1},
    }


def _persona_coverage_summary(case_ids: list[str], *, success: int = 5) -> dict[str, object]:
    quality_valid = success >= 4
    return {
        "min_success_personas_required": 4,
        "expected_persona_count": 5,
        "case_count": len(case_ids),
        "invalid_case_count": 0 if success >= 4 else len(case_ids),
        "invalid_case_ids": [] if success >= 4 else list(case_ids),
        "quality_invalid_case_count": 0 if quality_valid else len(case_ids),
        "quality_invalid_case_ids": [] if quality_valid else list(case_ids),
        "quality_eval_incomplete_case_count": 0 if quality_valid else len(case_ids),
        "quality_eval_incomplete_case_ids": [] if quality_valid else list(case_ids),
        "valid_quality_case_count": len(case_ids) if quality_valid else 0,
        "valid_quality_case_ids": list(case_ids) if quality_valid else [],
        "avg_successful_persona_count": float(success),
        "avg_session_eval_successful_persona_count": float(success),
        "avg_turns_successful_personas": 8.0,
        "cases": [
            {
                "case_id": case_id,
                "expected_persona_count": 5,
                "known_persona_count": 5,
                "successful_persona_count": success,
                "successful_persona_ids": ["baodian", "qinggan", "wenjian", "zhandui", "fuchou"][:success],
                "failed_persona_ids": ["zhandui", "fuchou"][max(0, success - 3) :] if success < 5 else [],
                "session_eval_successful_persona_count": success,
                "session_eval_successful_persona_ids": ["baodian", "qinggan", "wenjian", "zhandui", "fuchou"][:success],
                "avg_turns_successful_personas": 8.0,
                "is_valid": success >= 4,
                "quality_eval_valid": quality_valid,
                "quality_eval_incomplete": not quality_valid,
            }
            for case_id in case_ids
        ],
    }


def _write_variant_artifacts(
    artifacts_dir: Path,
    *,
    profile: str,
    case_ids: list[str],
    score: float,
    include_llm: bool,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "author_summary.json").write_text(
        json.dumps({"config": {"play_v2_narration_profile": profile}}, ensure_ascii=False, indent=2)
    )
    (artifacts_dir / "play_eval_summary.json").write_text(
        json.dumps(_play_eval_summary(case_ids, score=score), ensure_ascii=False, indent=2)
    )
    (artifacts_dir / "persona_coverage_summary.json").write_text(
        json.dumps(_persona_coverage_summary(case_ids), ensure_ascii=False, indent=2)
    )
    if include_llm:
        (artifacts_dir / "llm_text_audit_summary.json").write_text(
            json.dumps(_llm_text_audit_summary(case_ids, score=score), ensure_ascii=False, indent=2)
        )


def test_light_case_catalog_is_shell_balanced() -> None:
    selected = _select_light_case_catalog(v1_topic_gold_14())
    assert len(selected) == 8
    shell_counts: dict[str, int] = {}
    for case in selected:
        shell_counts[case.expected_shell] = shell_counts.get(case.expected_shell, 0) + 1
    assert shell_counts == {
        "wealth_families": 2,
        "office_power": 2,
        "entertainment_scandal": 2,
        "campus_romance": 2,
    }


def test_chaos_shadow_case_selection_prioritizes_ent_and_campus() -> None:
    selected = _select_light_case_catalog(v1_topic_gold_14())

    shadow_ids = _select_chaos_shadow_case_ids(selected, count=2)

    by_case_id = {case.case_id: case for case in selected}
    assert len(shadow_ids) == 2
    assert all(case_id in by_case_id for case_id in shadow_ids)
    assert {
        by_case_id[shadow_ids[0]].expected_shell,
        by_case_id[shadow_ids[1]].expected_shell,
    } <= {"entertainment_scandal", "campus_romance"}


def test_checkpoint_policy_cycle() -> None:
    assert _should_run_holdout(3, False) is True
    assert _should_run_holdout(4, False) is False
    assert _should_run_holdout(4, True) is True
    assert _should_run_llm_text_audit(2, False) is True
    assert _should_run_llm_text_audit(3, False) is False
    assert _should_run_llm_text_audit(3, True) is True


def test_failure_pack_selects_high_flag_cases() -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    summary = _play_eval_summary(case_ids, score=2.0, flag_count=0)
    rows = list(summary["cases"])
    rows[0]["turn_flag_counts"] = {"角色反应太泛": 3}
    rows[1]["turn_flag_counts"] = {"爆点没落地": 2}
    rows[2]["turn_flag_counts"] = {"发酵停滞": 1}
    summary["cases"] = rows
    pack = _build_failure_pack(
        case_catalog=selected_cases,
        baseline_summary=summary,  # type: ignore[arg-type]
    )
    selected = list(pack["selected_case_ids"])
    assert selected
    assert case_ids[0] in selected
    assert case_ids[1] in selected
    assert case_ids[2] in selected


def test_light_ab_eval_fails_fast_when_baseline_lock_missing(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="baseline lock"):
        run_light_ab_eval(
            tmp_path / "out",
            candidate_name="mainline_v2",
            run_seq=1,
            baseline_lock=tmp_path / "missing.lock.json",
        )


def test_light_ab_eval_reuses_baseline_and_writes_core_artifacts(tmp_path, monkeypatch) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    baseline_dir = tmp_path / "baseline_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=2.0,
        include_llm=False,
    )
    signature = _play_eval_signature(
        json.loads((baseline_dir / "play_eval_summary.json").read_text()),
        expected_case_ids=case_ids,
    )
    lock_path = tmp_path / "baseline.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": signature,
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    observed_limits: list[tuple[str | None, str | None, str | None, str | None, str | None]] = []
    observed_calls: list[str] = []

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
    ):  # noqa: ANN001, ANN201
        observed_calls.append(str(output_dir))
        observed_limits.append(
            (
                os.environ.get("APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_RESPONSES_GLOBAL_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_RESPONSES_GLOBAL_RATE_LIMIT_SCOPE"),
            )
        )
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        return {
            "artifacts_dir": str(output_path),
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": _play_eval_summary(
                [case.case_id for case in case_catalog],
                score=3.0,
                flag_count=1,
            ),
            "persona_coverage_summary": _persona_coverage_summary([case.case_id for case in case_catalog], success=5),
            "llm_text_audit_summary": None,
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_eval_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    result = run_light_ab_eval(
        tmp_path / "out",
        candidate_name="mainline_v2",
        run_seq=1,
        case_max_workers=20,
        total_rpm_limit=200,
        baseline_lock=lock_path,
    )

    assert len(observed_calls) == 1
    assert observed_limits == [("200", "200", "200", None, None)]
    assert (tmp_path / "out" / "light_play_eval_ab_summary.json").exists()
    assert (tmp_path / "out" / "light_effect_report.md").exists()
    assert (tmp_path / "out" / "light_persona_coverage_report.json").exists()
    assert (tmp_path / "out" / "light_failure_pack.json").exists()
    assert (tmp_path / "out" / "light_failure_pack_eval_summary.json").exists()
    assert result["play_eval_ab_summary"]["delta"]["avg_consequence_legibility"] > 0
    assert result["run_manifest"]["baseline_lock_schema_version"] == 1
    assert result["run_manifest"]["baseline_generated_at_utc"] == "2026-04-01T00:00:00Z"
    assert result["run_manifest"]["baseline_artifacts_dir"] == str(baseline_dir.resolve())
    assert result["run_manifest"]["semantic_strategy_version"] == 8
    assert result["run_manifest"]["policy_cost_visibility_enabled"] is True
    assert result["run_manifest"]["policy_question_progress_v2_enabled"] is True
    assert result["run_manifest"]["policy_role_divergence_v2_enabled"] is True


def test_light_ab_runner_max_workers_20_with_rpm_200_budget(tmp_path, monkeypatch) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    baseline_dir = tmp_path / "baseline_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=2.0,
        include_llm=False,
    )
    lock_path = tmp_path / "baseline.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": _play_eval_signature(
                    json.loads((baseline_dir / "play_eval_summary.json").read_text()),
                    expected_case_ids=case_ids,
                ),
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    observed_case_max_workers: list[int | None] = []
    observed_limits: list[tuple[str | None, str | None, str | None, str | None, str | None]] = []

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
    ):  # noqa: ANN001, ANN201
        observed_case_max_workers.append(case_max_workers)
        observed_limits.append(
            (
                os.environ.get("APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_RESPONSES_GLOBAL_REQUESTS_PER_MINUTE"),
                os.environ.get("APP_RESPONSES_GLOBAL_RATE_LIMIT_SCOPE"),
            )
        )
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        return {
            "artifacts_dir": str(output_path),
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": _play_eval_summary([case.case_id for case in case_catalog], score=3.0, flag_count=0),
            "persona_coverage_summary": _persona_coverage_summary([case.case_id for case in case_catalog], success=5),
            "llm_text_audit_summary": None,
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_eval_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    run_light_ab_eval(
        tmp_path / "out",
        candidate_name="mainline_v2",
        run_seq=1,
        case_max_workers=20,
        total_rpm_limit=200,
        baseline_lock=lock_path,
    )

    assert observed_case_max_workers == [20]
    assert observed_limits == [("200", "200", "200", None, None)]


def test_light_ab_eval_replays_failure_pack_when_focus_flags_exist(tmp_path, monkeypatch) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    baseline_dir = tmp_path / "baseline_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=2.0,
        include_llm=False,
    )
    baseline_summary = json.loads((baseline_dir / "play_eval_summary.json").read_text())
    for index, row in enumerate(list(baseline_summary["cases"])):
        if index < 4:
            row["turn_flag_counts"] = {"角色反应太泛": 2 + index}
    (baseline_dir / "play_eval_summary.json").write_text(json.dumps(baseline_summary, ensure_ascii=False, indent=2))
    signature = _play_eval_signature(
        baseline_summary,
        expected_case_ids=case_ids,
    )
    lock_path = tmp_path / "baseline.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": signature,
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    observed_case_counts: list[int] = []

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
    ):  # noqa: ANN001, ANN201
        observed_case_counts.append(len(case_catalog))
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        return {
            "artifacts_dir": str(output_path),
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": _play_eval_summary([case.case_id for case in case_catalog], score=3.0),
            "persona_coverage_summary": _persona_coverage_summary([case.case_id for case in case_catalog], success=5),
            "llm_text_audit_summary": None,
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_eval_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    run_light_ab_eval(
        tmp_path / "out",
        candidate_name="mainline_v2",
        run_seq=1,
        baseline_lock=lock_path,
    )

    assert len(observed_case_counts) == 2
    assert max(observed_case_counts) == len(selected_cases)
    assert min(observed_case_counts) < len(selected_cases)
    failure_summary = json.loads((tmp_path / "out" / "light_failure_pack_eval_summary.json").read_text())
    assert failure_summary["selected_case_count"] > 0
    assert failure_summary["replayed"] is True


def test_light_ab_eval_checkpoint_writes_holdout_and_llm_audit(tmp_path, monkeypatch) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    holdout_cases = build_holdout_case_catalog(selected_cases, seed=20260401, variants_per_case=2)
    holdout_case_ids = [case.case_id for case in holdout_cases]
    baseline_dir = tmp_path / "baseline_variant"
    baseline_holdout_dir = tmp_path / "baseline_holdout_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=2.2,
        include_llm=True,
    )
    _write_variant_artifacts(
        baseline_holdout_dir,
        profile="npc_texture_v2",
        case_ids=holdout_case_ids,
        score=2.1,
        include_llm=False,
    )
    lock_path = tmp_path / "baseline.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": _play_eval_signature(
                    json.loads((baseline_dir / "play_eval_summary.json").read_text()),
                    expected_case_ids=case_ids,
                ),
                "baseline_holdout_artifacts_dir": str(baseline_holdout_dir),
                "baseline_holdout_signature": _play_eval_signature(
                    json.loads((baseline_holdout_dir / "play_eval_summary.json").read_text()),
                    expected_case_ids=holdout_case_ids,
                ),
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    call_count = {"count": 0}

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
    ):  # noqa: ANN001, ANN201
        call_count["count"] += 1
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        return {
            "artifacts_dir": str(output_path),
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": _play_eval_summary([case.case_id for case in case_catalog], score=3.1),
            "persona_coverage_summary": _persona_coverage_summary([case.case_id for case in case_catalog], success=5),
            "llm_text_audit_summary": _llm_text_audit_summary([case.case_id for case in case_catalog], score=3.3)
            if enable_llm_text_audit
            else None,
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_eval_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    run_light_ab_eval(
        tmp_path / "out",
        candidate_name="mainline_v2",
        run_seq=6,
        force_holdout=True,
        force_llm_audit=True,
        baseline_lock=lock_path,
    )

    assert call_count["count"] >= 2
    assert (tmp_path / "out" / "light_holdout_summary.json").exists()
    assert (tmp_path / "out" / "light_llm_text_audit_summary.json").exists()


def test_light_ab_eval_even_run_seq_without_force_fails_fast(tmp_path) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    baseline_dir = tmp_path / "baseline_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=2.0,
        include_llm=False,
    )
    lock_path = tmp_path / "baseline.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": _play_eval_signature(
                    json.loads((baseline_dir / "play_eval_summary.json").read_text()),
                    expected_case_ids=case_ids,
                ),
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    with pytest.raises(RuntimeError, match="must be odd"):
        run_light_ab_eval(
            tmp_path / "out_even",
            candidate_name="mainline_v2",
            run_seq=2,
            baseline_lock=lock_path,
        )


def test_light_ab_eval_propagates_case_timeout_and_records_manifest(tmp_path, monkeypatch) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    baseline_dir = tmp_path / "baseline_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=2.0,
        include_llm=False,
    )
    lock_path = tmp_path / "baseline.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": _play_eval_signature(
                    json.loads((baseline_dir / "play_eval_summary.json").read_text()),
                    expected_case_ids=case_ids,
                ),
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    observed_timeouts: list[float | None] = []

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
        case_timeout_seconds=None,
    ):  # noqa: ANN001, ANN201
        observed_timeouts.append(float(case_timeout_seconds) if case_timeout_seconds is not None else None)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        return {
            "artifacts_dir": str(output_path),
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": _play_eval_summary([case.case_id for case in case_catalog], score=3.0, flag_count=0),
            "persona_coverage_summary": _persona_coverage_summary([case.case_id for case in case_catalog], success=5),
            "llm_text_audit_summary": None,
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_eval_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    result = run_light_ab_eval(
        tmp_path / "out",
        candidate_name="mainline_v2",
        run_seq=1,
        case_timeout_seconds=150.0,
        baseline_lock=lock_path,
    )

    assert observed_timeouts == [150.0]
    assert result["run_manifest"]["case_timeout_seconds"] == 150.0
    assert result["run_manifest"]["case_aggregate_timeout_seconds"] == 360.0
    assert result["run_manifest"]["session_play_eval_timeout_seconds"] == 90.0


def test_light_ab_eval_uses_quality_valid_case_intersection(tmp_path, monkeypatch) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    baseline_dir = tmp_path / "baseline_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=4.0,
        include_llm=False,
    )
    lock_path = tmp_path / "baseline.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": _play_eval_signature(
                    json.loads((baseline_dir / "play_eval_summary.json").read_text()),
                    expected_case_ids=case_ids,
                ),
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

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
        case_timeout_seconds=None,
    ):  # noqa: ANN001, ANN201
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / case_set_filename).write_text("[]")
        (output_path / blockers_filename).write_text(f"# {blockers_title}\n")
        return {
            "artifacts_dir": str(output_path),
            "author_summary": {"config": {"play_v2_narration_profile": "npc_texture_v2"}},
            "play_eval_summary": _play_eval_summary([case.case_id for case in case_catalog], score=1.0, flag_count=0),
            "persona_coverage_summary": _persona_coverage_summary(
                [case.case_id for case in case_catalog],
                success=3,
            ),
            "llm_text_audit_summary": None,
        }

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.light_ab_eval_runner.run_case_catalog_live_eval",
        _fake_run_case_catalog_live_eval,
    )

    result = run_light_ab_eval(
        tmp_path / "out_quality",
        candidate_name="mainline_v2",
        run_seq=1,
        baseline_lock=lock_path,
    )
    ab_summary = result["play_eval_ab_summary"]
    assert ab_summary["quality_eval_case_count"] == 0
    assert all(row["quality_eval_eligible"] is False for row in ab_summary["case_deltas"])


def test_baseline_lock_schema_version_and_signature_validation(tmp_path) -> None:
    selected_cases = _select_light_case_catalog(v1_topic_gold_14())
    case_ids = [case.case_id for case in selected_cases]
    baseline_dir = tmp_path / "baseline_variant"
    _write_variant_artifacts(
        baseline_dir,
        profile="npc_texture_v2",
        case_ids=case_ids,
        score=2.0,
        include_llm=False,
    )
    signature = _play_eval_signature(
        json.loads((baseline_dir / "play_eval_summary.json").read_text()),
        expected_case_ids=case_ids,
    )

    bad_schema_lock = tmp_path / "bad_schema.lock.json"
    bad_schema_lock.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": signature,
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 999,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    with pytest.raises(RuntimeError, match="schema version mismatch"):
        run_light_ab_eval(
            tmp_path / "out_schema",
            candidate_name="mainline_v2",
            run_seq=1,
            baseline_lock=bad_schema_lock,
        )

    bad_signature_lock = tmp_path / "bad_signature.lock.json"
    bad_signature_lock.write_text(
        json.dumps(
            {
                "baseline_name": "baseline",
                "baseline_profile": "npc_texture_v2",
                "baseline_artifacts_dir": str(baseline_dir),
                "baseline_signature": "invalid-signature",
                "generated_at_utc": "2026-04-01T00:00:00Z",
                "schema_version": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    with pytest.raises(RuntimeError, match="signature mismatch"):
        run_light_ab_eval(
            tmp_path / "out_signature",
            candidate_name="mainline_v2",
            run_seq=1,
            baseline_lock=bad_signature_lock,
        )
