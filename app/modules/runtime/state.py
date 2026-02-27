from __future__ import annotations

import copy

TIER_LABELS = ["Hostile", "Wary", "Neutral", "Warm", "Close"]
DEFAULT_NPC_THRESHOLDS = [-60, -20, 20, 60]


def default_state() -> dict:
    return {
        "energy": 80,
        "money": 50,
        "knowledge": 0,
        "affection": 0,
        "day": 1,
        "slot": "morning",
        "run_state": {
            "step_index": 0,
            "fallback_count": 0,
            "consecutive_fallback_count": 0,
            "last_fallback_reason": None,
            "nudge_tier": None,
            "run_ended": False,
            "ending_id": None,
            "ending_outcome": None,
            "ending_camp": None,
            "selection_retry_count": 0,
            "selection_retry_errors": [],
            "ending_report": None,
        },
        "flags": {},
        "inventory_state": {},
        "npc_state": {},
        "external_status": {},
    }


def clamp_npc_value(value: int | float) -> int:
    return int(max(-100, min(100, float(value))))


def _clamp_player_stat(key: str, value: int | float) -> int:
    num = float(value)
    if key == "energy":
        num = max(0, min(100, num))
    else:
        num = max(0, num)
    return int(num)


def _normalize_thresholds(raw: object) -> list[int]:
    values: list[int] = []
    if isinstance(raw, list) and len(raw) == 4:
        try:
            values = [int(v) for v in raw]
        except (TypeError, ValueError):
            values = []
    if len(values) != 4:
        values = list(DEFAULT_NPC_THRESHOLDS)
    values = sorted(values)
    if len(set(values)) != 4:
        values = list(DEFAULT_NPC_THRESHOLDS)
    if values[0] < -100 or values[-1] > 100:
        values = list(DEFAULT_NPC_THRESHOLDS)
    return values


def tier_from_value(value: int | float, thresholds: list[int]) -> str:
    t = _normalize_thresholds(thresholds)
    v = int(float(value))
    if v <= t[0]:
        return "Hostile"
    if v <= t[1]:
        return "Wary"
    if v < t[2]:
        return "Neutral"
    if v < t[3]:
        return "Warm"
    return "Close"


def tier_index(tier: str) -> int:
    try:
        return TIER_LABELS.index(str(tier))
    except ValueError:
        return 0


def relation_tier_from_tiers(affection_tier: str, trust_tier: str) -> str:
    idx = min(tier_index(affection_tier), tier_index(trust_tier))
    return TIER_LABELS[idx]


def _default_npc_entry() -> dict:
    thresholds = list(DEFAULT_NPC_THRESHOLDS)
    return {
        "affection": 0,
        "trust": 0,
        "affection_thresholds": thresholds,
        "trust_thresholds": thresholds,
        "affection_tier": "Neutral",
        "trust_tier": "Neutral",
        "relation_tier": "Neutral",
    }


