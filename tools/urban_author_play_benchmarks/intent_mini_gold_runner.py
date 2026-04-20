from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.config import get_settings
from rpg_backend.play_v2.runtime import (
    build_initial_world_state,
    build_suggested_actions,
    run_intent_stage,
)

DEFAULT_CASE_IDS: tuple[str, ...] = (
    "campus_topic_club_campaign_flip",
    "campus_topic_homecoming_recording",
    "entertainment_topic_awards_scandal",
    "entertainment_topic_livestream_hotsearch_flip",
    "office_topic_board_vote_blackledger",
    "office_topic_launch_contract_flip",
    "wealth_topic_banquet_will_flip",
    "wealth_topic_engagement_sideswitch",
)


@dataclass(frozen=True)
class IntentSample:
    sample_id: str
    input_text: str
    selected_suggestion_id: str | None = None
    expect_move_family: str | None = None
    expect_control_action: str | None = None
    expect_public_scene: bool = False
    expect_deviation: bool = False
    segment_role: str | None = None


def _timestamp_slug() -> str:
    return str(int(math.floor(os.times().elapsed)))


def _p90(values: list[float]) -> float:
    cleaned = sorted(float(item) for item in values if float(item) >= 0)
    if not cleaned:
        return 0.0
    idx = max(0, min(len(cleaned) - 1, math.ceil(0.9 * len(cleaned)) - 1))
    return round(cleaned[idx], 4)


def _median(values: list[float]) -> float:
    cleaned = [float(item) for item in values if float(item) >= 0]
    if not cleaned:
        return 0.0
    return round(float(median(cleaned)), 4)


def _find_compiled_plan_file(plans_root: Path, case_id: str) -> Path:
    direct = plans_root / case_id / "compiled_play_plan.json"
    if direct.exists():
        return direct
    smoke_matches = list((plans_root / "benchmark" / "smoke" / case_id).glob("*/compiled_play_plan.json"))
    if smoke_matches:
        return sorted(smoke_matches)[0]
    recursive = list(plans_root.glob(f"**/{case_id}/**/compiled_play_plan.json"))
    if recursive:
        return sorted(recursive)[0]
    raise FileNotFoundError(f"compiled_play_plan.json not found for case: {case_id} under {plans_root}")


def _load_plan(plan_path: Path) -> CompiledPlayPlan:
    payload = json.loads(plan_path.read_text())
    return CompiledPlayPlan.model_validate(payload)


def _build_samples(plan: CompiledPlayPlan) -> list[IntentSample]:
    state = build_initial_world_state(plan, session_id=f"intent_gold_seed_{plan.story_id}")
    suggestions = build_suggested_actions(plan, state)
    if not suggestions:
        return []
    first = suggestions[0]
    target_name = next((member.display_name for member in plan.cast if member.character_id == first.target_id), "她")
    redirect_target = next((member.display_name for member in plan.cast if member.character_id != first.target_id), target_name)
    return [
        IntentSample(
            sample_id="sugg_prompt",
            input_text=first.prompt,
            expect_move_family=first.move_family,
        ),
        IntentSample(
            sample_id="press_control",
            input_text="先把这颗雷压住，稳一拍再说。",
            expect_control_action="press",
        ),
        IntentSample(
            sample_id="redirect_control",
            input_text=f"先把这波锅转给{redirect_target}，让她先扛。",
            expect_control_action="redirect",
        ),
        IntentSample(
            sample_id="public_reveal",
            input_text=f"现在就当众把{target_name}手里的事说破。",
            expect_public_scene=True,
            segment_role="reveal",
        ),
        IntentSample(
            sample_id="scope_shift",
            input_text=f"先安抚{target_name}，再当众曝光，最后把风向转给{redirect_target}。",
            expect_deviation=True,
            segment_role="reveal",
        ),
    ]


