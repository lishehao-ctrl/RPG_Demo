from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Session as StorySession
from app.modules.llm.adapter import get_llm_runtime
from app.modules.llm.prompts import build_story_selection_prompt
from app.modules.llm.schemas import StorySelectionOutput
from app.modules.narrative.state_engine import normalize_state
from app.modules.session.story_runtime.models import SelectionInputSource, SelectionResult
from app.modules.story.mapping import RuleBasedMappingAdapter

story_mapping_adapter = RuleBasedMappingAdapter()


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
    selection_prompt = build_story_selection_prompt(
        player_input=raw,
        valid_choice_ids=valid_choice_ids,
        visible_choices=visible_choices,
        intents=normalized_intents,
        state_snippet=_selection_state_snippet(current_story_state, sess=sess),
    )
    min_confidence = max(0.0, min(1.0, float(settings.story_map_min_confidence)))
    llm_selection = StorySelectionOutput()
    parse_ok = True
    llm_requested_fallback = False
    llm_fallback_note: str | None = None
    llm_fallback_confidence = 0.0
    if hasattr(llm_runtime, "select_story_choice_with_fallback"):
        try:
            llm_selection, parse_ok = llm_runtime.select_story_choice_with_fallback(
                db,
                prompt=selection_prompt,
                session_id=sess.id,
            )
        except Exception:  # noqa: BLE001
            llm_selection = StorySelectionOutput()
            parse_ok = False
    if parse_ok and llm_selection.use_fallback:
        # Conservative rescue: keep fallback as a hint, then try deterministic intent/rule mapping.
        llm_requested_fallback = True
        llm_fallback_note = llm_selection.notes or "selector_fallback"
        llm_fallback_confidence = float(llm_selection.confidence)
    if parse_ok and llm_selection.choice_id and llm_selection.choice_id in valid_choice_ids and not llm_selection.use_fallback:
        return SelectionResult(
            selected_visible_choice_id=str(llm_selection.choice_id),
            attempted_choice_id=str(llm_selection.choice_id),
            mapping_confidence=float(llm_selection.confidence),
            mapping_note=llm_selection.notes,
            internal_reason=None,
            use_fallback=False,
            input_source=SelectionInputSource.TEXT,
        )
    if parse_ok and llm_selection.intent_id:
        alias_choice_id = intent_aliases.get(str(llm_selection.intent_id))
        llm_intent_confidence = float(llm_selection.confidence)
        if alias_choice_id and llm_intent_confidence >= min_confidence:
            mapping_note = llm_selection.notes or f"intent:{llm_selection.intent_id}"
            if llm_requested_fallback:
                mapping_note = f"rescued_after_llm_fallback:{mapping_note}"
            return SelectionResult(
                selected_visible_choice_id=alias_choice_id,
                attempted_choice_id=alias_choice_id,
                mapping_confidence=llm_intent_confidence,
                mapping_note=mapping_note,
                internal_reason=None,
                use_fallback=False,
                input_source=SelectionInputSource.TEXT,
            )

    normalized_input = " ".join(raw.lower().split())
    intent_hits: list[tuple[int, str, str]] = []
    for intent in normalized_intents:
        intent_id = str(intent.get("intent_id") or "")
        alias_choice_id = str(intent.get("alias_choice_id") or "")
        for pattern in (intent.get("patterns") or []):
            normalized_pattern = " ".join(str(pattern).lower().split())
            if not normalized_pattern:
                continue
            if normalized_pattern in normalized_input:
                intent_hits.append((len(normalized_pattern), intent_id, alias_choice_id))
    if intent_hits:
        intent_hits.sort(key=lambda item: (-item[0], item[1], item[2]))
        _, intent_id, alias_choice_id = intent_hits[0]
        mapping_note = f"intent_pattern:{intent_id}"
        if llm_requested_fallback:
            mapping_note = f"rescued_after_llm_fallback:{mapping_note}"
        return SelectionResult(
            selected_visible_choice_id=alias_choice_id,
            attempted_choice_id=alias_choice_id,
            mapping_confidence=0.8,
            mapping_note=mapping_note,
            internal_reason=None,
            use_fallback=False,
            input_source=SelectionInputSource.TEXT,
        )

    mapping_result = story_mapping_adapter.map_input(
        player_input=raw,
        choices=visible_choices,
        state={"story_node_id": _resolve_story_node_id(sess)},
    )
    if mapping_result.ranked_candidates:
        selected_choice_id = str(mapping_result.ranked_candidates[0].choice_id)
        mapping_confidence = float(mapping_result.confidence)
        mapping_is_ambiguous = mapping_result.note == "AMBIGUOUS_FIRST_MATCH"
        if mapping_confidence >= min_confidence and not mapping_is_ambiguous:
            mapping_note = mapping_result.note or "rule_based"
            if llm_requested_fallback:
                mapping_note = f"rescued_after_llm_fallback:{mapping_note}"
            return SelectionResult(
                selected_visible_choice_id=selected_choice_id,
                attempted_choice_id=selected_choice_id,
                mapping_confidence=mapping_confidence,
                mapping_note=mapping_note,
                internal_reason=None,
                use_fallback=False,
                input_source=SelectionInputSource.TEXT,
            )
        if llm_requested_fallback:
            reject_note = mapping_result.note or "rule_low_confidence"
            llm_fallback_note = f"{llm_fallback_note or 'selector_fallback'}|{reject_note}"
    return SelectionResult(
        selected_visible_choice_id=None,
        attempted_choice_id=None,
        mapping_confidence=(llm_fallback_confidence if llm_requested_fallback else 0.0),
        mapping_note=llm_fallback_note,
        internal_reason=("LLM_PARSE_ERROR" if not parse_ok else "NO_MATCH"),
        use_fallback=True,
        input_source=SelectionInputSource.TEXT,
    )
