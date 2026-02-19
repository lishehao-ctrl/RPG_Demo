from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ActionLog, Session as StorySession
from app.modules.llm.prompts import build_fallback_polish_prompt, build_story_narration_prompt
from app.modules.narrative.state_engine import apply_action as apply_state_action
from app.modules.narrative.state_engine import normalize_state
from app.modules.session.story_choice_gating import eval_prereq
from app.modules.session.story_runtime.decisions import (
    build_fallback_reasons,
    build_fallback_text_plan,
    resolve_story_choice,
)
from app.modules.session.story_runtime.models import (
    QuestStepEvent,
    QuestUpdateResult,
    StoryChoiceResolution,
    StoryRuntimeContext,
)
from app.modules.session.story_runtime.translate import build_choice_resolution_matched_rules, build_story_step_response_payload
from app.modules.story.fallback_narration import (
    build_fallback_narration_context,
    contains_internal_story_tokens,
    extract_skeleton_anchor_tokens,
    safe_polish_text,
)


@dataclass(slots=True)
class StoryRuntimePipelineDeps:
    load_story_pack: Callable[[Session, str, int | None], Any]
    normalize_pack_for_runtime: Callable[[dict | None], dict]
    story_node: Callable[[dict, str], dict | None]
    resolve_runtime_fallback: Callable[[dict, str, set[str]], tuple[dict, str, list[str]]]
    select_story_choice: Callable[..., Any]
    fallback_executed_choice_id: Callable[[dict, str], str]
    select_fallback_text_variant: Callable[[dict, str | None, str | None], str | None]
    sum_step_usage: Callable[[Session, uuid.UUID, uuid.UUID], tuple[int, int]]
    step_provider: Callable[[Session, uuid.UUID, uuid.UUID], str]
    apply_choice_effects: Callable[[dict, dict | None], dict]
    compute_state_delta: Callable[[dict, dict], dict]
    format_effects_suffix: Callable[[dict | None], str]
    story_choices_for_response: Callable[[dict, dict | None], list[dict]]
    advance_quest_state: Callable[..., QuestUpdateResult]
    summarize_quest_for_narration: Callable[[list[dict], dict | None], dict]
    auto_end_if_run_complete: Callable[[Session, StorySession, dict], None]
    llm_runtime_getter: Callable[[], Any]


@dataclass(slots=True)
class _NarrationPhaseResult:
    narrative_text: str
    tokens_in: int
    tokens_out: int
    provider_name: str


def _phase_load_runtime_context(
    *,
    db: Session,
    sess: StorySession,
    deps: StoryRuntimePipelineDeps,
) -> StoryRuntimeContext:
    story_row = deps.load_story_pack(db, sess.story_id, sess.story_version)
    runtime_pack = deps.normalize_pack_for_runtime(story_row.pack_json or {})
    if not sess.current_node_id:
        raise HTTPException(status_code=400, detail={"code": "STORY_NODE_MISSING"})

    current_node_id = str(sess.current_node_id)
    node = deps.story_node(runtime_pack, current_node_id)
    if not node:
        raise HTTPException(status_code=400, detail={"code": "STORY_NODE_MISSING"})

    node_ids = {
        str(n.get("node_id"))
        for n in (runtime_pack.get("nodes") or [])
        if (n or {}).get("node_id") is not None
    }
    visible_choices = [dict(c) for c in (node.get("choices") or []) if isinstance(c, dict)]
    fallback_spec, fallback_next_node_id, fallback_markers = deps.resolve_runtime_fallback(
        node=node,
        current_node_id=current_node_id,
        node_ids=node_ids,
    )
    fallback_executors = [
        dict(item)
        for item in (runtime_pack.get("fallback_executors") or [])
        if isinstance(item, dict)
    ]
    return StoryRuntimeContext(
        runtime_pack=runtime_pack,
        current_node_id=current_node_id,
        node=node,
        visible_choices=visible_choices,
        fallback_spec=fallback_spec,
        fallback_next_node_id=fallback_next_node_id,
        fallback_markers=fallback_markers,
        intents=[dict(v) for v in (node.get("intents") or []) if isinstance(v, dict)],
        fallback_executors=fallback_executors,
        node_fallback_choice_id=(
            str(node.get("node_fallback_choice_id"))
            if (node.get("node_fallback_choice_id") is not None)
            else None
        ),
        global_fallback_choice_id=(
            str(runtime_pack.get("global_fallback_choice_id"))
            if runtime_pack.get("global_fallback_choice_id") is not None
            else None
        ),
    )


