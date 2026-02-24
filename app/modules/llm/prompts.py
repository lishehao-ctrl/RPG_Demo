import json
from dataclasses import dataclass

from app.config import settings

from app.modules.story.constants import AUTHOR_ASSIST_TASKS_V4

_SELECTION_MAX_VISIBLE_CHOICES = 4
_SELECTION_MAX_INTENTS = 4
_SELECTION_MAX_PATTERNS = 2
_NARRATION_MAX_IMPACT_ITEMS = 4
_AUTHOR_SCENE_WINDOW = 6
_AUTHOR_OPTION_WINDOW = 4
_AUTHOR_WRITER_TURN_WINDOW = 6
_AUTHOR_TEXT_LIMIT_SHORT = 120
_AUTHOR_TEXT_LIMIT_MEDIUM = 260
_AUTHOR_TEXT_LIMIT_LONG = 2400


@dataclass(frozen=True, slots=True)
class PromptEnvelope:
    system_text: str
    user_text: str
    schema_name: str
    schema_payload: dict | None = None
    tags: tuple[str, ...] = ()

    def to_messages(self) -> list[dict]:
        return [
            {"role": "system", "content": self.system_text},
            {"role": "user", "content": self.user_text},
        ]


def _schema_story_selection() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["choice_id", "use_fallback", "confidence", "intent_id", "notes"],
        "properties": {
            "choice_id": {"type": ["string", "null"]},
            "use_fallback": {"type": "boolean"},
            "confidence": {"type": "number"},
            "intent_id": {"type": ["string", "null"]},
            "notes": {"type": ["string", "null"]},
        },
    }


def _schema_narrative() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["narrative_text"],
        "properties": {
            "narrative_text": {"type": "string"},
        },
    }


def _schema_author_assist() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["suggestions", "patch_preview", "warnings"],
        "properties": {
            "suggestions": {"type": "object"},
            "patch_preview": {"type": "array"},
            "warnings": {"type": "array"},
        },
    }


def _schema_author_idea() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["core_conflict", "tension_loop_plan", "branch_design", "lexical_anchors"],
        "properties": {
            "core_conflict": {"type": "object"},
            "tension_loop_plan": {"type": "object"},
            "branch_design": {"type": "object"},
            "lexical_anchors": {"type": "object"},
        },
    }


