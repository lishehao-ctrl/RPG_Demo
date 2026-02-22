from typing import Any

STATE_KEYS = ("energy", "money", "knowledge", "affection")
TIME_SLOTS = ("morning", "afternoon", "night")
TIME_ADVANCE_ACTIONS = {"study", "work", "rest", "date", "gift"}
MAX_DAYS = 7
QUEST_EVENT_HISTORY_LIMIT = 20


def default_initial_state() -> dict:
    return {
        "energy": 80,
        "money": 50,
        "knowledge": 0,
        "affection": 0,
        "day": 1,
        "slot": "morning",
    }


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unique_non_empty_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def normalize_run_state(run_state: dict | None) -> dict:
    raw = run_state if isinstance(run_state, dict) else {}

    step_index = _to_int(raw.get("step_index"), 0)
    if step_index < 0:
        step_index = 0

    triggered_event_ids: list[str] = []
    for item in (raw.get("triggered_event_ids") or []):
        text = str(item or "").strip()
        if text:
            triggered_event_ids.append(text)

    cooldowns_raw = raw.get("event_cooldowns") if isinstance(raw.get("event_cooldowns"), dict) else {}
    event_cooldowns: dict[str, int] = {}
    for raw_event_id, raw_value in cooldowns_raw.items():
        event_id = str(raw_event_id or "").strip()
        if not event_id:
            continue
        value = _to_int(raw_value, 0)
        if value <= 0:
            continue
        event_cooldowns[event_id] = value

    ending_id = raw.get("ending_id")
    ending_id = str(ending_id) if ending_id is not None else None

    ending_outcome = str(raw.get("ending_outcome") or "").strip().lower() or None
    if ending_outcome not in {None, "success", "neutral", "fail"}:
        ending_outcome = None

    ended_at_step_raw = raw.get("ended_at_step")
    ended_at_step = (
        _to_int(ended_at_step_raw, 0)
        if ended_at_step_raw is not None and not isinstance(ended_at_step_raw, bool)
        else None
    )
    if ended_at_step is not None and ended_at_step < 0:
        ended_at_step = None

    fallback_count = _to_int(raw.get("fallback_count"), 0)
    if fallback_count < 0:
        fallback_count = 0

    stall_turns = _to_int(raw.get("stall_turns"), 0)
    if stall_turns < 0:
        stall_turns = 0

    guard_all_blocked_hits = _to_int(raw.get("guard_all_blocked_hits"), 0)
    if guard_all_blocked_hits < 0:
        guard_all_blocked_hits = 0

    guard_stall_hits = _to_int(raw.get("guard_stall_hits"), 0)
    if guard_stall_hits < 0:
        guard_stall_hits = 0

    return {
        "step_index": step_index,
        "triggered_event_ids": triggered_event_ids,
        "event_cooldowns": event_cooldowns,
        "ending_id": ending_id,
        "ending_outcome": ending_outcome,
        "ended_at_step": ended_at_step,
        "fallback_count": fallback_count,
        "stall_turns": stall_turns,
        "guard_all_blocked_hits": guard_all_blocked_hits,
        "guard_stall_hits": guard_stall_hits,
    }


