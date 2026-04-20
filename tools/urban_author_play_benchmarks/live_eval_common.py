from __future__ import annotations

import json
from collections import Counter, defaultdict
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from statistics import mean
from typing import Any

from rpg_backend.config import HelperResponsesEndpoint, get_settings
from rpg_backend.responses_transport import build_openai_client
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase
from tools.urban_author_play_benchmarks.native_cn_live_eval import (
    _case_llm_text_audit_summary,
    _case_play_eval_summary,
    _smoke_results,
    _smoke_shell_summary,
    _write_json,
)
from tools.urban_author_play_benchmarks.runner import run_benchmark
from tools.urban_author_play_benchmarks.self_play_runner import run_self_play_pilot

LIVE_MODE = "live_gpt_5_4_mini"
EXECUTION_MODE = "parallel"
AUTHOR_STAGES = (
    "synthesize_preview_blueprint",
    "plan_cast_slots",
    "allocate_segment_contracts",
    "compile_segment_playbooks",
)
PERSONA_COVERAGE_MIN_SUCCESS = 4
PERSONA_COVERAGE_EXPECTED = 5
PLAY_EVAL_SUCCESS_STATUSES = {"completed", "partial_success"}
PERSONA_RUN_SUCCESS_STATUSES = {"completed", "stopped"}
DEFAULT_CASE_TIMEOUT_SECONDS = 1200.0
DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS = 360.0
DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS = 90.0


def _estimate_cost_rmb(*, input_tokens: int, output_tokens: int) -> float:
    settings = get_settings()
    input_price = float(getattr(settings, "responses_input_price_per_million_tokens_rmb", 0.2) or 0.2)
    output_price = float(getattr(settings, "responses_output_price_per_million_tokens_rmb", 2.0) or 2.0)
    input_rate = input_price / 1_000_000
    output_rate = output_price / 1_000_000
    return round(max(input_tokens, 0) * input_rate + max(output_tokens, 0) * output_rate, 6)


def _author_usage_totals(results: list[dict[str, Any]]) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    for result in results:
        for trace in list(result.get("llm_call_trace") or []):
            usage = dict(trace.get("usage") or {})
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
    return max(input_tokens, 0), max(output_tokens, 0)


def helper_probe() -> dict[str, Any]:
    get_settings.cache_clear()
    settings = get_settings()
    endpoints = list(settings.configured_helper_responses_endpoints())
    if not endpoints and settings.resolved_helper_responses_base_url():
        endpoints = [
            HelperResponsesEndpoint(
                slot_name="legacy_helper",
                base_url=settings.resolved_helper_responses_base_url(),
                api_key=settings.resolved_helper_responses_api_key(),
                model=settings.resolved_helper_responses_model(),
                use_session_cache=settings.resolved_helper_responses_use_session_cache(),
                weight=1.0,
                role="primary",
            )
        ]
    if not endpoints and settings.resolved_responses_base_url() and settings.resolved_responses_api_key() and settings.resolved_responses_model():
        endpoints = [
            HelperResponsesEndpoint(
                slot_name="generic_responses",
                base_url=settings.resolved_responses_base_url(),
                api_key=settings.resolved_responses_api_key(),
                model=settings.resolved_responses_model(),
                use_session_cache=settings.resolved_responses_use_session_cache(),
                weight=1.0,
                role="primary",
            )
        ]
    probes = (
        ("small", json.dumps({"ping": "ping"}, ensure_ascii=False), 3),
        ("segment_like", json.dumps({"segment_like": "x" * 4000}, ensure_ascii=False), 2),
    )
    endpoint_rows: list[dict[str, Any]] = []
    for endpoint in endpoints:
        client = build_openai_client(
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            api_keys=settings.helper_responses_api_key_pool(),
            use_session_cache=False,
            session_cache_header=settings.responses_session_cache_header,
            session_cache_value=settings.responses_session_cache_value,
            requests_per_minute=settings.helper_responses_requests_per_minute,
            rate_limit_scope="helper:probe",
        )
        summary_rows: list[dict[str, Any]] = []
        for probe_name, payload, runs in probes:
            outcomes: list[dict[str, Any]] = []
            for index in range(1, runs + 1):
                try:
                    response = client.responses.create(
                        model=endpoint.model,
                        instructions="你是 helper 连通性探针。只返回 JSON 对象。",
                        input=payload,
                        max_output_tokens=32,
                        timeout=20.0,
                        temperature=0.0,
                    )
                    outcomes.append({"run": index, "status": "ok", "response_id": getattr(response, "id", None)})
                except Exception as exc:  # noqa: BLE001
                    outcomes.append({"run": index, "status": "error", "error": str(exc)[:180]})
            summary_rows.append(
                {
                    "probe": probe_name,
                    "input_characters": len(payload),
                    "success_count": sum(1 for item in outcomes if item["status"] == "ok"),
                    "failure_count": sum(1 for item in outcomes if item["status"] != "ok"),
                    "runs": outcomes,
                }
            )
        endpoint_rows.append(
            {
                "slot_name": endpoint.slot_name,
                "role": endpoint.role,
                "base_url": endpoint.base_url,
                "model": endpoint.model,
                "probes": summary_rows,
            }
        )
    primary = next((row for row in endpoint_rows if row.get("role") == "primary"), endpoint_rows[0] if endpoint_rows else {"base_url": "", "model": "", "probes": [], "slot_name": ""})
    backups = [row for row in endpoint_rows if row is not primary]
    return {
        "base_url": primary["base_url"],
        "model": primary["model"],
        "probes": primary["probes"],
        "primary_helper": primary,
        "backup_helpers": backups,
        "endpoints": endpoint_rows,
    }


