from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from random import Random
from typing import Any
from urllib.parse import urlparse

import requests

from rpg_backend.author.metrics import estimate_token_cost, summarize_cache_metrics
from rpg_backend.config import Settings, get_settings
from rpg_backend.responses_transport import ResponsesJSONTransport, build_openai_client
from tools.play_benchmarks.story_seed_factory import GeneratedStorySeed, build_story_seed_batch

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "benchmarks"
TURN_AGENT_MAX_OUTPUT_TOKENS = 260
REPORT_AGENT_MAX_OUTPUT_TOKENS = 420
DEFAULT_REQUEST_TIMEOUT_SECONDS = 180
DEFAULT_CONNECT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class AgentPersona:
    persona_id: str
    label: str
    turn_style: str
    decision_lens: str
    report_lens: str


PERSONAS: tuple[AgentPersona, ...] = (
    AgentPersona(
        persona_id="assertive_operator",
        label="Assertive Operator",
        turn_style="Push conflicts into the open and force clear commitments in emotionally volatile scenes.",
        decision_lens="Prioritize leverage, confrontation, and fast route shifts over slow compromise.",
        report_lens="Judge whether aggressive escalation produced coherent relationship consequences and visible stakes.",
    ),
    AgentPersona(
        persona_id="coalition_builder",
        label="Coalition Builder",
        turn_style="Repair trust fractures, stabilize alliances, and keep multi-party coordination alive under pressure.",
        decision_lens="Prefer durable alignment and negotiated route control over dramatic but brittle spikes.",
        report_lens="Judge whether reconciliation and alliance maintenance remain playable without flattening drama.",
    ),
    AgentPersona(
        persona_id="evidence_archivist",
        label="Evidence Archivist",
        turn_style="Lock facts, preserve receipts, and use verified details to corner hidden motives.",
        decision_lens="Prioritize auditable evidence trails and institutional memory over impulsive emotional bets.",
        report_lens="Judge whether evidence-first play reliably unlocks secrets and forces accountable consequences.",
    ),
    AgentPersona(
        persona_id="resource_broker",
        label="Resource Broker",
        turn_style="Control scarce access, gate key resources, and trade relief for strategic concessions.",
        decision_lens="Exploit bottlenecks and exchange leverage to shape alignment, loyalty, and route lock.",
        report_lens="Judge whether resource control creates meaningful pressure, differentiated responses, and payoff.",
    ),
    AgentPersona(
        persona_id="legitimacy_guardian",
        label="Legitimacy Guardian",
        turn_style="Protect mandate clarity, expose procedural abuse, and push contested choices into formal settlement.",
        decision_lens="Prioritize enforceable legitimacy and clean adjudication when authority signals are unstable.",
        report_lens="Judge whether mandate-focused play can force settlement without collapsing narrative coherence.",
    ),
)


@dataclass(frozen=True)
class LiveApiPlaytestConfig:
    base_url: str
    output_dir: Path
    label: str | None
    launch_server: bool
    session_ttl_seconds: int
    max_turns: int
    seed: int | None
    story_count: int
    phase_id: str | None
    seed_set_id: str | None
    arm: str
    baseline_artifact: Path | None


def parse_args(argv: list[str] | None = None) -> LiveApiPlaytestConfig:
    parser = argparse.ArgumentParser(description="Run live author->publish->play benchmark against the HTTP API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--label")
    parser.add_argument("--launch-server", action="store_true")
    parser.add_argument("--session-ttl-seconds", type=int, default=3600)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--story-count", type=int, default=5)
    parser.add_argument("--phase-id")
    parser.add_argument("--seed-set-id")
    parser.add_argument("--arm", choices=("baseline", "candidate"), default="candidate")
    parser.add_argument("--baseline-artifact")
    args = parser.parse_args(argv)
    return LiveApiPlaytestConfig(
        base_url=args.base_url.rstrip("/"),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        label=args.label,
        launch_server=bool(args.launch_server),
        session_ttl_seconds=max(int(args.session_ttl_seconds), 60),
        max_turns=max(int(args.max_turns), 1),
        seed=args.seed,
        story_count=max(int(args.story_count), 1),
        phase_id=args.phase_id,
        seed_set_id=args.seed_set_id,
        arm=args.arm,
        baseline_artifact=Path(args.baseline_artifact).expanduser().resolve() if args.baseline_artifact else None,
    )


def _read_error_message(response: requests.Response) -> str:
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
    timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> tuple[dict[str, Any], float]:
    started_at = time.perf_counter()
    response = session.request(
        method,
        url,
        timeout=(DEFAULT_CONNECT_TIMEOUT_SECONDS, timeout_seconds),
        **kwargs,
    )
    elapsed_seconds = round(time.perf_counter() - started_at, 3)
    if not response.ok:
        raise RuntimeError(f"{method} {url}: {_read_error_message(response)}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {url}: expected JSON object payload")
    return payload, elapsed_seconds


def _authenticate_session(session: requests.Session, base_url: str, *, label: str) -> dict[str, Any]:
    suffix = secrets.token_hex(6)
    email = f"{label}-{suffix}@bench.local"
    payload = {
        "display_name": label.replace("-", " ").title(),
        "email": email,
        "password": "BenchPass123!",
    }
    response = session.post(
        f"{base_url}/auth/register",
        json=payload,
        timeout=(DEFAULT_CONNECT_TIMEOUT_SECONDS, DEFAULT_REQUEST_TIMEOUT_SECONDS),
    )
    if not response.ok:
        raise RuntimeError(f"POST {base_url}/auth/register: {_read_error_message(response)}")
    body = response.json()
    if not isinstance(body, dict) or not body.get("authenticated"):
        raise RuntimeError("benchmark auth registration did not return an authenticated session")
    return body


def _parse_sse_event(block: str) -> dict[str, Any] | None:
    event_id = 0
    event_name = "message"
    data_lines: list[str] = []
    for line in block.splitlines():
        if not line or line.startswith(":"):
            continue
        if line.startswith("id:"):
            event_id = int(line[3:].strip() or 0)
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    return {
        "id": event_id,
        "event": event_name,
        "data": json.loads("\n".join(data_lines)),
    }


def _stream_author_job_to_terminal(session: requests.Session, base_url: str, job_id: str) -> dict[str, Any]:
    url = f"{base_url}/author/jobs/{job_id}/events"
    started_at = time.perf_counter()
    events: list[dict[str, Any]] = []
    response = session.get(
        url,
        headers={"Accept": "text/event-stream"},
        stream=True,
        timeout=(DEFAULT_CONNECT_TIMEOUT_SECONDS, 600),
    )
    if not response.ok:
        raise RuntimeError(f"GET {url}: {_read_error_message(response)}")
    try:
        buffer: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            line = raw_line or ""
            if line == "":
                event = _parse_sse_event("\n".join(buffer))
                buffer = []
                if event is None:
                    continue
                events.append(event)
                if event["event"] in {"job_completed", "job_failed"}:
                    break
                continue
            buffer.append(line)
        if buffer:
            trailing = _parse_sse_event("\n".join(buffer))
            if trailing is not None:
                events.append(trailing)
    finally:
        response.close()
    return {
        "events": events,
        "stream_elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "terminal_event": events[-1] if events else None,
    }


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(ceil(q * len(ordered)) - 1, 0)
    return ordered[min(index, len(ordered) - 1)]


