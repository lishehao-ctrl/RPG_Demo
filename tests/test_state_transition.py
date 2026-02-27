from __future__ import annotations

from app.modules.runtime.state import apply_transition, default_state


def test_state_transition_applies_range_formula_and_clamp() -> None:
    before = default_state()
    before["energy"] = 99
    before["money"] = 50
    after, delta, range_effects_applied = apply_transition(
        before,
        range_effects=[
            {"target_type": "player", "metric": "energy", "center": 10, "intensity": 0},
            {"target_type": "player", "metric": "money", "center": -1000, "intensity": 0},
            {"target_type": "player", "metric": "knowledge", "center": 2, "intensity": 1},
        ],
        intensity_tier=2,
        fallback_used=False,
        fallback_reason=None,
    )
    assert after["energy"] == 100
    assert after["money"] == 0
    assert after["knowledge"] == 4
    assert delta["knowledge"] == 4
    assert len(range_effects_applied) == 3


def test_state_transition_updates_npc_dual_axis_and_fallback_state() -> None:
    before = default_state()
    before["npc_state"] = {
        "npc_maya": {
            "affection": 95,
            "trust": -95,
            "affection_thresholds": [-60, -20, 20, 60],
            "trust_thresholds": [-60, -20, 20, 60],
            "affection_tier": "Close",
            "trust_tier": "Hostile",
        }
    }
    after, delta, _ = apply_transition(
        before,
        range_effects=[
            {"target_type": "npc", "target_id": "npc_maya", "metric": "affection", "center": 4, "intensity": 1},
            {"target_type": "npc", "target_id": "npc_maya", "metric": "trust", "center": -12, "intensity": 2},
        ],
        intensity_tier=2,
        fallback_used=True,
        fallback_reason="NO_MATCH",
    )

    maya = after["npc_state"]["npc_maya"]
    assert maya["affection"] == 100
    assert maya["trust"] == -100
    assert maya["affection_tier"] == "Close"
    assert maya["trust_tier"] == "Hostile"
    assert maya["relation_tier"] == "Hostile"

    run_state = after["run_state"]
    assert run_state["step_index"] == 1
    assert run_state["fallback_count"] == 1
    assert run_state["consecutive_fallback_count"] == 1
    assert run_state["last_fallback_reason"] == "NO_MATCH"
    assert run_state["nudge_tier"] is None
    assert run_state["ending_report"] is None
    assert delta["npc"]["npc_maya"]["affection"] == 6
    assert delta["npc"]["npc_maya"]["trust"] == -8
    assert delta["npc"]["npc_maya"]["relation_tier"] == "Hostile"
