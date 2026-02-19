from __future__ import annotations

from datetime import datetime

from app.modules.narrative.state_engine import normalize_quest_state, normalize_state
from app.modules.session.story_runtime.models import QuestStepEvent, QuestUpdateResult

_STAT_KEYS = ("energy", "money", "knowledge", "affection")
_MAX_RECENT_EVENTS = 20


def _to_effect_points(rewards: dict | None) -> dict[str, int]:
    if not isinstance(rewards, dict):
        return {}
    out: dict[str, int] = {}
    for key in _STAT_KEYS:
        value = rewards.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out[key] = int(value)
    return out


def _normalize_quests_def(quests_def: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen_quest_ids: set[str] = set()
    for raw_quest in (quests_def or []):
        if not isinstance(raw_quest, dict):
            continue
        quest_id = str(raw_quest.get("quest_id") or "").strip()
        if not quest_id or quest_id in seen_quest_ids:
            continue
        seen_quest_ids.add(quest_id)

        stages: list[dict] = []
        seen_stage_ids: set[str] = set()
        for raw_stage in (raw_quest.get("stages") or []):
            if not isinstance(raw_stage, dict):
                continue
            stage_id = str(raw_stage.get("stage_id") or "").strip()
            if not stage_id or stage_id in seen_stage_ids:
                continue
            seen_stage_ids.add(stage_id)

            milestones: list[dict] = []
            seen_milestone_ids: set[str] = set()
            for raw_milestone in (raw_stage.get("milestones") or []):
                if not isinstance(raw_milestone, dict):
                    continue
                milestone_id = str(raw_milestone.get("milestone_id") or "").strip()
                if not milestone_id or milestone_id in seen_milestone_ids:
                    continue
                seen_milestone_ids.add(milestone_id)
                milestones.append(
                    {
                        "milestone_id": milestone_id,
                        "title": str(raw_milestone.get("title") or milestone_id),
                        "description": (
                            str(raw_milestone.get("description"))
                            if raw_milestone.get("description") is not None
                            else None
                        ),
                        "when": dict(raw_milestone.get("when") or {}),
                        "rewards": _to_effect_points(raw_milestone.get("rewards")),
                    }
                )

            stages.append(
                {
                    "stage_id": stage_id,
                    "title": str(raw_stage.get("title") or stage_id),
                    "description": (
                        str(raw_stage.get("description"))
                        if raw_stage.get("description") is not None
                        else None
                    ),
                    "stage_rewards": _to_effect_points(raw_stage.get("stage_rewards")),
                    "milestones": milestones,
                }
            )

        normalized.append(
            {
                "quest_id": quest_id,
                "title": str(raw_quest.get("title") or quest_id),
                "description": (
                    str(raw_quest.get("description"))
                    if raw_quest.get("description") is not None
                    else None
                ),
                "auto_activate": bool(raw_quest.get("auto_activate", True)),
                "completion_rewards": _to_effect_points(raw_quest.get("completion_rewards")),
                "stages": stages,
            }
        )
    return normalized


def _build_stage_runtime(stage_def: dict, *, status: str) -> dict:
    return {
        "status": status,
        "milestones": {
            str(item["milestone_id"]): {"done": False, "completed_at": None}
            for item in (stage_def.get("milestones") or [])
        },
        "completed_at": None,
    }


def _build_quest_runtime(quest_def: dict) -> dict:
    stages_def = list(quest_def.get("stages") or [])
    should_activate = bool(quest_def.get("auto_activate", True)) and bool(stages_def)
    current_stage_index = 0 if should_activate else None
    current_stage_id = str(stages_def[0]["stage_id"]) if should_activate else None

    stages_runtime: dict[str, dict] = {}
    for idx, stage_def in enumerate(stages_def):
        stage_id = str(stage_def["stage_id"])
        stage_status = "active" if should_activate and idx == 0 else "inactive"
        stages_runtime[stage_id] = _build_stage_runtime(stage_def, status=stage_status)

    return {
        "status": "active" if should_activate else "inactive",
        "current_stage_index": current_stage_index,
        "current_stage_id": current_stage_id,
        "stages": stages_runtime,
        "completed_at": None,
    }


def init_quest_state(quests_def: list[dict] | None) -> dict:
    quests: dict[str, dict] = {}
    active_quests: list[str] = []
    for quest in _normalize_quests_def(quests_def):
        quest_id = str(quest["quest_id"])
        runtime_entry = _build_quest_runtime(quest)
        quests[quest_id] = runtime_entry
        if runtime_entry["status"] == "active":
            active_quests.append(quest_id)
    return {
        "active_quests": active_quests,
        "completed_quests": [],
        "quests": quests,
        "recent_events": [],
        "event_seq": 0,
    }


def _trigger_matches(
    trigger: dict,
    *,
    event: QuestStepEvent,
    state_after: dict,
    state_delta: dict,
) -> bool:
    if not isinstance(trigger, dict):
        return False

    if trigger.get("node_id_is") is not None and str(trigger.get("node_id_is")) != str(event.current_node_id):
        return False
    if trigger.get("next_node_id_is") is not None and str(trigger.get("next_node_id_is")) != str(event.next_node_id):
        return False
    if trigger.get("executed_choice_id_is") is not None and str(trigger.get("executed_choice_id_is")) != str(event.executed_choice_id):
        return False
    if trigger.get("action_id_is") is not None and str(trigger.get("action_id_is")) != str(event.action_id or ""):
        return False
    if trigger.get("fallback_used_is") is not None and bool(trigger.get("fallback_used_is")) is not bool(event.fallback_used):
        return False

    state_at_least = trigger.get("state_at_least")
    if state_at_least is not None:
        if not isinstance(state_at_least, dict):
            return False
        for key, threshold in state_at_least.items():
            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                return False
            current_value = state_after.get(str(key))
            if not isinstance(current_value, (int, float)):
                return False
            if float(current_value) < float(threshold):
                return False

    state_delta_at_least = trigger.get("state_delta_at_least")
    if state_delta_at_least is not None:
        if not isinstance(state_delta_at_least, dict):
            return False
        for key, threshold in state_delta_at_least.items():
            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                return False
            current_value = state_delta.get(str(key), 0)
            if not isinstance(current_value, (int, float)):
                return False
            if float(current_value) < float(threshold):
                return False

    return True


def apply_quest_rewards(state_after: dict, rewards: dict | None) -> dict:
    delta_points = _to_effect_points(rewards)
    if not delta_points:
        return normalize_state(state_after)
    out = dict(state_after)
    for key, delta in delta_points.items():
        out[key] = int(out.get(key, 0)) + int(delta)
    return normalize_state(out)


def _emit_event(
    *,
    quest_state: dict,
    event_type: str,
    quest_id: str,
    stage_id: str | None,
    milestone_id: str | None,
    title: str,
    message: str,
    rewards: dict[str, int] | None,
) -> dict:
    next_seq = int(quest_state.get("event_seq", 0)) + 1
    quest_state["event_seq"] = next_seq
    entry = {
        "seq": next_seq,
        "type": event_type,
        "quest_id": quest_id,
        "stage_id": stage_id,
        "milestone_id": milestone_id,
        "title": title,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
        "rewards": dict(rewards or {}),
    }
    recent_events = list(quest_state.get("recent_events") or [])
    recent_events.append(entry)
    if len(recent_events) > _MAX_RECENT_EVENTS:
        recent_events = recent_events[-_MAX_RECENT_EVENTS:]
    quest_state["recent_events"] = recent_events
    return entry


def _refresh_state_delta(state_before: dict, state_after: dict) -> dict:
    return {
        key: int(state_after.get(key, 0)) - int(state_before.get(key, 0))
        for key in _STAT_KEYS
        if int(state_after.get(key, 0)) != int(state_before.get(key, 0))
    }


def _ensure_runtime_alignment(runtime_state: dict, normalized_defs: list[dict]) -> None:
    quest_map = runtime_state["quests"]
    for quest_def in normalized_defs:
        quest_id = str(quest_def["quest_id"])
        if quest_id not in quest_map or not isinstance(quest_map.get(quest_id), dict):
            quest_map[quest_id] = _build_quest_runtime(quest_def)
            continue

        quest_entry = quest_map[quest_id]
        status = str(quest_entry.get("status") or "inactive")
        if status not in {"inactive", "active", "completed"}:
            status = "inactive"
        quest_entry["status"] = status

        stages_raw = quest_entry.get("stages") if isinstance(quest_entry.get("stages"), dict) else {}
        stages: dict[str, dict] = {}
        stages_def = list(quest_def.get("stages") or [])
        for idx, stage_def in enumerate(stages_def):
            stage_id = str(stage_def["stage_id"])
            existing_stage = stages_raw.get(stage_id) if isinstance(stages_raw.get(stage_id), dict) else {}
            stage_status = str(existing_stage.get("status") or "inactive")
            if stage_status not in {"inactive", "active", "completed"}:
                stage_status = "inactive"
            milestone_state = (
                existing_stage.get("milestones") if isinstance(existing_stage.get("milestones"), dict) else {}
            )
            milestones: dict[str, dict] = {}
            for milestone_def in (stage_def.get("milestones") or []):
                milestone_id = str(milestone_def["milestone_id"])
                raw_milestone = (
                    milestone_state.get(milestone_id)
                    if isinstance(milestone_state.get(milestone_id), dict)
                    else {}
                )
                completed_at = raw_milestone.get("completed_at")
                milestones[milestone_id] = {
                    "done": bool(raw_milestone.get("done", False)),
                    "completed_at": (str(completed_at) if completed_at is not None else None),
                }
            completed_at = existing_stage.get("completed_at")
            stages[stage_id] = {
                "status": stage_status,
                "milestones": milestones,
                "completed_at": (str(completed_at) if completed_at is not None else None),
            }
            if status == "active" and idx == 0 and stage_status not in {"active", "completed"}:
                stages[stage_id]["status"] = "active"

        quest_entry["stages"] = stages
        current_stage_index = quest_entry.get("current_stage_index")
        if isinstance(current_stage_index, bool) or not isinstance(current_stage_index, int):
            current_stage_index = None
        current_stage_id = quest_entry.get("current_stage_id")
        current_stage_id = str(current_stage_id) if current_stage_id is not None else None
        stage_ids = [str(stage["stage_id"]) for stage in stages_def]

        if status == "active":
            if current_stage_id not in stage_ids:
                if stage_ids:
                    current_stage_id = stage_ids[0]
                    current_stage_index = 0
                else:
                    current_stage_id = None
                    current_stage_index = None
            if current_stage_id is not None:
                current_stage_index = stage_ids.index(current_stage_id)
                stage_entry = stages.get(current_stage_id)
                if isinstance(stage_entry, dict) and stage_entry.get("status") == "inactive":
                    stage_entry["status"] = "active"
        elif status == "completed":
            if current_stage_id not in stage_ids and stage_ids:
                current_stage_id = stage_ids[-1]
                current_stage_index = len(stage_ids) - 1
            elif current_stage_id in stage_ids:
                current_stage_index = stage_ids.index(current_stage_id)
        else:
            current_stage_index = None
            current_stage_id = None

        quest_entry["current_stage_index"] = current_stage_index
        quest_entry["current_stage_id"] = current_stage_id
        completed_at = quest_entry.get("completed_at")
        quest_entry["completed_at"] = str(completed_at) if completed_at is not None else None


def _mark_active_stage(quest_entry: dict, stage_id: str | None) -> None:
    stages = quest_entry.get("stages") if isinstance(quest_entry.get("stages"), dict) else {}
    for sid, stage_entry in stages.items():
        if not isinstance(stage_entry, dict):
            continue
        if stage_entry.get("status") == "completed":
            continue
        stage_entry["status"] = "active" if stage_id is not None and sid == stage_id else "inactive"


def _all_stage_milestones_done(stage_entry: dict, stage_def: dict) -> bool:
    milestones = stage_entry.get("milestones") if isinstance(stage_entry.get("milestones"), dict) else {}
    for milestone in (stage_def.get("milestones") or []):
        milestone_id = str(milestone["milestone_id"])
        milestone_entry = milestones.get(milestone_id) if isinstance(milestones.get(milestone_id), dict) else {}
        if not bool(milestone_entry.get("done", False)):
            return False
    return True


def advance_quest_state(
    *,
    quests_def: list[dict] | None,
    quest_state: dict | None,
    event: QuestStepEvent,
    state_before: dict,
    state_after: dict,
    state_delta: dict,
) -> QuestUpdateResult:
    normalized_defs = _normalize_quests_def(quests_def)
    if not normalized_defs:
        return QuestUpdateResult(
            state_after=normalize_state(state_after),
            quest_state=normalize_quest_state(quest_state),
            matched_rules=[],
        )

    current_state = normalize_state(state_after)
    current_delta = dict(state_delta or {})
    runtime_state = normalize_quest_state(quest_state)
    _ensure_runtime_alignment(runtime_state, normalized_defs)

    active_set = set(runtime_state.get("active_quests") or [])
    completed_set = set(runtime_state.get("completed_quests") or [])
    matched_rules: list[dict] = []

    for quest in normalized_defs:
        quest_id = str(quest["quest_id"])
        quest_entry = runtime_state["quests"][quest_id]
        quest_status = str(quest_entry.get("status") or "inactive")
        stages_def = list(quest.get("stages") or [])
        stage_ids = [str(stage["stage_id"]) for stage in stages_def]

        if quest_status == "completed":
            completed_set.add(quest_id)
            active_set.discard(quest_id)
            continue
        if quest_status != "active":
            active_set.discard(quest_id)
            continue

        if not stage_ids:
            quest_entry["status"] = "inactive"
            quest_entry["current_stage_index"] = None
            quest_entry["current_stage_id"] = None
            active_set.discard(quest_id)
            continue

        current_stage_id = str(quest_entry.get("current_stage_id") or "")
        if current_stage_id not in stage_ids:
            current_stage_id = stage_ids[0]
            quest_entry["current_stage_id"] = current_stage_id
            quest_entry["current_stage_index"] = 0

        current_stage_index = stage_ids.index(current_stage_id)
        current_stage_def = stages_def[current_stage_index]
        stage_entry = quest_entry["stages"].get(current_stage_id)
        if not isinstance(stage_entry, dict):
            stage_entry = _build_stage_runtime(current_stage_def, status="active")
            quest_entry["stages"][current_stage_id] = stage_entry

        _mark_active_stage(quest_entry, current_stage_id)
        active_set.add(quest_id)

        milestones_state = stage_entry["milestones"]
        for milestone in (current_stage_def.get("milestones") or []):
            milestone_id = str(milestone["milestone_id"])
            milestone_entry = (
                milestones_state.get(milestone_id)
                if isinstance(milestones_state.get(milestone_id), dict)
                else {"done": False, "completed_at": None}
            )
            if bool(milestone_entry.get("done", False)):
                milestones_state[milestone_id] = milestone_entry
                continue
            if not _trigger_matches(
                dict(milestone.get("when") or {}),
                event=event,
                state_after=current_state,
                state_delta=current_delta,
            ):
                milestones_state[milestone_id] = milestone_entry
                continue

            rewards = _to_effect_points(milestone.get("rewards"))
            milestone_entry["done"] = True
            milestone_entry["completed_at"] = datetime.utcnow().isoformat()
            milestones_state[milestone_id] = milestone_entry

            if rewards:
                current_state = apply_quest_rewards(current_state, rewards)
                current_delta = _refresh_state_delta(state_before, current_state)

            emitted = _emit_event(
                quest_state=runtime_state,
                event_type="milestone_completed",
                quest_id=quest_id,
                stage_id=current_stage_id,
                milestone_id=milestone_id,
                title=str(milestone.get("title") or milestone_id),
                message=f"Milestone completed: {milestone_id}",
                rewards=rewards,
            )
            matched_rules.append(
                {
                    "type": "quest_progress",
                    "event_type": "milestone_completed",
                    "quest_id": quest_id,
                    "stage_id": current_stage_id,
                    "milestone_id": milestone_id,
                    "seq": emitted["seq"],
                    "rewards": rewards,
                }
            )

        if not _all_stage_milestones_done(stage_entry, current_stage_def):
            continue

        if stage_entry.get("status") == "completed":
            continue

        stage_rewards = _to_effect_points(current_stage_def.get("stage_rewards"))
        stage_entry["status"] = "completed"
        stage_entry["completed_at"] = datetime.utcnow().isoformat()

        if stage_rewards:
            current_state = apply_quest_rewards(current_state, stage_rewards)
            current_delta = _refresh_state_delta(state_before, current_state)

        emitted_stage = _emit_event(
            quest_state=runtime_state,
            event_type="stage_completed",
            quest_id=quest_id,
            stage_id=current_stage_id,
            milestone_id=None,
            title=str(current_stage_def.get("title") or current_stage_id),
            message=f"Stage completed: {current_stage_id}",
            rewards=stage_rewards,
        )
        matched_rules.append(
            {
                "type": "quest_progress",
                "event_type": "stage_completed",
                "quest_id": quest_id,
                "stage_id": current_stage_id,
                "milestone_id": None,
                "seq": emitted_stage["seq"],
                "rewards": stage_rewards,
            }
        )

        next_stage_index = current_stage_index + 1
        if next_stage_index < len(stage_ids):
            next_stage_id = stage_ids[next_stage_index]
            quest_entry["current_stage_index"] = next_stage_index
            quest_entry["current_stage_id"] = next_stage_id
            _mark_active_stage(quest_entry, next_stage_id)
            emitted_activate = _emit_event(
                quest_state=runtime_state,
                event_type="stage_activated",
                quest_id=quest_id,
                stage_id=next_stage_id,
                milestone_id=None,
                title=str(stages_def[next_stage_index].get("title") or next_stage_id),
                message=f"Stage activated: {next_stage_id}",
                rewards={},
            )
            matched_rules.append(
                {
                    "type": "quest_progress",
                    "event_type": "stage_activated",
                    "quest_id": quest_id,
                    "stage_id": next_stage_id,
                    "milestone_id": None,
                    "seq": emitted_activate["seq"],
                    "rewards": {},
                }
            )
            continue

        completion_rewards = _to_effect_points(quest.get("completion_rewards"))
        quest_entry["status"] = "completed"
        quest_entry["completed_at"] = datetime.utcnow().isoformat()
        active_set.discard(quest_id)
        completed_set.add(quest_id)
        _mark_active_stage(quest_entry, None)

        if completion_rewards:
            current_state = apply_quest_rewards(current_state, completion_rewards)
            current_delta = _refresh_state_delta(state_before, current_state)

        emitted_quest = _emit_event(
            quest_state=runtime_state,
            event_type="quest_completed",
            quest_id=quest_id,
            stage_id=current_stage_id,
            milestone_id=None,
            title=str(quest.get("title") or quest_id),
            message=f"Quest completed: {quest_id}",
            rewards=completion_rewards,
        )
        matched_rules.append(
            {
                "type": "quest_progress",
                "event_type": "quest_completed",
                "quest_id": quest_id,
                "stage_id": current_stage_id,
                "milestone_id": None,
                "seq": emitted_quest["seq"],
                "rewards": completion_rewards,
            }
        )

    runtime_state["active_quests"] = [quest["quest_id"] for quest in normalized_defs if quest["quest_id"] in active_set]
    runtime_state["completed_quests"] = [
        quest["quest_id"] for quest in normalized_defs if quest["quest_id"] in completed_set
    ]
    runtime_state = normalize_quest_state(runtime_state)

    out_state = normalize_state(current_state)
    out_state["quest_state"] = runtime_state
    return QuestUpdateResult(
        state_after=out_state,
        quest_state=runtime_state,
        matched_rules=matched_rules,
    )


def summarize_quest_for_narration(quests_def: list[dict] | None, quest_state: dict | None) -> dict:
    normalized_defs = _normalize_quests_def(quests_def)
    normalized_state = normalize_quest_state(quest_state)

    quest_title_map = {str(quest["quest_id"]): str(quest.get("title") or quest["quest_id"]) for quest in normalized_defs}
    stage_title_map: dict[str, dict[str, str]] = {}
    for quest in normalized_defs:
        quest_id = str(quest["quest_id"])
        stage_title_map[quest_id] = {
            str(stage["stage_id"]): str(stage.get("title") or stage["stage_id"])
            for stage in (quest.get("stages") or [])
        }

    active_items: list[dict] = []
    for quest_id in (normalized_state.get("active_quests") or []):
        quest_entry = (
            normalized_state.get("quests", {}).get(quest_id)
            if isinstance(normalized_state.get("quests"), dict)
            else {}
        )
        current_stage_id = (
            str(quest_entry.get("current_stage_id"))
            if isinstance(quest_entry, dict) and quest_entry.get("current_stage_id") is not None
            else None
        )
        stage_entry = (
            (quest_entry.get("stages") or {}).get(current_stage_id)
            if isinstance(quest_entry, dict) and isinstance(quest_entry.get("stages"), dict) and current_stage_id
            else {}
        )
        milestones = stage_entry.get("milestones") if isinstance(stage_entry, dict) else {}
        milestone_values = list(milestones.values()) if isinstance(milestones, dict) else []
        done_count = sum(1 for item in milestone_values if isinstance(item, dict) and bool(item.get("done", False)))
        total_count = len(milestone_values)

        active_items.append(
            {
                "quest_id": quest_id,
                "title": quest_title_map.get(quest_id, quest_id),
                "current_stage_id": current_stage_id,
                "current_stage_title": (
                    stage_title_map.get(quest_id, {}).get(current_stage_id, current_stage_id)
                    if current_stage_id
                    else None
                ),
                "stage_progress": {"done": done_count, "total": total_count},
            }
        )

    recent_events = list(normalized_state.get("recent_events") or [])[-3:]
    compact_events = [
        {
            "seq": int(event.get("seq", 0)),
            "type": str(event.get("type") or ""),
            "quest_id": str(event.get("quest_id") or ""),
            "stage_id": event.get("stage_id"),
            "milestone_id": event.get("milestone_id"),
            "title": event.get("title"),
        }
        for event in recent_events
        if isinstance(event, dict)
    ]
    return {
        "active_quests": active_items,
        "recent_events": compact_events,
    }
