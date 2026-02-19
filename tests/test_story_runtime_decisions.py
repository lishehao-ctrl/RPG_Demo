from __future__ import annotations

from app.modules.session.story_choice_gating import eval_prereq
from app.modules.session.story_runtime.decisions import resolve_story_choice
from app.modules.session.story_runtime.models import (
    MARKER_REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED,
    MARKER_REROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED,
    MARKER_REROUTE_LIMIT_REACHED_DEGRADED,
    SelectionResult,
)


def _fallback_executed_choice_id(fallback: dict, current_node_id: str) -> str:
    fallback_id = fallback.get("id")
    if fallback_id:
        return str(fallback_id)
    return f"__fallback__:{current_node_id}"


def _select_direct_fallback(**_kwargs) -> SelectionResult:
    return SelectionResult(
        selected_visible_choice_id=None,
        attempted_choice_id=None,
        mapping_confidence=0.2,
        mapping_note="no match",
        internal_reason="NO_MATCH",
        use_fallback=True,
    )


def test_direct_fallback_selection_is_not_counted_as_reroute() -> None:
    visible_choices = [
        {
            "choice_id": "c1",
            "display_text": "Study",
            "action": {"action_id": "study", "params": {}},
            "next_node_id": "n2",
        }
    ]
    fallback_spec = {
        "id": "fb_runtime",
        "action": {"action_id": "rest", "params": {}},
        "effects": {},
    }

    resolution = resolve_story_choice(
        choice_id=None,
        player_input="random text",
        visible_choices=visible_choices,
        intents=[],
        current_story_state={},
        node_fallback_choice=None,
        global_fallback_executor=None,
        fallback_spec=fallback_spec,
        fallback_next_node_id="n1",
        current_node_id="n1",
        select_story_choice=_select_direct_fallback,
        eval_prereq=eval_prereq,
        fallback_executed_choice_id=_fallback_executed_choice_id,
    )

    assert resolution.using_fallback is True
    assert resolution.reroute_used is False
    assert resolution.executed_choice_id == "fb_runtime"
    assert MARKER_REROUTE_LIMIT_REACHED_DEGRADED not in resolution.markers


def test_rerouted_target_with_no_prereq_is_treated_as_ok() -> None:
    visible_choices = [
        {
            "choice_id": "locked",
            "display_text": "Expensive",
            "action": {"action_id": "gift", "params": {"target": "alice", "gift_type": "ring"}},
            "requires": {"min_money": 999},
            "next_node_id": "n2",
        },
        {
            "choice_id": "open",
            "display_text": "Rest",
            "action": {"action_id": "rest", "params": {}},
            "next_node_id": "n1",
        },
    ]
    node_fallback_choice = visible_choices[1]
    fallback_spec = {
        "id": "fb_runtime",
        "action": {"action_id": "rest", "params": {}},
        "effects": {},
    }

    resolution = resolve_story_choice(
        choice_id="locked",
        player_input=None,
        visible_choices=visible_choices,
        intents=[],
        current_story_state={"money": 10, "energy": 50},
        node_fallback_choice=node_fallback_choice,
        global_fallback_executor=None,
        fallback_spec=fallback_spec,
        fallback_next_node_id="n1",
        current_node_id="n1",
        select_story_choice=_select_direct_fallback,
        eval_prereq=eval_prereq,
        fallback_executed_choice_id=_fallback_executed_choice_id,
    )

    assert resolution.reroute_used is True
    assert resolution.fallback_reason_code == "BLOCKED"
    assert resolution.executed_choice_id == "open"
    assert resolution.markers == []


