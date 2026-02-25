from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.session.story_choice_gating import PrereqKind, PrereqResult
from app.modules.session.story_runtime.models import (
    CandidateChoice,
    CandidateKind,
    MARKER_REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED,
    MARKER_REROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED,
    MARKER_REROUTE_LIMIT_REACHED_DEGRADED,
    SelectionResult,
    SelectionInputSource,
    StoryChoiceResolution,
    StoryFallbackTextPlan,
)


def _candidate_from_visible_choice(choice: dict) -> CandidateChoice:
    return CandidateChoice(
        id=str(choice.get("choice_id")),
        kind=CandidateKind.VISIBLE,
        label=str(choice.get("display_text")) if choice.get("display_text") is not None else None,
        action=dict((choice.get("action") or {})),
        effects=dict((choice.get("effects") or {})),
        effect_ops=dict((choice.get("effect_ops") or {})),
        prereq_spec=dict((choice.get("requires") or {})),
        next_node_id=str(choice.get("next_node_id") or ""),
        narration_skeleton=None,
        alias_visible_choice_id=None,
        source_ref="node_visible_choice",
    )


def _candidate_from_fallback_executor(executor: dict) -> CandidateChoice:
    return CandidateChoice(
        id=str(executor.get("id") or "fallback_executor"),
        kind=CandidateKind.FALLBACK_EXECUTOR,
        label=str(executor.get("label")) if executor.get("label") is not None else None,
        action=dict((executor.get("action") or {})) if isinstance(executor.get("action"), dict) else None,
        effects=dict((executor.get("effects") or {})),
        effect_ops=dict((executor.get("effect_ops") or {})),
        prereq_spec=dict((executor.get("prereq") or {})) if isinstance(executor.get("prereq"), dict) else None,
        next_node_id=(str(executor.get("next_node_id")) if executor.get("next_node_id") is not None else None),
        narration_skeleton=(str((executor.get("narration") or {}).get("skeleton")) if isinstance(executor.get("narration"), dict) and (executor.get("narration") or {}).get("skeleton") is not None else None),
        alias_visible_choice_id=None,
        source_ref="pack_fallback_executor",
    )


def _candidate_from_runtime_fallback_spec(
    *,
    fallback_spec: dict,
    fallback_next_node_id: str,
    current_node_id: str,
    fallback_executed_choice_id: Callable[[dict, str], str],
) -> CandidateChoice:
    executed_choice_id = fallback_executed_choice_id(fallback_spec, current_node_id)
    return CandidateChoice(
        id=executed_choice_id,
        kind=CandidateKind.FALLBACK_EXECUTOR,
        label=None,
        action=dict((fallback_spec.get("action") or {})),
        effects=dict((fallback_spec.get("effects") or {})),
        effect_ops=dict((fallback_spec.get("effect_ops") or {})),
        prereq_spec=dict((fallback_spec.get("prereq") or {})) if isinstance(fallback_spec.get("prereq"), dict) else None,
        next_node_id=fallback_next_node_id,
        narration_skeleton=None,
        alias_visible_choice_id=None,
        source_ref="runtime_fallback_spec",
    )


def _resolve_outward_fallback_reason(internal_reason: str | None, *, using_fallback: bool) -> str | None:
    if not using_fallback:
        return None
    code = str(internal_reason or "").upper()
    if code == "NO_INPUT":
        return "NO_INPUT"
    if code == "PREREQ_BLOCKED":
        return "BLOCKED"
    return "FALLBACK"


