#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config.settings import get_settings
from app.eval.story_quality_judge import StoryQualityJudge, StoryQualityJudgeError
from app.generator.prompt_compiler import PromptCompileError, PromptCompiler
from app.generator.service import GeneratorBuildError, GeneratorService
from app.generator.versioning import compute_transcript_digest

try:
    from scripts.simulate_playthrough import DEFAULT_STRATEGIES, simulate_pack_playthrough
except ModuleNotFoundError:
    from simulate_playthrough import DEFAULT_STRATEGIES, simulate_pack_playthrough

EVAL_VERSION = "llm_story_generation_eval.v1"
GLOBAL_EVAL_SEED = "llm_story_eval_seed_v1"
DEFAULT_SUITE_FILE = "eval_data/prompt_suite_v1.json"
DEFAULT_OUTPUT = "reports/llm_story_generation_eval.json"
DEFAULT_PACKS_DIR = "reports/packs_llm"
DEFAULT_ARTIFACTS_DIR = "reports/llm_story_eval_artifacts"
DEFAULT_STRATEGY_SET = ("mixed", "text_noise", "button_random")
PROMPT_SPEC_TRACKED_FIELDS = ("premise", "stakes", "tone", "title")

FULL_GATE_THRESHOLDS: dict[str, float] = {
    "generation_success_rate_required": 1.0,
    "pack_lint_success_rate_required": 1.0,
    "completion_rate_required": 1.0,
    "avg_steps_min": 14.0,
    "avg_steps_max": 16.0,
    "meaningful_accept_rate_min": 0.90,
    "fallback_error_rate_max": 0.05,
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
            "fallback_with_progress_rate": 1.0,
            "fallback_error_rate": 0.0,
            "fallback_low_confidence_rate": 0.0,
        }

    completion_count = sum(1 for report in reports if report.get("ended"))
    completed_steps = [int(report.get("steps", 0)) for report in reports if report.get("ended")]
    total_steps = sum(int(report.get("steps", 0)) for report in reports)
    meaningful_steps = sum(int(report.get("meaningful_steps", 0)) for report in reports)
    fallback_steps = sum(int(report.get("fallback_steps", 0)) for report in reports)
    fallback_with_progress_steps = sum(int(report.get("fallback_with_progress_steps", 0)) for report in reports)
    text_input_steps = sum(int(report.get("text_input_steps", 0)) for report in reports)
    fallback_error_steps = sum(int(report.get("fallback_error_steps", 0)) for report in reports)
    fallback_low_confidence_steps = sum(int(report.get("fallback_low_confidence_steps", 0)) for report in reports)

    return {
        "completion_rate": completion_count / len(reports),
        "avg_steps": _safe_mean(completed_steps),
        "meaningful_accept_rate": meaningful_steps / total_steps if total_steps else 0.0,
        "fallback_with_progress_rate": (
            fallback_with_progress_steps / fallback_steps if fallback_steps else 1.0
        ),
        "fallback_error_rate": fallback_error_steps / text_input_steps if text_input_steps else 0.0,
        "fallback_low_confidence_rate": (
            fallback_low_confidence_steps / text_input_steps if text_input_steps else 0.0
        ),
    }


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
                    "fallback_with_progress": entry.get("fallback_with_progress"),
                }
            )

    return {
        "strategy": report.get("strategy"),
        "provider": report.get("provider"),
        "ended": bool(report.get("ended")),
        "steps": int(report.get("steps", 0)),
        "meaningful_steps": int(report.get("meaningful_steps", 0)),
        "fallback_steps": int(report.get("fallback_steps", 0)),
        "fallback_with_progress_steps": int(report.get("fallback_with_progress_steps", 0)),
        "fallback_error_steps": int(report.get("fallback_error_steps", 0)),
        "fallback_low_confidence_steps": int(report.get("fallback_low_confidence_steps", 0)),
        "highlights": highlights,
    }


