from typing import Any

STATE_KEYS = ("energy", "money", "knowledge", "affection")
TIME_SLOTS = ("morning", "afternoon", "night")
TIME_ADVANCE_ACTIONS = {"study", "work", "rest", "date", "gift"}
MAX_DAYS = 7
QUEST_EVENT_HISTORY_LIMIT = 20
INVENTORY_DEFAULT_CAPACITY = 40
NPC_SHORT_MEMORY_LIMIT = 12
NPC_LONG_MEMORY_REF_LIMIT = 120


def default_initial_state() -> dict:
    return {
        "energy": 80,
        "money": 50,
        "knowledge": 0,
        "affection": 0,
        "day": 1,
        "slot": "morning",
        "inventory_state": {
            "capacity": INVENTORY_DEFAULT_CAPACITY,
            "currency": {"gold": 50},
            "stack_items": {},
            "instance_items": {},
            "equipment_slots": {
                "weapon": None,
                "armor": None,
                "accessory": None,
            },
        },
        "external_status": {
            "player_effects": [],
            "world_flags": {},
            "faction_rep": {},
            "timers": {},
        },
        "npc_state": {},
    }


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
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


def _normalize_stack_items(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, int]] = {}
    for raw_item_id, raw_entry in raw.items():
        item_id = str(raw_item_id or "").strip()
        if not item_id:
            continue
        qty = 0
        if isinstance(raw_entry, dict):
            qty = _to_int(raw_entry.get("qty"), 0)
        elif isinstance(raw_entry, (int, float)) and not isinstance(raw_entry, bool):
            qty = int(raw_entry)
        if qty <= 0:
            continue
        out[item_id] = {"qty": qty}
    return out