def resolve_story_choice(
    *,
    choice_id: str | None,
    player_input: str | None,
    visible_choices: list[dict],
    intents: list[dict] | None,
    current_story_state: dict,
    node_fallback_choice: dict | None,
    global_fallback_executor: dict | None,
    fallback_spec: dict,
    fallback_next_node_id: str,
    current_node_id: str,
    select_story_choice: Callable[..., SelectionResult],
    eval_prereq: Callable[[dict | None, dict | None], PrereqResult],
    fallback_executed_choice_id: Callable[[dict, str], str],
) -> StoryChoiceResolution:
    selected_choice: dict | None = None
    selected_visible_choice_id: str | None = None
    attempted_choice_id: str | None = None
    mapping_confidence: float | None = None
    mapping_note: str | None = None
    internal_reason: str | None = None
    input_source = SelectionInputSource.EMPTY
    markers: list[str] = []

    node_fallback_candidate = _candidate_from_visible_choice(node_fallback_choice) if isinstance(node_fallback_choice, dict) else None
    global_fallback_candidate = (
        _candidate_from_fallback_executor(global_fallback_executor)
        if isinstance(global_fallback_executor, dict)
        else None
    )
    runtime_fallback_candidate = _candidate_from_runtime_fallback_spec(
        fallback_spec=fallback_spec,
        fallback_next_node_id=fallback_next_node_id,
        current_node_id=current_node_id,
        fallback_executed_choice_id=fallback_executed_choice_id,
    )

    def _resolve_fallback_target() -> CandidateChoice:
        if node_fallback_candidate is not None:
            return node_fallback_candidate
        if global_fallback_candidate is not None:
            return global_fallback_candidate
        return runtime_fallback_candidate

    use_direct_fallback = False
    if choice_id is not None:
        input_source = SelectionInputSource.BUTTON
        attempted_choice_id = str(choice_id)
        selected_choice = next((c for c in visible_choices if str(c.get("choice_id")) == attempted_choice_id), None)
        if selected_choice is None:
            internal_reason = "INVALID_CHOICE_ID"
            use_direct_fallback = True
        else:
            selected_visible_choice_id = attempted_choice_id
    elif player_input is None or not str(player_input).strip():
        internal_reason = "NO_INPUT"
        use_direct_fallback = True
    else:
        input_source = SelectionInputSource.TEXT
        selection = select_story_choice(
            player_input=player_input,
            visible_choices=visible_choices,
            intents=intents,
            current_story_state=current_story_state,
        )
        attempted_choice_id = selection.attempted_choice_id
        mapping_confidence = selection.mapping_confidence
        mapping_note = selection.mapping_note
        internal_reason = selection.internal_reason
        input_source = selection.input_source
        if selection.use_fallback:
            use_direct_fallback = True
        else:
            selected_visible_choice_id = selection.selected_visible_choice_id
            if selected_visible_choice_id:
                selected_choice = next(
                    (c for c in visible_choices if str(c.get("choice_id")) == str(selected_visible_choice_id)),
                    None,
                )
            if selected_choice is None:
                use_direct_fallback = True
                internal_reason = internal_reason or "NO_MATCH"

    reroute_used = False
    selected_target: CandidateChoice | None = None
    selected_target_kind = CandidateKind.FALLBACK_EXECUTOR
    prereq_kind = PrereqKind.OK

    if use_direct_fallback:
        selected_target = _resolve_fallback_target()
        selected_target_kind = selected_target.kind
    else:
        selected_target = _candidate_from_visible_choice(selected_choice or {})
        selected_target_kind = CandidateKind.VISIBLE

    final_target = selected_target
    final_target_kind = final_target.kind
    prereq_result = eval_prereq(current_story_state, final_target.prereq_spec)
    prereq_kind = prereq_result.kind

    # Single reroute happens only from initial visible target.
    if not use_direct_fallback and selected_target.kind == CandidateKind.VISIBLE and prereq_result.kind != PrereqKind.OK:
        reroute_used = True
        internal_reason = "PREREQ_BLOCKED" if prereq_result.kind == PrereqKind.BLOCKED else "FALLBACK_CONFIG_INVALID"
        final_target = _resolve_fallback_target()
        final_target_kind = final_target.kind
        prereq_result = eval_prereq(current_story_state, final_target.prereq_spec)
        prereq_kind = prereq_result.kind
        if prereq_result.kind != PrereqKind.OK:
            markers.append(MARKER_REROUTE_LIMIT_REACHED_DEGRADED)
            if prereq_result.kind == PrereqKind.BLOCKED:
                markers.append(MARKER_REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED)
            else:
                markers.append(MARKER_REROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED)
            final_target = CandidateChoice(
                id=final_target.id,
                kind=final_target.kind,
                label=final_target.label,
                action={},
                effects={},
                effect_ops={},
                prereq_spec=final_target.prereq_spec,
                next_node_id=current_node_id,
                narration_skeleton=final_target.narration_skeleton,
                alias_visible_choice_id=final_target.alias_visible_choice_id,
                source_ref=final_target.source_ref,
            )
    elif use_direct_fallback and prereq_result.kind != PrereqKind.OK:
        if prereq_result.kind == PrereqKind.BLOCKED:
            markers.append(MARKER_REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED)
        else:
            markers.append(MARKER_REROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED)
        final_target = CandidateChoice(
            id=final_target.id,
            kind=final_target.kind,
            label=final_target.label,
            action={},
            effects={},
            effect_ops={},
            prereq_spec=final_target.prereq_spec,
            next_node_id=current_node_id,
            narration_skeleton=final_target.narration_skeleton,
            alias_visible_choice_id=final_target.alias_visible_choice_id,
            source_ref=final_target.source_ref,
        )

    executed_choice_id = final_target.id
    resolved_choice_id = executed_choice_id
    next_node_id = str(final_target.next_node_id or current_node_id)
    final_action_for_state = dict(final_target.action or {})
    effects_for_state = dict(final_target.effects or {})
    effect_ops_for_state = dict(final_target.effect_ops or {})

    using_fallback = (
        selected_visible_choice_id is None
        or final_target.kind != CandidateKind.VISIBLE
        or str(final_target.id) != str(selected_visible_choice_id)
    )
    fallback_reason_code = _resolve_outward_fallback_reason(internal_reason, using_fallback=using_fallback)

    selected_choice_dict = selected_choice if selected_choice is not None else None
    key_decision = bool(selected_choice_dict.get("is_key_decision", False)) if selected_choice_dict and not using_fallback else False

    return StoryChoiceResolution(
        compiled_action=None,
        selected_choice=selected_choice_dict,
        attempted_choice_id=attempted_choice_id,
        selected_visible_choice_id=selected_visible_choice_id,
        mapping_confidence=mapping_confidence,
        mapping_note=mapping_note,
        fallback_reason_code=fallback_reason_code,
        internal_reason=internal_reason,
        input_source=input_source,
        using_fallback=using_fallback,
        reroute_used=reroute_used,
        final_action_for_state=final_action_for_state,
        effects_for_state=effects_for_state,
        effect_ops_for_state=effect_ops_for_state,
        next_node_id=next_node_id,
        executed_choice_id=executed_choice_id,
        resolved_choice_id=resolved_choice_id,
        key_decision=key_decision,
        selected_target_kind=selected_target_kind,
        final_target_kind=final_target_kind,
        markers=markers,
        prereq_kind=prereq_kind,
        fallback_executor_skeleton_text=final_target.narration_skeleton if final_target.kind == CandidateKind.FALLBACK_EXECUTOR else None,
    )


