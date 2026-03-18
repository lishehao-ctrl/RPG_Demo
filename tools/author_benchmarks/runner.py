from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.author_benchmarks.briefs import BRIEF_SUITES
from rpg_backend.author.contracts import AuthorBundleRequest
from rpg_backend.author.workflow import run_author_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "benchmarks"


@dataclass(frozen=True)
class RunnerConfig:
    briefs: list[str]
    suite: str | None
    runs: int
    rounds: int
    label: str | None
    baseline: Path | None
    output_dir: Path


def parse_args(argv: list[str] | None = None) -> RunnerConfig:
    parser = argparse.ArgumentParser(description="Run author pipeline benchmarks.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--suite", choices=sorted(BRIEF_SUITES))
    group.add_argument("--brief")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--label")
    parser.add_argument("--baseline")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.rounds < 1:
        parser.error("--rounds must be >= 1")
    if args.suite:
        briefs = BRIEF_SUITES[args.suite]
        suite = args.suite
    else:
        briefs = [args.brief]
        suite = None
    baseline = Path(args.baseline).expanduser().resolve() if args.baseline else None
    output_dir = Path(args.output_dir).expanduser().resolve()
    return RunnerConfig(
        briefs=briefs,
        suite=suite,
        runs=args.runs,
        rounds=args.rounds,
        label=args.label,
        baseline=baseline,
        output_dir=output_dir,
    )


def build_run_record(
    *,
    brief: str,
    round_index: int,
    run_in_round: int,
    run_index: int,
    duration_seconds: float,
    result: Any,
) -> dict[str, Any]:
    bundle = result.bundle
    trace = list(result.state.get("quality_trace") or [])
    llm_call_trace = list(result.state.get("llm_call_trace") or [])
    usage_totals: dict[str, int] = {}
    previous_response_calls = 0
    total_input_characters = 0
    for item in llm_call_trace:
        total_input_characters += int(item.get("input_characters") or 0)
        if item.get("used_previous_response_id"):
            previous_response_calls += 1
        for key, value in dict(item.get("usage") or {}).items():
            usage_totals[key] = usage_totals.get(key, 0) + int(value)
    return {
        "run": run_index,
        "round": round_index,
        "run_in_round": run_in_round,
        "brief": brief,
        "run_id": result.run_id,
        "duration_seconds": round(duration_seconds, 2),
        "title": bundle.story_bible.title,
        "premise": bundle.story_bible.premise,
        "story_frame_source": result.state.get("story_frame_source"),
        "story_frame_strategy": result.state.get("story_frame_strategy"),
        "beat_plan_source": result.state.get("beat_plan_source"),
        "route_affordance_source": result.state.get("route_affordance_source"),
        "ending_source": result.state.get("ending_source"),
        "cast_topology": result.state.get("cast_topology"),
        "cast_strategy": result.state.get("cast_strategy"),
        "primary_theme": result.state.get("primary_theme"),
        "theme_modifiers": list(result.state.get("theme_modifiers") or []),
        "beat_plan_strategy": result.state.get("beat_plan_strategy"),
        "cast_names": [item.name for item in bundle.story_bible.cast],
        "beat_count": len(bundle.beat_spine),
        "route_count": len(bundle.rule_pack.route_unlock_rules),
        "ending_ids": [item.ending_id for item in bundle.rule_pack.ending_rules],
        "quality_trace": trace,
        "llm_call_trace": llm_call_trace,
        "llm_call_count": len(llm_call_trace),
        "llm_input_characters": total_input_characters,
        "llm_previous_response_call_count": previous_response_calls,
        "llm_usage_totals": usage_totals,
    }


