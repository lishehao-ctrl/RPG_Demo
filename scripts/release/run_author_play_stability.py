#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.config.settings import get_settings
from rpg_backend.api.route_paths import (
    READY_PATH,
    admin_auth_login_path,
    author_run_path,
    author_runs_path,
    session_history_path,
    session_path,
    session_step_path,
    sessions_path,
    story_draft_path,
    story_publish_path,
)
from rpg_backend.eval.story_quality_judge import StoryQualityJudge, StoryQualityJudgeError
from scripts.eval.branch_coverage import analyze_branch_graph, summarize_branch_coverage
from scripts.eval.story_eval_helpers import (
    _aggregate_playthrough_metrics,
    _build_pack_summary,
    _compute_fun_score,
    _summarize_transcript,
)
from scripts.eval.simulate_playthrough import simulate_pack_playthrough

DEFAULT_SUITE_FILE = Path("eval_data/author_play_stability_suite_v1.json")
DEFAULT_OUTPUT_DIR = Path("reports/author_play_stability")
STANDARD_STRATEGIES = (
    "text_help",
    "text_noise",
    "button_first",
    "button_random",
    "mixed",
    "style_balanced",
)
BRANCH_HUNTER_MAX_RUNS = 6
PASS_THRESHOLDS = {
    "generation_success_rate": 1.0,
    "publish_success_rate": 1.0,
    "play_success_rate": 1.0,
    "completion_rate": 1.0,
    "meaningful_accept_rate": 0.90,
    "llm_route_success_rate": 0.80,
    "step_error_rate": 0.0,
    "scene_coverage_rate": 0.90,
    "conditional_edge_coverage_rate": 1.0,
    "terminal_edge_coverage_rate": 1.0,
    "judge_overall_avg": 7.5,
    "judge_prompt_fidelity_avg": 7.0,
    "fun_score_avg": 7.5,
    "fun_score_case_min": 6.5,
}


class StabilityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    raw_brief: str = Field(min_length=1)
    expected_tone: str | None = None


class StabilitySuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: list[StabilityCase] = Field(min_length=1)


