from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import settings

_SELECTION_MAX_VISIBLE_CHOICES = 4
_SELECTION_MAX_INTENTS = 4
_SELECTION_MAX_PATTERNS = 2
_NARRATION_MAX_IMPACT_ITEMS = 4


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


def _trim_prompt_text(text: str) -> str:
    limit = max(1500, int(settings.llm_prompt_play_max_chars))
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
    npc_context_raw = state_snippet.get("npc_context")
    if isinstance(npc_context_raw, list):
        npc_context: list[dict] = []
        for item in npc_context_raw:
            if not isinstance(item, dict):
                continue
            npc_id = _clip_text(item.get("npc_id"), limit=48)
            summary = _clip_text(item.get("summary"), limit=120)
            if not npc_id or not summary:
                continue
            npc_context.append({"npc_id": npc_id, "summary": summary})
            if len(npc_context) >= 3:
                break
        if npc_context:
            out["npc_context"] = npc_context
    return out


def _compact_visible_choices(visible_choices: list[dict] | None) -> list[dict]:
    if not isinstance(visible_choices, list):
        return []
    out: list[dict] = []
    for raw in visible_choices:
        if not isinstance(raw, dict):
            continue
        choice_id = _clip_text(raw.get("choice_id"), limit=48)
        display_text = _clip_text(raw.get("display_text"), limit=120)
        if not choice_id or not display_text:
            continue
        out.append({"choice_id": choice_id, "display_text": display_text})
        if len(out) >= _SELECTION_MAX_VISIBLE_CHOICES:
            break
    return out


def _compact_intents(intents: list[dict] | None) -> list[dict]:
    if not isinstance(intents, list):
        return []
    out: list[dict] = []
    for raw in intents:
        if not isinstance(raw, dict):
            continue
        intent_id = _clip_text(raw.get("intent_id"), limit=48)
        alias_choice_id = _clip_text(raw.get("alias_choice_id"), limit=48)
        if not intent_id or not alias_choice_id:
            continue
        patterns_raw = raw.get("patterns") if isinstance(raw.get("patterns"), list) else []
        patterns: list[str] = []
        for item in patterns_raw:
            text = _clip_text(item, limit=48)
            if text:
                patterns.append(text)
            if len(patterns) >= _SELECTION_MAX_PATTERNS:
                break
        out.append(
            {
                "intent_id": intent_id,
                "alias_choice_id": alias_choice_id,
                "description": _clip_text(raw.get("description"), limit=80),
                "patterns": patterns,
            }
        )
        if len(out) >= _SELECTION_MAX_INTENTS:
            break
    return out


def build_story_selection_prompt(
    *,
    player_input: str,
    valid_choice_ids: list[str],
    visible_choices: list[dict],
    intents: list[dict],
    state_snippet: dict,
) -> str:
    context = {
        "player_input": _clip_text(player_input, limit=240),
        "valid_choice_ids": [_clip_text(choice_id, limit=48) for choice_id in valid_choice_ids[:8] if _clip_text(choice_id, limit=48)],
        "visible_choices": _compact_visible_choices(visible_choices),
        "intents": _compact_intents(intents),
        "state": _compact_selection_state(state_snippet),
    }

    prompt_text = (
        "Story selection task. "
        "Return JSON only with schema {\"choice_id\":string|null,\"use_fallback\":boolean,\"confidence\":number,\"intent_id\":string|null,\"notes\":string|null}. "
        "No markdown code fences. "
        "Prefer visible choices and semantic match to player_input. "
        "Use fallback when confidence is low or no valid mapping exists. "
        "Context:"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )
    return _trim_prompt_text(prompt_text)


