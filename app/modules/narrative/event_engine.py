from __future__ import annotations

from hashlib import sha256

from app.modules.narrative.state_engine import normalize_run_state, normalize_state
from app.modules.session.story_runtime.models import EventResolution, RuntimeEventContext

_STAT_KEYS = ("energy", "money", "knowledge", "affection")


def _normalize_numeric_threshold_map(values: dict | None) -> dict[str, int]:
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


def _normalize_trigger(trigger: dict | None) -> dict:
    if not isinstance(trigger, dict):
        return {}
    normalized: dict[str, object] = {}
    if trigger.get("node_id_is") is not None:
        normalized["node_id_is"] = str(trigger.get("node_id_is"))
    day_in = trigger.get("day_in")
    if isinstance(day_in, list):
        normalized_days = [int(v) for v in day_in if isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) >= 1]
        if normalized_days:
            normalized["day_in"] = normalized_days
    slot_in = trigger.get("slot_in")
    if isinstance(slot_in, list):
        normalized_slots = [str(v) for v in slot_in if str(v) in {"morning", "afternoon", "night"}]
        if normalized_slots:
            normalized["slot_in"] = normalized_slots
    if trigger.get("fallback_used_is") is not None:
        normalized["fallback_used_is"] = bool(trigger.get("fallback_used_is"))
    state_at_least = _normalize_numeric_threshold_map(trigger.get("state_at_least"))
    if state_at_least:
        normalized["state_at_least"] = state_at_least
    state_delta_at_least = _normalize_numeric_threshold_map(trigger.get("state_delta_at_least"))
    if state_delta_at_least:
        normalized["state_delta_at_least"] = state_delta_at_least
    return normalized


def _normalize_event_defs(events_def: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen_event_ids: set[str] = set()
    for raw_event in (events_def or []):
        if not isinstance(raw_event, dict):
            continue
        event_id = str(raw_event.get("event_id") or "").strip()
        if not event_id or event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)

        weight_raw = raw_event.get("weight")
        weight = int(weight_raw) if isinstance(weight_raw, (int, float)) and not isinstance(weight_raw, bool) else 1
        if weight < 1:
            weight = 1

        cooldown_raw = raw_event.get("cooldown_steps")
        cooldown_steps = (
            int(cooldown_raw)
            if isinstance(cooldown_raw, (int, float)) and not isinstance(cooldown_raw, bool)
            else 2
        )
        if cooldown_steps < 0:
            cooldown_steps = 0

        effects_raw = raw_event.get("effects")
        effects: dict[str, int] = {}
        if isinstance(effects_raw, dict):
            for key in _STAT_KEYS:
                value = effects_raw.get(key)
                if value is None or isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    effects[key] = int(value)

        normalized.append(
            {
                "event_id": event_id,
                "title": str(raw_event.get("title") or event_id),
                "weight": weight,
                "once_per_run": bool(raw_event.get("once_per_run", True)),
                "cooldown_steps": cooldown_steps,
                "trigger": _normalize_trigger(raw_event.get("trigger")),
                "effects": effects,
                "narration_hint": (
                    str(raw_event.get("narration_hint"))
                    if raw_event.get("narration_hint") is not None
                    else None
                ),
            }
        )
    return normalized


def _trigger_matches(
    trigger: dict,
    *,
    context: RuntimeEventContext,
    state_after: dict,
    state_delta: dict,
) -> bool:
    if not isinstance(trigger, dict):
        return True

    node_id_is = trigger.get("node_id_is")
    if node_id_is is not None and str(node_id_is) != str(context.story_node_id):
        return False

    day_in = trigger.get("day_in")
    if isinstance(day_in, list) and day_in:
        day = int(state_after.get("day", 0))
        if day not in {int(item) for item in day_in}:
            return False

    slot_in = trigger.get("slot_in")
    if isinstance(slot_in, list) and slot_in:
        if str(state_after.get("slot") or "") not in {str(item) for item in slot_in}:
            return False

    fallback_used_is = trigger.get("fallback_used_is")
    if fallback_used_is is not None and bool(fallback_used_is) is not bool(context.fallback_used):
        return False

    state_at_least = trigger.get("state_at_least")
    if isinstance(state_at_least, dict):
        for key, threshold in state_at_least.items():
            current_value = state_after.get(str(key))
            if not isinstance(current_value, (int, float)):
                return False
            if float(current_value) < float(threshold):
                return False

    state_delta_at_least = trigger.get("state_delta_at_least")
    if isinstance(state_delta_at_least, dict):
        for key, threshold in state_delta_at_least.items():
            current_value = state_delta.get(str(key), 0)
            if not isinstance(current_value, (int, float)):
                return False
            if float(current_value) < float(threshold):
                return False

    return True


