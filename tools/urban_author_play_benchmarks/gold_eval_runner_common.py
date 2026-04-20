from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from rpg_backend.config import Settings
from tools.urban_author_play_benchmarks.gold_eval_v2_metrics import (
    build_gold_eval_v2_effect_report,
    build_gold_eval_v2_outputs,
)
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase
from tools.urban_author_play_benchmarks.light_ab_shared import (
    build_rpm_budget,
    rpm_budget_limits,
    strict_no_repair_fallback,
)
from tools.urban_author_play_benchmarks.live_eval_common import run_case_catalog_live_eval
from tools.urban_author_play_benchmarks.native_cn_live_eval import _write_json


def _distribution_by_band(case_catalog: list[UrbanGoldCase]) -> dict[str, int]:
    if any(case.expected_play_length_preset is not None for case in case_catalog):
        counter = Counter(str(case.expected_play_length_preset or "") for case in case_catalog)
        return {
            "15_20": int(counter.get("15_20", 0)),
            "20_25": int(counter.get("20_25", 0)),
            "30_45": int(counter.get("30_45", 0)),
        }
    counter = Counter(str(case.expected_band) for case in case_catalog)
    return {
        "5_8": int(counter.get("5_8", 0)),
        "8_15": int(counter.get("8_15", 0)),
        "15_25": int(counter.get("15_25", 0)),
    }


def _distribution_by_experience_band(case_catalog: list[UrbanGoldCase]) -> dict[str, int]:
    counter = Counter(str(case.expected_band) for case in case_catalog)
    return {
        "5_8": int(counter.get("5_8", 0)),
        "8_15": int(counter.get("8_15", 0)),
        "15_25": int(counter.get("15_25", 0)),
    }


def _distribution_by_shell(case_catalog: list[UrbanGoldCase]) -> dict[str, int]:
    counter = Counter(str(case.expected_shell) for case in case_catalog)
    return {shell: int(counter[shell]) for shell in sorted(counter.keys())}


def _turn_target_for_suite(*, suite_type: str, profile: str) -> int:
    normalized_suite = str(suite_type).strip().lower()
    normalized_profile = str(profile).strip().lower()
    if normalized_suite == "mini":
        return 12
    if normalized_suite == "full" and normalized_profile == "heavy":
        return 15
    return 14


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = line.strip()
        if not payload:
            continue
        rows.append(json.loads(payload))
    return rows


def _turn_input_mode_from_turn_log(turn_log: dict[str, Any]) -> str:
    raw = str(turn_log.get("turn_input_mode") or "").strip().lower()
    if raw in {"free_input", "select_id"}:
        return raw
    submitted = turn_log.get("submitted_with_selected_ids")
    return "select_id" if bool(submitted) else "free_input"


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(int(round(float(value))), 0)
    return 0


