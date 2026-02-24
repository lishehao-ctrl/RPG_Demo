from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Session as StorySession
from app.modules.session.story_runtime.models import EndingResolution, EventResolution
from app.modules.session.story_runtime.phases.observability import (
    build_impact_brief_for_prompt,
    build_impact_sources_for_prompt,
    build_quest_nudge,
    choose_quest_nudge_text,
    compact_run_ending_for_prompt,
    compact_runtime_event_for_prompt,
    compact_state_delta_for_prompt,
    compact_state_snapshot_for_prompt,
    derive_intent_action_alignment,
    safe_int,
)
from app.modules.story.fallback_narration import (
    build_free_input_fallback_narrative_text,
    build_fallback_narration_context,
    contains_internal_story_tokens,
    extract_skeleton_anchor_tokens,
    naturalize_narrative_tone,
    sanitize_rejecting_tone,
    safe_polish_text,
)


@dataclass(slots=True)
class NarrationPhaseResult:
    narrative_text: str


_FREE_INPUT_JARGON_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bmapped to\b", re.IGNORECASE), "led to"),
    (re.compile(r"\bmaps to\b", re.IGNORECASE), "leads to"),
    (re.compile(r"\bmapping\b", re.IGNORECASE), "interpretation"),
    (re.compile(r"\bchoice_id\b", re.IGNORECASE), "choice"),
    (re.compile(r"\bselected_action_id\b", re.IGNORECASE), "action"),
    (re.compile(r"\bfallback_reason\b", re.IGNORECASE), "reason"),
    (re.compile(r"\bintent\b", re.IGNORECASE), "approach"),
    (re.compile(r"\bconfidence\b", re.IGNORECASE), "certainty"),
)
_FREE_INPUT_JARGON_DETECT_RE = re.compile(
    r"\bmapped to\b|\bmaps to\b|\bmapping\b|\bmapped\b|\bintent\b|\bchoice_id\b|"
    r"\bselected_action_id\b|\bfallback_reason\b|\bconfidence\b|"
    r"\bfor this turn\b|\bthis turn\b|\bthe scene\b|\bstory keeps moving\b",
    re.IGNORECASE,
)


def split_first_sentence(text: str) -> tuple[str, str]:
    marker = re.search(r"[.!?]", text)
    if marker is None:
        return text, ""
    end = marker.end()
    return text[:end], text[end:]


def build_free_input_lead_sentence(
    *,
    player_input_raw: str | None,
    selected_choice_label: str | None,
    selected_action_id: str | None,
) -> str:
    choice_label = " ".join(str(selected_choice_label or "").split())[:72].strip()
    if choice_label:
        return f"You act on your own read of the moment, and {choice_label} immediately shapes what happens next."
    action_label = " ".join(str((selected_action_id or "").replace("_", " ")).split())[:48].strip()
    if action_label:
        return f"You follow your instinct, and {action_label} drives the next beat right away."
    player_text = " ".join(str(player_input_raw or "").split())[:96].strip()
    if player_text:
        return "You follow your own call, and the world reacts to that choice right away."
    return "You make your move, and the world reacts right away."


def sanitize_free_input_narrative_text(
    *,
    narrative_text: str,
    player_input_raw: str | None,
    selected_choice_label: str | None,
    selected_action_id: str | None,
) -> str:
    clean_text = " ".join(str(narrative_text or "").split())
    if not clean_text:
        return clean_text

    for pattern, replacement in _FREE_INPUT_JARGON_REPLACEMENTS:
        clean_text = pattern.sub(replacement, clean_text)
    clean_text = " ".join(clean_text.split())
    first_sentence, remainder = split_first_sentence(clean_text)
    if _FREE_INPUT_JARGON_DETECT_RE.search(first_sentence):
        first_sentence = build_free_input_lead_sentence(
            player_input_raw=player_input_raw,
            selected_choice_label=selected_choice_label,
            selected_action_id=selected_action_id,
        )
        clean_text = f"{first_sentence}{remainder}"
    clean_text = sanitize_rejecting_tone(clean_text)
    clean_text = naturalize_narrative_tone(clean_text)
    return clean_text.strip()