def _resolve_node_fallback_choice(context: StoryRuntimeContext) -> dict | None:
    if not context.node_fallback_choice_id:
        return None
    return next(
        (c for c in context.visible_choices if str(c.get("choice_id")) == str(context.node_fallback_choice_id)),
        None,
    )


def _resolve_global_fallback_executor(context: StoryRuntimeContext) -> dict | None:
    if not context.global_fallback_choice_id:
        return None
    return next(
        (e for e in context.fallback_executors if str(e.get("id")) == str(context.global_fallback_choice_id)),
        None,
    )


def _phase_resolve_choice(
    *,
    sess: StorySession,
    player_input: str | None,
    choice_id: str | None,
    context: StoryRuntimeContext,
    deps: StoryRuntimePipelineDeps,
) -> StoryChoiceResolution:
    return resolve_story_choice(
        choice_id=choice_id,
        player_input=player_input,
        visible_choices=context.visible_choices,
        intents=context.intents,
        current_story_state=normalize_state(sess.state_json),
        node_fallback_choice=_resolve_node_fallback_choice(context),
        global_fallback_executor=_resolve_global_fallback_executor(context),
        fallback_spec=context.fallback_spec,
        fallback_next_node_id=context.fallback_next_node_id,
        current_node_id=context.current_node_id,
        select_story_choice=deps.select_story_choice,
        eval_prereq=eval_prereq,
        fallback_executed_choice_id=deps.fallback_executed_choice_id,
    )


def _phase_compute_state_transition(
    *,
    sess: StorySession,
    final_action_for_state: dict,
    effects_for_state: dict,
    deps: StoryRuntimePipelineDeps,
) -> tuple[dict, dict, dict]:
    state_before = normalize_state(sess.state_json)
    state_after_base, _ = apply_state_action(state_before, final_action_for_state)
    state_after = deps.apply_choice_effects(state_after_base, effects_for_state)
    state_delta = deps.compute_state_delta(state_before, state_after)
    sess.state_json = state_after
    return state_before, state_after, state_delta


def _phase_build_polish_inputs(
    *,
    using_fallback: bool,
    fallback_skeleton_text: str | None,
    locale: str,
    current_node_id: str,
    fallback_reason_code: str | None,
    player_input: str | None,
    mapping_note: str | None,
    attempted_choice_id: str | None,
    selected_choice: dict | None,
    visible_choices: list[dict],
    state_after: dict,
) -> tuple[dict | None, list[str] | None]:
    if not using_fallback or not fallback_skeleton_text or not settings.story_fallback_llm_enabled:
        return None, None

    attempted_choice_label = (
        str(selected_choice.get("display_text"))
        if selected_choice is not None and selected_choice.get("display_text") is not None
        else None
    )
    narration_ctx = build_fallback_narration_context(
        locale=locale,
        node_id=current_node_id,
        fallback_reason=fallback_reason_code,
        player_input=player_input,
        mapping_note=mapping_note,
        attempted_choice_id=attempted_choice_id,
        attempted_choice_label=attempted_choice_label,
        visible_choices=visible_choices,
        state_snippet_source=state_after,
        skeleton_text=fallback_skeleton_text,
    )
    anchor_tokens = extract_skeleton_anchor_tokens(fallback_skeleton_text, locale)
    return narration_ctx, anchor_tokens


