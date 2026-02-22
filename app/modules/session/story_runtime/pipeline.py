from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
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
    EndingResolution,
    EventResolution,
    QuestStepEvent,
    QuestUpdateResult,
    RuntimeEventContext,
    SelectionInputSource,
    StoryChoiceResolution,
    StoryRuntimeContext,
)
from app.modules.session.story_runtime.translate import build_choice_resolution_matched_rules, build_story_step_response_payload
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
    advance_runtime_events: Callable[..., EventResolution]
    resolve_run_ending: Callable[..., EndingResolution]
    summarize_quest_for_narration: Callable[[list[dict], dict | None], dict]
    llm_runtime_getter: Callable[[], Any]


@dataclass(slots=True)
class _NarrationPhaseResult:
    narrative_text: str
    tokens_in: int
    tokens_out: int
    provider_name: str


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
_QUEST_NUDGE_CADENCE = 3
_QUEST_HINT_SYSTEM_TERMS_RE = re.compile(
    r"\b(main quest|side quest|objective|stage|milestone|quest_id)\b",
    re.IGNORECASE,
)
_ALIGNMENT_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z'\-]*")
_ACTION_ALIGNMENT_HINTS: dict[str, set[str]] = {
    "study": {"study", "class", "library", "learn", "notes", "exam", "math", "homework", "focus"},
    "work": {"work", "job", "shift", "money", "cash", "salary", "earn", "paid", "parttime", "part-time"},
    "rest": {"rest", "recover", "sleep", "nap", "pause", "break", "food", "eat", "fries", "burger", "lunch", "dinner"},
    "date": {"date", "alice", "walk", "talk", "meet", "hang", "together", "gift"},
    "gift": {"gift", "present", "flowers", "alice"},
}