def phase_build_polish_inputs(
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


def phase_generate_narrative(
    *,
    db: Session,
    sess: StorySession,
    deps: Any,
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
    input_mode: str,
    player_input_raw: str | None,
    selected_choice_label: str | None,
    selected_action_id: str | None,
    state_before: dict,
    action_state_delta: dict,
    state_delta: dict,
    state_after: dict,
    quest_summary: dict | None,
    event_resolution: EventResolution | None,
    ending_resolution: EndingResolution | None,
    fallback_narration_ctx: dict | None,
    fallback_anchor_tokens: list[str] | None,
    build_story_narration_envelope_fn,
    build_fallback_polish_prompt_fn,
    stage_emitter: Callable[[object], None] | None = None,
    locale: str = "en",
) -> NarrationPhaseResult:
    step_id = uuid.uuid4()
    llm_runtime = deps.llm_runtime_getter()
    compact_state_before = compact_state_snapshot_for_prompt(state_before)
    compact_state_after = compact_state_snapshot_for_prompt(state_after)
    compact_state_delta = compact_state_delta_for_prompt(state_delta, max_items=4)
    impact_brief = build_impact_brief_for_prompt(compact_state_delta)
    intent_action_alignment = derive_intent_action_alignment(
        player_input_raw=player_input_raw,
        selected_action_id=selected_action_id,
        selected_choice_label=selected_choice_label,
    )
    impact_sources = build_impact_sources_for_prompt(
        action_state_delta=action_state_delta,
        total_state_delta=state_delta,
        event_resolution=event_resolution,
    )
    run_state = (state_after or {}).get("run_state") if isinstance(state_after, dict) else {}
    run_step_index = safe_int((run_state or {}).get("step_index"), 0)
    quest_nudge = build_quest_nudge(
        input_mode=input_mode,
        quest_summary=quest_summary or {},
        run_step_index=run_step_index,
        run_ended=bool(ending_resolution.run_ended if ending_resolution else False),
    )
    compact_event = compact_runtime_event_for_prompt(event_resolution)
    event_present = compact_event is not None
    quest_nudge_suppressed_by_event = False
    if event_present and bool(quest_nudge.get("enabled")):
        quest_nudge = {
            "enabled": False,
            "mode": "off",
            "mainline_hint": None,
            "sideline_hint": None,
        }
        quest_nudge_suppressed_by_event = True

    story_prompt_payload = {
        "input_mode": input_mode,
        "player_input_raw": player_input_raw,
        "causal_policy": "strict_separation",
        "intent_action_alignment": intent_action_alignment,
        "node_transition": {
            "from_node_id": current_node_id,
            "to_node_id": next_node_id,
            "from_scene": node.get("scene_brief", ""),
            "to_scene": next_node.get("scene_brief", ""),
        },
        "selection_resolution": {
            "attempted_choice_id": attempted_choice_id,
            "executed_choice_id": executed_choice_id,
            "resolved_choice_id": resolved_choice_id,
            "selected_choice_label": selected_choice_label,
            "selected_action_id": selected_action_id,
            "fallback_reason": fallback_reason_code,
            "fallback_used": using_fallback,
            "mapping_confidence": mapping_confidence,
        },
        "state_snapshot_before": compact_state_before,
        "state_delta": compact_state_delta,
        "state_snapshot_after": compact_state_after,
        "impact_brief": impact_brief,
        "impact_sources": impact_sources,
        "event_present": event_present,
        "quest_summary": quest_summary or {},
        "quest_nudge": quest_nudge,
        "quest_nudge_suppressed_by_event": quest_nudge_suppressed_by_event,
        "run_ending": compact_run_ending_for_prompt(ending_resolution),
    }
    if compact_event is not None:
        story_prompt_payload["runtime_event"] = compact_event
    narration_envelope = build_story_narration_envelope_fn(story_prompt_payload)
    try:
        llm_narrative, _ = llm_runtime.narrative_with_fallback(
            db,
            prompt=narration_envelope.user_text,
            prompt_envelope=narration_envelope,
            session_id=sess.id,
            step_id=step_id,
            stage_emitter=stage_emitter,
            stage_locale=str(settings.story_default_locale or "en"),
            stage_request_kind=input_mode,
        )
    except TypeError as exc:
        msg = str(exc)
        if (
            "prompt_envelope" not in msg
            and "stage_emitter" not in msg
            and "stage_locale" not in msg
            and "stage_request_kind" not in msg
        ):
            raise
        llm_narrative, _ = llm_runtime.narrative_with_fallback(
            db,
            prompt=narration_envelope.user_text,
            session_id=sess.id,
            step_id=step_id,
        )
    if using_fallback:
        narrative_text = fallback_skeleton_text or fallback_builtin_text
        if input_mode == "free_input":
            narrative_text = build_free_input_fallback_narrative_text(
                player_input=player_input_raw,
                selected_choice_label=selected_choice_label,
                selected_action_id=selected_action_id,
                quest_nudge_text=choose_quest_nudge_text(quest_nudge),
            )
        if settings.story_fallback_llm_enabled:
            polish_ctx = dict(fallback_narration_ctx or {})
            polish_ctx["quest_nudge"] = quest_nudge
            polish_ctx["causal_policy"] = "strict_separation"
            polish_ctx["intent_action_alignment"] = intent_action_alignment
            polish_ctx["impact_sources"] = impact_sources
            polish_ctx["event_present"] = event_present
            polish_ctx["quest_nudge_suppressed_by_event"] = quest_nudge_suppressed_by_event
            if compact_event is not None:
                polish_ctx["runtime_event"] = compact_event
            polish_prompt = build_fallback_polish_prompt_fn(polish_ctx, narrative_text)
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
            required_anchor_tokens = fallback_anchor_tokens
            if input_mode == "free_input":
                required_anchor_tokens = None
            narrative_text = safe_polish_text(
                candidate_text,
                narrative_text,
                max_chars=int(settings.story_fallback_llm_max_chars),
                required_anchor_tokens=required_anchor_tokens,
                enforce_error_phrase_denylist=True,
            )
        if input_mode == "free_input":
            narrative_text = sanitize_rejecting_tone(narrative_text)
        narrative_text = naturalize_narrative_tone(narrative_text)
    else:
        narrative_text = llm_narrative.narrative_text
        if input_mode == "free_input":
            narrative_text = sanitize_free_input_narrative_text(
                narrative_text=narrative_text,
                player_input_raw=player_input_raw,
                selected_choice_label=selected_choice_label,
                selected_action_id=selected_action_id,
            )
        narrative_text = naturalize_narrative_tone(narrative_text)

    if ending_resolution and ending_resolution.run_ended:
        epilogue = str(ending_resolution.ending_epilogue or "").strip()
        if epilogue:
            narrative_text = f"{narrative_text}\n\n{naturalize_narrative_tone(epilogue)}"
        else:
            narrative_text = (
                f"{narrative_text}\n\nThe run ends with a {ending_resolution.ending_outcome or 'neutral'} outcome."
            )

    return NarrationPhaseResult(
        narrative_text=narrative_text,
    )


def sanitize_fallback_narrative_text(
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