def _counter_to_dict(counter: Counter[tuple[str, str]]) -> dict[str, int]:
    return {f"{left}:{right}": count for (left, right), count in sorted(counter.items())}


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    source_distribution: Counter[tuple[str, str]] = Counter()
    outcome_distribution: Counter[tuple[str, str]] = Counter()
    reason_distribution: Counter[tuple[str, str]] = Counter()
    title_distribution = Counter()
    cast_topology_distribution = Counter()
    theme_distribution = Counter()
    beat_plan_strategy_distribution = Counter()
    beat_count_distribution = Counter()
    route_count_distribution = Counter()
    llm_call_counts: list[int] = []
    llm_input_characters: list[int] = []
    llm_previous_response_call_counts: list[int] = []
    llm_usage_totals: dict[str, int] = {}
    durations: list[float] = []
    trace_total = 0
    default_fallback = 0
    generated_accept = 0

    for result in results:
        title_distribution[result["title"]] += 1
        cast_topology_distribution[result.get("cast_topology") or "unknown"] += 1
        theme_distribution[result.get("primary_theme") or "unknown"] += 1
        beat_plan_strategy_distribution[result.get("beat_plan_strategy") or "unknown"] += 1
        beat_count_distribution[str(result["beat_count"])] += 1
        route_count_distribution[str(result["route_count"])] += 1
        llm_call_counts.append(int(result.get("llm_call_count") or 0))
        llm_input_characters.append(int(result.get("llm_input_characters") or 0))
        llm_previous_response_call_counts.append(int(result.get("llm_previous_response_call_count") or 0))
        for key, value in dict(result.get("llm_usage_totals") or {}).items():
            llm_usage_totals[key] = llm_usage_totals.get(key, 0) + int(value)
        durations.append(float(result["duration_seconds"]))
        for item in result.get("quality_trace") or []:
            trace_total += 1
            source_distribution[(item["stage"], item["source"])] += 1
            outcome_distribution[(item["stage"], item["outcome"])] += 1
            if item["source"] == "default" and item["outcome"] == "fallback":
                default_fallback += 1
            if item["source"] == "generated" and item["outcome"] == "accepted":
                generated_accept += 1
            for reason in item.get("reasons") or []:
                reason_distribution[(item["stage"], reason)] += 1

    duration_summary = {
        "min_seconds": round(min(durations), 2) if durations else 0.0,
        "max_seconds": round(max(durations), 2) if durations else 0.0,
        "avg_seconds": round(statistics.mean(durations), 2) if durations else 0.0,
        "median_seconds": round(statistics.median(durations), 2) if durations else 0.0,
    }
    default_fallback_rate = round(default_fallback / trace_total, 4) if trace_total else 0.0
    generated_accept_rate = round(generated_accept / trace_total, 4) if trace_total else 0.0
    return {
        "source_distribution": _counter_to_dict(source_distribution),
        "outcome_distribution": _counter_to_dict(outcome_distribution),
        "reason_distribution": _counter_to_dict(reason_distribution),
        "title_distribution": dict(sorted(title_distribution.items())),
        "cast_topology_distribution": dict(sorted(cast_topology_distribution.items())),
        "theme_distribution": dict(sorted(theme_distribution.items())),
        "beat_plan_strategy_distribution": dict(sorted(beat_plan_strategy_distribution.items())),
        "beat_count_distribution": dict(sorted(beat_count_distribution.items())),
        "route_count_distribution": dict(sorted(route_count_distribution.items())),
        "duration_summary": duration_summary,
        "llm_summary": {
            "total_call_count": sum(llm_call_counts),
            "avg_call_count": round(statistics.mean(llm_call_counts), 2) if llm_call_counts else 0.0,
            "median_call_count": round(statistics.median(llm_call_counts), 2) if llm_call_counts else 0.0,
            "total_input_characters": sum(llm_input_characters),
            "avg_input_characters": round(statistics.mean(llm_input_characters), 2) if llm_input_characters else 0.0,
            "median_input_characters": round(statistics.median(llm_input_characters), 2) if llm_input_characters else 0.0,
            "total_previous_response_calls": sum(llm_previous_response_call_counts),
            "avg_previous_response_calls": round(statistics.mean(llm_previous_response_call_counts), 2) if llm_previous_response_call_counts else 0.0,
            "usage_totals": llm_usage_totals,
        },
        "default_fallback_rate": default_fallback_rate,
        "generated_accept_rate": generated_accept_rate,
    }