def _clip_prompt_text(value: object, *, max_len: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _compact_state_snapshot_for_prompt(state: dict) -> dict:
    if not isinstance(state, dict):
        return {}
    run_state = state.get("run_state") if isinstance(state.get("run_state"), dict) else {}
    out: dict[str, object] = {}
    for key in ("slot",):
        value = state.get(key)
        if value is None:
            continue
        out[key] = _clip_prompt_text(value, max_len=24)
    for key in ("day", "energy", "money", "knowledge", "affection"):
        value = state.get(key)
        if value is None:
            continue
        try:
            out[key] = int(value)
        except Exception:  # noqa: BLE001
            continue
    if run_state:
        for key in ("step_index", "fallback_count"):
            value = run_state.get(key)
            if value is None:
                continue
            try:
                out[f"run_{key}"] = int(value)
            except Exception:  # noqa: BLE001
                continue
    return out


def _compact_state_delta_for_prompt(state_delta: dict, *, max_items: int = 4) -> dict:
    if not isinstance(state_delta, dict):
        return {}
    out: dict[str, object] = {}
    for key in ("energy", "money", "knowledge", "affection", "day"):
        value = state_delta.get(key)
        if value is None:
            continue
        try:
            numeric = int(value)
        except Exception:  # noqa: BLE001
            continue
        if numeric == 0:
            continue
        out[key] = numeric
        if len(out) >= max_items:
            return out
    if len(out) < max_items and state_delta.get("slot") is not None:
        out["slot"] = _clip_prompt_text(state_delta.get("slot"), max_len=24)
    return out


def _build_impact_brief_for_prompt(state_delta: dict) -> list[str]:
    out: list[str] = []
    for key, label in (
        ("energy", "energy"),
        ("money", "money"),
        ("knowledge", "knowledge"),
        ("affection", "affection"),
        ("day", "day"),
    ):
        value = state_delta.get(key)
        if value is None:
            continue
        try:
            numeric = int(value)
        except Exception:  # noqa: BLE001
            continue
        if numeric == 0:
            continue
        prefix = "+" if numeric > 0 else ""
        out.append(f"{label} {prefix}{numeric}")
    slot_value = state_delta.get("slot")
    if slot_value:
        out.append(f"time moved to {_clip_prompt_text(slot_value, max_len=24)}")
    return out[:3]


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return int(default)


def _normalize_hint_source(value: object, *, max_words: int = 5) -> str | None:
    text = _clip_prompt_text(value, max_len=72)
    text = text.replace("_", " ").strip()
    text = _QUEST_HINT_SYSTEM_TERMS_RE.sub("", text)
    text = " ".join(text.split())
    if not text:
        return None
    words = text.split(" ")
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip()
    return text.strip(" ,.;:")


def _clip_hint_words(text: str, *, max_words: int = 16) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,.;:")


def _tokenize_alignment_text(value: object) -> set[str]:
    text = " ".join(str(value or "").lower().split())
    if not text:
        return set()
    return {token.strip("-'") for token in _ALIGNMENT_TOKEN_RE.findall(text) if token.strip("-'")}


def _infer_action_from_label(selected_choice_label: str | None) -> str | None:
    label_tokens = _tokenize_alignment_text(selected_choice_label)
    if not label_tokens:
        return None
    best_action = None
    best_hits = 0
    for action_id, hints in _ACTION_ALIGNMENT_HINTS.items():
        hits = len(label_tokens.intersection(hints))
        if hits > best_hits:
            best_action = action_id
            best_hits = hits
    return best_action if best_hits > 0 else None


def _derive_intent_action_alignment(
    *,
    player_input_raw: str | None,
    selected_action_id: str | None,
    selected_choice_label: str | None,
) -> str:
    player_tokens = _tokenize_alignment_text(player_input_raw)
    if not player_tokens:
        return "unknown"

    action_key = str(selected_action_id or "").strip().lower()
    if action_key not in _ACTION_ALIGNMENT_HINTS:
        inferred = _infer_action_from_label(selected_choice_label)
        action_key = inferred if inferred else action_key
    if action_key not in _ACTION_ALIGNMENT_HINTS:
        return "unknown"

    aligned_hints = _ACTION_ALIGNMENT_HINTS[action_key]
    if player_tokens.intersection(aligned_hints):
        return "aligned"

    for other_action, hints in _ACTION_ALIGNMENT_HINTS.items():
        if other_action == action_key:
            continue
        if player_tokens.intersection(hints):
            return "mismatch"
    return "unknown"


def _build_impact_sources_for_prompt(
    *,
    action_state_delta: dict,
    total_state_delta: dict,
    event_resolution: EventResolution | None,
) -> dict:
    event_effects_raw = {}
    if event_resolution and event_resolution.selected_event_id:
        event_effects_raw = event_resolution.selected_event_effects or {}

    return {
        "action_effects": _compact_state_delta_for_prompt(action_state_delta, max_items=3),
        "event_effects": _compact_state_delta_for_prompt(event_effects_raw, max_items=3),
        "total_effects": _compact_state_delta_for_prompt(total_state_delta, max_items=4),
    }


def _build_quest_nudge(
    *,
    input_mode: str,
    quest_summary: dict | None,
    run_step_index: int,
    run_ended: bool,
) -> dict:
    default_nudge = {
        "enabled": False,
        "mode": "off",
        "mainline_hint": None,
        "sideline_hint": None,
    }
    if input_mode != "free_input" or run_ended:
        return default_nudge
    if not isinstance(quest_summary, dict):
        return default_nudge

    active_quests = quest_summary.get("active_quests") if isinstance(quest_summary.get("active_quests"), list) else []
    if not active_quests:
        return default_nudge

    recent_events = quest_summary.get("recent_events") if isinstance(quest_summary.get("recent_events"), list) else []
    has_recent = any(isinstance(item, dict) for item in recent_events)
    cadence_hit = bool(_safe_int(run_step_index, 0) > 0 and _safe_int(run_step_index, 0) % _QUEST_NUDGE_CADENCE == 0)
    if not has_recent and not cadence_hit:
        return default_nudge

    mode = "event_driven" if has_recent else "cadence"
    first_active = active_quests[0] if isinstance(active_quests[0], dict) else {}
    first_active_quest_id = str(first_active.get("quest_id") or "").strip()
    stage_hint_source = _normalize_hint_source(first_active.get("current_stage_title"))
    mainline_hint = (
        f"your current track still points toward {stage_hint_source.lower()}"
        if stage_hint_source
        else "the week's plan still has a clear next step"
    )
    mainline_hint = _clip_hint_words(mainline_hint, max_words=16)

    selected_recent = None
    for raw_event in reversed(recent_events):
        if not isinstance(raw_event, dict):
            continue
        event_quest_id = str(raw_event.get("quest_id") or "").strip()
        if first_active_quest_id and event_quest_id and event_quest_id == first_active_quest_id:
            continue
        selected_recent = raw_event
        break
    if selected_recent is None:
        for raw_event in reversed(recent_events):
            if isinstance(raw_event, dict):
                selected_recent = raw_event
                break

    sideline_hint = None
    if isinstance(selected_recent, dict):
        side_source = _normalize_hint_source(selected_recent.get("title"))
        if side_source:
            sideline_hint = _clip_hint_words(
                f"a smaller thread around {side_source.lower()} still lingers at the edge of your day",
                max_words=16,
            )
        else:
            sideline_hint = "that side thread is still open if you want to pivot later"

    return {
        "enabled": True,
        "mode": mode,
        "mainline_hint": mainline_hint,
        "sideline_hint": sideline_hint,
    }


def _choose_quest_nudge_text(quest_nudge: dict | None) -> str | None:
    if not isinstance(quest_nudge, dict) or not bool(quest_nudge.get("enabled")):
        return None
    mode = str(quest_nudge.get("mode") or "off").strip().lower()
    mainline_hint = str(quest_nudge.get("mainline_hint") or "").strip()
    sideline_hint = str(quest_nudge.get("sideline_hint") or "").strip()
    if mode == "event_driven" and sideline_hint:
        return sideline_hint
    if mainline_hint:
        return mainline_hint
    if sideline_hint:
        return sideline_hint
    return None


def _compact_runtime_event_for_prompt(event_resolution: EventResolution | None) -> dict | None:
    if not event_resolution or not event_resolution.selected_event_id:
        return None
    return {
        "event_id": _clip_prompt_text(event_resolution.selected_event_id, max_len=64),
        "title": _clip_prompt_text(event_resolution.selected_event_title, max_len=80),
        "narration_hint": _clip_prompt_text(event_resolution.selected_event_narration_hint, max_len=96),
        "effects": _compact_state_delta_for_prompt(event_resolution.selected_event_effects or {}, max_items=3),
    }


def _compact_run_ending_for_prompt(ending_resolution: EndingResolution | None) -> dict:
    if not ending_resolution or not ending_resolution.run_ended:
        return {"run_ended": False}
    return {
        "run_ended": True,
        "ending_id": _clip_prompt_text(ending_resolution.ending_id, max_len=64),
        "ending_outcome": _clip_prompt_text(ending_resolution.ending_outcome, max_len=24),
        "ending_title": _clip_prompt_text(ending_resolution.ending_title, max_len=96),
        "ending_epilogue": _clip_prompt_text(ending_resolution.ending_epilogue, max_len=160),
    }


def _resolve_input_mode_for_prompt(resolution: StoryChoiceResolution, player_input: str | None) -> str:
    if resolution.input_source == SelectionInputSource.TEXT and str(player_input or "").strip():
        return "free_input"
    return "choice_click"


def _split_first_sentence(text: str) -> tuple[str, str]:
    marker = re.search(r"[.!?]", text)
    if marker is None:
        return text, ""
    end = marker.end()
    return text[:end], text[end:]


def _build_free_input_lead_sentence(
    *,
    player_input_raw: str | None,
    selected_choice_label: str | None,
    selected_action_id: str | None,
) -> str:
    choice_label = _clip_prompt_text(selected_choice_label, max_len=72).strip()
    if choice_label:
        return f"You act on your own read of the moment, and {choice_label} immediately shapes what happens next."
    action_label = _clip_prompt_text((selected_action_id or "").replace("_", " "), max_len=48).strip()
    if action_label:
        return f"You follow your instinct, and {action_label} drives the next beat right away."
    player_text = _clip_prompt_text(player_input_raw, max_len=96).strip()
    if player_text:
        return "You follow your own call, and the world reacts to that choice right away."
    return "You make your move, and the world reacts right away."


def _sanitize_free_input_narrative_text(
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
    first_sentence, remainder = _split_first_sentence(clean_text)
    if _FREE_INPUT_JARGON_DETECT_RE.search(first_sentence):
        first_sentence = _build_free_input_lead_sentence(
            player_input_raw=player_input_raw,
            selected_choice_label=selected_choice_label,
            selected_action_id=selected_action_id,
        )
        clean_text = f"{first_sentence}{remainder}"
    clean_text = sanitize_rejecting_tone(clean_text)
    clean_text = naturalize_narrative_tone(clean_text)
    return clean_text.strip()


def _phase_load_runtime_context(
    *,
    db: Session,
    sess: StorySession,
    deps: StoryRuntimePipelineDeps,
) -> StoryRuntimeContext:
    story_row = deps.load_story_pack(db, sess.story_id, sess.story_version)
    runtime_pack = deps.normalize_pack_for_runtime(story_row.pack_json or {})
    story_node_id = str(sess.story_node_id or "").strip()
    if story_node_id:
        current_node_id = story_node_id
    else:
        raise HTTPException(status_code=400, detail={"code": "STORY_NODE_MISSING"})

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
) -> _NarrationPhaseResult:
    step_id = uuid.uuid4()
    llm_runtime = deps.llm_runtime_getter()
    compact_state_before = _compact_state_snapshot_for_prompt(state_before)
    compact_state_after = _compact_state_snapshot_for_prompt(state_after)
    compact_state_delta = _compact_state_delta_for_prompt(state_delta, max_items=4)
    impact_brief = _build_impact_brief_for_prompt(compact_state_delta)
    intent_action_alignment = _derive_intent_action_alignment(
        player_input_raw=player_input_raw,
        selected_action_id=selected_action_id,
        selected_choice_label=selected_choice_label,
    )
    impact_sources = _build_impact_sources_for_prompt(
        action_state_delta=action_state_delta,
        total_state_delta=state_delta,
        event_resolution=event_resolution,
    )
    run_state = (state_after or {}).get("run_state") if isinstance(state_after, dict) else {}
    run_step_index = _safe_int((run_state or {}).get("step_index"), 0)
    quest_nudge = _build_quest_nudge(
        input_mode=input_mode,
        quest_summary=quest_summary or {},
        run_step_index=run_step_index,
        run_ended=bool(ending_resolution.run_ended if ending_resolution else False),
    )
    compact_event = _compact_runtime_event_for_prompt(event_resolution)
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
        "run_ending": _compact_run_ending_for_prompt(ending_resolution),
    }
    if compact_event is not None:
        story_prompt_payload["runtime_event"] = compact_event
    llm_narrative, _ = llm_runtime.narrative_with_fallback(
        db,
        prompt=build_story_narration_prompt(story_prompt_payload),
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
                quest_nudge_text=_choose_quest_nudge_text(quest_nudge),
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
            polish_prompt = build_fallback_polish_prompt(polish_ctx, narrative_text)
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
            narrative_text = _sanitize_free_input_narrative_text(
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


def _phase_apply_runtime_events(
    *,
    sess: StorySession,
    context: StoryRuntimeContext,
    resolution: StoryChoiceResolution,
    state_before: dict,
    state_after: dict,
    state_delta: dict,
    deps: StoryRuntimePipelineDeps,
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


def _phase_resolve_ending(
    *,
    context: StoryRuntimeContext,
    resolution: StoryChoiceResolution,
    state_after: dict,
    run_state: dict,
    deps: StoryRuntimePipelineDeps,
) -> EndingResolution:
    return deps.resolve_run_ending(
        endings_def=(context.runtime_pack.get("endings") or []),
        run_config=(context.runtime_pack.get("run_config") or {}),
        run_state=run_state,
        next_node_id=resolution.next_node_id,
        state_after=state_after,
        quest_state=(state_after or {}).get("quest_state"),
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
    action_state_delta = dict(state_delta or {})
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

    event_update = _phase_apply_runtime_events(
        sess=sess,
        context=context,
        resolution=resolution,
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        deps=deps,
    )
    state_after = normalize_state(event_update.state_after)
    run_state = dict(event_update.run_state or {})
    if resolution.using_fallback:
        run_state["fallback_count"] = int(run_state.get("fallback_count", 0)) + 1
    state_after["run_state"] = run_state
    state_after = normalize_state(state_after)
    state_delta = deps.compute_state_delta(state_before, state_after)

    ending_resolution = _phase_resolve_ending(
        context=context,
        resolution=resolution,
        state_after=state_after,
        run_state=(state_after or {}).get("run_state") or {},
        deps=deps,
    )
    state_after["run_state"] = dict(ending_resolution.run_state or {})
    state_after = normalize_state(state_after)
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

    input_mode_for_prompt = _resolve_input_mode_for_prompt(resolution, player_input)
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
        input_mode=input_mode_for_prompt,
        player_input_raw=player_input,
        selected_choice_label=(
            str(resolution.selected_choice.get("display_text"))
            if resolution.selected_choice is not None and resolution.selected_choice.get("display_text") is not None
            else None
        ),
        selected_action_id=(
            str((resolution.final_action_for_state or {}).get("action_id"))
            if (resolution.final_action_for_state or {}).get("action_id") is not None
            else None
        ),
        state_before=state_before,
        action_state_delta=action_state_delta,
        state_delta=state_delta,
        state_after=state_after,
        quest_summary=quest_summary,
        event_resolution=event_update,
        ending_resolution=ending_resolution,
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

    response_choices = [] if ending_resolution.run_ended else deps.story_choices_for_response(next_node, state_after)

    run_state_after = (state_after or {}).get("run_state") if isinstance(state_after, dict) else {}
    run_state_after = dict(run_state_after or {})
    progress_keypoints = _compact_state_delta_for_prompt(state_delta, max_items=6)
    has_progress = any(key in progress_keypoints for key in ("energy", "money", "knowledge", "affection"))
    stall_turns = _safe_int(run_state_after.get("stall_turns"), 0)
    stall_turns = 0 if has_progress else stall_turns + 1
    guard_stall_triggered = False
    if not ending_resolution.run_ended and stall_turns >= 2:
        guard_stall_triggered = True
        run_state_after["guard_stall_hits"] = _safe_int(run_state_after.get("guard_stall_hits"), 0) + 1
        stall_turns = 0
        narrative_text = (
            f"{narrative_text} You force a small forward step instead of letting the pace stall."
        )
    run_state_after["stall_turns"] = stall_turns

    guard_all_blocked_triggered = False
    if not ending_resolution.run_ended and not response_choices:
        guard_all_blocked_triggered = True
        run_state_after["guard_all_blocked_hits"] = _safe_int(run_state_after.get("guard_all_blocked_hits"), 0) + 1
        global_fallback_choice_id = str(context.runtime_pack.get("global_fallback_choice_id") or "").strip()
        if global_fallback_choice_id:
            response_choices = [
                {
                    "id": global_fallback_choice_id,
                    "text": "Take a stabilizing pause and reset your pace",
                    "type": "rest",
                    "is_available": True,
                    "unavailable_reason": None,
                }
            ]
        narrative_text = (
            f"{narrative_text} The pressure tightens, but you keep control and reset your footing."
        )

    state_after["run_state"] = run_state_after
    state_after = normalize_state(state_after)
    state_delta = deps.compute_state_delta(state_before, state_after)
    sess.state_json = state_after

    sess.story_node_id = resolution.next_node_id
    if ending_resolution.run_ended:
        sess.status = "ended"
    sess.updated_at = datetime.now(timezone.utc)

    matched_rules = build_choice_resolution_matched_rules(
        attempted_choice_id=resolution.attempted_choice_id,
        executed_choice_id=resolution.executed_choice_id,
        resolved_choice_id=resolution.resolved_choice_id,
        fallback_reason_code=resolution.internal_reason,
        mapping_confidence=resolution.mapping_confidence,
        mapping_note=resolution.mapping_note,
    )
    matched_rules.extend(quest_update.matched_rules or [])
    matched_rules.extend(event_update.matched_rules or [])
    matched_rules.extend(ending_resolution.matched_rules or [])

    layer_debug = {
        "input_mode": input_mode_for_prompt,
        "player_input": player_input,
        "attempted_choice_id": resolution.attempted_choice_id,
        "executed_choice_id": resolution.executed_choice_id,
        "resolved_choice_id": resolution.resolved_choice_id,
        "selected_action_id": (
            str((resolution.final_action_for_state or {}).get("action_id"))
            if (resolution.final_action_for_state or {}).get("action_id") is not None
            else None
        ),
        "mapping_confidence": resolution.mapping_confidence,
        "fallback_reason": resolution.fallback_reason_code,
        "mapping_note": resolution.mapping_note,
        "state_delta_keypoints": _compact_state_delta_for_prompt(state_delta, max_items=6),
        "quest_event_ending_flags": {
            "fallback_used": bool(resolution.using_fallback),
            "event_present": bool(event_update.selected_event_id),
            "run_ended": bool(ending_resolution.run_ended),
            "ending_id": ending_resolution.ending_id,
            "ending_outcome": ending_resolution.ending_outcome,
            "step_index": _safe_int(((state_after or {}).get("run_state") or {}).get("step_index"), 0),
            "all_blocked_guard_triggered": guard_all_blocked_triggered,
            "stall_guard_triggered": guard_stall_triggered,
        },
        "prompt_policy": {
            "causal_policy": "strict_separation",
            "intent_action_alignment": _derive_intent_action_alignment(
                player_input_raw=player_input,
                selected_action_id=(
                    str((resolution.final_action_for_state or {}).get("action_id"))
                    if (resolution.final_action_for_state or {}).get("action_id") is not None
                    else None
                ),
                selected_choice_label=(
                    str(resolution.selected_choice.get("display_text"))
                    if resolution.selected_choice is not None and resolution.selected_choice.get("display_text") is not None
                    else None
                ),
            ),
            "event_present": bool(event_update.selected_event_id),
            "all_blocked_guard_triggered": guard_all_blocked_triggered,
            "stall_guard_triggered": guard_stall_triggered,
        },
    }

    log = ActionLog(
        session_id=sess.id,
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
        classification={"layer_debug": layer_debug},
        state_before=state_before,
        state_after=state_after,
        state_delta=state_delta,
        matched_rules=matched_rules,
    )
    db.add(log)

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
        run_ended=bool(ending_resolution.run_ended),
        ending_id=ending_resolution.ending_id,
        ending_outcome=ending_resolution.ending_outcome,
    )
    return response_payload