def test_rerouted_target_prereq_blocked_degrades_without_second_reroute() -> None:
    visible_choices = [
        {
            "choice_id": "locked",
            "display_text": "Expensive",
            "action": {"action_id": "gift", "params": {"target": "alice", "gift_type": "ring"}},
            "requires": {"min_money": 999},
            "next_node_id": "n2",
        }
    ]
    global_executor = {
        "id": "fb_global",
        "action": {"action_id": "work", "params": {}},
        "effects": {"money": 10},
        "prereq": {"min_energy": 999},
        "next_node_id": "n2",
    }
    fallback_spec = {
        "id": "fb_runtime",
        "action": {"action_id": "rest", "params": {}},
        "effects": {},
    }

    resolution = resolve_story_choice(
        choice_id="locked",
        player_input=None,
        visible_choices=visible_choices,
        intents=[],
        current_story_state={"money": 10, "energy": 5},
        node_fallback_choice=None,
        global_fallback_executor=global_executor,
        fallback_spec=fallback_spec,
        fallback_next_node_id="n1",
        current_node_id="n1",
        select_story_choice=_select_direct_fallback,
        eval_prereq=eval_prereq,
        fallback_executed_choice_id=_fallback_executed_choice_id,
    )

    assert resolution.reroute_used is True
    assert resolution.fallback_reason_code == "BLOCKED"
    assert MARKER_REROUTE_LIMIT_REACHED_DEGRADED in resolution.markers
    assert MARKER_REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED in resolution.markers
    assert resolution.final_action_for_state == {}
    assert resolution.effects_for_state == {}
    assert resolution.next_node_id == "n1"


def test_rerouted_target_invalid_spec_degrades_and_keeps_outward_reason() -> None:
    visible_choices = [
        {
            "choice_id": "broken",
            "display_text": "Broken prereq",
            "action": {"action_id": "rest", "params": {}},
            "requires": {"min_money": "oops"},
            "next_node_id": "n2",
        }
    ]
    global_executor = {
        "id": "fb_global_invalid",
        "action": {"action_id": "rest", "params": {}},
        "effects": {"energy": 2},
        "prereq": {"slot_in": "night"},
        "next_node_id": "n2",
    }
    fallback_spec = {
        "id": "fb_runtime",
        "action": {"action_id": "rest", "params": {}},
        "effects": {},
    }

    resolution = resolve_story_choice(
        choice_id="broken",
        player_input=None,
        visible_choices=visible_choices,
        intents=[],
        current_story_state={"money": 20, "energy": 20},
        node_fallback_choice=None,
        global_fallback_executor=global_executor,
        fallback_spec=fallback_spec,
        fallback_next_node_id="n1",
        current_node_id="n1",
        select_story_choice=_select_direct_fallback,
        eval_prereq=eval_prereq,
        fallback_executed_choice_id=_fallback_executed_choice_id,
    )

    assert resolution.reroute_used is True
    assert resolution.fallback_reason_code == "FALLBACK"
    assert MARKER_REROUTE_LIMIT_REACHED_DEGRADED in resolution.markers
    assert MARKER_REROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED in resolution.markers
    assert resolution.final_action_for_state == {}
    assert resolution.effects_for_state == {}
    assert resolution.next_node_id == "n1"


def test_resolution_ignores_quest_state_payload_shape() -> None:
    visible_choices = [
        {
            "choice_id": "c1",
            "display_text": "Study",
            "action": {"action_id": "study", "params": {}},
            "next_node_id": "n2",
        }
    ]
    fallback_spec = {
        "id": "fb_runtime",
        "action": {"action_id": "rest", "params": {}},
        "effects": {},
    }

    resolution = resolve_story_choice(
        choice_id="c1",
        player_input=None,
        visible_choices=visible_choices,
        intents=[],
        current_story_state={
            "money": 50,
            "energy": 80,
            "quest_state": {
                "active_quests": ["q1"],
                "completed_quests": [],
                "quests": {
                    "q1": {
                        "status": "active",
                        "current_stage_index": 0,
                        "current_stage_id": "s1",
                        "stages": {"s1": {"status": "active", "milestones": {}}},
                    }
                },
            },
        },
        node_fallback_choice=None,
        global_fallback_executor=None,
        fallback_spec=fallback_spec,
        fallback_next_node_id="n1",
        current_node_id="n1",
        select_story_choice=_select_direct_fallback,
        eval_prereq=eval_prereq,
        fallback_executed_choice_id=_fallback_executed_choice_id,
    )

    assert resolution.using_fallback is False
    assert resolution.executed_choice_id == "c1"