def _phase_generate_narrative(
    *,
    db: Session,
    sess: StorySession,
    deps: StoryRuntimePipelineDeps,
    using_fallback: bool,
    fallback_skeleton_text: str | None,
    fallback_builtin_text: str,
    current_node_id: str,
    next_node_id: str,
    node: dict,
    next_node: dict,
    attempted_choice_id: str | None,
    executed_choice_id: str,
    resolved_choice_id: str,
    fallback_reason_code: str | None,
    mapping_confidence: float | None,
    state_before: dict,
    state_delta: dict,
    state_after: dict,
    quest_summary: dict | None,
    fallback_narration_ctx: dict | None,
    fallback_anchor_tokens: list[str] | None,
) -> _NarrationPhaseResult:
    step_id = uuid.uuid4()
    llm_runtime = deps.llm_runtime_getter()
    story_prompt_payload = {
        "from_node_id": current_node_id,
        "to_node_id": next_node_id,
        "from_scene": node.get("scene_brief", ""),
        "to_scene": next_node.get("scene_brief", ""),
        "attempted_choice_id": attempted_choice_id,
        "executed_choice_id": executed_choice_id,
        "resolved_choice_id": resolved_choice_id,
        "fallback_reason": fallback_reason_code,
        "fallback_used": using_fallback,
        "mapping_confidence": mapping_confidence,
        "state_before": state_before,
        "state_delta": state_delta,
        "state_after": state_after,
        "quest_summary": quest_summary or {},
    }
    llm_narrative, _ = llm_runtime.narrative_with_fallback(
        db,
        prompt=build_story_narration_prompt(story_prompt_payload),
        session_id=sess.id,
        step_id=step_id,
    )
    if using_fallback:
        narrative_text = fallback_skeleton_text or fallback_builtin_text
        if settings.story_fallback_llm_enabled:
            polish_prompt = build_fallback_polish_prompt(fallback_narration_ctx or {}, narrative_text)
            candidate_text = ""
            try:
                polish_narrative, _ = llm_runtime.narrative_with_fallback(
                    db,
                    prompt=polish_prompt,
                    session_id=sess.id,
                    step_id=step_id,
                )
                candidate_text = polish_narrative.narrative_text
            except Exception:  # noqa: BLE001
                candidate_text = ""
            narrative_text = safe_polish_text(
                candidate_text,
                narrative_text,
                max_chars=int(settings.story_fallback_llm_max_chars),
                required_anchor_tokens=fallback_anchor_tokens,
                enforce_error_phrase_denylist=True,
            )
    else:
        narrative_text = llm_narrative.narrative_text

    db.flush()
    tokens_in, tokens_out = deps.sum_step_usage(db, sess.id, step_id)
    provider_name = deps.step_provider(db, sess.id, step_id)
    return _NarrationPhaseResult(
        narrative_text=narrative_text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        provider_name=provider_name,
    )


