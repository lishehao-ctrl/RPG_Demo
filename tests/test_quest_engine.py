from __future__ import annotations

from app.modules.narrative.quest_engine import (
    advance_quest_state,
    apply_quest_rewards,
    init_quest_state,
)
from app.modules.narrative.state_engine import default_initial_state, normalize_state
from app.modules.session.story_runtime.models import QuestStepEvent


def _stage_quest_def() -> list[dict]:
    return [
        {
            "quest_id": "q1",
            "title": "Opening Arc",
            "auto_activate": True,
            "stages": [
                {
                    "stage_id": "s1",
                    "title": "Stage One",
                    "milestones": [
                        {
                            "milestone_id": "m1",
                            "title": "Choose c1",
                            "when": {"executed_choice_id_is": "c1"},
                            "rewards": {"money": 4},
                        },
                        {
                            "milestone_id": "m2",
                            "title": "Use fallback once",
                            "when": {"fallback_used_is": True},
                            "rewards": {"affection": 1},
                        },
                    ],
                    "stage_rewards": {"knowledge": 2},
                },
                {
                    "stage_id": "s2",
                    "title": "Stage Two",
                    "milestones": [
                        {
                            "milestone_id": "m3",
                            "title": "Work once",
                            "when": {"action_id_is": "work"},
                            "rewards": {"money": 3},
                        }
                    ],
                    "stage_rewards": {"energy": 1},
                },
            ],
            "completion_rewards": {"money": 5},
        }
    ]


def test_init_quest_state_activates_first_stage() -> None:
    quest_state = init_quest_state(_stage_quest_def())

    assert quest_state["active_quests"] == ["q1"]
    q1 = quest_state["quests"]["q1"]
    assert q1["status"] == "active"
    assert q1["current_stage_index"] == 0
    assert q1["current_stage_id"] == "s1"
    assert q1["stages"]["s1"]["status"] == "active"
    assert q1["stages"]["s2"]["status"] == "inactive"


def test_advance_quest_state_stage_progression_and_rewards_once() -> None:
    quests_def = _stage_quest_def()
    before = normalize_state(default_initial_state())
    base_after = normalize_state(before)

    first = advance_quest_state(
        quests_def=quests_def,
        quest_state=init_quest_state(quests_def),
        event=QuestStepEvent(
            current_node_id="n1",
            next_node_id="n2",
            executed_choice_id="c1",
            action_id="study",
            fallback_used=False,
        ),
        state_before=before,
        state_after=base_after,
        state_delta={},
    )
    q1_first = first.quest_state["quests"]["q1"]
    assert first.state_after["money"] == 54
    assert q1_first["current_stage_id"] == "s1"
    assert q1_first["stages"]["s1"]["milestones"]["m1"]["done"] is True
    assert q1_first["stages"]["s1"]["milestones"]["m2"]["done"] is False

    second = advance_quest_state(
        quests_def=quests_def,
        quest_state=first.quest_state,
        event=QuestStepEvent(
            current_node_id="n2",
            next_node_id="n2",
            executed_choice_id="__fallback__:n2",
            action_id="rest",
            fallback_used=True,
        ),
        state_before=first.state_after,
        state_after=first.state_after,
        state_delta={},
    )
    q1_second = second.quest_state["quests"]["q1"]
    assert q1_second["current_stage_id"] == "s2"
    assert q1_second["stages"]["s1"]["status"] == "completed"
    assert q1_second["stages"]["s2"]["status"] == "active"
    event_types_second = [item["event_type"] for item in second.matched_rules]
    assert "milestone_completed" in event_types_second
    assert "stage_completed" in event_types_second
    assert "stage_activated" in event_types_second
    assert second.state_after["knowledge"] == 2
    assert second.state_after["affection"] == 1

    third = advance_quest_state(
        quests_def=quests_def,
        quest_state=second.quest_state,
        event=QuestStepEvent(
            current_node_id="n2",
            next_node_id="n3",
            executed_choice_id="c3",
            action_id="work",
            fallback_used=False,
        ),
        state_before=second.state_after,
        state_after=second.state_after,
        state_delta={},
    )
    q1_third = third.quest_state["quests"]["q1"]
    assert q1_third["status"] == "completed"
    assert "q1" in third.quest_state["completed_quests"]
    event_types_third = [item["event_type"] for item in third.matched_rules]
    assert "milestone_completed" in event_types_third
    assert "stage_completed" in event_types_third
    assert "quest_completed" in event_types_third

    # s2 milestone reward +3, s2 stage reward +1 energy, quest completion +5 money
    assert third.state_after["money"] == 62
    assert third.state_after["energy"] == 81

    fourth = advance_quest_state(
        quests_def=quests_def,
        quest_state=third.quest_state,
        event=QuestStepEvent(
            current_node_id="n3",
            next_node_id="n3",
            executed_choice_id="c3",
            action_id="work",
            fallback_used=False,
        ),
        state_before=third.state_after,
        state_after=third.state_after,
        state_delta={},
    )
    assert fourth.state_after == third.state_after
    assert fourth.matched_rules == []


def test_later_stage_milestone_does_not_fire_before_stage_activation() -> None:
    quests_def = _stage_quest_def()
    before = normalize_state(default_initial_state())

    result = advance_quest_state(
        quests_def=quests_def,
        quest_state=init_quest_state(quests_def),
        event=QuestStepEvent(
            current_node_id="n1",
            next_node_id="n2",
            executed_choice_id="c3",
            action_id="work",
            fallback_used=False,
        ),
        state_before=before,
        state_after=before,
        state_delta={},
    )

    q1 = result.quest_state["quests"]["q1"]
    assert q1["current_stage_id"] == "s1"
    assert q1["stages"]["s2"]["milestones"]["m3"]["done"] is False
    assert result.matched_rules == []


def test_advance_quest_state_truncates_recent_event_history() -> None:
    quests_def = []
    for idx in range(11):
        quests_def.append(
            {
                "quest_id": f"q{idx}",
                "title": f"Quest {idx}",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "Stage 1",
                        "milestones": [
                            {
                                "milestone_id": f"m{idx}",
                                "title": "Fallback once",
                                "when": {"fallback_used_is": True},
                            }
                        ],
                    }
                ],
            }
        )

    before = normalize_state(default_initial_state())
    result = advance_quest_state(
        quests_def=quests_def,
        quest_state=init_quest_state(quests_def),
        event=QuestStepEvent(
            current_node_id="n1",
            next_node_id="n1",
            executed_choice_id="__fallback__:n1",
            action_id="rest",
            fallback_used=True,
        ),
        state_before=before,
        state_after=before,
        state_delta={},
    )
    recent_events = result.quest_state["recent_events"]
    assert len(recent_events) == 20
    assert result.quest_state["event_seq"] == 33
    assert int(recent_events[0]["seq"]) == 14


def test_apply_quest_rewards_uses_int_toward_zero() -> None:
    state = normalize_state(default_initial_state())
    out = apply_quest_rewards(state, {"energy": 1.9, "affection": -1.9})
    assert out["energy"] == 81
    assert out["affection"] == -1
