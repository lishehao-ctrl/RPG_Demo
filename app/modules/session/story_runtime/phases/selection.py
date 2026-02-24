from __future__ import annotations

from typing import Any

from app.db.models import Session as StorySession
from app.modules.narrative.state_engine import normalize_state
from app.modules.session.story_choice_gating import eval_prereq
from app.modules.session.story_runtime.decisions import resolve_story_choice
from app.modules.session.story_runtime.models import SelectionInputSource, StoryChoiceResolution, StoryRuntimeContext
from app.modules.session.story_runtime.phases.context import resolve_global_fallback_executor, resolve_node_fallback_choice


def phase_resolve_choice(
    *,
    sess: StorySession,
    player_input: str | None,
    choice_id: str | None,
    context: StoryRuntimeContext,
    deps: Any,
) -> StoryChoiceResolution:
    return resolve_story_choice(
        choice_id=choice_id,
        player_input=player_input,
        visible_choices=context.visible_choices,
        intents=context.intents,
        current_story_state=normalize_state(sess.state_json),
        node_fallback_choice=resolve_node_fallback_choice(context),
        global_fallback_executor=resolve_global_fallback_executor(context),
        fallback_spec=context.fallback_spec,
        fallback_next_node_id=context.fallback_next_node_id,
        current_node_id=context.current_node_id,
        select_story_choice=deps.select_story_choice,
        eval_prereq=eval_prereq,
        fallback_executed_choice_id=deps.fallback_executed_choice_id,
    )


def resolve_input_mode_for_prompt(resolution: StoryChoiceResolution, player_input: str | None) -> str:
    if resolution.input_source == SelectionInputSource.TEXT and str(player_input or "").strip():
        return "free_input"
    return "choice_click"
