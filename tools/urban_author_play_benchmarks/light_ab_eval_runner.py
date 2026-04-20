from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from statistics import mean
from typing import Any

from rpg_backend.config import Settings
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase, v1_topic_gold_14
from tools.urban_author_play_benchmarks.light_ab_shared import (
    BASELINE_LOCK_DEFAULT,
    BASELINE_LOCK_SCHEMA_VERSION,
    build_holdout_case_catalog,
    build_rpm_budget,
    play_eval_signature,
    rpm_budget_limits,
    select_light_case_catalog,
    strict_no_repair_fallback,
)
from tools.urban_author_play_benchmarks.live_eval_common import run_case_catalog_live_eval
from tools.urban_author_play_benchmarks.native_cn_live_eval import _write_json
from tools.urban_author_play_benchmarks.semantic_policy_autotune import (
    build_semantic_autotune_patch,
    render_semantic_autotune_notes,
)

PLAY_EVAL_KEYS: tuple[str, ...] = (
    "avg_strategic_tension_curve",
    "avg_consequence_legibility",
    "avg_payoff_realization",
    "avg_npc_interest_divergence",
    "avg_control_tradeoff_quality",
    "avg_shell_system_activation",
    "avg_ending_cost_integrity",
    "avg_replay_variance",
    "avg_turn_consequence_impact",
    "avg_turn_intent_binding",
    "avg_key_segment_shell_anchor_hit_rate",
)
LLM_TEXT_AUDIT_KEYS: tuple[str, ...] = (
    "avg_arc_coherence",
    "avg_payoff_strength",
    "avg_npc_presence",
    "avg_style_consistency",
    "avg_shell_distinctiveness",
    "avg_memorable_moments",
    "avg_turn_tone_naturalness",
    "avg_turn_character_specificity",
    "avg_turn_dramatic_tension",
    "avg_turn_shell_fidelity",
    "avg_turn_consequence_clarity",
    "avg_turn_anti_template_stiffness",
)
GENERALIZATION_KEYS: tuple[str, ...] = (
    "avg_turn_intent_binding",
    "avg_shell_system_activation",
    "avg_payoff_realization",
    "avg_npc_interest_divergence",
)
FAILURE_PACK_FLAGS: tuple[str, ...] = (
    "角色反应太泛",
    "爆点没落地",
    "发酵停滞",
)
FAILURE_PACK_MAX_CASES = 4
CHAOS_SHADOW_DEFAULT_COUNT = 2

def _select_light_case_catalog(case_catalog: list[UrbanGoldCase]) -> list[UrbanGoldCase]:
    return select_light_case_catalog(case_catalog)


def _build_rpm_budget(total_rpm_limit: int) -> dict[str, int]:
    return build_rpm_budget(total_rpm_limit)


def _select_chaos_shadow_case_ids(case_catalog: list[UrbanGoldCase], *, count: int) -> list[str]:
    desired = max(0, int(count))
    if desired == 0:
        return []
    prioritized_shells = ("entertainment_scandal", "campus_romance")
    ordered_ids: list[str] = []
    for shell_id in prioritized_shells:
        for case in sorted((item for item in case_catalog if item.expected_shell == shell_id), key=lambda item: item.case_id):
            ordered_ids.append(case.case_id)
    for case in sorted(case_catalog, key=lambda item: item.case_id):
        if case.case_id not in set(ordered_ids):
            ordered_ids.append(case.case_id)
    deduped: list[str] = []
    for case_id in ordered_ids:
        if case_id not in deduped:
            deduped.append(case_id)
    return deduped[:desired]


def _mean_case_metric(summary: dict[str, Any], key: str) -> float:
    values = [float(row.get(key, 0.0)) for row in list(summary.get("cases") or [])]
    return round(mean(values), 4) if values else 0.0


def _mean_case_metric_for_ids(summary: dict[str, Any], key: str, case_ids: list[str]) -> float:
    rows_by_id = _case_rows_by_id(summary)
    values = [
        float(rows_by_id[case_id].get(key, 0.0))
        for case_id in case_ids
        if case_id in rows_by_id
    ]
    return round(mean(values), 4) if values else 0.0


def _case_rows_by_id(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["case_id"]): row for row in list(summary.get("cases") or [])}


def _quality_valid_case_ids(payload: dict[str, Any]) -> set[str]:
    coverage = dict(payload.get("persona_coverage_summary") or {})
    explicit = [str(case_id) for case_id in list(coverage.get("valid_quality_case_ids") or []) if str(case_id)]
    if explicit:
        return set(explicit)
    rows = list(coverage.get("cases") or [])
    if rows:
        selected: set[str] = set()
        for row in rows:
            case_id = str(dict(row).get("case_id") or "")
            if not case_id:
                continue
            if bool(dict(row).get("quality_eval_valid", dict(row).get("is_valid", True))):
                selected.add(case_id)
        return selected
    summary = dict(payload.get("play_eval_summary") or {})
    return {str(row.get("case_id")) for row in list(summary.get("cases") or []) if str(row.get("case_id"))}


def _flag_delta(baseline: dict[str, int], candidate: dict[str, int]) -> dict[str, int]:
    keys = sorted(set(baseline) | set(candidate))
    return {key: int(candidate.get(key, 0)) - int(baseline.get(key, 0)) for key in keys}


