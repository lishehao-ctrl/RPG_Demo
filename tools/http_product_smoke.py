from __future__ import annotations

import argparse
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_REQUEST_TIMEOUT_SECONDS = 60
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_POLL_TIMEOUT_SECONDS = 180
DEFAULT_TURN_BUDGET = 4
DEFAULT_SEED = (
    "A municipal archivist finds the blackout ration rolls were altered to punish districts "
    "that backed the reform slate."
)
DEFAULT_TURN_INPUT = (
    "I force the emergency council to compare the sealed ration rolls in public before any "
    "clerk can revise them again."
)
DEFAULT_ADVISOR_QUESTION = "Is the chair stalling, or is someone else controlling the room?"


@dataclass(frozen=True)
class HttpProductSmokeConfig:
    base_url: str
    prompt_seed: str
    first_turn_input: str
    poll_interval_seconds: float
    poll_timeout_seconds: float
    request_timeout_seconds: float
    output_path: Path | None
    include_benchmark_diagnostics: bool
    turn_budget: int = DEFAULT_TURN_BUDGET
    advisor_question: str = DEFAULT_ADVISOR_QUESTION


def parse_args(argv: list[str] | None = None) -> HttpProductSmokeConfig:
    parser = argparse.ArgumentParser(description="Run a live HTTP smoke test against the current narrative core.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--prompt-seed", default=DEFAULT_SEED)
    parser.add_argument("--first-turn-input", default=DEFAULT_TURN_INPUT)
    parser.add_argument("--turn-budget", type=int, default=DEFAULT_TURN_BUDGET)
    parser.add_argument("--advisor-question", default=DEFAULT_ADVISOR_QUESTION)
    parser.add_argument("--poll-interval-seconds", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--poll-timeout-seconds", type=float, default=DEFAULT_POLL_TIMEOUT_SECONDS)
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--output-path")
    parser.add_argument(
        "--include-benchmark-diagnostics",
        action="store_true",
        help="Accepted for backwards compatibility; the current narrative core has no benchmark endpoint.",
    )
    args = parser.parse_args(argv)
    return HttpProductSmokeConfig(
        base_url=args.base_url.rstrip("/"),
        prompt_seed=str(args.prompt_seed),
        first_turn_input=str(args.first_turn_input),
        poll_interval_seconds=max(float(args.poll_interval_seconds), 0.05),
        poll_timeout_seconds=max(float(args.poll_timeout_seconds), 1.0),
        request_timeout_seconds=max(float(args.request_timeout_seconds), 1.0),
        output_path=Path(args.output_path).expanduser().resolve() if args.output_path else None,
        include_benchmark_diagnostics=bool(args.include_benchmark_diagnostics),
        turn_budget=max(4, min(int(args.turn_budget), 12)),
        advisor_question=str(args.advisor_question),
    )


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"request failed with status {response.status_code}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
    return f"request failed with status {response.status_code}"


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    request_timeout_seconds: float,
    **kwargs: Any,
) -> tuple[dict[str, Any], float]:
    started_at = time.perf_counter()
    response = session.request(method, url, timeout=request_timeout_seconds, **kwargs)
    elapsed_seconds = round(time.perf_counter() - started_at, 3)
    if not response.ok:
        raise RuntimeError(f"{method} {url}: {_error_message(response)}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {url}: expected JSON object payload")
    return payload, elapsed_seconds


def _authenticate_session(
    session: requests.Session,
    config: HttpProductSmokeConfig,
) -> dict[str, Any]:
    payload, _elapsed = _request_json(
        session,
        "POST",
        f"{config.base_url}/auth/login",
        request_timeout_seconds=config.request_timeout_seconds,
        json={"username": f"smoke_{secrets.token_hex(5)}"},
    )
    if not payload.get("authenticated"):
        raise RuntimeError("smoke auth login did not return an authenticated session")
    return payload


