"""Storylet firing engine — the missing pipe between author_v3 and the play runtime.

The author pipeline produces a `storylet_pool` of 4-60 scene-fragments, each with
preconditions and effects. Until now the play runtime only used these as background
hints for narration prompts; this module makes them actually *fire* — apply effects
to state, cascade through SecretChain edges, honour cooldowns.

The engine is deliberately stateless: `fire_storylet` mutates the passed-in
`UrbanWorldState` in place. Callers are responsible for snapshotting state before
firing if they need rollback.

Two firing paths:
- Auto-fire from the matcher (turn finalize): runtime picks the highest-scoring
  storylet whose preconditions match and fires it; one storylet per turn cap.
- Player-driven (suggested action): runtime exposes a top match as a 4th choice
  card; if the player picks it, the engine fires with `bypass_preconditions=True`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author_v3.storylet_compiler import Storylet
from rpg_backend.author_v3.tension_weaver import SecretChain
from rpg_backend.play_v2.contracts import CompiledPlayPlan, UrbanWorldState


# How many storylets we'll fire automatically per turn (matcher-driven path).
# Player-driven fires don't count against this — they're additive.
MAX_AUTO_FIRES_PER_TURN = 1

# Field caps mirrored from contracts.py so we don't hit ValidationError on append.
_KNOWN_SECRETS_CAP = 8
_LAST_TURN_REVEALED_CAP = 4
_LAST_TURN_FIRED_CAP = 4


class StoryletFireResult(BaseModel):
    """Diff record of what a single fire changed. Returned for telemetry / tests."""

    model_config = ConfigDict(extra="forbid")

    storylet_id: str
    fired: bool
    skipped_reason: str | None = None
    revealed_secret_ids: list[str] = Field(default_factory=list)
    chained_secret_ids: list[str] = Field(default_factory=list)
    relationship_changes: dict[str, int] = Field(default_factory=dict)  # char_id → affection_delta
    scene_heat_delta: int = 0


# ---------------- preconditions / cooldown ----------------


def is_in_cooldown(storylet: Storylet, state: UrbanWorldState) -> bool:
    last_fired = state.fired_storylet_ids.get(storylet.storylet_id)
    if last_fired is None:
        return False
    if storylet.cooldown_turns <= 0:
        return False
    return (state.turn_index - last_fired) < storylet.cooldown_turns


def preconditions_satisfied(
    storylet: Storylet,
    state: UrbanWorldState,
    plan: CompiledPlayPlan,
) -> bool:
    """Strict gate: ALL preconditions must pass.

    The matcher (storylet_matcher.py) uses fuzzy scoring to decide which storylets
    are *most relevant* — we use that for ranking. But before fire, we double-check
    every condition is hard-met to avoid false positives that would warp state.
    """
    pre = storylet.preconditions

    if pre.required_secrets_known:
        known = set(state.known_secret_ids)
        if not set(pre.required_secrets_known).issubset(known):
            return False

    if pre.min_tension_score > 0.0:
        if _normalized_tension(state) < pre.min_tension_score:
            return False

    if pre.required_segment_roles:
        if _current_segment_role(state, plan) not in pre.required_segment_roles:
            return False

    if pre.required_relationships:
        # Relaxed match: any of the listed character ids must currently be active
        # in state.relationships. This mirrors the matcher's loose semantics.
        active_ids = {cid.lower() for cid in state.relationships.keys() if cid}
        if not active_ids:
            return False
        for entry in pre.required_relationships:
            entry_text = entry.lower()
            if not any(cid in entry_text for cid in active_ids):
                return False

    return True


def _normalized_tension(state: UrbanWorldState) -> float:
    components = (
        state.scene_heat / 6.0,
        state.secret_exposure / 6.0,
        state.witness_pressure / 3.0,
    )
    return max(0.0, min(1.0, sum(components) / max(len(components), 1)))


def _current_segment_role(state: UrbanWorldState, plan: CompiledPlayPlan) -> str:
    for segment in plan.segments:
        if segment.segment_id == state.segment_id:
            return segment.segment_role
    return ""


# ---------------- fire ----------------


def fire_storylet(
    storylet: Storylet,
    state: UrbanWorldState,
    plan: CompiledPlayPlan,
    *,
    bypass_preconditions: bool = False,
) -> StoryletFireResult:
    """Apply a storylet's effects to state. Mutates state in place.

    `bypass_preconditions=True` is for player-driven fires (the player picked the
    card) — we trust the runtime that the player wanted this and skip the gate.
    Cooldown is *always* enforced to avoid same-turn double-fires.
    """
    if is_in_cooldown(storylet, state):
        return StoryletFireResult(
            storylet_id=storylet.storylet_id,
            fired=False,
            skipped_reason="cooldown",
        )

    if not bypass_preconditions and not preconditions_satisfied(storylet, state, plan):
        return StoryletFireResult(
            storylet_id=storylet.storylet_id,
            fired=False,
            skipped_reason="preconditions_unmet",
        )

    effects = storylet.effects
    result = StoryletFireResult(storylet_id=storylet.storylet_id, fired=True)

    # 1. Reveal secrets.
    for secret_id in effects.secrets_revealed:
        if not secret_id or secret_id in state.known_secret_ids:
            continue
        if len(state.known_secret_ids) >= _KNOWN_SECRETS_CAP:
            break
        state.known_secret_ids.append(secret_id)
        result.revealed_secret_ids.append(secret_id)

    # 2. Cascade SecretChain unlocks.
    if result.revealed_secret_ids and plan.secret_chains:
        chained = _cascade_chains(plan.secret_chains, result.revealed_secret_ids)
        for sid in chained:
            if sid in state.known_secret_ids:
                continue
            if len(state.known_secret_ids) >= _KNOWN_SECRETS_CAP:
                break
            state.known_secret_ids.append(sid)
            result.chained_secret_ids.append(sid)

    # 3. Relationship shifts (float -1..1 quantized to int -3..3 affection delta).
    for char_id, shift in effects.relationship_shifts.items():
        rel = state.relationships.get(char_id)
        if rel is None:
            continue
        affection_delta = max(-3, min(3, int(round(shift * 3))))
        if affection_delta == 0:
            continue
        new_affection = max(-3, min(6, rel.affection + affection_delta))
        applied_delta = new_affection - rel.affection
        rel.affection = new_affection
        result.relationship_changes[char_id] = applied_delta

    # 4. Tension delta → scene_heat. Positive = ramp up, negative = cool down.
    scene_heat_delta = int(round(effects.tension_delta * 2))
    if scene_heat_delta != 0:
        new_heat = max(0, min(6, state.scene_heat + scene_heat_delta))
        result.scene_heat_delta = new_heat - state.scene_heat
        state.scene_heat = new_heat

    # 5. Cooldown bookkeeping + per-turn surface.
    state.fired_storylet_ids[storylet.storylet_id] = state.turn_index
    if (
        storylet.storylet_id not in state.last_turn_fired_storylet_ids
        and len(state.last_turn_fired_storylet_ids) < _LAST_TURN_FIRED_CAP
    ):
        state.last_turn_fired_storylet_ids.append(storylet.storylet_id)

    # 6. Mirror new reveals into last_turn_revealed_secret_ids so the narration
    # surface picks them up exactly like a normal reveal would.
    for sid in [*result.revealed_secret_ids, *result.chained_secret_ids]:
        if sid in state.last_turn_revealed_secret_ids:
            continue
        if len(state.last_turn_revealed_secret_ids) >= _LAST_TURN_REVEALED_CAP:
            break
        state.last_turn_revealed_secret_ids.append(sid)

    return result


def _cascade_chains(chain_dicts: list[dict[str, Any]], trigger_secret_ids: list[str]) -> list[str]:
    """BFS through SecretChain edges. Trigger A → unlocks B → may itself trigger C..."""
    chains_by_trigger: dict[str, list[str]] = {}
    for chain_dict in chain_dicts:
        try:
            chain = SecretChain.model_validate(chain_dict)
        except Exception:  # noqa: BLE001 — bad data shouldn't crash the turn
            continue
        chains_by_trigger.setdefault(chain.trigger_secret_id, []).append(chain.unlocks_secret_id)

    unlocked: list[str] = []
    queue = list(trigger_secret_ids)
    seen = set(queue)
    while queue:
        current = queue.pop(0)
        for next_id in chains_by_trigger.get(current, []):
            if next_id in seen:
                continue
            seen.add(next_id)
            unlocked.append(next_id)
            queue.append(next_id)
    return unlocked


# ---------------- pool helpers ----------------


def deserialize_storylet(raw: dict[str, Any]) -> Storylet | None:
    """Best-effort hydrate; returns None for malformed records."""
    try:
        return Storylet.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def storylet_pool_iter(plan: CompiledPlayPlan):
    """Iterate hydrated storylets from plan.storylet_pool, skipping malformed ones."""
    if not plan.storylet_pool:
        return
    for raw in plan.storylet_pool:
        storylet = deserialize_storylet(raw)
        if storylet is not None:
            yield storylet


def reset_turn_storylet_state(state: UrbanWorldState) -> None:
    """Clear per-turn buffers. Call at the start of every new turn."""
    state.last_turn_fired_storylet_ids = []