def author_case_rows(results: list[dict[str, Any]], case_catalog: list[UrbanGoldCase]) -> list[dict[str, Any]]:
    by_id = {case.case_id: case for case in case_catalog}
    rows: list[dict[str, Any]] = []
    for result in results:
        case = by_id[str(result["case_id"])]
        case_input_tokens = 0
        case_output_tokens = 0
        case_total_tokens = 0
        case_elapsed_ms = 0.0
        for trace in list(result.get("llm_call_trace") or []):
            usage = dict(trace.get("usage") or {})
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            total_tokens = int(usage.get("total_tokens", 0) or 0)
            case_input_tokens += max(input_tokens, 0)
            case_output_tokens += max(output_tokens, 0)
            case_total_tokens += max(total_tokens, 0) if total_tokens > 0 else max(input_tokens + output_tokens, 0)
            duration_seconds = trace.get("duration_seconds")
            if isinstance(duration_seconds, (int, float)) and not isinstance(duration_seconds, bool):
                case_elapsed_ms += max(float(duration_seconds), 0.0) * 1000.0
        rows.append(
            {
                "case_id": case.case_id,
                "shell": case.expected_shell,
                "band": case.expected_band,
                "expected_template_id": case.expected_template_id,
                "passed": bool(result.get("passed")),
                "content_score": float(result.get("content_score", 0.0)),
                "structure_score": float(result.get("structure_score", 0.0)),
                "live_depth_score": int(result.get("live_depth_score", 0)),
                "template_id": str(result.get("template_id") or "unknown"),
                "fit_mode": str(result.get("fit_mode") or "unknown"),
                "seed_fingerprint_summary": dict(result.get("seed_fingerprint_summary") or {}),
                "seed_preservation_failures": list(result.get("seed_preservation_failures") or []),
                "sibling_divergence_flags": list(result.get("sibling_divergence_flags") or []),
                "final_mode_path": str(result.get("final_mode_path") or "deterministic"),
                "failure_category": result.get("failure_category"),
                "stage": str(result.get("stage") or "unknown"),
                "failing_assertions": [
                    item["name"]
                    for item in list(result.get("assertions") or [])
                    if isinstance(item, dict) and not bool(item.get("passed"))
                ],
                "author_case_elapsed_ms": round(case_elapsed_ms, 4),
                "author_case_input_tokens": case_input_tokens,
                "author_case_output_tokens": case_output_tokens,
                "author_case_total_tokens": case_total_tokens,
            }
        )
    return rows


def token_usage_summary(results: list[dict[str, Any]], case_catalog: list[UrbanGoldCase]) -> dict[str, Any]:
    by_id = {case.case_id: case for case in case_catalog}
    per_stage_tokens: dict[str, list[int]] = defaultdict(list)
    per_case_stage_tokens: list[dict[str, Any]] = []
    for result in results:
        case = by_id[str(result["case_id"])]
        stage_tokens = {stage: 0 for stage in AUTHOR_STAGES}
        stage_retry_count = Counter[str]()
        for trace in list(result.get("llm_call_trace") or []):
            stage = str(trace.get("stage") or "")
            if stage not in set(AUTHOR_STAGES):
                continue
            output_tokens = int(dict(trace.get("usage") or {}).get("output_tokens", 0) or 0)
            stage_tokens[stage] += output_tokens
            per_stage_tokens[stage].append(output_tokens)
            if int(trace.get("retry_count", 0) or 0) > 0:
                stage_retry_count[stage] += 1
        per_case_stage_tokens.append(
            {
                "case_id": case.case_id,
                "shell": case.expected_shell,
                "template_id": case.expected_template_id,
                "stage_output_tokens": stage_tokens,
                "stage_retry_count": dict(stage_retry_count),
            }
        )
    diagnosis = {
        "synthesize_preview_blueprint": "高 token 主要来自完整 preview blueprint 的多段长文本字段。",
        "plan_cast_slots": "高 token 主要来自多 slot 数组，以及 chemistry/danger/secret/mask 四类长文本。",
        "allocate_segment_contracts": "高 token 主要来自每段的 entry/exit/handoff 三段合同文本叠加。",
        "compile_segment_playbooks": "高 token 主要来自 scene_goal/emotional_goal/progression/render_cues 组合；若有 repair/fallback，会放大重复输出。",
    }
    total_input_tokens, total_output_tokens = _author_usage_totals(results)
    return {
        "per_stage": {
            stage: {
                "total_output_tokens": sum(values),
                "avg_output_tokens": round(mean(values), 4) if values else 0.0,
                "max_output_tokens": max(values) if values else 0,
                "diagnosis": diagnosis[stage],
            }
            for stage, values in per_stage_tokens.items()
        },
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "estimated_author_cost_rmb": _estimate_cost_rmb(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        ),
        "per_case": per_case_stage_tokens,
    }