def _normalize_instance_items(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for raw_instance_id, raw_entry in raw.items():
        instance_id = str(raw_instance_id or "").strip()
        if not instance_id or not isinstance(raw_entry, dict):
            continue
        item_id = str(raw_entry.get("item_id") or "").strip()
        if not item_id:
            continue
        durability = _to_int(raw_entry.get("durability"), 100)
        durability = max(0, min(100, durability))
        out[instance_id] = {
            "item_id": item_id,
            "durability": durability,
            "bound": bool(raw_entry.get("bound", False)),
            "props": dict(raw_entry.get("props") or {}) if isinstance(raw_entry.get("props"), dict) else {},
        }
    return out


def _normalize_equipment_slots(raw: Any, instance_items: dict) -> dict:
    default_slots = {"weapon": None, "armor": None, "accessory": None}
    if not isinstance(raw, dict):
        return default_slots
    out = dict(default_slots)
    for slot in default_slots:
        instance_id = raw.get(slot)
        if instance_id is None:
            out[slot] = None
            continue
        text = str(instance_id or "").strip()
        if not text or text not in instance_items:
            out[slot] = None
            continue
        out[slot] = text
    return out


def normalize_inventory_state(inventory_state: dict | None) -> dict:
    raw = inventory_state if isinstance(inventory_state, dict) else {}
    capacity = _to_int(raw.get("capacity"), INVENTORY_DEFAULT_CAPACITY)
    if capacity <= 0:
        capacity = INVENTORY_DEFAULT_CAPACITY

    currency_raw = raw.get("currency") if isinstance(raw.get("currency"), dict) else {}
    currency: dict[str, int] = {}
    for raw_code, raw_amount in currency_raw.items():
        code = str(raw_code or "").strip()
        if not code:
            continue
        amount = _to_int(raw_amount, 0)
        if amount < 0:
            amount = 0
        currency[code] = amount
    if "gold" not in currency:
        currency["gold"] = 0

    stack_items = _normalize_stack_items(raw.get("stack_items"))
    instance_items = _normalize_instance_items(raw.get("instance_items"))
    equipment_slots = _normalize_equipment_slots(raw.get("equipment_slots"), instance_items)

    return {
        "capacity": capacity,
        "currency": currency,
        "stack_items": stack_items,
        "instance_items": instance_items,
        "equipment_slots": equipment_slots,
    }


def _normalize_status_effects(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        status_id = str(item.get("status_id") or "").strip()
        if not status_id:
            continue
        stacks = _to_int(item.get("stacks"), 1)
        if stacks <= 0:
            continue
        expires_at_step_raw = item.get("expires_at_step")
        expires_at_step = None
        if expires_at_step_raw is not None and not isinstance(expires_at_step_raw, bool):
            expires_at_step = _to_int(expires_at_step_raw, 0)
            if expires_at_step <= 0:
                expires_at_step = None
        out.append(
            {
                "status_id": status_id,
                "stacks": stacks,
                "expires_at_step": expires_at_step,
            }
        )
    return out


def normalize_external_status(external_status: dict | None) -> dict:
    raw = external_status if isinstance(external_status, dict) else {}

    world_flags_raw = raw.get("world_flags") if isinstance(raw.get("world_flags"), dict) else {}
    world_flags: dict[str, Any] = {}
    for raw_key, raw_value in world_flags_raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        world_flags[key] = raw_value

    faction_rep_raw = raw.get("faction_rep") if isinstance(raw.get("faction_rep"), dict) else {}
    faction_rep: dict[str, int] = {}
    for raw_key, raw_value in faction_rep_raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        faction_rep[key] = _to_int(raw_value, 0)

    timers_raw = raw.get("timers") if isinstance(raw.get("timers"), dict) else {}
    timers: dict[str, int] = {}
    for raw_key, raw_value in timers_raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        value = _to_int(raw_value, 0)
        if value <= 0:
            continue
        timers[key] = value

    return {
        "player_effects": _normalize_status_effects(raw.get("player_effects")),
        "world_flags": world_flags,
        "faction_rep": faction_rep,
        "timers": timers,
    }


def _normalize_short_memory(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mem_id = str(item.get("mem_id") or "").strip()
        mem_type = str(item.get("type") or "event").strip()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        importance = _to_float(item.get("importance"), 0.5)
        importance = max(0.0, min(1.0, importance))
        created_step = _to_int(item.get("created_step"), 0)
        ttl_steps = _to_int(item.get("ttl_steps"), 0)
        if ttl_steps <= 0:
            ttl_steps = None
        out.append(
            {
                "mem_id": mem_id or None,
                "type": mem_type,
                "content": content,
                "importance": importance,
                "created_step": max(0, created_step),
                "ttl_steps": ttl_steps,
            }
        )
    if len(out) > NPC_SHORT_MEMORY_LIMIT:
        out = out[-NPC_SHORT_MEMORY_LIMIT:]
    return out


def _normalize_long_memory_refs(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    if len(out) > NPC_LONG_MEMORY_REF_LIMIT:
        out = out[-NPC_LONG_MEMORY_REF_LIMIT:]
    return out


def _normalize_npc_entry(raw: Any) -> dict:
    source = raw if isinstance(raw, dict) else {}
    relation_raw = source.get("relation") if isinstance(source.get("relation"), dict) else {}
    mood_raw = source.get("mood") if isinstance(source.get("mood"), dict) else {}
    beliefs_raw = source.get("beliefs") if isinstance(source.get("beliefs"), dict) else {}

    relation: dict[str, int] = {}
    for raw_key, raw_value in relation_raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        relation[key] = max(-100, min(100, _to_int(raw_value, 0)))

    mood: dict[str, float] = {}
    for raw_key, raw_value in mood_raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        mood[key] = max(-1.0, min(1.0, _to_float(raw_value, 0.0)))

    beliefs: dict[str, float] = {}
    for raw_key, raw_value in beliefs_raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        beliefs[key] = max(0.0, min(1.0, _to_float(raw_value, 0.0)))

    active_goals = source.get("active_goals")
    if not isinstance(active_goals, list):
        active_goals = []
    normalized_goals: list[dict] = []
    for item in active_goals:
        if not isinstance(item, dict):
            continue
        goal_id = str(item.get("goal_id") or "").strip()
        if not goal_id:
            continue
        normalized_goals.append(
            {
                "goal_id": goal_id,
                "priority": max(0.0, min(1.0, _to_float(item.get("priority"), 0.5))),
                "progress": max(0.0, min(1.0, _to_float(item.get("progress"), 0.0))),
                "status": str(item.get("status") or "active"),
            }
        )
    if len(normalized_goals) > 8:
        normalized_goals = normalized_goals[:8]

    return {
        "relation": relation,
        "mood": mood,
        "beliefs": beliefs,
        "active_goals": normalized_goals,
        "status_effects": _normalize_status_effects(source.get("status_effects")),
        "short_memory": _normalize_short_memory(source.get("short_memory")),
        "long_memory_refs": _normalize_long_memory_refs(source.get("long_memory_refs")),
        "last_seen_step": max(0, _to_int(source.get("last_seen_step"), 0)),
    }


def normalize_npc_state(npc_state: dict | None) -> dict:
    raw = npc_state if isinstance(npc_state, dict) else {}
    out: dict[str, dict] = {}
    for raw_npc_id, raw_entry in raw.items():
        npc_id = str(raw_npc_id or "").strip()
        if not npc_id:
            continue
        out[npc_id] = _normalize_npc_entry(raw_entry)
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
    normalized["inventory_state"] = normalize_inventory_state(raw.get("inventory_state"))
    normalized["external_status"] = normalize_external_status(raw.get("external_status"))
    normalized["npc_state"] = normalize_npc_state(raw.get("npc_state"))
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
