#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import re
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rpg_backend.config.settings import get_settings
from rpg_backend.eval.story_quality_judge import StoryQualityJudge, StoryQualityJudgeError
from rpg_backend.generator.prompt_compiler import PromptCompileError, PromptCompiler
from rpg_backend.generator.errors import GeneratorBuildError
from rpg_backend.generator.pipeline import GeneratorPipeline
from rpg_backend.generator.versioning import compute_transcript_digest

try:
    from scripts.simulate_playthrough import DEFAULT_STRATEGIES, simulate_pack_playthrough
except ModuleNotFoundError:
    from simulate_playthrough import DEFAULT_STRATEGIES, simulate_pack_playthrough

EVAL_VERSION = "llm_story_generation_eval.v1"
GLOBAL_EVAL_SEED = "llm_story_eval_seed_v1"
DEFAULT_SUITE_FILE = "eval_data/prompt_suite_v1.json"
DEFAULT_FUN_FOCUS_SUITE_FILE = "eval_data/prompt_suite_fun_v1.json"
DEFAULT_OUTPUT = "reports/llm_story_generation_eval.json"
DEFAULT_PACKS_DIR = "reports/packs_llm"
DEFAULT_ARTIFACTS_DIR = "reports/llm_story_eval_artifacts"
DEFAULT_STRATEGY_SET = ("mixed", "text_noise", "button_random")
DEFAULT_FUN_FOCUS_STRATEGY_SET = ("mixed",)
PROMPT_SPEC_TRACKED_FIELDS = ("premise", "stakes", "tone", "title")
FUN_SCORE_WEIGHTS: dict[str, float] = {
    "overall": 0.40,
    "playability": 0.25,
    "choice_impact": 0.25,
    "tension_curve": 0.10,
}
FUN_FOCUS_THRESHOLD_HINTS: dict[str, float] = {
    "fun_score_avg_min": 7.5,
    "fun_score_case_min": 6.5,
}

FULL_GATE_THRESHOLDS: dict[str, float] = {
    "generation_success_rate_required": 1.0,
    "pack_lint_success_rate_required": 1.0,
    "completion_rate_required": 1.0,
    "avg_steps_min": 14.0,
    "avg_steps_max": 16.0,
    "meaningful_accept_rate_min": 0.90,
    "llm_route_success_rate_min": 0.80,
    "step_error_rate_required": 0.0,
    "judge_overall_avg_min": 7.5,
    "judge_prompt_fidelity_avg_min": 7.0,
    "case_overall_score_min": 6.0,
}


class PromptSuiteCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    prompt_text: str = Field(min_length=1)
    target_minutes: int = Field(default=10, ge=8, le=12)
    npc_count: int = Field(default=4, ge=3, le=5)
    style: str | None = None
    tags: list[str] = Field(default_factory=list)
    expected_tone: str | None = None


class PromptSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: list[PromptSuiteCase] = Field(min_length=1)


PromptSuiteCase.model_rebuild()
PromptSuite.model_rebuild()


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {value}")


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _to_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _compute_fun_score(judge_result_dict: dict[str, Any]) -> float:
    overall = _to_score(judge_result_dict.get("overall_score"))
    playability = _to_score(judge_result_dict.get("playability_score"))
    choice_impact = _to_score(judge_result_dict.get("choice_impact_score"))
    tension_curve = _to_score(judge_result_dict.get("tension_curve_score"))
    return (
        FUN_SCORE_WEIGHTS["overall"] * overall
        + FUN_SCORE_WEIGHTS["playability"] * playability
        + FUN_SCORE_WEIGHTS["choice_impact"] * choice_impact
        + FUN_SCORE_WEIGHTS["tension_curve"] * tension_curve
    )


def _aggregate_fun_metrics(judge_results: list[dict[str, Any]]) -> dict[str, float]:
    if not judge_results:
        return {
            "fun_score_avg": 0.0,
            "judge_playability_avg": 0.0,
            "judge_choice_impact_avg": 0.0,
            "judge_tension_curve_avg": 0.0,
        }

    fun_scores = [_compute_fun_score(result) for result in judge_results]
    playability_scores = [_to_score(result.get("playability_score")) for result in judge_results]
    choice_impact_scores = [_to_score(result.get("choice_impact_score")) for result in judge_results]
    tension_curve_scores = [_to_score(result.get("tension_curve_score")) for result in judge_results]
    return {
        "fun_score_avg": _safe_mean(fun_scores),
        "judge_playability_avg": _safe_mean(playability_scores),
        "judge_choice_impact_avg": _safe_mean(choice_impact_scores),
        "judge_tension_curve_avg": _safe_mean(tension_curve_scores),
    }