def _run_precheck() -> dict[str, Any]:
    settings = get_settings()
    base_url = (settings.llm_openai_base_url or "").strip()
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        return {
            "status": "failed",
            "error_type": "misconfigured",
            "error": "APP_LLM_OPENAI_BASE_URL is missing or invalid",
            "base_url": base_url,
            "host": host,
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
        }

    try:
        compiled = PromptCompiler().compile(
            prompt_text="Precheck story prompt: produce a compact but playable city emergency setup.",
            target_minutes=10,
            npc_count=4,
            style="neutral",
            attempt_index=0,
            attempt_seed="precheck",
        )
        return {
            "status": "ok",
            "error_type": None,
            "error": None,
            "base_url": base_url,
            "host": host,
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
    if metrics["fallback_error_rate"] > FULL_GATE_THRESHOLDS["fallback_error_rate_max"]:
        fail_reasons.append(
            f"fallback_error_rate={metrics['fallback_error_rate']:.4f} "
            f"> {FULL_GATE_THRESHOLDS['fallback_error_rate_max']:.4f}"
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
        "fallback_with_progress_rate": 1.0,
        "fallback_error_rate": 0.0,
        "fallback_low_confidence_rate": 0.0,
        "judge_overall_avg": 0.0,
        "judge_prompt_fidelity_avg": 0.0,
        "case_overall_score_min": 0.0,
        "judge_sample_count": 0.0,
        "expected_judge_sample_count": 0.0,
        "generation_failure_breakdown": {},
        "prompt_spec_invalid_field_counts": {},
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
            "gate": gate,
            "cases": [],
        }

    service = GeneratorService()
    judge = StoryQualityJudge(model_override=judge_model)

    total_runs = len(suite.cases) * runs_per_prompt
    generation_success_count = 0
    pack_lint_success_count = 0
    global_play_reports: list[dict[str, Any]] = []
    global_judge_overall_scores: list[float] = []
    global_judge_fidelity_scores: list[float] = []
    case_level_overall: dict[str, list[float]] = {}
    generation_failure_breakdown: dict[str, int] = {}
    prompt_spec_invalid_field_counts: dict[str, int] = {}
    case_reports: list[dict[str, Any]] = []

    packs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for case in suite.cases:
        case_seed = _derive_case_seed(case.id)
        case_runs: list[dict[str, Any]] = []
        case_play_reports: list[dict[str, Any]] = []
        case_level_overall.setdefault(case.id, [])

        for run_index in range(1, runs_per_prompt + 1):
            run_seed = f"{case_seed}:run{run_index}"
            run_entry: dict[str, Any] = {
                "run_index": run_index,
                "variant_seed": run_seed,
                "status": "failed",
                "playthroughs": [],
            }

            try:
                generated = service.generate_pack(
                    prompt_text=case.prompt_text,
                    target_minutes=case.target_minutes,
                    npc_count=case.npc_count,
                    style=case.style,
                    variant_seed=run_seed,
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
                case_runs.append(run_entry)
                continue
            except Exception as exc:  # noqa: BLE001
                generation_failure_breakdown["generation_exception"] = (
                    generation_failure_breakdown.get("generation_exception", 0) + 1
                )
                run_entry.update(
                    {
                        "status": "generation_failed",
                        "error_code": "generation_exception",
                        "errors": [str(exc)],
                        "warnings": [],
                    }
                )
                case_runs.append(run_entry)
                continue

            generation_success_count += 1
            if generated.lint_report.ok:
                pack_lint_success_count += 1

            pack_path = packs_dir / f"{generated.pack_hash}.json"
            if not pack_path.exists():
                _write_json(pack_path, generated.pack)

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
                        provider_name="fake",
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

                global_play_reports.append(play_report)
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
                        "fallback_steps": int(play_report["fallback_steps"]),
                        "fallback_with_progress_steps": int(play_report["fallback_with_progress_steps"]),
                        "fallback_error_steps": int(play_report["fallback_error_steps"]),
                        "fallback_low_confidence_steps": int(play_report["fallback_low_confidence_steps"]),
                        "strategy_seed": strategy_seed,
                        "artifact_path": str(artifact_path),
                        "transcript_digest": transcript_digest,
                    }
                )

            if run_play_reports:
                run_metrics = _aggregate_playthrough_metrics(run_play_reports)
                try:
                    decision = judge.evaluate(
                        prompt_text=case.prompt_text,
                        expected_tone=case.expected_tone,
                        pack_summary=_build_pack_summary(generated.pack),
                        transcript_summary={
                            "strategies": transcript_by_strategy,
                            "aggregate": run_metrics,
                        },
                        metrics=run_metrics,
                    )
                    judge_payload = decision.result.model_dump()
                    global_judge_overall_scores.append(float(decision.result.overall_score))
                    global_judge_fidelity_scores.append(float(decision.result.prompt_fidelity_score))
                    case_level_overall[case.id].append(float(decision.result.overall_score))
                    run_entry["judge"] = {
                        "status": "ok",
                        "model": decision.model,
                        "attempts": decision.attempts,
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

            case_runs.append(run_entry)

        case_metrics = _aggregate_playthrough_metrics(case_play_reports)
        case_generation_success_count = sum(1 for run in case_runs if run.get("status") == "ok")
        case_metrics.update(
            {
                "generation_success_rate": (
                    case_generation_success_count / runs_per_prompt if runs_per_prompt else 0.0
                ),
                "judge_overall_avg": _safe_mean(case_level_overall.get(case.id, [])),
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
    min_case_overall_score = min(per_case_overall_avg.values()) if per_case_overall_avg else 0.0

    metrics = {
        "generation_success_rate": generation_success_count / total_runs if total_runs else 0.0,
        "pack_lint_success_rate": (
            pack_lint_success_count / generation_success_count if generation_success_count else 0.0
        ),
        **global_play_metrics,
        "judge_overall_avg": _safe_mean(global_judge_overall_scores),
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
        "gate": gate,
        "cases": case_reports,
    }


def _determine_exit_code(*, strict: bool, gate: dict[str, Any]) -> int:
    if strict and not gate.get("passed"):
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Full eval for LLM prompt-to-story generation quality.")
    parser.add_argument("--suite-file", default=DEFAULT_SUITE_FILE, help="Prompt suite JSON file")
    parser.add_argument("--runs-per-prompt", type=int, default=3, help="Generation runs per prompt case")
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGY_SET),
        help="Comma-separated simulation strategies",
    )
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum simulation steps per playthrough")
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
        default=True,
        help="Hard gate mode: true exits non-zero on failed gate",
    )
    args = parser.parse_args()

    suite_path = Path(args.suite_file)
    suite = _load_prompt_suite(suite_path)

    strategies = [item.strip() for item in str(args.strategies).split(",") if item.strip()]
    if not strategies:
        raise RuntimeError("at least one strategy must be provided")
    unknown = sorted(set(strategies) - set(DEFAULT_STRATEGIES))
    if unknown:
        raise RuntimeError(f"unsupported strategies: {', '.join(unknown)}")

    report = evaluate_llm_story_generation(
        suite=suite,
        runs_per_prompt=max(1, args.runs_per_prompt),
        strategies=strategies,
        max_steps=max(1, args.max_steps),
        packs_dir=Path(args.packs_dir),
        artifacts_dir=Path(args.artifacts_dir),
        judge_model=args.judge_model,
    )

    output_path = Path(args.output)
    _write_json(output_path, report)
    print(str(output_path))

    exit_code = _determine_exit_code(strict=bool(args.strict), gate=report.get("gate") or {})
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