def _phase_apply_quest_updates(
    *,
    context: StoryRuntimeContext,
    resolution: StoryChoiceResolution,
    state_before: dict,
    state_after: dict,
    state_delta: dict,
    deps: StoryRuntimePipelineDeps,
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


def _sanitize_fallback_narrative_text(
    *,
    narrative_text: str,
    fallback_skeleton_text: str | None,
    fallback_builtin_text: str,
) -> str:
    if not contains_internal_story_tokens(narrative_text):
        return narrative_text

    baseline = fallback_skeleton_text or fallback_builtin_text
    if contains_internal_story_tokens(baseline):
        baseline = fallback_builtin_text
    return baseline


def run_story_runtime_pipeline(
    *,
    db: Session,
    sess: StorySession,
    choice_id: str | None,
    player_input: str | None,
    fallback_builtin_text: str,
    deps: StoryRuntimePipelineDeps,
) -> dict:
    context = _phase_load_runtime_context(db=db, sess=sess, deps=deps)
    resolution = _phase_resolve_choice(
        sess=sess,
        player_input=player_input,
        choice_id=choice_id,
        context=context,
        deps=deps,
    )

    next_node = deps.story_node(context.runtime_pack, resolution.next_node_id)
    if not next_node:
        raise HTTPException(status_code=400, detail={"code": "INVALID_NEXT_NODE"})

    locale = settings.story_default_locale
    fallback_text_plan = build_fallback_text_plan(
        using_fallback=resolution.using_fallback,
        fallback_spec=context.fallback_spec,
        fallback_reason_code=(resolution.internal_reason or resolution.fallback_reason_code),
        locale=locale,
        fallback_builtin_text=fallback_builtin_text,
        select_fallback_text_variant=deps.select_fallback_text_variant,
        executor_skeleton_text=resolution.fallback_executor_skeleton_text,
    )
    fallback_skeleton_text = fallback_text_plan.fallback_skeleton_text

    fallback_reasons = build_fallback_reasons(
        using_fallback=resolution.using_fallback,
        internal_reason=resolution.internal_reason,
        fallback_markers=context.fallback_markers,
        extra_markers=resolution.markers,
    )
    state_before, state_after, state_delta = _phase_compute_state_transition(
        sess=sess,
        final_action_for_state=resolution.final_action_for_state,
        effects_for_state=resolution.effects_for_state,
        deps=deps,
    )
    quest_update = _phase_apply_quest_updates(
        context=context,
        resolution=resolution,
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        deps=deps,
    )
    state_after = normalize_state(quest_update.state_after)
    state_delta = deps.compute_state_delta(state_before, state_after)
    sess.state_json = state_after
    quest_summary = deps.summarize_quest_for_narration(
        context.runtime_pack.get("quests") or [],
        (state_after or {}).get("quest_state"),
    )

    fallback_narration_ctx, fallback_anchor_tokens = _phase_build_polish_inputs(
        using_fallback=resolution.using_fallback,
        fallback_skeleton_text=fallback_skeleton_text,
        locale=locale,
        current_node_id=context.current_node_id,
        fallback_reason_code=resolution.fallback_reason_code,
        player_input=player_input,
        mapping_note=resolution.mapping_note,
        attempted_choice_id=resolution.attempted_choice_id,
        selected_choice=resolution.selected_choice,
        visible_choices=context.visible_choices,
        state_after=state_after,
    )

    narration_result = _phase_generate_narrative(
        db=db,
        sess=sess,
        deps=deps,
        using_fallback=resolution.using_fallback,
        fallback_skeleton_text=fallback_skeleton_text,
        fallback_builtin_text=fallback_builtin_text,
        current_node_id=context.current_node_id,
        next_node_id=resolution.next_node_id,
        node=context.node,
        next_node=next_node,
        attempted_choice_id=resolution.attempted_choice_id,
        executed_choice_id=resolution.executed_choice_id,
        resolved_choice_id=resolution.resolved_choice_id,
        fallback_reason_code=resolution.fallback_reason_code,
        mapping_confidence=resolution.mapping_confidence,
        state_before=state_before,
        state_delta=state_delta,
        state_after=state_after,
        quest_summary=quest_summary,
        fallback_narration_ctx=fallback_narration_ctx,
        fallback_anchor_tokens=fallback_anchor_tokens,
    )
    narrative_text = narration_result.narrative_text

    if resolution.using_fallback and settings.story_fallback_show_effects_in_text:
        effects_suffix = deps.format_effects_suffix(resolution.effects_for_state)
        if effects_suffix:
            narrative_text = f"{narrative_text}{effects_suffix}"
    if resolution.using_fallback:
        narrative_text = _sanitize_fallback_narrative_text(
            narrative_text=narrative_text,
            fallback_skeleton_text=fallback_skeleton_text,
            fallback_builtin_text=fallback_builtin_text,
        )

    response_choices = deps.story_choices_for_response(next_node, state_after)

    try:
        sess.current_node_id = uuid.UUID(resolution.next_node_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "INVALID_NEXT_NODE_ID"}) from exc
    sess.updated_at = datetime.utcnow()

    matched_rules = build_choice_resolution_matched_rules(
        attempted_choice_id=resolution.attempted_choice_id,
        executed_choice_id=resolution.executed_choice_id,
        resolved_choice_id=resolution.resolved_choice_id,
        fallback_reason_code=resolution.internal_reason,
        mapping_confidence=resolution.mapping_confidence,
        mapping_note=resolution.mapping_note,
    )
    matched_rules.extend(quest_update.matched_rules or [])

    log = ActionLog(
        session_id=sess.id,
        node_id=None,
        story_node_id=context.current_node_id,
        story_choice_id=resolution.executed_choice_id,
        player_input=(player_input or ""),
        user_raw_input=(player_input or ""),
        proposed_action={},
        final_action=resolution.final_action_for_state,
        fallback_used=resolution.using_fallback,
        fallback_reasons=fallback_reasons,
        action_confidence=resolution.mapping_confidence,
        key_decision=resolution.key_decision,
        classification={},
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        matched_rules=matched_rules,
    )
    db.add(log)
    deps.auto_end_if_run_complete(db, sess, state_after)

    response_payload = build_story_step_response_payload(
        story_node_id=resolution.next_node_id,
        attempted_choice_id=resolution.attempted_choice_id,
        executed_choice_id=resolution.executed_choice_id,
        resolved_choice_id=resolution.resolved_choice_id,
        fallback_used=resolution.using_fallback,
        fallback_reason=resolution.fallback_reason_code,
        mapping_confidence=resolution.mapping_confidence,
        narrative_text=narrative_text,
        choices=response_choices,
        tokens_in=narration_result.tokens_in,
        tokens_out=narration_result.tokens_out,
        provider_name=narration_result.provider_name,
    )
    response_payload["node_id"] = uuid.uuid4()
    return response_payload