def _build_fun_focus_report(metrics: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    fun_score_avg = _to_score(metrics.get("fun_score_avg"))
    fun_score_case_min = _to_score(metrics.get("fun_score_case_min"))
    global_help_route_rate = _to_score(metrics.get("global_help_route_rate"))
    non_global_text_route_rate = _to_score(metrics.get("non_global_text_route_rate"))
    if fun_score_avg < FUN_FOCUS_THRESHOLD_HINTS["fun_score_avg_min"]:
        warnings.append(
            f"fun_score_avg={fun_score_avg:.4f} < hint {FUN_FOCUS_THRESHOLD_HINTS['fun_score_avg_min']:.4f}"
        )
    if fun_score_case_min < FUN_FOCUS_THRESHOLD_HINTS["fun_score_case_min"]:
        warnings.append(
            f"fun_score_case_min={fun_score_case_min:.4f} < hint {FUN_FOCUS_THRESHOLD_HINTS['fun_score_case_min']:.4f}"
        )
    if global_help_route_rate > 0.25:
        warnings.append(f"global_help_route_rate={global_help_route_rate:.4f} > diagnostic target 0.2500")
    if non_global_text_route_rate < 0.55:
        warnings.append(f"non_global_text_route_rate={non_global_text_route_rate:.4f} < diagnostic target 0.5500")
    return {
        "formula": {
            "expression": "0.40*overall + 0.25*playability + 0.25*choice_impact + 0.10*tension_curve",
            "weights": dict(FUN_SCORE_WEIGHTS),
        },
        "threshold_hints": {
            "fun_score_avg_min": FUN_FOCUS_THRESHOLD_HINTS["fun_score_avg_min"],
            "fun_score_case_min": FUN_FOCUS_THRESHOLD_HINTS["fun_score_case_min"],
            "diagnostic_only": True,
        },
        "warnings": warnings,
    }


def _resolve_profile_config(
    *,
    profile: str,
    suite_file: str | None,
    runs_per_prompt: int | None,
    strategies: str | None,
    max_steps: int | None,
    strict: bool | None,
) -> dict[str, Any]:
    if profile == "fun_focus":
        defaults = {
            "suite_file": DEFAULT_FUN_FOCUS_SUITE_FILE,
            "runs_per_prompt": 2,
            "strategies": ",".join(DEFAULT_FUN_FOCUS_STRATEGY_SET),
            "max_steps": 20,
            "strict": True,
        }
    else:
        defaults = {
            "suite_file": DEFAULT_SUITE_FILE,
            "runs_per_prompt": 3,
            "strategies": ",".join(DEFAULT_STRATEGY_SET),
            "max_steps": 20,
            "strict": True,
        }

    return {
        "suite_file": suite_file if suite_file is not None else defaults["suite_file"],
        "runs_per_prompt": runs_per_prompt if runs_per_prompt is not None else defaults["runs_per_prompt"],
        "strategies": strategies if strategies is not None else defaults["strategies"],
        "max_steps": max_steps if max_steps is not None else defaults["max_steps"],
        "strict": strict if strict is not None else defaults["strict"],
    }


def _unwrap_exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _classify_precheck_error(exc: BaseException) -> str:
    chain = _unwrap_exception_chain(exc)
    for item in chain:
        if isinstance(item, socket.gaierror):
            return "dns_unreachable"
        if isinstance(item, httpx.ConnectError):
            return "connect_error"
        if isinstance(item, httpx.HTTPStatusError):
            status = item.response.status_code
            if status in {401, 403}:
                return "auth_error"
            if 400 <= status < 500:
                return "http_4xx"
            if status >= 500:
                return "http_5xx"
            return f"http_{status}"

    for item in chain:
        if isinstance(item, PromptCompileError):
            return item.error_code or "prompt_compile_failed"
        if isinstance(item, StoryQualityJudgeError):
            return item.error_type or "judge_failed"
        if isinstance(item, ValidationError):
            return "prompt_spec_invalid"
        if isinstance(item, ValueError):
            lowered = str(item).lower()
            if "missing" in lowered or "invalid" in lowered:
                return "misconfigured"
    return "unknown_error"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


_PACK_WRITE_LOCK = threading.Lock()


def _write_json_if_missing(path: Path, payload: dict[str, Any]) -> None:
    with _PACK_WRITE_LOCK:
        if not path.exists():
            _write_json(path, payload)


def _load_prompt_suite(path: Path) -> PromptSuite:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PromptSuite.model_validate(payload)


def _derive_case_seed(case_id: str) -> str:
    material = f"{case_id}{GLOBAL_EVAL_SEED}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _derive_strategy_seed(*, pack_hash: str, case_id: str, run_index: int, strategy: str) -> int:
    material = f"{pack_hash}|{case_id}|run{run_index}|{strategy}"
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16)


def _extract_prompt_spec_invalid_field_counts(errors: list[str]) -> dict[str, int]:
    counts = {field: 0 for field in PROMPT_SPEC_TRACKED_FIELDS}
    if not errors:
        return {}
    text = "\n".join(errors).lower()
    for field in PROMPT_SPEC_TRACKED_FIELDS:
        pattern = rf"\b{re.escape(field)}\b"
        hits = len(re.findall(pattern, text))
        if hits > 0:
            counts[field] = hits
    return {field: count for field, count in counts.items() if count > 0}


def _aggregate_playthrough_metrics(reports: list[dict[str, Any]]) -> dict[str, float]:
    if not reports:
        return {
            "completion_rate": 0.0,
            "avg_steps": 0.0,
            "meaningful_accept_rate": 0.0,
            "llm_route_success_rate": 0.0,
            "global_help_route_rate": 0.0,
            "non_global_text_route_rate": 0.0,
            "pressure_recoil_trigger_rate": 0.0,
            "npc_stance_mentions_per_run_avg": 0.0,
            "step_error_rate": 0.0,
        }

    completion_count = sum(1 for report in reports if report.get("ended"))
    completed_steps = [int(report.get("steps", 0)) for report in reports if report.get("ended")]
    total_steps = sum(int(report.get("steps", 0)) for report in reports)
    meaningful_steps = sum(int(report.get("meaningful_steps", 0)) for report in reports)
    text_input_steps = sum(int(report.get("text_input_steps", 0)) for report in reports)
    llm_route_steps = sum(int(report.get("llm_route_steps", 0)) for report in reports)
    global_help_route_steps = sum(int(report.get("global_help_route_steps", 0)) for report in reports)
    pressure_recoil_steps = sum(int(report.get("pressure_recoil_steps", 0)) for report in reports)
    npc_stance_mentions = sum(int(report.get("npc_stance_mentions", 0)) for report in reports)
    runtime_error_steps = sum(int(report.get("runtime_error_steps", 0)) for report in reports)

    non_global_text_routes = max(llm_route_steps - global_help_route_steps, 0)

    return {
        "completion_rate": completion_count / len(reports),
        "avg_steps": _safe_mean(completed_steps),
        "meaningful_accept_rate": meaningful_steps / total_steps if total_steps else 0.0,
        "llm_route_success_rate": llm_route_steps / text_input_steps if text_input_steps else 0.0,
        "global_help_route_rate": global_help_route_steps / text_input_steps if text_input_steps else 0.0,
        "non_global_text_route_rate": non_global_text_routes / text_input_steps if text_input_steps else 0.0,
        "pressure_recoil_trigger_rate": pressure_recoil_steps / len(reports),
        "npc_stance_mentions_per_run_avg": npc_stance_mentions / len(reports),
        "step_error_rate": runtime_error_steps / len(reports),
    }


