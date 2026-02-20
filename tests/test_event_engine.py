from __future__ import annotations

from app.modules.narrative.event_engine import advance_runtime_events
from app.modules.narrative.state_engine import default_initial_state, normalize_state
from app.modules.session.story_runtime.models import RuntimeEventContext


def _context(*, step_id: int, node_id: str = "n1") -> RuntimeEventContext:
    return RuntimeEventContext(
        session_id="sess-1",
        step_id=step_id,
        story_node_id=node_id,
        next_node_id=node_id,
        executed_choice_id="c1",
        action_id="study",
        fallback_used=False,
    )


def test_event_selection_is_deterministic_for_same_seed() -> None:
    events = [
        {
            "event_id": "ev_a",
            "title": "A",
            "weight": 1,
            "once_per_run": False,
            "cooldown_steps": 0,
            "trigger": {"node_id_is": "n1"},
            "effects": {"money": 1},
        },
        {
            "event_id": "ev_b",
            "title": "B",
            "weight": 3,
            "once_per_run": False,
            "cooldown_steps": 0,
            "trigger": {"node_id_is": "n1"},
            "effects": {"money": 2},
        },
    ]
    base = normalize_state(default_initial_state())
    ctx = _context(step_id=1, node_id="n1")

    first = advance_runtime_events(
        events_def=events,
        run_state=None,
        context=ctx,
        state_before=base,
        state_after=base,
        state_delta={},
    )
    second = advance_runtime_events(
        events_def=events,
        run_state=None,
        context=ctx,
        state_before=base,
        state_after=base,
        state_delta={},
    )

    assert first.selected_event_id == second.selected_event_id
    assert first.selected_event_id in {"ev_a", "ev_b"}


def test_event_cooldown_and_once_per_run_rules() -> None:
    events = [
        {
            "event_id": "ev_cd",
            "title": "Cooldown",
            "weight": 1,
            "once_per_run": False,
            "cooldown_steps": 2,
            "trigger": {"node_id_is": "n1"},
            "effects": {"money": 2},
        },
        {
            "event_id": "ev_once",
            "title": "Once",
            "weight": 1,
            "once_per_run": True,
            "cooldown_steps": 0,
            "trigger": {"node_id_is": "n2"},
            "effects": {"affection": 1},
        },
    ]

    state = normalize_state(default_initial_state())
    run_state = None

    first = advance_runtime_events(
        events_def=events,
        run_state=run_state,
        context=_context(step_id=1, node_id="n1"),
        state_before=state,
        state_after=state,
        state_delta={},
    )
    assert first.selected_event_id == "ev_cd"
    assert first.state_after["money"] == 52

    second = advance_runtime_events(
        events_def=events,
        run_state=first.run_state,
        context=_context(step_id=2, node_id="n1"),
        state_before=first.state_after,
        state_after=first.state_after,
        state_delta={},
    )
    third = advance_runtime_events(
        events_def=events,
        run_state=second.run_state,
        context=_context(step_id=3, node_id="n1"),
        state_before=second.state_after,
        state_after=second.state_after,
        state_delta={},
    )
    assert second.selected_event_id is None
    assert third.selected_event_id is None

    fourth = advance_runtime_events(
        events_def=events,
        run_state=third.run_state,
        context=_context(step_id=4, node_id="n1"),
        state_before=third.state_after,
        state_after=third.state_after,
        state_delta={},
    )
    assert fourth.selected_event_id == "ev_cd"
    assert fourth.state_after["money"] == 54

    once_first = advance_runtime_events(
        events_def=events,
        run_state=fourth.run_state,
        context=_context(step_id=5, node_id="n2"),
        state_before=fourth.state_after,
        state_after=fourth.state_after,
        state_delta={},
    )
    once_second = advance_runtime_events(
        events_def=events,
        run_state=once_first.run_state,
        context=_context(step_id=6, node_id="n2"),
        state_before=once_first.state_after,
        state_after=once_first.state_after,
        state_delta={},
    )
    assert once_first.selected_event_id == "ev_once"
    assert once_second.selected_event_id is None


def test_event_trigger_uses_current_node_and_state_after_semantics() -> None:
    events = [
        {
            "event_id": "ev_semantics",
            "title": "Semantics",
            "weight": 1,
            "once_per_run": False,
            "cooldown_steps": 0,
            "trigger": {
                "node_id_is": "n1",
                "day_in": [2],
                "slot_in": ["afternoon"],
            },
            "effects": {"knowledge": 1},
        }
    ]

    state_before = normalize_state(default_initial_state())
    state_after = dict(state_before)
    state_after["day"] = 2
    state_after["slot"] = "afternoon"

    matched = advance_runtime_events(
        events_def=events,
        run_state=None,
        context=_context(step_id=4, node_id="n1"),
        state_before=state_before,
        state_after=state_after,
        state_delta={"day": 1, "slot": "afternoon"},
    )
    assert matched.selected_event_id == "ev_semantics"

    blocked_by_node = advance_runtime_events(
        events_def=events,
        run_state=None,
        context=_context(step_id=4, node_id="n2"),
        state_before=state_before,
        state_after=state_after,
        state_delta={"day": 1, "slot": "afternoon"},
    )
    assert blocked_by_node.selected_event_id is None