def _ab_summary(
    *,
    baseline_name: str,
    baseline_payload: dict[str, Any],
    candidate_name: str,
    candidate_payload: dict[str, Any],
) -> dict[str, Any]:
    baseline = baseline_payload["play_eval_summary"]
    candidate = candidate_payload["play_eval_summary"]
    baseline_cases = _case_rows_by_id(baseline)
    candidate_cases = _case_rows_by_id(candidate)
    baseline_quality_cases = _quality_valid_case_ids(baseline_payload)
    candidate_quality_cases = _quality_valid_case_ids(candidate_payload)
    quality_case_ids = sorted(
        set(baseline_cases)
        & set(candidate_cases)
        & baseline_quality_cases
        & candidate_quality_cases
    )
    case_deltas: list[dict[str, Any]] = []
    for case_id in sorted(set(baseline_cases) | set(candidate_cases)):
        base = baseline_cases.get(case_id, {})
        exp = candidate_cases.get(case_id, {})
        quality_eval_eligible = case_id in set(quality_case_ids)
        case_deltas.append(
            {
                "case_id": case_id,
                "quality_eval_eligible": quality_eval_eligible,
                **{
                    key: round(float(exp.get(key, 0.0)) - float(base.get(key, 0.0)), 4)
                    for key in PLAY_EVAL_KEYS
                },
            }
        )
    baseline_means = {
        key: _mean_case_metric_for_ids(baseline, key, quality_case_ids)
        for key in PLAY_EVAL_KEYS
    }
    candidate_means = {
        key: _mean_case_metric_for_ids(candidate, key, quality_case_ids)
        for key in PLAY_EVAL_KEYS
    }
    return {
        "baseline_variant": baseline_name,
        "candidate_variant": candidate_name,
        "quality_eval_case_count": len(quality_case_ids),
        "quality_eval_case_ids": quality_case_ids,
        "variants": {
            "baseline": {
                "name": baseline_name,
                "play_v2_narration_profile": baseline_payload["author_summary"]["config"]["play_v2_narration_profile"],
                **baseline_means,
                "top_flags": baseline.get("top_flags", {}),
            },
            "candidate": {
                "name": candidate_name,
                "play_v2_narration_profile": candidate_payload["author_summary"]["config"]["play_v2_narration_profile"],
                **candidate_means,
                "top_flags": candidate.get("top_flags", {}),
            },
        },
        "delta": {
            key: round(candidate_means[key] - baseline_means[key], 4)
            for key in PLAY_EVAL_KEYS
        },
        "flag_delta": _flag_delta(
            dict(baseline.get("top_flags") or {}),
            dict(candidate.get("top_flags") or {}),
        ),
        "case_deltas": case_deltas,
    }


def _llm_text_audit_ab_summary(
    *,
    baseline_name: str,
    baseline_payload: dict[str, Any],
    candidate_name: str,
    candidate_payload: dict[str, Any],
) -> dict[str, Any]:
    baseline = dict(baseline_payload.get("llm_text_audit_summary") or {})
    candidate = dict(candidate_payload.get("llm_text_audit_summary") or {})
    baseline_cases = _case_rows_by_id(baseline)
    candidate_cases = _case_rows_by_id(candidate)
    case_deltas: list[dict[str, Any]] = []
    for case_id in sorted(set(baseline_cases) | set(candidate_cases)):
        base = baseline_cases.get(case_id, {})
        exp = candidate_cases.get(case_id, {})
        case_deltas.append(
            {
                "case_id": case_id,
                **{
                    key: round(float(exp.get(key, 0.0)) - float(base.get(key, 0.0)), 4)
                    for key in LLM_TEXT_AUDIT_KEYS
                },
            }
        )
    return {
        "baseline_variant": baseline_name,
        "candidate_variant": candidate_name,
        "variants": {
            "baseline": {
                "name": baseline_name,
                "play_v2_narration_profile": baseline_payload["author_summary"]["config"]["play_v2_narration_profile"],
                **{key: _mean_case_metric(baseline, key) for key in LLM_TEXT_AUDIT_KEYS},
                "top_flags": baseline.get("top_flags", {}),
            },
            "candidate": {
                "name": candidate_name,
                "play_v2_narration_profile": candidate_payload["author_summary"]["config"]["play_v2_narration_profile"],
                **{key: _mean_case_metric(candidate, key) for key in LLM_TEXT_AUDIT_KEYS},
                "top_flags": candidate.get("top_flags", {}),
            },
        },
        "delta": {
            key: round(_mean_case_metric(candidate, key) - _mean_case_metric(baseline, key), 4)
            for key in LLM_TEXT_AUDIT_KEYS
        },
        "flag_delta": _flag_delta(
            dict(baseline.get("top_flags") or {}),
            dict(candidate.get("top_flags") or {}),
        ),
        "case_deltas": case_deltas,
    }


def _effect_report(ab_summary: dict[str, Any]) -> str:
    delta = dict(ab_summary["delta"])
    flag_delta = dict(ab_summary["flag_delta"])
    lines = [
        "# Light Play Eval Effect Report",
        "",
        "## Aggregate Delta",
        "",
    ]
    for key in PLAY_EVAL_KEYS:
        lines.append(f"- `{key}`: {float(delta.get(key, 0.0)):+.4f}")
    lines.extend(["", "## Flag Delta", ""])
    for key, value in sorted(flag_delta.items()):
        lines.append(f"- `{key}`: {int(value):+d}")
    return "\n".join(lines) + "\n"