def _session_feedback_metrics(turns: list[dict[str, Any]]) -> dict[str, int]:
    distinct_axes = {
        axis_id
        for turn in turns
        for axis_id, value in dict((turn.get("feedback") or {}).get("last_turn_axis_deltas") or {}).items()
        if int(value) != 0
    }
    distinct_stances = {
        stance_id
        for turn in turns
        for stance_id, value in dict((turn.get("feedback") or {}).get("last_turn_stance_deltas") or {}).items()
        if int(value) != 0
    }
    distinct_consequences = {
        consequence
        for turn in turns
        for consequence in list((turn.get("feedback") or {}).get("last_turn_consequences") or [])
        if isinstance(consequence, str) and consequence.strip()
    }
    nonzero_feedback_turns = sum(
        1
        for turn in turns
        if any(int(value) != 0 for value in dict((turn.get("feedback") or {}).get("last_turn_axis_deltas") or {}).values())
        or any(int(value) != 0 for value in dict((turn.get("feedback") or {}).get("last_turn_stance_deltas") or {}).values())
    )
    return {
        "distinct_axis_count": len(distinct_axes),
        "distinct_stance_count": len(distinct_stances),
        "distinct_consequence_count": len(distinct_consequences),
        "nonzero_feedback_turns": nonzero_feedback_turns,
    }