def build_story_selection_envelope(
    *,
    player_input: str,
    valid_choice_ids: list[str],
    visible_choices: list[dict],
    intents: list[dict],
    state_snippet: dict,
) -> PromptEnvelope:
    return PromptEnvelope(
        system_text="Return STRICT JSON. No markdown. No explanation.",
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


def _compact_state_snapshot(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return {}
    out: dict[str, object] = {}
    for key in ("slot",):
        value = state.get(key)
        if value is not None:
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
        if numeric != 0:
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


def build_story_narration_prompt(payload: dict) -> str:
    compact_payload = {
        "input_mode": _clip_text(payload.get("input_mode"), limit=32),
        "player_input_raw": _clip_text(payload.get("player_input_raw"), limit=240),
        "causal_policy": _clip_text(payload.get("causal_policy"), limit=48),
        "intent_action_alignment": _clip_text(payload.get("intent_action_alignment"), limit=48),
        "node_transition": payload.get("node_transition") if isinstance(payload.get("node_transition"), dict) else {},
        "selection_resolution": payload.get("selection_resolution") if isinstance(payload.get("selection_resolution"), dict) else {},
        "state_snapshot_before": _compact_state_snapshot(payload.get("state_snapshot_before")),
        "state_snapshot_after": _compact_state_snapshot(payload.get("state_snapshot_after")),
        "state_delta": _compact_state_delta(payload.get("state_delta")),
        "impact_brief": _compact_impact_brief(payload.get("impact_brief")),
        "impact_sources": payload.get("impact_sources") if isinstance(payload.get("impact_sources"), dict) else {},
        "event_present": bool(payload.get("event_present")),
        "runtime_event": payload.get("runtime_event") if isinstance(payload.get("runtime_event"), dict) else {},
        "quest_nudge": payload.get("quest_nudge") if isinstance(payload.get("quest_nudge"), dict) else {},
        "quest_nudge_suppressed_by_event": bool(payload.get("quest_nudge_suppressed_by_event")),
    }

    prompt_text = (
        "Story narration task. Return JSON only with schema {\"narrative_text\":\"string\"}. "
        "No markdown code fences. "
        "Use grounded cinematic second-person voice. "
        "Write 2-4 concise sentences with cause -> consequence ordering. "
        "Respect strict separation between player intent acknowledgment and executed outcome. "
        "Context:"
        + json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))
    )
    return _trim_prompt_text(prompt_text)


def build_story_narration_envelope(payload: dict) -> PromptEnvelope:
    return PromptEnvelope(
        system_text="Return STRICT JSON. No markdown. No explanation.",
        user_text=build_story_narration_prompt(payload),
        schema_name="story_narrative_v1",
        schema_payload=_schema_narrative(),
        tags=("play", "narration"),
    )


def build_narrative_repair_prompt(raw_text: str) -> str:
    prompt_text = (
        "Narrative repair task. "
        "Return JSON only with schema {\"narrative_text\":\"string\"}. "
        "No markdown code fences. "
        "Source:"
        + _clip_text(raw_text, limit=1200)
    )
    return _trim_prompt_text(prompt_text)


def build_fallback_polish_prompt(ctx: dict, skeleton_text: str) -> str:
    compact_ctx = {
        "locale": _clip_text(ctx.get("locale"), limit=16),
        "fallback_reason": _clip_text(ctx.get("fallback_reason"), limit=32),
        "node_id": _clip_text(ctx.get("node_id"), limit=64),
        "player_input": _clip_text(ctx.get("player_input"), limit=200),
        "mapping_note": _clip_text(ctx.get("mapping_note"), limit=80),
        "causal_policy": _clip_text(ctx.get("causal_policy"), limit=48),
        "intent_action_alignment": _clip_text(ctx.get("intent_action_alignment"), limit=48),
        "event_present": bool(ctx.get("event_present")),
        "quest_nudge_suppressed_by_event": bool(ctx.get("quest_nudge_suppressed_by_event")),
        "attempted_choice_id": _clip_text(ctx.get("attempted_choice_id"), limit=64),
        "attempted_choice_label": _clip_text(ctx.get("attempted_choice_label"), limit=120),
        "visible_choices": [item for item in (ctx.get("visible_choices") or []) if isinstance(item, dict)][:4],
        "impact_sources": ctx.get("impact_sources") if isinstance(ctx.get("impact_sources"), dict) else {},
        "runtime_event": ctx.get("runtime_event") if isinstance(ctx.get("runtime_event"), dict) else {},
        "quest_nudge": ctx.get("quest_nudge") if isinstance(ctx.get("quest_nudge"), dict) else {},
        "state_snippet": _compact_state_snapshot(ctx.get("state_snippet") if isinstance(ctx.get("state_snippet"), dict) else {}),
        "short_recent_summary": [
            _clip_text(item, limit=120)
            for item in (ctx.get("short_recent_summary") or [])
            if _clip_text(item, limit=120)
        ][:4],
    }

    prompt_text = (
        "Fallback narration polish task. Return JSON only with schema {\"narrative_text\":\"string\"}. "
        "No markdown code fences. "
        "Write exactly 2 concise sentences. "
        "Sentence 1 acknowledges attempted intent in-world; sentence 2 states executed outcome and immediate consequence. "
        "Avoid system jargon and rejection phrasing. "
        "Context:"
        + json.dumps(compact_ctx, ensure_ascii=False, separators=(",", ":"))
        + " Skeleton:"
        + _clip_text(skeleton_text, limit=280)
    )
    return _trim_prompt_text(prompt_text)