@dataclass
class AuthContext:
    token: str
    headers: dict[str, str]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_suite(path: Path) -> StabilitySuite:
    return StabilitySuite.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _login(base_url: str) -> AuthContext:
    settings = get_settings()
    payload = {
        "email": settings.admin_bootstrap_email,
        "password": settings.admin_bootstrap_password,
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(f"{base_url}{admin_auth_login_path()}", json=payload)
        response.raise_for_status()
        token = response.json()["access_token"]
        return AuthContext(token=token, headers={"Authorization": f"Bearer {token}"})


def _check_ready(base_url: str) -> dict[str, Any]:
    with httpx.Client(timeout=60.0) as client:
        backend = client.get(f"{base_url}{READY_PATH}")
    return {
        "backend": backend.json(),
    }


def _generate_story(base_url: str, auth: AuthContext, case: StabilityCase) -> tuple[Any, dict[str, Any]]:
    raw_brief = case.raw_brief.strip()
    with httpx.Client(timeout=240.0) as client:
        created = client.post(
            f"{base_url}{author_runs_path()}",
            headers=auth.headers,
            json={"raw_brief": raw_brief},
        )
        created_body = created.json()
        if created.status_code >= 400:
            return created, created_body

        run_id = created_body["run_id"]
        story_id = created_body["story_id"]
        run_body: dict[str, Any] = {}
        for _ in range(120):
            run_response = client.get(f"{base_url}{author_run_path(run_id)}", headers=auth.headers)
            run_body = run_response.json()
            if run_response.status_code >= 400:
                return run_response, run_body
            if run_body.get("status") == "review_ready":
                draft_response = client.get(f"{base_url}{story_draft_path(story_id)}", headers=auth.headers)
                draft_body = draft_response.json()
                synthesized = {
                    "story_id": story_id,
                    "run_id": run_id,
                    "status": run_body.get("status"),
                    "pack": draft_body.get("draft_pack", {}),
                    "author_run": run_body,
                }
                return draft_response, synthesized
            if run_body.get("status") == "failed":
                return run_response, run_body
            import time
            time.sleep(2.0)
        return run_response, {"error": "author_run_timeout", "run": run_body}


def _publish_story(base_url: str, auth: AuthContext, story_id: str) -> tuple[httpx.Response, dict[str, Any]]:
    with httpx.Client(timeout=120.0) as client:
        response = client.post(f"{base_url}{story_publish_path(story_id)}", headers=auth.headers, json={})
        body = response.json()
    return response, body


def _story_draft(base_url: str, auth: AuthContext, story_id: str) -> dict[str, Any]:
    with httpx.Client(timeout=60.0) as client:
        response = client.get(f"{base_url}{story_draft_path(story_id)}", headers=auth.headers)
        response.raise_for_status()
        return response.json()


def _play_api_flow(base_url: str, auth: AuthContext, story_id: str, version: int) -> dict[str, Any]:
    with httpx.Client(timeout=180.0) as client:
        created = client.post(
            f"{base_url}{sessions_path()}",
            headers=auth.headers,
            json={"story_id": story_id, "version": version},
        )
        created.raise_for_status()
        session_id = created.json()["session_id"]

        first = client.post(
            f"{base_url}{session_step_path(session_id)}",
            headers=auth.headers,
            json={
                "client_action_id": f"{story_id}-text-1",
                "input": {"type": "text", "text": "Begin with a careful survey of the breach"},
                "dev_mode": False,
            },
        )
        first_body = first.json()
        first_ok = first.status_code == 200

        second_ok = False
        second_body: dict[str, Any] | None = None
        if first_ok and first_body.get("ui", {}).get("moves"):
            move_id = first_body["ui"]["moves"][0]["move_id"]
            second = client.post(
                f"{base_url}{session_step_path(session_id)}",
                headers=auth.headers,
                json={
                    "client_action_id": f"{story_id}-button-2",
                    "input": {"type": "button", "move_id": move_id},
                    "dev_mode": False,
                },
            )
            second_body = second.json()
            second_ok = second.status_code == 200

        history = client.get(f"{base_url}{session_history_path(session_id)}", headers=auth.headers)
        history.raise_for_status()
        session_after_reload = client.get(f"{base_url}{session_path(session_id)}", headers=auth.headers)
        session_after_reload.raise_for_status()

    return {
        "session_id": session_id,
        "create_status_code": created.status_code,
        "text_step_status_code": first.status_code,
        "button_step_status_code": 200 if second_ok else (None if second_body is None else second.status_code),
        "text_route_source": first_body.get("recognized", {}).get("route_source") if first_ok else None,
        "button_route_source": second_body.get("recognized", {}).get("route_source") if second_body else None,
        "history_turns": len(history.json().get("history") or []),
        "reload_ended": session_after_reload.json().get("ended"),
        "passed": bool(created.status_code == 200 and first_ok and second_ok and len(history.json().get("history") or []) >= 2),
        "text_error": None if first_ok else first_body.get("error"),
        "button_error": None if second_ok or second_body is None else second_body.get("error"),
    }


def _judge_reports(case: StabilityCase, pack_json: dict[str, Any], reports: list[dict[str, Any]]) -> dict[str, Any]:
    judge = StoryQualityJudge()
    results: list[dict[str, Any]] = []
    for report in reports:
        transcript_summary = _summarize_transcript(report)
        metrics = _aggregate_playthrough_metrics([report])
        try:
            decision = asyncio.run(
                judge.evaluate(
                    prompt_text=case.raw_brief or case.id,
                    expected_tone=case.expected_tone,
                    pack_summary=_build_pack_summary(pack_json),
                    transcript_summary=transcript_summary,
                    metrics=metrics,
                )
            )
            payload = decision.result.model_dump()
            results.append(
                {
                    "strategy": report["strategy"],
                    "status": "ok",
                    "fun_score": _compute_fun_score(payload),
                    **payload,
                }
            )
        except StoryQualityJudgeError as exc:
            results.append(
                {
                    "strategy": report["strategy"],
                    "status": "failed",
                    "error_type": exc.error_type,
                    "error": str(exc),
                }
            )
    return {
        "results": results,
        "successful": [item for item in results if item["status"] == "ok"],
    }


def _run_pack_strategies(case: StabilityCase, pack_json: dict[str, Any], *, max_steps: int, branch_hunter_max_runs: int) -> dict[str, Any]:
    graph = analyze_branch_graph(pack_json)
    reports: list[dict[str, Any]] = []
    for index, strategy in enumerate(STANDARD_STRATEGIES, start=1):
        reports.append(
            simulate_pack_playthrough(
                pack_json,
                strategy=strategy,
                max_steps=max_steps,
                strategy_seed=20_000 + index,
            )
        )
    coverage = summarize_branch_coverage(graph=graph, play_reports=reports)

    branch_hunter_reports: list[dict[str, Any]] = []
    run_index = 0
    while run_index < branch_hunter_max_runs and (
        coverage["conditional_edge_coverage_rate"] < 1.0
        or coverage["terminal_edge_coverage_rate"] < 1.0
        or coverage["scene_coverage_rate"] < 0.90
    ):
        run_index += 1
        report = simulate_pack_playthrough(
            pack_json,
            strategy="branch_hunter",
            max_steps=max_steps,
            strategy_seed=30_000 + run_index,
            strategy_state={
                "branch_targets": graph["edges_by_scene"],
                "covered_edge_ids": coverage["covered_edge_ids"],
            },
        )
        branch_hunter_reports.append(report)
        reports.append(report)
        coverage = summarize_branch_coverage(graph=graph, play_reports=reports)

    aggregate_metrics = _aggregate_playthrough_metrics(reports)
    return {
        "graph": graph,
        "coverage": coverage,
        "reports": reports,
        "branch_hunter_runs": branch_hunter_reports,
        "metrics": aggregate_metrics,
    }


def _case_pass(case_result: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not case_result["generation"]["ok"]:
        failures.append("generation_failed")
    if not case_result["publish"]["ok"]:
        failures.append("publish_failed")
    if not case_result["ui_flow"]["passed"]:
        failures.append("play_api_flow_failed")

    coverage = case_result["system"]["coverage"]
    metrics = case_result["system"]["metrics"]
    judge_ok = case_result["judge"]["successful"]
    if coverage["scene_coverage_rate"] < PASS_THRESHOLDS["scene_coverage_rate"]:
        failures.append("scene_coverage_low")
    if coverage["conditional_edge_coverage_rate"] < PASS_THRESHOLDS["conditional_edge_coverage_rate"]:
        failures.append("conditional_edge_coverage_low")
    if coverage["terminal_edge_coverage_rate"] < PASS_THRESHOLDS["terminal_edge_coverage_rate"]:
        failures.append("terminal_edge_coverage_low")
    if metrics["completion_rate"] < PASS_THRESHOLDS["completion_rate"]:
        failures.append("completion_rate_low")
    if metrics["meaningful_accept_rate"] < PASS_THRESHOLDS["meaningful_accept_rate"]:
        failures.append("meaningful_accept_rate_low")
    if metrics["llm_route_success_rate"] < PASS_THRESHOLDS["llm_route_success_rate"]:
        failures.append("llm_route_success_rate_low")
    if metrics["step_error_rate"] > PASS_THRESHOLDS["step_error_rate"]:
        failures.append("step_error_rate_high")
    if coverage["untriggerable_conditional_edges"]:
        failures.append("untriggerable_conditional_edges")
    if not judge_ok:
        failures.append("judge_failed")
    else:
        overall_avg = mean(item["overall_score"] for item in judge_ok)
        fidelity_avg = mean(item["prompt_fidelity_score"] for item in judge_ok)
        fun_avg = mean(item["fun_score"] for item in judge_ok)
        fun_min = min(item["fun_score"] for item in judge_ok)
        if overall_avg < PASS_THRESHOLDS["judge_overall_avg"]:
            failures.append("judge_overall_low")
        if fidelity_avg < PASS_THRESHOLDS["judge_prompt_fidelity_avg"]:
            failures.append("judge_prompt_fidelity_low")
        if fun_avg < PASS_THRESHOLDS["fun_score_avg"]:
            failures.append("fun_score_avg_low")
        if fun_min < PASS_THRESHOLDS["fun_score_case_min"]:
            failures.append("fun_score_case_min_low")
    return (len(failures) == 0, failures)


def run_suite(*, suite: StabilitySuite, base_url: str, output_dir: Path, max_steps: int, branch_hunter_max_runs: int) -> dict[str, Any]:
    auth = _login(base_url)
    readiness = _check_ready(base_url)
    summary_cases: list[dict[str, Any]] = []
    passed_cases = 0

    for case in suite.cases:
        case_dir = output_dir / "per_game" / case.id
        case_dir.mkdir(parents=True, exist_ok=True)
        generated_response, generated_body = _generate_story(base_url, auth, case)
        generation_ok = generated_response.status_code == 200
        case_result: dict[str, Any] = {
            "case": case.model_dump(),
            "generation": {
                "ok": generation_ok,
                "status_code": generated_response.status_code,
                "response": generated_body,
            },
            "publish": {"ok": False},
            "ui_flow": {"passed": False},
            "system": {
                "graph": {},
                "coverage": {},
                "reports": [],
                "branch_hunter_runs": [],
                "metrics": {},
            },
            "judge": {"results": [], "successful": []},
        }
        if generation_ok:
            story_id = generated_body["story_id"]
            pack = generated_body["pack"]
            _write_json(case_dir / "generated_response.json", generated_body)
            draft = _story_draft(base_url, auth, story_id)
            _write_json(case_dir / "draft.json", draft)
            publish_response, publish_body = _publish_story(base_url, auth, story_id)
            case_result["publish"] = {
                "ok": publish_response.status_code == 200,
                "status_code": publish_response.status_code,
                "response": publish_body,
            }
            if publish_response.status_code == 200:
                ui_flow = _play_api_flow(base_url, auth, story_id, publish_body["version"])
                case_result["ui_flow"] = ui_flow
            system_result = _run_pack_strategies(case, pack, max_steps=max_steps, branch_hunter_max_runs=branch_hunter_max_runs)
            case_result["system"] = system_result
            case_result["judge"] = _judge_reports(case, pack, system_result["reports"])
            _write_json(case_dir / "system_result.json", {
                "graph": system_result["graph"],
                "coverage": system_result["coverage"],
                "metrics": system_result["metrics"],
                "reports": system_result["reports"],
                "judge": case_result["judge"]["results"],
                "ui_flow": case_result["ui_flow"],
            })
        passed, failures = _case_pass(case_result)
        case_result["status"] = "passed" if passed else "failed"
        case_result["failures"] = failures
        if passed:
            passed_cases += 1
        summary_cases.append(case_result)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "suite": suite.model_dump(),
        "readiness": readiness,
        "thresholds": PASS_THRESHOLDS,
        "case_count": len(summary_cases),
        "passed_case_count": passed_cases,
        "failed_case_count": len(summary_cases) - passed_cases,
        "status": "passed" if passed_cases == len(summary_cases) else ("partial" if passed_cases > 0 else "failed"),
        "cases": summary_cases,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run large-scale author/play stability evaluation.")
    parser.add_argument("--suite-file", default=str(DEFAULT_SUITE_FILE), help="Path to stability suite JSON")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum playthrough steps per run")
    parser.add_argument("--branch-hunter-max-runs", type=int, default=BRANCH_HUNTER_MAX_RUNS, help="Maximum branch hunter runs per game")
    args = parser.parse_args()

    suite = _load_suite(Path(args.suite_file))
    summary = run_suite(
        suite=suite,
        base_url=args.base_url.rstrip("/"),
        output_dir=Path(args.output_dir),
        max_steps=max(1, args.max_steps),
        branch_hunter_max_runs=max(1, args.branch_hunter_max_runs),
    )
    print(Path(args.output_dir) / "summary.json")
    if summary["status"] == "passed":
        return 0
    if summary["status"] == "partial":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
