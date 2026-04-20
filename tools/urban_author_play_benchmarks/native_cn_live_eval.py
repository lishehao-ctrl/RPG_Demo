from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from rpg_backend.config import get_settings
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase, native_cn_gold_realistic_14
from tools.urban_author_play_benchmarks.runner import LIVE_BENCHMARK_MODES, run_benchmark
from tools.urban_author_play_benchmarks.self_play_runner import run_self_play_pilot

LIVE_MODE = "pure_gpt"
DEFAULT_TOP_CASES = 3
DEFAULT_EXECUTION_MODE = "parallel"
LEGACY_LIVE_MODE_ALIASES = {
    "openai_prompted": "pure_gpt",
}


def _to_jsonable(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json")
    if isinstance(payload, list):
        return [_to_jsonable(item) for item in payload]
    if isinstance(payload, tuple):
        return [_to_jsonable(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _to_jsonable(value) for key, value in payload.items()}
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _as_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return {}


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _smoke_results(summary: dict[str, Any], *, live_mode: str) -> list[dict[str, Any]]:
    return list(summary.get("smoke", {}).get("mode_summaries", {}).get(live_mode, {}).get("results", []))


def _normalize_live_mode(live_mode: str) -> str:
    return LEGACY_LIVE_MODE_ALIASES.get(live_mode, live_mode)


def _select_top_cases(
    *,
    case_catalog: list[UrbanGoldCase],
    results: list[dict[str, Any]],
    top_n: int = DEFAULT_TOP_CASES,
) -> list[dict[str, Any]]:
    by_id = {case.case_id: case for case in case_catalog}
    passing = [
        result
        for result in results
        if bool(result.get("passed")) and str(result.get("case_id")) in by_id
    ]
    ordered = sorted(
        passing,
        key=lambda item: (
            -float(item.get("content_score", 0.0)),
            -float(item.get("live_depth_score", 0.0)),
            -float(item.get("structure_score", 0.0)),
            str(item.get("case_id")),
        ),
    )
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen_shells: set[str] = set()
    for result in ordered:
        case = by_id[str(result["case_id"])]
        enriched = {
            "case_id": case.case_id,
            "expected_shell": case.expected_shell,
            "expected_band": case.expected_band,
            "content_score": float(result.get("content_score", 0.0)),
            "structure_score": float(result.get("structure_score", 0.0)),
            "live_depth_score": int(result.get("live_depth_score", 0)),
            "final_mode_path": str(result.get("final_mode_path") or "deterministic"),
        }
        if case.expected_shell not in seen_shells and len(selected) < top_n:
            selected.append(enriched)
            seen_shells.add(case.expected_shell)
        else:
            deferred.append(enriched)
    for item in deferred:
        if len(selected) >= top_n:
            break
        selected.append(item)
    return selected


def _smoke_shell_summary(case_catalog: list[UrbanGoldCase], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {case.case_id: case for case in case_catalog}
    per_shell: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        case = by_id.get(str(result.get("case_id")))
        if case is None:
            continue
        per_shell.setdefault(case.expected_shell, []).append(result)
    shell_rows: list[dict[str, Any]] = []
    for shell_id, shell_results in per_shell.items():
        shell_rows.append(
            {
                "shell_id": shell_id,
                "case_count": len(shell_results),
                "pass_rate": round(
                    sum(1 for item in shell_results if item.get("passed")) / len(shell_results),
                    4,
                ),
                "avg_content_score": round(mean(float(item.get("content_score", 0.0)) for item in shell_results), 4),
                "avg_live_depth_score": round(mean(float(item.get("live_depth_score", 0.0)) for item in shell_results), 4),
            }
        )
    return sorted(shell_rows, key=lambda item: (-item["avg_content_score"], -item["pass_rate"], item["shell_id"]))


def _turn_play_eval_records(case_artifact_dir: Path) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {}
    for persona_dir in sorted((case_artifact_dir / "personas").glob("*")):
        if not persona_dir.is_dir():
            continue
        records[persona_dir.name] = _read_jsonl(persona_dir / "turn_play_eval_logs.jsonl")
    return records


def _session_play_eval_reports(case_artifact_dir: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for persona_dir in sorted((case_artifact_dir / "personas").glob("*")):
        if not persona_dir.is_dir():
            continue
        report_path = persona_dir / "session_play_eval_report.json"
        if report_path.exists():
            reports[persona_dir.name] = _as_dict(_read_json(report_path))
    return reports


def _mean_session_play_eval_score(reports: dict[str, dict[str, Any]], metric: str) -> float:
    values: list[float] = []
    for report in reports.values():
        report_payload = _as_dict(report)
        if str(report_payload.get("play_eval_status") or "") not in {"completed", "partial_success"}:
            continue
        scores = _as_dict(report_payload.get("scores"))
        numeric = _numeric(scores.get(metric))
        if numeric is None:
            continue
        values.append(numeric)
    return round(mean(values), 4) if values else 0.0


def _session_play_eval_counts(reports: dict[str, dict[str, Any]]) -> tuple[int, int]:
    total = len(reports)
    completed = sum(
        1
        for report in reports.values()
        if str(_as_dict(report).get("play_eval_status") or "") in {"completed", "partial_success"}
        and isinstance(_as_dict(report).get("scores"), dict)
    )
    return completed, total


def _mean_turn_play_eval_score(turn_records: dict[str, list[dict[str, Any]]], metric: str) -> float:
    values: list[float] = []
    for records in turn_records.values():
        for record in records:
            record_payload = _as_dict(record)
            if str(record_payload.get("play_eval_status") or "") != "completed":
                continue
            scores = _as_dict(record_payload.get("scores"))
            numeric = _numeric(scores.get(metric))
            if numeric is None:
                continue
            values.append(numeric)
    return round(mean(values), 4) if values else 0.0


def _mean_turn_play_eval_rate(turn_records: dict[str, list[dict[str, Any]]], marker: str) -> float:
    values = [
        bool(record.get(marker))
        for records in turn_records.values()
        for record in records
        if record.get("play_eval_status") == "completed" and record.get(marker) is not None
    ]
    if not values:
        return 0.0
    return round(sum(1 for value in values if value) / len(values), 4)


def _aggregate_flags(turn_records: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for records in turn_records.values():
        for record in records:
            record_payload = _as_dict(record)
            counter.update(flag for flag in list(record_payload.get("flags") or []) if isinstance(flag, str))
    return dict(counter.most_common())


def _aggregate_session_items(reports: dict[str, dict[str, Any]], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for report in reports.values():
        report_payload = _as_dict(report)
        for item in list(report_payload.get(key) or []):
            if isinstance(item, str) and item.strip():
                counter[item.strip()] += 1
    return dict(counter.most_common())


def _case_play_eval_summary(case_id: str, artifact_dir: Path) -> dict[str, Any]:
    turn_records = _turn_play_eval_records(artifact_dir)
    session_reports = _session_play_eval_reports(artifact_dir)
    session_completed_count, session_total_count = _session_play_eval_counts(session_reports)
    comparison = _read_json(artifact_dir / "comparison_summary.json")
    return {
        "case_id": case_id,
        "artifacts_dir": str(artifact_dir),
        "comparison_summary": comparison,
        "turn_flag_counts": _aggregate_flags(turn_records),
        "session_reports": session_reports,
        "session_play_eval_completed_count": session_completed_count,
        "session_play_eval_total_count": session_total_count,
        "session_play_eval_incomplete": session_total_count > 0 and session_completed_count < session_total_count,
        "avg_strategic_tension_curve": _mean_session_play_eval_score(session_reports, "strategic_tension_curve"),
        "avg_consequence_legibility": _mean_session_play_eval_score(session_reports, "consequence_legibility"),
        "avg_payoff_realization": _mean_session_play_eval_score(session_reports, "payoff_realization"),
        "avg_npc_interest_divergence": _mean_session_play_eval_score(session_reports, "npc_interest_divergence"),
        "avg_control_tradeoff_quality": _mean_session_play_eval_score(session_reports, "control_tradeoff_quality"),
        "avg_shell_system_activation": _mean_session_play_eval_score(session_reports, "shell_system_activation"),
        "avg_ending_cost_integrity": _mean_session_play_eval_score(session_reports, "ending_cost_integrity"),
        "avg_replay_variance": _mean_session_play_eval_score(session_reports, "replay_variance"),
        "avg_turn_consequence_impact": _mean_turn_play_eval_score(turn_records, "consequence_impact"),
        "avg_turn_intent_binding": _mean_turn_play_eval_score(turn_records, "intent_binding"),
        "avg_turn_pressure_exchange": _mean_turn_play_eval_score(turn_records, "pressure_exchange"),
        "avg_key_segment_shell_anchor_hit_rate": _mean_turn_play_eval_rate(turn_records, "key_segment_shell_anchor_hit"),
        "top_play_eval_issues": _aggregate_session_items(session_reports, "top_issues"),
        "top_play_eval_strengths": _aggregate_session_items(session_reports, "top_strengths"),
    }


def _turn_llm_text_audit_records(case_artifact_dir: Path) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {}
    for persona_dir in sorted((case_artifact_dir / "personas").glob("*")):
        if not persona_dir.is_dir():
            continue
        records[persona_dir.name] = _read_jsonl(persona_dir / "turn_llm_text_audit_logs.jsonl")
    return records


def _session_llm_text_audit_reports(case_artifact_dir: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for persona_dir in sorted((case_artifact_dir / "personas").glob("*")):
        if not persona_dir.is_dir():
            continue
        report_path = persona_dir / "session_llm_text_audit_report.json"
        if report_path.exists():
            reports[persona_dir.name] = _as_dict(_read_json(report_path))
    return reports


def _mean_session_llm_text_audit_score(reports: dict[str, dict[str, Any]], metric: str) -> float:
    values: list[float] = []
    for report in reports.values():
        report_payload = _as_dict(report)
        if str(report_payload.get("llm_audit_status") or "") not in {"completed", "partial_success"}:
            continue
        scores = _as_dict(report_payload.get("scores"))
        numeric = _numeric(scores.get(metric))
        if numeric is None:
            continue
        values.append(numeric)
    return round(mean(values), 4) if values else 0.0


def _mean_turn_llm_text_audit_score(turn_records: dict[str, list[dict[str, Any]]], metric: str) -> float:
    values: list[float] = []
    for records in turn_records.values():
        for record in records:
            record_payload = _as_dict(record)
            if str(record_payload.get("llm_audit_status") or "") not in {"completed", "partial_success"}:
                continue
            scores = _as_dict(record_payload.get("scores"))
            numeric = _numeric(scores.get(metric))
            if numeric is None:
                continue
            values.append(numeric)
    return round(mean(values), 4) if values else 0.0


def _aggregate_llm_flags(turn_records: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for records in turn_records.values():
        for record in records:
            record_payload = _as_dict(record)
            counter.update(flag for flag in list(record_payload.get("flags") or []) if isinstance(flag, str))
    return dict(counter.most_common())


def _aggregate_llm_session_items(reports: dict[str, dict[str, Any]], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for report in reports.values():
        report_payload = _as_dict(report)
        for item in list(report_payload.get(key) or []):
            if isinstance(item, str) and item.strip():
                counter[item.strip()] += 1
    return dict(counter.most_common())


def _llm_text_audit_usage_totals(
    turn_records: dict[str, list[dict[str, Any]]],
    session_reports: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    for records in turn_records.values():
        for record in records:
            record_payload = _as_dict(record)
            for endpoint in list(record_payload.get("endpoint_results") or []):
                if not isinstance(endpoint, dict):
                    continue
                input_tokens += int(endpoint.get("input_tokens", 0) or 0)
                output_tokens += int(endpoint.get("output_tokens", 0) or 0)
    for report in session_reports.values():
        report_payload = _as_dict(report)
        for endpoint in list(report_payload.get("endpoint_results") or []):
            if not isinstance(endpoint, dict):
                continue
            input_tokens += int(endpoint.get("input_tokens", 0) or 0)
            output_tokens += int(endpoint.get("output_tokens", 0) or 0)
    return max(input_tokens, 0), max(output_tokens, 0)


def _estimate_cost_rmb(*, input_tokens: int, output_tokens: int) -> float:
    settings = get_settings()
    input_rate = settings.responses_input_price_per_million_tokens_rmb / 1_000_000
    output_rate = settings.responses_output_price_per_million_tokens_rmb / 1_000_000
    return round(max(input_tokens, 0) * input_rate + max(output_tokens, 0) * output_rate, 6)


def _case_llm_text_audit_summary(case_id: str, artifact_dir: Path) -> dict[str, Any]:
    turn_records = _turn_llm_text_audit_records(artifact_dir)
    session_reports = _session_llm_text_audit_reports(artifact_dir)
    total_input_tokens, total_output_tokens = _llm_text_audit_usage_totals(turn_records, session_reports)
    return {
        "case_id": case_id,
        "artifacts_dir": str(artifact_dir),
        "session_reports": session_reports,
        "turn_flag_counts": _aggregate_llm_flags(turn_records),
        "avg_arc_coherence": _mean_session_llm_text_audit_score(session_reports, "arc_coherence"),
        "avg_payoff_strength": _mean_session_llm_text_audit_score(session_reports, "payoff_strength"),
        "avg_npc_presence": _mean_session_llm_text_audit_score(session_reports, "npc_presence"),
        "avg_style_consistency": _mean_session_llm_text_audit_score(session_reports, "style_consistency"),
        "avg_shell_distinctiveness": _mean_session_llm_text_audit_score(session_reports, "shell_distinctiveness"),
        "avg_memorable_moments": _mean_session_llm_text_audit_score(session_reports, "memorable_moments"),
        "avg_turn_tone_naturalness": _mean_turn_llm_text_audit_score(turn_records, "tone_naturalness"),
        "avg_turn_character_specificity": _mean_turn_llm_text_audit_score(turn_records, "character_specificity"),
        "avg_turn_dramatic_tension": _mean_turn_llm_text_audit_score(turn_records, "dramatic_tension"),
        "avg_turn_shell_fidelity": _mean_turn_llm_text_audit_score(turn_records, "shell_fidelity"),
        "avg_turn_consequence_clarity": _mean_turn_llm_text_audit_score(turn_records, "consequence_clarity"),
        "avg_turn_anti_template_stiffness": _mean_turn_llm_text_audit_score(turn_records, "anti_template_stiffness"),
        "top_llm_text_issues": _aggregate_llm_session_items(session_reports, "top_issues"),
        "top_llm_text_strengths": _aggregate_llm_session_items(session_reports, "top_strengths"),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "estimated_llm_text_audit_cost_rmb": _estimate_cost_rmb(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        ),
    }


def _build_report(
    *,
    case_catalog: list[UrbanGoldCase],
    benchmark_summary: dict[str, Any],
    selected_cases: list[dict[str, Any]],
    deep_play_summaries: list[dict[str, Any]],
    live_mode: str,
) -> str:
    smoke_results = _smoke_results(benchmark_summary, live_mode=live_mode)
    mode_summary = benchmark_summary["smoke"]["mode_summaries"][live_mode]
    shell_rows = _smoke_shell_summary(case_catalog, smoke_results)
    best_shell = shell_rows[0]["shell_id"] if shell_rows else "unknown"
    weakest_shell = shell_rows[-1]["shell_id"] if shell_rows else "unknown"
    lines = [
        "# 原生中文 Live Eval 总报告",
        "",
        f"## {len(case_catalog)}-case live smoke summary",
        "",
        f"- live 轨道：`{live_mode}`",
        f"- case 总数：`{mode_summary['total_cases']}`",
        f"- 通过数：`{mode_summary['passed_cases']}`",
        f"- pass rate：`{mode_summary['pass_rate']:.4f}`",
        f"- 平均内容分：`{mode_summary['avg_content_score']:.4f}`",
        f"- 平均结构分：`{mode_summary['avg_structure_score']:.4f}`",
        f"- 平均 live depth：`{mode_summary['avg_live_depth_score']:.4f}`",
        f"- 首轮最强 shell：`{best_shell}`",
        f"- 当前最弱 shell：`{weakest_shell}`",
        "",
        "按 shell 看首轮 live author 质量：",
    ]
    for row in shell_rows:
        lines.append(
            f"- `{row['shell_id']}`：pass_rate={row['pass_rate']:.4f}，"
            f"avg_content={row['avg_content_score']:.4f}，avg_live_depth={row['avg_live_depth_score']:.4f}"
        )
    lines.extend(
        [
            "",
            "主要 fallback / repair 聚集点：",
        ]
    )
    for key, value in dict(mode_summary.get("fallback_distribution") or {}).items():
        lines.append(f"- `{key}`：{value}")
    lines.extend(
        [
            "",
            "## top-3 deep play summary",
            "",
            f"- 实际入选 case 数：`{len(selected_cases)}`",
        ]
    )
    shortfall = DEFAULT_TOP_CASES - len(selected_cases)
    if shortfall > 0:
        lines.append(f"- shortfall：只拿到 `{len(selected_cases)}` 个 passing case，少了 `{shortfall}` 个。")
    for summary in deep_play_summaries:
        comparison = summary["comparison_summary"]
        lines.append(
            f"- `{summary['case_id']}`：distinct_playstyles=`{comparison.get('supports_distinct_playstyles')}`，"
            f"strategic_tension_curve={summary['avg_strategic_tension_curve']:.2f}，"
            f"payoff_realization={summary['avg_payoff_realization']:.2f}，"
            f"control_tradeoff_quality={summary['avg_control_tradeoff_quality']:.2f}"
        )
    lines.extend(["", "## play signal findings", ""])
    if deep_play_summaries:
        strongest_signal_case = max(
            deep_play_summaries,
            key=lambda item: (
                item["avg_consequence_legibility"],
                item["avg_turn_consequence_impact"],
                item["case_id"],
            ),
        )
        weakest_signal_case = min(
            deep_play_summaries,
            key=lambda item: (
                item["avg_consequence_legibility"],
                item["avg_turn_consequence_impact"],
                item["case_id"],
            ),
        )
        lines.append(
            f"- play 信号链最完整的是 `{strongest_signal_case['case_id']}`，"
            f"session consequence_legibility={strongest_signal_case['avg_consequence_legibility']:.2f}。"
        )
        lines.append(
            f"- play 信号链最弱的是 `{weakest_signal_case['case_id']}`，"
            f"session consequence_legibility={weakest_signal_case['avg_consequence_legibility']:.2f}。"
        )
    global_flag_counter: Counter[str] = Counter()
    for summary in deep_play_summaries:
        global_flag_counter.update(summary["turn_flag_counts"])
    if global_flag_counter:
        lines.append("- 最常见的 turn-level 机制警报：")
        for flag, count in global_flag_counter.most_common(5):
            lines.append(f"- `{flag}`：{count}")
    lines.extend(["", "## consequence and pressure findings", ""])
    for summary in deep_play_summaries:
        lines.append(
            f"- `{summary['case_id']}`：consequence_legibility={summary['avg_consequence_legibility']:.2f}，"
            f"turn pressure_exchange={summary['avg_turn_pressure_exchange']:.2f}"
        )
    lines.extend(["", "## payoff and control findings", ""])
    for summary in deep_play_summaries:
        lines.append(
            f"- `{summary['case_id']}`：payoff_realization={summary['avg_payoff_realization']:.2f}，"
            f"control_tradeoff_quality={summary['avg_control_tradeoff_quality']:.2f}"
        )
    lines.extend(["", "## NPC interest findings", ""])
    for summary in deep_play_summaries:
        lines.append(
            f"- `{summary['case_id']}`：npc_interest_divergence={summary['avg_npc_interest_divergence']:.2f}，"
            f"turn intent_binding={summary['avg_turn_intent_binding']:.2f}"
        )
    issue_counter: Counter[str] = Counter()
    for summary in deep_play_summaries:
        issue_counter.update(summary["top_play_eval_issues"])
        issue_counter.update(summary["turn_flag_counts"])
    strength_counter: Counter[str] = Counter()
    for summary in deep_play_summaries:
        strength_counter.update(summary["top_play_eval_strengths"])
    lines.extend(["", "## top 3 blocking issues before wider rollout", ""])
    if issue_counter:
        for issue, count in issue_counter.most_common(3):
            lines.append(f"- `{issue}`：{count}")
    else:
        lines.append("- 暂无明显共性阻塞项。")
    lines.extend(["", "附加亮点："])
    if strength_counter:
        for strength, count in strength_counter.most_common(3):
            lines.append(f"- `{strength}`：{count}")
    else:
        lines.append("- play_eval 侧暂未形成稳定亮点聚类。")
    return "\n".join(lines) + "\n"


def run_native_cn_live_eval(
    output_dir: Path,
    *,
    live_mode: str = LIVE_MODE,
    top_n: int = DEFAULT_TOP_CASES,
    select_id_probability: float = 0.1,
) -> dict[str, Any]:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    case_catalog = native_cn_gold_realistic_14()
    benchmark_dir = root / "benchmark"
    benchmark_summary = run_benchmark(
        benchmark_dir,
        mini_cases=case_catalog,
        modes=(live_mode,),  # type: ignore[arg-type]
        include_burst=False,
    )
    _write_json(root / "native_cn_gold_realistic_14_summary.json", benchmark_summary)
    smoke_results = _smoke_results(benchmark_summary, live_mode=live_mode)
    selected_cases = _select_top_cases(case_catalog=case_catalog, results=smoke_results, top_n=top_n)
    _write_json(
        root / "selected_cases.json",
        {
            "requested_top_n": top_n,
            "selected_count": len(selected_cases),
            "selected_cases": selected_cases,
        },
    )
    deep_play_root = root / "deep_play"
    deep_play_summaries: list[dict[str, Any]] = []
    for case in selected_cases:
        result = run_self_play_pilot(
            deep_play_root,
            case_id=case["case_id"],
            live_mode=live_mode,
            execution_mode=DEFAULT_EXECUTION_MODE,
            enable_turn_play_eval=True,
            enable_session_play_eval=True,
            select_id_probability=min(max(float(select_id_probability), 0.0), 1.0),
        )
        artifact_dir = Path(str(result["artifacts_dir"]))
        deep_play_summaries.append(_case_play_eval_summary(case["case_id"], artifact_dir))
    report = _build_report(
        case_catalog=case_catalog,
        benchmark_summary=benchmark_summary,
        selected_cases=selected_cases,
        deep_play_summaries=deep_play_summaries,
        live_mode=live_mode,
    )
    (root / "consolidated_report_zh.md").write_text(report)
    return {
        "artifacts_dir": str(root),
        "live_mode": live_mode,
        "benchmark_summary": benchmark_summary,
        "selected_cases": selected_cases,
        "deep_play_summaries": deep_play_summaries,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the realistic-14-case native-Chinese live eval with turn/session play eval.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_CASES)
    parser.add_argument(
        "--live-mode",
        default=LIVE_MODE,
        help=f"author live mode. legacy alias openai_prompted -> pure_gpt. supported: {', '.join(LIVE_BENCHMARK_MODES)}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _ = parse_args(argv)
    raise SystemExit(
        "native_cn_live_eval CLI 已下线。请改用: "
        "python -m tools.urban_author_play_benchmarks.gold_eval_mini_runner 或 "
        "python -m tools.urban_author_play_benchmarks.gold_eval_full_runner"
    )


if __name__ == "__main__":
    raise SystemExit(main())
