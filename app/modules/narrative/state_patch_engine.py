from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from app.modules.narrative.state_engine import normalize_state

_EQUIPMENT_SLOTS = ("weapon", "armor", "accessory")


def _state_json_size_bytes(state: dict) -> int:
    return len(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _inventory_occupancy(inventory_state: dict) -> int:
    stack_items = inventory_state.get("stack_items") if isinstance(inventory_state.get("stack_items"), dict) else {}
    instance_items = inventory_state.get("instance_items") if isinstance(inventory_state.get("instance_items"), dict) else {}
    stack_count = sum(
        int((entry or {}).get("qty", 0))
        for entry in stack_items.values()
        if isinstance(entry, dict)
    )
    return max(0, int(stack_count)) + len(instance_items)


def _apply_status_list(
    status_list: list[dict],
    *,
    status_id: str,
    op: str,
    stacks: int,
    ttl_steps: int | None,
    step_index: int,
) -> int:
    mutated = 0
    if op == "remove":
        next_list = [item for item in status_list if str(item.get("status_id")) != status_id]
        if len(next_list) != len(status_list):
            status_list[:] = next_list
            mutated = 1
        return mutated

    for item in status_list:
        if str(item.get("status_id")) != status_id:
            continue
        item["stacks"] = max(1, int(item.get("stacks", 1)) + int(stacks))
        if ttl_steps is not None and ttl_steps > 0:
            expires_at_step = step_index + ttl_steps
            current_expiry = item.get("expires_at_step")
            if current_expiry is None or int(current_expiry) < expires_at_step:
                item["expires_at_step"] = expires_at_step
        mutated = 1
        return mutated

    expires_at = (step_index + ttl_steps) if ttl_steps is not None and ttl_steps > 0 else None
    status_list.append(
        {
            "status_id": status_id,
            "stacks": max(1, int(stacks)),
            "expires_at_step": expires_at,
        }
    )
    return 1


def _make_memory_ref(npc_id: str, memory: dict, step_index: int) -> str:
    mem_id = str(memory.get("mem_id") or "").strip()
    if mem_id:
        return mem_id
    content = str(memory.get("content") or "").strip()
    digest = hashlib.sha1(f"{npc_id}:{step_index}:{content}".encode("utf-8")).hexdigest()[:16]
    return f"mem_{digest}"


def apply_effect_ops(state: dict | None, effect_ops: dict | None) -> tuple[dict, dict]:
    out = normalize_state(state)
    effect_patch = effect_ops if isinstance(effect_ops, dict) else {}

    inventory_state = dict((out.get("inventory_state") or {}))
    stack_items = dict((inventory_state.get("stack_items") or {}))
    instance_items = dict((inventory_state.get("instance_items") or {}))
    equipment_slots = dict((inventory_state.get("equipment_slots") or {}))
    currency = dict((inventory_state.get("currency") or {}))
    capacity = max(1, int(inventory_state.get("capacity", 40)))

    external_status = dict((out.get("external_status") or {}))
    world_flags = dict((external_status.get("world_flags") or {}))
    player_effects = list((external_status.get("player_effects") or []))

    npc_state = dict((out.get("npc_state") or {}))
    run_state = dict((out.get("run_state") or {}))
    step_index = int(run_state.get("step_index") or 0)

    inventory_mutation_count = 0
    npc_mutation_count = 0
    status_mutation_count = 0
    world_flag_mutation_count = 0

    for op in (effect_patch.get("inventory_ops") or []):
        if not isinstance(op, dict):
            continue
        op_name = str(op.get("op") or "").strip()
        if op_name in {"add_stack", "remove_stack"}:
            item_id = str(op.get("item_id") or "").strip()
            qty = int(op.get("qty") or 0)
            if not item_id or qty <= 0:
                continue
            current_qty = int((stack_items.get(item_id) or {}).get("qty", 0))
            if op_name == "add_stack":
                occupancy = _inventory_occupancy(
                    {
                        "stack_items": stack_items,
                        "instance_items": instance_items,
                    }
                )
                available = max(0, capacity - occupancy)
                add_qty = min(available, qty)
                if add_qty <= 0:
                    continue
                stack_items[item_id] = {"qty": current_qty + add_qty}
                inventory_mutation_count += 1
            else:
                next_qty = max(0, current_qty - qty)
                if next_qty == current_qty:
                    continue
                if next_qty <= 0:
                    stack_items.pop(item_id, None)
                else:
                    stack_items[item_id] = {"qty": next_qty}
                inventory_mutation_count += 1
            continue

        if op_name == "add_instance":
            item_id = str(op.get("item_id") or "").strip()
            if not item_id:
                continue
            occupancy = _inventory_occupancy(
                {
                    "stack_items": stack_items,
                    "instance_items": instance_items,
                }
            )
            if occupancy >= capacity:
                continue
            instance_id = str(op.get("instance_id") or "").strip() or f"inst_{uuid.uuid4().hex[:12]}"
            durability = int(op.get("durability") or 100)
            instance_items[instance_id] = {
                "item_id": item_id,
                "durability": max(0, min(100, durability)),
                "bound": bool(op.get("bound", False)),
                "props": dict(op.get("props") or {}) if isinstance(op.get("props"), dict) else {},
            }
            inventory_mutation_count += 1
            continue

        if op_name == "remove_instance":
            target_instance_id = str(op.get("instance_id") or "").strip()
            if not target_instance_id:
                target_item_id = str(op.get("item_id") or "").strip()
                if target_item_id:
                    for candidate_id, candidate in instance_items.items():
                        if str((candidate or {}).get("item_id") or "").strip() == target_item_id:
                            target_instance_id = candidate_id
                            break
            if not target_instance_id or target_instance_id not in instance_items:
                continue
            instance_items.pop(target_instance_id, None)
            for slot_name in _EQUIPMENT_SLOTS:
                if str(equipment_slots.get(slot_name) or "") == target_instance_id:
                    equipment_slots[slot_name] = None
            inventory_mutation_count += 1
            continue

        if op_name == "equip":
            slot = str(op.get("slot") or "").strip().lower()
            instance_id = str(op.get("instance_id") or "").strip()
            if slot not in _EQUIPMENT_SLOTS or instance_id not in instance_items:
                continue
            if str(equipment_slots.get(slot) or "") != instance_id:
                equipment_slots[slot] = instance_id
                inventory_mutation_count += 1
            continue

        if op_name == "unequip":
            slot = str(op.get("slot") or "").strip().lower()
            if slot not in _EQUIPMENT_SLOTS:
                continue
            if equipment_slots.get(slot) is not None:
                equipment_slots[slot] = None
                inventory_mutation_count += 1
            continue

        if op_name in {"grant_currency", "spend_currency"}:
            currency_code = str(op.get("currency") or "").strip()
            amount = int(op.get("amount") or 0)
            if not currency_code or amount <= 0:
                continue
            current = int(currency.get(currency_code) or 0)
            if op_name == "grant_currency":
                currency[currency_code] = current + amount
                inventory_mutation_count += 1
            else:
                next_value = max(0, current - amount)
                if next_value != current:
                    currency[currency_code] = next_value
                    inventory_mutation_count += 1

    for op in (effect_patch.get("npc_ops") or []):
        if not isinstance(op, dict):
            continue
        npc_id = str(op.get("npc_id") or "").strip()
        if not npc_id:
            continue
        npc_entry = dict(npc_state.get(npc_id) or {})
        relation = dict(npc_entry.get("relation") or {})
        mood = dict(npc_entry.get("mood") or {})
        beliefs = dict(npc_entry.get("beliefs") or {})
        changed = False

        for key, value in (op.get("relation") or {}).items():
            axis = str(key or "").strip()
            if not axis:
                continue
            delta = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
            if delta == 0:
                continue
            next_value = max(-100, min(100, int(relation.get(axis, 0)) + int(delta)))
            if int(relation.get(axis, 0)) != next_value:
                relation[axis] = next_value
                changed = True

        for key, value in (op.get("mood") or {}).items():
            axis = str(key or "").strip()
            if not axis:
                continue
            delta = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
            if delta == 0:
                continue
            next_value = max(-1.0, min(1.0, float(mood.get(axis, 0.0)) + delta))
            if float(mood.get(axis, 0.0)) != next_value:
                mood[axis] = next_value
                changed = True

        for key, value in (op.get("beliefs") or {}).items():
            axis = str(key or "").strip()
            if not axis:
                continue
            delta = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
            if delta == 0:
                continue
            next_value = max(0.0, min(1.0, float(beliefs.get(axis, 0.0)) + delta))
            if float(beliefs.get(axis, 0.0)) != next_value:
                beliefs[axis] = next_value
                changed = True

        npc_entry["relation"] = relation
        npc_entry["mood"] = mood
        npc_entry["beliefs"] = beliefs
        npc_entry["active_goals"] = list(npc_entry.get("active_goals") or [])
        npc_entry["status_effects"] = list(npc_entry.get("status_effects") or [])
        npc_entry["short_memory"] = list(npc_entry.get("short_memory") or [])
        npc_entry["long_memory_refs"] = list(npc_entry.get("long_memory_refs") or [])
        npc_entry["last_seen_step"] = max(step_index, int(npc_entry.get("last_seen_step") or 0))
        npc_state[npc_id] = npc_entry
        if changed:
            npc_mutation_count += 1

    for op in (effect_patch.get("status_ops") or []):
        if not isinstance(op, dict):
            continue
        target = str(op.get("target") or "player").strip().lower()
        status_id = str(op.get("status_id") or "").strip()
        op_name = str(op.get("op") or "").strip().lower()
        stacks = int(op.get("stacks") or 1)
        ttl_steps = op.get("ttl_steps")
        ttl_steps = int(ttl_steps) if isinstance(ttl_steps, (int, float)) and not isinstance(ttl_steps, bool) else None
        if not status_id or op_name not in {"add", "remove"}:
            continue
        if target == "npc":
            npc_id = str(op.get("npc_id") or "").strip()
            if not npc_id:
                continue
            npc_entry = dict(npc_state.get(npc_id) or {})
            status_effects = list(npc_entry.get("status_effects") or [])
            status_mutation_count += _apply_status_list(
                status_effects,
                status_id=status_id,
                op=op_name,
                stacks=stacks,
                ttl_steps=ttl_steps,
                step_index=step_index,
            )
            npc_entry["status_effects"] = status_effects
            npc_entry["relation"] = dict(npc_entry.get("relation") or {})
            npc_entry["mood"] = dict(npc_entry.get("mood") or {})
            npc_entry["beliefs"] = dict(npc_entry.get("beliefs") or {})
            npc_entry["active_goals"] = list(npc_entry.get("active_goals") or [])
            npc_entry["short_memory"] = list(npc_entry.get("short_memory") or [])
            npc_entry["long_memory_refs"] = list(npc_entry.get("long_memory_refs") or [])
            npc_entry["last_seen_step"] = max(step_index, int(npc_entry.get("last_seen_step") or 0))
            npc_state[npc_id] = npc_entry
        else:
            status_mutation_count += _apply_status_list(
                player_effects,
                status_id=status_id,
                op=op_name,
                stacks=stacks,
                ttl_steps=ttl_steps,
                step_index=step_index,
            )

    for op in (effect_patch.get("world_flag_ops") or []):
        if not isinstance(op, dict):
            continue
        key = str(op.get("key") or "").strip()
        if not key:
            continue
        value = op.get("value")
        if world_flags.get(key) != value:
            world_flags[key] = value
            world_flag_mutation_count += 1

    inventory_state["stack_items"] = stack_items
    inventory_state["instance_items"] = instance_items
    inventory_state["equipment_slots"] = equipment_slots
    inventory_state["currency"] = currency
    inventory_state["capacity"] = capacity
    out["inventory_state"] = inventory_state

    external_status["world_flags"] = world_flags
    external_status["player_effects"] = player_effects
    external_status["faction_rep"] = dict(external_status.get("faction_rep") or {})
    external_status["timers"] = dict(external_status.get("timers") or {})
    out["external_status"] = external_status
    out["npc_state"] = npc_state

    out = normalize_state(out)
    return out, {
        "inventory_mutation_count": inventory_mutation_count,
        "npc_mutation_count": npc_mutation_count,
        "status_mutation_count": status_mutation_count,
        "world_flag_mutation_count": world_flag_mutation_count,
    }


def compact_npc_memories(
    state: dict | None,
    *,
    short_memory_limit: int = 12,
    long_memory_ref_limit: int = 120,
    state_size_soft_limit_bytes: int = 65536,
    state_size_hard_limit_bytes: int = 131072,
) -> tuple[dict, dict]:
    out = normalize_state(state)
    npc_state = dict((out.get("npc_state") or {}))
    run_state = dict((out.get("run_state") or {}))
    step_index = int(run_state.get("step_index") or 0)

    compacted_count = 0
    for npc_id, raw_entry in list(npc_state.items()):
        entry = dict(raw_entry or {})
        short_memory = [item for item in (entry.get("short_memory") or []) if isinstance(item, dict)]
        filtered_short_memory: list[dict] = []
        for item in short_memory:
            ttl_steps = item.get("ttl_steps")
            created_step = int(item.get("created_step") or 0)
            if ttl_steps is not None and int(ttl_steps) > 0 and (created_step + int(ttl_steps)) <= step_index:
                compacted_count += 1
                continue
            filtered_short_memory.append(item)
        short_memory = filtered_short_memory

        if len(short_memory) > short_memory_limit:
            overflow = len(short_memory) - short_memory_limit
            moved = short_memory[:overflow]
            short_memory = short_memory[overflow:]
            long_memory_refs = list(entry.get("long_memory_refs") or [])
            for item in moved:
                ref = _make_memory_ref(npc_id, item, step_index)
                if ref in long_memory_refs:
                    continue
                long_memory_refs.append(ref)
            entry["long_memory_refs"] = long_memory_refs
            compacted_count += len(moved)

        long_memory_refs = list(entry.get("long_memory_refs") or [])
        if len(long_memory_refs) > long_memory_ref_limit:
            compacted_count += len(long_memory_refs) - long_memory_ref_limit
            long_memory_refs = long_memory_refs[-long_memory_ref_limit:]

        entry["short_memory"] = short_memory
        entry["long_memory_refs"] = long_memory_refs
        npc_state[npc_id] = entry

    out["npc_state"] = npc_state
    out = normalize_state(out)
    size_bytes = _state_json_size_bytes(out)

    pressure = "ok"
    if size_bytes > state_size_hard_limit_bytes:
        pressure = "hard"
    elif size_bytes > state_size_soft_limit_bytes:
        pressure = "soft"

    if pressure in {"soft", "hard"}:
        for npc_id, raw_entry in list(npc_state.items()):
            entry = dict(raw_entry or {})
            if pressure == "hard":
                compacted_count += len(entry.get("short_memory") or [])
                entry["short_memory"] = []
                long_refs = list(entry.get("long_memory_refs") or [])
                trim_to = max(20, long_memory_ref_limit // 3)
                if len(long_refs) > trim_to:
                    compacted_count += len(long_refs) - trim_to
                    long_refs = long_refs[-trim_to:]
                entry["long_memory_refs"] = long_refs
            else:
                short_memory = list(entry.get("short_memory") or [])
                trim_to = max(6, short_memory_limit // 2)
                if len(short_memory) > trim_to:
                    compacted_count += len(short_memory) - trim_to
                    entry["short_memory"] = short_memory[-trim_to:]
            npc_state[npc_id] = entry
        out["npc_state"] = npc_state
        out = normalize_state(out)
        size_bytes = _state_json_size_bytes(out)

    return out, {
        "short_memory_compacted_count": compacted_count,
        "state_json_size_bytes": size_bytes,
        "state_size_pressure": pressure,
    }


def build_npc_prompt_context(state: dict | None, *, max_npcs: int = 3, max_chars: int = 120) -> list[dict]:
    normalized = normalize_state(state)
    npc_state = normalized.get("npc_state") if isinstance(normalized.get("npc_state"), dict) else {}
    rows: list[dict] = []
    for npc_id, entry in npc_state.items():
        if not isinstance(entry, dict):
            continue
        relation = entry.get("relation") if isinstance(entry.get("relation"), dict) else {}
        trust = int(relation.get("trust") or 0)
        affection = int(relation.get("affection") or 0)
        active_goals = entry.get("active_goals") if isinstance(entry.get("active_goals"), list) else []
        goal_id = None
        if active_goals and isinstance(active_goals[0], dict):
            goal_id = str(active_goals[0].get("goal_id") or "").strip() or None
        summary = f"trust={trust}, affection={affection}"
        if goal_id:
            summary = f"{summary}, focus={goal_id}"
        if len(summary) > max_chars:
            summary = summary[:max_chars]
        rows.append(
            {
                "npc_id": str(npc_id),
                "summary": summary,
                "last_seen_step": int(entry.get("last_seen_step") or 0),
            }
        )
    rows.sort(key=lambda item: (int(item.get("last_seen_step") or 0), str(item.get("npc_id") or "")), reverse=True)
    return [{"npc_id": item["npc_id"], "summary": item["summary"]} for item in rows[:max(1, int(max_npcs or 1))]]