def _count_duplicate_beat_titles(pack_json: dict[str, Any]) -> int:
    beats = pack_json.get("beats", [])
    titles = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        title = beat.get("title")
        if isinstance(title, str):
            titles.append(title.strip().casefold())
    return 1 if len(set(titles)) != len(titles) else 0


def _count_banned_moves(pack_json: dict[str, Any]) -> int:
    count = 0
    for move in pack_json.get("moves", []):
        if isinstance(move, dict) and move.get("id") == "inspect_relic":
            count += 1
    return count


def _strategy_triangle_coverage_rate(pack_json: dict[str, Any]) -> float:
    moves = pack_json.get("moves", [])
    scenes = pack_json.get("scenes", [])
    if not isinstance(moves, list) or not isinstance(scenes, list) or not scenes:
        return 0.0
    move_style_map: dict[str, str] = {}
    for move in moves:
        if not isinstance(move, dict):
            continue
        move_id = move.get("id")
        strategy_style = move.get("strategy_style")
        if isinstance(move_id, str) and isinstance(strategy_style, str):
            move_style_map[move_id] = strategy_style

    required_styles = {"fast_dirty", "steady_slow", "political_safe_resource_heavy"}
    covered = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        enabled = scene.get("enabled_moves", [])
        if not isinstance(enabled, list):
            continue
        styles = {
            move_style_map.get(move_id)
            for move_id in enabled
            if isinstance(move_id, str) and not move_id.startswith("global.")
        }
        if required_styles.issubset(styles):
            covered += 1
    return covered / len(scenes)


def _build_pack_summary(pack_json: dict[str, Any]) -> dict[str, Any]:
    scenes = pack_json.get("scenes", [])
    moves = pack_json.get("moves", [])
    beats = pack_json.get("beats", [])
    enabled_move_total = sum(len(scene.get("enabled_moves", [])) for scene in scenes if isinstance(scene, dict))
    outcome_distribution = {"success": 0, "partial": 0, "fail_forward": 0}
    palette_distribution: dict[str, int] = {}
    move_ids: list[str] = []
    for move in moves:
        if not isinstance(move, dict):
            continue
        move_id = move.get("id", "")
        if isinstance(move_id, str):
            move_ids.append(move_id)
        for outcome in move.get("outcomes", []):
            if not isinstance(outcome, dict):
                continue
            result = outcome.get("result")
            if result in outcome_distribution:
                outcome_distribution[result] += 1
            outcome_id = outcome.get("id", "")
            if isinstance(outcome_id, str):
                parts = outcome_id.split(".")
                if len(parts) >= 3:
                    palette_id = parts[-1]
                    palette_distribution[palette_id] = palette_distribution.get(palette_id, 0) + 1

    beat_titles = []
    for beat in beats:
        if isinstance(beat, dict) and isinstance(beat.get("title"), str):
            beat_titles.append(beat["title"])

    return {
        "story_id": pack_json.get("story_id"),
        "title": pack_json.get("title"),
        "description": pack_json.get("description"),
        "npc_count": len(pack_json.get("npcs", [])),
        "npcs": pack_json.get("npcs", []),
        "beat_count": len(beats),
        "beat_titles": beat_titles,
        "scene_count": len(scenes),
        "move_count": len(moves),
        "enabled_moves_avg": enabled_move_total / len(scenes) if scenes else 0.0,
        "move_ids_sample": move_ids[:12],
        "outcome_distribution": outcome_distribution,
        "palette_distribution": palette_distribution,
    }