def _normalize_agent_report(
    *,
    report: dict[str, Any],
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = dict(report)
    ratings = dict(normalized.get("ratings") or {})
    if "suggested_action_relevance" not in ratings and "suggested_action_coherence" in ratings:
        ratings["suggested_action_relevance"] = ratings["suggested_action_coherence"]
    ratings.setdefault("narration_coherence", 3)
    ratings.setdefault("suggested_action_relevance", 3)
    ratings.setdefault("state_feedback_credibility", 3)
    ratings.setdefault("ending_satisfaction", 3)
    ratings.setdefault("overall_player_feel", 3)
    ratings.setdefault("content_richness", 3)
    ratings.setdefault("state_feedback_distinctness", ratings.get("state_feedback_credibility", 3))
    ratings.setdefault("protagonist_identity_clarity", 3)
    normalized["ratings"] = ratings
    flags = [
        flag
        for flag in list(normalized.get("flags") or [])
        if flag
        in {
            "flat_state_feedback",
            "suggestion_template_drift",
            "ending_feels_unearned",
            "narration_does_not_pay_off_state",
            "player_identity_confusion",
            "templated_opening",
        }
    ]
    metrics = _session_feedback_metrics(turns)
    distinctness = int(ratings.get("state_feedback_distinctness") or 0)
    credibility = int(ratings.get("state_feedback_credibility") or 0)
    flat_supported = (
        metrics["distinct_axis_count"] <= 1
        and metrics["distinct_stance_count"] <= 1
        and metrics["distinct_consequence_count"] <= 2
        and metrics["nonzero_feedback_turns"] <= 2
        and distinctness <= 3
        and credibility <= 3
    )
    if "flat_state_feedback" in flags and not flat_supported:
        flags = [flag for flag in flags if flag != "flat_state_feedback"]
    if "flat_state_feedback" not in flags and flat_supported:
        flags.append("flat_state_feedback")
    normalized["flags"] = flags
    normalized["best_moment"] = str(normalized.get("best_moment") or "No clear peak moment reported.")
    normalized["verdict"] = str(normalized.get("verdict") or normalized.get("player_feel_verdict") or "Playable but needs closer review.")
    if "player_feel_verdict" in normalized:
        normalized.pop("player_feel_verdict", None)
    return normalized


class _PlaytestAgentError(RuntimeError):
    pass


class PlaytestAgentClient:
    def __init__(self, persona: AgentPersona, settings: Settings | None = None, *, provider: str = "primary") -> None:
        self.persona = persona
        self._settings = settings or get_settings()
        resolved_provider = "helper" if provider == "helper" else "primary"
        if resolved_provider == "helper":
            base_url = self._settings.resolved_helper_responses_base_url()
            api_key = self._settings.resolved_helper_responses_api_key()
            api_keys = self._settings.helper_responses_api_key_pool()
            model = self._settings.resolved_helper_responses_model()
            use_session_cache = self._settings.resolved_helper_responses_use_session_cache()
            missing_message = (
                "Either APP_HELPER_RESPONSES_BASE_URL / APP_HELPER_RESPONSES_API_KEY / APP_HELPER_RESPONSES_MODEL "
                "or legacy APP_HELPER_GATEWAY_BASE_URL / APP_HELPER_GATEWAY_API_KEY / APP_HELPER_GATEWAY_MODEL "
                "are required for helper benchmark agents"
            )
        else:
            base_url = self._settings.resolved_play_responses_base_url()
            api_key = self._settings.resolved_play_responses_api_key()
            api_keys = self._settings.play_responses_api_key_pool()
            model = self._settings.resolved_play_responses_model()
            use_session_cache = self._settings.resolved_play_responses_use_session_cache()
            missing_message = (
                "Either APP_RESPONSES_PLAY_BASE_URL / APP_RESPONSES_PLAY_API_KEY / APP_RESPONSES_PLAY_MODEL "
                "(or generic APP_RESPONSES_BASE_URL / APP_RESPONSES_API_KEY / APP_RESPONSES_MODEL), "
                "or legacy APP_GATEWAY_PLAY_BASE_URL / APP_GATEWAY_PLAY_API_KEY / APP_GATEWAY_PLAY_MODEL "
                "(or APP_GATEWAY_BASE_URL / APP_GATEWAY_API_KEY / APP_GATEWAY_PLAY_MODEL / APP_GATEWAY_MODEL) are required for benchmark agents"
            )
        if not base_url or not api_key or not model:
            raise _PlaytestAgentError(missing_message)
        self.call_trace: list[dict[str, Any]] = []
        self._previous_response_id: str | None = None
        self._provider = resolved_provider
        self._transport = ResponsesJSONTransport(
            client=build_openai_client(
                base_url=base_url,
                api_key=api_key,
                api_keys=api_keys,
                use_session_cache=bool(use_session_cache),
                session_cache_header=self._settings.responses_session_cache_header,
                session_cache_value=self._settings.responses_session_cache_value,
            ),
            model=model,
            timeout_seconds=float(self._settings.responses_timeout_seconds),
            use_session_cache=bool(use_session_cache),
            temperature=0.45,
            enable_thinking=False,
            json_object_prompt_only=bool(self._settings.responses_json_object_prompt_only),
            provider_failed_code="playtest_agent_provider_failed",
            invalid_response_code="playtest_agent_invalid_response",
            invalid_json_code="playtest_agent_invalid_json",
            error_factory=self._error_factory,
            call_trace=self.call_trace,
        )

    @staticmethod
    def _error_factory(code: str, message: str, _status_code: int) -> _PlaytestAgentError:
        return _PlaytestAgentError(f"{code}: {message}")

    def _invoke_json(self, *, system_prompt: str, user_payload: dict[str, Any], max_output_tokens: int, operation_name: str) -> dict[str, Any]:
        response = self._transport.invoke_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_output_tokens=max_output_tokens,
            previous_response_id=self._previous_response_id,
            operation_name=operation_name,
        )
        self._previous_response_id = response.response_id or self._previous_response_id
        return response.payload

    @staticmethod
    def _fallback_turn(persona: AgentPersona, snapshot: dict[str, Any]) -> str:
        beat_title = str(snapshot.get("beat_title") or "the crisis")
        if persona.persona_id == "assertive_operator":
            return f"I force a direct public confrontation around {beat_title} and demand a clear commitment before anyone can stall again."
        if persona.persona_id == "coalition_builder":
            return f"I pull the most hostile sides into one room on {beat_title} and broker a short-term trust pact before the coalition breaks."
        if persona.persona_id == "evidence_archivist":
            return f"I lock the key receipts tied to {beat_title} and force each side to answer the same documented facts on record."
        if persona.persona_id == "resource_broker":
            return f"I control the chokepoint tied to {beat_title} and trade access only for explicit concessions from both camps."
        return f"I force a formal settlement step on {beat_title}, with clear accountability, before rumor takes over the route."

    def propose_turn(
        self,
        *,
        story_detail: dict[str, Any],
        snapshot: dict[str, Any],
        transcript: list[dict[str, str]],
    ) -> dict[str, Any]:
        suggested_actions = snapshot.get("suggested_actions") or []
        forbidden_verbatim = [str(item.get("prompt") or "").strip() for item in suggested_actions if item.get("prompt")]
        system_prompt = (
            "You are a benchmark playtest agent for an interactive fiction API. "
            "Stay in English. Output only JSON with one key: input_text. "
            "Write one concrete first-person player move, 1-2 sentences, grounded in the current scene. "
            "You may draw inspiration from suggested actions but must not copy their prompt text verbatim. "
            f"Persona: {self.persona.label}. "
            f"Turn style: {self.persona.turn_style} "
            f"Decision lens: {self.persona.decision_lens}"
        )
        payload = {
            "story_detail": story_detail,
            "session_snapshot": snapshot,
            "transcript": transcript[-8:],
            "forbidden_verbatim_prompts": forbidden_verbatim,
        }
        for attempt in range(2):
            try:
                response = self._invoke_json(
                    system_prompt=system_prompt,
                    user_payload=payload,
                    max_output_tokens=TURN_AGENT_MAX_OUTPUT_TOKENS,
                    operation_name=f"playtest_turn_{self.persona.persona_id}",
                )
                input_text = str(response.get("input_text") or "").strip()
                if input_text and input_text.casefold() not in {item.casefold() for item in forbidden_verbatim if item}:
                    return {"input_text": input_text, "source": "llm", "attempt": attempt + 1}
                payload["forbidden_verbatim_prompts"] = [*forbidden_verbatim, input_text]
            except _PlaytestAgentError:
                break
        return {
            "input_text": self._fallback_turn(self.persona, snapshot),
            "source": "fallback",
            "attempt": 0,
        }

    def build_report(
        self,
        *,
        story_detail: dict[str, Any],
        opening: str,
        turns: list[dict[str, Any]],
        final_snapshot: dict[str, Any],
        forced_stop: bool,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are grading an interactive fiction play session. Stay in English. "
            "Output only JSON with keys: ending_id, turn_count, ratings, flags, strongest_issue, best_moment, verdict. "
            "ratings must contain narration_coherence, suggested_action_relevance, state_feedback_credibility, ending_satisfaction, overall_player_feel, content_richness, state_feedback_distinctness, protagonist_identity_clarity as integers 1-5. "
            "flags must be a list chosen from flat_state_feedback, suggestion_template_drift, ending_feels_unearned, narration_does_not_pay_off_state, player_identity_confusion, templated_opening. "
            "Only use flat_state_feedback when most turns produce nearly identical visible feedback or almost no distinct state change. "
            f"Persona lens: {self.persona.report_lens}"
        )
        payload = {
            "story_detail": story_detail,
            "opening": opening,
            "turns": turns,
            "final_snapshot": final_snapshot,
            "forced_stop": forced_stop,
        }
        try:
            response = self._invoke_json(
                system_prompt=system_prompt,
                user_payload=payload,
                max_output_tokens=REPORT_AGENT_MAX_OUTPUT_TOKENS,
                operation_name=f"playtest_report_{self.persona.persona_id}",
            )
            ratings = dict(response.get("ratings") or {})
            flags = [
                flag
                for flag in list(response.get("flags") or [])
                if flag in {"flat_state_feedback", "player_identity_confusion", "templated_opening"}
            ]
            return _normalize_agent_report(
                report={
                "ending_id": str(response.get("ending_id") or ((final_snapshot.get("ending") or {}).get("ending_id") or "unfinished")),
                "turn_count": int(response.get("turn_count") or final_snapshot.get("turn_index") or len(turns)),
                "ratings": {
                    "narration_coherence": int(ratings.get("narration_coherence") or 3),
                    "suggested_action_relevance": int(ratings.get("suggested_action_relevance") or ratings.get("suggested_action_coherence") or 3),
                    "state_feedback_credibility": int(ratings.get("state_feedback_credibility") or 3),
                    "ending_satisfaction": int(ratings.get("ending_satisfaction") or ratings.get("overall_player_feel") or 3),
                    "overall_player_feel": int(ratings.get("overall_player_feel") or ratings.get("content_richness") or 3),
                    "protagonist_identity_clarity": int(ratings.get("protagonist_identity_clarity") or 3),
                    "content_richness": int(ratings.get("content_richness") or 3),
                    "state_feedback_distinctness": int(ratings.get("state_feedback_distinctness") or ratings.get("state_feedback_credibility") or 3),
                },
                "flags": flags,
                "strongest_issue": str(response.get("strongest_issue") or "No dominant issue reported."),
                "best_moment": str(response.get("best_moment") or "No clear peak moment reported."),
                "verdict": str(response.get("verdict") or response.get("player_feel_verdict") or "Playable but needs closer manual review."),
                "source": "llm",
                },
                turns=turns,
            )
        except _PlaytestAgentError:
            any_axis_change = any(
                any(int(value) != 0 for value in dict((turn.get("feedback") or {}).get("last_turn_axis_deltas") or {}).values())
                for turn in turns
            )
            any_stance_change = any(
                any(int(value) != 0 for value in dict((turn.get("feedback") or {}).get("last_turn_stance_deltas") or {}).values())
                for turn in turns
            )
            flags: list[str] = []
            if not any_axis_change and not any_stance_change:
                flags.append("flat_state_feedback")
            if "you" not in opening.casefold():
                flags.append("templated_opening")
            distinct_axes = len(
                {
                    axis_id
                    for turn in turns
                    for axis_id, value in dict((turn.get("feedback") or {}).get("last_turn_axis_deltas") or {}).items()
                    if int(value) != 0
                }
            )
            return _normalize_agent_report(
                report={
                "ending_id": str((final_snapshot.get("ending") or {}).get("ending_id") or "unfinished"),
                "turn_count": int(final_snapshot.get("turn_index") or len(turns)),
                "ratings": {
                    "narration_coherence": 3,
                    "suggested_action_relevance": 3,
                    "state_feedback_credibility": 2 if "flat_state_feedback" in flags else 3,
                    "ending_satisfaction": 3,
                    "overall_player_feel": 3,
                    "protagonist_identity_clarity": 3,
                    "content_richness": 3,
                    "state_feedback_distinctness": 2 if distinct_axes <= 1 else 3 if distinct_axes == 2 else 4,
                },
                "flags": flags,
                "strongest_issue": "Agent report fallback triggered; inspect transcript manually.",
                "best_moment": "No clear peak moment reported.",
                "verdict": "Benchmark report generation fell back to heuristics.",
                "source": "fallback",
                },
                turns=turns,
            )


def _create_story_preview(session: requests.Session, base_url: str, prompt_seed: str) -> tuple[dict[str, Any], float]:
    return _request_json(
        session,
        "POST",
        f"{base_url}/author/story-previews",
        json={"prompt_seed": prompt_seed},
    )


def _create_author_job(session: requests.Session, base_url: str, prompt_seed: str, preview_id: str) -> tuple[dict[str, Any], float]:
    return _request_json(
        session,
        "POST",
        f"{base_url}/author/jobs",
        json={"prompt_seed": prompt_seed, "preview_id": preview_id},
    )


def _get_author_job_result(session: requests.Session, base_url: str, job_id: str) -> tuple[dict[str, Any], float]:
    return _request_json(session, "GET", f"{base_url}/author/jobs/{job_id}/result")