def _case_play_eval_failure_summary(*, case_id: str, error: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "artifacts_dir": "",
        "comparison_summary": {},
        "turn_flag_counts": {"case_run_failed": 1},
        "session_reports": {},
        "avg_strategic_tension_curve": 0.0,
        "avg_consequence_legibility": 0.0,
        "avg_payoff_realization": 0.0,
        "avg_npc_interest_divergence": 0.0,
        "avg_control_tradeoff_quality": 0.0,
        "avg_shell_system_activation": 0.0,
        "avg_ending_cost_integrity": 0.0,
        "avg_replay_variance": 0.0,
        "avg_turn_consequence_impact": 0.0,
        "avg_turn_intent_binding": 0.0,
        "avg_turn_pressure_exchange": 0.0,
        "avg_key_segment_shell_anchor_hit_rate": 0.0,
        "top_play_eval_issues": {f"case_run_failed:{error[:120]}": 1},
        "top_play_eval_strengths": {},
    }


def _case_llm_text_failure_summary(*, case_id: str, error: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "artifacts_dir": "",
        "session_reports": {},
        "turn_flag_counts": {"case_run_failed": 1},
        "avg_arc_coherence": 0.0,
        "avg_payoff_strength": 0.0,
        "avg_npc_presence": 0.0,
        "avg_style_consistency": 0.0,
        "avg_shell_distinctiveness": 0.0,
        "avg_memorable_moments": 0.0,
        "avg_turn_tone_naturalness": 0.0,
        "avg_turn_character_specificity": 0.0,
        "avg_turn_dramatic_tension": 0.0,
        "avg_turn_shell_fidelity": 0.0,
        "avg_turn_consequence_clarity": 0.0,
        "avg_turn_anti_template_stiffness": 0.0,
        "top_llm_text_issues": {f"case_run_failed:{error[:120]}": 1},
        "top_llm_text_strengths": {},
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "estimated_llm_text_audit_cost_rmb": 0.0,
    }


