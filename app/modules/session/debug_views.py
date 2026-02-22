from __future__ import annotations

import re
import uuid
from collections import Counter
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ActionLog, LLMUsageLog, Session as StorySession, SessionStepIdempotency

_TRACE_ERROR_KIND_RE = re.compile(r"(?:^|\|)\s*kind=([A-Z_]+)")
_TRACE_RAW_SNIPPET_RE = re.compile(r"(?:^|\|)\s*raw=([^|]+)")
_TRACE_TOKEN_REDACTION_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")


def _require_session(db: Session, session_id: uuid.UUID) -> StorySession:
    sess = db.get(StorySession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


def _phase_guess_for_llm_call(call: LLMUsageLog) -> str:
    if call.step_id is None:
        return "selection_phase_or_selector_repair"
    return "narrative_phase_or_narrative_repair"


def _sanitize_trace_raw_snippet(value: str | None, max_len: int = 200) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _TRACE_TOKEN_REDACTION_RE.sub("[REDACTED_KEY]", text)
    text = " ".join(text.split())
    text = text.replace("|", "/")
    return text[:max_len] if text else None


def _extract_trace_error_kind(error_message: str | None) -> str | None:
    text = str(error_message or "")
    match = _TRACE_ERROR_KIND_RE.search(text)
    if not match:
        return None
    value = str(match.group(1) or "").strip().upper()
    return value or None


def _extract_trace_raw_snippet(error_message: str | None) -> str | None:
    text = str(error_message or "")
    match = _TRACE_RAW_SNIPPET_RE.search(text)
    if not match:
        return None
    return _sanitize_trace_raw_snippet(match.group(1))


def _trace_error_prefix(error_message: str | None) -> str | None:
    text = str(error_message or "").strip()
    if not text:
        return None
    base = text.split("| kind=", 1)[0].strip()
    if not base:
        return None
    return base[:80]


def get_llm_trace(db: Session, session_id: uuid.UUID, limit: int = 50) -> dict:
    _require_session(db, session_id)
    if str(settings.env).lower() != "dev":
        raise HTTPException(status_code=404, detail={"code": "DEBUG_DISABLED"})

    bounded_limit = max(1, min(int(limit), 200))
    calls = db.execute(
        select(LLMUsageLog)
        .where(LLMUsageLog.session_id == session_id)
        .order_by(LLMUsageLog.created_at.desc(), LLMUsageLog.id.desc())
        .limit(bounded_limit)
    ).scalars().all()
    latest_idem = db.execute(
        select(SessionStepIdempotency)
        .where(SessionStepIdempotency.session_id == session_id)
        .order_by(SessionStepIdempotency.updated_at.desc(), SessionStepIdempotency.created_at.desc())
    ).scalars().first()

    providers_counter: Counter[str] = Counter()
    error_kind_counter: Counter[str] = Counter()
    error_prefix_counter: Counter[str] = Counter()
    success_calls = 0
    error_calls = 0
    llm_calls: list[dict] = []
    for call in calls:
        providers_counter[str(call.provider)] += 1
        if str(call.status) == "success":
            success_calls += 1
        else:
            error_calls += 1
            if call.error_message:
                prefix = _trace_error_prefix(call.error_message)
                if prefix:
                    error_prefix_counter[prefix] += 1
            error_kind = _extract_trace_error_kind(call.error_message)
            if error_kind:
                error_kind_counter[error_kind] += 1
        call_error_kind = _extract_trace_error_kind(call.error_message)
        call_raw_snippet = _extract_trace_raw_snippet(call.error_message)
        llm_calls.append(
            {
                "id": str(call.id),
                "created_at": call.created_at.isoformat(),
                "provider": str(call.provider),
                "model": str(call.model),
                "operation": str(call.operation),
                "status": str(call.status),
                "step_id": (str(call.step_id) if call.step_id else None),
                "prompt_tokens": int(call.prompt_tokens or 0),
                "completion_tokens": int(call.completion_tokens or 0),
                "latency_ms": int(call.latency_ms or 0),
                "error_message": call.error_message,
                "error_kind": call_error_kind,
                "raw_snippet": call_raw_snippet,
                "phase_guess": _phase_guess_for_llm_call(call),
            }
        )

    idempotency = None
    if latest_idem is not None:
        idempotency = {
            "idempotency_key": str(latest_idem.idempotency_key),
            "status": str(latest_idem.status),
            "error_code": latest_idem.error_code,
            "updated_at": latest_idem.updated_at.isoformat(),
            "request_hash_prefix": str(latest_idem.request_hash or "")[:12],
            "response_present": isinstance(latest_idem.response_json, dict),
        }

    provider_chain = [settings.llm_provider_primary] + list(settings.llm_provider_fallbacks)
    provider_chain = [str(item) for item in provider_chain if str(item).strip()]

    return {
        "session_id": str(session_id),
        "env": str(settings.env),
        "provider_chain": provider_chain,
        "model_generate": str(settings.llm_model_generate),
        "runtime_limits": {
            "llm_timeout_s": float(settings.llm_timeout_s),
            "llm_total_deadline_s": float(settings.llm_total_deadline_s),
            "llm_retry_attempts_network": int(settings.llm_retry_attempts_network),
            "llm_max_retries": int(settings.llm_max_retries),
            "circuit_window_s": float(settings.llm_circuit_breaker_window_s),
            "circuit_fail_threshold": int(settings.llm_circuit_breaker_fail_threshold),
            "circuit_open_s": float(settings.llm_circuit_breaker_open_s),
        },
        "latest_idempotency": idempotency,
        "summary": {
            "total_calls": len(calls),
            "success_calls": success_calls,
            "error_calls": error_calls,
            "providers": dict(providers_counter),
            "errors_by_kind": dict(error_kind_counter),
            "errors_by_message_prefix": dict(error_prefix_counter),
        },
        "llm_calls": llm_calls,
    }


def _action_log_layer_debug(log: ActionLog) -> dict:
    classification = log.classification if isinstance(log.classification, dict) else {}
    layer_debug = classification.get("layer_debug") if isinstance(classification.get("layer_debug"), dict) else {}
    return dict(layer_debug or {})


def _nearest_llm_step_id(db: Session, *, session_id: uuid.UUID, created_at: datetime) -> str | None:
    value = db.execute(
        select(LLMUsageLog.step_id)
        .where(
            LLMUsageLog.session_id == session_id,
            LLMUsageLog.step_id.is_not(None),
            LLMUsageLog.created_at <= created_at,
        )
        .order_by(LLMUsageLog.created_at.desc(), LLMUsageLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return str(value) if value is not None else None


def _world_layer_snapshot(state_after: dict) -> dict:
    state = state_after if isinstance(state_after, dict) else {}
    return {
        "day": state.get("day"),
        "slot": state.get("slot"),
        "energy": state.get("energy"),
        "money": state.get("money"),
        "knowledge": state.get("knowledge"),
        "affection": state.get("affection"),
    }


def _plot_layer_snapshot(state_after: dict, *, fallback_used: bool) -> dict:
    state = state_after if isinstance(state_after, dict) else {}
    run_state = state.get("run_state") if isinstance(state.get("run_state"), dict) else {}
    quest_state = state.get("quest_state") if isinstance(state.get("quest_state"), dict) else {}
    active_quests = quest_state.get("active_quests") if isinstance(quest_state.get("active_quests"), list) else []
    completed_quests = (
        quest_state.get("completed_quests") if isinstance(quest_state.get("completed_quests"), list) else []
    )
    return {
        "step_index": run_state.get("step_index"),
        "fallback_count": run_state.get("fallback_count"),
        "guard_all_blocked_hits": run_state.get("guard_all_blocked_hits"),
        "guard_stall_hits": run_state.get("guard_stall_hits"),
        "active_quests": len(active_quests),
        "completed_quests": len(completed_quests),
        "fallback_used": bool(fallback_used),
    }


def _consequence_snapshot(layer_debug: dict, state_delta: dict) -> dict:
    delta = state_delta if isinstance(state_delta, dict) else {}
    keypoints = (
        layer_debug.get("state_delta_keypoints")
        if isinstance(layer_debug.get("state_delta_keypoints"), dict)
        else {}
    )
    return {
        "state_delta_keypoints": keypoints or delta,
        "fallback_reason": layer_debug.get("fallback_reason"),
        "event_present": bool(
            ((layer_debug.get("quest_event_ending_flags") or {}).get("event_present"))
            if isinstance(layer_debug.get("quest_event_ending_flags"), dict)
            else False
        ),
        "all_blocked_guard_triggered": bool(
            ((layer_debug.get("quest_event_ending_flags") or {}).get("all_blocked_guard_triggered"))
            if isinstance(layer_debug.get("quest_event_ending_flags"), dict)
            else False
        ),
        "stall_guard_triggered": bool(
            ((layer_debug.get("quest_event_ending_flags") or {}).get("stall_guard_triggered"))
            if isinstance(layer_debug.get("quest_event_ending_flags"), dict)
            else False
        ),
    }


def get_layer_inspector(db: Session, session_id: uuid.UUID, limit: int = 20) -> dict:
    sess = _require_session(db, session_id)
    if str(settings.env).lower() != "dev":
        raise HTTPException(status_code=404, detail={"code": "DEBUG_DISABLED"})

    bounded_limit = max(1, min(int(limit), 200))
    logs = db.execute(
        select(ActionLog)
        .where(ActionLog.session_id == session_id)
        .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
        .limit(bounded_limit)
    ).scalars().all()

    steps: list[dict] = []
    fallback_turns = 0
    mismatch_count = 0
    event_turns = 0
    guard_all_blocked_turns = 0
    guard_stall_turns = 0
    latest_ending: str | None = None

    for idx, log in enumerate(logs):
        layer_debug = _action_log_layer_debug(log)
        flags = (
            layer_debug.get("quest_event_ending_flags")
            if isinstance(layer_debug.get("quest_event_ending_flags"), dict)
            else {}
        )
        prompt_policy = layer_debug.get("prompt_policy") if isinstance(layer_debug.get("prompt_policy"), dict) else {}
        fallback_used = bool(flags.get("fallback_used", log.fallback_used))
        if fallback_used:
            fallback_turns += 1
        if str(prompt_policy.get("intent_action_alignment") or "").lower() == "mismatch":
            mismatch_count += 1
        if bool(flags.get("event_present")):
            event_turns += 1
        if bool(flags.get("all_blocked_guard_triggered")):
            guard_all_blocked_turns += 1
        if bool(flags.get("stall_guard_triggered")):
            guard_stall_turns += 1
        if bool(flags.get("run_ended")) and not latest_ending:
            latest_ending = str(flags.get("ending_id") or "ended")

        step_index = flags.get("step_index")
        if step_index is None:
            run_state = log.state_after.get("run_state") if isinstance(log.state_after, dict) else {}
            step_index = run_state.get("step_index") if isinstance(run_state, dict) else None
        if step_index is None:
            step_index = len(logs) - idx

        llm_step_id = _nearest_llm_step_id(db, session_id=session_id, created_at=log.created_at)
        steps.append(
            {
                "step_index": int(step_index),
                "world_layer": _world_layer_snapshot(log.state_after),
                "characters_layer": {
                    "affection": (log.state_after or {}).get("affection") if isinstance(log.state_after, dict) else None,
                    "input_mode": layer_debug.get("input_mode"),
                },
                "plot_layer": _plot_layer_snapshot(log.state_after, fallback_used=fallback_used),
                "scene_layer": {
                    "story_node_id": str(log.story_node_id) if log.story_node_id else None,
                    "executed_choice_id": str(log.story_choice_id) if log.story_choice_id else None,
                    "resolved_choice_id": layer_debug.get("resolved_choice_id"),
                },
                "action_layer": {
                    "input_mode": layer_debug.get("input_mode"),
                    "player_input": layer_debug.get("player_input"),
                    "attempted_choice_id": layer_debug.get("attempted_choice_id"),
                    "executed_choice_id": layer_debug.get("executed_choice_id"),
                    "resolved_choice_id": layer_debug.get("resolved_choice_id"),
                    "mapping_confidence": layer_debug.get("mapping_confidence"),
                    "fallback_reason": layer_debug.get("fallback_reason"),
                    "mapping_note": layer_debug.get("mapping_note"),
                },
                "consequence_layer": _consequence_snapshot(layer_debug, log.state_delta),
                "ending_layer": {
                    "run_ended": bool(flags.get("run_ended")),
                    "ending_id": flags.get("ending_id"),
                    "ending_outcome": flags.get("ending_outcome"),
                },
                "raw_refs": {
                    "action_log_id": str(log.id),
                    "llm_step_id": llm_step_id,
                    "created_at": log.created_at.isoformat(),
                },
            }
        )

    total_steps = len(steps)
    ending_state = "in_progress"
    if sess.status == "ended":
        ending_state = latest_ending or "ended"

    return {
        "session_id": str(session_id),
        "env": str(settings.env),
        "steps": steps,
        "summary": {
            "fallback_rate": float(fallback_turns / total_steps) if total_steps else 0.0,
            "mismatch_count": int(mismatch_count),
            "event_turns": int(event_turns),
            "guard_all_blocked_turns": int(guard_all_blocked_turns),
            "guard_stall_turns": int(guard_stall_turns),
            "ending_state": ending_state,
        },
    }
