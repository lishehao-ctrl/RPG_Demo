from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.modules.narrative.state_engine import normalize_state


class PrereqKind(str, Enum):
    OK = "OK"
    BLOCKED = "BLOCKED"
    INVALID_SPEC = "INVALID_SPEC"


@dataclass(frozen=True, slots=True)
class PrereqResult:
    allowed: bool
    kind: PrereqKind
    details: dict[str, Any]


def eval_prereq(ctx: dict | None, prereq_spec: dict | None) -> PrereqResult:
    state = normalize_state(ctx)
    requires = prereq_spec or {}
    if requires is None:
        requires = {}
    if not isinstance(requires, dict):
        return PrereqResult(
            allowed=False,
            kind=PrereqKind.INVALID_SPEC,
            details={"reason": "requires_not_dict"},
        )
    if not requires:
        return PrereqResult(
            allowed=True,
            kind=PrereqKind.OK,
            details={"reason": "empty_requires"},
        )

    def _safe_int(value: Any, label: str) -> tuple[int | None, str | None]:
        try:
            return int(value), None
        except Exception:  # noqa: BLE001
            return None, f"{label}_not_int"

    min_money = requires.get("min_money")
    if min_money is not None:
        min_money_value, min_money_error = _safe_int(min_money, "min_money")
        if min_money_error:
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.INVALID_SPEC,
                details={"reason": min_money_error},
            )
        if int(state["money"]) < int(min_money_value or 0):
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.BLOCKED,
                details={"reason": "min_money", "required": int(min_money_value or 0), "actual": int(state["money"])},
            )

    min_energy = requires.get("min_energy")
    if min_energy is not None:
        min_energy_value, min_energy_error = _safe_int(min_energy, "min_energy")
        if min_energy_error:
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.INVALID_SPEC,
                details={"reason": min_energy_error},
            )
        if int(state["energy"]) < int(min_energy_value or 0):
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.BLOCKED,
                details={"reason": "min_energy", "required": int(min_energy_value or 0), "actual": int(state["energy"])},
            )

    min_affection = requires.get("min_affection")
    if min_affection is not None:
        min_affection_value, min_affection_error = _safe_int(min_affection, "min_affection")
        if min_affection_error:
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.INVALID_SPEC,
                details={"reason": min_affection_error},
            )
        if int(state["affection"]) < int(min_affection_value or 0):
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.BLOCKED,
                details={
                    "reason": "min_affection",
                    "required": int(min_affection_value or 0),
                    "actual": int(state["affection"]),
                },
            )

    day_at_least = requires.get("day_at_least")
    if day_at_least is not None:
        day_at_least_value, day_at_least_error = _safe_int(day_at_least, "day_at_least")
        if day_at_least_error:
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.INVALID_SPEC,
                details={"reason": day_at_least_error},
            )
        if int(state["day"]) < int(day_at_least_value or 0):
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.BLOCKED,
                details={"reason": "day_at_least", "required": int(day_at_least_value or 0), "actual": int(state["day"])},
            )

    slot_in = requires.get("slot_in")
    if slot_in is not None:
        if not isinstance(slot_in, list):
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.INVALID_SPEC,
                details={"reason": "slot_in_not_list"},
            )
        normalized_slot_values = {str(v) for v in slot_in}
        if state["slot"] not in normalized_slot_values:
            return PrereqResult(
                allowed=False,
                kind=PrereqKind.BLOCKED,
                details={"reason": "slot_in", "required": sorted(normalized_slot_values), "actual": state["slot"]},
            )

    return PrereqResult(
        allowed=True,
        kind=PrereqKind.OK,
        details={"reason": "ok"},
    )


def evaluate_choice_availability(choice: dict, state_json: dict | None) -> tuple[bool, str | None]:
    """Compatibility bridge for existing response rendering.

    Returns stable unavailable reason labels for unavailable visible choices.
    Story resolver flow should use eval_prereq directly.
    """

    requires = (choice or {}).get("requires") if isinstance(choice, dict) else None
    result = eval_prereq(state_json, requires if isinstance(requires, dict) else {})
    if result.kind == PrereqKind.OK:
        return True, None
    if result.kind == PrereqKind.INVALID_SPEC:
        return False, "FALLBACK_CONFIG_INVALID"

    reason = str((result.details or {}).get("reason") or "")
    if reason == "min_money":
        return False, "BLOCKED_MIN_MONEY"
    if reason == "min_energy":
        return False, "BLOCKED_MIN_ENERGY"
    if reason == "min_affection":
        return False, "BLOCKED_MIN_AFFECTION"
    if reason == "day_at_least":
        return False, "BLOCKED_DAY_AT_LEAST"
    if reason == "slot_in":
        return False, "BLOCKED_SLOT_IN"
    return False, "BLOCKED"
