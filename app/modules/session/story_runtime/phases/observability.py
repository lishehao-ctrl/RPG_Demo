from __future__ import annotations

import re

from app.modules.session.story_runtime.models import EndingResolution, EventResolution, StoryChoiceResolution

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


def clip_prompt_text(value: object, *, max_len: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[:max_len]


def compact_state_snapshot_for_prompt(state: dict) -> dict:
    if not isinstance(state, dict):
        return {}
    run_state = state.get("run_state") if isinstance(state.get("run_state"), dict) else {}
    out: dict[str, object] = {}
    for key in ("slot",):
        value = state.get(key)
        if value is None:
            continue
        out[key] = clip_prompt_text(value, max_len=24)
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


def compact_state_delta_for_prompt(state_delta: dict, *, max_items: int = 4) -> dict:
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
        out["slot"] = clip_prompt_text(state_delta.get("slot"), max_len=24)
    return out


def build_impact_brief_for_prompt(state_delta: dict) -> list[str]:
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
        out.append(f"time moved to {clip_prompt_text(slot_value, max_len=24)}")
    return out[:3]


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return int(default)


def estimate_turn_intensity(state_delta: dict, *, fallback_used: bool, event_present: bool) -> float:
    delta = state_delta if isinstance(state_delta, dict) else {}
    energy = abs(safe_int(delta.get("energy"), 0))
    money = abs(safe_int(delta.get("money"), 0))
    knowledge = abs(safe_int(delta.get("knowledge"), 0))
    affection = abs(safe_int(delta.get("affection"), 0))
    base = (energy / 30.0) + (money / 80.0) + (knowledge / 8.0) + (affection / 8.0)
    if fallback_used:
        base += 0.15
    if event_present:
        base += 0.15
    return max(0.0, min(float(base), 1.0))


def recovery_offered_from_choices(choices: list[dict]) -> bool:
    for item in choices or []:
        choice_type = str(item.get("type") or "").strip().lower()
        if choice_type == "rest":
            return True
        text = str(item.get("text") or "").strip().lower()
        if any(token in text for token in ("rest", "recover", "reset", "pause")):
            return True
    return False


def normalize_hint_source(value: object, *, max_words: int = 5) -> str | None:
    text = clip_prompt_text(value, max_len=72)
    text = text.replace("_", " ").strip()
    text = _QUEST_HINT_SYSTEM_TERMS_RE.sub("", text)
    text = " ".join(text.split())
    if not text:
        return None
    words = text.split(" ")
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip()
    return text.strip(" ,.;:")


def clip_hint_words(text: str, *, max_words: int = 16) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,.;:")


def tokenize_alignment_text(value: object) -> set[str]:
    text = " ".join(str(value or "").lower().split())
    if not text:
        return set()
    return {token.strip("-'") for token in _ALIGNMENT_TOKEN_RE.findall(text) if token.strip("-'")}


def infer_action_from_label(selected_choice_label: str | None) -> str | None:
    label_tokens = tokenize_alignment_text(selected_choice_label)
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


def derive_intent_action_alignment(
    *,
    player_input_raw: str | None,
    selected_action_id: str | None,
    selected_choice_label: str | None,
) -> str:
    player_tokens = tokenize_alignment_text(player_input_raw)
    if not player_tokens:
        return "unknown"

    action_key = str(selected_action_id or "").strip().lower()
    if action_key not in _ACTION_ALIGNMENT_HINTS:
        inferred = infer_action_from_label(selected_choice_label)
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


def build_impact_sources_for_prompt(
    *,
    action_state_delta: dict,
    total_state_delta: dict,
    event_resolution: EventResolution | None,
) -> dict:
    event_effects_raw = {}
    if event_resolution and event_resolution.selected_event_id:
        event_effects_raw = event_resolution.selected_event_effects or {}

    return {
        "action_effects": compact_state_delta_for_prompt(action_state_delta, max_items=3),
        "event_effects": compact_state_delta_for_prompt(event_effects_raw, max_items=3),
        "total_effects": compact_state_delta_for_prompt(total_state_delta, max_items=4),
    }


def build_quest_nudge(
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
    cadence_hit = bool(safe_int(run_step_index, 0) > 0 and safe_int(run_step_index, 0) % _QUEST_NUDGE_CADENCE == 0)
    if not has_recent and not cadence_hit:
        return default_nudge

    mode = "event_driven" if has_recent else "cadence"
    first_active = active_quests[0] if isinstance(active_quests[0], dict) else {}
    first_active_quest_id = str(first_active.get("quest_id") or "").strip()
    stage_hint_source = normalize_hint_source(first_active.get("current_stage_title"))
    mainline_hint = (
        f"your current track still points toward {stage_hint_source.lower()}"
        if stage_hint_source
        else "the week's plan still has a clear next step"
    )
    mainline_hint = clip_hint_words(mainline_hint, max_words=16)

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
        side_source = normalize_hint_source(selected_recent.get("title"))
        if side_source:
            sideline_hint = clip_hint_words(
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


def choose_quest_nudge_text(quest_nudge: dict | None) -> str | None:
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


def compact_runtime_event_for_prompt(event_resolution: EventResolution | None) -> dict | None:
    if not event_resolution or not event_resolution.selected_event_id:
        return None
    return {
        "event_id": clip_prompt_text(event_resolution.selected_event_id, max_len=64),
        "title": clip_prompt_text(event_resolution.selected_event_title, max_len=80),
        "narration_hint": clip_prompt_text(event_resolution.selected_event_narration_hint, max_len=96),
        "effects": compact_state_delta_for_prompt(event_resolution.selected_event_effects or {}, max_items=3),
    }


def compact_run_ending_for_prompt(ending_resolution: EndingResolution | None) -> dict:
    if not ending_resolution or not ending_resolution.run_ended:
        return {"run_ended": False}
    return {
        "run_ended": True,
        "ending_id": clip_prompt_text(ending_resolution.ending_id, max_len=64),
        "ending_outcome": clip_prompt_text(ending_resolution.ending_outcome, max_len=24),
        "ending_title": clip_prompt_text(ending_resolution.ending_title, max_len=96),
        "ending_epilogue": clip_prompt_text(ending_resolution.ending_epilogue, max_len=160),
    }


def build_layer_debug_payload(
    *,
    input_mode_for_prompt: str,
    player_input: str | None,
    resolution: StoryChoiceResolution,
    event_present: bool,
    ending_resolution: EndingResolution,
    state_after: dict,
    state_delta: dict,
    turn_intensity: float,
    recovery_offered: bool,
    dominant_route_streak: int,
    tension_note: str,
    guard_all_blocked_triggered: bool,
    guard_stall_triggered: bool,
) -> dict:
    selected_action_id = (
        str((resolution.final_action_for_state or {}).get("action_id"))
        if (resolution.final_action_for_state or {}).get("action_id") is not None
        else None
    )
    selected_choice_label = (
        str(resolution.selected_choice.get("display_text"))
        if resolution.selected_choice is not None and resolution.selected_choice.get("display_text") is not None
        else None
    )

    return {
        "input_mode": input_mode_for_prompt,
        "player_input": player_input,
        "attempted_choice_id": resolution.attempted_choice_id,
        "executed_choice_id": resolution.executed_choice_id,
        "resolved_choice_id": resolution.resolved_choice_id,
        "selected_action_id": selected_action_id,
        "mapping_confidence": resolution.mapping_confidence,
        "fallback_reason": resolution.fallback_reason_code,
        "mapping_note": resolution.mapping_note,
        "turn_intensity": turn_intensity,
        "recovery_offered": recovery_offered,
        "dominant_route_streak": dominant_route_streak,
        "tension_note": tension_note,
        "state_delta_keypoints": compact_state_delta_for_prompt(state_delta, max_items=6),
        "quest_event_ending_flags": {
            "fallback_used": bool(resolution.using_fallback),
            "event_present": bool(event_present),
            "run_ended": bool(ending_resolution.run_ended),
            "ending_id": ending_resolution.ending_id,
            "ending_outcome": ending_resolution.ending_outcome,
            "step_index": safe_int(((state_after or {}).get("run_state") or {}).get("step_index"), 0),
            "all_blocked_guard_triggered": guard_all_blocked_triggered,
            "stall_guard_triggered": guard_stall_triggered,
            "recovery_offered": recovery_offered,
        },
        "prompt_policy": {
            "causal_policy": "strict_separation",
            "intent_action_alignment": derive_intent_action_alignment(
                player_input_raw=player_input,
                selected_action_id=selected_action_id,
                selected_choice_label=selected_choice_label,
            ),
            "event_present": bool(event_present),
            "all_blocked_guard_triggered": guard_all_blocked_triggered,
            "stall_guard_triggered": guard_stall_triggered,
        },
    }