def _llm_text_effect_report(ab_summary: dict[str, Any]) -> str:
    delta = dict(ab_summary["delta"])
    flag_delta = dict(ab_summary["flag_delta"])
    lines = [
        "# Light LLM Text Audit Effect Report",
        "",
        "## Aggregate Delta",
        "",
    ]
    for key in LLM_TEXT_AUDIT_KEYS:
        lines.append(f"- `{key}`: {float(delta.get(key, 0.0)):+.4f}")
    lines.extend(["", "## Flag Delta", ""])
    for key, value in sorted(flag_delta.items()):
        lines.append(f"- `{key}`: {int(value):+d}")
    return "\n".join(lines) + "\n"


def _failure_score_for_case_row(row: dict[str, Any]) -> int:
    counts = dict(row.get("turn_flag_counts") or {})
    return sum(int(counts.get(flag, 0) or 0) for flag in FAILURE_PACK_FLAGS)


def _build_failure_pack(
    *,
    case_catalog: list[UrbanGoldCase],
    baseline_summary: dict[str, Any],
) -> dict[str, Any]:
    by_case_id = {case.case_id: case for case in case_catalog}
    rows = list(baseline_summary.get("cases") or [])
    ranked = sorted(
        rows,
        key=lambda row: (
            _failure_score_for_case_row(dict(row)),
            -float(dict(row).get("avg_payoff_realization", 0.0)),
            -float(dict(row).get("avg_turn_intent_binding", 0.0)),
            str(dict(row).get("case_id") or ""),
        ),
        reverse=True,
    )
    selected_rows: list[dict[str, Any]] = []
    for row in ranked:
        case_id = str(dict(row).get("case_id") or "")
        if case_id not in by_case_id:
            continue
        if _failure_score_for_case_row(dict(row)) <= 0:
            continue
        selected_rows.append(dict(row))
        if len(selected_rows) >= FAILURE_PACK_MAX_CASES:
            break
    selected_case_ids = [str(row.get("case_id") or "") for row in selected_rows]
    selected_case_catalog = [by_case_id[case_id] for case_id in selected_case_ids if case_id in by_case_id]
    total_focus_flags = sum(_failure_score_for_case_row(row) for row in selected_rows)
    return {
        "focus_flags": list(FAILURE_PACK_FLAGS),
        "selected_case_ids": selected_case_ids,
        "selected_case_count": len(selected_case_ids),
        "total_focus_flags": total_focus_flags,
        "cases": [
            {
                "case_id": case.case_id,
                "shell": case.expected_shell,
                "expected_template_id": case.expected_template_id,
                "focus_flag_score": _failure_score_for_case_row(row),
                "turn_flag_counts": {
                    flag: int(dict(row.get("turn_flag_counts") or {}).get(flag, 0) or 0)
                    for flag in FAILURE_PACK_FLAGS
                },
                "avg_payoff_realization": float(row.get("avg_payoff_realization", 0.0)),
                "avg_turn_intent_binding": float(row.get("avg_turn_intent_binding", 0.0)),
            }
            for case, row in zip(selected_case_catalog, selected_rows)
        ],
    }


def _focus_flag_totals(summary: dict[str, Any], case_ids: list[str]) -> dict[str, int]:
    rows_by_id = _case_rows_by_id(summary)
    totals = {flag: 0 for flag in FAILURE_PACK_FLAGS}
    for case_id in case_ids:
        row = dict(rows_by_id.get(case_id) or {})
        counts = dict(row.get("turn_flag_counts") or {})
        for flag in FAILURE_PACK_FLAGS:
            totals[flag] += int(counts.get(flag, 0) or 0)
    return totals


