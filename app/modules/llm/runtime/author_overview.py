from __future__ import annotations

from typing import TypedDict


class OverviewRow(TypedDict):
    label: str
    value: str


def _clean_text(value: object, *, fallback: str = "") -> str:
    text = " ".join(str(value or "").split()).strip()
    return text or fallback


def _join_non_empty(parts: list[str], *, sep: str = " | ", fallback: str = "n/a") -> str:
    out = [part for part in parts if part]
    return sep.join(out) if out else fallback


def _branch_line(prefix: str, payload: dict) -> str:
    action_type = _clean_text(payload.get("signature_action_type"))
    short_gain = _clean_text(payload.get("short_term_gain"))
    long_cost = _clean_text(payload.get("long_term_cost"))
    if not any((action_type, short_gain, long_cost)):
        return ""
    parts: list[str] = [prefix.strip()]
    if action_type:
        parts.append(action_type)
    if short_gain:
        parts.append(f"+{short_gain}")
    if long_cost:
        parts.append(f"cost {long_cost}")
    return " ".join(parts).strip()


def build_overview_rows_from_blueprint(*, task: str, blueprint: dict) -> list[OverviewRow]:
    core_conflict = blueprint.get("core_conflict") if isinstance(blueprint.get("core_conflict"), dict) else {}
    tension_loop_plan = blueprint.get("tension_loop_plan") if isinstance(blueprint.get("tension_loop_plan"), dict) else {}
    branch_design = blueprint.get("branch_design") if isinstance(blueprint.get("branch_design"), dict) else {}
    lexical_anchors = blueprint.get("lexical_anchors") if isinstance(blueprint.get("lexical_anchors"), dict) else {}

    protagonist = _clean_text(core_conflict.get("protagonist"))
    opposition_actor = _clean_text(core_conflict.get("opposition_actor"))
    scarce_resource = _clean_text(core_conflict.get("scarce_resource"))
    deadline = _clean_text(core_conflict.get("deadline"))
    irreversible_risk = _clean_text(core_conflict.get("irreversible_risk"))
    core_pair = f"{protagonist} vs {opposition_actor}".strip() if protagonist and opposition_actor else ""
    core_conflict_value = _join_non_empty(
        [
            core_pair,
            _clean_text(f"resource {scarce_resource}" if scarce_resource else ""),
            _clean_text(f"deadline {deadline}" if deadline else ""),
            _clean_text(f"risk {irreversible_risk}" if irreversible_risk else ""),
        ]
    )

    tension_bits: list[str] = []
    for beat in ("pressure_open", "pressure_escalation", "recovery_window", "decision_gate"):
        node = tension_loop_plan.get(beat) if isinstance(tension_loop_plan.get(beat), dict) else {}
        objective = _clean_text(node.get("objective"))
        stakes = _clean_text(node.get("stakes"))
        risk_level = _clean_text(node.get("risk_level"), fallback="3")
        if objective or stakes:
            tension_bits.append(f"{beat} (r{risk_level}): {objective}; stakes {stakes}")
    tension_loop_value = _join_non_empty(tension_bits)

    high_risk_push = (
        branch_design.get("high_risk_push")
        if isinstance(branch_design.get("high_risk_push"), dict)
        else {}
    )
    recovery_stabilize = (
        branch_design.get("recovery_stabilize")
        if isinstance(branch_design.get("recovery_stabilize"), dict)
        else {}
    )
    branch_contrast_value = _join_non_empty(
        [
            _branch_line("high-risk", high_risk_push),
            _branch_line("recovery", recovery_stabilize),
        ]
    )

    must_include_terms = lexical_anchors.get("must_include_terms") if isinstance(lexical_anchors.get("must_include_terms"), list) else []
    avoid_generic_labels = lexical_anchors.get("avoid_generic_labels") if isinstance(lexical_anchors.get("avoid_generic_labels"), list) else []
    must_include = ", ".join(
        [_clean_text(item) for item in must_include_terms if _clean_text(item)]
    ).strip()
    avoid_generic = ", ".join(
        [_clean_text(item) for item in avoid_generic_labels if _clean_text(item)]
    ).strip()
    lexical_anchors_value = _join_non_empty(
        [
            _clean_text(f"must include: {must_include}" if must_include else ""),
            _clean_text(f"avoid generic: {avoid_generic}" if avoid_generic else ""),
        ]
    )

    task_focus_map = {
        "seed_expand": "Expand seed into a playable 4-beat tension loop.",
        "story_ingest": "Project source story into compile-safe branching structure.",
        "continue_write": "Append a follow-up beat while preserving conflict contrast.",
    }
    task_focus_value = task_focus_map.get(str(task or "").strip(), "Keep conflict clarity and branch contrast.")

    return [
        {"label": "Core Conflict", "value": core_conflict_value},
        {"label": "Tension Loop", "value": tension_loop_value},
        {"label": "Branch Contrast", "value": branch_contrast_value},
        {"label": "Lexical Anchors", "value": lexical_anchors_value},
        {"label": "Task Focus", "value": task_focus_value},
    ]


__all__ = ["OverviewRow", "build_overview_rows_from_blueprint"]
