from __future__ import annotations

from typing import Any

from app.config import settings
from app.db.models import Session as StorySession
from app.modules.narrative.state_engine import normalize_state
from app.modules.session.story_choice_gating import eval_prereq
from app.modules.session.story_runtime.decisions import resolve_story_choice
from app.modules.session.story_runtime.models import SelectionInputSource, StoryChoiceResolution, StoryRuntimeContext
from app.modules.session.story_runtime.phases.context import resolve_global_fallback_executor, resolve_node_fallback_choice
from app.modules.session.story_runtime.phases.input_policy import apply_input_policy


def phase_resolve_choice(
    *,
    sess: StorySession,
    player_input: str | None,
    choice_id: str | None,
    context: StoryRuntimeContext,
    deps: Any,
) -> StoryChoiceResolution:
    player_input_sanitized = player_input
    policy_blocked = False
    policy_reason = None
    if choice_id is None and str(player_input or "").strip():
        max_chars = max(256, int(settings.story_input_max_chars))
        player_input_sanitized, policy_blocked, policy_reason = apply_input_policy(
            player_input,
            max_chars=max_chars,
        )

    if policy_blocked:
        blocked_resolution = resolve_story_choice(
            choice_id="__policy_blocked__",
            player_input=None,
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
        blocked_resolution.attempted_choice_id = None
        blocked_resolution.mapping_confidence = 0.0
        blocked_resolution.mapping_note = f"INPUT_POLICY_BLOCKED:{policy_reason or 'POLICY'}"
        blocked_resolution.internal_reason = "POLICY_BLOCKED_INPUT"
        blocked_resolution.fallback_reason_code = "FALLBACK"
        blocked_resolution.input_source = SelectionInputSource.TEXT
        return blocked_resolution

    return resolve_story_choice(
        choice_id=choice_id,
        player_input=player_input_sanitized,
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