def _failure_pack_eval_summary(
    *,
    baseline_name: str,
    baseline_payload: dict[str, Any],
    candidate_name: str,
    candidate_payload: dict[str, Any] | None,
    fallback_candidate_payload: dict[str, Any],
    failure_pack: dict[str, Any],
) -> dict[str, Any]:
    selected_case_ids = [str(case_id) for case_id in list(failure_pack.get("selected_case_ids") or []) if str(case_id)]
    if not selected_case_ids:
        return {
            "baseline_variant": baseline_name,
            "candidate_variant": candidate_name,
            "focus_flags": list(FAILURE_PACK_FLAGS),
            "selected_case_ids": [],
            "selected_case_count": 0,
            "replayed": False,
            "replay_source": "skipped",
            "reproduction_rate": 0.0,
            "baseline_focus_flag_totals": {flag: 0 for flag in FAILURE_PACK_FLAGS},
            "candidate_focus_flag_totals": {flag: 0 for flag in FAILURE_PACK_FLAGS},
            "focus_flag_delta": {flag: 0 for flag in FAILURE_PACK_FLAGS},
            "delta": {key: 0.0 for key in PLAY_EVAL_KEYS},
            "case_deltas": [],
        }
    baseline_summary = baseline_payload["play_eval_summary"]
    replay_payload = candidate_payload or fallback_candidate_payload
    candidate_summary = replay_payload["play_eval_summary"]
    baseline_rows = _case_rows_by_id(baseline_summary)
    candidate_rows = _case_rows_by_id(candidate_summary)
    case_deltas: list[dict[str, Any]] = []
    reproduction_hits = 0
    for case_id in selected_case_ids:
        base_row = dict(baseline_rows.get(case_id) or {})
        exp_row = dict(candidate_rows.get(case_id) or {})
        candidate_focus_hits = sum(
            int(dict(exp_row.get("turn_flag_counts") or {}).get(flag, 0) or 0)
            for flag in FAILURE_PACK_FLAGS
        )
        if candidate_focus_hits > 0:
            reproduction_hits += 1
        case_deltas.append(
            {
                "case_id": case_id,
                **{
                    key: round(float(exp_row.get(key, 0.0)) - float(base_row.get(key, 0.0)), 4)
                    for key in PLAY_EVAL_KEYS
                },
            }
        )
    baseline_flag_totals = _focus_flag_totals(baseline_summary, selected_case_ids)
    candidate_flag_totals = _focus_flag_totals(candidate_summary, selected_case_ids)
    flag_delta = _flag_delta(baseline_flag_totals, candidate_flag_totals)
    return {
        "baseline_variant": baseline_name,
        "candidate_variant": candidate_name,
        "focus_flags": list(FAILURE_PACK_FLAGS),
        "selected_case_ids": selected_case_ids,
        "selected_case_count": len(selected_case_ids),
        "replayed": candidate_payload is not None,
        "replay_source": "candidate_failure_pack" if candidate_payload is not None else "candidate_main_subset",
        "reproduction_rate": round(reproduction_hits / max(len(selected_case_ids), 1), 4),
        "baseline_focus_flag_totals": baseline_flag_totals,
        "candidate_focus_flag_totals": candidate_flag_totals,
        "focus_flag_delta": flag_delta,
        "delta": {
            key: round(
                _mean_case_metric_for_ids(candidate_summary, key, selected_case_ids)
                - _mean_case_metric_for_ids(baseline_summary, key, selected_case_ids),
                4,
            )
            for key in PLAY_EVAL_KEYS
        },
        "case_deltas": case_deltas,
    }


def _generalization_effect_report(main_ab: dict[str, Any], holdout_ab: dict[str, Any]) -> str:
    lines = [
        "# Light Generalization Effect Report",
        "",
        "| Metric | 8-case Delta | Holdout Delta |",
        "| --- | ---: | ---: |",
    ]
    for key in GENERALIZATION_KEYS:
        main_delta = float(main_ab.get("delta", {}).get(key, 0.0))
        holdout_delta = float(holdout_ab.get("delta", {}).get(key, 0.0))
        lines.append(f"| `{key}` | {main_delta:+.4f} | {holdout_delta:+.4f} |")
    lines.extend(["", "## Gate Check", ""])
    for key in GENERALIZATION_KEYS:
        main_delta = float(main_ab.get("delta", {}).get(key, 0.0))
        holdout_delta = float(holdout_ab.get("delta", {}).get(key, 0.0))
        passed = main_delta >= 0 and holdout_delta >= 0
        lines.append(f"- `{key}`: {'PASS' if passed else 'FAIL'} (8-case={main_delta:+.4f}, holdout={holdout_delta:+.4f})")
    return "\n".join(lines) + "\n"


def _play_eval_signature(summary: dict[str, Any], *, expected_case_ids: list[str]) -> str:
    return play_eval_signature(summary, expected_case_ids=expected_case_ids)


def _load_variant_payload(
    artifacts_dir: Path,
    *,
    require_llm_text_audit: bool,
    require_persona_coverage: bool,
) -> dict[str, Any]:
    author_summary_path = artifacts_dir / "author_summary.json"
    play_eval_summary_path = artifacts_dir / "play_eval_summary.json"
    if not author_summary_path.exists() or not play_eval_summary_path.exists():
        raise RuntimeError(
            f"baseline artifacts incomplete under `{artifacts_dir}`; "
            "expected author_summary.json and play_eval_summary.json"
        )
    payload: dict[str, Any] = {
        "artifacts_dir": str(artifacts_dir),
        "author_summary": json.loads(author_summary_path.read_text()),
        "play_eval_summary": json.loads(play_eval_summary_path.read_text()),
    }
    llm_path = artifacts_dir / "llm_text_audit_summary.json"
    if llm_path.exists():
        payload["llm_text_audit_summary"] = json.loads(llm_path.read_text())
    elif require_llm_text_audit:
        raise RuntimeError(
            f"checkpoint requires `{llm_path}`; refresh baseline lock artifacts before running light AB."
        )
    else:
        payload["llm_text_audit_summary"] = None
    coverage_path = artifacts_dir / "persona_coverage_summary.json"
    if coverage_path.exists():
        payload["persona_coverage_summary"] = json.loads(coverage_path.read_text())
    elif require_persona_coverage:
        raise RuntimeError(
            f"baseline artifacts missing `{coverage_path}`; refresh baseline lock artifacts before running light AB."
        )
    else:
        payload["persona_coverage_summary"] = None
    return payload