def _summarize_transcript(report: dict[str, Any]) -> dict[str, Any]:
    transcript = report.get("transcript", [])
    highlights: list[dict[str, Any]] = []
    if transcript:
        indexes = sorted({0, len(transcript) // 2, len(transcript) - 1})
        for idx in indexes:
            entry = transcript[idx]
            action_input = entry.get("action_input", {}) if isinstance(entry, dict) else {}
            recognized = entry.get("recognized", {}) if isinstance(entry, dict) else {}
            resolution = entry.get("resolution", {}) if isinstance(entry, dict) else {}
            highlights.append(
                {
                    "step": entry.get("step"),
                    "scene_id": entry.get("scene_id"),
                    "input_type": action_input.get("type"),
                    "route_source": entry.get("route_source"),
                    "recognized_move_id": recognized.get("move_id"),
                    "resolution_result": resolution.get("result"),
                    "meaningful_change": entry.get("meaningful_change"),
                }
            )

    return {
        "strategy": report.get("strategy"),
        "provider": report.get("provider"),
        "ended": bool(report.get("ended")),
        "steps": int(report.get("steps", 0)),
        "meaningful_steps": int(report.get("meaningful_steps", 0)),
        "text_input_steps": int(report.get("text_input_steps", 0)),
        "llm_route_steps": int(report.get("llm_route_steps", 0)),
        "runtime_error": bool(report.get("runtime_error", False)),
        "runtime_error_code": report.get("runtime_error_code"),
        "runtime_error_stage": report.get("runtime_error_stage"),
        "highlights": highlights,
    }


def _run_precheck() -> dict[str, Any]:
    settings = get_settings()
    gateway_mode = "worker"
    base_url = (getattr(settings, "llm_worker_base_url", None) or "").strip()
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        return {
            "status": "failed",
            "error_type": "misconfigured",
            "error": "APP_LLM_WORKER_BASE_URL is missing or invalid",
            "base_url": base_url,
            "host": host,
            "gateway_mode": gateway_mode,
        }

    try:
        socket.getaddrinfo(host, parsed.port or 443)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error_type": _classify_precheck_error(exc),
            "error": str(exc),
            "base_url": base_url,
            "host": host,
            "gateway_mode": gateway_mode,
        }

    try:
        compiled = asyncio.run(
            PromptCompiler().compile(
                prompt_text="Precheck story prompt: produce a compact but playable city emergency setup.",
                target_minutes=10,
                npc_count=4,
                style="neutral",
                attempt_index=0,
                attempt_seed="precheck",
            )
        )
        return {
            "status": "ok",
            "error_type": None,
            "error": None,
            "base_url": base_url,
            "host": host,
            "gateway_mode": gateway_mode,
            "compiler_model": compiled.model,
            "compiler_attempts": compiled.attempts,
            "spec_hash": compiled.spec_hash,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error_type": _classify_precheck_error(exc),
            "error": str(exc),
            "base_url": base_url,
            "host": host,
            "gateway_mode": gateway_mode,
        }


def _compute_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    fail_reasons: list[str] = []
    if metrics["generation_success_rate"] != FULL_GATE_THRESHOLDS["generation_success_rate_required"]:
        fail_reasons.append(
            f"generation_success_rate={metrics['generation_success_rate']:.4f} "
            f"< required {FULL_GATE_THRESHOLDS['generation_success_rate_required']:.4f}"
        )
    if metrics["pack_lint_success_rate"] != FULL_GATE_THRESHOLDS["pack_lint_success_rate_required"]:
        fail_reasons.append(
            f"pack_lint_success_rate={metrics['pack_lint_success_rate']:.4f} "
            f"< required {FULL_GATE_THRESHOLDS['pack_lint_success_rate_required']:.4f}"
        )
    if metrics["completion_rate"] != FULL_GATE_THRESHOLDS["completion_rate_required"]:
        fail_reasons.append(
            f"completion_rate={metrics['completion_rate']:.4f} "
            f"< required {FULL_GATE_THRESHOLDS['completion_rate_required']:.4f}"
        )
    if not (FULL_GATE_THRESHOLDS["avg_steps_min"] <= metrics["avg_steps"] <= FULL_GATE_THRESHOLDS["avg_steps_max"]):
        fail_reasons.append(
            f"avg_steps={metrics['avg_steps']:.4f} outside "
            f"[{FULL_GATE_THRESHOLDS['avg_steps_min']:.1f}, {FULL_GATE_THRESHOLDS['avg_steps_max']:.1f}]"
        )
    if metrics["meaningful_accept_rate"] < FULL_GATE_THRESHOLDS["meaningful_accept_rate_min"]:
        fail_reasons.append(
            f"meaningful_accept_rate={metrics['meaningful_accept_rate']:.4f} "
            f"< {FULL_GATE_THRESHOLDS['meaningful_accept_rate_min']:.4f}"
        )
    if metrics["llm_route_success_rate"] < FULL_GATE_THRESHOLDS["llm_route_success_rate_min"]:
        fail_reasons.append(
            f"llm_route_success_rate={metrics['llm_route_success_rate']:.4f} "
            f"< {FULL_GATE_THRESHOLDS['llm_route_success_rate_min']:.4f}"
        )
    if metrics["step_error_rate"] != FULL_GATE_THRESHOLDS["step_error_rate_required"]:
        fail_reasons.append(
            f"step_error_rate={metrics['step_error_rate']:.4f} "
            f"!= {FULL_GATE_THRESHOLDS['step_error_rate_required']:.4f}"
        )
    if metrics["judge_overall_avg"] < FULL_GATE_THRESHOLDS["judge_overall_avg_min"]:
        fail_reasons.append(
            f"judge_overall_avg={metrics['judge_overall_avg']:.4f} "
            f"< {FULL_GATE_THRESHOLDS['judge_overall_avg_min']:.4f}"
        )
    if metrics["judge_prompt_fidelity_avg"] < FULL_GATE_THRESHOLDS["judge_prompt_fidelity_avg_min"]:
        fail_reasons.append(
            f"judge_prompt_fidelity_avg={metrics['judge_prompt_fidelity_avg']:.4f} "
            f"< {FULL_GATE_THRESHOLDS['judge_prompt_fidelity_avg_min']:.4f}"
        )
    if metrics["case_overall_score_min"] < FULL_GATE_THRESHOLDS["case_overall_score_min"]:
        fail_reasons.append(
            f"case_overall_score_min={metrics['case_overall_score_min']:.4f} "
            f"< {FULL_GATE_THRESHOLDS['case_overall_score_min']:.4f}"
        )

    failure_breakdown = metrics.get("generation_failure_breakdown") or {}
    if fail_reasons and isinstance(failure_breakdown, dict) and failure_breakdown:
        top_code, top_count = max(failure_breakdown.items(), key=lambda item: item[1])
        fail_reasons.append(f"top_generation_failure={top_code}:{top_count}")

    passed = not fail_reasons
    return {
        "passed": passed,
        "evaluation_status": "passed" if passed else "failed",
        "thresholds": dict(FULL_GATE_THRESHOLDS),
        "fail_reasons": fail_reasons,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "generation_success_rate": 0.0,
        "pack_lint_success_rate": 0.0,
        "completion_rate": 0.0,
        "avg_steps": 0.0,
        "meaningful_accept_rate": 0.0,
        "llm_route_success_rate": 0.0,
        "global_help_route_rate": 0.0,
        "non_global_text_route_rate": 0.0,
        "strategy_triangle_coverage_rate": 0.0,
        "pressure_recoil_trigger_rate": 0.0,
        "npc_stance_mentions_per_run_avg": 0.0,
        "duplicate_beat_title_run_count": 0.0,
        "banned_move_hit_count": 0.0,
        "step_error_rate": 0.0,
        "judge_overall_avg": 0.0,
        "fun_score_avg": 0.0,
        "fun_score_case_min": 0.0,
        "judge_playability_avg": 0.0,
        "judge_choice_impact_avg": 0.0,
        "judge_tension_curve_avg": 0.0,
        "judge_prompt_fidelity_avg": 0.0,
        "case_overall_score_min": 0.0,
        "judge_sample_count": 0.0,
        "expected_judge_sample_count": 0.0,
        "generation_failure_breakdown": {},
        "prompt_spec_invalid_field_counts": {},
    }


def _evaluate_case_run(
    *,
    case: PromptSuiteCase,
    run_index: int,
    strategies: list[str],
    max_steps: int,
    packs_dir: Path,
    artifacts_dir: Path,
    judge_model: str | None,
    pipeline: GeneratorPipeline | None = None,
    judge: StoryQualityJudge | None = None,
) -> dict[str, Any]:
    case_seed = _derive_case_seed(case.id)
    run_seed = f"{case_seed}:run{run_index}"
    run_entry: dict[str, Any] = {
        "run_index": run_index,
        "variant_seed": run_seed,
        "status": "failed",
        "playthroughs": [],
    }
    generation_failure_breakdown: dict[str, int] = {}
    prompt_spec_invalid_field_counts: dict[str, int] = {}
    case_play_reports: list[dict[str, Any]] = []
    case_level_overall: list[float] = []
    case_level_fun: list[float] = []
    case_level_playability: list[float] = []
    case_level_choice_impact: list[float] = []
    case_level_tension_curve: list[float] = []
    global_judge_results: list[dict[str, Any]] = []
    global_judge_overall_scores: list[float] = []
    global_judge_fidelity_scores: list[float] = []

    pipeline_instance = pipeline or GeneratorPipeline()

    try:
        generated = asyncio.run(
            pipeline_instance.run(
                prompt_text=case.prompt_text,
                target_minutes=case.target_minutes,
                npc_count=case.npc_count,
                style=case.style,
                variant_seed=run_seed,
            )
        )
    except GeneratorBuildError as exc:
        error_code = exc.error_code or "generation_failed_after_regenerates"
        generation_failure_breakdown[error_code] = generation_failure_breakdown.get(error_code, 0) + 1
        if error_code == "prompt_spec_invalid":
            per_run_counts = _extract_prompt_spec_invalid_field_counts(list(exc.lint_report.errors))
            for field, count in per_run_counts.items():
                prompt_spec_invalid_field_counts[field] = prompt_spec_invalid_field_counts.get(field, 0) + count
        run_entry.update(
            {
                "status": "generation_failed",
                "error_code": error_code,
                "errors": list(exc.lint_report.errors),
                "warnings": list(exc.lint_report.warnings),
                "generation_attempts": exc.generation_attempts,
                "regenerate_count": exc.regenerate_count,
                "notes": list(exc.notes),
            }
        )
        return {
            "run_entry": run_entry,
            "generation_success": False,
            "pack_lint_success": False,
            "duplicate_beat_title_count": 0,
            "banned_move_hit_count": 0,
            "strategy_triangle_coverage": 0.0,
            "play_reports": case_play_reports,
            "judge_overall_scores": global_judge_overall_scores,
            "judge_results": global_judge_results,
            "judge_fidelity_scores": global_judge_fidelity_scores,
            "case_level_overall": case_level_overall,
            "case_level_fun": case_level_fun,
            "case_level_playability": case_level_playability,
            "case_level_choice_impact": case_level_choice_impact,
            "case_level_tension_curve": case_level_tension_curve,
            "generation_failure_breakdown": generation_failure_breakdown,
            "prompt_spec_invalid_field_counts": prompt_spec_invalid_field_counts,
        }
    except Exception as exc:  # noqa: BLE001
        generation_failure_breakdown["generation_exception"] = generation_failure_breakdown.get("generation_exception", 0) + 1
        run_entry.update(
            {
                "status": "generation_failed",
                "error_code": "generation_exception",
                "errors": [str(exc)],
                "warnings": [],
            }
        )
        return {
            "run_entry": run_entry,
            "generation_success": False,
            "pack_lint_success": False,
            "duplicate_beat_title_count": 0,
            "banned_move_hit_count": 0,
            "strategy_triangle_coverage": 0.0,
            "play_reports": case_play_reports,
            "judge_overall_scores": global_judge_overall_scores,
            "judge_results": global_judge_results,
            "judge_fidelity_scores": global_judge_fidelity_scores,
            "case_level_overall": case_level_overall,
            "case_level_fun": case_level_fun,
            "case_level_playability": case_level_playability,
            "case_level_choice_impact": case_level_choice_impact,
            "case_level_tension_curve": case_level_tension_curve,
            "generation_failure_breakdown": generation_failure_breakdown,
            "prompt_spec_invalid_field_counts": prompt_spec_invalid_field_counts,
        }

    pack_path = packs_dir / f"{generated.pack_hash}.json"
    _write_json_if_missing(pack_path, generated.pack)
    run_entry.update(
        {
            "status": "ok",
            "pack_hash": generated.pack_hash,
            "pack_path": str(pack_path),
            "generator_version": generated.generator_version,
            "generation_attempts": generated.generation_attempts,
            "regenerate_count": generated.regenerate_count,
            "spec_hash": generated.spec_hash,
            "lint_ok": generated.lint_report.ok,
            "lint_errors": list(generated.lint_report.errors),
            "lint_warnings": list(generated.lint_report.warnings),
        }
    )

    run_play_reports: list[dict[str, Any]] = []
    transcript_by_strategy: dict[str, dict[str, Any]] = {}
    for strategy in strategies:
        strategy_seed = _derive_strategy_seed(
            pack_hash=generated.pack_hash,
            case_id=case.id,
            run_index=run_index,
            strategy=strategy,
        )
        try:
            play_report = simulate_pack_playthrough(
                generated.pack,
                strategy=strategy,
                provider_name="openai",
                max_steps=max_steps,
                strategy_seed=strategy_seed,
                metadata={
                    "pack_hash": generated.pack_hash,
                    "generator_version": generated.generator_version,
                    "variant_seed": generated.variant_seed,
                },
            )
        except Exception as exc:  # noqa: BLE001
            run_entry["playthroughs"].append(
                {
                    "strategy": strategy,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue

        case_play_reports.append(play_report)
        run_play_reports.append(play_report)
        transcript_digest = compute_transcript_digest(play_report["transcript"])
        transcript_summary = _summarize_transcript(play_report)
        transcript_by_strategy[strategy] = transcript_summary
        artifact_path = artifacts_dir / case.id / f"run{run_index}_{strategy}.json"
        _write_json(
            artifact_path,
            {
                "case_id": case.id,
                "run_index": run_index,
                "strategy": strategy,
                "pack_hash": generated.pack_hash,
                "generator_version": generated.generator_version,
                "variant_seed": generated.variant_seed,
                "strategy_seed": strategy_seed,
                "transcript_digest": transcript_digest,
                "summary": transcript_summary,
            },
        )

        run_entry["playthroughs"].append(
            {
                "strategy": strategy,
                "status": "ok",
                "ended": bool(play_report["ended"]),
                "steps": int(play_report["steps"]),
                "meaningful_steps": int(play_report["meaningful_steps"]),
                "text_input_steps": int(play_report["text_input_steps"]),
                "llm_route_steps": int(play_report["llm_route_steps"]),
                "global_help_route_steps": int(play_report.get("global_help_route_steps", 0)),
                "pressure_recoil_steps": int(play_report.get("pressure_recoil_steps", 0)),
                "npc_stance_mentions": int(play_report.get("npc_stance_mentions", 0)),
                "runtime_error": bool(play_report["runtime_error"]),
                "runtime_error_code": play_report["runtime_error_code"],
                "runtime_error_stage": play_report["runtime_error_stage"],
                "strategy_seed": strategy_seed,
                "artifact_path": str(artifact_path),
                "transcript_digest": transcript_digest,
            }
        )

    if run_play_reports:
        run_metrics = _aggregate_playthrough_metrics(run_play_reports)
        try:
            judge_instance = judge or StoryQualityJudge(model_override=judge_model)
            decision = asyncio.run(
                judge_instance.evaluate(
                    prompt_text=case.prompt_text,
                    expected_tone=case.expected_tone,
                    pack_summary=_build_pack_summary(generated.pack),
                    transcript_summary={
                        "strategies": transcript_by_strategy,
                        "aggregate": run_metrics,
                    },
                    metrics=run_metrics,
                )
            )
            judge_payload = decision.result.model_dump()
            fun_score = _compute_fun_score(judge_payload)
            global_judge_overall_scores.append(float(decision.result.overall_score))
            global_judge_fidelity_scores.append(float(decision.result.prompt_fidelity_score))
            global_judge_results.append(judge_payload)
            case_level_overall.append(float(decision.result.overall_score))
            case_level_fun.append(fun_score)
            case_level_playability.append(float(decision.result.playability_score))
            case_level_choice_impact.append(float(decision.result.choice_impact_score))
            case_level_tension_curve.append(float(decision.result.tension_curve_score))
            run_entry["judge"] = {
                "status": "ok",
                "model": decision.model,
                "attempts": decision.attempts,
                "fun_score": fun_score,
                **judge_payload,
            }
        except Exception as exc:  # noqa: BLE001
            run_entry["judge"] = {
                "status": "failed",
                "error_type": _classify_precheck_error(exc),
                "error": str(exc),
            }
    else:
        run_entry["judge"] = {
            "status": "skipped",
            "reason": "no_playthrough_data",
        }

    return {
        "run_entry": run_entry,
        "generation_success": True,
        "pack_lint_success": bool(generated.lint_report.ok),
        "duplicate_beat_title_count": _count_duplicate_beat_titles(generated.pack),
        "banned_move_hit_count": _count_banned_moves(generated.pack),
        "strategy_triangle_coverage": _strategy_triangle_coverage_rate(generated.pack),
        "play_reports": case_play_reports,
        "judge_overall_scores": global_judge_overall_scores,
        "judge_results": global_judge_results,
        "judge_fidelity_scores": global_judge_fidelity_scores,
        "case_level_overall": case_level_overall,
        "case_level_fun": case_level_fun,
        "case_level_playability": case_level_playability,
        "case_level_choice_impact": case_level_choice_impact,
        "case_level_tension_curve": case_level_tension_curve,
        "generation_failure_breakdown": generation_failure_breakdown,
        "prompt_spec_invalid_field_counts": prompt_spec_invalid_field_counts,
    }


def evaluate_llm_story_generation(
    *,
    suite: PromptSuite,
    runs_per_prompt: int,
    strategies: list[str],
    max_steps: int,
    packs_dir: Path,
    artifacts_dir: Path,
    judge_model: str | None = None,
    max_workers: int = 1,
) -> dict[str, Any]:
    precheck = _run_precheck()
    suite_meta = {
        "id": suite.id,
        "version": suite.version,
        "prompt_count": len(suite.cases),
    }
    config = {
        "runs_per_prompt": runs_per_prompt,
        "strategies": strategies,
        "max_steps": max_steps,
        "judge_model": judge_model,
        "max_workers": max(1, int(max_workers)),
    }

    if precheck["status"] != "ok":
        metrics = _empty_metrics()
        gate = _compute_gate(metrics)
        gate["fail_reasons"].insert(0, f"precheck_failed:{precheck.get('error_type', 'unknown_error')}")
        gate["passed"] = False
        gate["evaluation_status"] = "failed"
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "eval_version": EVAL_VERSION,
            "suite": suite_meta,
            "config": config,
            "precheck": precheck,
            "metrics": metrics,
            "fun_focus": _build_fun_focus_report(metrics),
            "gate": gate,
            "cases": [],
        }

    shared_pipeline: GeneratorPipeline | None = None
    shared_judge: StoryQualityJudge | None = None
    if max_workers <= 1:
        shared_pipeline = GeneratorPipeline()
        shared_judge = StoryQualityJudge(model_override=judge_model)

    total_runs = len(suite.cases) * runs_per_prompt
    generation_success_count = 0
    pack_lint_success_count = 0
    global_play_reports: list[dict[str, Any]] = []
    global_judge_overall_scores: list[float] = []
    global_judge_results: list[dict[str, Any]] = []
    global_judge_fidelity_scores: list[float] = []
    case_level_overall: dict[str, list[float]] = {}
    case_level_fun: dict[str, list[float]] = {}
    case_level_playability: dict[str, list[float]] = {}
    case_level_choice_impact: dict[str, list[float]] = {}
    case_level_tension_curve: dict[str, list[float]] = {}
    generation_failure_breakdown: dict[str, int] = {}
    prompt_spec_invalid_field_counts: dict[str, int] = {}
    duplicate_beat_title_run_count = 0
    banned_move_hit_count = 0
    strategy_triangle_coverage_accumulator = 0.0
    case_reports: list[dict[str, Any]] = []

    packs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for case in suite.cases:
        case_runs: list[dict[str, Any]] = []
        case_play_reports: list[dict[str, Any]] = []
        case_level_overall.setdefault(case.id, [])
        case_level_fun.setdefault(case.id, [])
        case_level_playability.setdefault(case.id, [])
        case_level_choice_impact.setdefault(case.id, [])
        case_level_tension_curve.setdefault(case.id, [])

        run_results: list[dict[str, Any]] = []
        if max_workers <= 1:
            for run_index in range(1, runs_per_prompt + 1):
                run_results.append(
                    _evaluate_case_run(
                        case=case,
                        run_index=run_index,
                        strategies=strategies,
                        max_steps=max_steps,
                        packs_dir=packs_dir,
                        artifacts_dir=artifacts_dir,
                        judge_model=judge_model,
                        pipeline=shared_pipeline,
                        judge=shared_judge,
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(
                        _evaluate_case_run,
                        case=case,
                        run_index=run_index,
                        strategies=strategies,
                        max_steps=max_steps,
                        packs_dir=packs_dir,
                        artifacts_dir=artifacts_dir,
                        judge_model=judge_model,
                        pipeline=None,
                        judge=None,
                    ): run_index
                    for run_index in range(1, runs_per_prompt + 1)
                }
                for future in as_completed(futures):
                    run_results.append(future.result())

        run_results.sort(key=lambda item: int((item.get("run_entry") or {}).get("run_index", 0)))
        for run_result in run_results:
            run_entry = dict(run_result.get("run_entry") or {})
            case_runs.append(run_entry)

            if bool(run_result.get("generation_success", False)):
                generation_success_count += 1
            if bool(run_result.get("pack_lint_success", False)):
                pack_lint_success_count += 1
            duplicate_beat_title_run_count += int(run_result.get("duplicate_beat_title_count", 0))
            banned_move_hit_count += int(run_result.get("banned_move_hit_count", 0))
            strategy_triangle_coverage_accumulator += float(run_result.get("strategy_triangle_coverage", 0.0))

            for code, count in (run_result.get("generation_failure_breakdown") or {}).items():
                generation_failure_breakdown[code] = generation_failure_breakdown.get(code, 0) + int(count)
            for field, count in (run_result.get("prompt_spec_invalid_field_counts") or {}).items():
                prompt_spec_invalid_field_counts[field] = prompt_spec_invalid_field_counts.get(field, 0) + int(count)

            play_reports = list(run_result.get("play_reports") or [])
            global_play_reports.extend(play_reports)
            case_play_reports.extend(play_reports)

            global_judge_overall_scores.extend(float(v) for v in (run_result.get("judge_overall_scores") or []))
            global_judge_results.extend(list(run_result.get("judge_results") or []))
            global_judge_fidelity_scores.extend(float(v) for v in (run_result.get("judge_fidelity_scores") or []))

            case_level_overall[case.id].extend(float(v) for v in (run_result.get("case_level_overall") or []))
            case_level_fun[case.id].extend(float(v) for v in (run_result.get("case_level_fun") or []))
            case_level_playability[case.id].extend(float(v) for v in (run_result.get("case_level_playability") or []))
            case_level_choice_impact[case.id].extend(float(v) for v in (run_result.get("case_level_choice_impact") or []))
            case_level_tension_curve[case.id].extend(float(v) for v in (run_result.get("case_level_tension_curve") or []))

        case_metrics = _aggregate_playthrough_metrics(case_play_reports)
        case_generation_success_count = sum(1 for run in case_runs if run.get("status") == "ok")
        case_metrics.update(
            {
                "generation_success_rate": (
                    case_generation_success_count / runs_per_prompt if runs_per_prompt else 0.0
                ),
                "judge_overall_avg": _safe_mean(case_level_overall.get(case.id, [])),
                "fun_score_avg": _safe_mean(case_level_fun.get(case.id, [])),
                "playability_avg": _safe_mean(case_level_playability.get(case.id, [])),
                "choice_impact_avg": _safe_mean(case_level_choice_impact.get(case.id, [])),
                "tension_curve_avg": _safe_mean(case_level_tension_curve.get(case.id, [])),
                "judge_sample_count": len(case_level_overall.get(case.id, [])),
            }
        )
        case_reports.append(
            {
                "id": case.id,
                "tags": case.tags,
                "expected_tone": case.expected_tone,
                "runs": case_runs,
                "metrics": case_metrics,
            }
        )

    global_play_metrics = _aggregate_playthrough_metrics(global_play_reports)
    per_case_overall_avg = {
        case.id: _safe_mean(case_level_overall.get(case.id, []))
        for case in suite.cases
    }
    per_case_fun_avg = {
        case.id: _safe_mean(case_level_fun.get(case.id, []))
        for case in suite.cases
    }
    min_case_overall_score = min(per_case_overall_avg.values()) if per_case_overall_avg else 0.0
    min_case_fun_score = min(per_case_fun_avg.values()) if per_case_fun_avg else 0.0
    global_fun_metrics = _aggregate_fun_metrics(global_judge_results)

    metrics = {
        "generation_success_rate": generation_success_count / total_runs if total_runs else 0.0,
        "pack_lint_success_rate": (
            pack_lint_success_count / generation_success_count if generation_success_count else 0.0
        ),
        **global_play_metrics,
        "strategy_triangle_coverage_rate": (
            strategy_triangle_coverage_accumulator / generation_success_count if generation_success_count else 0.0
        ),
        "duplicate_beat_title_run_count": float(duplicate_beat_title_run_count),
        "banned_move_hit_count": float(banned_move_hit_count),
        "judge_overall_avg": _safe_mean(global_judge_overall_scores),
        "fun_score_avg": global_fun_metrics["fun_score_avg"],
        "fun_score_case_min": min_case_fun_score,
        "judge_playability_avg": global_fun_metrics["judge_playability_avg"],
        "judge_choice_impact_avg": global_fun_metrics["judge_choice_impact_avg"],
        "judge_tension_curve_avg": global_fun_metrics["judge_tension_curve_avg"],
        "judge_prompt_fidelity_avg": _safe_mean(global_judge_fidelity_scores),
        "case_overall_score_min": min_case_overall_score,
        "judge_sample_count": float(len(global_judge_overall_scores)),
        "expected_judge_sample_count": float(generation_success_count),
        "generation_failure_breakdown": generation_failure_breakdown,
        "prompt_spec_invalid_field_counts": prompt_spec_invalid_field_counts,
    }
    gate = _compute_gate(metrics)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_version": EVAL_VERSION,
        "suite": suite_meta,
        "config": config,
        "precheck": precheck,
        "metrics": metrics,
        "fun_focus": _build_fun_focus_report(metrics),
        "gate": gate,
        "cases": case_reports,
    }


def _determine_exit_code(*, strict: bool, gate: dict[str, Any]) -> int:
    if strict and not gate.get("passed"):
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Full eval for LLM prompt-to-story generation quality.")
    parser.add_argument("--profile", choices=("full", "fun_focus"), default="full", help="Eval profile preset")
    parser.add_argument("--suite-file", default=None, help="Prompt suite JSON file")
    parser.add_argument("--runs-per-prompt", type=int, default=None, help="Generation runs per prompt case")
    parser.add_argument(
        "--strategies",
        default=None,
        help="Comma-separated simulation strategies",
    )
    parser.add_argument("--max-steps", type=int, default=None, help="Maximum simulation steps per playthrough")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Max parallel workers across case x run units (default: 1 serial)",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output report path")
    parser.add_argument("--packs-dir", default=DEFAULT_PACKS_DIR, help="Directory to persist generated pack files")
    parser.add_argument(
        "--artifacts-dir",
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory to persist transcript summary artifacts",
    )
    parser.add_argument("--judge-model", default=None, help="Optional override model for quality judge")
    parser.add_argument(
        "--strict",
        type=_parse_bool,
        default=None,
        help="Hard gate mode: true exits non-zero on failed gate",
    )
    args = parser.parse_args()

    profile_config = _resolve_profile_config(
        profile=args.profile,
        suite_file=args.suite_file,
        runs_per_prompt=args.runs_per_prompt,
        strategies=args.strategies,
        max_steps=args.max_steps,
        strict=args.strict,
    )

    suite_path = Path(str(profile_config["suite_file"]))
    suite = _load_prompt_suite(suite_path)

    strategies = [item.strip() for item in str(profile_config["strategies"]).split(",") if item.strip()]
    if not strategies:
        raise RuntimeError("at least one strategy must be provided")
    unknown = sorted(set(strategies) - set(DEFAULT_STRATEGIES))
    if unknown:
        raise RuntimeError(f"unsupported strategies: {', '.join(unknown)}")

    report = evaluate_llm_story_generation(
        suite=suite,
        runs_per_prompt=max(1, int(profile_config["runs_per_prompt"])),
        strategies=strategies,
        max_steps=max(1, int(profile_config["max_steps"])),
        packs_dir=Path(args.packs_dir),
        artifacts_dir=Path(args.artifacts_dir),
        judge_model=args.judge_model,
        max_workers=max(1, int(args.max_workers)),
    )

    report["config"]["profile"] = args.profile

    output_path = Path(args.output)
    _write_json(output_path, report)
    print(str(output_path))
    metrics = report.get("metrics") or {}
    fun_focus = report.get("fun_focus") or {}
    warnings = fun_focus.get("warnings") or []
    print(
        "fun summary: "
        f"fun_score_avg={_to_score(metrics.get('fun_score_avg')):.4f}, "
        f"fun_score_case_min={_to_score(metrics.get('fun_score_case_min')):.4f}, "
        f"judge_playability_avg={_to_score(metrics.get('judge_playability_avg')):.4f}, "
        f"judge_choice_impact_avg={_to_score(metrics.get('judge_choice_impact_avg')):.4f}, "
        f"judge_tension_curve_avg={_to_score(metrics.get('judge_tension_curve_avg')):.4f}, "
        f"fun_warnings={len(warnings)}"
    )
    for warning in warnings:
        print(f"fun warning: {warning}")

    exit_code = _determine_exit_code(strict=bool(profile_config["strict"]), gate=report.get("gate") or {})
    if exit_code != 0:
        gate = report.get("gate") or {}
        fail_reasons = gate.get("fail_reasons") or []
        if fail_reasons:
            print("gate failed:")
            for reason in fail_reasons:
                print(f"- {reason}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
