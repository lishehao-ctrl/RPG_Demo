from __future__ import annotations

from typing import Any

from rpg_backend.play_v2.contracts import SemanticEffect, UrbanWorldState
from rpg_backend.play_v2.hook_engine import HookContext

Delta = float | int

_HOOK_WEIGHT_FACTORS: dict[str, dict[str, float]] = {
    "betrayal": {"no_hook": 0.8, "active": 1.4, "leveraged": 1.8},
    "secret_reveal": {"no_hook": 1.0, "active": 1.3, "leveraged": 1.6},
    "public_exposure": {"no_hook": 1.0, "active": 1.3, "leveraged": 1.5},
    "confrontation": {"no_hook": 0.9, "active": 1.3, "leveraged": 1.5},
    "confession": {"no_hook": 1.0, "active": 1.2, "leveraged": 1.3},
    "jealousy_provocation": {"no_hook": 0.9, "active": 1.3, "leveraged": 1.4},
    "alliance_change": {"no_hook": 1.0, "active": 1.2, "leveraged": 1.3},
    "protection": {"no_hook": 1.0, "active": 1.1, "leveraged": 1.1},
    "trust_action": {"no_hook": 1.0, "active": 1.0, "leveraged": 0.9},
    "emotional_shift": {"no_hook": 1.0, "active": 1.1, "leveraged": 1.1},
}
_HOOK_HOLDER_BONUS_EFFECT_TYPES = {"confrontation", "betrayal"}
_HOOK_SECRET_PRIORITY: dict[str, int] = {
    "suspected": 0,
    "dormant": 1,
    "active": 2,
    "leveraged": 3,
    "detonated": 4,
}


def resolve_semantic_effects(
    plan: Any,
    state: UrbanWorldState,
    effects: list[SemanticEffect],
    *,
    hook_context: HookContext | None = None,
    move_family: str | None = None,
) -> dict[str, Any]:
    global_deltas: dict[str, Delta] = {}
    relationship_deltas: dict[str, dict[str, Delta]] = {}
    secret_ids_to_add: list[str] = []
    tags: list[str] = []
    hooks_enabled = bool(getattr(plan, "hooks", None) or [])

    segment = _current_segment(plan, state)
    allocated_secrets = set(segment.allocated_secret_ids) if segment else set()

    for effect in effects[:6]:
        _resolve_one(
            effect=effect,
            state=state,
            allocated_secrets=allocated_secrets,
            global_deltas=global_deltas,
            relationship_deltas=relationship_deltas,
            secret_ids_to_add=secret_ids_to_add,
            tags=tags,
            hook_context=hook_context,
            hooks_enabled=hooks_enabled,
            move_family=move_family,
        )

    return {
        "global_deltas": global_deltas,
        "relationship_deltas": relationship_deltas,
        "known_secret_ids_to_add": secret_ids_to_add[:4],
        "tags": tags[:8],
    }


def _current_segment(plan: Any, state: UrbanWorldState) -> Any:
    segments = getattr(plan, "segments", [])
    idx = min(int(state.segment_index), len(segments) - 1) if segments else 0
    return segments[idx] if segments else None


def _effect_multiplier(effect_type: str, hook_context: HookContext | None) -> float | None:
    if hook_context is None:
        return None
    factors = _HOOK_WEIGHT_FACTORS.get(effect_type)
    if factors is None:
        return None
    if hook_context.target_has_leveraged_hook:
        multiplier = factors["leveraged"]
    elif hook_context.target_has_active_hook:
        multiplier = factors["active"]
    else:
        multiplier = factors["no_hook"]
    if hook_context.actor_is_hook_holder and effect_type in _HOOK_HOLDER_BONUS_EFFECT_TYPES:
        multiplier *= 1.2
    return min(multiplier, 2.0)


def _weighted_delta(
    effect_type: str,
    baseline_delta: int,
    *,
    hook_context: HookContext | None,
    relationship_delta: bool = False,
) -> Delta:
    multiplier = _effect_multiplier(effect_type, hook_context)
    if multiplier is None:
        return baseline_delta
    weighted = round((baseline_delta * multiplier) / 0.5) * 0.5
    if relationship_delta:
        weighted = max(-3.0, min(6.0, weighted))
    if abs(weighted) < 1e-9:
        return 0.0
    return weighted


def _acc(d: dict[str, Delta], key: str, delta: Delta) -> None:
    d[key] = d.get(key, 0) + delta


def _rel_acc(rd: dict[str, dict[str, Delta]], char_id: str, key: str, delta: Delta) -> None:
    if not char_id:
        return
    if char_id not in rd:
        rd[char_id] = {}
    rd[char_id][key] = rd[char_id].get(key, 0) + delta