def _state_for_segment(plan: CompiledPlayPlan, state, segment_role: str):
    segment = next((item for item in plan.segments if item.segment_role == segment_role), None)
    if segment is None:
        return state
    copied = state.model_copy(deep=True)
    copied.segment_index = plan.segments.index(segment)
    copied.segment_id = segment.segment_id
    copied.scene_frame = "public" if segment.segment_role in {"reveal", "terminal"} else (
        "semi_public" if segment.segment_role == "pressure" else "private"
    )
    copied.venue_id = segment.venue_id
    copied.active_character_ids = list((segment.focus_target_ids + segment.rival_target_ids)[:3])
    return copied


def _sample_checks(sample: IntentSample, intent, diagnostics: dict[str, Any]) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    if sample.expect_move_family is not None:
        checks["move_family_match"] = intent.move_family == sample.expect_move_family
    if sample.expect_control_action is not None:
        checks["control_action_match"] = intent.control_action == sample.expect_control_action
    if sample.expect_public_scene:
        checks["scene_public"] = intent.scene_frame == "public"
    if sample.expect_deviation:
        checks["deviation_present"] = bool(intent.deviation_note)
    checks["intent_stage_latency_recorded"] = float(diagnostics.get("intent_stage_latency_ms", 0.0)) > 0
    return checks