def build_npc_state_from_defs(npc_defs: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for item in npc_defs:
        npc_id = str((item or {}).get("npc_id") or "").strip()
        if not npc_id:
            continue
        affection = clamp_npc_value((item or {}).get("initial_affection", 0))
        trust = clamp_npc_value((item or {}).get("initial_trust", 0))
        affection_thresholds = _normalize_thresholds((item or {}).get("affection_thresholds"))
        trust_thresholds = _normalize_thresholds((item or {}).get("trust_thresholds"))
        out[npc_id] = {
            "affection": affection,
            "trust": trust,
            "affection_thresholds": affection_thresholds,
            "trust_thresholds": trust_thresholds,
            "affection_tier": tier_from_value(affection, affection_thresholds),
            "trust_tier": tier_from_value(trust, trust_thresholds),
            "relation_tier": relation_tier_from_tiers(
                tier_from_value(affection, affection_thresholds),
                tier_from_value(trust, trust_thresholds),
            ),
        }
    return out


def _ensure_npc_relation_tiers(state: dict) -> None:
    npc_state = state.get("npc_state")
    if not isinstance(npc_state, dict):
        return
    for npc in npc_state.values():
        if not isinstance(npc, dict):
            continue
        affection_thresholds = _normalize_thresholds(npc.get("affection_thresholds"))
        trust_thresholds = _normalize_thresholds(npc.get("trust_thresholds"))
        npc["affection_thresholds"] = affection_thresholds
        npc["trust_thresholds"] = trust_thresholds
        npc["affection_tier"] = tier_from_value(int(npc.get("affection", 0) or 0), affection_thresholds)
        npc["trust_tier"] = tier_from_value(int(npc.get("trust", 0) or 0), trust_thresholds)
        npc["relation_tier"] = relation_tier_from_tiers(str(npc["affection_tier"]), str(npc["trust_tier"]))


def _next_day_slot(day: int, slot: str) -> tuple[int, str]:
    order = ["morning", "afternoon", "night"]
    if slot not in order:
        return day, "morning"
    idx = order.index(slot)
    if idx == len(order) - 1:
        return day + 1, order[0]
    return day, order[idx + 1]


def apply_range_effects(
    state_before: dict,
    *,
    range_effects: list[dict],
    intensity_tier: int,
) -> tuple[dict, dict, list[dict]]:
    after = copy.deepcopy(state_before)
    delta: dict[str, object] = {}
    range_effects_applied: list[dict] = []

    player_totals = {"energy": 0, "money": 0, "knowledge": 0, "affection": 0}

    for item in range_effects or []:
        effect = item if isinstance(item, dict) else {}
        target_type = str(effect.get("target_type") or "").strip()
        metric = str(effect.get("metric") or "").strip()
        target_id = str(effect.get("target_id") or "").strip() or None
        center = int(effect.get("center", 0) or 0)
        intensity = max(0, int(effect.get("intensity", 0) or 0))

        effect_delta = int(center + int(intensity_tier) * intensity)

        if target_type == "player" and metric in player_totals:
            base = int(after.get(metric, 0) or 0)
            new_value = _clamp_player_stat(metric, base + effect_delta)
            after[metric] = new_value
            player_totals[metric] += effect_delta
            range_effects_applied.append(
                {
                    "target_type": target_type,
                    "target_id": None,
                    "metric": metric,
                    "center": center,
                    "intensity": intensity,
                    "intensity_tier": int(intensity_tier),
                    "delta": effect_delta,
                }
            )
            continue

        if target_type == "npc" and target_id and metric in {"affection", "trust"}:
            npc_state = after.setdefault("npc_state", {})
            npc = npc_state.get(target_id)
            if not isinstance(npc, dict):
                npc = _default_npc_entry()
                npc_state[target_id] = npc

            base = int(npc.get(metric, 0) or 0)
            new_value = clamp_npc_value(base + effect_delta)
            npc[metric] = new_value

            affection_thresholds = _normalize_thresholds(npc.get("affection_thresholds"))
            trust_thresholds = _normalize_thresholds(npc.get("trust_thresholds"))
            npc["affection_thresholds"] = affection_thresholds
            npc["trust_thresholds"] = trust_thresholds
            npc["affection_tier"] = tier_from_value(npc.get("affection", 0), affection_thresholds)
            npc["trust_tier"] = tier_from_value(npc.get("trust", 0), trust_thresholds)
            npc["relation_tier"] = relation_tier_from_tiers(str(npc["affection_tier"]), str(npc["trust_tier"]))

            npc_delta = delta.setdefault("npc", {})
            if not isinstance(npc_delta, dict):
                npc_delta = {}
                delta["npc"] = npc_delta
            per_npc = npc_delta.setdefault(target_id, {})
            if not isinstance(per_npc, dict):
                per_npc = {}
                npc_delta[target_id] = per_npc
            per_npc[metric] = int(per_npc.get(metric, 0) or 0) + effect_delta
            per_npc["affection_tier"] = npc.get("affection_tier")
            per_npc["trust_tier"] = npc.get("trust_tier")
            per_npc["relation_tier"] = npc.get("relation_tier")

            range_effects_applied.append(
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "metric": metric,
                    "center": center,
                    "intensity": intensity,
                    "intensity_tier": int(intensity_tier),
                    "delta": effect_delta,
                }
            )

    for key, value in player_totals.items():
        if value != 0:
            delta[key] = value

    return after, delta, range_effects_applied


def apply_transition(
    state_before: dict,
    *,
    range_effects: list[dict],
    intensity_tier: int,
    fallback_used: bool,
    fallback_reason: str | None,
) -> tuple[dict, dict, list[dict]]:
    after, delta, range_effects_applied = apply_range_effects(
        state_before,
        range_effects=range_effects,
        intensity_tier=intensity_tier,
    )
    _ensure_npc_relation_tiers(after)

    day = int(after.get("day", 1) or 1)
    slot = str(after.get("slot", "morning") or "morning")
    next_day, next_slot = _next_day_slot(day, slot)
    after["day"] = next_day
    after["slot"] = next_slot
    delta["day"] = next_day - day
    delta["slot"] = next_slot

    run_state = after.setdefault("run_state", {})
    prev_step_index = int(run_state.get("step_index", 0) or 0)
    run_state["step_index"] = prev_step_index + 1
    if fallback_used:
        run_state["fallback_count"] = int(run_state.get("fallback_count", 0) or 0) + 1
        run_state["consecutive_fallback_count"] = int(run_state.get("consecutive_fallback_count", 0) or 0) + 1
        run_state["last_fallback_reason"] = fallback_reason
    else:
        run_state["consecutive_fallback_count"] = 0
        run_state["last_fallback_reason"] = None
    run_state.setdefault("run_ended", False)
    run_state.setdefault("ending_id", None)
    run_state.setdefault("ending_outcome", None)
    run_state.setdefault("ending_camp", None)
    run_state.setdefault("selection_retry_count", 0)
    run_state.setdefault("selection_retry_errors", [])
    run_state.setdefault("nudge_tier", None)
    run_state.setdefault("ending_report", None)

    delta["run_state"] = {
        "step_index": run_state["step_index"],
        "fallback_count": int(run_state.get("fallback_count", 0) or 0),
        "consecutive_fallback_count": int(run_state.get("consecutive_fallback_count", 0) or 0),
        "last_fallback_reason": run_state.get("last_fallback_reason"),
        "nudge_tier": run_state.get("nudge_tier"),
        "run_ended": bool(run_state.get("run_ended", False)),
        "ending_id": run_state.get("ending_id"),
        "ending_outcome": run_state.get("ending_outcome"),
        "ending_camp": run_state.get("ending_camp"),
        "selection_retry_count": int(run_state.get("selection_retry_count", 0) or 0),
        "selection_retry_errors": list(run_state.get("selection_retry_errors") or []),
        "ending_report": run_state.get("ending_report"),
    }

    return after, delta, range_effects_applied