def _schema_author_cast_blueprint() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["target_npc_count", "npc_roster", "beat_presence"],
        "properties": {
            "target_npc_count": {"type": "integer", "minimum": 3, "maximum": 6},
            "npc_roster": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "role", "motivation", "tension_hook", "relationship_to_protagonist"],
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                        "motivation": {"type": "string"},
                        "tension_hook": {"type": "string"},
                        "relationship_to_protagonist": {"type": "string"},
                    },
                },
            },
            "beat_presence": {
                "type": "object",
                "additionalProperties": False,
                "required": ["pressure_open", "pressure_escalation", "recovery_window", "decision_gate"],
                "properties": {
                    "pressure_open": {"type": "array", "items": {"type": "string"}},
                    "pressure_escalation": {"type": "array", "items": {"type": "string"}},
                    "recovery_window": {"type": "array", "items": {"type": "string"}},
                    "decision_gate": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


def _prompt_budget_limit(tags: tuple[str, ...]) -> int:
    if "author" in tags:
        return max(2000, int(settings.llm_prompt_author_max_chars))
    return max(1500, int(settings.llm_prompt_play_max_chars))


def _trim_prompt_text(text: str, *, tags: tuple[str, ...]) -> str:
    limit = _prompt_budget_limit(tags)
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit]


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


def build_author_assist_repair_prompt(raw_text: str) -> str:
    return (
        "Author-assist repair task. Fix output to JSON with exact schema: "
        '{"suggestions":object,"patch_preview":array,"warnings":array}. '
        "Return JSON only. No markdown code fences. No extra top-level keys. "
        "patch_preview entries must contain keys: id, path, label, value. Source:\n"
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
    prompt_text = (
        "Story selection task. Return JSON only with schema: "
        "{choice_id:string|null,use_fallback:boolean,confidence:number,intent_id:string|null,notes:string|null}. "
        "Map player_input to one visible choice_id from valid_choice_ids. "
        "If uncertain, use_fallback=true and choice_id=null. Context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return _trim_prompt_text(prompt_text, tags=("play", "selection"))


def build_story_selection_envelope(
    *,
    player_input: str,
    valid_choice_ids: list[str],
    visible_choices: list[dict],
    intents: list[dict] | None = None,
    state_snippet: dict | None = None,
) -> PromptEnvelope:
    return PromptEnvelope(
        system_text=(
            "You are a strict story-selection JSON generator. "
            "Return one JSON object only. No markdown, no prose, no extra keys."
        ),
        user_text=build_story_selection_prompt(
            player_input=player_input,
            valid_choice_ids=valid_choice_ids,
            visible_choices=visible_choices,
            intents=intents,
            state_snippet=state_snippet,
        ),
        schema_name="story_selection_v1",
        schema_payload=_schema_story_selection(),
        tags=("play", "selection"),
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

    prompt_text = (
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
    return _trim_prompt_text(prompt_text, tags=("play", "narration"))


def build_story_narration_envelope(payload: dict) -> PromptEnvelope:
    return PromptEnvelope(
        system_text=(
            "You are a strict narrative JSON generator for an interactive story runtime. "
            "Output exactly one JSON object with no extra keys."
        ),
        user_text=build_story_narration_prompt(payload),
        schema_name="story_narrative_v1",
        schema_payload=_schema_narrative(),
        tags=("play", "narration"),
    )


def _author_compaction_profile(task: str) -> dict:
    mode = str(settings.llm_prompt_compaction_level or "aggressive").strip().lower()
    aggressive = mode == "aggressive"
    base = {
        "scene_window": 6 if aggressive else 8,
        "option_window": 4 if aggressive else 4,
        "writer_turn_window": 6 if aggressive else 8,
        "source_limit": _AUTHOR_TEXT_LIMIT_LONG if aggressive else 3200,
    }
    if task == "story_ingest":
        base["source_limit"] = 2600 if aggressive else 3400
        base["scene_window"] = 4 if aggressive else 6
    elif task == "continue_write":
        base["scene_window"] = 5 if aggressive else 7
        base["writer_turn_window"] = 4 if aggressive else 6
    elif task == "seed_expand":
        base["scene_window"] = 4 if aggressive else 6
    return base


def _compact_author_scene(scene: dict, *, option_window: int) -> dict:
    options = scene.get("options") if isinstance(scene.get("options"), list) else []
    compact_options = []
    for option in options[:max(1, option_window)]:
        if not isinstance(option, dict):
            continue
        compact_options.append(
            {
                "option_key": _clip_text(option.get("option_key"), limit=48),
                "label": _clip_text(option.get("label"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
                "action_type": _clip_text(option.get("action_type"), limit=24),
                "go_to": _clip_text(option.get("go_to"), limit=48),
                "is_key_decision": bool(option.get("is_key_decision", False)),
            }
        )
    return {
        "scene_key": _clip_text(scene.get("scene_key"), limit=48),
        "title": _clip_text(scene.get("title"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
        "setup": _clip_text(scene.get("setup"), limit=_AUTHOR_TEXT_LIMIT_MEDIUM),
        "is_end": bool(scene.get("is_end", False)),
        "options": compact_options,
    }


def _compact_author_assist_context(context: dict | None, *, task: str | None = None) -> dict:
    if not isinstance(context, dict):
        return {}

    normalized_task = _normalize_author_assist_task(task or str(context.get("task") or "seed_expand"))
    profile = _author_compaction_profile(normalized_task)

    compact: dict[str, object] = {}
    for key in (
        "format_version",
        "layer",
        "entry_mode",
        "operation",
        "target_scope",
        "target_scene_key",
        "target_option_key",
        "preserve_existing",
        "story_id",
        "locale",
    ):
        if key not in context:
            continue
        compact[key] = context.get(key)

    for key in ("title", "premise", "mainline_goal", "scene_key", "scene_title", "option_label", "action_type"):
        value = context.get(key)
        if value is None:
            continue
        compact[key] = _clip_text(value, limit=_AUTHOR_TEXT_LIMIT_SHORT)

    for key in ("seed_text", "global_brief", "continue_input"):
        value = context.get(key)
        if value is None:
            continue
        compact[key] = _clip_text(value, limit=_AUTHOR_TEXT_LIMIT_MEDIUM)
    source_text = context.get("source_text")
    if source_text is not None:
        compact["source_text"] = _clip_text(source_text, limit=max(800, int(profile.get("source_limit", _AUTHOR_TEXT_LIMIT_LONG))))

    writer_journal = context.get("writer_journal")
    if isinstance(writer_journal, list):
        compact_turns = []
        for turn in writer_journal[-max(1, int(profile.get("writer_turn_window", _AUTHOR_WRITER_TURN_WINDOW))):]:
            if not isinstance(turn, dict):
                continue
            compact_turns.append(
                {
                    "turn_id": _clip_text(turn.get("turn_id"), limit=48),
                    "phase": _clip_text(turn.get("phase"), limit=24),
                    "author_text": _clip_text(turn.get("author_text"), limit=_AUTHOR_TEXT_LIMIT_MEDIUM),
                    "assistant_text": _clip_text(turn.get("assistant_text"), limit=_AUTHOR_TEXT_LIMIT_MEDIUM),
                }
            )
        compact["writer_journal"] = compact_turns

    draft = context.get("draft")
    if isinstance(draft, dict):
        compact_draft: dict[str, object] = {}
        meta = draft.get("meta")
        if isinstance(meta, dict):
            compact_draft["meta"] = {
                "story_id": _clip_text(meta.get("story_id"), limit=48),
                "title": _clip_text(meta.get("title"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
                "locale": _clip_text(meta.get("locale"), limit=24),
            }
        plot = draft.get("plot")
        if isinstance(plot, dict):
            compact_draft["plot"] = {
                "mainline_goal": _clip_text(plot.get("mainline_goal"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            }
        flow = draft.get("flow")
        if isinstance(flow, dict):
            scenes = flow.get("scenes") if isinstance(flow.get("scenes"), list) else []
            target_scene_key = _clip_text(context.get("target_scene_key"), limit=48)
            selected_index = 0
            if target_scene_key:
                for idx, scene in enumerate(scenes):
                    if not isinstance(scene, dict):
                        continue
                    if str(scene.get("scene_key") or "") == target_scene_key:
                        selected_index = idx
                        break
            if scenes:
                scene_window = max(1, int(profile.get("scene_window", _AUTHOR_SCENE_WINDOW)))
                left = max(0, selected_index - (scene_window // 2))
                right = min(len(scenes), left + scene_window)
                selected_scenes = scenes[left:right]
            else:
                selected_scenes = []
            compact_draft["flow"] = {
                "start_scene_key": _clip_text(flow.get("start_scene_key"), limit=48),
                "scenes": [
                    _compact_author_scene(scene, option_window=max(1, int(profile.get("option_window", _AUTHOR_OPTION_WINDOW))))
                    for scene in selected_scenes
                    if isinstance(scene, dict)
                ],
            }
        characters = draft.get("characters")
        if isinstance(characters, dict):
            compact_characters: dict[str, object] = {}
            protagonist = characters.get("protagonist")
            if isinstance(protagonist, dict):
                compact_characters["protagonist"] = {
                    "name": _clip_text(protagonist.get("name"), limit=64),
                    "role": _clip_text(protagonist.get("role"), limit=64),
                    "traits": [
                        _clip_text(item, limit=40)
                        for item in (protagonist.get("traits") if isinstance(protagonist.get("traits"), list) else [])[:4]
                        if _clip_text(item, limit=40)
                    ],
                }
            npcs = characters.get("npcs")
            if isinstance(npcs, list):
                compact_npcs: list[dict[str, object]] = []
                for npc in npcs[:6]:
                    if not isinstance(npc, dict):
                        continue
                    name = _clip_text(npc.get("name"), limit=64)
                    if not name:
                        continue
                    compact_npcs.append(
                        {
                            "name": name,
                            "role": _clip_text(npc.get("role"), limit=64),
                            "traits": [
                                _clip_text(item, limit=40)
                                for item in (npc.get("traits") if isinstance(npc.get("traits"), list) else [])[:4]
                                if _clip_text(item, limit=40)
                            ],
                        }
                    )
                compact_characters["npcs"] = compact_npcs
            relationship_axes = characters.get("relationship_axes")
            if isinstance(relationship_axes, dict):
                compact_axes: dict[str, str] = {}
                for idx, (raw_key, raw_value) in enumerate(relationship_axes.items()):
                    if idx >= 6:
                        break
                    key = _clip_text(raw_key, limit=48)
                    value = _clip_text(raw_value, limit=96)
                    if not key or not value:
                        continue
                    compact_axes[key] = value
                if compact_axes:
                    compact_characters["relationship_axes"] = compact_axes
            if compact_characters:
                compact_draft["characters"] = compact_characters
        if compact_draft:
            compact["draft"] = compact_draft

    return compact


def _normalize_author_assist_task(task: str) -> str:
    normalized_task = str(task or "").strip().lower()
    if normalized_task not in set(AUTHOR_ASSIST_TASKS_V4):
        return "seed_expand"
    return normalized_task


def _compact_idea_blueprint(idea_blueprint: dict | None) -> dict:
    if not isinstance(idea_blueprint, dict):
        return {}
    core_conflict = idea_blueprint.get("core_conflict") if isinstance(idea_blueprint.get("core_conflict"), dict) else {}
    tension_loop_plan = idea_blueprint.get("tension_loop_plan") if isinstance(idea_blueprint.get("tension_loop_plan"), dict) else {}
    branch_design = idea_blueprint.get("branch_design") if isinstance(idea_blueprint.get("branch_design"), dict) else {}
    lexical_anchors = idea_blueprint.get("lexical_anchors") if isinstance(idea_blueprint.get("lexical_anchors"), dict) else {}
    out: dict[str, object] = {
        "core_conflict": {
            "protagonist": _clip_text(core_conflict.get("protagonist"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            "opposition_actor": _clip_text(core_conflict.get("opposition_actor"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            "scarce_resource": _clip_text(core_conflict.get("scarce_resource"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            "deadline": _clip_text(core_conflict.get("deadline"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            "irreversible_risk": _clip_text(core_conflict.get("irreversible_risk"), limit=_AUTHOR_TEXT_LIMIT_MEDIUM),
        },
        "tension_loop_plan": {},
        "branch_design": {
            "high_risk_push": {},
            "recovery_stabilize": {},
        },
        "lexical_anchors": {
            "must_include_terms": [],
            "avoid_generic_labels": [],
        },
    }
    for beat in ("pressure_open", "pressure_escalation", "recovery_window", "decision_gate"):
        node = tension_loop_plan.get(beat) if isinstance(tension_loop_plan.get(beat), dict) else {}
        entities_raw = node.get("required_entities") if isinstance(node.get("required_entities"), list) else []
        entities = [_clip_text(item, limit=48) for item in entities_raw if _clip_text(item, limit=48)]
        risk_level = node.get("risk_level")
        try:
            risk_level = int(risk_level)
        except Exception:  # noqa: BLE001
            risk_level = 3
        risk_level = max(1, min(5, risk_level))
        out["tension_loop_plan"][beat] = {
            "objective": _clip_text(node.get("objective"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            "stakes": _clip_text(node.get("stakes"), limit=_AUTHOR_TEXT_LIMIT_MEDIUM),
            "required_entities": entities[:6],
            "risk_level": risk_level,
        }
    for key in ("high_risk_push", "recovery_stabilize"):
        branch = branch_design.get(key) if isinstance(branch_design.get(key), dict) else {}
        out["branch_design"][key] = {
            "short_term_gain": _clip_text(branch.get("short_term_gain"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            "long_term_cost": _clip_text(branch.get("long_term_cost"), limit=_AUTHOR_TEXT_LIMIT_SHORT),
            "signature_action_type": _clip_text(branch.get("signature_action_type"), limit=24),
        }
    for key in ("must_include_terms", "avoid_generic_labels"):
        values = lexical_anchors.get(key) if isinstance(lexical_anchors.get(key), list) else []
        out["lexical_anchors"][key] = [
            _clip_text(item, limit=48)
            for item in values[:8]
            if _clip_text(item, limit=48)
        ]
    return out


def _compact_cast_blueprint(cast_blueprint: dict | None) -> dict:
    if not isinstance(cast_blueprint, dict):
        return {}

    target_npc_count = cast_blueprint.get("target_npc_count")
    try:
        normalized_target = int(target_npc_count)
    except Exception:  # noqa: BLE001
        normalized_target = 4
    normalized_target = max(3, min(6, normalized_target))

    roster_raw = cast_blueprint.get("npc_roster")
    compact_roster: list[dict[str, str]] = []
    if isinstance(roster_raw, list):
        for item in roster_raw[:6]:
            if not isinstance(item, dict):
                continue
            name = _clip_text(item.get("name"), limit=64)
            role = _clip_text(item.get("role"), limit=64)
            motivation = _clip_text(item.get("motivation"), limit=_AUTHOR_TEXT_LIMIT_SHORT)
            tension_hook = _clip_text(item.get("tension_hook"), limit=_AUTHOR_TEXT_LIMIT_SHORT)
            relationship = _clip_text(item.get("relationship_to_protagonist"), limit=_AUTHOR_TEXT_LIMIT_SHORT)
            if not all([name, role, motivation, tension_hook, relationship]):
                continue
            compact_roster.append(
                {
                    "name": name,
                    "role": role,
                    "motivation": motivation,
                    "tension_hook": tension_hook,
                    "relationship_to_protagonist": relationship,
                }
            )

    compact_beats: dict[str, list[str]] = {
        "pressure_open": [],
        "pressure_escalation": [],
        "recovery_window": [],
        "decision_gate": [],
    }
    beat_presence = cast_blueprint.get("beat_presence")
    if isinstance(beat_presence, dict):
        for beat in compact_beats.keys():
            values = beat_presence.get(beat)
            compact_beats[beat] = [
                _clip_text(item, limit=64)
                for item in (values if isinstance(values, list) else [])[:6]
                if _clip_text(item, limit=64)
            ]

    return {
        "target_npc_count": normalized_target,
        "npc_roster": compact_roster,
        "beat_presence": compact_beats,
    }


def build_author_idea_repair_prompt(raw_text: str) -> str:
    return (
        "Author idea repair task. Fix output to JSON with exact schema: "
        '{"core_conflict":object,"tension_loop_plan":object,"branch_design":object,"lexical_anchors":object}. '
        "Return JSON only. No markdown code fences. No extra top-level keys. "
        "Required beats in tension_loop_plan: pressure_open, pressure_escalation, recovery_window, decision_gate. Source:\n"
        + raw_text
    )


def build_author_cast_expand_prompt(*, task: str, locale: str, context: dict | None, idea_blueprint: dict) -> str:
    normalized_task = _normalize_author_assist_task(task)
    safe_locale = _clip_text(locale, limit=24) or "en"
    safe_context = _compact_author_assist_context(context if isinstance(context, dict) else {}, task=normalized_task)
    compact_blueprint = _compact_idea_blueprint(idea_blueprint)
    payload = {
        "task": normalized_task,
        "locale": safe_locale,
        "context": safe_context,
        "idea_blueprint": compact_blueprint,
    }
    prompt_text = (
        "Author cast expansion task. Return JSON only with exact schema: "
        '{"target_npc_count":integer,"npc_roster":array,"beat_presence":object}. '
        "No markdown code fences. No extra top-level keys. "
        "target_npc_count must be between 3 and 6. "
        "npc_roster entries must include name, role, motivation, tension_hook, relationship_to_protagonist. "
        "beat_presence must include pressure_open, pressure_escalation, recovery_window, decision_gate and list NPC names used in each beat. "
        "Design cast to preserve existing named NPCs and only supplement gaps. "
        "Role mix must include at least two of: support, rival, gatekeeper. "
        + _author_task_specific_rule(normalized_task)
        + " "
        f"Write text in locale '{safe_locale}'. "
        "Task context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return _trim_prompt_text(prompt_text, tags=("author", "cast", normalized_task))


def _author_task_specific_rule(task: str) -> str:
    rules = {
        "seed_expand": (
            "Task=seed_expand: extract protagonist, opposition_actor, scarce_resource, deadline, irreversible risk. "
            "Generate exactly 4 scenes keyed pressure_open, pressure_escalation, recovery_window, decision_gate. "
            "Every non-end scene must keep 2-4 options, include one high-reward/high-risk option, and keep one recovery option every two scenes."
        ),
        "story_ingest": (
            "Task=story_ingest: convert source_text conflict into playable flow, preserving core entities and stakes. "
            "Map source conflict to scarce_resource, deadline, irreversible risk and keep go_to references compile-safe."
        ),
        "continue_write": (
            "Task=continue_write: append one playable follow-up scene after decision gate, keep branch contrast, and repair graph references."
        ),
        "scene_deepen": "Task=scene_deepen: only refine one scene and keep graph stable.",
        "option_weave": "Task=option_weave: improve option intents/aliases and keep action/go_to compile-safe.",
        "consequence_balance": "Task=consequence_balance: rebalance requirements/effects conservatively; avoid extreme deltas.",
        "ending_design": "Task=ending_design: provide ending trigger and priority sketches aligned with current flow.",
        "trim_content": "Task=trim_content: remove requested content and repair dangling graph references.",
        "spice_branch": "Task=spice_branch: increase strategy contrast while preserving 2-4 options per scene.",
        "tension_rebalance": (
            "Task=tension_rebalance: restore pressure-recovery rhythm by reducing extreme penalties and adding recovery windows."
        ),
        "consistency_check": "Task=consistency_check: emit concise warnings and optional repair patches only.",
        "beat_to_scene": "Task=beat_to_scene: project the beat into one playable scene with compile-safe options.",
    }
    return rules.get(task, rules["seed_expand"])


def _author_common_constraint_block() -> str:
    return (
        "Return JSON only, no markdown fences, no extra top-level keys. "
        "Treat suggestions as patch candidates only; never assume persistence. "
        "Honor context.operation, context.target_scope, context.target_scene_key, context.target_option_key, "
        "and context.preserve_existing when present."
    )


def build_author_story_build_prompt(
    *,
    task: str,
    locale: str,
    context: dict | None,
    idea_blueprint: dict,
    cast_blueprint: dict | None = None,
) -> str:
    normalized_task = _normalize_author_assist_task(task)
    safe_locale = _clip_text(locale, limit=24) or "en"
    safe_context = _compact_author_assist_context(context if isinstance(context, dict) else {}, task=normalized_task)
    compact_blueprint = _compact_idea_blueprint(idea_blueprint)
    payload = {
        "task": normalized_task,
        "locale": safe_locale,
        "context": safe_context,
        "idea_blueprint": compact_blueprint,
    }
    compact_cast_blueprint = _compact_cast_blueprint(cast_blueprint)
    if compact_cast_blueprint:
        payload["cast_blueprint"] = compact_cast_blueprint
    prompt_text = (
        "Author story build task. Return JSON only with exact schema: "
        '{"suggestions":object,"patch_preview":array,"warnings":array}. '
        "patch_preview must be a list of objects with keys: id, path, label, value. "
        + _author_common_constraint_block()
        + " "
        "Use idea_blueprint as mandatory creative constraints for conflict, branch contrast, and pacing. "
        "Treat suggestions as patch candidates only; never assume direct persistence. "
        "Prefer layered outputs aligned with ASF v4: entry_mode/source_text/meta/world/characters/plot/flow/"
        "action/consequence/ending/systems/writer_journal/playability_policy. "
        + _author_task_specific_rule(normalized_task)
        + " "
        "Option labels must include seed/source entities and avoid generic placeholders from lexical_anchors. "
        "When cast_blueprint is present, preserve existing NPC names, supplement NPCs to 3-5 (hard cap 6), "
        "and ensure each NPC has concrete story function across beats. "
        f"Write text in locale '{safe_locale}'. "
        "Task context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return _trim_prompt_text(prompt_text, tags=("author", "build", normalized_task))


def build_author_assist_prompt(*, task: str, locale: str, context: dict | None) -> str:
    normalized_task = _normalize_author_assist_task(task)
    safe_locale = _clip_text(locale, limit=24) or "en"
    safe_context = _compact_author_assist_context(context if isinstance(context, dict) else {}, task=normalized_task)
    payload = {
        "task": normalized_task,
        "locale": safe_locale,
        "context": safe_context,
    }
    prompt_text = (
        "Author-assist task. Return JSON only with exact schema: "
        '{"suggestions":object,"patch_preview":array,"warnings":array}. '
        "patch_preview must be a list of objects with keys: id, path, label, value. "
        + _author_common_constraint_block()
        + " "
        "Keep suggestions compact and practical for a creative v4 authoring wizard. "
        "Treat suggestions as patch candidates only; never assume direct persistence. "
        "Prefer layered outputs aligned with ASF v4: entry_mode/source_text/meta/world/characters/plot/flow/"
        "action/consequence/ending/systems/writer_journal/playability_policy. "
        + _author_task_specific_rule(normalized_task)
        + " "
        f"Write text in locale '{safe_locale}'. "
        "Task context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return _trim_prompt_text(prompt_text, tags=("author", "assist", normalized_task))


def build_author_idea_expand_prompt(*, task: str, locale: str, context: dict | None) -> str:
    normalized_task = _normalize_author_assist_task(task)
    safe_locale = _clip_text(locale, limit=24) or "en"
    safe_context = _compact_author_assist_context(context if isinstance(context, dict) else {}, task=normalized_task)
    payload = {
        "task": normalized_task,
        "locale": safe_locale,
        "context": safe_context,
    }
    prompt_text = (
        "Author idea expansion task. Return JSON only with exact schema: "
        '{"core_conflict":object,"tension_loop_plan":object,"branch_design":object,"lexical_anchors":object}. '
        "No markdown code fences. No extra top-level keys. "
        "core_conflict must include protagonist, opposition_actor, scarce_resource, deadline, irreversible_risk. "
        "tension_loop_plan must include pressure_open, pressure_escalation, recovery_window, decision_gate. "
        "Each beat must include objective, stakes, required_entities(array), risk_level(1-5). "
        "branch_design must include high_risk_push and recovery_stabilize with short_term_gain, long_term_cost, signature_action_type. "
        "lexical_anchors must include must_include_terms(array) and avoid_generic_labels(array). "
        + _author_task_specific_rule(normalized_task)
        + " "
        f"Write text in locale '{safe_locale}'. "
        "Task context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return _trim_prompt_text(prompt_text, tags=("author", "idea", normalized_task))


def build_author_idea_expand_envelope(*, task: str, locale: str, context: dict | None) -> PromptEnvelope:
    normalized_task = _normalize_author_assist_task(task)
    return PromptEnvelope(
        system_text=(
            "You are a strict author-idea JSON generator for ASF v4 planning. "
            "Return one JSON object only. No extra keys."
        ),
        user_text=build_author_idea_expand_prompt(task=normalized_task, locale=locale, context=context),
        schema_name="author_idea_blueprint_v1",
        schema_payload=_schema_author_idea(),
        tags=("author", "idea", normalized_task),
    )


def build_author_cast_expand_envelope(
    *,
    task: str,
    locale: str,
    context: dict | None,
    idea_blueprint: dict,
) -> PromptEnvelope:
    normalized_task = _normalize_author_assist_task(task)
    return PromptEnvelope(
        system_text=(
            "You are a strict author-cast JSON generator for ASF v4 planning. "
            "Return one JSON object only. No extra keys."
        ),
        user_text=build_author_cast_expand_prompt(
            task=normalized_task,
            locale=locale,
            context=context,
            idea_blueprint=idea_blueprint,
        ),
        schema_name="author_cast_blueprint_v1",
        schema_payload=_schema_author_cast_blueprint(),
        tags=("author", "cast", normalized_task),
    )


def build_author_story_build_envelope(
    *,
    task: str,
    locale: str,
    context: dict | None,
    idea_blueprint: dict,
    cast_blueprint: dict | None = None,
) -> PromptEnvelope:
    normalized_task = _normalize_author_assist_task(task)
    return PromptEnvelope(
        system_text=(
            "You are a strict author-assist JSON generator for ASF v4 patches. "
            "Return one JSON object only. No extra keys."
        ),
        user_text=build_author_story_build_prompt(
            task=normalized_task,
            locale=locale,
            context=context,
            idea_blueprint=idea_blueprint,
            cast_blueprint=cast_blueprint,
        ),
        schema_name="author_assist_payload_v1",
        schema_payload=_schema_author_assist(),
        tags=("author", "build", normalized_task),
    )


def build_author_assist_envelope(*, task: str, locale: str, context: dict | None) -> PromptEnvelope:
    normalized_task = _normalize_author_assist_task(task)
    return PromptEnvelope(
        system_text=(
            "You are a strict author-assist JSON generator for ASF v4 patches. "
            "Return one JSON object only. No extra keys."
        ),
        user_text=build_author_assist_prompt(task=normalized_task, locale=locale, context=context),
        schema_name="author_assist_payload_v1",
        schema_payload=_schema_author_assist(),
        tags=("author", "assist", normalized_task),
    )