def _publish_author_job(session: requests.Session, base_url: str, job_id: str) -> tuple[dict[str, Any], float]:
    return _request_json(
        session,
        "POST",
        f"{base_url}/author/jobs/{job_id}/publish",
        params={"visibility": "public"},
    )


def _get_story_detail(session: requests.Session, base_url: str, story_id: str) -> tuple[dict[str, Any], float]:
    return _request_json(session, "GET", f"{base_url}/stories/{story_id}")


def _get_author_diagnostics(session: requests.Session, base_url: str, job_id: str) -> tuple[dict[str, Any], float]:
    return _request_json(session, "GET", f"{base_url}/benchmark/author/jobs/{job_id}/diagnostics")


def _create_play_session(session: requests.Session, base_url: str, story_id: str) -> tuple[dict[str, Any], float]:
    return _request_json(session, "POST", f"{base_url}/play/sessions", json={"story_id": story_id})


def _submit_play_turn(session: requests.Session, base_url: str, session_id: str, input_text: str) -> tuple[dict[str, Any], float]:
    return _request_json(
        session,
        "POST",
        f"{base_url}/play/sessions/{session_id}/turns",
        json={"input_text": input_text},
    )


def _get_play_diagnostics(session: requests.Session, base_url: str, session_id: str) -> tuple[dict[str, Any], float]:
    return _request_json(session, "GET", f"{base_url}/benchmark/play/sessions/{session_id}/diagnostics")


