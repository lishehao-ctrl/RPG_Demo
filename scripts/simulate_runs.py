#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from statistics import mean
from typing import Any

import httpx


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(method, url, json=json_body)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed: {response.status_code} {response.text}")
    if not response.text:
        return {}
    return response.json()


def _available_choices(choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    available = [choice for choice in choices if bool(choice.get("is_available", True))]
    return available if available else list(choices)


def _first_by_type(candidates: list[dict[str, Any]], choice_type: str) -> str | None:
    for choice in candidates:
        if str(choice.get("type") or "").lower() == choice_type:
            return str(choice["id"])
    return None


def _choose_choice_balanced(choices: list[dict[str, Any]], state_json: dict[str, Any]) -> str:
    candidates = _available_choices(choices)
    if not candidates:
        raise RuntimeError("no choices available on current node")

    energy = int((state_json or {}).get("energy", 0))
    money = int((state_json or {}).get("money", 0))
    knowledge = int((state_json or {}).get("knowledge", 0))
    affection = int((state_json or {}).get("affection", 0))

    # Balanced policy: recover first, then patch weak resources, then move forward.
    if energy < 30:
        target = _first_by_type(candidates, "rest")
        if target:
            return target
    if money < 40:
        target = _first_by_type(candidates, "work")
        if target:
            return target
    if knowledge < 10:
        target = _first_by_type(candidates, "study")
        if target:
            return target
    if affection < 8:
        target = _first_by_type(candidates, "date") or _first_by_type(candidates, "gift")
        if target:
            return target
    return str(candidates[0]["id"])


def _choose_choice_random(choices: list[dict[str, Any]], *, rng: random.Random) -> str:
    candidates = _available_choices(choices)
    if not candidates:
        raise RuntimeError("no choices available on current node")
    picked = rng.choice(candidates)
    return str(picked["id"])


def run_once(
    client: httpx.Client,
    *,
    backend_url: str,
    story_id: str,
    version: int | None,
    policy: str,
    rng: random.Random,
    max_local_steps: int = 80,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"story_id": story_id}
    if version is not None:
        payload["version"] = version

    session = _request(client, "POST", f"{backend_url}/sessions", json_body=payload)
    session_id = str(session["id"])

    step_count = 0
    fallback_steps = 0
    ending_id = None
    ending_outcome = None

    for _ in range(max_local_steps):
        state = _request(client, "GET", f"{backend_url}/sessions/{session_id}")
        current_node = state.get("current_node") or {}
        choices = current_node.get("choices") or []
        if not choices:
            break

        if policy == "balanced":
            choice_id = _choose_choice_balanced(choices, state.get("state_json") or {})
        elif policy == "random":
            choice_id = _choose_choice_random(choices, rng=rng)
        else:
            raise RuntimeError(f"unsupported policy: {policy}")

        step = _request(
            client,
            "POST",
            f"{backend_url}/sessions/{session_id}/step",
            json_body={"choice_id": choice_id},
        )
        step_count += 1
        if bool(step.get("fallback_used")):
            fallback_steps += 1

        if bool(step.get("run_ended", False)):
            ending_id = step.get("ending_id")
            ending_outcome = step.get("ending_outcome")
            break

    final_state = _request(client, "GET", f"{backend_url}/sessions/{session_id}")
    state_json = final_state.get("state_json") or {}
    run_state = state_json.get("run_state") or {}

    return {
        "session_id": session_id,
        "steps": step_count,
        "fallback_steps": fallback_steps,
        "ending_id": ending_id or run_state.get("ending_id"),
        "ending_outcome": ending_outcome or run_state.get("ending_outcome"),
        "final_state": {
            "energy": int(state_json.get("energy", 0)),
            "money": int(state_json.get("money", 0)),
            "knowledge": int(state_json.get("knowledge", 0)),
            "affection": int(state_json.get("affection", 0)),
            "day": int(state_json.get("day", 0)),
        },
        "triggered_events": list(run_state.get("triggered_event_ids") or []),
    }


def _rate(counter: Counter[str], key: str, total: int) -> float:
    if total <= 0:
        return 0.0
    return float(counter.get(key, 0)) / float(total)


def _build_policy_metrics(
    policy: str,
    *,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    ending_distribution = Counter(str(item.get("ending_id") or "none") for item in results)
    outcome_distribution = Counter(str(item.get("ending_outcome") or "none") for item in results)

    event_frequency: Counter[str] = Counter()
    event_total = 0
    for item in results:
        triggered = [str(event_id) for event_id in (item.get("triggered_events") or [])]
        event_total += len(triggered)
        for event_id in triggered:
            event_frequency[event_id] += 1

    step_values = [int(item.get("steps", 0)) for item in results]
    fallback_steps = sum(int(item.get("fallback_steps", 0)) for item in results)
    total_steps = sum(step_values)
    timeout_rate = _rate(ending_distribution, "__timeout__", len(results))

    return {
        "policy": policy,
        "runs": len(results),
        "ending_distribution": dict(ending_distribution),
        "ending_outcome_distribution": dict(outcome_distribution),
        "average_steps_to_end": round(mean(step_values), 2) if step_values else 0.0,
        "timeout_rate": round(timeout_rate, 4),
        "fallback_rate": round(float(fallback_steps) / float(total_steps), 4) if total_steps > 0 else 0.0,
        "event_frequency": dict(event_frequency),
        "events_per_run": round(float(event_total) / float(len(results)), 4) if results else 0.0,
    }


def _assert_playable_v1(*, metrics_by_policy: dict[str, dict[str, Any]], runs_min: int) -> list[str]:
    errors: list[str] = []

    def _assert_policy_present(policy: str) -> dict[str, Any] | None:
        metrics = metrics_by_policy.get(policy)
        if metrics is None:
            errors.append(f"missing policy results for {policy}")
            return None
        if int(metrics.get("runs", 0)) < runs_min:
            errors.append(f"{policy}: runs={metrics.get('runs')} is below assert minimum {runs_min}")
        return metrics

    balanced = _assert_policy_present("balanced")
    if balanced is not None:
        outcomes = Counter({str(k): int(v) for k, v in (balanced.get("ending_outcome_distribution") or {}).items()})
        total = int(balanced.get("runs", 0))
        success_rate = _rate(outcomes, "success", total)
        neutral_rate = _rate(outcomes, "neutral", total)
        fail_rate = _rate(outcomes, "fail", total)
        timeout_rate = float(balanced.get("timeout_rate", 0.0))
        avg_steps = float(balanced.get("average_steps_to_end", 0.0))
        events_per_run = float(balanced.get("events_per_run", 0.0))

        if not (0.40 <= success_rate <= 0.55):
            errors.append(f"balanced: success_rate={success_rate:.4f} outside [0.40, 0.55]")
        if not (0.30 <= neutral_rate <= 0.45):
            errors.append(f"balanced: neutral_rate={neutral_rate:.4f} outside [0.30, 0.45]")
        if not (0.10 <= fail_rate <= 0.20):
            errors.append(f"balanced: fail_rate={fail_rate:.4f} outside [0.10, 0.20]")
        if timeout_rate > 0.05:
            errors.append(f"balanced: timeout_rate={timeout_rate:.4f} exceeds 0.05")
        if not (14 <= avg_steps <= 22):
            errors.append(f"balanced: average_steps_to_end={avg_steps:.2f} outside [14, 22]")
        if events_per_run < 0.50:
            errors.append(f"balanced: events_per_run={events_per_run:.4f} below 0.50")

    random_metrics = _assert_policy_present("random")
    if random_metrics is not None:
        outcomes = Counter({str(k): int(v) for k, v in (random_metrics.get("ending_outcome_distribution") or {}).items()})
        total = int(random_metrics.get("runs", 0))
        success_rate = _rate(outcomes, "success", total)
        fail_rate = _rate(outcomes, "fail", total)
        timeout_rate = float(random_metrics.get("timeout_rate", 0.0))
        avg_steps = float(random_metrics.get("average_steps_to_end", 0.0))
        events_per_run = float(random_metrics.get("events_per_run", 0.0))

        if timeout_rate > 0.12:
            errors.append(f"random: timeout_rate={timeout_rate:.4f} exceeds 0.12")
        if success_rate < 0.08:
            errors.append(f"random: success_rate={success_rate:.4f} below 0.08")
        if fail_rate < 0.15:
            errors.append(f"random: fail_rate={fail_rate:.4f} below 0.15")
        if not (10 <= avg_steps <= 22):
            errors.append(f"random: average_steps_to_end={avg_steps:.2f} outside [10, 22]")
        if events_per_run < 0.40:
            errors.append(f"random: events_per_run={events_per_run:.4f} below 0.40")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic simulation runner for story sessions.")
    parser.add_argument("--story-id", required=True)
    parser.add_argument("--version", type=int, default=None)
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--policy", choices=["balanced", "random", "both"], default="both")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--assert-profile", choices=["playable_v1"], default=None)
    parser.add_argument("--assert-runs-min", type=int, default=200)
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/"))
    args = parser.parse_args()

    policies = ["balanced", "random"] if args.policy == "both" else [str(args.policy)]
    results_by_policy: dict[str, list[dict[str, Any]]] = {policy: [] for policy in policies}

    with httpx.Client(timeout=30.0) as client:
        for index, policy in enumerate(policies):
            rng = random.Random(int(args.seed) + (index * 1009))
            for _ in range(int(args.runs)):
                results_by_policy[policy].append(
                    run_once(
                        client,
                        backend_url=args.backend_url,
                        story_id=args.story_id,
                        version=args.version,
                        policy=policy,
                        rng=rng,
                    )
                )

    metrics_by_policy = {
        policy: _build_policy_metrics(policy, results=policy_results)
        for policy, policy_results in results_by_policy.items()
    }

    payload = {
        "story_id": args.story_id,
        "version": args.version,
        "seed": args.seed,
        "requested_runs_per_policy": int(args.runs),
        "policy": args.policy,
        "metrics": metrics_by_policy,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.assert_profile == "playable_v1":
        assertion_errors = _assert_playable_v1(
            metrics_by_policy=metrics_by_policy,
            runs_min=int(args.assert_runs_min),
        )
        if assertion_errors:
            for item in assertion_errors:
                print(f"ASSERTION_FAILED: {item}", file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