def _load_baseline_lock(
    *,
    baseline_lock: Path,
    expected_case_ids: list[str],
    require_llm_text_audit: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not baseline_lock.exists():
        raise RuntimeError(
            f"baseline lock `{baseline_lock}` not found. "
            "Run a baseline refresh first and write the lock file."
        )
    try:
        lock_payload = json.loads(baseline_lock.read_text())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"baseline lock `{baseline_lock}` is invalid JSON: {exc}") from exc
    required_fields = {
        "baseline_name",
        "baseline_profile",
        "baseline_artifacts_dir",
        "baseline_signature",
        "generated_at_utc",
        "schema_version",
    }
    missing = sorted(field for field in required_fields if not str(lock_payload.get(field) or "").strip())
    if missing:
        raise RuntimeError(
            f"baseline lock `{baseline_lock}` missing required fields: {', '.join(missing)}"
        )
    schema_version = int(lock_payload.get("schema_version", 0) or 0)
    if schema_version != BASELINE_LOCK_SCHEMA_VERSION:
        raise RuntimeError(
            "baseline lock schema version mismatch: "
            f"expected {BASELINE_LOCK_SCHEMA_VERSION}, got {schema_version}."
        )
    baseline_artifacts_dir = Path(str(lock_payload["baseline_artifacts_dir"])).expanduser().resolve()
    baseline_payload = _load_variant_payload(
        baseline_artifacts_dir,
        require_llm_text_audit=require_llm_text_audit,
        require_persona_coverage=True,
    )
    computed_signature = _play_eval_signature(
        baseline_payload["play_eval_summary"],
        expected_case_ids=expected_case_ids,
    )
    if computed_signature != str(lock_payload["baseline_signature"]):
        raise RuntimeError(
            "baseline lock signature mismatch. baseline artifacts changed or lock is stale; "
            "refresh baseline and regenerate lock."
        )
    lock_payload["baseline_artifacts_dir"] = str(baseline_artifacts_dir)
    return lock_payload, baseline_payload


def _load_holdout_baseline_payload(
    *,
    lock_payload: dict[str, Any],
    holdout_case_ids: list[str],
) -> dict[str, Any]:
    holdout_dir_raw = str(lock_payload.get("baseline_holdout_artifacts_dir") or "").strip()
    holdout_signature = str(lock_payload.get("baseline_holdout_signature") or "").strip()
    if not holdout_dir_raw or not holdout_signature:
        raise RuntimeError(
            "holdout checkpoint requested but baseline lock does not include "
            "`baseline_holdout_artifacts_dir` and `baseline_holdout_signature`."
        )
    holdout_dir = Path(holdout_dir_raw).expanduser().resolve()
    payload = _load_variant_payload(
        holdout_dir,
        require_llm_text_audit=False,
        require_persona_coverage=False,
    )
    computed_signature = _play_eval_signature(
        payload["play_eval_summary"],
        expected_case_ids=holdout_case_ids,
    )
    if computed_signature != holdout_signature:
        raise RuntimeError(
            "baseline holdout signature mismatch. Refresh baseline holdout artifacts and lock."
        )
    return payload


def _persona_coverage_report(
    *,
    baseline_name: str,
    baseline_payload: dict[str, Any],
    candidate_name: str,
    candidate_payload: dict[str, Any],
) -> dict[str, Any]:
    baseline = dict(baseline_payload.get("persona_coverage_summary") or {})
    candidate = dict(candidate_payload.get("persona_coverage_summary") or {})
    baseline_cases = {
        str(row["case_id"]): row
        for row in list(baseline.get("cases") or [])
    }
    candidate_cases = {
        str(row["case_id"]): row
        for row in list(candidate.get("cases") or [])
    }
    case_rows: list[dict[str, Any]] = []
    for case_id in sorted(set(baseline_cases) | set(candidate_cases)):
        base = baseline_cases.get(case_id, {})
        exp = candidate_cases.get(case_id, {})
        case_rows.append(
            {
                "case_id": case_id,
                "baseline_successful_personas": int(base.get("successful_persona_count", 0) or 0),
                "candidate_successful_personas": int(exp.get("successful_persona_count", 0) or 0),
                "delta_successful_personas": int(exp.get("successful_persona_count", 0) or 0) - int(base.get("successful_persona_count", 0) or 0),
                "baseline_failed_personas": list(base.get("failed_persona_ids") or []),
                "candidate_failed_personas": list(exp.get("failed_persona_ids") or []),
                "baseline_avg_turns": float(base.get("avg_turns_successful_personas", 0.0) or 0.0),
                "candidate_avg_turns": float(exp.get("avg_turns_successful_personas", 0.0) or 0.0),
                "candidate_valid": bool(exp.get("is_valid")),
            }
        )
    baseline_avg_success = float(baseline.get("avg_successful_persona_count", 0.0) or 0.0)
    candidate_avg_success = float(candidate.get("avg_successful_persona_count", 0.0) or 0.0)
    baseline_avg_session_eval_success = float(baseline.get("avg_session_eval_successful_persona_count", 0.0) or 0.0)
    candidate_avg_session_eval_success = float(candidate.get("avg_session_eval_successful_persona_count", 0.0) or 0.0)
    return {
        "baseline_variant": baseline_name,
        "candidate_variant": candidate_name,
        "min_success_personas_required": int(candidate.get("min_success_personas_required", 4) or 4),
        "expected_persona_count": int(candidate.get("expected_persona_count", 5) or 5),
        "baseline_invalid_case_count": int(baseline.get("invalid_case_count", 0) or 0),
        "candidate_invalid_case_count": int(candidate.get("invalid_case_count", 0) or 0),
        "baseline_invalid_case_ids": list(baseline.get("invalid_case_ids") or []),
        "candidate_invalid_case_ids": list(candidate.get("invalid_case_ids") or []),
        "baseline_avg_successful_persona_count": round(baseline_avg_success, 4),
        "candidate_avg_successful_persona_count": round(candidate_avg_success, 4),
        "delta_avg_successful_persona_count": round(candidate_avg_success - baseline_avg_success, 4),
        "baseline_avg_session_eval_successful_persona_count": round(baseline_avg_session_eval_success, 4),
        "candidate_avg_session_eval_successful_persona_count": round(candidate_avg_session_eval_success, 4),
        "delta_avg_session_eval_successful_persona_count": round(
            candidate_avg_session_eval_success - baseline_avg_session_eval_success,
            4,
        ),
        "baseline_quality_invalid_case_count": int(baseline.get("quality_invalid_case_count", 0) or 0),
        "candidate_quality_invalid_case_count": int(candidate.get("quality_invalid_case_count", 0) or 0),
        "baseline_quality_invalid_case_ids": list(baseline.get("quality_invalid_case_ids") or []),
        "candidate_quality_invalid_case_ids": list(candidate.get("quality_invalid_case_ids") or []),
        "baseline_quality_eval_incomplete_case_count": int(baseline.get("quality_eval_incomplete_case_count", 0) or 0),
        "candidate_quality_eval_incomplete_case_count": int(candidate.get("quality_eval_incomplete_case_count", 0) or 0),
        "baseline_quality_eval_incomplete_case_ids": list(baseline.get("quality_eval_incomplete_case_ids") or []),
        "candidate_quality_eval_incomplete_case_ids": list(candidate.get("quality_eval_incomplete_case_ids") or []),
        "cases": case_rows,
    }


