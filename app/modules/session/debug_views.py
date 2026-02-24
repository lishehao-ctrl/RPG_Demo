from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ActionLog, Session as StorySession


def _require_session(db: Session, session_id: uuid.UUID) -> StorySession:
    sess = db.get(StorySession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


def _action_log_layer_debug(log: ActionLog) -> dict:
    classification = log.classification if isinstance(log.classification, dict) else {}
    layer_debug = classification.get("layer_debug") if isinstance(classification.get("layer_debug"), dict) else {}
    return dict(layer_debug or {})


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
    dominant_route_alerts = 0
    low_recovery_turns = 0
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
        turn_intensity = float(layer_debug.get("turn_intensity") or 0.0)
        recovery_offered = bool(layer_debug.get("recovery_offered"))
        if int(layer_debug.get("dominant_route_streak") or 0) >= 3:
            dominant_route_alerts += 1
        if turn_intensity >= 0.6 and not recovery_offered:
            low_recovery_turns += 1
        if bool(flags.get("run_ended")) and not latest_ending:
            latest_ending = str(flags.get("ending_id") or "ended")

        step_index = flags.get("step_index")
        if step_index is None:
            run_state = log.state_after.get("run_state") if isinstance(log.state_after, dict) else {}
            step_index = run_state.get("step_index") if isinstance(run_state, dict) else None
        if step_index is None:
            step_index = len(logs) - idx

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
                    "turn_intensity": layer_debug.get("turn_intensity"),
                    "recovery_offered": layer_debug.get("recovery_offered"),
                    "dominant_route_streak": layer_debug.get("dominant_route_streak"),
                    "tension_note": layer_debug.get("tension_note"),
                },
                "consequence_layer": _consequence_snapshot(layer_debug, log.state_delta),
                "ending_layer": {
                    "run_ended": bool(flags.get("run_ended")),
                    "ending_id": flags.get("ending_id"),
                    "ending_outcome": flags.get("ending_outcome"),
                },
                "raw_refs": {
                    "action_log_id": str(log.id),
                    "llm_step_id": None,
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
            "dominant_route_alerts": int(dominant_route_alerts),
            "low_recovery_turns": int(low_recovery_turns),
            "ending_state": ending_state,
        },
    }
