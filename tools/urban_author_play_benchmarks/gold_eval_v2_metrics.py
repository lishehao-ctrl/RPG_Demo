from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase

PLAY_EVAL_SUCCESS_STATUSES: set[str] = {"completed", "partial_success"}
LLM_AUDIT_SUCCESS_STATUSES: set[str] = {"completed", "partial_success"}

PLAY_TURN_SCORE_KEYS: tuple[str, ...] = (
    "consequence_impact",
    "intent_binding",
    "pressure_exchange",
    "control_effectiveness",
    "trigger_conversion",
    "foreshadow_clarity",
    "shell_signal_fidelity",
    "npc_agency_reversal",
)
PLAY_SESSION_SCORE_KEYS: tuple[str, ...] = (
    "strategic_tension_curve",
    "consequence_legibility",
    "payoff_realization",
    "npc_interest_divergence",
    "control_tradeoff_quality",
    "shell_system_activation",
    "ending_cost_integrity",
    "replay_variance",
)
LLM_TURN_SCORE_KEYS: tuple[str, ...] = (
    "tone_naturalness",
    "character_specificity",
    "dramatic_tension",
    "shell_fidelity",
    "consequence_clarity",
    "anti_template_stiffness",
)
LLM_SESSION_SCORE_KEYS: tuple[str, ...] = (
    "arc_coherence",
    "payoff_strength",
    "npc_presence",
    "style_consistency",
    "shell_distinctiveness",
    "memorable_moments",
)
AUTHOR_PERF_KEYS: tuple[str, ...] = (
    "case_elapsed_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
)
PLAY_TURN_PERF_KEYS: tuple[str, ...] = (
    "decision_latency_ms",
    "runtime_latency_ms",
    "total_turn_latency_ms",
    "intent_stage_latency_ms",
    "intent_stage_input_tokens",
    "intent_stage_output_tokens",
    "intent_stage_total_tokens",
    "intent_llm_total_tokens",
    "micro_sim_total_tokens",
    "draft_call_count",
    "draft_input_tokens",
    "draft_output_tokens",
    "draft_total_tokens",
    "pre_submit_total_tokens",
    "post_submit_total_tokens",
    "play_turn_total_tokens",
    "compose_prewarm_total_tokens",
    "read_phase_prewarm_tokens",
    "typing_phase_prewarm_tokens",
    "submit_phase_tokens",
)
LLM_JUDGE_PERF_KEYS: tuple[str, ...] = (
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
)


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _to_int(value: Any) -> int:
    parsed = _to_float(value)
    if parsed is None:
        return 0
    return max(int(round(parsed)), 0)


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return round(float(ordered[0]), 4)
    rank = max(1, int(math.ceil(percentile * n)))
    index = min(max(rank - 1, 0), n - 1)
    return round(float(ordered[index]), 4)


def _quantiles(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"sample_count": 0, "median": 0.0, "p90": 0.0, "p95": 0.0}
    return {
        "sample_count": len(values),
        "median": round(float(median(values)), 4),
        "p90": _nearest_rank(values, 0.9),
        "p95": _nearest_rank(values, 0.95),
    }