def _weighted_pick(events: list[dict], *, context: RuntimeEventContext) -> dict | None:
    if not events:
        return None
    total_weight = sum(max(1, int(item.get("weight", 1))) for item in events)
    if total_weight <= 0:
        return None

    seed_text = f"{context.session_id}:{context.step_id}:{context.story_node_id}"
    seed_int = int(sha256(seed_text.encode("utf-8")).hexdigest(), 16)
    cursor = seed_int % total_weight

    running = 0
    for event in events:
        weight = max(1, int(event.get("weight", 1)))
        running += weight
        if cursor < running:
            return event
    return events[-1]


def _apply_effects(state_after: dict, effects: dict[str, int]) -> dict:
    if not effects:
        return normalize_state(state_after)
    out = dict(state_after)
    for key, delta in effects.items():
        if key not in _STAT_KEYS:
            continue
        out[key] = int(out.get(key, 0)) + int(delta)
    return normalize_state(out)


def _compute_state_delta(before: dict, after: dict) -> dict:
    delta: dict = {}
    keys = set(before.keys()) | set(after.keys())
    for key in keys:
        before_value = before.get(key)
        after_value = after.get(key)
        if before_value == after_value:
            continue
        if isinstance(before_value, int) and isinstance(after_value, int):
            delta[key] = after_value - before_value
        else:
            delta[key] = after_value
    return delta


def _decrement_cooldowns(event_cooldowns: dict[str, int]) -> dict[str, int]:
    decremented: dict[str, int] = {}
    for event_id, remaining in event_cooldowns.items():
        left = int(remaining) - 1
        if left > 0:
            decremented[event_id] = left
    return decremented


def advance_runtime_events(
    *,
    events_def: list[dict] | None,
    run_state: dict | None,
    context: RuntimeEventContext,
    state_before: dict,
    state_after: dict,
    state_delta: dict,
) -> EventResolution:
    normalized_events = _normalize_event_defs(events_def)
    current_state = normalize_state(state_after)
    runtime_state = normalize_run_state(run_state)
    runtime_state["step_index"] = max(int(runtime_state.get("step_index", 0)), int(context.step_id))
    current_cooldowns = dict(runtime_state.get("event_cooldowns") or {})
    next_cooldowns = _decrement_cooldowns(current_cooldowns)

    if not normalized_events:
        runtime_state["event_cooldowns"] = next_cooldowns
        return EventResolution(
            state_after=current_state,
            state_delta=_compute_state_delta(state_before, current_state),
            run_state=runtime_state,
            matched_rules=[],
            selected_event_id=None,
            selected_event_title=None,
            selected_event_narration_hint=None,
            selected_event_effects={},
        )

    cooldowns = current_cooldowns
    triggered_event_ids = list(runtime_state.get("triggered_event_ids") or [])

    eligible: list[dict] = []
    for event in normalized_events:
        event_id = str(event["event_id"])
        if bool(event.get("once_per_run", True)) and event_id in triggered_event_ids:
            continue
        if int(cooldowns.get(event_id, 0)) > 0:
            continue
        trigger = dict(event.get("trigger") or {})
        if not _trigger_matches(trigger, context=context, state_after=current_state, state_delta=state_delta):
            continue
        eligible.append(event)

    selected = _weighted_pick(eligible, context=context)
    if selected is None:
        runtime_state["event_cooldowns"] = next_cooldowns
        return EventResolution(
            state_after=current_state,
            state_delta=_compute_state_delta(state_before, current_state),
            run_state=runtime_state,
            matched_rules=[],
            selected_event_id=None,
            selected_event_title=None,
            selected_event_narration_hint=None,
            selected_event_effects={},
        )

    event_id = str(selected["event_id"])
    effects = dict(selected.get("effects") or {})
    current_state = _apply_effects(current_state, effects)

    updated_triggered = list(runtime_state.get("triggered_event_ids") or [])
    updated_triggered.append(event_id)
    runtime_state["triggered_event_ids"] = updated_triggered
    cooldown_steps = max(0, int(selected.get("cooldown_steps", 0)))
    updated_cooldowns = dict(next_cooldowns)
    if cooldown_steps > 0:
        updated_cooldowns[event_id] = cooldown_steps
    runtime_state["event_cooldowns"] = updated_cooldowns

    rule = {
        "type": "runtime_event",
        "event_id": event_id,
        "title": str(selected.get("title") or event_id),
        "effects": effects,
        "step_id": int(context.step_id),
    }
    return EventResolution(
        state_after=current_state,
        state_delta=_compute_state_delta(state_before, current_state),
        run_state=runtime_state,
        matched_rules=[rule],
        selected_event_id=event_id,
        selected_event_title=str(selected.get("title") or event_id),
        selected_event_narration_hint=(
            str(selected.get("narration_hint"))
            if selected.get("narration_hint") is not None
            else None
        ),
        selected_event_effects=effects,
    )