def _hook_secret_candidates(
    state: UrbanWorldState,
    *,
    target_id: str,
    prefer_holder: bool,
) -> list[tuple[str, str]]:
    if not target_id:
        return []
    hook_states = getattr(state, "hook_states", None) or {}
    if not hook_states:
        return []
    primary = "holder_id" if prefer_holder else "target_id"
    secondary = "target_id" if prefer_holder else "holder_id"
    matched_hooks = [
        hook
        for hook in hook_states.values()
        if str(getattr(hook, primary, "") or "").strip() == target_id
        and str(getattr(hook, "source_secret_id", "") or "").strip()
    ]
    fallback_hooks = [
        hook
        for hook in hook_states.values()
        if str(getattr(hook, secondary, "") or "").strip() == target_id
        and str(getattr(hook, "source_secret_id", "") or "").strip()
    ]
    candidate_hooks = matched_hooks or fallback_hooks
    ordered_hooks = sorted(
        candidate_hooks,
        key=lambda hook: (
            _HOOK_SECRET_PRIORITY.get(str(getattr(hook, "status", "dormant") or "dormant"), 99),
            -float(getattr(hook, "leverage_value", 0.0) or 0.0),
            str(getattr(hook, "hook_id", "") or ""),
        ),
    )
    return [
        (
            str(getattr(hook, "source_secret_id", "") or "").strip(),
            str(getattr(hook, "status", "dormant") or "dormant").strip() or "dormant",
        )
        for hook in ordered_hooks
    ]


def _resolve_one(
    *,
    effect: SemanticEffect,
    state: UrbanWorldState,
    allocated_secrets: set[str],
    global_deltas: dict[str, Delta],
    relationship_deltas: dict[str, dict[str, Delta]],
    secret_ids_to_add: list[str],
    tags: list[str],
    hook_context: HookContext | None,
    hooks_enabled: bool,
    move_family: str | None,
) -> None:
    et = effect.effect_type
    tid = effect.target_id or ""

    if et == "secret_reveal":
        _acc(global_deltas, "secret_exposure", _weighted_delta(et, 2, hook_context=hook_context))
        _acc(global_deltas, "scene_heat", _weighted_delta(et, 1, hook_context=hook_context))
        hook_secret_candidates = _hook_secret_candidates(
            state,
            target_id=tid,
            prefer_holder=True,
        ) if hooks_enabled else []
        candidate_secret_id = ""
        candidate_hook_status = ""
        if hook_secret_candidates:
            candidate_secret_id, candidate_hook_status = hook_secret_candidates[0]
        elif allocated_secrets:
            candidate_secret_id = next(iter(allocated_secrets))
        if candidate_secret_id and move_family in {None, "probe_secret"}:
            revealed_secret_ids = list(getattr(state, "last_turn_revealed_secret_ids", []) or [])
            if candidate_secret_id not in revealed_secret_ids:
                state.last_turn_revealed_secret_ids = [*revealed_secret_ids, candidate_secret_id][:4]
            if (
                candidate_secret_id not in (state.known_secret_ids or [])
                and candidate_hook_status in {"", "suspected", "active", "leveraged", "detonated"}
            ):
                secret_ids_to_add.append(candidate_secret_id)
                state.known_secret_ids = [*list(state.known_secret_ids or []), candidate_secret_id][:8]
        tags.append("semantic:secret_reveal")

    elif et == "public_exposure":
        _acc(global_deltas, "secret_exposure", _weighted_delta(et, 2, hook_context=hook_context))
        _acc(global_deltas, "scene_heat", _weighted_delta(et, 2, hook_context=hook_context))
        _acc(global_deltas, "public_image", _weighted_delta(et, -1, hook_context=hook_context))
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "tension", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "suspicion", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
        tags.append("semantic:public_exposure")

    elif et == "trust_action":
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "trust", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "affection", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
        tags.append("semantic:trust_action")

    elif et == "betrayal":
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "trust", _weighted_delta(et, -3, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "suspicion", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
        _acc(global_deltas, "scene_heat", _weighted_delta(et, 1, hook_context=hook_context))
        tags.append("semantic:betrayal")

    elif et == "emotional_shift":
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "affection", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "tension", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
        tags.append("semantic:emotional_shift")

    elif et == "alliance_change":
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "trust", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "dependency", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
        _acc(global_deltas, "route_lock", _weighted_delta(et, 1, hook_context=hook_context))
        tags.append("semantic:alliance_change")

    elif et == "confession":
        _acc(global_deltas, "secret_exposure", _weighted_delta(et, 1, hook_context=hook_context))
        _acc(global_deltas, "route_lock", _weighted_delta(et, 1, hook_context=hook_context))
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "trust", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "affection", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "dependency", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
        for sid in allocated_secrets:
            if sid not in (state.known_secret_ids or []):
                secret_ids_to_add.append(sid)
                break
        tags.append("semantic:confession")

    elif et == "confrontation":
        _acc(global_deltas, "scene_heat", _weighted_delta(et, 2, hook_context=hook_context))
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "tension", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "suspicion", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
        tags.append("semantic:confrontation")

    elif et == "protection":
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "trust", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "affection", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "tension", _weighted_delta(et, -1, hook_context=hook_context, relationship_delta=True))
        tags.append("semantic:protection")

    elif et == "jealousy_provocation":
        if tid and tid in state.relationships:
            _rel_acc(relationship_deltas, tid, "tension", _weighted_delta(et, 2, hook_context=hook_context, relationship_delta=True))
            _rel_acc(relationship_deltas, tid, "suspicion", _weighted_delta(et, 1, hook_context=hook_context, relationship_delta=True))
        _acc(global_deltas, "scene_heat", _weighted_delta(et, 1, hook_context=hook_context))
        tags.append("semantic:jealousy_provocation")