def summarize_rounds(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rounds: dict[int, list[dict[str, Any]]] = {}
    for item in results:
        rounds.setdefault(int(item["round"]), []).append(item)
    round_summaries: list[dict[str, Any]] = []
    default_fallback_rates: list[float] = []
    generated_accept_rates: list[float] = []
    avg_durations: list[float] = []
    median_durations: list[float] = []
    for round_index in sorted(rounds):
        summary = summarize_results(rounds[round_index])
        round_summary = {
            "round": round_index,
            "run_count": len(rounds[round_index]),
            "default_fallback_rate": summary["default_fallback_rate"],
            "generated_accept_rate": summary["generated_accept_rate"],
            "duration_summary": summary["duration_summary"],
            "llm_summary": summary["llm_summary"],
            "source_distribution": summary["source_distribution"],
            "reason_distribution": summary["reason_distribution"],
        }
        round_summaries.append(round_summary)
        default_fallback_rates.append(summary["default_fallback_rate"])
        generated_accept_rates.append(summary["generated_accept_rate"])
        avg_durations.append(summary["duration_summary"]["avg_seconds"])
        median_durations.append(summary["duration_summary"]["median_seconds"])
    trend_summary = {
        "default_fallback_rate_by_round": default_fallback_rates,
        "generated_accept_rate_by_round": generated_accept_rates,
        "avg_duration_by_round": avg_durations,
        "median_duration_by_round": median_durations,
        "default_fallback_rate_mean": round(statistics.mean(default_fallback_rates), 4) if default_fallback_rates else 0.0,
        "default_fallback_rate_median": round(statistics.median(default_fallback_rates), 4) if default_fallback_rates else 0.0,
        "generated_accept_rate_mean": round(statistics.mean(generated_accept_rates), 4) if generated_accept_rates else 0.0,
        "generated_accept_rate_median": round(statistics.median(generated_accept_rates), 4) if generated_accept_rates else 0.0,
        "avg_duration_mean": round(statistics.mean(avg_durations), 2) if avg_durations else 0.0,
        "avg_duration_median": round(statistics.median(avg_durations), 2) if avg_durations else 0.0,
        "median_duration_mean": round(statistics.mean(median_durations), 2) if median_durations else 0.0,
        "median_duration_median": round(statistics.median(median_durations), 2) if median_durations else 0.0,
    }
    return round_summaries, trend_summary


def load_baseline_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def build_artifact_basename(config: RunnerConfig, timestamp: str) -> str:
    if config.baseline:
        label = config.label or "candidate"
        return f"abtest-{label}-{timestamp}"
    if config.rounds > 1 and config.label:
        return f"author_pipeline_{config.runs}runs_{config.rounds}rounds_{config.label}_{timestamp}"
    if config.rounds > 1:
        return f"author_pipeline_{config.runs}runs_{config.rounds}rounds_{timestamp}"
    if config.label:
        return f"author_pipeline_{config.runs}runs_{config.label}_{timestamp}"
    return f"author_pipeline_{config.runs}runs_{timestamp}"


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Author Pipeline Benchmark",
        "",
        f"- Captured at: {summary['captured_at']}",
        f"- Runs per brief: {summary['runs_per_brief']}",
        f"- Rounds: {summary['rounds']}",
        f"- Suite: {summary['suite'] or 'custom'}",
        "",
        "## Source Distribution",
        "```json",
        json.dumps(summary["source_distribution"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Outcome Distribution",
        "```json",
        json.dumps(summary["outcome_distribution"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Top Reasons",
        "```json",
        json.dumps(summary["reason_distribution"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Derived Metrics",
        "```json",
        json.dumps(
            {
                "default_fallback_rate": summary["default_fallback_rate"],
                "generated_accept_rate": summary["generated_accept_rate"],
                "duration_summary": summary["duration_summary"],
                "cast_topology_distribution": summary["cast_topology_distribution"],
                "theme_distribution": summary["theme_distribution"],
                "beat_plan_strategy_distribution": summary["beat_plan_strategy_distribution"],
                "beat_count_distribution": summary["beat_count_distribution"],
                "route_count_distribution": summary["route_count_distribution"],
                "llm_summary": summary["llm_summary"],
                "round_trend_summary": summary["round_trend_summary"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## Round Summary",
        "```json",
        json.dumps(summary["round_summaries"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Run Summary",
        "| Run | Title | Theme | Story Strategy | Cast Strategy | Beat Strategy | Story | Beats | Ending | Cast | Duration |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in summary["results"]:
        lines.append(
            f"| {item['run']} | {item['title']} | {item.get('primary_theme') or 'unknown'} | {item.get('story_frame_strategy') or 'unknown'} | {item.get('cast_strategy') or 'unknown'} | {item.get('beat_plan_strategy') or 'unknown'} | {item['story_frame_source']} | {item['beat_plan_source']} | {item['ending_source']} | {item.get('cast_topology') or 'unknown'} | {item['duration_seconds']}s |"
        )
    if summary.get("baseline_artifact"):
        lines.extend(
            [
                "",
                "## Baseline",
                f"- Baseline artifact: {summary['baseline_artifact']}",
                "```json",
                json.dumps(summary["baseline_summary"], ensure_ascii=False, indent=2),
                "```",
                "",
                "## Candidate",
                "```json",
                json.dumps(summary["candidate_summary"], ensure_ascii=False, indent=2),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def run_benchmark(config: RunnerConfig) -> tuple[dict[str, Any], str]:
    captured_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    run_index = 0
    for round_index in range(1, config.rounds + 1):
        for brief in config.briefs:
            for run_in_round in range(1, config.runs + 1):
                run_index += 1
                started = time.time()
                result = run_author_bundle(AuthorBundleRequest(raw_brief=brief))
                results.append(
                    build_run_record(
                        brief=brief,
                        round_index=round_index,
                        run_in_round=run_in_round,
                        run_index=run_index,
                        duration_seconds=time.time() - started,
                        result=result,
                    )
                )
    metrics = summarize_results(results)
    round_summaries, round_trend_summary = summarize_rounds(results)
    summary: dict[str, Any] = {
        "captured_at": captured_at,
        "label": config.label,
        "suite": config.suite,
        "briefs": config.briefs,
        "runs_per_brief": config.runs,
        "rounds": config.rounds,
        **metrics,
        "round_summaries": round_summaries,
        "round_trend_summary": round_trend_summary,
        "results": results,
    }
    if config.baseline:
        baseline_summary = load_baseline_summary(config.baseline)
        summary["baseline_artifact"] = str(config.baseline)
        summary["baseline_summary"] = {
            "source_distribution": baseline_summary.get("source_distribution", {}),
            "outcome_distribution": baseline_summary.get("outcome_distribution", {}),
            "reason_distribution": baseline_summary.get("reason_distribution", {}),
            "default_fallback_rate": baseline_summary.get("default_fallback_rate", 0.0),
            "generated_accept_rate": baseline_summary.get("generated_accept_rate", 0.0),
            "duration_summary": baseline_summary.get("duration_summary", {}),
            "round_trend_summary": baseline_summary.get("round_trend_summary", {}),
        }
        summary["candidate_summary"] = {
            "source_distribution": summary["source_distribution"],
            "outcome_distribution": summary["outcome_distribution"],
            "reason_distribution": summary["reason_distribution"],
            "default_fallback_rate": summary["default_fallback_rate"],
            "generated_accept_rate": summary["generated_accept_rate"],
            "duration_summary": summary["duration_summary"],
            "round_trend_summary": summary["round_trend_summary"],
        }
    markdown = render_markdown(summary)
    return summary, markdown


def write_artifacts(config: RunnerConfig, summary: dict[str, Any], markdown: str) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = build_artifact_basename(config, timestamp)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = config.output_dir / f"{basename}.json"
    md_path = config.output_dir / f"{basename}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    md_path.write_text(markdown)
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    summary, markdown = run_benchmark(config)
    json_path, md_path = write_artifacts(config, summary, markdown)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