def _collect_play_token_stats(artifacts_dir: Path) -> tuple[dict[str, Any], dict[tuple[str, str, int], dict[str, int]]]:
    deep_play_root = artifacts_dir / "deep_play"
    by_input_mode = {
        "free_input": {
            "turn_count": 0,
            "play_total_tokens": 0,
            "pre_submit_total_tokens": 0,
            "post_submit_total_tokens": 0,
        },
        "select_id": {
            "turn_count": 0,
            "play_total_tokens": 0,
            "pre_submit_total_tokens": 0,
            "post_submit_total_tokens": 0,
        },
    }
    summary = {
        "turn_count": 0,
        "play_total_tokens": 0,
        "pre_submit_total_tokens": 0,
        "post_submit_total_tokens": 0,
    }
    aligned_turns: dict[tuple[str, str, int], dict[str, int]] = {}
    if not deep_play_root.exists():
        summary["by_input_mode"] = by_input_mode
        summary["pre_submit_share"] = 0.0
        summary["post_submit_share"] = 0.0
        return summary, aligned_turns
    for turn_log_path in deep_play_root.glob("*/**/personas/*/turn_logs.jsonl"):
        try:
            case_id = turn_log_path.parents[3].name
            persona_id_default = turn_log_path.parents[1].name
        except Exception:  # noqa: BLE001
            continue
        for turn_log in _read_jsonl(turn_log_path):
            turn_index = _to_int(turn_log.get("turn_index"))
            if turn_index <= 0:
                continue
            persona_id = str(turn_log.get("persona_id") or persona_id_default or "").strip() or persona_id_default
            mode = _turn_input_mode_from_turn_log(turn_log)
            mode_bucket = by_input_mode["select_id" if mode == "select_id" else "free_input"]
            pre_submit_tokens = _to_int(turn_log.get("pre_submit_total_tokens"))
            post_submit_tokens = _to_int(turn_log.get("post_submit_total_tokens"))
            play_turn_total_tokens = _to_int(turn_log.get("play_turn_total_tokens"))
            if play_turn_total_tokens <= 0:
                play_turn_total_tokens = pre_submit_tokens + post_submit_tokens
            summary["turn_count"] += 1
            summary["pre_submit_total_tokens"] += pre_submit_tokens
            summary["post_submit_total_tokens"] += post_submit_tokens
            summary["play_total_tokens"] += play_turn_total_tokens
            mode_bucket["turn_count"] += 1
            mode_bucket["pre_submit_total_tokens"] += pre_submit_tokens
            mode_bucket["post_submit_total_tokens"] += post_submit_tokens
            mode_bucket["play_total_tokens"] += play_turn_total_tokens
            aligned_turns[(case_id, persona_id, turn_index)] = {
                "pre_submit_total_tokens": pre_submit_tokens,
                "post_submit_total_tokens": post_submit_tokens,
                "play_turn_total_tokens": play_turn_total_tokens,
            }
    summary["by_input_mode"] = by_input_mode
    total = max(int(summary["play_total_tokens"]), 0)
    summary["pre_submit_share"] = round((summary["pre_submit_total_tokens"] / total), 4) if total > 0 else 0.0
    summary["post_submit_share"] = round((summary["post_submit_total_tokens"] / total), 4) if total > 0 else 0.0
    for mode in ("free_input", "select_id"):
        mode_total = max(int(by_input_mode[mode]["play_total_tokens"]), 0)
        by_input_mode[mode]["pre_submit_share"] = (
            round((by_input_mode[mode]["pre_submit_total_tokens"] / mode_total), 4) if mode_total > 0 else 0.0
        )
        by_input_mode[mode]["post_submit_share"] = (
            round((by_input_mode[mode]["post_submit_total_tokens"] / mode_total), 4) if mode_total > 0 else 0.0
        )
    return summary, aligned_turns