def _build_metric_quantiles(metric_values: dict[str, list[float]], metric_keys: tuple[str, ...]) -> dict[str, dict[str, float | int]]:
    return {
        metric: _quantiles(list(metric_values.get(metric) or []))
        for metric in metric_keys
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        payload = line.strip()
        if not payload:
            continue
        rows.append(json.loads(payload))
    return rows


def _rate_entry(*, numerator: int, denominator: int) -> dict[str, float | int]:
    return {
        "value": round((numerator / denominator), 4) if denominator > 0 else 0.0,
        "numerator": max(int(numerator), 0),
        "denominator": max(int(denominator), 0),
        "sample_count": max(int(denominator), 0),
    }


def _empty_metric_store(metric_keys: tuple[str, ...]) -> dict[str, list[float]]:
    return {metric: [] for metric in metric_keys}


def _append_metric_values(store: dict[str, list[float]], metric_keys: tuple[str, ...], scores: dict[str, Any] | None) -> None:
    if not isinstance(scores, dict):
        return
    for metric in metric_keys:
        parsed = _to_float(scores.get(metric))
        if parsed is None:
            continue
        store.setdefault(metric, []).append(parsed)


def _append_perf_values(store: dict[str, list[float]], metric_keys: tuple[str, ...], payload: dict[str, Any]) -> None:
    for metric in metric_keys:
        parsed = _to_float(payload.get(metric))
        if parsed is None:
            continue
        store.setdefault(metric, []).append(parsed)


def _to_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _turn_input_mode_from_turn_log(turn_log: dict[str, Any]) -> str | None:
    raw_mode = str(turn_log.get("turn_input_mode") or "").strip().lower()
    if raw_mode in {"free_input", "select_id"}:
        return raw_mode
    submitted_with_selected_ids = _to_optional_bool(turn_log.get("submitted_with_selected_ids"))
    if submitted_with_selected_ids is None:
        return None
    return "select_id" if submitted_with_selected_ids else "free_input"


def _risk_payload(flag_counter: Counter[str], turn_count: int) -> dict[str, Any]:
    tags = {
        tag: {
            "count": int(count),
            "per_100_turns": round((count * 100.0 / turn_count), 4) if turn_count > 0 else 0.0,
        }
        for tag, count in flag_counter.most_common()
    }
    return {"turn_count": max(turn_count, 0), "tags": tags}


def _quality_quantiles_payload(
    *,
    turn_metric_global: dict[str, list[float]],
    turn_metric_by_shell: dict[str, dict[str, list[float]]],
    session_metric_global: dict[str, list[float]],
    session_metric_by_shell: dict[str, dict[str, list[float]]],
    turn_metric_keys: tuple[str, ...],
    session_metric_keys: tuple[str, ...],
) -> dict[str, Any]:
    by_shell: dict[str, Any] = {}
    for shell_id in sorted(set(turn_metric_by_shell.keys()) | set(session_metric_by_shell.keys())):
        by_shell[shell_id] = {
            "turn": _build_metric_quantiles(turn_metric_by_shell.get(shell_id, {}), turn_metric_keys),
            "session": _build_metric_quantiles(session_metric_by_shell.get(shell_id, {}), session_metric_keys),
        }
    return {
        "global": {
            "turn": _build_metric_quantiles(turn_metric_global, turn_metric_keys),
            "session": _build_metric_quantiles(session_metric_global, session_metric_keys),
        },
        "by_shell": by_shell,
    }


def _performance_quantiles_payload(
    *,
    global_metrics: dict[str, list[float]],
    by_shell_metrics: dict[str, dict[str, list[float]]],
    metric_keys: tuple[str, ...],
    by_input_mode_metrics: dict[str, dict[str, list[float]]] | None = None,
) -> dict[str, Any]:
    by_shell: dict[str, Any] = {}
    for shell_id in sorted(by_shell_metrics.keys()):
        by_shell[shell_id] = _build_metric_quantiles(by_shell_metrics[shell_id], metric_keys)
    payload = {
        "global": _build_metric_quantiles(global_metrics, metric_keys),
        "by_shell": by_shell,
    }
    if by_input_mode_metrics is not None:
        payload["by_input_mode"] = {
            mode: _build_metric_quantiles(by_input_mode_metrics.get(mode, {}), metric_keys)
            for mode in ("free_input", "select_id")
        }
    return payload


def _collect_case_shell_map(case_catalog: list[UrbanGoldCase]) -> dict[str, str]:
    return {case.case_id: case.expected_shell for case in case_catalog}


def _collect_author_performance(
    *,
    author_summary: dict[str, Any],
    case_shell_map: dict[str, str],
) -> tuple[dict[str, list[float]], dict[str, dict[str, list[float]]]]:
    global_store = _empty_metric_store(AUTHOR_PERF_KEYS)
    by_shell_store: dict[str, dict[str, list[float]]] = defaultdict(lambda: _empty_metric_store(AUTHOR_PERF_KEYS))
    for row in list(author_summary.get("benchmark_results") or []):
        case_id = str(row.get("case_id") or "")
        if not case_id:
            continue
        shell_id = str(case_shell_map.get(case_id) or row.get("shell_id") or "unknown")
        llm_call_trace = list(row.get("llm_call_trace") or [])
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        elapsed_ms = 0.0
        for trace in llm_call_trace:
            if not isinstance(trace, dict):
                continue
            usage = dict(trace.get("usage") or {})
            input_tokens += _to_int(usage.get("input_tokens"))
            output_tokens += _to_int(usage.get("output_tokens"))
            raw_total = _to_int(usage.get("total_tokens"))
            total_tokens += raw_total if raw_total > 0 else (_to_int(usage.get("input_tokens")) + _to_int(usage.get("output_tokens")))
            duration_s = _to_float(trace.get("duration_seconds"))
            if duration_s is not None:
                elapsed_ms += max(duration_s, 0.0) * 1000.0
        payload = {
            "case_elapsed_ms": elapsed_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
        _append_perf_values(global_store, AUTHOR_PERF_KEYS, payload)
        _append_perf_values(by_shell_store[shell_id], AUTHOR_PERF_KEYS, payload)
    return global_store, dict(by_shell_store)


def _load_persona_dirs(artifact_dir: Path) -> list[Path]:
    personas_root = artifact_dir / "personas"
    if not personas_root.exists():
        return []
    return sorted(path for path in personas_root.iterdir() if path.is_dir())


def build_gold_eval_v2_outputs(
    *,
    case_catalog: list[UrbanGoldCase],
    author_summary: dict[str, Any],
    case_summaries: list[dict[str, Any]],
    llm_text_case_summaries: list[dict[str, Any]] | None,
    persona_coverage_summary: dict[str, Any],
    case_failures: dict[str, str] | None,
) -> dict[str, Any]:
    case_shell_map = _collect_case_shell_map(case_catalog)
    case_count = len(case_catalog)
    failure_map = dict(case_failures or {})

    play_turn_global = _empty_metric_store(PLAY_TURN_SCORE_KEYS)
    play_turn_by_shell: dict[str, dict[str, list[float]]] = defaultdict(lambda: _empty_metric_store(PLAY_TURN_SCORE_KEYS))
    play_session_global = _empty_metric_store(PLAY_SESSION_SCORE_KEYS)
    play_session_by_shell: dict[str, dict[str, list[float]]] = defaultdict(lambda: _empty_metric_store(PLAY_SESSION_SCORE_KEYS))
    play_flag_global: Counter[str] = Counter()
    play_flag_by_shell: dict[str, Counter[str]] = defaultdict(Counter)
    play_turn_count_global = 0
    play_turn_count_by_shell: Counter[str] = Counter()

    llm_turn_global = _empty_metric_store(LLM_TURN_SCORE_KEYS)
    llm_turn_by_shell: dict[str, dict[str, list[float]]] = defaultdict(lambda: _empty_metric_store(LLM_TURN_SCORE_KEYS))
    llm_session_global = _empty_metric_store(LLM_SESSION_SCORE_KEYS)
    llm_session_by_shell: dict[str, dict[str, list[float]]] = defaultdict(lambda: _empty_metric_store(LLM_SESSION_SCORE_KEYS))
    llm_flag_global: Counter[str] = Counter()
    llm_flag_by_shell: dict[str, Counter[str]] = defaultdict(Counter)
    llm_turn_count_global = 0
    llm_turn_count_by_shell: Counter[str] = Counter()

    play_eval_failed_turn_count = 0
    play_eval_turn_total = 0
    play_eval_failed_session_count = 0
    play_eval_session_total = 0
    llm_audit_failed_turn_count = 0
    llm_audit_turn_total = 0
    llm_audit_failed_session_count = 0
    llm_audit_session_total = 0

    play_perf_global = _empty_metric_store(PLAY_TURN_PERF_KEYS)
    play_perf_by_shell: dict[str, dict[str, list[float]]] = defaultdict(lambda: _empty_metric_store(PLAY_TURN_PERF_KEYS))
    play_perf_by_input_mode: dict[str, dict[str, list[float]]] = {
        "free_input": _empty_metric_store(PLAY_TURN_PERF_KEYS),
        "select_id": _empty_metric_store(PLAY_TURN_PERF_KEYS),
    }
    llm_perf_global = _empty_metric_store(LLM_JUDGE_PERF_KEYS)
    llm_perf_by_shell: dict[str, dict[str, list[float]]] = defaultdict(lambda: _empty_metric_store(LLM_JUDGE_PERF_KEYS))

    for case_summary in case_summaries:
        case_id = str(case_summary.get("case_id") or "")
        artifact_path_raw = str(case_summary.get("artifacts_dir") or "").strip()
        if not case_id or not artifact_path_raw:
            continue
        artifact_dir = Path(artifact_path_raw)
        if not artifact_dir.exists():
            continue
        default_shell = str(case_shell_map.get(case_id) or "unknown")
        for persona_dir in _load_persona_dirs(artifact_dir):
            # play turn quality + play turn performance
            for turn_record in _read_jsonl(persona_dir / "turn_play_eval_logs.jsonl"):
                shell_id = str(turn_record.get("story_shell_id") or default_shell)
                status = str(turn_record.get("play_eval_status") or "")
                play_eval_turn_total += 1
                if status not in PLAY_EVAL_SUCCESS_STATUSES or not isinstance(turn_record.get("scores"), dict):
                    play_eval_failed_turn_count += 1
                else:
                    scores = dict(turn_record.get("scores") or {})
                    _append_metric_values(play_turn_global, PLAY_TURN_SCORE_KEYS, scores)
                    _append_metric_values(play_turn_by_shell[shell_id], PLAY_TURN_SCORE_KEYS, scores)
                flags = [flag for flag in list(turn_record.get("flags") or []) if isinstance(flag, str) and flag.strip()]
                if flags:
                    play_flag_global.update(flags)
                    play_flag_by_shell[shell_id].update(flags)
                play_turn_count_global += 1
                play_turn_count_by_shell[shell_id] += 1

            for turn_log in _read_jsonl(persona_dir / "turn_logs.jsonl"):
                shell_id = default_shell
                payload = {
                    "decision_latency_ms": _to_float(turn_log.get("decision_latency_ms")) or 0.0,
                    "runtime_latency_ms": _to_float(turn_log.get("runtime_latency_ms")) or 0.0,
                    "total_turn_latency_ms": _to_float(turn_log.get("total_turn_latency_ms")) or 0.0,
                    "intent_stage_latency_ms": _to_float(turn_log.get("intent_stage_latency_ms")) or 0.0,
                    "intent_stage_input_tokens": _to_float(turn_log.get("intent_stage_input_tokens")) or 0.0,
                    "intent_stage_output_tokens": _to_float(turn_log.get("intent_stage_output_tokens")) or 0.0,
                    "intent_stage_total_tokens": _to_float(turn_log.get("intent_stage_total_tokens")) or 0.0,
                    "intent_llm_total_tokens": _to_float(turn_log.get("intent_llm_total_tokens")) or 0.0,
                    "micro_sim_total_tokens": _to_float(turn_log.get("micro_sim_total_tokens")) or 0.0,
                    "draft_call_count": _to_float(turn_log.get("draft_call_count")) or 0.0,
                    "draft_input_tokens": _to_float(turn_log.get("draft_input_tokens")) or 0.0,
                    "draft_output_tokens": _to_float(turn_log.get("draft_output_tokens")) or 0.0,
                    "draft_total_tokens": _to_float(turn_log.get("draft_total_tokens")) or 0.0,
                    "pre_submit_total_tokens": _to_float(turn_log.get("pre_submit_total_tokens")) or 0.0,
                    "post_submit_total_tokens": _to_float(turn_log.get("post_submit_total_tokens")) or 0.0,
                    "play_turn_total_tokens": _to_float(turn_log.get("play_turn_total_tokens")) or 0.0,
                    "compose_prewarm_total_tokens": _to_float(turn_log.get("compose_prewarm_total_tokens")) or 0.0,
                    "read_phase_prewarm_tokens": _to_float(turn_log.get("read_phase_prewarm_tokens")) or 0.0,
                    "typing_phase_prewarm_tokens": _to_float(turn_log.get("typing_phase_prewarm_tokens")) or 0.0,
                    "submit_phase_tokens": _to_float(turn_log.get("submit_phase_tokens")) or 0.0,
                }
                _append_perf_values(play_perf_global, PLAY_TURN_PERF_KEYS, payload)
                _append_perf_values(play_perf_by_shell[shell_id], PLAY_TURN_PERF_KEYS, payload)
                input_mode = _turn_input_mode_from_turn_log(turn_log)
                if input_mode in play_perf_by_input_mode:
                    _append_perf_values(play_perf_by_input_mode[input_mode], PLAY_TURN_PERF_KEYS, payload)

            # play session quality
            session_play_eval_path = persona_dir / "session_play_eval_report.json"
            if session_play_eval_path.exists():
                report = _read_json(session_play_eval_path)
                shell_id = default_shell
                status = str(report.get("play_eval_status") or "")
                play_eval_session_total += 1
                if status not in PLAY_EVAL_SUCCESS_STATUSES or not isinstance(report.get("scores"), dict):
                    play_eval_failed_session_count += 1
                else:
                    scores = dict(report.get("scores") or {})
                    _append_metric_values(play_session_global, PLAY_SESSION_SCORE_KEYS, scores)
                    _append_metric_values(play_session_by_shell[shell_id], PLAY_SESSION_SCORE_KEYS, scores)

            # llm turn quality + llm judge performance
            for turn_record in _read_jsonl(persona_dir / "turn_llm_text_audit_logs.jsonl"):
                shell_id = str(turn_record.get("story_shell_id") or default_shell)
                status = str(turn_record.get("llm_audit_status") or "")
                llm_audit_turn_total += 1
                if status not in LLM_AUDIT_SUCCESS_STATUSES or not isinstance(turn_record.get("scores"), dict):
                    llm_audit_failed_turn_count += 1
                else:
                    scores = dict(turn_record.get("scores") or {})
                    _append_metric_values(llm_turn_global, LLM_TURN_SCORE_KEYS, scores)
                    _append_metric_values(llm_turn_by_shell[shell_id], LLM_TURN_SCORE_KEYS, scores)
                flags = [flag for flag in list(turn_record.get("flags") or []) if isinstance(flag, str) and flag.strip()]
                if flags:
                    llm_flag_global.update(flags)
                    llm_flag_by_shell[shell_id].update(flags)
                llm_turn_count_global += 1
                llm_turn_count_by_shell[shell_id] += 1
                for endpoint in list(turn_record.get("endpoint_results") or []):
                    if not isinstance(endpoint, dict):
                        continue
                    input_tokens = _to_float(endpoint.get("input_tokens")) or 0.0
                    output_tokens = _to_float(endpoint.get("output_tokens")) or 0.0
                    payload = {
                        "latency_ms": _to_float(endpoint.get("latency_ms")) or 0.0,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    }
                    _append_perf_values(llm_perf_global, LLM_JUDGE_PERF_KEYS, payload)
                    _append_perf_values(llm_perf_by_shell[shell_id], LLM_JUDGE_PERF_KEYS, payload)

            # llm session quality + llm judge performance
            session_llm_audit_path = persona_dir / "session_llm_text_audit_report.json"
            if session_llm_audit_path.exists():
                report = _read_json(session_llm_audit_path)
                shell_id = default_shell
                status = str(report.get("llm_audit_status") or "")
                llm_audit_session_total += 1
                if status not in LLM_AUDIT_SUCCESS_STATUSES or not isinstance(report.get("scores"), dict):
                    llm_audit_failed_session_count += 1
                else:
                    scores = dict(report.get("scores") or {})
                    _append_metric_values(llm_session_global, LLM_SESSION_SCORE_KEYS, scores)
                    _append_metric_values(llm_session_by_shell[shell_id], LLM_SESSION_SCORE_KEYS, scores)
                for endpoint in list(report.get("endpoint_results") or []):
                    if not isinstance(endpoint, dict):
                        continue
                    input_tokens = _to_float(endpoint.get("input_tokens")) or 0.0
                    output_tokens = _to_float(endpoint.get("output_tokens")) or 0.0
                    payload = {
                        "latency_ms": _to_float(endpoint.get("latency_ms")) or 0.0,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    }
                    _append_perf_values(llm_perf_global, LLM_JUDGE_PERF_KEYS, payload)
                    _append_perf_values(llm_perf_by_shell[shell_id], LLM_JUDGE_PERF_KEYS, payload)

    author_perf_global, author_perf_by_shell = _collect_author_performance(
        author_summary=author_summary,
        case_shell_map=case_shell_map,
    )

    expected_persona_count = int(persona_coverage_summary.get("expected_persona_count", 5) or 5)
    persona_rows = {
        str(row.get("case_id") or ""): row
        for row in list(persona_coverage_summary.get("cases") or [])
        if isinstance(row, dict)
    }
    persona_total_expected = case_count * max(expected_persona_count, 0)
    persona_fail_count = 0
    for case in case_catalog:
        row = dict(persona_rows.get(case.case_id) or {})
        success_count = int(row.get("successful_persona_count", 0) or 0)
        persona_fail_count += max(expected_persona_count - success_count, 0)

    timeout_case_count = sum(
        1
        for message in failure_map.values()
        if isinstance(message, str) and "timeout" in message.lower()
    )
    invalid_case_count = int(persona_coverage_summary.get("invalid_case_count", 0) or 0)
    quality_invalid_case_count = int(persona_coverage_summary.get("quality_invalid_case_count", 0) or 0)

    fail_rates = {
        "case_fail_rate": _rate_entry(numerator=len(failure_map), denominator=case_count),
        "invalid_case_rate": _rate_entry(numerator=invalid_case_count, denominator=case_count),
        "quality_invalid_case_rate": _rate_entry(numerator=quality_invalid_case_count, denominator=case_count),
        "persona_fail_rate": _rate_entry(numerator=persona_fail_count, denominator=persona_total_expected),
        "play_eval_failed_turn_rate": _rate_entry(
            numerator=play_eval_failed_turn_count,
            denominator=play_eval_turn_total,
        ),
        "play_eval_failed_session_rate": _rate_entry(
            numerator=play_eval_failed_session_count,
            denominator=play_eval_session_total,
        ),
        "llm_audit_failed_turn_rate": _rate_entry(
            numerator=llm_audit_failed_turn_count,
            denominator=llm_audit_turn_total,
        ),
        "llm_audit_failed_session_rate": _rate_entry(
            numerator=llm_audit_failed_session_count,
            denominator=llm_audit_session_total,
        ),
        "timeout_case_rate": _rate_entry(numerator=timeout_case_count, denominator=case_count),
    }

    play_eval_summary_v2 = {
        "metric_contract_version": 2,
        "quantile_granularity": "global_and_shell",
        "quality_quantiles": _quality_quantiles_payload(
            turn_metric_global=play_turn_global,
            turn_metric_by_shell=dict(play_turn_by_shell),
            session_metric_global=play_session_global,
            session_metric_by_shell=dict(play_session_by_shell),
            turn_metric_keys=PLAY_TURN_SCORE_KEYS,
            session_metric_keys=PLAY_SESSION_SCORE_KEYS,
        ),
        "risk_tags": {
            "global": _risk_payload(play_flag_global, play_turn_count_global),
            "by_shell": {
                shell_id: _risk_payload(play_flag_by_shell[shell_id], int(play_turn_count_by_shell.get(shell_id, 0)))
                for shell_id in sorted(set(play_flag_by_shell.keys()) | set(play_turn_count_by_shell.keys()))
            },
        },
        "fail_rates": fail_rates,
    }

    llm_text_audit_summary_v2 = {
        "metric_contract_version": 2,
        "quantile_granularity": "global_and_shell",
        "quality_quantiles": _quality_quantiles_payload(
            turn_metric_global=llm_turn_global,
            turn_metric_by_shell=dict(llm_turn_by_shell),
            session_metric_global=llm_session_global,
            session_metric_by_shell=dict(llm_session_by_shell),
            turn_metric_keys=LLM_TURN_SCORE_KEYS,
            session_metric_keys=LLM_SESSION_SCORE_KEYS,
        ),
        "risk_tags": {
            "global": _risk_payload(llm_flag_global, llm_turn_count_global),
            "by_shell": {
                shell_id: _risk_payload(llm_flag_by_shell[shell_id], int(llm_turn_count_by_shell.get(shell_id, 0)))
                for shell_id in sorted(set(llm_flag_by_shell.keys()) | set(llm_turn_count_by_shell.keys()))
            },
        },
        "fail_rates": fail_rates,
    }

    performance_summary = {
        "metric_contract_version": 2,
        "quantile_granularity": "global_and_shell",
        "author_generation": _performance_quantiles_payload(
            global_metrics=author_perf_global,
            by_shell_metrics=author_perf_by_shell,
            metric_keys=AUTHOR_PERF_KEYS,
        ),
        "play_turn": _performance_quantiles_payload(
            global_metrics=play_perf_global,
            by_shell_metrics=dict(play_perf_by_shell),
            metric_keys=PLAY_TURN_PERF_KEYS,
            by_input_mode_metrics=play_perf_by_input_mode,
        ),
        "llm_judge": _performance_quantiles_payload(
            global_metrics=llm_perf_global,
            by_shell_metrics=dict(llm_perf_by_shell),
            metric_keys=LLM_JUDGE_PERF_KEYS,
        ),
    }

    return {
        "play_eval_summary": play_eval_summary_v2,
        "llm_text_audit_summary": llm_text_audit_summary_v2,
        "performance_summary": performance_summary,
        "fail_rates": fail_rates,
    }


def build_gold_eval_v2_effect_report(
    *,
    suite_type: str,
    profile: str,
    case_count: int,
    play_eval_summary: dict[str, Any],
    llm_text_audit_summary: dict[str, Any],
    performance_summary: dict[str, Any],
) -> str:
    play_session_global = dict(dict(play_eval_summary.get("quality_quantiles") or {}).get("global") or {}).get("session") or {}
    llm_session_global = dict(dict(llm_text_audit_summary.get("quality_quantiles") or {}).get("global") or {}).get("session") or {}
    fail_rates = dict(play_eval_summary.get("fail_rates") or {})

    def _metric_line(metrics: dict[str, Any], metric: str) -> str:
        payload = dict(metrics.get(metric) or {})
        return (
            f"`{metric}` median={float(payload.get('median', 0.0)):.4f} "
            f"p90={float(payload.get('p90', 0.0)):.4f} "
            f"p95={float(payload.get('p95', 0.0)):.4f} "
            f"(n={int(payload.get('sample_count', 0) or 0)})"
        )

    lines = [
        "# Gold Eval v2 Effect Report",
        "",
        "## Run",
        "",
        f"- suite_type: `{suite_type}`",
        f"- profile: `{profile}`",
        f"- case_count: {int(case_count)}",
        "",
        "## PlayEval Session Quantiles (Global)",
        "",
        f"- {_metric_line(play_session_global, 'strategic_tension_curve')}",
        f"- {_metric_line(play_session_global, 'payoff_realization')}",
        f"- {_metric_line(play_session_global, 'npc_interest_divergence')}",
        f"- {_metric_line(play_session_global, 'shell_system_activation')}",
        "",
        "## LLM Text Audit Session Quantiles (Global)",
        "",
        f"- {_metric_line(llm_session_global, 'arc_coherence')}",
        f"- {_metric_line(llm_session_global, 'payoff_strength')}",
        f"- {_metric_line(llm_session_global, 'npc_presence')}",
        f"- {_metric_line(llm_session_global, 'shell_distinctiveness')}",
        "",
        "## Fail Rates",
        "",
    ]
    for key in (
        "case_fail_rate",
        "invalid_case_rate",
        "quality_invalid_case_rate",
        "persona_fail_rate",
        "play_eval_failed_turn_rate",
        "play_eval_failed_session_rate",
        "llm_audit_failed_turn_rate",
        "llm_audit_failed_session_rate",
        "timeout_case_rate",
    ):
        payload = dict(fail_rates.get(key) or {})
        lines.append(
            f"- `{key}` value={float(payload.get('value', 0.0)):.4f} "
            f"({int(payload.get('numerator', 0) or 0)}/{int(payload.get('denominator', 0) or 0)})"
        )

    perf = dict(performance_summary or {})
    author_global = dict(dict(perf.get("author_generation") or {}).get("global") or {})
    play_global = dict(dict(perf.get("play_turn") or {}).get("global") or {})
    judge_global = dict(dict(perf.get("llm_judge") or {}).get("global") or {})
    lines.extend(
        [
            "",
            "## Performance Quantiles (Global)",
            "",
            f"- author_generation.case_elapsed_ms: {_metric_line(author_global, 'case_elapsed_ms')}",
            f"- play_turn.total_turn_latency_ms: {_metric_line(play_global, 'total_turn_latency_ms')}",
            f"- play_turn.intent_stage_total_tokens: {_metric_line(play_global, 'intent_stage_total_tokens')}",
            f"- llm_judge.latency_ms: {_metric_line(judge_global, 'latency_ms')}",
            f"- llm_judge.total_tokens: {_metric_line(judge_global, 'total_tokens')}",
        ]
    )
    return "\n".join(lines) + "\n"
