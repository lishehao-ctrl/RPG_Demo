from __future__ import annotations

from typing import Any

from app.db.models import Session as StorySession
from app.modules.session.story_runtime.models import (
    EndingResolution,
    EventResolution,
    QuestStepEvent,
    QuestUpdateResult,
    RuntimeEventContext,
    StoryChoiceResolution,
    StoryRuntimeContext,
)


def phase_apply_quest_updates(
    *,
    context: StoryRuntimeContext,
    resolution: StoryChoiceResolution,
    state_before: dict,
    state_after: dict,
    state_delta: dict,
    deps: Any,
) -> QuestUpdateResult:
    quest_event = QuestStepEvent(
        current_node_id=context.current_node_id,
        next_node_id=resolution.next_node_id,
        executed_choice_id=resolution.executed_choice_id,
        action_id=(
            str((resolution.final_action_for_state or {}).get("action_id"))
            if (resolution.final_action_for_state or {}).get("action_id") is not None
            else None
        ),
        fallback_used=bool(resolution.using_fallback),
    )
    return deps.advance_quest_state(
        quests_def=(context.runtime_pack.get("quests") or []),
        quest_state=(state_after or {}).get("quest_state"),
        event=quest_event,
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
    )


def phase_apply_runtime_events(
    *,
    sess: StorySession,
    context: StoryRuntimeContext,
    resolution: StoryChoiceResolution,
    state_before: dict,
    state_after: dict,
    state_delta: dict,
    deps: Any,
) -> EventResolution:
    run_state = (state_after or {}).get("run_state") if isinstance(state_after, dict) else {}
    next_step_id = int((run_state or {}).get("step_index", 0)) + 1
    event_context = RuntimeEventContext(
        session_id=str(sess.id),
        step_id=next_step_id,
        story_node_id=context.current_node_id,
        next_node_id=resolution.next_node_id,
        executed_choice_id=resolution.executed_choice_id,
        action_id=(
            str((resolution.final_action_for_state or {}).get("action_id"))
            if (resolution.final_action_for_state or {}).get("action_id") is not None
            else None
        ),
        fallback_used=bool(resolution.using_fallback),
    )
    return deps.advance_runtime_events(
        events_def=(context.runtime_pack.get("events") or []),
        run_state=run_state,
        context=event_context,
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
    )


def phase_resolve_ending(
    *,
    context: StoryRuntimeContext,
    resolution: StoryChoiceResolution,
    state_after: dict,
    run_state: dict,
    deps: Any,
) -> EndingResolution:
    return deps.resolve_run_ending(
        endings_def=(context.runtime_pack.get("endings") or []),
        run_config=(context.runtime_pack.get("run_config") or {}),
        run_state=run_state,
        next_node_id=resolution.next_node_id,
        state_after=state_after,
        quest_state=(state_after or {}).get("quest_state"),
    )