def _should_run_holdout(run_seq: int, force_holdout: bool) -> bool:
    return force_holdout or run_seq % 3 == 0


def _should_run_llm_text_audit(run_seq: int, force_llm_audit: bool) -> bool:
    return force_llm_audit or run_seq % 2 == 0


def run_light_ab_eval(
    output_dir: Path,
    *,
    candidate_name: str,
    run_seq: int,
    case_max_workers: int = 40,
    total_rpm_limit: int = 200,
    baseline_lock: Path = BASELINE_LOCK_DEFAULT,
    force_holdout: bool = False,
    force_llm_audit: bool = False,
    chaos_rollout: str = "off",
    chaos_shadow_count: int = CHAOS_SHADOW_DEFAULT_COUNT,
    case_timeout_seconds: float = 150.0,
    case_aggregate_timeout_seconds: float = 360.0,
    session_play_eval_timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    if run_seq <= 0:
        raise RuntimeError("`run_seq` must be a positive integer.")
    if run_seq % 2 == 0 and not (force_holdout or force_llm_audit):
        raise RuntimeError(
            "`run_seq` must be odd for stable mainline runs; "
            "use --force-holdout/--force-llm-audit to run checkpoint on even sequences."
        )
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    case_catalog = _select_light_case_catalog(v1_topic_gold_14())
    holdout_catalog = build_holdout_case_catalog(case_catalog)
    _write_json(root / "light_case_set.json", case_catalog)
    run_holdout = _should_run_holdout(run_seq, force_holdout)
    run_llm_audit = _should_run_llm_text_audit(run_seq, force_llm_audit)
    _write_json(root / "light_holdout_case_set.json", holdout_catalog)
    case_ids = [case.case_id for case in case_catalog]
    holdout_case_ids = [case.case_id for case in holdout_catalog]
    if chaos_rollout not in {"off", "shadow", "full"}:
        raise RuntimeError("`chaos_rollout` must be one of: off|shadow|full")
    if chaos_rollout == "off":
        chaos_shadow_case_ids: list[str] = []
    elif chaos_rollout == "full":
        chaos_shadow_case_ids = list(case_ids)
    else:
        chaos_shadow_case_ids = _select_chaos_shadow_case_ids(case_catalog, count=chaos_shadow_count)
    lock_payload, baseline_payload = _load_baseline_lock(
        baseline_lock=baseline_lock,
        expected_case_ids=case_ids,
        require_llm_text_audit=run_llm_audit,
    )
    failure_pack = _build_failure_pack(
        case_catalog=case_catalog,
        baseline_summary=baseline_payload["play_eval_summary"],
    )
    _write_json(root / "light_failure_pack.json", failure_pack)
    failure_pack_catalog = [
        case
        for case in case_catalog
        if case.case_id in set(failure_pack.get("selected_case_ids") or [])
    ]

    def _run_case_eval_with_timeout_compat(output_path: Path, **kwargs: Any) -> dict[str, Any]:
        try:
            return run_case_catalog_live_eval(
                output_path,
                case_timeout_seconds=case_timeout_seconds,
                case_aggregate_timeout_seconds=case_aggregate_timeout_seconds,
                session_play_eval_timeout_seconds=session_play_eval_timeout_seconds,
                **kwargs,
            )
        except TypeError as exc:
            message = str(exc)
            if (
                "case_timeout_seconds" not in message
                and "case_aggregate_timeout_seconds" not in message
                and "session_play_eval_timeout_seconds" not in message
            ):
                raise
            try:
                return run_case_catalog_live_eval(
                    output_path,
                    case_timeout_seconds=case_timeout_seconds,
                    **kwargs,
                )
            except TypeError as exc_timeout_only:
                if "case_timeout_seconds" not in str(exc_timeout_only):
                    raise
                return run_case_catalog_live_eval(output_path, **kwargs)

    rpm_budget = _build_rpm_budget(total_rpm_limit)
    with strict_no_repair_fallback(enabled=True):
        with rpm_budget_limits(
            total_rpm_limit=rpm_budget["total"],
        ):
            candidate_chaos_kwargs = {"chaos_shadow_case_ids": chaos_shadow_case_ids} if chaos_shadow_case_ids else {}
            candidate_failure_payload: dict[str, Any] | None = None
            if failure_pack_catalog:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    candidate_future = executor.submit(
                        _run_case_eval_with_timeout_compat,
                        root / "candidate",
                        case_catalog=case_catalog,
                        case_set_filename="light_case_set.json",
                        blockers_filename="light_blockers.md",
                        blockers_title=f"Light AB Blockers ({candidate_name})",
                        enable_llm_text_audit=run_llm_audit,
                        case_max_workers=case_max_workers,
                        **candidate_chaos_kwargs,
                    )
                    failure_pack_shadow_ids = [
                        case.case_id
                        for case in failure_pack_catalog
                        if case.case_id in set(chaos_shadow_case_ids)
                    ]
                    failure_pack_chaos_kwargs = {"chaos_shadow_case_ids": failure_pack_shadow_ids} if failure_pack_shadow_ids else {}
                    failure_future = executor.submit(
                        _run_case_eval_with_timeout_compat,
                        root / "candidate_failure_pack",
                        case_catalog=failure_pack_catalog,
                        case_set_filename="light_failure_pack_case_set.json",
                        blockers_filename="light_failure_pack_blockers.md",
                        blockers_title=f"Light Failure Pack Blockers ({candidate_name})",
                        enable_llm_text_audit=False,
                        case_max_workers=case_max_workers,
                        **failure_pack_chaos_kwargs,
                    )
                    candidate_payload = candidate_future.result()
                    candidate_failure_payload = failure_future.result()
            else:
                candidate_payload = _run_case_eval_with_timeout_compat(
                    root / "candidate",
                    case_catalog=case_catalog,
                    case_set_filename="light_case_set.json",
                    blockers_filename="light_blockers.md",
                    blockers_title=f"Light AB Blockers ({candidate_name})",
                    enable_llm_text_audit=run_llm_audit,
                    case_max_workers=case_max_workers,
                    **candidate_chaos_kwargs,
                )
            candidate_holdout_payload: dict[str, Any] | None = None
            if run_holdout:
                candidate_holdout_payload = _run_case_eval_with_timeout_compat(
                    root / "candidate_holdout",
                    case_catalog=holdout_catalog,
                    case_set_filename="light_holdout_case_set.json",
                    blockers_filename="light_holdout_blockers.md",
                    blockers_title=f"Light AB Holdout Blockers ({candidate_name})",
                    enable_llm_text_audit=False,
                    case_max_workers=case_max_workers,
                )
    baseline_name = str(lock_payload["baseline_name"])
    play_eval_ab_summary = _ab_summary(
        baseline_name=baseline_name,
        baseline_payload=baseline_payload,
        candidate_name=candidate_name,
        candidate_payload=candidate_payload,
    )
    _write_json(root / "light_play_eval_ab_summary.json", play_eval_ab_summary)
    (root / "light_effect_report.md").write_text(_effect_report(play_eval_ab_summary))
    persona_coverage_report = _persona_coverage_report(
        baseline_name=baseline_name,
        baseline_payload=baseline_payload,
        candidate_name=candidate_name,
        candidate_payload=candidate_payload,
    )
    _write_json(root / "light_persona_coverage_report.json", persona_coverage_report)
    failure_pack_eval_summary = _failure_pack_eval_summary(
        baseline_name=baseline_name,
        baseline_payload=baseline_payload,
        candidate_name=candidate_name,
        candidate_payload=candidate_failure_payload,
        fallback_candidate_payload=candidate_payload,
        failure_pack=failure_pack,
    )
    _write_json(root / "light_failure_pack_eval_summary.json", failure_pack_eval_summary)
    semantic_autotune_patch = build_semantic_autotune_patch(
        play_eval_ab_summary=play_eval_ab_summary,
        failure_pack_eval_summary=failure_pack_eval_summary,
    )
    _write_json(root / "light_semantic_autotune_patch.json", semantic_autotune_patch)
    (root / "light_semantic_autotune_notes.md").write_text(render_semantic_autotune_notes(semantic_autotune_patch))
    holdout_summary: dict[str, Any] | None = None
    if run_holdout:
        baseline_holdout_payload = _load_holdout_baseline_payload(
            lock_payload=lock_payload,
            holdout_case_ids=holdout_case_ids,
        )
        if candidate_holdout_payload is None:
            raise RuntimeError("internal error: holdout checkpoint expected candidate holdout payload")
        holdout_ab = _ab_summary(
            baseline_name=baseline_name,
            baseline_payload=baseline_holdout_payload,
            candidate_name=candidate_name,
            candidate_payload=candidate_holdout_payload,
        )
        holdout_summary = {
            "seed": 20260401,
            "case_count": len(holdout_catalog),
            "ab_summary": holdout_ab,
        }
        _write_json(root / "light_holdout_summary.json", holdout_summary)
        (root / "generalization_effect_report.md").write_text(
            _generalization_effect_report(play_eval_ab_summary, holdout_ab)
        )
    llm_text_audit_ab: dict[str, Any] | None = None
    if run_llm_audit:
        llm_text_audit_ab = _llm_text_audit_ab_summary(
            baseline_name=baseline_name,
            baseline_payload=baseline_payload,
            candidate_name=candidate_name,
            candidate_payload=candidate_payload,
        )
        _write_json(root / "light_llm_text_audit_summary.json", llm_text_audit_ab)
        (root / "light_llm_text_audit_effect_report.md").write_text(_llm_text_effect_report(llm_text_audit_ab))
    settings_snapshot = Settings(_env_file=None)
    run_manifest = {
        "run_seq": run_seq,
        "baseline_lock": str(baseline_lock.resolve()),
        "baseline_name": baseline_name,
        "baseline_profile": lock_payload["baseline_profile"],
        "baseline_lock_schema_version": int(lock_payload.get("schema_version", 0) or 0),
        "baseline_generated_at_utc": str(lock_payload.get("generated_at_utc") or ""),
        "baseline_artifacts_dir": str(lock_payload.get("baseline_artifacts_dir") or ""),
        "candidate_name": candidate_name,
        "play_v2_narration_profile": "npc_texture_v2",
        "case_count": len(case_catalog),
        "case_max_workers": case_max_workers,
        "case_timeout_seconds": float(case_timeout_seconds),
        "case_aggregate_timeout_seconds": float(case_aggregate_timeout_seconds),
        "session_play_eval_timeout_seconds": float(session_play_eval_timeout_seconds),
        "failure_pack": {
            "selected_case_count": int(failure_pack.get("selected_case_count", 0) or 0),
            "replayed": candidate_failure_payload is not None,
            "reproduction_rate": float(failure_pack_eval_summary.get("reproduction_rate", 0.0) or 0.0),
        },
        "checkpoint": {
            "run_holdout": run_holdout,
            "run_llm_text_audit": run_llm_audit,
            "holdout_cycle_mod": run_seq % 3,
            "llm_cycle_mod": run_seq % 2,
        },
        "chaos_rollout": {
            "mode": chaos_rollout,
            "shadow_case_count": len(chaos_shadow_case_ids),
            "shadow_case_ids": chaos_shadow_case_ids,
        },
        "rpm_budget": rpm_budget,
        "semantic_strategy_version": 8,
        "policy_cost_visibility_enabled": bool(settings_snapshot.play_v2_policy_cost_visibility_enabled),
        "policy_question_progress_v2_enabled": bool(settings_snapshot.play_v2_policy_question_progress_v2_enabled),
        "policy_role_divergence_v2_enabled": bool(settings_snapshot.play_v2_policy_role_divergence_v2_enabled),
        "strict_no_repair_fallback_enabled": True,
    }
    _write_json(root / "light_run_manifest.json", run_manifest)
    return {
        "artifacts_dir": str(root),
        "run_manifest": run_manifest,
        "candidate": candidate_payload,
        "play_eval_ab_summary": play_eval_ab_summary,
        "persona_coverage_report": persona_coverage_report,
        "light_failure_pack_eval_summary": failure_pack_eval_summary,
        "light_semantic_autotune_patch": semantic_autotune_patch,
        "light_holdout_summary": holdout_summary,
        "light_llm_text_audit_summary": llm_text_audit_ab,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lightweight AB + persona coverage eval.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--candidate-name", required=True)
    parser.add_argument("--run-seq", required=True, type=int)
    parser.add_argument("--case-max-workers", type=int, default=40)
    parser.add_argument("--total-rpm-limit", type=int, default=200)
    parser.add_argument("--case-timeout-seconds", type=float, default=150.0)
    parser.add_argument("--case-aggregate-timeout-seconds", type=float, default=360.0)
    parser.add_argument("--session-play-eval-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--baseline-lock", type=Path, default=BASELINE_LOCK_DEFAULT)
    parser.add_argument("--force-holdout", action="store_true")
    parser.add_argument("--force-llm-audit", action="store_true")
    parser.add_argument("--chaos-rollout", choices=("off", "shadow", "full"), default="off")
    parser.add_argument("--chaos-shadow-count", type=int, default=CHAOS_SHADOW_DEFAULT_COUNT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_light_ab_eval(
        args.output_dir,
        candidate_name=str(args.candidate_name),
        run_seq=int(args.run_seq),
        case_max_workers=int(args.case_max_workers),
        total_rpm_limit=int(args.total_rpm_limit),
        case_timeout_seconds=float(args.case_timeout_seconds),
        case_aggregate_timeout_seconds=float(args.case_aggregate_timeout_seconds),
        session_play_eval_timeout_seconds=float(args.session_play_eval_timeout_seconds),
        baseline_lock=args.baseline_lock,
        force_holdout=bool(args.force_holdout),
        force_llm_audit=bool(args.force_llm_audit),
        chaos_rollout=str(args.chaos_rollout),
        chaos_shadow_count=int(args.chaos_shadow_count),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
