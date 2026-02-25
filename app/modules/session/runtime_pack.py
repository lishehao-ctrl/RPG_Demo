from __future__ import annotations

from typing import Any

from pydantic import ValidationError


def story_node(pack: dict, node_id: str) -> dict | None:
    for node in (pack.get("nodes") or []):
        if str(node.get("node_id")) == str(node_id):
            return node
    return None


def _normalize_story_choice(choice: dict) -> dict:
    return dict(choice or {})


def _implicit_fallback_spec() -> dict:
    return {
        "id": None,
        "action": {"action_id": "clarify", "params": {}},
        "next_node_id_policy": "stay",
    }


def _coerce_effect_value_to_point(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _normalize_effects_to_point(effects: dict | None) -> dict:
    if not isinstance(effects, dict):
        return {}
    normalized: dict[str, int] = {}
    for key in ("energy", "money", "knowledge", "affection"):
        point = _coerce_effect_value_to_point(effects.get(key))
        if point is not None:
            normalized[key] = int(point)
    return normalized


def _as_dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_inventory_ops(ops: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for raw in (ops or []):
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "").strip()
        if not op:
            continue
        normalized = {"op": op}
        if raw.get("item_id") is not None:
            normalized["item_id"] = str(raw.get("item_id"))
        if raw.get("qty") is not None and not isinstance(raw.get("qty"), bool):
            normalized["qty"] = max(1, int(raw.get("qty")))
        if raw.get("instance_id") is not None:
            normalized["instance_id"] = str(raw.get("instance_id"))
        if raw.get("slot") is not None:
            normalized["slot"] = str(raw.get("slot"))
        if raw.get("currency") is not None:
            normalized["currency"] = str(raw.get("currency"))
        if raw.get("amount") is not None and not isinstance(raw.get("amount"), bool):
            normalized["amount"] = max(1, int(raw.get("amount")))
        if raw.get("bound") is not None:
            normalized["bound"] = bool(raw.get("bound"))
        if raw.get("durability") is not None and not isinstance(raw.get("durability"), bool):
            normalized["durability"] = max(0, min(100, int(raw.get("durability"))))
        if isinstance(raw.get("props"), dict):
            normalized["props"] = dict(raw.get("props") or {})
        out.append(normalized)
    return out


def _normalize_npc_ops(ops: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for raw in (ops or []):
        if not isinstance(raw, dict):
            continue
        npc_id = str(raw.get("npc_id") or "").strip()
        if not npc_id:
            continue
        normalized = {"npc_id": npc_id}
        for key in ("relation", "mood", "beliefs"):
            values = raw.get(key)
            if not isinstance(values, dict):
                continue
            data: dict[str, float] = {}
            for raw_k, raw_v in values.items():
                name = str(raw_k or "").strip()
                if not name:
                    continue
                if isinstance(raw_v, bool) or not isinstance(raw_v, (int, float)):
                    continue
                data[name] = float(raw_v)
            if data:
                normalized[key] = data
        out.append(normalized)
    return out


def _normalize_status_ops(ops: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for raw in (ops or []):
        if not isinstance(raw, dict):
            continue
        status_id = str(raw.get("status_id") or "").strip()
        op = str(raw.get("op") or "").strip().lower()
        if not status_id or op not in {"add", "remove"}:
            continue
        normalized = {
            "target": str(raw.get("target") or "player").strip().lower(),
            "status_id": status_id,
            "op": op,
            "stacks": max(1, int(raw.get("stacks") or 1)),
        }
        if raw.get("npc_id") is not None:
            normalized["npc_id"] = str(raw.get("npc_id"))
        if raw.get("ttl_steps") is not None and not isinstance(raw.get("ttl_steps"), bool):
            normalized["ttl_steps"] = max(1, int(raw.get("ttl_steps")))
        out.append(normalized)
    return out


def _normalize_world_flag_ops(ops: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for raw in (ops or []):
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        if not key:
            continue
        out.append({"key": key, "value": raw.get("value")})
    return out


def _normalize_effect_ops(
    raw_effects: dict | None,
    raw_action_effects_v2: dict | None = None,
) -> dict:
    effects = _as_dict(raw_effects)
    extra = _as_dict(raw_action_effects_v2)

    inventory_ops = _normalize_inventory_ops(
        (effects.get("inventory_ops") if isinstance(effects.get("inventory_ops"), list) else [])
        + (extra.get("inventory_ops") if isinstance(extra.get("inventory_ops"), list) else [])
    )
    npc_ops = _normalize_npc_ops(
        (effects.get("npc_ops") if isinstance(effects.get("npc_ops"), list) else [])
        + (extra.get("npc_ops") if isinstance(extra.get("npc_ops"), list) else [])
    )
    status_ops = _normalize_status_ops(
        (effects.get("status_ops") if isinstance(effects.get("status_ops"), list) else [])
        + (extra.get("status_ops") if isinstance(extra.get("status_ops"), list) else [])
    )
    world_flag_ops = _normalize_world_flag_ops(
        (effects.get("world_flag_ops") if isinstance(effects.get("world_flag_ops"), list) else [])
        + (extra.get("world_flag_ops") if isinstance(extra.get("world_flag_ops"), list) else [])
    )

    out: dict[str, list[dict]] = {}
    if inventory_ops:
        out["inventory_ops"] = inventory_ops
    if npc_ops:
        out["npc_ops"] = npc_ops
    if status_ops:
        out["status_ops"] = status_ops
    if world_flag_ops:
        out["world_flag_ops"] = world_flag_ops
    return out


def _normalize_numeric_threshold_map(values: dict | None) -> dict:
    if not isinstance(values, dict):
        return {}
    normalized: dict[str, int] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        if raw_value is None or isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, (int, float)):
            normalized[key] = int(raw_value)
    return normalized


def _normalize_trigger_for_runtime(trigger: dict | None) -> dict:
    if not isinstance(trigger, dict):
        return {}
    normalized: dict[str, object] = {}
    if trigger.get("node_id_is") is not None:
        normalized["node_id_is"] = str(trigger.get("node_id_is"))
    if trigger.get("next_node_id_is") is not None:
        normalized["next_node_id_is"] = str(trigger.get("next_node_id_is"))
    if trigger.get("executed_choice_id_is") is not None:
        normalized["executed_choice_id_is"] = str(trigger.get("executed_choice_id_is"))
    if trigger.get("action_id_is") is not None:
        normalized["action_id_is"] = str(trigger.get("action_id_is"))
    if trigger.get("fallback_used_is") is not None:
        normalized["fallback_used_is"] = bool(trigger.get("fallback_used_is"))
    if isinstance(trigger.get("state_at_least"), dict):
        normalized["state_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_at_least"))
    if isinstance(trigger.get("state_delta_at_least"), dict):
        normalized["state_delta_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_delta_at_least"))
    return normalized


def _normalize_event_trigger_for_runtime(trigger: dict | None) -> dict:
    if not isinstance(trigger, dict):
        return {}
    normalized: dict[str, object] = {}
    if trigger.get("node_id_is") is not None:
        normalized["node_id_is"] = str(trigger.get("node_id_is"))
    day_in = trigger.get("day_in")
    if isinstance(day_in, list):
        normalized_day_in: list[int] = []
        for value in day_in:
            if isinstance(value, bool):
                continue
            try:
                ivalue = int(value)
            except Exception:  # noqa: BLE001
                continue
            if ivalue >= 1:
                normalized_day_in.append(ivalue)
        if normalized_day_in:
            normalized["day_in"] = normalized_day_in
    slot_in = trigger.get("slot_in")
    if isinstance(slot_in, list):
        allowed = {"morning", "afternoon", "night"}
        normalized_slots = [
            str(slot).strip().lower()
            for slot in slot_in
            if str(slot).strip().lower() in allowed
        ]
        if normalized_slots:
            normalized["slot_in"] = normalized_slots
    if trigger.get("fallback_used_is") is not None:
        normalized["fallback_used_is"] = bool(trigger.get("fallback_used_is"))
    if isinstance(trigger.get("state_at_least"), dict):
        normalized["state_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_at_least"))
    if isinstance(trigger.get("state_delta_at_least"), dict):
        normalized["state_delta_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_delta_at_least"))
    return normalized


