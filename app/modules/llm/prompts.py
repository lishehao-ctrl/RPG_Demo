import json

from app.modules.story.constants import AUTHOR_ASSIST_TASKS_V4

_SELECTION_MAX_VISIBLE_CHOICES = 6
_SELECTION_MAX_INTENTS = 6
_SELECTION_MAX_PATTERNS = 2
_NARRATION_MAX_IMPACT_ITEMS = 4


def _clip_text(value: object, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit]


def _compact_selection_state(state_snippet: dict | None) -> dict:
    if not isinstance(state_snippet, dict):
        return {}
    out: dict[str, object] = {}
    for key in ("story_node_id", "slot"):
        value = state_snippet.get(key)
        if value is None:
            continue
        out[key] = _clip_text(value, limit=64)
    for key in ("day", "energy", "money", "knowledge", "affection", "run_step_index", "fallback_count"):
        value = state_snippet.get(key)
        if value is None:
            continue
        try:
            out[key] = int(value)
        except Exception:  # noqa: BLE001
            continue
    return out


def _compact_state_snapshot(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return {}
    out: dict[str, object] = {}
    for key in ("slot",):
        value = state.get(key)
        if value is None:
            continue
        out[key] = _clip_text(value, limit=24)
    for key in ("day", "energy", "money", "knowledge", "affection", "run_step_index", "fallback_count"):
        value = state.get(key)
        if value is None:
            continue
        try:
            out[key] = int(value)
        except Exception:  # noqa: BLE001
            continue
    return out


def _compact_state_delta(delta: dict | None) -> dict:
    if not isinstance(delta, dict):
        return {}
    out: dict[str, object] = {}
    for key in ("energy", "money", "knowledge", "affection", "day"):
        value = delta.get(key)
        if value is None:
            continue
        try:
            numeric = int(value)
        except Exception:  # noqa: BLE001
            continue
        if numeric == 0:
            continue
        out[key] = numeric
    slot_value = delta.get("slot")
    if slot_value is not None:
        out["slot"] = _clip_text(slot_value, limit=24)
    return out


def _compact_impact_brief(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = _clip_text(item, limit=80)
        if not text:
            continue
        out.append(text)
        if len(out) >= _NARRATION_MAX_IMPACT_ITEMS:
            break
    return out


def _compact_quest_summary(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, object] = {"active_quests": [], "recent_events": []}
    active_items = raw.get("active_quests")
    if isinstance(active_items, list):
        compact_active: list[dict] = []
        for item in active_items[:2]:
            if not isinstance(item, dict):
                continue
            progress = item.get("stage_progress") if isinstance(item.get("stage_progress"), dict) else {}
            try:
                done = int(progress.get("done", 0) or 0)
            except Exception:  # noqa: BLE001
                done = 0
            try:
                total = int(progress.get("total", 0) or 0)
            except Exception:  # noqa: BLE001
                total = 0
            compact_active.append(
                {
                    "quest_id": _clip_text(item.get("quest_id"), limit=48),
                    "title": _clip_text(item.get("title"), limit=64),
                    "current_stage_title": _clip_text(item.get("current_stage_title"), limit=64),
                    "stage_progress": {
                        "done": done,
                        "total": total,
                    },
                }
            )
        out["active_quests"] = compact_active
    recent_items = raw.get("recent_events")
    if isinstance(recent_items, list):
        compact_recent: list[dict] = []
        for item in recent_items[-2:]:
            if not isinstance(item, dict):
                continue
            compact_recent.append(
                {
                    "type": _clip_text(item.get("type"), limit=32),
                    "quest_id": _clip_text(item.get("quest_id"), limit=48),
                    "title": _clip_text(item.get("title"), limit=64),
                }
            )
        out["recent_events"] = compact_recent
    return out


def _compact_quest_nudge(raw: object) -> dict:
    out = {
        "enabled": False,
        "mode": "off",
        "mainline_hint": None,
        "sideline_hint": None,
    }
    if not isinstance(raw, dict):
        return out

    enabled = bool(raw.get("enabled", False))
    mode = str(raw.get("mode") or "off").strip().lower()
    if mode not in {"event_driven", "cadence"}:
        mode = "off"
    out["enabled"] = enabled and mode in {"event_driven", "cadence"}
    out["mode"] = mode if out["enabled"] else "off"
    if not out["enabled"]:
        return out

    mainline_hint = _clip_text(raw.get("mainline_hint"), limit=96).strip()
    sideline_hint = _clip_text(raw.get("sideline_hint"), limit=96).strip()
    out["mainline_hint"] = mainline_hint or None
    out["sideline_hint"] = sideline_hint or None
    return out


def _compact_impact_sources(raw: object) -> dict:
    out = {"action_effects": {}, "event_effects": {}, "total_effects": {}}
    if not isinstance(raw, dict):
        return out
    for key in ("action_effects", "event_effects", "total_effects"):
        value = raw.get(key)
        out[key] = _compact_state_delta(value if isinstance(value, dict) else {})
    return out


def _compact_narrative_context(payload: dict) -> dict:
    raw_transition = payload.get("node_transition") if isinstance(payload.get("node_transition"), dict) else {}
    raw_selection = payload.get("selection_resolution") if isinstance(payload.get("selection_resolution"), dict) else {}
    raw_event = payload.get("runtime_event") if isinstance(payload.get("runtime_event"), dict) else {}
    raw_ending = payload.get("run_ending") if isinstance(payload.get("run_ending"), dict) else {}

    input_mode = str(payload.get("input_mode") or "choice_click").strip().lower()
    if input_mode not in {"free_input", "choice_click"}:
        input_mode = "choice_click"

    fallback_used = bool(raw_selection.get("fallback_used", payload.get("fallback_used", False)))
    compact_event = None
    if raw_event.get("event_id"):
        compact_event = {
            "event_id": _clip_text(raw_event.get("event_id"), limit=64),
            "title": _clip_text(raw_event.get("title"), limit=80),
            "narration_hint": _clip_text(raw_event.get("narration_hint"), limit=96),
            "effects": _compact_state_delta(raw_event.get("effects") if isinstance(raw_event.get("effects"), dict) else {}),
        }
    event_present = bool(payload.get("event_present", compact_event is not None))
    causal_policy = _clip_text(payload.get("causal_policy"), limit=32).strip().lower() or "strict_separation"
    if causal_policy != "strict_separation":
        causal_policy = "strict_separation"
    intent_action_alignment = _clip_text(payload.get("intent_action_alignment"), limit=24).strip().lower() or "unknown"
    if intent_action_alignment not in {"aligned", "mismatch", "unknown"}:
        intent_action_alignment = "unknown"

    run_ended = bool(raw_ending.get("run_ended", False))
    compact_ending = {"run_ended": run_ended}
    if run_ended:
        compact_ending.update(
            {
                "ending_id": _clip_text(raw_ending.get("ending_id"), limit=64),
                "ending_outcome": _clip_text(raw_ending.get("ending_outcome"), limit=24),
                "ending_title": _clip_text(raw_ending.get("ending_title"), limit=96),
                "ending_epilogue": _clip_text(raw_ending.get("ending_epilogue"), limit=160),
            }
        )

    return {
        "input_mode": input_mode,
        "player_input_raw": _clip_text(payload.get("player_input_raw"), limit=180),
        "node_transition": {
            "from_node_id": _clip_text(raw_transition.get("from_node_id"), limit=64),
            "to_node_id": _clip_text(raw_transition.get("to_node_id"), limit=64),
            "from_scene": _clip_text(raw_transition.get("from_scene"), limit=96),
            "to_scene": _clip_text(raw_transition.get("to_scene"), limit=96),
        },
        "selection_resolution": {
            "attempted_choice_id": _clip_text(raw_selection.get("attempted_choice_id"), limit=64),
            "executed_choice_id": _clip_text(raw_selection.get("executed_choice_id"), limit=64),
            "resolved_choice_id": _clip_text(raw_selection.get("resolved_choice_id"), limit=64),
            "selected_choice_label": _clip_text(raw_selection.get("selected_choice_label"), limit=72),
            "selected_action_id": _clip_text(raw_selection.get("selected_action_id"), limit=64),
            "mapping_confidence": raw_selection.get("mapping_confidence"),
            "fallback_used": fallback_used,
            "fallback_reason": _clip_text(raw_selection.get("fallback_reason"), limit=32),
        },
        "causal_policy": causal_policy,
        "intent_action_alignment": intent_action_alignment,
        "state_snapshot_before": _compact_state_snapshot(payload.get("state_snapshot_before")),
        "state_snapshot_after": _compact_state_snapshot(payload.get("state_snapshot_after")),
        "state_delta": _compact_state_delta(payload.get("state_delta")),
        "impact_brief": _compact_impact_brief(payload.get("impact_brief")),
        "impact_sources": _compact_impact_sources(payload.get("impact_sources")),
        "event_present": event_present,
        "quest_summary": _compact_quest_summary(payload.get("quest_summary")),
        "quest_nudge": _compact_quest_nudge(payload.get("quest_nudge")),
        "quest_nudge_suppressed_by_event": bool(payload.get("quest_nudge_suppressed_by_event", False)),
        "runtime_event": compact_event,
        "run_ending": compact_ending,
    }


def build_selection_repair_prompt(raw_text: str) -> str:
    return (
        "Selection repair task. Fix JSON to match schema exactly: "
        "{choice_id:string|null,use_fallback:boolean,confidence:number,intent_id:string|null,notes:string|null}. "
        "Return JSON only. No markdown code fences. No extra keys. Source:\n"
        + raw_text
    )


def build_repair_prompt(raw_text: str) -> str:
    # Backward-compatible alias for selector repair.
    return build_selection_repair_prompt(raw_text)


def build_narrative_repair_prompt(raw_text: str) -> str:
    return (
        "Narrative repair task. Fix output to JSON with exact schema: "
        '{"narrative_text":"string"}. '
        "Return JSON only. No markdown code fences. No extra keys. Source:\n"
        + raw_text
    )


def build_fallback_polish_prompt(ctx: dict, skeleton_text: str) -> str:
    reason = str((ctx or {}).get("fallback_reason") or "")
    locale = str((ctx or {}).get("locale") or "en")
    choice_labels = [
        str(item.get("label") or "")
        for item in ((ctx or {}).get("visible_choices") or [])
        if isinstance(item, dict) and item.get("label")
    ]
    payload = {
        "locale": locale,
        "fallback_reason": reason,
        "causal_policy": _clip_text((ctx or {}).get("causal_policy"), limit=32).strip().lower() or "strict_separation",
        "intent_action_alignment": _clip_text((ctx or {}).get("intent_action_alignment"), limit=24).strip().lower()
        or "unknown",
        "event_present": bool((ctx or {}).get("event_present", False)),
        "quest_nudge_suppressed_by_event": bool((ctx or {}).get("quest_nudge_suppressed_by_event", False)),
        "node_id": (ctx or {}).get("node_id"),
        "player_input": (ctx or {}).get("player_input", ""),
        "mapping_note": (ctx or {}).get("mapping_note", ""),
        "attempted_choice_id": (ctx or {}).get("attempted_choice_id"),
        "attempted_choice_label": (ctx or {}).get("attempted_choice_label"),
        "visible_choice_labels": choice_labels,
        "impact_sources": _compact_impact_sources((ctx or {}).get("impact_sources")),
        "runtime_event": (
            {
                "event_id": _clip_text(((ctx or {}).get("runtime_event") or {}).get("event_id"), limit=64),
                "title": _clip_text(((ctx or {}).get("runtime_event") or {}).get("title"), limit=80),
            }
            if isinstance((ctx or {}).get("runtime_event"), dict) and ((ctx or {}).get("runtime_event") or {}).get("event_id")
            else None
        ),
        "quest_nudge": _compact_quest_nudge((ctx or {}).get("quest_nudge")),
        "state_snippet": (ctx or {}).get("state_snippet", {}),
        "short_recent_summary": (ctx or {}).get("short_recent_summary", []),
    }
    return (
        "Fallback rewrite task. Return JSON only with exact schema: "
        '{"narrative_text":"string"}. '
        "Narration only, exactly 2 concise sentences. "
        "Rewrite the provided skeleton text into grounded cinematic second-person in-world wording. "
        "Preserve meaning and outcome exactly. "
        "Do NOT add new facts, events, entities, items, rules, or state changes. "
        "Do NOT advance the story. "
        "Sentence 1 should acknowledge the player's attempted intent in-world. "
        "Sentence 2 should describe the action that actually happens and its immediate consequence. "
        "Keep strict separation between intent acknowledgment and executed-result causality. "
        "If event_present is true, treat runtime_event as an additional beat; never present it as a direct result of player_input. "
        "When intent_action_alignment is mismatch, use a bridge phrase (for example but/instead/as an opening appears) before landing on executed action. "
        "Use clear cause -> consequence flow. "
        "If quest_nudge is enabled, keep at most one subtle in-world hint and avoid task-log narration. "
        "Do NOT use labels like main quest, side quest, objective, stage, or milestone. "
        "Do not quote or copy the player input verbatim; paraphrase the intent naturally. "
        "Do NOT use rejecting phrasing such as fuzzy, unclear, invalid, wrong input, or cannot understand. "
        "Soft-avoid system-like phrasing such as for this turn, the scene, and story keeps moving. "
        "Narrative-first numbers rule: use world-language first and at most one short numeric mention. "
        "Do NOT output internal tokens/codes/ids including NO_INPUT, BLOCKED, FALLBACK, "
        "INVALID_CHOICE_ID, NO_MATCH, LLM_PARSE_ERROR, PREREQ_BLOCKED, next_node_id, __fallback__, "
        "choice_id, intent_id, confidence, delta_scale. "
        "Keep key terms from the skeleton text present; do not replace those key terms with synonyms. "
        f"Write narrative_text in locale '{locale}'. "
        "Use visible choice labels only, never choice ids. "
        "Context JSON: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + " Skeleton: "
        + skeleton_text
    )


def build_story_selection_prompt(
    *,
    player_input: str,
    valid_choice_ids: list[str],
    visible_choices: list[dict],
    intents: list[dict] | None = None,
    state_snippet: dict | None = None,
) -> str:
    payload = {
        "player_input": player_input,
        "valid_choice_ids": sorted({str(cid) for cid in valid_choice_ids if str(cid)}),
        "visible_choices": [
            {
                "choice_id": _clip_text(choice.get("choice_id"), limit=64),
                "display_text": _clip_text(choice.get("display_text"), limit=56),
            }
            for choice in (visible_choices or [])[:_SELECTION_MAX_VISIBLE_CHOICES]
            if isinstance(choice, dict)
        ],
        "intents": [
            {
                "intent_id": _clip_text(intent.get("intent_id"), limit=64),
                "alias_choice_id": _clip_text(intent.get("alias_choice_id"), limit=64),
                "description": _clip_text(intent.get("description"), limit=56),
                "patterns": [
                    _clip_text(pattern, limit=28)
                    for pattern in (intent.get("patterns") or [])[:_SELECTION_MAX_PATTERNS]
                    if str(pattern).strip()
                ],
            }
            for intent in (intents or [])[:_SELECTION_MAX_INTENTS]
            if isinstance(intent, dict)
        ],
        "state": _compact_selection_state(state_snippet),
    }
    return (
        "Story selection task. Return JSON only with schema: "
        "{choice_id:string|null,use_fallback:boolean,confidence:number,intent_id:string|null,notes:string|null}. "
        "Map player_input to one visible choice_id from valid_choice_ids. "
        "If uncertain, use_fallback=true and choice_id=null. Context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def build_story_narration_prompt(payload: dict) -> str:
    compact_context = _compact_narrative_context(payload if isinstance(payload, dict) else {})
    input_mode = compact_context.get("input_mode")
    fallback_used = bool((compact_context.get("selection_resolution") or {}).get("fallback_used"))
    causal_policy = str(compact_context.get("causal_policy") or "strict_separation")
    intent_action_alignment = str(compact_context.get("intent_action_alignment") or "unknown")
    event_present = bool(compact_context.get("event_present", False))
    quest_nudge = compact_context.get("quest_nudge") if isinstance(compact_context.get("quest_nudge"), dict) else {}
    nudge_enabled = bool(quest_nudge.get("enabled", False))
    quest_nudge_suppressed_by_event = bool(compact_context.get("quest_nudge_suppressed_by_event", False))
    if input_mode == "free_input" and not fallback_used:
        alignment_rule = (
            "Free-input alignment rule: sentence 1 should paraphrase player_input_raw in world language "
            "(no quote echo); sentence 2 must describe the executed action and its direct consequence using impact_sources.action_effects. "
            "If event_present is true, runtime_event may appear as one additional beat only, never as direct causality from player_input."
        )
    elif input_mode == "free_input":
        alignment_rule = (
            "Free-input fallback rule: acknowledge attempted intent first, then narrate the fallback action "
            "and immediate in-world consequence without inventing unsupported actions."
        )
    else:
        alignment_rule = (
            "Button-choice rule: narrate the selected action first, then the immediate in-world consequence "
            "in the same grounded tone."
        )
    mismatch_rule = ""
    if input_mode == "free_input" and intent_action_alignment == "mismatch":
        mismatch_rule = (
            "Mismatch rule: do not frame intent as fully completed on sentence 1; use a bridge turn "
            "(for example but/instead/as an opening appears) before landing on executed action. "
        )
    event_rule = ""
    if input_mode == "free_input" and event_present:
        event_rule = (
            "Event layering rule: if runtime_event is present, keep it to one short added clause or sentence after executed action; "
            "do not merge event payoff into the same direct cause as player intent. "
        )
    nudge_rule = ""
    if nudge_enabled:
        nudge_rule = (
            "Quest nudge rule: include at most one subtle in-world task-direction nudge using either "
            "quest_nudge.mainline_hint or quest_nudge.sideline_hint. "
            "Do not narrate a quest log and do not use labels like main quest, side quest, objective, stage, or milestone. "
        )
    elif quest_nudge_suppressed_by_event:
        nudge_rule = (
            "Quest nudge suppression rule: skip quest-direction hints on event-present turns to avoid overloaded narration. "
        )

    return (
        "Story narration task. Return JSON only with exact schema "
        '{"narrative_text":"string"}. '
        "No markdown code fences. No extra keys. "
        "Narration only, 2-4 concise sentences. "
        "Use grounded cinematic second-person voice. "
        f"Causal policy is {causal_policy}; keep intent acknowledgment and effect sources strictly separated. "
        "Use cause -> consequence ordering: player action first, observable world response next. "
        "Keep actions consistent with executed_choice_id and selected_action_id. "
        "Do not quote player_input_raw verbatim. "
        "Soft-avoid system jargon in narrative_text: map/mapped/mapping, intent, choice_id, selected_action_id, "
        "fallback_reason, confidence, and avoid formulaic phrases like for this turn, the scene, story keeps moving. "
        "If impact_brief or impact_sources exists, explain one or two key impacts naturally with in-world wording first; "
        "use at most one short numeric mention and avoid ledger-style lists. "
        + event_rule
        + mismatch_rule
        + nudge_rule
        + alignment_rule
        + " Context: "
        + json.dumps(compact_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def build_author_assist_prompt(*, task: str, locale: str, context: dict | None) -> str:
    normalized_task = str(task or "").strip().lower()
    if normalized_task not in set(AUTHOR_ASSIST_TASKS_V4):
        normalized_task = "seed_expand"
    safe_locale = _clip_text(locale, limit=24) or "en"
    safe_context = context if isinstance(context, dict) else {}
    payload = {
        "task": normalized_task,
        "locale": safe_locale,
        "context": safe_context,
    }
    return (
        "Author-assist task. Return JSON only with exact schema: "
        '{"suggestions":object,"patch_preview":array,"warnings":array}. '
        "No markdown code fences. No extra top-level keys. "
        "patch_preview must be a list of objects with keys: id, path, label, value. "
        "Keep suggestions compact and practical for a creative v4 authoring wizard. "
        "Treat suggestions as patch candidates only; never assume direct persistence. "
        "Prefer layered outputs aligned with ASF v4: entry_mode/source_text/meta/world/characters/plot/flow/"
        "action/consequence/ending/systems/writer_journal/playability_policy. "
        "For story_ingest or seed_expand, include runnable flow.scenes scaffold and writer_journal seed turn. "
        "For scene_deepen, keep changes focused on one scene/layer. "
        "For option_weave, produce intent_aliases + action/go_to-safe option edits. "
        "For consequence_balance, keep effects moderate and compile-safe. "
        "For ending_design, include priority and trigger sketches. "
        "When task=consistency_check, emit concise warnings and optional repair patches. "
        f"Write text in locale '{safe_locale}'. "
        "Task context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