def build_fallback_reasons(
    *,
    using_fallback: bool,
    internal_reason: str | None,
    fallback_markers: list[str],
    extra_markers: list[str] | None = None,
) -> list[str]:
    fallback_reasons: list[str] = []
    if using_fallback:
        fallback_reasons.append(str(internal_reason or "FALLBACK"))
    for marker in fallback_markers:
        if marker not in fallback_reasons:
            fallback_reasons.append(marker)
    for marker in (extra_markers or []):
        if marker not in fallback_reasons:
            fallback_reasons.append(marker)
    return fallback_reasons


def build_fallback_text_plan(
    *,
    using_fallback: bool,
    fallback_spec: dict,
    fallback_reason_code: str | None,
    locale: str,
    fallback_builtin_text: str,
    select_fallback_text_variant: Callable[[dict, str | None, str], str | None],
    executor_skeleton_text: str | None = None,
) -> StoryFallbackTextPlan:
    if not using_fallback:
        return StoryFallbackTextPlan(
            fallback_variant_text=None,
            fallback_skeleton_text=None,
            text_source=None,
        )

    if executor_skeleton_text:
        return StoryFallbackTextPlan(
            fallback_variant_text=executor_skeleton_text,
            fallback_skeleton_text=executor_skeleton_text,
            text_source="executor_skeleton",
        )

    fallback_variant_text = select_fallback_text_variant(fallback_spec, fallback_reason_code, locale)
    if fallback_variant_text:
        return StoryFallbackTextPlan(
            fallback_variant_text=fallback_variant_text,
            fallback_skeleton_text=fallback_variant_text,
            text_source="pack_variant",
        )

    return StoryFallbackTextPlan(
        fallback_variant_text=None,
        fallback_skeleton_text=fallback_builtin_text,
        text_source="system_builtin",
    )