def play_eval_summary(case_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    top_issue_counter: Counter[str] = Counter()
    top_strength_counter: Counter[str] = Counter()
    flag_counter: Counter[str] = Counter()
    case_rows: list[dict[str, Any]] = []
    for summary in case_summaries:
        turn_flag_counts = dict(summary.get("turn_flag_counts") or {})
        flag_counter.update(turn_flag_counts)
        top_issue_counter.update(dict(summary.get("top_play_eval_issues") or {}))
        top_strength_counter.update(dict(summary.get("top_play_eval_strengths") or {}))
        case_rows.append(
            {
                "case_id": summary["case_id"],
                "avg_strategic_tension_curve": summary["avg_strategic_tension_curve"],
                "avg_consequence_legibility": summary["avg_consequence_legibility"],
                "avg_payoff_realization": summary["avg_payoff_realization"],
                "avg_npc_interest_divergence": summary["avg_npc_interest_divergence"],
                "avg_control_tradeoff_quality": summary["avg_control_tradeoff_quality"],
                "avg_shell_system_activation": summary["avg_shell_system_activation"],
                "avg_ending_cost_integrity": summary["avg_ending_cost_integrity"],
                "avg_replay_variance": summary["avg_replay_variance"],
                "avg_turn_consequence_impact": summary["avg_turn_consequence_impact"],
                "avg_turn_intent_binding": summary["avg_turn_intent_binding"],
                "avg_key_segment_shell_anchor_hit_rate": summary.get("avg_key_segment_shell_anchor_hit_rate", 0.0),
                "turn_flag_counts": turn_flag_counts,
            }
        )
    return {
        "cases": case_rows,
        "top_issues": dict(top_issue_counter.most_common(10)),
        "top_strengths": dict(top_strength_counter.most_common(10)),
        "top_flags": dict(flag_counter.most_common(10)),
    }


def llm_text_audit_summary(case_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    top_issue_counter: Counter[str] = Counter()
    top_strength_counter: Counter[str] = Counter()
    flag_counter: Counter[str] = Counter()
    case_rows: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    for summary in case_summaries:
        turn_flag_counts = dict(summary.get("turn_flag_counts") or {})
        flag_counter.update(turn_flag_counts)
        top_issue_counter.update(dict(summary.get("top_llm_text_issues") or {}))
        top_strength_counter.update(dict(summary.get("top_llm_text_strengths") or {}))
        total_input_tokens += int(summary.get("total_input_tokens", 0) or 0)
        total_output_tokens += int(summary.get("total_output_tokens", 0) or 0)
        case_rows.append(
            {
                "case_id": summary["case_id"],
                "avg_arc_coherence": summary["avg_arc_coherence"],
                "avg_payoff_strength": summary["avg_payoff_strength"],
                "avg_npc_presence": summary["avg_npc_presence"],
                "avg_style_consistency": summary["avg_style_consistency"],
                "avg_shell_distinctiveness": summary["avg_shell_distinctiveness"],
                "avg_memorable_moments": summary["avg_memorable_moments"],
                "avg_turn_tone_naturalness": summary["avg_turn_tone_naturalness"],
                "avg_turn_character_specificity": summary["avg_turn_character_specificity"],
                "avg_turn_dramatic_tension": summary["avg_turn_dramatic_tension"],
                "avg_turn_shell_fidelity": summary["avg_turn_shell_fidelity"],
                "avg_turn_consequence_clarity": summary["avg_turn_consequence_clarity"],
                "avg_turn_anti_template_stiffness": summary["avg_turn_anti_template_stiffness"],
                "turn_flag_counts": turn_flag_counts,
            }
        )
    return {
        "cases": case_rows,
        "top_issues": dict(top_issue_counter.most_common(10)),
        "top_strengths": dict(top_strength_counter.most_common(10)),
        "top_flags": dict(flag_counter.most_common(10)),
        "total_input_tokens": max(total_input_tokens, 0),
        "total_output_tokens": max(total_output_tokens, 0),
        "estimated_llm_text_audit_cost_rmb": _estimate_cost_rmb(
            input_tokens=max(total_input_tokens, 0),
            output_tokens=max(total_output_tokens, 0),
        ),
    }


def _case_persona_coverage(
    case_summary: dict[str, Any],
    *,
    min_success_personas_required: int = PERSONA_COVERAGE_MIN_SUCCESS,
    expected_persona_count: int = PERSONA_COVERAGE_EXPECTED,
    quality_min_success_personas_required: int | None = None,
) -> dict[str, Any]:
    case_id = str(case_summary.get("case_id") or "unknown")
    session_reports = dict(case_summary.get("session_reports") or {})
    comparison_summary = dict(case_summary.get("comparison_summary") or {})
    persona_summaries = dict(comparison_summary.get("persona_summaries") or {})
    known_persona_ids = sorted(
        set(str(persona_id) for persona_id in session_reports)
        | set(str(persona_id) for persona_id in persona_summaries)
    )
    successful_ids = sorted(
        str(persona_id)
        for persona_id, summary in persona_summaries.items()
        if str(dict(summary).get("worker_status") or "") in PERSONA_RUN_SUCCESS_STATUSES
    )
    if not successful_ids:
        successful_ids = sorted(
            str(persona_id)
            for persona_id, report in session_reports.items()
            if str(dict(report).get("play_eval_status") or "") in PLAY_EVAL_SUCCESS_STATUSES
        )
    failed_ids = sorted(persona_id for persona_id in known_persona_ids if persona_id not in set(successful_ids))
    successful_turn_counts: list[int] = []
    for persona_id in successful_ids:
        turns = int(dict(persona_summaries.get(persona_id) or {}).get("turn_count", 0) or 0)
        if turns > 0:
            successful_turn_counts.append(turns)
    session_eval_success_ids = sorted(
        str(persona_id)
        for persona_id, report in session_reports.items()
        if str(dict(report).get("play_eval_status") or "") in PLAY_EVAL_SUCCESS_STATUSES
        and dict(report).get("scores") is not None
    )
    min_success = max(1, int(min_success_personas_required))
    quality_min_success = max(
        1,
        int(
            quality_min_success_personas_required
            if quality_min_success_personas_required is not None
            else min_success
        ),
    )
    expected_count = max(1, int(expected_persona_count))
    success_count = len(successful_ids)
    session_eval_success_count = len(session_eval_success_ids)
    is_valid = success_count >= min_success
    quality_eval_valid = is_valid and session_eval_success_count >= quality_min_success
    return {
        "case_id": case_id,
        "expected_persona_count": expected_count,
        "min_success_personas_required": min_success,
        "quality_min_success_personas_required": quality_min_success,
        "known_persona_count": len(known_persona_ids),
        "successful_persona_count": success_count,
        "successful_persona_ids": successful_ids,
        "failed_persona_ids": failed_ids,
        "session_eval_successful_persona_count": session_eval_success_count,
        "session_eval_successful_persona_ids": session_eval_success_ids,
        "avg_turns_successful_personas": round(mean(successful_turn_counts), 4) if successful_turn_counts else 0.0,
        "is_valid": is_valid,
        "quality_eval_valid": quality_eval_valid,
        "quality_eval_incomplete": is_valid and not quality_eval_valid,
    }


def persona_coverage_summary(
    case_summaries: list[dict[str, Any]],
    *,
    min_success_personas_required: int = PERSONA_COVERAGE_MIN_SUCCESS,
    expected_persona_count: int = PERSONA_COVERAGE_EXPECTED,
    quality_min_success_personas_required: int | None = None,
) -> dict[str, Any]:
    case_rows = [
        _case_persona_coverage(
            summary,
            min_success_personas_required=min_success_personas_required,
            expected_persona_count=expected_persona_count,
            quality_min_success_personas_required=quality_min_success_personas_required,
        )
        for summary in case_summaries
    ]
    invalid_rows = [row for row in case_rows if not row["is_valid"]]
    quality_invalid_rows = [row for row in case_rows if not row["quality_eval_valid"]]
    quality_incomplete_rows = [row for row in case_rows if row["quality_eval_incomplete"]]
    successful_counts = [int(row["successful_persona_count"]) for row in case_rows]
    avg_turn_values = [float(row["avg_turns_successful_personas"]) for row in case_rows if row["avg_turns_successful_personas"] > 0]
    session_eval_success_counts = [int(row["session_eval_successful_persona_count"]) for row in case_rows]
    min_success_value = max(1, int(min_success_personas_required))
    expected_count = max(1, int(expected_persona_count))
    quality_min_success_value = max(
        1,
        int(
            quality_min_success_personas_required
            if quality_min_success_personas_required is not None
            else min_success_value
        ),
    )
    return {
        "min_success_personas_required": min_success_value,
        "expected_persona_count": expected_count,
        "quality_min_success_personas_required": quality_min_success_value,
        "case_count": len(case_rows),
        "invalid_case_count": len(invalid_rows),
        "invalid_case_ids": [str(row["case_id"]) for row in invalid_rows],
        "quality_invalid_case_count": len(quality_invalid_rows),
        "quality_invalid_case_ids": [str(row["case_id"]) for row in quality_invalid_rows],
        "quality_eval_incomplete_case_count": len(quality_incomplete_rows),
        "quality_eval_incomplete_case_ids": [str(row["case_id"]) for row in quality_incomplete_rows],
        "valid_quality_case_count": len(case_rows) - len(quality_invalid_rows),
        "valid_quality_case_ids": [str(row["case_id"]) for row in case_rows if row["quality_eval_valid"]],
        "avg_successful_persona_count": round(mean(successful_counts), 4) if successful_counts else 0.0,
        "avg_session_eval_successful_persona_count": round(mean(session_eval_success_counts), 4) if session_eval_success_counts else 0.0,
        "avg_turns_successful_personas": round(mean(avg_turn_values), 4) if avg_turn_values else 0.0,
        "cases": case_rows,
    }


def blockers_markdown(
    *,
    title: str,
    case_catalog: list[UrbanGoldCase],
    author_summary: dict[str, Any],
    play_eval_summary_payload: dict[str, Any],
    token_usage_summary_payload: dict[str, Any],
    persona_coverage_payload: dict[str, Any],
) -> str:
    case_rows = list(author_summary["cases"])
    shell_author_rows = _smoke_shell_summary(case_catalog, author_summary["benchmark_results"])
    strongest_shell = shell_author_rows[0]["shell_id"] if shell_author_rows else "unknown"
    issue_counter = Counter(author_summary.get("failing_assertions") or {})
    issue_counter.update(play_eval_summary_payload.get("top_issues") or {})
    issue_counter.update(play_eval_summary_payload.get("top_flags") or {})
    issue_counter.update({"persona_coverage_invalid": int(persona_coverage_payload.get("invalid_case_count", 0) or 0)})
    most_diffuse_case = None
    highest_diffuse = -1
    for row in play_eval_summary_payload["cases"]:
        diffuse = int(dict(row.get("turn_flag_counts") or {}).get("角色反应太泛", 0))
        if diffuse > highest_diffuse:
            highest_diffuse = diffuse
            most_diffuse_case = row["case_id"]
    lines = [
        f"# {title}",
        "",
        f"- strongest direction: `{strongest_shell}`",
        f"- highest diffuse-reaction case: `{most_diffuse_case or 'unknown'}`",
        (
            "- persona coverage gate: "
            f"{int(persona_coverage_payload.get('invalid_case_count', 0) or 0)} invalid "
            f"(min success={int(persona_coverage_payload.get('min_success_personas_required', PERSONA_COVERAGE_MIN_SUCCESS) or PERSONA_COVERAGE_MIN_SUCCESS)}/"
            f"{int(persona_coverage_payload.get('expected_persona_count', PERSONA_COVERAGE_EXPECTED) or PERSONA_COVERAGE_EXPECTED)})"
        ),
        (
            "- quality-eval gate: "
            f"{int(persona_coverage_payload.get('quality_invalid_case_count', 0) or 0)} invalid "
            f"(eval incomplete={int(persona_coverage_payload.get('quality_eval_incomplete_case_count', 0) or 0)})"
        ),
        "",
        "## Per-Case Author Score",
        "",
        "| Case | Shell | Template | Passed | Content | Live Depth | Failure |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in case_rows:
        lines.append(
            f"| {row['case_id']} | {row['shell']} | {row['template_id']} | {row['passed']} | "
            f"{row['content_score']:.4f} | {row['live_depth_score']} | {row['failure_category'] or 'none'} |"
        )
        if row["seed_preservation_failures"] or row["sibling_divergence_flags"]:
            lines.append(
                f"  diagnostics: preservation={','.join(row['seed_preservation_failures']) or 'none'}; "
                f"sibling={','.join(row['sibling_divergence_flags']) or 'none'}"
            )
    lines.extend(["", "## Play Eval Summary", "", "| Case | Tension | Consequence | NPC Interest | Control | Payoff |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for row in play_eval_summary_payload["cases"]:
        lines.append(
            f"| {row['case_id']} | {row['avg_strategic_tension_curve']:.2f} | {row['avg_consequence_legibility']:.2f} | "
            f"{row['avg_npc_interest_divergence']:.2f} | {row['avg_control_tradeoff_quality']:.2f} | {row['avg_payoff_realization']:.2f} |"
        )
    lines.extend(["", "## Token Usage", ""])
    for stage, payload in token_usage_summary_payload["per_stage"].items():
        lines.append(
            f"- `{stage}`: total={payload['total_output_tokens']}, avg={payload['avg_output_tokens']:.2f}, "
            f"max={payload['max_output_tokens']}。{payload['diagnosis']}"
        )
    lines.extend(["", "## Persona Coverage", ""])
    lines.append(
        (
            f"- avg successful personas per case: "
            f"{float(persona_coverage_payload.get('avg_successful_persona_count', 0.0)):.2f}"
        )
    )
    lines.append(
        (
            f"- avg turns (successful personas): "
            f"{float(persona_coverage_payload.get('avg_turns_successful_personas', 0.0)):.2f}"
        )
    )
    invalid_case_ids = list(persona_coverage_payload.get("invalid_case_ids") or [])
    if invalid_case_ids:
        lines.append(f"- invalid cases: `{','.join(str(case_id) for case_id in invalid_case_ids)}`")
    else:
        lines.append("- invalid cases: `none`")
    lines.extend(["", "## Top 5 Blockers", ""])
    for issue, count in issue_counter.most_common(5):
        lines.append(f"- `{issue}`: {count}")
    return "\n".join(lines) + "\n"


def run_case_catalog_live_eval(
    output_dir: Path,
    *,
    case_catalog: list[UrbanGoldCase],
    case_set_filename: str,
    blockers_filename: str,
    blockers_title: str,
    live_mode: str = LIVE_MODE,
    execution_mode: str = EXECUTION_MODE,
    source_author_artifacts: bool = True,
    enable_llm_text_audit: bool = True,
    llm_text_audit_max_workers: int | None = None,
    case_max_workers: int | None = None,
    case_timeout_seconds: float | None = DEFAULT_CASE_TIMEOUT_SECONDS,
    case_aggregate_timeout_seconds: float | None = None,
    session_play_eval_timeout_seconds: float | None = DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS,
    select_id_probability: float = 0.1,
    typing_rhythm_enabled: bool = False,
    draft_intent_probability: float = 0.3,
    draft_call_count_min: int = 1,
    draft_call_count_max: int = 2,
    draft_debounce_ms: int = 350,
    session_play_eval_persona_limit: int | None = None,
    llm_text_audit_persona_limit: int | None = None,
    chaos_shadow_case_ids: list[str] | None = None,
    max_turns_override: int | None = None,
) -> dict[str, Any]:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / case_set_filename, case_catalog)
    persona_timeout_seconds = (
        float(case_timeout_seconds)
        if case_timeout_seconds is not None and float(case_timeout_seconds) > 0
        else None
    )
    aggregate_timeout_seconds = (
        float(case_aggregate_timeout_seconds)
        if case_aggregate_timeout_seconds is not None and float(case_aggregate_timeout_seconds) > 0
        else max(
            DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS,
            (persona_timeout_seconds or DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS) * 2,
        )
    )
    session_eval_timeout = (
        float(session_play_eval_timeout_seconds)
        if session_play_eval_timeout_seconds is not None and float(session_play_eval_timeout_seconds) > 0
        else None
    )

    helper_probe_payload = helper_probe()
    try:
        benchmark_summary = run_benchmark(
            root / "benchmark",
            mini_cases=case_catalog,
            modes=(live_mode,),  # type: ignore[arg-type]
            include_burst=False,
            case_timeout_seconds=persona_timeout_seconds,
            case_max_workers=case_max_workers,
        )
    except TypeError as exc:
        if "case_timeout_seconds" not in str(exc) and "case_max_workers" not in str(exc):
            raise
        benchmark_summary = run_benchmark(
            root / "benchmark",
            mini_cases=case_catalog,
            modes=(live_mode,),  # type: ignore[arg-type]
            include_burst=False,
        )
    smoke_results = _smoke_results(benchmark_summary, live_mode=live_mode)
    author_cases = author_case_rows(smoke_results, case_catalog)
    author_summary = {
        "live_mode": live_mode,
        "config": {
            "author_product_run_mode": get_settings().author_product_run_mode,
            "author_model": get_settings().resolved_author_responses_model(),
            "play_model": get_settings().resolved_play_responses_model(),
            "helper_base_url": get_settings().resolved_helper_responses_base_url(),
            "helper_model": get_settings().resolved_helper_responses_model(),
            "play_v2_narration_profile": get_settings().play_v2_narration_profile,
        },
        "helper_probe": helper_probe_payload,
        "benchmark_results": smoke_results,
        "cases": author_cases,
        "failing_assertions": benchmark_summary["smoke"]["mode_summaries"][live_mode]["failing_assertions"],
        "fallback_distribution": benchmark_summary["smoke"]["mode_summaries"][live_mode]["fallback_distribution"],
    }
    author_input_tokens, author_output_tokens = _author_usage_totals(smoke_results)
    author_summary["author_token_usage"] = {
        "input_tokens": author_input_tokens,
        "output_tokens": author_output_tokens,
    }
    author_summary["estimated_author_cost_rmb"] = _estimate_cost_rmb(
        input_tokens=author_input_tokens,
        output_tokens=author_output_tokens,
    )
    _write_json(root / "author_summary.json", author_summary)
    token_usage_payload = token_usage_summary(smoke_results, case_catalog)
    _write_json(root / "token_usage_summary.json", token_usage_payload)
    deep_play_root = root / "deep_play"
    case_artifacts: dict[str, Path] = {}
    case_failures: dict[str, str] = {}
    chaos_shadow_case_set = {case_id for case_id in list(chaos_shadow_case_ids or []) if case_id}

    def _run_case(case: UrbanGoldCase) -> tuple[str, Path | None, str | None]:
        source_artifacts_dir = root / "benchmark" / "smoke" / case.case_id / live_mode
        chaos_kwargs = {"enable_chaos_persona_shadow": True} if case.case_id in chaos_shadow_case_set else {}
        try:
            result = run_self_play_pilot(
                deep_play_root,
                case_id=case.case_id,
                case_catalog=case_catalog,
                source_artifacts_dir=source_artifacts_dir,
                live_mode=live_mode,
                execution_mode=execution_mode,
                enable_turn_play_eval=True,
                enable_session_play_eval=True,
                enable_llm_text_audit=enable_llm_text_audit,
                llm_text_audit_max_workers=llm_text_audit_max_workers,
                max_case_runtime_seconds=aggregate_timeout_seconds,
                persona_runtime_timeout_seconds=persona_timeout_seconds,
                session_play_eval_timeout_seconds=session_eval_timeout,
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
                max_turns_override=max_turns_override,
                **chaos_kwargs,
            )
            return case.case_id, Path(str(result["artifacts_dir"])), None
        except TypeError as exc:
            message = str(exc)
            if (
                "persona_runtime_timeout_seconds" not in message
                and "session_play_eval_timeout_seconds" not in message
                and "typing_rhythm_enabled" not in message
                and "draft_intent_probability" not in message
                and "draft_call_count_min" not in message
                and "draft_call_count_max" not in message
                and "draft_debounce_ms" not in message
                and "session_play_eval_persona_limit" not in message
                and "llm_text_audit_persona_limit" not in message
                and "max_turns_override" not in message
            ):
                raise
            result = run_self_play_pilot(
                deep_play_root,
                case_id=case.case_id,
                case_catalog=case_catalog,
                source_artifacts_dir=source_artifacts_dir,
                live_mode=live_mode,
                execution_mode=execution_mode,
                enable_turn_play_eval=True,
                enable_session_play_eval=True,
                enable_llm_text_audit=enable_llm_text_audit,
                llm_text_audit_max_workers=llm_text_audit_max_workers,
                max_case_runtime_seconds=aggregate_timeout_seconds,
                select_id_probability=min(max(float(select_id_probability), 0.0), 1.0),
                **chaos_kwargs,
            )
            return case.case_id, Path(str(result["artifacts_dir"])), None
        except Exception as exc:  # noqa: BLE001
            return case.case_id, None, str(exc)[:240]

    # Full-case parallel mode: if caller does not pin worker count, fan out all cases.
    max_case_workers = max(1, int(case_max_workers)) if case_max_workers is not None else max(1, len(case_catalog))
    executor = ThreadPoolExecutor(max_workers=max_case_workers)
    future_map: dict[Any, str] = {}
    pending_futures: set[Any] = set()
    future_started_at: dict[Any, float] = {}
    hard_case_timeout_seconds = max(
        30.0,
        float(aggregate_timeout_seconds) + 30.0,
    )
    try:
        future_map = {executor.submit(_run_case, case): case.case_id for case in case_catalog}
        pending_futures = set(future_map.keys())
        future_started_at = {future: time.monotonic() for future in pending_futures}
        while pending_futures:
            done, _ = wait(pending_futures, timeout=1.0, return_when=FIRST_COMPLETED)
            now = time.monotonic()
            for future in done:
                pending_futures.discard(future)
                case_id = future_map[future]
                try:
                    resolved_case_id, artifact_dir, error = future.result()
                except Exception as exc:  # noqa: BLE001
                    case_failures[case_id] = f"case_runner_future_failed:{str(exc)[:200]}"
                    continue
                if error or artifact_dir is None:
                    case_failures[resolved_case_id] = error or "case_runner_failed"
                    continue
                case_artifacts[resolved_case_id] = artifact_dir
            for future in list(pending_futures):
                started_at = future_started_at.get(future, now)
                if now - started_at < hard_case_timeout_seconds:
                    continue
                case_id = future_map[future]
                case_failures[case_id] = f"case_timeout_guard:{int(hard_case_timeout_seconds)}s"
                pending_futures.discard(future)
                future.cancel()
    finally:
        for future in list(pending_futures):
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    case_summaries: list[dict[str, Any]] = []
    llm_text_case_summaries: list[dict[str, Any]] = []
    for case in case_catalog:
        artifact_dir = case_artifacts.get(case.case_id)
        error: str | None = case_failures.get(case.case_id)
        if artifact_dir is not None:
            try:
                case_summaries.append(_case_play_eval_summary(case.case_id, artifact_dir))
                if enable_llm_text_audit:
                    llm_text_case_summaries.append(_case_llm_text_audit_summary(case.case_id, artifact_dir))
                continue
            except Exception as exc:  # noqa: BLE001
                error = f"case_artifact_summary_failed:{str(exc)[:200]}"
                case_failures[case.case_id] = error
        fallback_error = error or "case_missing_artifacts"
        case_summaries.append(_case_play_eval_failure_summary(case_id=case.case_id, error=fallback_error))
        if enable_llm_text_audit:
            llm_text_case_summaries.append(_case_llm_text_failure_summary(case_id=case.case_id, error=fallback_error))
    coverage_min_success_required = max(1, PERSONA_COVERAGE_MIN_SUCCESS)
    coverage_expected_persona_count = max(1, PERSONA_COVERAGE_EXPECTED)
    quality_expected_persona_count = (
        min(coverage_expected_persona_count, max(1, int(session_play_eval_persona_limit)))
        if session_play_eval_persona_limit is not None
        else coverage_expected_persona_count
    )
    quality_min_success_required = min(coverage_min_success_required, quality_expected_persona_count)

    play_eval_summary_payload = play_eval_summary(case_summaries)
    persona_coverage_payload = persona_coverage_summary(
        case_summaries,
        min_success_personas_required=coverage_min_success_required,
        expected_persona_count=coverage_expected_persona_count,
        quality_min_success_personas_required=quality_min_success_required,
    )
    play_eval_summary_payload["persona_coverage"] = {
        "min_success_personas_required": persona_coverage_payload["min_success_personas_required"],
        "expected_persona_count": persona_coverage_payload["expected_persona_count"],
        "quality_min_success_personas_required": int(
            persona_coverage_payload.get("quality_min_success_personas_required", quality_min_success_required) or quality_min_success_required
        ),
        "invalid_case_ids": list(persona_coverage_payload["invalid_case_ids"]),
        "invalid_case_count": int(persona_coverage_payload["invalid_case_count"]),
        "quality_invalid_case_ids": list(persona_coverage_payload.get("quality_invalid_case_ids") or []),
        "quality_invalid_case_count": int(persona_coverage_payload.get("quality_invalid_case_count", 0) or 0),
        "quality_eval_incomplete_case_ids": list(persona_coverage_payload.get("quality_eval_incomplete_case_ids") or []),
        "quality_eval_incomplete_case_count": int(persona_coverage_payload.get("quality_eval_incomplete_case_count", 0) or 0),
        "valid_quality_case_ids": list(persona_coverage_payload.get("valid_quality_case_ids") or []),
        "valid_quality_case_count": int(persona_coverage_payload.get("valid_quality_case_count", 0) or 0),
    }
    _write_json(root / "play_eval_summary.json", play_eval_summary_payload)
    _write_json(root / "persona_coverage_summary.json", persona_coverage_payload)
    _write_json(
        root / "case_failures.json",
        {
            "failure_count": len(case_failures),
            "cases": dict(case_failures),
        },
    )
    llm_text_audit_summary_payload: dict[str, Any] | None = None
    if enable_llm_text_audit:
        llm_text_audit_summary_payload = llm_text_audit_summary(llm_text_case_summaries)
        _write_json(root / "llm_text_audit_summary.json", llm_text_audit_summary_payload)
    blockers = blockers_markdown(
        title=blockers_title,
        case_catalog=case_catalog,
        author_summary=author_summary,
        play_eval_summary_payload=play_eval_summary_payload,
        token_usage_summary_payload=token_usage_payload,
        persona_coverage_payload=persona_coverage_payload,
    )
    (root / blockers_filename).write_text(blockers)
    return {
        "artifacts_dir": str(root),
        "author_summary": author_summary,
        "play_eval_summary": play_eval_summary_payload,
        "llm_text_audit_summary": llm_text_audit_summary_payload,
        "token_usage_summary": token_usage_payload,
        "case_summaries": case_summaries,
        "llm_text_case_summaries": llm_text_case_summaries,
        "persona_coverage_summary": persona_coverage_payload,
        "case_failures": dict(case_failures),
    }