def normalize_quest_state(quest_state: dict | None) -> dict:
    raw = quest_state if isinstance(quest_state, dict) else {}
    quests_raw = raw.get("quests") if isinstance(raw.get("quests"), dict) else {}
    quests: dict[str, dict] = {}
    for raw_quest_id, raw_entry in quests_raw.items():
        quest_id = str(raw_quest_id or "").strip()
        if not quest_id:
            continue
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        status = str(entry.get("status") or "inactive").strip().lower()
        if status not in {"inactive", "active", "completed"}:
            status = "inactive"

        current_stage_index = entry.get("current_stage_index")
        if isinstance(current_stage_index, bool) or not isinstance(current_stage_index, int):
            current_stage_index = None
        elif current_stage_index < 0:
            current_stage_index = None

        current_stage_id = entry.get("current_stage_id")
        current_stage_id = str(current_stage_id) if current_stage_id is not None else None

        stages_raw = entry.get("stages") if isinstance(entry.get("stages"), dict) else {}
        stages: dict[str, dict] = {}
        for raw_stage_id, raw_stage in stages_raw.items():
            stage_id = str(raw_stage_id or "").strip()
            if not stage_id:
                continue
            stage_entry = raw_stage if isinstance(raw_stage, dict) else {}
            stage_status = str(stage_entry.get("status") or "inactive").strip().lower()
            if stage_status not in {"inactive", "active", "completed"}:
                stage_status = "inactive"
            stage_completed_at = stage_entry.get("completed_at")

            milestones_raw = stage_entry.get("milestones")
            milestones: dict[str, dict] = {}
            if isinstance(milestones_raw, dict):
                for raw_milestone_id, raw_milestone in milestones_raw.items():
                    milestone_id = str(raw_milestone_id or "").strip()
                    if not milestone_id:
                        continue
                    milestone_entry = raw_milestone if isinstance(raw_milestone, dict) else {}
                    completed_at = milestone_entry.get("completed_at")
                    milestones[milestone_id] = {
                        "done": bool(milestone_entry.get("done", False)),
                        "completed_at": (str(completed_at) if completed_at is not None else None),
                    }

            stages[stage_id] = {
                "status": stage_status,
                "milestones": milestones,
                "completed_at": (str(stage_completed_at) if stage_completed_at is not None else None),
            }

        completed_at = entry.get("completed_at")
        quests[quest_id] = {
            "status": status,
            "current_stage_index": current_stage_index,
            "current_stage_id": current_stage_id,
            "stages": stages,
            "completed_at": (str(completed_at) if completed_at is not None else None),
        }

    active_quests = _unique_non_empty_strings(raw.get("active_quests"))
    completed_quests = _unique_non_empty_strings(raw.get("completed_quests"))
    active_quests = [quest_id for quest_id in active_quests if quest_id in quests]
    completed_quests = [quest_id for quest_id in completed_quests if quest_id in quests]

    for quest_id, entry in quests.items():
        status = str(entry.get("status") or "inactive")
        if status == "completed":
            if quest_id not in completed_quests:
                completed_quests.append(quest_id)
            if quest_id in active_quests:
                active_quests.remove(quest_id)
            stage_ids = list((entry.get("stages") or {}).keys()) if isinstance(entry.get("stages"), dict) else []
            current_stage_id = entry.get("current_stage_id")
            if not current_stage_id and stage_ids:
                current_stage_id = stage_ids[-1]
            if current_stage_id not in stage_ids:
                current_stage_id = stage_ids[-1] if stage_ids else None
            entry["current_stage_id"] = current_stage_id
            entry["current_stage_index"] = stage_ids.index(current_stage_id) if current_stage_id in stage_ids else None
            for stage_id, stage_entry in (entry.get("stages") or {}).items():
                if not isinstance(stage_entry, dict):
                    continue
                if stage_id == current_stage_id and stage_entry.get("status") != "completed":
                    stage_entry["status"] = "completed"
                elif stage_entry.get("status") == "active":
                    stage_entry["status"] = "inactive"
        elif status == "active":
            if quest_id not in active_quests:
                active_quests.append(quest_id)
            if quest_id in completed_quests:
                completed_quests.remove(quest_id)
            stage_ids = list((entry.get("stages") or {}).keys()) if isinstance(entry.get("stages"), dict) else []
            current_stage_id = entry.get("current_stage_id")
            if current_stage_id not in stage_ids:
                current_stage_id = stage_ids[0] if stage_ids else None
            entry["current_stage_id"] = current_stage_id
            entry["current_stage_index"] = stage_ids.index(current_stage_id) if current_stage_id in stage_ids else None
            if current_stage_id is None:
                entry["status"] = "inactive"
                if quest_id in active_quests:
                    active_quests.remove(quest_id)
            for stage_id, stage_entry in (entry.get("stages") or {}).items():
                if not isinstance(stage_entry, dict):
                    continue
                if stage_entry.get("status") == "completed":
                    continue
                stage_entry["status"] = "active" if stage_id == current_stage_id else "inactive"
        else:
            if quest_id in active_quests:
                active_quests.remove(quest_id)
            if quest_id in completed_quests:
                completed_quests.remove(quest_id)
            entry["current_stage_id"] = None
            entry["current_stage_index"] = None
            for _stage_id, stage_entry in (entry.get("stages") or {}).items():
                if not isinstance(stage_entry, dict):
                    continue
                if stage_entry.get("status") != "completed":
                    stage_entry["status"] = "inactive"

    recent_events: list[dict] = []
    for event in (raw.get("recent_events") or []):
        if not isinstance(event, dict):
            continue
        seq = _to_int(event.get("seq"), 0)
        if seq <= 0:
            continue
        event_type = str(event.get("type") or "").strip()
        quest_id = str(event.get("quest_id") or "").strip()
        milestone_id = event.get("milestone_id")
        timestamp = event.get("timestamp")
        title = event.get("title")
        message = event.get("message")
        rewards = event.get("rewards")
        normalized_event = {
            "seq": seq,
            "type": event_type,
            "quest_id": quest_id,
            "stage_id": (str(event.get("stage_id")) if event.get("stage_id") is not None else None),
            "milestone_id": (str(milestone_id) if milestone_id is not None else None),
            "timestamp": (str(timestamp) if timestamp is not None else None),
            "title": (str(title) if title is not None else None),
            "message": (str(message) if message is not None else None),
            "rewards": rewards if isinstance(rewards, dict) else {},
        }
        recent_events.append(normalized_event)
    if len(recent_events) > QUEST_EVENT_HISTORY_LIMIT:
        recent_events = recent_events[-QUEST_EVENT_HISTORY_LIMIT:]

    event_seq = _to_int(raw.get("event_seq"), 0)
    if recent_events:
        event_seq = max(event_seq, max(int(event.get("seq", 0)) for event in recent_events))
    event_seq = max(0, event_seq)

    return {
        "active_quests": active_quests,
        "completed_quests": completed_quests,
        "quests": quests,
        "recent_events": recent_events,
        "event_seq": event_seq,
    }