def _stage_timings_summary(diagnostics: dict[str, Any] | None) -> list[dict[str, Any]]:
    if diagnostics is None:
        return []
    rows: list[dict[str, Any]] = []
    for item in list(diagnostics.get("stage_timings") or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "stage": item.get("stage"),
                "elapsed_ms": item.get("elapsed_ms"),
            }
        )
    return rows


def _advance_turn(
    session: requests.Session,
    config: HttpProductSmokeConfig,
    *,
    session_id: str,
    turn_number: int,
) -> tuple[dict[str, Any], float]:
    if turn_number == 1:
        body: dict[str, Any] = {
            "free_input": config.first_turn_input,
            "diary": "Keep the evidence visible and the room accountable.",
        }
    elif turn_number == config.turn_budget:
        body = {
            "free_input": "I keep the record public and ask every witness to confirm the timeline."
        }
    else:
        body = {"chosen_option_index": 0}
    return _request_json(
        session,
        "POST",
        f"{config.base_url}/narrative/sessions/{session_id}/story/turns",
        request_timeout_seconds=max(config.request_timeout_seconds, 120.0),
        json=body,
    )


def run_http_product_smoke(config: HttpProductSmokeConfig) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "base_url": config.base_url,
        "prompt_seed": config.prompt_seed,
        "first_turn_input": config.first_turn_input,
        "ok": False,
        "steps": {},
        "contracts": {},
        "ids": {},
        "narrative": {},
        "benchmark": {},
    }
    with requests.Session() as session:
        health_payload, health_elapsed = _request_json(
            session,
            "GET",
            f"{config.base_url}/health",
            request_timeout_seconds=config.request_timeout_seconds,
        )
        summary["steps"]["health"] = {"elapsed_seconds": health_elapsed, "status": health_payload.get("status")}
        auth_payload = _authenticate_session(session, config)
        summary["steps"]["auth"] = {"authenticated": bool(auth_payload.get("authenticated"))}
        summary["contracts"]["auth_user_present"] = isinstance(auth_payload.get("user"), dict)

        create_payload, create_elapsed = _request_json(
            session,
            "POST",
            f"{config.base_url}/narrative/templates",
            request_timeout_seconds=max(config.request_timeout_seconds, 120.0),
            json={
                "seed": config.prompt_seed,
                "visibility": "public",
                "turn_budget": config.turn_budget,
                "difficulty": "story",
                "language": "en",
            },
        )
        template = dict(create_payload.get("template") or {})
        owner_session = dict(create_payload.get("session") or {})
        opening = dict(create_payload.get("opening") or {})
        template_id = str(template["template_id"])
        summary["ids"]["template_id"] = template_id
        summary["ids"]["owner_session_id"] = owner_session.get("session_id")
        summary["steps"]["create_template"] = {"elapsed_seconds": create_elapsed}
        summary["contracts"]["template_language_en"] = template.get("language") == "en"
        summary["contracts"]["opening_has_options"] = bool(opening.get("options"))
        summary["contracts"]["template_has_role_cards"] = bool(template.get("player_role_options"))

        detail_payload, detail_elapsed = _request_json(
            session,
            "GET",
            f"{config.base_url}/narrative/templates/{template_id}",
            request_timeout_seconds=config.request_timeout_seconds,
        )
        summary["steps"]["template_detail"] = {"elapsed_seconds": detail_elapsed}
        summary["contracts"]["detail_matches_template"] = detail_payload.get("template_id") == template_id

        fork_payload, fork_elapsed = _request_json(
            session,
            "POST",
            f"{config.base_url}/narrative/templates/{template_id}/sessions",
            request_timeout_seconds=config.request_timeout_seconds,
            json={"turn_budget": config.turn_budget, "difficulty": "story", "player_role_index": 1},
        )
        fork_session = dict(fork_payload.get("session") or {})
        session_id = str(fork_session["session_id"])
        summary["ids"]["session_id"] = session_id
        summary["steps"]["start_session"] = {"elapsed_seconds": fork_elapsed}
        summary["contracts"]["fork_keeps_template_id"] = fork_session.get("template_id") == template_id
        summary["contracts"]["fork_has_role"] = isinstance(fork_session.get("player_role"), dict)

        for turn_number in range(1, config.turn_budget + 1):
            turn_payload, turn_elapsed = _advance_turn(
                session,
                config,
                session_id=session_id,
                turn_number=turn_number,
            )
            summary["steps"][f"turn_{turn_number}"] = {"elapsed_seconds": turn_elapsed}
            summary["narrative"][f"turn_{turn_number}_complete"] = bool(turn_payload.get("is_complete"))
            if turn_number == 2:
                advisor_payload, advisor_elapsed = _request_json(
                    session,
                    "POST",
                    f"{config.base_url}/narrative/sessions/{session_id}/advisor",
                    request_timeout_seconds=max(config.request_timeout_seconds, 120.0),
                    json={"question": config.advisor_question},
                )
                advisor_message = dict(advisor_payload.get("advisor_message") or {})
                summary["steps"]["advisor"] = {"elapsed_seconds": advisor_elapsed}
                summary["contracts"]["advisor_replied"] = bool(advisor_message.get("content"))
            if turn_number == config.turn_budget:
                summary["contracts"]["final_turn_completed"] = bool(turn_payload.get("is_complete"))
                summary["contracts"]["final_turn_has_ending"] = isinstance(turn_payload.get("ending"), dict)

        history_payload, history_elapsed = _request_json(
            session,
            "GET",
            f"{config.base_url}/narrative/sessions/{session_id}/story",
            request_timeout_seconds=config.request_timeout_seconds,
        )
        summary["steps"]["history"] = {"elapsed_seconds": history_elapsed}
        history_message_count = len(list(history_payload.get("messages") or []))
        summary["narrative"]["history_message_count"] = history_message_count
        summary["contracts"]["history_has_completed_run"] = history_message_count >= config.turn_budget * 2 + 1

        ending_payload, ending_elapsed = _request_json(
            session,
            "GET",
            f"{config.base_url}/narrative/sessions/{session_id}/ending",
            request_timeout_seconds=config.request_timeout_seconds,
        )
        summary["steps"]["ending"] = {"elapsed_seconds": ending_elapsed}
        summary["contracts"]["ending_persisted"] = bool(ending_payload.get("label"))

        replay_payload, replay_elapsed = _request_json(
            session,
            "GET",
            f"{config.base_url}/narrative/sessions/{session_id}/replay",
            request_timeout_seconds=config.request_timeout_seconds,
        )
        summary["steps"]["replay"] = {"elapsed_seconds": replay_elapsed}
        summary["contracts"]["replay_has_template_id"] = replay_payload.get("template_id") == template_id
        summary["contracts"]["replay_completed"] = replay_payload.get("completed") is True
        summary["contracts"]["replay_has_advisor"] = len(list(replay_payload.get("advisor_messages") or [])) >= 2

        distribution_payload, distribution_elapsed = _request_json(
            session,
            "GET",
            f"{config.base_url}/narrative/templates/{template_id}/ending-distribution",
            request_timeout_seconds=config.request_timeout_seconds,
        )
        summary["steps"]["ending_distribution"] = {"elapsed_seconds": distribution_elapsed}
        summary["contracts"]["distribution_counts_completed_run"] = (
            int(distribution_payload.get("total_completed") or 0) >= 1
        )

        if config.include_benchmark_diagnostics:
            summary["benchmark"] = {
                "available": False,
                "reason": "The current narrative core does not expose benchmark diagnostics endpoints.",
            }

    failed = [name for name, ok in summary["contracts"].items() if not ok]
    if failed:
        summary["failed_contracts"] = failed
        raise RuntimeError(f"HTTP narrative smoke failed contracts: {', '.join(failed)}")
    summary["ok"] = True
    return summary


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    payload = run_http_product_smoke(config)
    if config.output_path is not None:
        write_output(config.output_path, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