def run_intent_mini_gold(
    *,
    plans_root: Path,
    output_dir: Path,
    case_ids: list[str],
    enable_intent_llm: bool,
    enable_micro_sim_llm: bool,
) -> dict[str, Any]:
    previous_intent = os.environ.get("APP_PLAY_V2_INTENT_COMPILER_USE_LLM")
    previous_micro = os.environ.get("APP_PLAY_V2_MICRO_SIM_USE_LLM")
    os.environ["APP_PLAY_V2_INTENT_COMPILER_USE_LLM"] = "true" if enable_intent_llm else "false"
    os.environ["APP_PLAY_V2_MICRO_SIM_USE_LLM"] = "true" if enable_micro_sim_llm else "false"
    get_settings.cache_clear()
    try:
        case_rows: list[dict[str, Any]] = []
        all_stage_latency: list[float] = []
        all_parse_latency: list[float] = []
        all_micro_latency: list[float] = []
        all_tokens: list[float] = []
        all_parse_tokens: list[float] = []
        all_micro_tokens: list[float] = []
        total_checks = 0
        passed_checks = 0
        check_counter: Counter[str] = Counter()
        check_pass_counter: Counter[str] = Counter()
        intent_compile_source_counter: Counter[str] = Counter()
        control_source_counter: Counter[str] = Counter()
        intent_status_counter: Counter[str] = Counter()
        micro_status_counter: Counter[str] = Counter()

        for case_id in case_ids:
            plan_path = _find_compiled_plan_file(plans_root, case_id)
            plan = _load_plan(plan_path)
            samples = _build_samples(plan)
            base_state = build_initial_world_state(plan, session_id=f"intent_gold_{case_id}")
            sample_rows: list[dict[str, Any]] = []
            case_checks_total = 0
            case_checks_passed = 0
            for sample in samples:
                sample_state = _state_for_segment(plan, base_state, sample.segment_role) if sample.segment_role else base_state.model_copy(deep=True)
                intent, micro_sim, diagnostics = run_intent_stage(
                    plan,
                    sample_state,
                    sample.input_text,
                    selected_suggestion_id=sample.selected_suggestion_id,
                )
                checks = _sample_checks(sample, intent, diagnostics)
                check_total = len(checks)
                check_passed = sum(1 for ok in checks.values() if ok)
                for check_name, check_ok in checks.items():
                    check_counter[check_name] += 1
                    if check_ok:
                        check_pass_counter[check_name] += 1
                case_checks_total += check_total
                case_checks_passed += check_passed
                total_checks += check_total
                passed_checks += check_passed
                intent_compile_source_counter[str(diagnostics.get("intent_compile_source") or "unknown")] += 1
                control_source_counter[str(diagnostics.get("control_source") or "unknown")] += 1
                intent_status_counter[str(diagnostics.get("intent_llm_status") or "unknown")] += 1
                micro_status_counter[str(diagnostics.get("micro_sim_status") or "unknown")] += 1

                stage_latency = float(diagnostics.get("intent_stage_latency_ms", 0.0))
                parse_latency = float(diagnostics.get("intent_parse_latency_ms", 0.0))
                micro_latency = float(diagnostics.get("micro_sim_latency_ms", 0.0))
                stage_tokens = float(diagnostics.get("intent_stage_total_tokens", 0))
                parse_tokens = float(diagnostics.get("intent_llm_total_tokens", 0))
                micro_tokens = float(diagnostics.get("micro_sim_total_tokens", 0))
                all_stage_latency.append(stage_latency)
                all_parse_latency.append(parse_latency)
                all_micro_latency.append(micro_latency)
                all_tokens.append(stage_tokens)
                all_parse_tokens.append(parse_tokens)
                all_micro_tokens.append(micro_tokens)
                sample_rows.append(
                    {
                        "sample_id": sample.sample_id,
                        "input_text": sample.input_text,
                        "intent": intent.model_dump(mode="json"),
                        "micro_sim": None
                        if micro_sim is None
                        else {
                            "source": micro_sim.source,
                            "recommended_actor_id": micro_sim.recommended_actor_id,
                            "choices": [
                                {
                                    "character_id": choice.character_id,
                                    "reason_family": choice.reason_family,
                                    "confidence": choice.confidence,
                                }
                                for choice in micro_sim.choices
                            ],
                        },
                        "diagnostics": diagnostics,
                        "checks": checks,
                        "check_passed": check_passed,
                        "check_total": check_total,
                    }
                )
            case_rows.append(
                {
                    "case_id": case_id,
                    "plan_path": str(plan_path),
                    "check_passed": case_checks_passed,
                    "check_total": case_checks_total,
                    "check_pass_rate": round((case_checks_passed / case_checks_total) if case_checks_total else 0.0, 4),
                    "samples": sample_rows,
                }
            )

        summary = {
            "plans_root": str(plans_root),
            "case_count": len(case_rows),
            "sample_count": sum(len(row["samples"]) for row in case_rows),
            "check_pass_rate": round((passed_checks / total_checks) if total_checks else 0.0, 4),
            "check_scores": {
                key: round((check_pass_counter[key] / check_counter[key]) if check_counter[key] else 0.0, 4)
                for key in sorted(check_counter.keys())
            },
            "intent_compile_source_distribution": dict(intent_compile_source_counter),
            "control_source_distribution": dict(control_source_counter),
            "intent_llm_status_distribution": dict(intent_status_counter),
            "micro_sim_status_distribution": dict(micro_status_counter),
            "latency_ms": {
                "intent_stage_median": _median(all_stage_latency),
                "intent_stage_p90": _p90(all_stage_latency),
                "intent_parse_median": _median(all_parse_latency),
                "intent_parse_p90": _p90(all_parse_latency),
                "intent_micro_median": _median(all_micro_latency),
                "intent_micro_p90": _p90(all_micro_latency),
            },
            "tokens": {
                "intent_stage_total_sum": int(sum(all_tokens)),
                "intent_stage_total_median": _median(all_tokens),
                "intent_stage_total_p90": _p90(all_tokens),
                "intent_parse_total_sum": int(sum(all_parse_tokens)),
                "intent_parse_total_median": _median(all_parse_tokens),
                "intent_parse_total_p90": _p90(all_parse_tokens),
                "intent_micro_total_sum": int(sum(all_micro_tokens)),
                "intent_micro_total_median": _median(all_micro_tokens),
                "intent_micro_total_p90": _p90(all_micro_tokens),
            },
            "case_results": case_rows,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "intent_mini_gold_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        report = [
            "# Intent Mini Gold Report",
            "",
            f"- cases: `{summary['case_count']}`",
            f"- samples: `{summary['sample_count']}`",
            f"- check pass rate: `{summary['check_pass_rate']:.2%}`",
            "",
            "## Check Scores",
            *[
                f"- {name}: `{float(score):.2%}`"
                for name, score in sorted(dict(summary["check_scores"]).items())
            ],
            "",
            "## Latency (ms)",
            f"- intent_stage median/p90: `{summary['latency_ms']['intent_stage_median']}` / `{summary['latency_ms']['intent_stage_p90']}`",
            f"- intent_parse median/p90: `{summary['latency_ms']['intent_parse_median']}` / `{summary['latency_ms']['intent_parse_p90']}`",
            f"- intent_micro median/p90: `{summary['latency_ms']['intent_micro_median']}` / `{summary['latency_ms']['intent_micro_p90']}`",
            "",
            "## Tokens",
            f"- intent_stage sum / median / p90: `{summary['tokens']['intent_stage_total_sum']}` / `{summary['tokens']['intent_stage_total_median']}` / `{summary['tokens']['intent_stage_total_p90']}`",
            f"- intent_parse sum / median / p90: `{summary['tokens']['intent_parse_total_sum']}` / `{summary['tokens']['intent_parse_total_median']}` / `{summary['tokens']['intent_parse_total_p90']}`",
            f"- intent_micro sum / median / p90: `{summary['tokens']['intent_micro_total_sum']}` / `{summary['tokens']['intent_micro_total_median']}` / `{summary['tokens']['intent_micro_total_p90']}`",
            "",
            "## Status Distribution",
            f"- intent_compile_source: `{json.dumps(summary['intent_compile_source_distribution'], ensure_ascii=False)}`",
            f"- control_source: `{json.dumps(summary['control_source_distribution'], ensure_ascii=False)}`",
            f"- intent_llm_status: `{json.dumps(summary['intent_llm_status_distribution'], ensure_ascii=False)}`",
            f"- micro_sim_status: `{json.dumps(summary['micro_sim_status_distribution'], ensure_ascii=False)}`",
        ]
        (output_dir / "intent_mini_gold_report.md").write_text("\n".join(report))
        return summary
    finally:
        if previous_intent is None:
            os.environ.pop("APP_PLAY_V2_INTENT_COMPILER_USE_LLM", None)
        else:
            os.environ["APP_PLAY_V2_INTENT_COMPILER_USE_LLM"] = previous_intent
        if previous_micro is None:
            os.environ.pop("APP_PLAY_V2_MICRO_SIM_USE_LLM", None)
        else:
            os.environ["APP_PLAY_V2_MICRO_SIM_USE_LLM"] = previous_micro
        get_settings.cache_clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mini gold eval for play intent stage.")
    parser.add_argument("--plans-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(f"/tmp/intent_mini_gold_{_timestamp_slug()}"))
    parser.add_argument("--case-ids", type=str, nargs="*", default=list(DEFAULT_CASE_IDS))
    parser.add_argument("--enable-intent-llm", action="store_true")
    parser.add_argument("--enable-micro-sim-llm", action="store_true")
    args = parser.parse_args()
    summary = run_intent_mini_gold(
        plans_root=args.plans_root,
        output_dir=args.output_dir,
        case_ids=list(args.case_ids),
        enable_intent_llm=bool(args.enable_intent_llm),
        enable_micro_sim_llm=bool(args.enable_micro_sim_llm),
    )
    print(json.dumps(summary["latency_ms"], ensure_ascii=False, indent=2))
    print(json.dumps(summary["tokens"], ensure_ascii=False, indent=2))
    print(f"report: {args.output_dir / 'intent_mini_gold_report.md'}")


if __name__ == "__main__":
    main()