def normalize_state(state: dict | None) -> dict:
    defaults = default_initial_state()
    raw = state or {}
    normalized = {
        "energy": _to_int(raw.get("energy"), defaults["energy"]),
        "money": _to_int(raw.get("money"), defaults["money"]),
        "knowledge": _to_int(raw.get("knowledge"), defaults["knowledge"]),
        "affection": _to_int(raw.get("affection"), defaults["affection"]),
        "day": _to_int(raw.get("day"), defaults["day"]),
        "slot": str(raw.get("slot") or defaults["slot"]),
    }
    normalized["energy"] = max(0, min(100, normalized["energy"]))
    normalized["money"] = max(0, min(999999, normalized["money"]))
    normalized["knowledge"] = max(0, min(999, normalized["knowledge"]))
    normalized["affection"] = max(-100, min(100, normalized["affection"]))
    normalized["day"] = max(1, normalized["day"])
    if normalized["slot"] not in TIME_SLOTS:
        normalized["slot"] = defaults["slot"]
    normalized["quest_state"] = normalize_quest_state(raw.get("quest_state"))
    normalized["run_state"] = normalize_run_state(raw.get("run_state"))
    return normalized


def advance_time(state: dict | None, action_id: str | None) -> dict:
    out = normalize_state(state)
    action = str(action_id or "")
    if action not in TIME_ADVANCE_ACTIONS:
        return out

    slot_idx = TIME_SLOTS.index(out["slot"]) + 1
    day = int(out["day"])
    if slot_idx >= len(TIME_SLOTS):
        day += 1
        slot_idx = 0

    out["day"] = day
    out["slot"] = TIME_SLOTS[slot_idx]
    return out


def is_run_complete(state: dict | None, max_days: int | None = None) -> bool:
    normalized = normalize_state(state)
    threshold = MAX_DAYS if max_days is None else int(max_days)
    return int(normalized["day"]) > threshold


def apply_action(state: dict | None, final_action: dict | None) -> tuple[dict, dict]:
    before = normalize_state(state)
    after = dict(before)

    action_id = str((final_action or {}).get("action_id") or "")

    if action_id == "study":
        after["energy"] -= 10
        after["knowledge"] += 2
    elif action_id == "work":
        after["energy"] -= 15
        after["money"] += 20
    elif action_id == "rest":
        after["energy"] += 20
    elif action_id == "date":
        after["energy"] -= 12
        after["money"] -= 5
        after["affection"] += 3
    elif action_id == "gift":
        after["money"] -= 15
        after["affection"] += 4

    after = normalize_state(after)
    after = advance_time(after, action_id)
    after = normalize_state(after)

    delta = {}
    for key, before_value in before.items():
        after_value = after.get(key)
        if before_value == after_value:
            continue
        if isinstance(before_value, int) and isinstance(after_value, int):
            delta[key] = after_value - before_value
        else:
            delta[key] = after_value

    return after, delta
