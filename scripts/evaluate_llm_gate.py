#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from rpg_backend.config.settings import get_settings
from rpg_backend.llm.base import LLMNarrationError, LLMProviderConfigError, LLMRouteError
from rpg_backend.llm.factory import get_llm_provider, resolve_openai_models

try:
    from scripts.simulate_playthrough import simulate_pack_playthrough
except ModuleNotFoundError:
    from simulate_playthrough import simulate_pack_playthrough

MEDIUM_GATE_THRESHOLDS: dict[str, float] = {
    "completion_rate_required": 1.0,
    "meaningful_accept_rate_min": 0.90,
    "llm_route_success_rate_min": 0.80,
    "step_error_rate_required": 0.0,
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
            if status in {404, 405, 422}:
                return "unsupported_chat_completions_api"
            if item.response.status_code in {401, 403}:
                return "auth_error"
            return f"http_{status}"
        if isinstance(item, LLMProviderConfigError):
            return "misconfigured"
        if isinstance(item, LLMRouteError):
            return "route_error"
        if isinstance(item, LLMNarrationError):
            return "narration_error"
    return "unknown_error"


def _run_openai_precheck() -> dict[str, Any]:
    settings = get_settings()
    base_url = (getattr(settings, "llm_openai_base_url", None) or "").strip()
    route_model, _ = resolve_openai_models(
        getattr(settings, "llm_openai_route_model", None),
        getattr(settings, "llm_openai_narration_model", None),
        getattr(settings, "llm_openai_model", None),
    )
    parsed = urlparse(base_url)
    host = parsed.hostname or ""

    if not host:
        return {
            "status": "failed",
            "error_type": "misconfigured",
            "error": "APP_LLM_OPENAI_BASE_URL is missing or invalid",
            "base_url": base_url,
            "host": host,
            "route_model": route_model,
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
            "route_model": route_model,
        }

    try:
        provider = get_llm_provider()
        routed = asyncio.run(
            provider.route_intent(
                scene_context={
                    "moves": [
                        {
                            "id": "global.help_me_progress",
                            "label": "Help me progress",
                            "intents": ["progress", "help"],
                            "synonyms": ["advance"],
                        },
                        {
                            "id": "global.clarify",
                            "label": "Clarify intent",
                            "intents": ["clarify"],
                            "synonyms": ["explain"],
                        },
                    ],
                    "fallback_move": "global.help_me_progress",
                    "scene_seed": "precheck scene",
                },
                text="help me progress",
            )
        )
        return {
            "status": "ok",
            "error_type": None,
            "error": None,
            "base_url": base_url,
            "host": host,
            "route_model": getattr(provider, "route_model", route_model),
            "probe_move_id": routed.move_id,
            "probe_confidence": float(routed.confidence),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "error_type": _classify_precheck_error(exc),
            "error": str(exc),
            "base_url": base_url,
            "host": host,
            "route_model": route_model,
        }


def _compute_gate(metrics: dict[str, float]) -> dict[str, Any]:
    gate = {
        "thresholds": dict(MEDIUM_GATE_THRESHOLDS),
        "completion_rate": metrics["completion_rate"],
        "meaningful_accept_rate": metrics["meaningful_accept_rate"],
        "llm_route_success_rate": metrics["llm_route_success_rate"],
        "step_error_rate": metrics["step_error_rate"],
    }
    gate["passed"] = (
        gate["completion_rate"] == MEDIUM_GATE_THRESHOLDS["completion_rate_required"]
        and gate["meaningful_accept_rate"] >= MEDIUM_GATE_THRESHOLDS["meaningful_accept_rate_min"]
        and gate["llm_route_success_rate"] >= MEDIUM_GATE_THRESHOLDS["llm_route_success_rate_min"]
        and gate["step_error_rate"] <= MEDIUM_GATE_THRESHOLDS["step_error_rate_required"]
    )
    gate["evaluation_status"] = "passed" if gate["passed"] else "failed"
    return gate


def _aggregate_provider_metrics(reports: list[dict[str, Any]]) -> dict[str, float]:
    if not reports:
        return {
            "completion_rate": 0.0,
            "avg_steps": 0.0,
            "meaningful_accept_rate": 0.0,
            "llm_route_success_rate": 0.0,
            "step_error_rate": 0.0,
        }

    completion_count = sum(1 for report in reports if report["ended"])
    completed_steps = [report["steps"] for report in reports if report["ended"]]
    total_steps = sum(report["steps"] for report in reports)
    meaningful_steps = sum(report["meaningful_steps"] for report in reports)
    text_input_steps = sum(report.get("text_input_steps", 0) for report in reports)
    llm_route_steps = sum(report.get("llm_route_steps", 0) for report in reports)
    runtime_error_steps = sum(report.get("runtime_error_steps", 0) for report in reports)

    return {
        "completion_rate": completion_count / len(reports),
        "avg_steps": (sum(completed_steps) / len(completed_steps)) if completed_steps else 0.0,
        "meaningful_accept_rate": (meaningful_steps / total_steps) if total_steps else 0.0,
        "llm_route_success_rate": (llm_route_steps / text_input_steps) if text_input_steps else 0.0,
        "step_error_rate": runtime_error_steps / len(reports),
    }


def evaluate_llm_gate(
    *,
    pack_json: dict[str, Any],
    runs: int,
    strategy: str,
    max_steps: int,
    allow_precheck_fail: bool = False,
) -> dict[str, Any]:
    precheck = _run_openai_precheck()
    if precheck["status"] != "ok":
        metrics = _aggregate_provider_metrics([])
        gate = _compute_gate(metrics)
        gate["passed"] = False
        gate["precheck_required"] = True
        gate["evaluation_status"] = "inconclusive" if allow_precheck_fail else "failed"
        gate["inconclusive"] = bool(allow_precheck_fail)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "runs": runs,
            "strategy": strategy,
            "max_steps": max_steps,
            "allow_precheck_fail": allow_precheck_fail,
            "precheck": precheck,
            "metrics": metrics,
            "gate": gate,
            "runs_detail": [],
        }

    provider_reports: list[dict[str, Any]] = []
    runs_detail: list[dict[str, Any]] = []

    for run_index in range(1, runs + 1):
        strategy_seed = 10_000 + run_index
        run_entry: dict[str, Any] = {"run": run_index, "strategy_seed": strategy_seed}

        report = simulate_pack_playthrough(
            pack_json,
            strategy=strategy,
            provider_name="openai",
            max_steps=max_steps,
            strategy_seed=strategy_seed,
        )
        provider_reports.append(report)
        run_entry["openai"] = {
            "ended": report["ended"],
            "steps": report["steps"],
            "meaningful_steps": report["meaningful_steps"],
            "text_input_steps": report.get("text_input_steps", 0),
            "llm_route_steps": report.get("llm_route_steps", 0),
            "runtime_error": bool(report.get("runtime_error", False)),
            "runtime_error_code": report.get("runtime_error_code"),
            "runtime_error_stage": report.get("runtime_error_stage"),
            "runtime_error_message": report.get("runtime_error_message"),
        }

        runs_detail.append(run_entry)

    metrics = _aggregate_provider_metrics(provider_reports)
    gate = _compute_gate(metrics)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "runs": runs,
        "strategy": strategy,
        "max_steps": max_steps,
        "allow_precheck_fail": allow_precheck_fail,
        "precheck": precheck,
        "metrics": metrics,
        "gate": gate,
        "runs_detail": runs_detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate OpenAI runtime gate metrics on the same pack.")
    parser.add_argument("--pack-file", required=True, help="Path to a raw pack JSON file")
    parser.add_argument("--runs", type=int, default=50, help="Number of repeated runs")
    parser.add_argument(
        "--strategy",
        default="mixed",
        choices=["text_help", "text_noise", "button_first", "button_random", "mixed"],
        help="Simulation strategy",
    )
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum steps per playthrough")
    parser.add_argument("--output", default="reports/llm_gate_eval.json", help="Output report path")
    parser.add_argument(
        "--allow-precheck-fail",
        action="store_true",
        help="Allow OpenAI precheck failure and mark gate as inconclusive instead of hard fail",
    )
    args = parser.parse_args()

    with open(args.pack_file, "r", encoding="utf-8") as f:
        pack_json = json.load(f)

    try:
        report = evaluate_llm_gate(
            pack_json=pack_json,
            runs=max(1, args.runs),
            strategy=args.strategy,
            max_steps=max(1, args.max_steps),
            allow_precheck_fail=args.allow_precheck_fail,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(str(output_path))
    gate = report.get("gate") or {}
    if gate.get("evaluation_status") == "inconclusive":
        precheck = report.get("precheck") or {}
        error_type = precheck.get("error_type", "unknown_error")
        error_msg = precheck.get("error") or "precheck failed"
        print(f"precheck inconclusive: {error_type}: {error_msg}")
        return 0
    if not gate.get("passed"):
        precheck = report.get("precheck") or {}
        if precheck.get("status") == "failed":
            error_type = precheck.get("error_type", "unknown_error")
            error_msg = precheck.get("error") or "precheck failed"
            print(f"precheck failed: {error_type}: {error_msg}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
