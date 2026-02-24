from __future__ import annotations

from typing import Any

from app.db.models import Session as StorySession
from app.modules.narrative.state_engine import apply_action as apply_state_action
from app.modules.narrative.state_engine import normalize_state


def phase_compute_state_transition(
    *,
    sess: StorySession,
    final_action_for_state: dict,
    effects_for_state: dict,
    deps: Any,
) -> tuple[dict, dict, dict]:
    state_before = normalize_state(sess.state_json)
    state_after_base, _ = apply_state_action(state_before, final_action_for_state)
    state_after = deps.apply_choice_effects(state_after_base, effects_for_state)
    state_delta = deps.compute_state_delta(state_before, state_after)
    sess.state_json = state_after
    return state_before, state_after, state_delta