def _is_transient_benchmark_error(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.casefold()
    transient_markers = (
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "expecting value",
        "expecting property name enclosed in double quotes",
        "provider_failed",
    )
    return any(marker in lowered for marker in transient_markers)


def _run_author_story(
    *,
    session: requests.Session,
    base_url: str,
    generated_seed: GeneratedStorySeed,
) -> dict[str, Any]:
    seed_started_at = time.perf_counter()
    story_payload: dict[str, Any] = {
        "bucket_id": generated_seed.bucket_id,
        "slug": generated_seed.slug,
        "seed": generated_seed.seed,
        "generated_at": generated_seed.generated_at,
        "job_id": None,
        "preview": None,
        "stream": None,
        "result": None,
        "diagnostics": None,
        "published_story": None,
        "story_detail": None,
        "error": None,
        "timings": {
            "author_total_elapsed_seconds": round(time.perf_counter() - seed_started_at, 3),
        },
    }
    try:
        _authenticate_session(session, base_url, label=f"author-{generated_seed.slug}")
        preview, preview_elapsed_seconds = _create_story_preview(session, base_url, generated_seed.seed)
        job, create_job_elapsed_seconds = _create_author_job(
            session,
            base_url,
            generated_seed.seed,
            str(preview["preview_id"]),
        )
        job_id = str(job["job_id"])
        stream_result = _stream_author_job_to_terminal(session, base_url, job_id)
        result, result_elapsed_seconds = _get_author_job_result(session, base_url, job_id)
        diagnostics, diagnostics_elapsed_seconds = _get_author_diagnostics(session, base_url, job_id)
        story_payload.update(
            {
                "job_id": job_id,
                "preview": preview,
                "stream": stream_result,
                "result": result,
                "diagnostics": diagnostics,
            }
        )
        story_payload["timings"].update(
            {
                "preview_elapsed_seconds": preview_elapsed_seconds,
                "create_job_elapsed_seconds": create_job_elapsed_seconds,
                "get_result_elapsed_seconds": result_elapsed_seconds,
                "get_diagnostics_elapsed_seconds": diagnostics_elapsed_seconds,
            }
        )
        if result.get("status") != "completed":
            story_payload["timings"]["author_total_elapsed_seconds"] = round(time.perf_counter() - seed_started_at, 3)
            return story_payload
        published_story, publish_elapsed_seconds = _publish_author_job(session, base_url, job_id)
        story_detail, detail_elapsed_seconds = _get_story_detail(session, base_url, str(published_story["story_id"]))
        story_payload["published_story"] = published_story
        story_payload["story_detail"] = story_detail
        story_payload["timings"]["publish_elapsed_seconds"] = publish_elapsed_seconds
        story_payload["timings"]["get_story_detail_elapsed_seconds"] = detail_elapsed_seconds
    except Exception as exc:  # noqa: BLE001
        story_payload["error"] = str(exc)
    story_payload["timings"]["author_total_elapsed_seconds"] = round(time.perf_counter() - seed_started_at, 3)
    return story_payload


def _run_persona_story_session(
    *,
    base_url: str,
    story_detail: dict[str, Any],
    persona: AgentPersona,
    max_turns: int,
) -> dict[str, Any]:
    session = requests.Session()
    try:
        _authenticate_session(
            session,
            base_url,
            label=f"{persona.persona_id}-{str(story_detail['story']['story_id'])[:8]}",
        )
        agent = PlaytestAgentClient(persona)
        story_id = str(story_detail["story"]["story_id"])
        created_snapshot, create_elapsed_seconds = _create_play_session(session, base_url, story_id)
        session_id = str(created_snapshot["session_id"])
        opening = str(created_snapshot.get("narration") or "")
        transcript = [{"speaker": "gm", "text": opening}]
        turn_records: list[dict[str, Any]] = []
        snapshot = created_snapshot
        forced_stop = False
        for _ in range(max_turns):
            if snapshot.get("status") != "active":
                break
            proposed = agent.propose_turn(
                story_detail=story_detail,
                snapshot=snapshot,
                transcript=transcript,
            )
            next_snapshot, submit_elapsed_seconds = _submit_play_turn(
                session,
                base_url,
                session_id,
                str(proposed["input_text"]),
            )
            narration = str(next_snapshot.get("narration") or "")
            transcript.append({"speaker": "player", "text": str(proposed["input_text"])})
            transcript.append({"speaker": "gm", "text": narration})
            turn_records.append(
                {
                    "input_text": str(proposed["input_text"]),
                    "agent_turn_source": proposed["source"],
                    "agent_turn_attempt": proposed["attempt"],
                    "submit_elapsed_seconds": submit_elapsed_seconds,
                    "status": next_snapshot.get("status"),
                    "beat_index": next_snapshot.get("beat_index"),
                    "beat_title": next_snapshot.get("beat_title"),
                    "narration": narration,
                    "feedback": next_snapshot.get("feedback"),
                    "suggested_actions": next_snapshot.get("suggested_actions"),
                    "state_bars": next_snapshot.get("state_bars"),
                    "ending": next_snapshot.get("ending"),
                    "narration_word_count": _word_count(narration),
                }
            )
            snapshot = next_snapshot
        if snapshot.get("status") == "active":
            forced_stop = True
        diagnostics, diagnostics_elapsed_seconds = _get_play_diagnostics(session, base_url, session_id)
        report = agent.build_report(
            story_detail=story_detail,
            opening=opening,
            turns=turn_records,
            final_snapshot=snapshot,
            forced_stop=forced_stop,
        )
        agent_cache_metrics = summarize_cache_metrics(agent.call_trace)
        agent_cost_estimate = estimate_token_cost(agent_cache_metrics)
        return {
            "persona_id": persona.persona_id,
            "persona_label": persona.label,
            "session_id": session_id,
            "create_elapsed_seconds": create_elapsed_seconds,
            "forced_stop": forced_stop,
            "opening": opening,
            "final_snapshot": snapshot,
            "turns": turn_records,
            "diagnostics": diagnostics,
            "diagnostics_elapsed_seconds": diagnostics_elapsed_seconds,
            "agent_report": report,
            "agent_cache_metrics": agent_cache_metrics.model_dump(mode="json"),
            "agent_cost_estimate": agent_cost_estimate.model_dump(mode="json") if agent_cost_estimate else None,
            "agent_call_trace": list(agent.call_trace),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "persona_id": persona.persona_id,
            "persona_label": persona.label,
            "session_id": None,
            "create_elapsed_seconds": 0.0,
            "forced_stop": False,
            "opening": "",
            "final_snapshot": {"status": "failed", "turn_index": 0, "ending": None},
            "turns": [],
            "diagnostics": {"summary": {}},
            "diagnostics_elapsed_seconds": 0.0,
            "agent_report": {
                "ending_id": "unfinished",
                "turn_count": 0,
                "ratings": {
                    "narration_coherence": 1,
                    "suggested_action_relevance": 1,
                    "state_feedback_credibility": 1,
                    "ending_satisfaction": 1,
                    "overall_player_feel": 1,
                    "protagonist_identity_clarity": 1,
                    "content_richness": 1,
                    "state_feedback_distinctness": 1,
                },
                "flags": [],
                "strongest_issue": "Benchmark agent session failed before completion.",
                "best_moment": "No clear peak moment reported.",
                "verdict": "Session execution failed.",
                "source": "fallback",
            },
            "agent_cache_metrics": summarize_cache_metrics([]).model_dump(mode="json"),
            "agent_cost_estimate": None,
            "agent_call_trace": [],
            "error": str(exc),
        }
    finally:
        session.close()


def _run_story_playtests(*, base_url: str, story_detail: dict[str, Any], max_turns: int) -> list[dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=len(PERSONAS)) as executor:
        futures = [
            executor.submit(
                _run_persona_story_session,
                base_url=base_url,
                story_detail=story_detail,
                persona=persona,
                max_turns=max_turns,
            )
            for persona in PERSONAS
        ]
    sessions = [future.result() for future in futures]
    recovered: list[dict[str, Any]] = []
    for session in sessions:
        if session.get("error") and _is_transient_benchmark_error(str(session.get("error"))):
            recovered.append(
                _run_persona_story_session(
                    base_url=base_url,
                    story_detail=story_detail,
                    persona=next(persona for persona in PERSONAS if persona.persona_id == session["persona_id"]),
                    max_turns=max_turns,
                )
            )
        else:
            recovered.append(session)
    return recovered


def _accumulate_distribution(total: dict[str, int], values: dict[str, int]) -> None:
    for key, value in values.items():
        total[str(key)] = total.get(str(key), 0) + int(value)


def _axis_diversity_per_session(sessions: list[dict[str, Any]]) -> float:
    values: list[int] = []
    for session in sessions:
        axis_ids = {
            axis_id
            for turn in session.get("turns", [])
            for axis_id, delta in dict((turn.get("feedback") or {}).get("last_turn_axis_deltas") or {}).items()
            if int(delta) != 0
        }
        if axis_ids:
            values.append(len(axis_ids))
    return round(statistics.mean(values), 3) if values else 0.0


def _stance_target_diversity_per_session(sessions: list[dict[str, Any]]) -> float:
    values: list[int] = []
    for session in sessions:
        stance_ids = {
            stance_id
            for turn in session.get("turns", [])
            for stance_id, delta in dict((turn.get("feedback") or {}).get("last_turn_stance_deltas") or {}).items()
            if int(delta) != 0
        }
        if stance_ids:
            values.append(len(stance_ids))
    return round(statistics.mean(values), 3) if values else 0.0


def _average_report_rating(sessions: list[dict[str, Any]], key: str) -> float:
    values = [
        int((session.get("agent_report", {}).get("ratings") or {}).get(key) or 0)
        for session in sessions
        if session.get("agent_report")
    ]
    return round(statistics.mean(values), 3) if values else 0.0


def _build_scorecard(stories: list[dict[str, Any]], *, target_story_count: int, personas_per_story: int) -> dict[str, Any]:
    author_successes = sum(1 for story in stories if story.get("published_story"))
    target_session_count = target_story_count * personas_per_story
    all_sessions = [session for story in stories for session in story.get("sessions", [])]
    completed_session_records = [
        session
        for session in all_sessions
        if session["final_snapshot"].get("status") == "completed" and not session["forced_stop"]
    ]
    completed_sessions = len(completed_session_records)
    expired_sessions = sum(1 for session in all_sessions if session["final_snapshot"].get("status") == "expired")
    create_session_seconds = [float(session["create_elapsed_seconds"]) for session in all_sessions]
    submit_turn_seconds = [
        float(turn["submit_elapsed_seconds"])
        for session in all_sessions
        for turn in session["turns"]
    ]
    total_turns = sum(len(session["turns"]) for session in all_sessions)
    render_fallback_turns = sum(
        int((session["diagnostics"].get("summary") or {}).get("render_fallback_turn_count") or 0)
        for session in all_sessions
    )
    heuristic_interpret_turns = sum(
        int((session["diagnostics"].get("summary") or {}).get("heuristic_interpret_turn_count") or 0)
        for session in all_sessions
    )
    flat_state_feedback_count = sum(
        1
        for session in all_sessions
        if "flat_state_feedback" in set(session["agent_report"].get("flags") or [])
    )
    player_identity_confusion_count = sum(
        1
        for session in all_sessions
        if "player_identity_confusion" in set(session["agent_report"].get("flags") or [])
    )
    templated_opening_count = sum(
        1
        for session in all_sessions
        if "templated_opening" in set(session["agent_report"].get("flags") or [])
    )
    narration_word_counts = [
        int(turn["narration_word_count"])
        for session in all_sessions
        for turn in session["turns"]
    ]
    richness_scores = [
        int((session["agent_report"].get("ratings") or {}).get("content_richness") or 0)
        for session in all_sessions
    ]
    judge_sources = [str((session.get("agent_report") or {}).get("source") or "fallback") for session in completed_session_records]
    judge_llm_count = sum(1 for source in judge_sources if source == "llm")
    judge_llm_salvage_partial_count = sum(1 for source in judge_sources if source in {"llm_salvage_partial", "salvage_partial"})
    judge_fallback_count = sum(1 for source in judge_sources if source == "fallback")
    agent_trace_covered_sessions = sum(
        1
        for session in completed_session_records
        if bool(list(session.get("agent_call_trace") or []))
    )
    play_trace_covered_sessions = sum(
        1
        for session in completed_session_records
        if bool(list((session.get("diagnostics") or {}).get("turn_traces") or []))
    )
    trace_failure_candidate_turns = 0
    trace_labeled_failure_turns = 0
    for session in completed_session_records:
        for trace in list((session.get("diagnostics") or {}).get("turn_traces") or []):
            if not isinstance(trace, dict):
                continue
            interpret_source = str(trace.get("interpret_source") or "").casefold()
            render_source = str(trace.get("render_source") or "").casefold()
            repaired_or_fallback = (
                interpret_source in {"heuristic", "fallback", "repair", "llm_repair"}
                or render_source in {"heuristic", "fallback", "repair", "llm_repair"}
                or bool(trace.get("render_narration_stage2_rescue"))
                or bool(trace.get("render_plan_stage2_rescue"))
                or bool(trace.get("ending_judge_stage2_rescue"))
                or bool(trace.get("pyrrhic_critic_stage2_rescue"))
            )
            if not repaired_or_fallback:
                continue
            trace_failure_candidate_turns += 1
            failure_reason = (
                trace.get("interpret_failure_reason")
                or trace.get("render_failure_reason")
                or trace.get("render_primary_failure_reason")
                or trace.get("render_quality_reason_before_repair")
                or trace.get("render_repair_failure_reason")
                or trace.get("ending_judge_failure_reason")
                or trace.get("pyrrhic_critic_failure_reason")
            )
            if isinstance(failure_reason, str) and failure_reason.strip():
                trace_labeled_failure_turns += 1
    author_total_estimated_cost_rmb = round(
        sum(
            float((((story.get("diagnostics") or {}).get("token_cost_estimate") or {}).get("estimated_total_cost_rmb") or 0.0))
            for story in stories
        ),
        6,
    )
    play_usage_totals: dict[str, int] = {}
    author_source_distribution: dict[str, int] = {}
    play_interpret_distribution: dict[str, int] = {}
    play_render_distribution: dict[str, int] = {}
    ending_distribution: dict[str, int] = {}
    for story in stories:
        source_summary = dict((story.get("diagnostics") or {}).get("source_summary") or {})
        for key, value in source_summary.items():
            author_source_distribution[f"{key}:{value}"] = author_source_distribution.get(f"{key}:{value}", 0) + 1
        for session in story.get("sessions", []):
            summary = dict(session["diagnostics"].get("summary") or {})
            _accumulate_distribution(play_usage_totals, dict(summary.get("usage_totals") or {}))
            _accumulate_distribution(play_interpret_distribution, dict(summary.get("interpret_source_distribution") or {}))
            _accumulate_distribution(play_render_distribution, dict(summary.get("render_source_distribution") or {}))
            ending_id = str((session["final_snapshot"].get("ending") or {}).get("ending_id") or "unfinished")
            ending_distribution[ending_id] = ending_distribution.get(ending_id, 0) + 1
    actuals = {
        "author_publish_success_rate": round(author_successes / target_story_count, 3) if target_story_count else 0.0,
        "play_completed_sessions": completed_sessions,
        "expired_sessions": expired_sessions,
        "median_create_session_seconds": round(statistics.median(create_session_seconds), 3) if create_session_seconds else 0.0,
        "p95_submit_turn_seconds": round(_percentile(submit_turn_seconds, 0.95), 3) if submit_turn_seconds else 0.0,
        "render_fallback_rate": round(render_fallback_turns / total_turns, 3) if total_turns else 0.0,
        "heuristic_interpret_rate": round(heuristic_interpret_turns / total_turns, 3) if total_turns else 0.0,
        "player_identity_confusion_flag_rate": round(player_identity_confusion_count / len(all_sessions), 3) if all_sessions else 0.0,
        "flat_state_feedback_flag_rate": round(flat_state_feedback_count / len(all_sessions), 3) if all_sessions else 0.0,
        "mean_narration_word_count_per_turn": round(statistics.mean(narration_word_counts), 3) if narration_word_counts else 0.0,
        "axis_diversity_per_session": _axis_diversity_per_session(all_sessions),
        "stance_target_diversity_per_session": _stance_target_diversity_per_session(all_sessions),
        "benchmark_agent_report_llm_rate": round(judge_llm_count / completed_sessions, 3) if completed_sessions else 0.0,
        "benchmark_agent_report_llm_salvage_partial_rate": round(judge_llm_salvage_partial_count / completed_sessions, 3) if completed_sessions else 0.0,
        "judge_nonfallback_rate": round((judge_llm_count + judge_llm_salvage_partial_count) / completed_sessions, 3) if completed_sessions else 0.0,
        "judge_fallback_rate": round(judge_fallback_count / completed_sessions, 3) if completed_sessions else 0.0,
        "agent_trace_coverage_rate": round(agent_trace_covered_sessions / completed_sessions, 3) if completed_sessions else 0.0,
        "play_trace_coverage_rate": round(play_trace_covered_sessions / completed_sessions, 3) if completed_sessions else 0.0,
        "trace_labeled_failure_rate": round(trace_labeled_failure_turns / trace_failure_candidate_turns, 3) if trace_failure_candidate_turns else 0.0,
        "state_feedback_distinctness": round(
            statistics.mean(
                [
                    int((session["agent_report"].get("ratings") or {}).get("state_feedback_distinctness") or 0)
                    for session in all_sessions
                    if session.get("agent_report")
                ]
            ),
            3,
        ) if all_sessions else 0.0,
    }
    gates = [
        {"metric": "author_publish_success_rate", "actual": actuals["author_publish_success_rate"], "threshold": 1.0, "operator": ">=", "passed": actuals["author_publish_success_rate"] >= 1.0},
        {
            "metric": "play_completed_sessions",
            "actual": actuals["play_completed_sessions"],
            "threshold": target_session_count,
            "operator": ">=",
            "passed": actuals["play_completed_sessions"] >= target_session_count,
        },
        {"metric": "expired_sessions", "actual": actuals["expired_sessions"], "threshold": 0, "operator": "<=", "passed": actuals["expired_sessions"] <= 0},
        {"metric": "median_create_session_seconds", "actual": actuals["median_create_session_seconds"], "threshold": 5.0, "operator": "<=", "passed": actuals["median_create_session_seconds"] <= 5.0},
        {"metric": "p95_submit_turn_seconds", "actual": actuals["p95_submit_turn_seconds"], "threshold": 25.0, "operator": "<=", "passed": actuals["p95_submit_turn_seconds"] <= 25.0},
        {"metric": "render_fallback_rate", "actual": actuals["render_fallback_rate"], "threshold": 0.35, "operator": "<=", "passed": actuals["render_fallback_rate"] <= 0.35},
        {"metric": "heuristic_interpret_rate", "actual": actuals["heuristic_interpret_rate"], "threshold": 0.35, "operator": "<=", "passed": actuals["heuristic_interpret_rate"] <= 0.35},
        {"metric": "player_identity_confusion_flag_rate", "actual": actuals["player_identity_confusion_flag_rate"], "threshold": 0.20, "operator": "<=", "passed": actuals["player_identity_confusion_flag_rate"] <= 0.20},
        {"metric": "flat_state_feedback_flag_rate", "actual": actuals["flat_state_feedback_flag_rate"], "threshold": 0.40, "operator": "<=", "passed": actuals["flat_state_feedback_flag_rate"] <= 0.40},
        {"metric": "mean_narration_word_count_per_turn", "actual": actuals["mean_narration_word_count_per_turn"], "threshold": 70.0, "operator": ">=", "passed": actuals["mean_narration_word_count_per_turn"] >= 70.0},
    ]
    return {
        "passed": all(gate["passed"] for gate in gates),
        "target_story_count": target_story_count,
        "target_session_count": target_session_count,
        "actuals": actuals,
        "gates": gates,
        "content_richness": {
            "average_rating": round(statistics.mean(richness_scores), 3) if richness_scores else 0.0,
            "report_count": len(richness_scores),
            "templated_opening_flag_count": templated_opening_count,
        },
        "subjective_summary": {
            "avg_narration_coherence": _average_report_rating(all_sessions, "narration_coherence"),
            "avg_suggested_action_relevance": _average_report_rating(all_sessions, "suggested_action_relevance"),
            "avg_state_feedback_credibility": _average_report_rating(all_sessions, "state_feedback_credibility"),
            "avg_ending_satisfaction": _average_report_rating(all_sessions, "ending_satisfaction"),
            "avg_overall_player_feel": _average_report_rating(all_sessions, "overall_player_feel"),
        },
        "cost_and_cache": {
            "author_total_estimated_cost_rmb": author_total_estimated_cost_rmb,
            "play_usage_totals": play_usage_totals,
        },
        "source_distribution": {
            "author": author_source_distribution,
            "play_interpret": play_interpret_distribution,
            "play_render": play_render_distribution,
        },
        "judge_trace_evaluation": {
            "completed_session_count": completed_sessions,
            "benchmark_agent_report_llm_rate": actuals["benchmark_agent_report_llm_rate"],
            "benchmark_agent_report_llm_salvage_partial_rate": actuals["benchmark_agent_report_llm_salvage_partial_rate"],
            "judge_nonfallback_rate": actuals["judge_nonfallback_rate"],
            "judge_fallback_rate": actuals["judge_fallback_rate"],
            "agent_trace_coverage_rate": actuals["agent_trace_coverage_rate"],
            "play_trace_coverage_rate": actuals["play_trace_coverage_rate"],
            "trace_failure_candidate_turns": trace_failure_candidate_turns,
            "trace_labeled_failure_turns": trace_labeled_failure_turns,
            "trace_labeled_failure_rate": actuals["trace_labeled_failure_rate"],
        },
        "ending_distribution": ending_distribution,
    }


def _distribution_shift(baseline: dict[str, int], candidate: dict[str, int]) -> dict[str, int]:
    keys = sorted({*baseline.keys(), *candidate.keys()})
    return {key: int(candidate.get(key, 0)) - int(baseline.get(key, 0)) for key in keys}


def compare_benchmark_payloads(
    *,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    phase_id: str | None,
    baseline_artifact: str | None,
) -> dict[str, Any]:
    baseline_scorecard = dict(baseline_payload.get("scorecard") or {})
    candidate_scorecard = dict(candidate_payload.get("scorecard") or {})
    baseline_actuals = dict(baseline_scorecard.get("actuals") or {})
    candidate_actuals = dict(candidate_scorecard.get("actuals") or {})
    deltas = {
        key: round(float(candidate_actuals.get(key, 0.0)) - float(baseline_actuals.get(key, 0.0)), 3)
        for key in sorted({*baseline_actuals.keys(), *candidate_actuals.keys()})
    }
    reliability_passed = (
        candidate_actuals.get("author_publish_success_rate", 0.0) >= 1.0
        and candidate_actuals.get("play_completed_sessions", 0) >= baseline_scorecard.get("target_session_count", 6)
        and candidate_actuals.get("expired_sessions", 0) <= 0
    )
    if phase_id == "stage1":
        phase_gates = [
            {"metric": "reliability_gate", "passed": reliability_passed},
            {"metric": "flat_state_feedback_flag_rate", "passed": candidate_actuals.get("flat_state_feedback_flag_rate", 1.0) < baseline_actuals.get("flat_state_feedback_flag_rate", 1.0)},
            {"metric": "axis_diversity_per_session", "passed": candidate_actuals.get("axis_diversity_per_session", 0.0) > baseline_actuals.get("axis_diversity_per_session", 0.0)},
            {"metric": "p95_submit_turn_seconds", "passed": candidate_actuals.get("p95_submit_turn_seconds", 999.0) <= min(float(baseline_actuals.get("p95_submit_turn_seconds", 25.0)) * 1.2, 25.0)},
            {"metric": "heuristic_interpret_rate", "passed": candidate_actuals.get("heuristic_interpret_rate", 1.0) <= float(baseline_actuals.get("heuristic_interpret_rate", 0.0)) + 0.05},
            {"metric": "render_fallback_rate", "passed": candidate_actuals.get("render_fallback_rate", 1.0) <= baseline_actuals.get("render_fallback_rate", 1.0)},
        ]
    elif phase_id == "stage2":
        phase_gates = [
            {"metric": "reliability_gate", "passed": reliability_passed},
            {"metric": "flat_state_feedback_flag_rate", "passed": candidate_actuals.get("flat_state_feedback_flag_rate", 1.0) <= 0.4},
            {"metric": "state_feedback_distinctness", "passed": candidate_actuals.get("state_feedback_distinctness", 0.0) > baseline_actuals.get("state_feedback_distinctness", 0.0)},
            {"metric": "mean_narration_word_count_per_turn", "passed": candidate_actuals.get("mean_narration_word_count_per_turn", 0.0) >= 70.0},
            {"metric": "player_identity_confusion_flag_rate", "passed": candidate_actuals.get("player_identity_confusion_flag_rate", 1.0) <= 0.2},
            {"metric": "render_fallback_rate", "passed": candidate_actuals.get("render_fallback_rate", 1.0) <= 0.35},
        ]
    else:
        phase_gates = [
            {"metric": "reliability_gate", "passed": reliability_passed},
        ]
    return {
        "phase_id": phase_id,
        "seed_set_id": candidate_payload.get("seed_set_id"),
        "baseline_artifact": baseline_artifact,
        "baseline_label": baseline_payload.get("label"),
        "candidate_label": candidate_payload.get("label"),
        "baseline_scorecard": baseline_scorecard,
        "candidate_scorecard": candidate_scorecard,
        "delta_actuals": deltas,
        "ending_distribution_shift": _distribution_shift(
            dict(baseline_scorecard.get("ending_distribution") or {}),
            dict(candidate_scorecard.get("ending_distribution") or {}),
        ),
        "phase_gates": phase_gates,
        "passed": all(bool(gate["passed"]) for gate in phase_gates),
    }


@contextmanager
def _managed_server(config: LiveApiPlaytestConfig, library_db_path: Path | None):
    if not config.launch_server:
        yield
        return
    if library_db_path is None:
        raise RuntimeError("library_db_path is required when --launch-server is used")
    parsed = urlparse(config.base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8010
    env = os.environ.copy()
    env["APP_STORY_LIBRARY_DB_PATH"] = str(library_db_path)
    env["APP_PLAY_SESSION_TTL_SECONDS"] = str(config.session_ttl_seconds)
    env["APP_ENABLE_BENCHMARK_API"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "rpg_backend.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("managed API server exited before becoming healthy")
            try:
                response = requests.get(f"{config.base_url}/health", timeout=1)
                if response.ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("managed API server did not become healthy in time")
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _runtime_config_snapshot(settings: Settings) -> dict[str, Any]:
    return {
        "runtime_profile": str(settings.runtime_profile or "").strip() or None,
        "author": {
            "base_url": settings.resolved_author_responses_base_url() or None,
            "model": settings.resolved_author_responses_model() or None,
        },
        "play": {
            "base_url": settings.resolved_play_responses_base_url() or None,
            "model": settings.resolved_play_responses_model() or None,
        },
        "helper": {
            "base_url": settings.resolved_helper_responses_base_url() or None,
            "model": settings.resolved_helper_responses_model() or None,
        },
    }


def run_live_api_playtest(config: LiveApiPlaytestConfig) -> dict[str, Any]:
    rng = Random(config.seed) if config.seed is not None else Random()
    generated_seeds = build_story_seed_batch(rng=rng, story_count=config.story_count)
    stories: list[dict[str, Any]] = []
    runtime_settings = get_settings()
    runtime_config = _runtime_config_snapshot(runtime_settings)
    with tempfile.TemporaryDirectory() as tmpdir:
        library_db_path = Path(tmpdir) / "stories.sqlite3" if config.launch_server else None
        with _managed_server(config, library_db_path):
            author_session = requests.Session()
            try:
                for generated_seed in generated_seeds:
                    story_record = _run_author_story(
                        session=author_session,
                        base_url=config.base_url,
                        generated_seed=generated_seed,
                    )
                    if story_record.get("error") and _is_transient_benchmark_error(str(story_record.get("error"))):
                        story_record = _run_author_story(
                            session=author_session,
                            base_url=config.base_url,
                            generated_seed=generated_seed,
                        )
                    if story_record.get("published_story") and story_record.get("story_detail"):
                        story_record["sessions"] = _run_story_playtests(
                            base_url=config.base_url,
                            story_detail=story_record["story_detail"],
                            max_turns=config.max_turns,
                        )
                    else:
                        story_record["sessions"] = []
                    stories.append(story_record)
            finally:
                author_session.close()
    return {
        "base_url": config.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "launch_server": config.launch_server,
        "label": config.label,
        "phase_id": config.phase_id,
        "seed_set_id": config.seed_set_id or (f"seed-{config.seed}" if config.seed is not None else None),
        "arm": config.arm,
        "baseline_artifact": str(config.baseline_artifact) if config.baseline_artifact else None,
        "personas": [persona.persona_id for persona in PERSONAS],
        "max_turns": config.max_turns,
        "story_count_requested": config.story_count,
        "story_count": len(generated_seeds),
        "stories": stories,
        "runtime_profile": runtime_config.get("runtime_profile"),
        "runtime_config": runtime_config,
        "scorecard": _build_scorecard(
            stories,
            target_story_count=len(generated_seeds),
            personas_per_story=len(PERSONAS),
        ),
    }


def write_artifacts(config: LiveApiPlaytestConfig, payload: dict[str, Any]) -> tuple[Path, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    label = config.label or "live_api_playtest"
    stem = f"{label}_{timestamp}"
    json_path = config.output_dir / f"{stem}.json"
    md_path = config.output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    scorecard = dict(payload.get("scorecard") or {})
    actuals = dict(scorecard.get("actuals") or {})
    subjective_summary = dict(scorecard.get("subjective_summary") or {})
    judge_trace = dict(scorecard.get("judge_trace_evaluation") or {})
    lines = [
        "# Live Author->Play Benchmark",
        "",
        f"- Base URL: `{payload['base_url']}`",
        f"- Runtime profile: `{payload.get('runtime_profile')}`",
        f"- Phase: `{payload.get('phase_id')}`",
        f"- Seed set: `{payload.get('seed_set_id')}`",
        f"- Arm: `{payload.get('arm')}`",
        f"- Story count: `{payload['story_count']}`",
        f"- Personas per story: `{len(payload.get('personas') or [])}`",
        f"- Overall pass: `{scorecard.get('passed')}`",
        "",
        "## Runtime Config",
        "",
    ]
    runtime_config = dict(payload.get("runtime_config") or {})
    for channel in ("author", "play", "helper"):
        channel_payload = dict(runtime_config.get(channel) or {})
        lines.append(
            f"- {channel}: base=`{channel_payload.get('base_url')}` model=`{channel_payload.get('model')}`"
        )
    lines.extend(
        [
            "",
        "## Scorecard",
        "",
        f"- Author publish success rate: `{actuals.get('author_publish_success_rate')}`",
        f"- Completed sessions: `{actuals.get('play_completed_sessions')}`",
        f"- Expired sessions: `{actuals.get('expired_sessions')}`",
        f"- Median create session seconds: `{actuals.get('median_create_session_seconds')}`",
        f"- P95 submit turn seconds: `{actuals.get('p95_submit_turn_seconds')}`",
        f"- Render fallback rate: `{actuals.get('render_fallback_rate')}`",
        f"- Heuristic interpret rate: `{actuals.get('heuristic_interpret_rate')}`",
        f"- Identity confusion flag rate: `{actuals.get('player_identity_confusion_flag_rate')}`",
        f"- Flat state feedback flag rate: `{actuals.get('flat_state_feedback_flag_rate')}`",
        f"- Mean narration words per turn: `{actuals.get('mean_narration_word_count_per_turn')}`",
        "",
        "## Judge + Trace Evaluation",
        "",
        f"- Session coverage: `{actuals.get('play_completed_sessions')}` / `{scorecard.get('target_session_count')}`",
        f"- Judge non-fallback rate: `{actuals.get('judge_nonfallback_rate')}`",
        f"- Judge fallback rate: `{actuals.get('judge_fallback_rate')}`",
        f"- Agent trace coverage rate: `{actuals.get('agent_trace_coverage_rate')}`",
        f"- Play trace coverage rate: `{actuals.get('play_trace_coverage_rate')}`",
        f"- Trace labeled failure rate: `{actuals.get('trace_labeled_failure_rate')}`",
        f"- Trace labeled failures: `{judge_trace.get('trace_labeled_failure_turns')}` / `{judge_trace.get('trace_failure_candidate_turns')}`",
        "",
        "## Subjective",
        "",
        f"- Avg narration coherence: `{subjective_summary.get('avg_narration_coherence')}`",
        f"- Avg suggested action relevance: `{subjective_summary.get('avg_suggested_action_relevance')}`",
        f"- Avg state feedback credibility: `{subjective_summary.get('avg_state_feedback_credibility')}`",
        f"- Avg ending satisfaction: `{subjective_summary.get('avg_ending_satisfaction')}`",
        f"- Avg overall player feel: `{subjective_summary.get('avg_overall_player_feel')}`",
        "",
        "## Stories",
        "",
        ]
    )
    for story in payload["stories"]:
        result = story.get("result") or {}
        published_story = story.get("published_story") or {}
        lines.extend(
            [
                f"### {story['slug']}",
                "",
                f"- Bucket: `{story['bucket_id']}`",
                f"- Seed: {story['seed']}",
                f"- Job: `{story['job_id']}` status=`{result.get('status')}`",
                f"- Published story: `{published_story.get('story_id')}` `{published_story.get('title')}`",
            ]
        )
        if story.get("error"):
            lines.append(f"- Error: `{story['error']}`")
        for session in story.get("sessions", []):
            lines.append(
                f"- `{session['persona_id']}` ending=`{(session['final_snapshot'].get('ending') or {}).get('ending_id', 'unfinished')}` "
                f"turns=`{session['final_snapshot'].get('turn_index')}` forced_stop=`{session['forced_stop']}` "
                f"richness=`{session['agent_report']['ratings']['content_richness']}`"
            )
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def write_compare_artifacts(config: LiveApiPlaytestConfig, compare_payload: dict[str, Any]) -> tuple[Path, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    label = config.label or "live_api_abcompare"
    phase = config.phase_id or "phase"
    stem = f"{label}_{phase}_compare_{timestamp}"
    json_path = config.output_dir / f"{stem}.json"
    md_path = config.output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(compare_payload, ensure_ascii=False, indent=2))
    lines = [
        "# Live Author->Play A/B Compare",
        "",
        f"- Phase: `{compare_payload.get('phase_id')}`",
        f"- Seed set: `{compare_payload.get('seed_set_id')}`",
        f"- Overall pass: `{compare_payload.get('passed')}`",
        "",
        "## Gates",
        "",
    ]
    for gate in compare_payload.get("phase_gates", []):
        lines.append(f"- `{gate['metric']}` passed=`{gate['passed']}`")
    lines.extend(
        [
            "",
            "## Deltas",
            "",
        ]
    )
    for key, value in dict(compare_payload.get("delta_actuals") or {}).items():
        lines.append(f"- `{key}` delta=`{value}`")
    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    payload = run_live_api_playtest(config)
    json_path, md_path = write_artifacts(config, payload)
    compare_json_path: str | None = None
    compare_md_path: str | None = None
    compare_passed: bool | None = None
    if config.baseline_artifact is not None:
        baseline_payload = json.loads(config.baseline_artifact.read_text())
        compare_payload = compare_benchmark_payloads(
            baseline_payload=baseline_payload,
            candidate_payload=payload,
            phase_id=config.phase_id,
            baseline_artifact=str(config.baseline_artifact),
        )
        compare_json, compare_md = write_compare_artifacts(config, compare_payload)
        compare_json_path = str(compare_json)
        compare_md_path = str(compare_md)
        compare_passed = bool(compare_payload.get("passed"))
    print(
        json.dumps(
            {
                "json": str(json_path),
                "markdown": str(md_path),
                "passed": bool((payload.get("scorecard") or {}).get("passed")),
                "compare_json": compare_json_path,
                "compare_markdown": compare_md_path,
                "compare_passed": compare_passed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