def _resolve_baseline_artifacts_dir(*, root: Path, explicit_baseline_artifacts_dir: Path | None) -> Path | None:
    if explicit_baseline_artifacts_dir is not None:
        candidate = explicit_baseline_artifacts_dir.resolve()
        if (candidate / "performance_summary.json").exists():
            return candidate
        return None
    parent_dir = root.parent
    if not parent_dir.exists():
        return None
    candidates = [
        path
        for path in parent_dir.iterdir()
        if path.is_dir()
        and path != root
        and (path / "performance_summary.json").exists()
        and (path / "play_eval_summary.json").exists()
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def _build_play_token_uplift(
    *,
    root: Path,
    explicit_baseline_artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    candidate_summary, candidate_turns = _collect_play_token_stats(root)
    baseline_dir = _resolve_baseline_artifacts_dir(
        root=root,
        explicit_baseline_artifacts_dir=explicit_baseline_artifacts_dir,
    )
    payload: dict[str, Any] = {
        "candidate_artifacts_dir": str(root),
        "baseline_artifacts_dir": str(baseline_dir) if baseline_dir is not None else None,
        "resolved": baseline_dir is not None,
        "candidate": candidate_summary,
    }
    if baseline_dir is None:
        payload["reason"] = "baseline_not_found"
        payload["baseline"] = {}
        payload["delta"] = {}
        payload["turn_alignment"] = {
            "candidate_turn_count": candidate_summary.get("turn_count", 0),
            "baseline_turn_count": 0,
            "matched_turn_count": 0,
            "coverage_vs_candidate": 0.0,
            "coverage_vs_baseline": 0.0,
            "mean_delta_play_turn_total_tokens": 0.0,
        }
        return payload

    baseline_summary, baseline_turns = _collect_play_token_stats(baseline_dir)
    payload["baseline"] = baseline_summary
    delta = {
        "play_total_tokens": candidate_summary.get("play_total_tokens", 0) - baseline_summary.get("play_total_tokens", 0),
        "pre_submit_total_tokens": candidate_summary.get("pre_submit_total_tokens", 0) - baseline_summary.get("pre_submit_total_tokens", 0),
        "post_submit_total_tokens": candidate_summary.get("post_submit_total_tokens", 0) - baseline_summary.get("post_submit_total_tokens", 0),
        "pre_submit_share": round(
            float(candidate_summary.get("pre_submit_share", 0.0)) - float(baseline_summary.get("pre_submit_share", 0.0)),
            4,
        ),
        "post_submit_share": round(
            float(candidate_summary.get("post_submit_share", 0.0)) - float(baseline_summary.get("post_submit_share", 0.0)),
            4,
        ),
        "by_input_mode": {},
    }
    for mode in ("free_input", "select_id"):
        cand_mode = dict((candidate_summary.get("by_input_mode") or {}).get(mode) or {})
        base_mode = dict((baseline_summary.get("by_input_mode") or {}).get(mode) or {})
        delta["by_input_mode"][mode] = {
            "play_total_tokens": int(cand_mode.get("play_total_tokens", 0)) - int(base_mode.get("play_total_tokens", 0)),
            "pre_submit_total_tokens": int(cand_mode.get("pre_submit_total_tokens", 0)) - int(base_mode.get("pre_submit_total_tokens", 0)),
            "post_submit_total_tokens": int(cand_mode.get("post_submit_total_tokens", 0)) - int(base_mode.get("post_submit_total_tokens", 0)),
            "pre_submit_share": round(
                float(cand_mode.get("pre_submit_share", 0.0)) - float(base_mode.get("pre_submit_share", 0.0)),
                4,
            ),
            "post_submit_share": round(
                float(cand_mode.get("post_submit_share", 0.0)) - float(base_mode.get("post_submit_share", 0.0)),
                4,
            ),
        }
    payload["delta"] = delta
    shared_keys = set(candidate_turns.keys()) & set(baseline_turns.keys())
    per_turn_deltas = [
        candidate_turns[key]["play_turn_total_tokens"] - baseline_turns[key]["play_turn_total_tokens"]
        for key in shared_keys
    ]
    candidate_turn_count = int(candidate_summary.get("turn_count", 0))
    baseline_turn_count = int(baseline_summary.get("turn_count", 0))
    payload["turn_alignment"] = {
        "candidate_turn_count": candidate_turn_count,
        "baseline_turn_count": baseline_turn_count,
        "matched_turn_count": len(shared_keys),
        "coverage_vs_candidate": round((len(shared_keys) / candidate_turn_count), 4) if candidate_turn_count > 0 else 0.0,
        "coverage_vs_baseline": round((len(shared_keys) / baseline_turn_count), 4) if baseline_turn_count > 0 else 0.0,
        "mean_delta_play_turn_total_tokens": round(
            (sum(per_turn_deltas) / len(per_turn_deltas)),
            4,
        ) if per_turn_deltas else 0.0,
    }
    return payload


def _play_token_uplift_markdown(payload: dict[str, Any]) -> str:
    candidate = dict(payload.get("candidate") or {})
    baseline = dict(payload.get("baseline") or {})
    delta = dict(payload.get("delta") or {})
    lines = ["# Play Token Uplift vs Baseline", ""]
    lines.append(f"- candidate: `{payload.get('candidate_artifacts_dir', '')}`")
    lines.append(f"- baseline: `{payload.get('baseline_artifacts_dir', '')}`")
    lines.append(f"- baseline_resolved: `{bool(payload.get('resolved'))}`")
    if not bool(payload.get("resolved")):
        lines.append(f"- reason: `{payload.get('reason', 'baseline_not_found')}`")
    lines.extend(["", "## Global", ""])
    lines.append(
        f"- play_total_tokens: {int(candidate.get('play_total_tokens', 0))} "
        f"(delta {int(delta.get('play_total_tokens', 0)):+d})"
    )
    lines.append(
        f"- pre_submit_total_tokens: {int(candidate.get('pre_submit_total_tokens', 0))} "
        f"(delta {int(delta.get('pre_submit_total_tokens', 0)):+d})"
    )
    lines.append(
        f"- post_submit_total_tokens: {int(candidate.get('post_submit_total_tokens', 0))} "
        f"(delta {int(delta.get('post_submit_total_tokens', 0)):+d})"
    )
    lines.append(
        f"- pre_submit_share: {float(candidate.get('pre_submit_share', 0.0)):.4f} "
        f"(delta {float(delta.get('pre_submit_share', 0.0)):+.4f})"
    )
    lines.append(
        f"- post_submit_share: {float(candidate.get('post_submit_share', 0.0)):.4f} "
        f"(delta {float(delta.get('post_submit_share', 0.0)):+.4f})"
    )
    lines.extend(["", "## By Input Mode", ""])
    for mode in ("free_input", "select_id"):
        cand_mode = dict((candidate.get("by_input_mode") or {}).get(mode) or {})
        base_mode = dict((baseline.get("by_input_mode") or {}).get(mode) or {})
        delta_mode = dict((delta.get("by_input_mode") or {}).get(mode) or {})
        lines.append(f"### {mode}")
        lines.append(
            f"- play_total_tokens: {int(cand_mode.get('play_total_tokens', 0))} "
            f"(baseline {int(base_mode.get('play_total_tokens', 0))}, delta {int(delta_mode.get('play_total_tokens', 0)):+d})"
        )
        lines.append(
            f"- pre_submit_share: {float(cand_mode.get('pre_submit_share', 0.0)):.4f} "
            f"(delta {float(delta_mode.get('pre_submit_share', 0.0)):+.4f})"
        )
        lines.append(
            f"- post_submit_share: {float(cand_mode.get('post_submit_share', 0.0)):.4f} "
            f"(delta {float(delta_mode.get('post_submit_share', 0.0)):+.4f})"
        )
        lines.append("")
    align = dict(payload.get("turn_alignment") or {})
    lines.extend(["## Turn Alignment", ""])
    lines.append(
        f"- matched_turn_count: {int(align.get('matched_turn_count', 0))} "
        f"/ candidate {int(align.get('candidate_turn_count', 0))} / baseline {int(align.get('baseline_turn_count', 0))}"
    )
    lines.append(
        f"- coverage_vs_candidate: {float(align.get('coverage_vs_candidate', 0.0)):.4f}, "
        f"coverage_vs_baseline: {float(align.get('coverage_vs_baseline', 0.0)):.4f}"
    )
    lines.append(
        f"- mean_delta_play_turn_total_tokens: {float(align.get('mean_delta_play_turn_total_tokens', 0.0)):+.4f}"
    )
    return "\n".join(lines).rstrip() + "\n"


def run_gold_eval_suite(
    *,
    output_dir: Path,
    suite_type: str,
    profile: str,
    case_catalog: list[UrbanGoldCase],
    case_set_filename: str,
    blockers_filename: str,
    blockers_title: str,
    case_max_workers: int,
    total_rpm_limit: int,
    case_timeout_seconds: float,
    case_aggregate_timeout_seconds: float,
    session_play_eval_timeout_seconds: float,
    select_id_probability: float = 0.1,
    typing_rhythm_enabled: bool = False,
    draft_intent_probability: float = 0.2,
    draft_call_count_min: int = 1,
    draft_call_count_max: int = 1,
    draft_debounce_ms: int = 250,
    session_play_eval_persona_limit: int | None = 3,
    llm_text_audit_persona_limit: int | None = 2,
    baseline_artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / case_set_filename, case_catalog)
    rpm_budget = build_rpm_budget(total_rpm_limit)
    target_turns = _turn_target_for_suite(suite_type=suite_type, profile=profile)
    with strict_no_repair_fallback(enabled=True):
        with rpm_budget_limits(
            total_rpm_limit=int(rpm_budget["total"]),
        ):
            result = run_case_catalog_live_eval(
                root,
                case_catalog=case_catalog,
                case_set_filename=case_set_filename,
                blockers_filename=blockers_filename,
                blockers_title=blockers_title,
                enable_llm_text_audit=True,
                case_max_workers=max(1, int(case_max_workers)),
                case_timeout_seconds=max(30.0, float(case_timeout_seconds)),
                case_aggregate_timeout_seconds=max(60.0, float(case_aggregate_timeout_seconds)),
                session_play_eval_timeout_seconds=max(30.0, float(session_play_eval_timeout_seconds)),
                select_id_probability=min(max(float(select_id_probability), 0.0), 1.0),
                typing_rhythm_enabled=bool(typing_rhythm_enabled),
                draft_intent_probability=min(max(float(draft_intent_probability), 0.0), 1.0),
                draft_call_count_min=max(1, int(draft_call_count_min)),
                draft_call_count_max=max(1, int(draft_call_count_max)),
                draft_debounce_ms=max(0, int(draft_debounce_ms)),
                session_play_eval_persona_limit=(
                    max(1, int(session_play_eval_persona_limit))
                    if session_play_eval_persona_limit is not None
                    else None
                ),
                llm_text_audit_persona_limit=(
                    max(1, int(llm_text_audit_persona_limit))
                    if llm_text_audit_persona_limit is not None
                    else None
                ),
                max_turns_override=target_turns,
            )
    persona_coverage_summary = dict(result.get("persona_coverage_summary") or {})
    avg_turns = float(persona_coverage_summary.get("avg_turns_successful_personas", 0.0) or 0.0)
    persona_coverage_summary["avg_turns_successful_personas_target"] = int(target_turns)
    persona_coverage_summary["avg_turns_successful_personas_target_met"] = bool(avg_turns >= float(target_turns))
    _write_json(root / "persona_coverage_summary.json", persona_coverage_summary)
    result["persona_coverage_summary"] = persona_coverage_summary

    v2_payload = build_gold_eval_v2_outputs(
        case_catalog=case_catalog,
        author_summary=dict(result.get("author_summary") or {}),
        case_summaries=list(result.get("case_summaries") or []),
        llm_text_case_summaries=list(result.get("llm_text_case_summaries") or []),
        persona_coverage_summary=persona_coverage_summary,
        case_failures=dict(result.get("case_failures") or {}),
    )
    play_eval_summary = dict(v2_payload.get("play_eval_summary") or {})
    llm_text_audit_summary = dict(v2_payload.get("llm_text_audit_summary") or {})
    performance_summary = dict(v2_payload.get("performance_summary") or {})

    _write_json(root / "play_eval_summary.json", play_eval_summary)
    _write_json(root / "llm_text_audit_summary.json", llm_text_audit_summary)
    _write_json(root / "performance_summary.json", performance_summary)
    token_uplift_payload = _build_play_token_uplift(
        root=root,
        explicit_baseline_artifacts_dir=baseline_artifacts_dir,
    )
    _write_json(root / "play_token_uplift_vs_baseline.json", token_uplift_payload)
    (root / "play_token_uplift_vs_baseline.md").write_text(_play_token_uplift_markdown(token_uplift_payload), encoding="utf-8")

    effect_report = build_gold_eval_v2_effect_report(
        suite_type=suite_type,
        profile=profile,
        case_count=len(case_catalog),
        play_eval_summary=play_eval_summary,
        llm_text_audit_summary=llm_text_audit_summary,
        performance_summary=performance_summary,
    )
    (root / "effect_report.md").write_text(effect_report)

    settings_snapshot = Settings(_env_file=None)
    run_manifest = {
        "suite_type": suite_type,
        "profile": profile,
        "case_count": len(case_catalog),
        "workers": max(1, int(case_max_workers)),
        "rpm": max(1, int(total_rpm_limit)),
        "timeout_seconds": max(30.0, float(case_timeout_seconds)),
        "max_turns_override": int(target_turns),
        "total_rpm_limit": max(1, int(total_rpm_limit)),
        "case_timeout_seconds": max(30.0, float(case_timeout_seconds)),
        "case_aggregate_timeout_seconds": max(60.0, float(case_aggregate_timeout_seconds)),
        "session_play_eval_timeout_seconds": max(30.0, float(session_play_eval_timeout_seconds)),
        "select_id_probability": min(max(float(select_id_probability), 0.0), 1.0),
        "typing_rhythm_enabled": bool(typing_rhythm_enabled),
        "draft_intent_probability": min(max(float(draft_intent_probability), 0.0), 1.0),
        "draft_call_count_min": max(1, int(draft_call_count_min)),
        "draft_call_count_max": max(1, int(draft_call_count_max)),
        "draft_debounce_ms": max(0, int(draft_debounce_ms)),
        "session_play_eval_persona_limit": (
            max(1, int(session_play_eval_persona_limit))
            if session_play_eval_persona_limit is not None
            else None
        ),
        "llm_text_audit_persona_limit": (
            max(1, int(llm_text_audit_persona_limit))
            if llm_text_audit_persona_limit is not None
            else None
        ),
        "baseline_artifacts_dir": str(baseline_artifacts_dir.resolve()) if baseline_artifacts_dir is not None else None,
        "rpm_budget": rpm_budget,
        "llm_text_audit_forced": True,
        "intent_compiler_llm_enabled": bool(settings_snapshot.play_v2_intent_compiler_use_llm),
        "micro_sim_llm_enabled": bool(settings_snapshot.play_v2_micro_sim_use_llm),
        "micro_sim_max_candidates": int(settings_snapshot.play_v2_micro_sim_max_candidates),
        "semantic_strategy_version": 8,
        "policy_cost_visibility_enabled": bool(settings_snapshot.play_v2_policy_cost_visibility_enabled),
        "policy_question_progress_v2_enabled": bool(settings_snapshot.play_v2_policy_question_progress_v2_enabled),
        "policy_role_divergence_v2_enabled": bool(settings_snapshot.play_v2_policy_role_divergence_v2_enabled),
        "gold_set_profile_version": "super_flagship_v3",
        "gold_set_band_distribution": _distribution_by_band(case_catalog),
        "gold_set_experience_band_distribution": _distribution_by_experience_band(case_catalog),
        "gold_set_shell_distribution": _distribution_by_shell(case_catalog),
        "metric_contract_version": 2,
        "quantile_granularity": "global_and_shell",
        "strict_no_repair_fallback_enabled": True,
    }
    _write_json(root / "run_manifest.json", run_manifest)
    return {
        "artifacts_dir": str(root),
        "run_manifest": run_manifest,
        "author_summary": result.get("author_summary"),
        "play_eval_summary": play_eval_summary,
        "llm_text_audit_summary": llm_text_audit_summary,
        "performance_summary": performance_summary,
        "play_token_uplift_vs_baseline": token_uplift_payload,
        "persona_coverage_summary": result.get("persona_coverage_summary"),
    }


def print_runner_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
