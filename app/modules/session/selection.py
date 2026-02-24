from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Session as StorySession
from app.modules.llm.adapter import LLMUnavailableError, get_llm_runtime
from app.modules.llm.prompts import build_story_selection_envelope, build_story_selection_prompt
from app.modules.narrative.state_engine import normalize_state
from app.modules.session.story_runtime.models import SelectionInputSource, SelectionResult


def _resolve_story_node_id(sess: StorySession) -> str | None:
    story_node_id = str(sess.story_node_id or "").strip()
    return story_node_id or None


def _selection_state_snippet(current_story_state: dict, *, sess: StorySession) -> dict:
    state = normalize_state(current_story_state)
    run_state = (state.get("run_state") or {}) if isinstance(state.get("run_state"), dict) else {}
    out: dict[str, object] = {}
    story_node_id = _resolve_story_node_id(sess)
    if story_node_id:
        out["story_node_id"] = story_node_id
    for key in ("day", "slot", "energy", "money", "knowledge", "affection"):
        value = state.get(key)
        if value is None:
            continue
        out[key] = value
    if run_state.get("step_index") is not None:
        out["run_step_index"] = run_state.get("step_index")
    if run_state.get("fallback_count") is not None:
        out["fallback_count"] = run_state.get("fallback_count")
    return out


def select_story_choice(
    *,
    db: Session,
    sess: StorySession,
    player_input: str,
    visible_choices: list[dict],
    intents: list[dict] | None,
    current_story_state: dict,
    llm_runtime_getter=get_llm_runtime,
    stage_emitter: Callable[[object], None] | None = None,
) -> SelectionResult:
    raw = str(player_input or "").strip()
    if not raw:
        return SelectionResult(
            selected_visible_choice_id=None,
            attempted_choice_id=None,
            mapping_confidence=0.0,
            mapping_note=None,
            internal_reason="NO_INPUT",
            use_fallback=True,
            input_source=SelectionInputSource.EMPTY,
        )

    valid_choice_ids = [str(c.get("choice_id")) for c in visible_choices if c.get("choice_id") is not None]
    normalized_intents: list[dict] = []
    intent_aliases: dict[str, str] = {}
    for raw_intent in (intents or []):
        if not isinstance(raw_intent, dict):
            continue
        intent_id = str(raw_intent.get("intent_id") or "").strip()
        alias_choice_id = str(raw_intent.get("alias_choice_id") or "").strip()
        if not intent_id or alias_choice_id not in valid_choice_ids:
            continue
        normalized_intents.append(
            {
                "intent_id": intent_id,
                "alias_choice_id": alias_choice_id,
                "description": str(raw_intent.get("description") or ""),
                "patterns": [
                    str(pattern).strip()
                    for pattern in (raw_intent.get("patterns") or [])
                    if str(pattern).strip()
                ],
            }
        )
        intent_aliases[intent_id] = alias_choice_id

    llm_runtime = llm_runtime_getter()
    state_snippet = _selection_state_snippet(current_story_state, sess=sess)
    selection_prompt = build_story_selection_prompt(
        player_input=raw,
        valid_choice_ids=valid_choice_ids,
        visible_choices=visible_choices,
        intents=normalized_intents,
        state_snippet=state_snippet,
    )
    selection_envelope = build_story_selection_envelope(
        player_input=raw,
        valid_choice_ids=valid_choice_ids,
        visible_choices=visible_choices,
        intents=normalized_intents,
        state_snippet=state_snippet,
    )

    try:
        try:
            llm_selection, _ = llm_runtime.select_story_choice_with_fallback(
                db,
                prompt=selection_prompt,
                prompt_envelope=selection_envelope,
                session_id=sess.id,
                stage_emitter=stage_emitter,
                stage_locale=str(settings.story_default_locale or "en"),
                stage_request_kind="free_input",
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
            llm_selection, _ = llm_runtime.select_story_choice_with_fallback(
                db,
                prompt=selection_prompt,
                session_id=sess.id,
            )
    except Exception as exc:  # noqa: BLE001
        raise LLMUnavailableError(f"selection llm failed: {exc}") from exc

    if llm_selection.choice_id and str(llm_selection.choice_id) in valid_choice_ids:
        resolved_choice_id = str(llm_selection.choice_id)
    elif llm_selection.intent_id and str(llm_selection.intent_id) in intent_aliases:
        resolved_choice_id = intent_aliases[str(llm_selection.intent_id)]
    else:
        raise LLMUnavailableError("selection output missing valid choice_id/intent_id")

    return SelectionResult(
        selected_visible_choice_id=resolved_choice_id,
        attempted_choice_id=resolved_choice_id,
        mapping_confidence=float(llm_selection.confidence),
        mapping_note=llm_selection.notes,
        internal_reason=None,
        use_fallback=False,
        input_source=SelectionInputSource.TEXT,
    )
