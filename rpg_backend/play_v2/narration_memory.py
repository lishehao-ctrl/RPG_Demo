from __future__ import annotations

from typing import Any

from rpg_backend.play_v2.contracts import (
    NarrationEventEntry,
    NarrationSegmentSummary,
    UrbanWorldState,
)
from rpg_backend.play_v2.narration_variants import (
    canonicalize_phrase,
    phrase_fingerprint,
    pattern_fingerprint,
)


_EVENT_LOG_MAX = 16
_SUMMARY_MAX = 4
_RELATIONSHIP_TRAJECTORY_WINDOW = 3
_ACTIVE_HOOK_SUMMARY_MAX = 5
_REVEALED_SECRET_SUMMARY_MAX = 8
_PRESSURE_FIELDS = ("pressure_load", "humiliation_risk", "betrayal_readiness")
_RELATIONSHIP_TRAJECTORY_FIELDS = frozenset({"affection", "trust", "tension", "suspicion"})


def _get_attr_or_key(obj: object, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _build_relationship_trajectory(state: UrbanWorldState) -> dict[str, dict[str, str]]:
    try:
        event_log = list(getattr(state, "narration_event_log", []) or [])
        if not event_log:
            return {}
        aggregated: dict[str, dict[str, float]] = {}
        for entry in event_log[-_RELATIONSHIP_TRAJECTORY_WINDOW:]:
            relationship_deltas = _get_attr_or_key(entry, "relationship_deltas", {}) or {}
            if not isinstance(relationship_deltas, dict):
                continue
            for character_id, raw_deltas in relationship_deltas.items():
                if not isinstance(raw_deltas, dict):
                    continue
                npc_totals = aggregated.setdefault(str(character_id), {})
                for dimension, raw_value in raw_deltas.items():
                    if dimension not in _RELATIONSHIP_TRAJECTORY_FIELDS:
                        continue
                    npc_totals[dimension] = npc_totals.get(dimension, 0.0) + float(raw_value)
        trajectory: dict[str, dict[str, str]] = {}
        for character_id, dimension_totals in aggregated.items():
            dimension_states: dict[str, str] = {}
            for dimension, total in dimension_totals.items():
                if total > 0.5:
                    dimension_states[dimension] = "rising"
                elif total < -0.5:
                    dimension_states[dimension] = "falling"
                else:
                    dimension_states[dimension] = "stable"
            if dimension_states:
                trajectory[character_id] = dimension_states
        return trajectory
    except Exception:
        return {}


def _build_active_hook_summary(state: UrbanWorldState) -> list[dict[str, object]]:
    try:
        hook_states = getattr(state, "hook_states", None) or {}
        if not isinstance(hook_states, dict) or not hook_states:
            return []
        allowed_statuses = {"suspected", "active", "leveraged"}
        summary = [
            {
                "hook_id": hook.hook_id,
                "holder_id": hook.holder_id,
                "target_id": hook.target_id,
                "leverage_type": hook.leverage_type,
                "status": hook.status,
                "leverage_value": round(float(hook.leverage_value), 2),
            }
            for hook in hook_states.values()
            if getattr(hook, "status", "") in allowed_statuses
        ]
        summary.sort(key=lambda item: float(item["leverage_value"]), reverse=True)
        return summary[:_ACTIVE_HOOK_SUMMARY_MAX]
    except Exception:
        return []


def _build_revealed_secret_summary(
    state: UrbanWorldState,
    *,
    plan: object | None = None,
) -> list[dict[str, object | None]]:
    try:
        revealed_secret_ids = list(getattr(state, "last_turn_revealed_secret_ids", []) or [])
        if not revealed_secret_ids:
            return []
        secret_lookup: dict[str, object] = {}
        organic_secrets = _get_attr_or_key(plan, "organic_secrets", None) if plan is not None else None
        if organic_secrets:
            for secret in organic_secrets:
                secret_id = str(_get_attr_or_key(secret, "secret_id", "") or "").strip()
                if secret_id:
                    secret_lookup[secret_id] = secret
        summary: list[dict[str, object | None]] = []
        for secret_id in revealed_secret_ids[:_REVEALED_SECRET_SUMMARY_MAX]:
            secret = secret_lookup.get(secret_id)
            title = _get_attr_or_key(secret, "title", None) if secret is not None else None
            description = _get_attr_or_key(secret, "description", None) if secret is not None else None
            summary.append(
                {
                    "secret_id": secret_id,
                    "title": str(title) if title is not None else None,
                    "description_excerpt": str(description)[:60] if description is not None else None,
                }
            )
        return summary
    except Exception:
        return []


def _build_npc_pressure_snapshot(
    state: UrbanWorldState,
    *,
    current_turn_npc_ids: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    try:
        npc_mind_states = getattr(state, "npc_mind_states", None) or {}
        if not isinstance(npc_mind_states, dict) or not npc_mind_states or current_turn_npc_ids is None:
            return {}
        snapshot: dict[str, dict[str, float]] = {}
        for character_id in current_turn_npc_ids:
            mind = npc_mind_states.get(character_id)
            if mind is None:
                continue
            metrics = {
                field_name: round(float(_get_attr_or_key(mind, field_name, 0.0)), 1)
                for field_name in _PRESSURE_FIELDS
                if _get_attr_or_key(mind, field_name, None) is not None
            }
            if metrics:
                snapshot[str(character_id)] = metrics
        return snapshot
    except Exception:
        return {}


def append_narration_event(
    state: UrbanWorldState,
    *,
    turn_index: int,
    narration: str,
    move_family: str = "",
    target_id: str = "",
) -> None:
    fp = phrase_fingerprint(narration)
    phrase = canonicalize_phrase(narration)[:320]
    pfp = pattern_fingerprint(narration)
    if not fp or not phrase:
        return
    entry = NarrationEventEntry(
        turn_index=turn_index,
        fingerprint=fp,
        phrase=phrase,
        pattern_fingerprint=pfp,
        move_family=str(move_family)[:30],
        target_id=str(target_id or "")[:120],
    )
    log = [e for e in state.narration_event_log if e.fingerprint != fp]
    log.append(entry)
    state.narration_event_log = log[-_EVENT_LOG_MAX:]


def consolidate_segment_memory(
    state: UrbanWorldState,
    *,
    segment_id: str,
    segment_role: str,
) -> None:
    event_log = list(state.narration_event_log)
    if not event_log:
        return
    turn_indices = [e.turn_index for e in event_log]
    turn_start = min(turn_indices)
    turn_end = max(turn_indices)
    key_events: list[str] = []
    seen_patterns: set[str] = set()
    for entry in event_log:
        if entry.pattern_fingerprint and entry.pattern_fingerprint not in seen_patterns:
            label = entry.phrase[:80]
            if entry.move_family:
                label = f"[{entry.move_family}] {label}"
            key_events.append(label)
            seen_patterns.add(entry.pattern_fingerprint)
        if len(key_events) >= 6:
            break
    summary_text = "；".join(ke[:90] for ke in key_events[:4])[:600]
    summary = NarrationSegmentSummary(
        segment_id=str(segment_id)[:120],
        segment_role=str(segment_role)[:30],
        summary_text=summary_text,
        key_events=key_events[:6],
        turn_range_start=turn_start,
        turn_range_end=turn_end,
        entry_count=len(event_log),
    )
    summaries = list(state.narration_segment_summaries)
    summaries.append(summary)
    state.narration_segment_summaries = summaries[-_SUMMARY_MAX:]
    state.narration_event_log = []


def build_narration_memory_context(
    state: UrbanWorldState,
    plan: object | None = None,
    current_turn_npc_ids: list[str] | None = None,
) -> dict:
    event_log = list(getattr(state, "narration_event_log", []) or [])
    summaries = list(getattr(state, "narration_segment_summaries", []) or [])
    event_fingerprints = {fp for entry in event_log if (fp := _get_attr_or_key(entry, "fingerprint", ""))}
    event_pattern_fingerprints = {
        pfp for entry in event_log if (pfp := _get_attr_or_key(entry, "pattern_fingerprint", ""))
    }
    event_phrases = [phrase for entry in event_log if (phrase := _get_attr_or_key(entry, "phrase", ""))]
    summary_texts = [summary_text for summary in summaries if (summary_text := _get_attr_or_key(summary, "summary_text", ""))]
    summary_key_events = []
    for summary in summaries:
        summary_key_events.extend(list(_get_attr_or_key(summary, "key_events", []) or []))
    return {
        "event_fingerprints": event_fingerprints,
        "event_pattern_fingerprints": event_pattern_fingerprints,
        "event_phrases": event_phrases,
        "summary_texts": summary_texts[-3:],
        "summary_key_events": summary_key_events[-12:],
        "relationship_trajectory": _build_relationship_trajectory(state),
        "active_hook_summary": _build_active_hook_summary(state),
        "revealed_secret_summary": _build_revealed_secret_summary(state, plan=plan),
        "npc_pressure_snapshot": _build_npc_pressure_snapshot(
            state,
            current_turn_npc_ids=current_turn_npc_ids,
        ),
    }