def _normalize_ending_trigger_for_runtime(trigger: dict | None) -> dict:
    if not isinstance(trigger, dict):
        return {}
    normalized: dict[str, object] = {}
    if trigger.get("node_id_is") is not None:
        normalized["node_id_is"] = str(trigger.get("node_id_is"))
    for key in (
        "day_at_least",
        "day_at_most",
        "energy_at_most",
        "money_at_least",
        "knowledge_at_least",
        "affection_at_least",
    ):
        value = trigger.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            normalized[key] = int(value)
    completed = trigger.get("completed_quests_include")
    if isinstance(completed, list):
        normalized["completed_quests_include"] = [str(item) for item in completed if str(item).strip()]
    return normalized


def _normalize_events_for_runtime(events: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for raw in (events or []):
        if not isinstance(raw, dict):
            continue
        event = dict(raw)
        event_id = str(event.get("event_id") or "").strip()
        title = str(event.get("title") or "").strip()
        if not event_id or not title:
            continue
        trigger = _normalize_event_trigger_for_runtime(event.get("trigger"))
        normalized_event = {
            "event_id": event_id,
            "title": title,
            "weight": max(1, int(event.get("weight") or 1)),
            "once_per_run": bool(event.get("once_per_run", True)),
            "cooldown_steps": max(0, int(event.get("cooldown_steps") or 0)),
            "trigger": trigger,
            "effects": _normalize_effects_to_point(event.get("effects")),
            "narration_hint": str(event.get("narration_hint")) if event.get("narration_hint") is not None else None,
        }
        out.append(normalized_event)
    return out


def _normalize_endings_for_runtime(endings: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for raw in (endings or []):
        if not isinstance(raw, dict):
            continue
        ending = dict(raw)
        ending_id = str(ending.get("ending_id") or "").strip()
        title = str(ending.get("title") or "").strip()
        outcome = str(ending.get("outcome") or "").strip().lower()
        epilogue = str(ending.get("epilogue") or "").strip()
        if not ending_id or not title or not epilogue:
            continue
        if outcome not in {"success", "neutral", "fail"}:
            outcome = "neutral"
        trigger = _normalize_ending_trigger_for_runtime(ending.get("trigger"))
        out.append(
            {
                "ending_id": ending_id,
                "title": title,
                "priority": int(ending.get("priority") or 100),
                "outcome": outcome,
                "trigger": trigger,
                "epilogue": epilogue,
            }
        )
    return out


def _normalize_run_config_for_runtime(run_config: dict | None) -> dict:
    config = run_config if isinstance(run_config, dict) else {}
    max_days = config.get("max_days", 7)
    max_steps = config.get("max_steps", 24)
    timeout = str(config.get("default_timeout_outcome") or "neutral").strip().lower()
    if timeout not in {"neutral", "fail"}:
        timeout = "neutral"

    try:
        max_days_value = int(max_days)
    except Exception:  # noqa: BLE001
        max_days_value = 7
    try:
        max_steps_value = int(max_steps)
    except Exception:  # noqa: BLE001
        max_steps_value = 24
    return {
        "max_days": max(1, max_days_value),
        "max_steps": max(1, max_steps_value),
        "default_timeout_outcome": timeout,
    }


def _normalize_quests_for_runtime(quests: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for raw_q in (quests or []):
        if not isinstance(raw_q, dict):
            continue
        q = dict(raw_q)
        qid = str(q.get("quest_id") or "").strip()
        title = str(q.get("title") or "").strip()
        if not qid or not title:
            continue
        stages_out: list[dict] = []
        for raw_stage in (q.get("stages") or []):
            if not isinstance(raw_stage, dict):
                continue
            stage = dict(raw_stage)
            sid = str(stage.get("stage_id") or "").strip()
            stitle = str(stage.get("title") or "").strip()
            if not sid or not stitle:
                continue
            milestones_out: list[dict] = []
            for raw_m in (stage.get("milestones") or []):
                if not isinstance(raw_m, dict):
                    continue
                milestone = dict(raw_m)
                mid = str(milestone.get("milestone_id") or "").strip()
                mtitle = str(milestone.get("title") or "").strip()
                if not mid or not mtitle:
                    continue
                milestones_out.append(
                    {
                        "milestone_id": mid,
                        "title": mtitle,
                        "description": (
                            str(milestone.get("description"))
                            if milestone.get("description") is not None
                            else None
                        ),
                        "when": _normalize_trigger_for_runtime(milestone.get("when")),
                        "rewards": _normalize_effects_to_point(milestone.get("rewards")),
                    }
                )
            if not milestones_out:
                continue
            stages_out.append(
                {
                    "stage_id": sid,
                    "title": stitle,
                    "description": (str(stage.get("description")) if stage.get("description") is not None else None),
                    "milestones": milestones_out,
                    "stage_rewards": _normalize_effects_to_point(stage.get("stage_rewards")),
                }
            )
        if not stages_out:
            continue
        normalized.append(
            {
                "quest_id": qid,
                "title": title,
                "description": (str(q.get("description")) if q.get("description") is not None else None),
                "auto_activate": bool(q.get("auto_activate", True)),
                "stages": stages_out,
                "completion_rewards": _normalize_effects_to_point(q.get("completion_rewards")),
            }
        )
    return normalized


def normalize_pack_for_runtime(pack_json: dict | None) -> dict:
    pack = dict(pack_json or {})
    pack["story_id"] = str(pack.get("story_id") or "default_story")
    pack["version"] = int(pack.get("version") or 1)
    pack["title"] = str(pack.get("title") or "Story")
    pack["summary"] = str(pack.get("summary") or "")
    pack["start_node_id"] = str(pack.get("start_node_id") or "")
    if not pack["start_node_id"]:
        first_node = (pack.get("nodes") or [{}])[0]
        pack["start_node_id"] = str(first_node.get("node_id") or "")
    pack["initial_state"] = dict(pack.get("initial_state") or {})

    default_fallback = pack.get("default_fallback")
    if isinstance(default_fallback, dict):
        default_fallback = dict(default_fallback)
        raw_default_effects = _as_dict(default_fallback.get("effects"))
        default_fallback["effects"] = _normalize_effects_to_point(raw_default_effects)
        default_fallback["effect_ops"] = _normalize_effect_ops(raw_default_effects)
        default_fallback["prereq"] = (
            dict((default_fallback.get("prereq") or {}))
            if isinstance(default_fallback.get("prereq"), dict)
            else None
        )
    else:
        default_fallback = None
    pack["default_fallback"] = default_fallback

    nodes: list[dict] = []
    fallback_executors: list[dict] = []
    for raw_executor in (pack.get("fallback_executors") or []):
        if not isinstance(raw_executor, dict):
            continue
        executor = dict(raw_executor)
        executor["id"] = str(executor.get("id") or "").strip()
        if not executor["id"]:
            continue
        executor["label"] = str(executor.get("label")) if executor.get("label") is not None else None
        executor["action_id"] = (
            str(executor.get("action_id"))
            if executor.get("action_id") is not None
            else None
        )
        executor["action_params"] = (
            dict((executor.get("action_params") or {}))
            if isinstance(executor.get("action_params"), dict)
            else {}
        )
        raw_executor_effects = _as_dict(executor.get("effects"))
        executor["effects"] = _normalize_effects_to_point(raw_executor_effects)
        executor["effect_ops"] = _normalize_effect_ops(raw_executor_effects)
        narration = executor.get("narration")
        if not isinstance(narration, dict):
            narration = {}
        executor["narration"] = {
            "skeleton": (str(narration.get("skeleton")) if narration.get("skeleton") is not None else None)
        }
        executor["prereq"] = (
            dict((executor.get("prereq") or {}))
            if isinstance(executor.get("prereq"), dict)
            else None
        )
        executor["next_node_id"] = (
            str(executor.get("next_node_id"))
            if executor.get("next_node_id") is not None
            else None
        )
        fallback_executors.append(executor)

    for raw_node in (pack.get("nodes") or []):
        node = dict(raw_node or {})
        visible_choices: list[dict] = []

        for raw_choice in (node.get("choices") or []):
            choice = _normalize_story_choice(raw_choice)
            raw_choice_effects = _as_dict(choice.get("effects"))
            choice["effects"] = _normalize_effects_to_point(raw_choice_effects)
            choice["effect_ops"] = _normalize_effect_ops(
                raw_choice_effects,
                _as_dict(choice.get("action_effects_v2")),
            )
            visible_choices.append(choice)

        fallback = node.get("fallback")
        fallback_source = "node"
        if fallback is None and default_fallback is not None:
            fallback = dict(default_fallback)
            fallback_source = "default"
        elif fallback is None:
            fallback = _implicit_fallback_spec()
            fallback_source = "implicit"
        else:
            fallback = dict(fallback)
        raw_fallback_effects = _as_dict(fallback.get("effects"))
        fallback["effects"] = _normalize_effects_to_point(raw_fallback_effects)
        fallback["effect_ops"] = _normalize_effect_ops(raw_fallback_effects)
        fallback["prereq"] = (
            dict((fallback.get("prereq") or {}))
            if isinstance(fallback.get("prereq"), dict)
            else None
        )

        node["choices"] = visible_choices
        node["intents"] = [dict(item) for item in (node.get("intents") or []) if isinstance(item, dict)]
        node["node_fallback_choice_id"] = (
            str(node.get("node_fallback_choice_id"))
            if node.get("node_fallback_choice_id") is not None
            else None
        )
        node["fallback"] = fallback
        node["_fallback_source"] = fallback_source
        nodes.append(node)

    pack["nodes"] = nodes
    pack["fallback_executors"] = fallback_executors
    pack["global_fallback_choice_id"] = (
        str(pack.get("global_fallback_choice_id"))
        if pack.get("global_fallback_choice_id") is not None
        else None
    )
    pack["item_defs"] = [dict(item) for item in (pack.get("item_defs") or []) if isinstance(item, dict)]
    pack["npc_defs"] = [dict(item) for item in (pack.get("npc_defs") or []) if isinstance(item, dict)]
    pack["status_defs"] = [dict(item) for item in (pack.get("status_defs") or []) if isinstance(item, dict)]
    pack["quests"] = _normalize_quests_for_runtime(pack.get("quests"))
    pack["events"] = _normalize_events_for_runtime(pack.get("events"))
    pack["endings"] = _normalize_endings_for_runtime(pack.get("endings"))
    pack["run_config"] = _normalize_run_config_for_runtime(pack.get("run_config"))
    return pack


def _render_schema_errors(exc: ValidationError) -> list[str]:
    rendered: list[str] = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", ()))
        message = str(item.get("msg") or "validation error")
        rendered.append(f"SCHEMA:{location}:{message}")
    return rendered


def validate_runtime_pack_v10_strict(pack_json: dict | None) -> list[str]:
    payload: Any = pack_json if isinstance(pack_json, dict) else {}
    from app.modules.story.schemas import StoryPack
    from app.modules.story.validation import validate_story_pack_structural

    try:
        pack = StoryPack.model_validate(payload)
    except ValidationError as exc:
        return sorted(set(_render_schema_errors(exc)))
    return sorted(set(validate_story_pack_structural(pack)))


def assert_runtime_pack_v10_strict(pack_json: dict | None) -> dict:
    errors = validate_runtime_pack_v10_strict(pack_json)
    if errors:
        raise ValueError("RUNTIME_PACK_V10_REQUIRED")
    return normalize_pack_for_runtime(pack_json)


def implicit_fallback_spec() -> dict:
    return _implicit_fallback_spec()
