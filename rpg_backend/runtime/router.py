from __future__ import annotations

import re
from typing import Any

from rpg_backend.config.settings import get_settings
from rpg_backend.domain.constants import GLOBAL_CLARIFY_MOVE_ID, GLOBAL_HELP_ME_PROGRESS_MOVE_ID
from rpg_backend.domain.pack_schema import Beat, Move, Scene
from rpg_backend.llm.base import LLMProvider
from rpg_backend.runtime.errors import RuntimeRouteError

_HELP_INTENT_RE = re.compile(
    r"\b(help|stuck|next step|what now|guide me|dont know|don't know|how do i proceed)\b",
    flags=re.IGNORECASE,
)


def _is_explicit_help_intent(text: str) -> bool:
    return bool(_HELP_INTENT_RE.search(text or ""))


def route_player_action(
    provider: LLMProvider,
    scene: Scene,
    move_map: dict[str, Move],
    action_input: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    beat_progress: dict[str, int] | None = None,
    beat: Beat | None = None,
    beat_index: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    threshold = settings.routing_confidence_threshold

    available = list(dict.fromkeys(scene.enabled_moves + scene.always_available_moves))
    fallback_move = (
        GLOBAL_HELP_ME_PROGRESS_MOVE_ID if GLOBAL_HELP_ME_PROGRESS_MOVE_ID in available else GLOBAL_CLARIFY_MOVE_ID
    )
    if fallback_move not in available and available:
        fallback_move = available[0]

    if action_input.get("type") == "button":
        requested = action_input.get("move_id")
        if requested in available:
            return {
                "interpreted_intent": f"button:{requested}",
                "move_id": requested,
                "confidence": 1.0,
                "route_source": "button",
            }
        return {
            "interpreted_intent": f"button:{requested or 'invalid'}",
            "move_id": fallback_move,
            "confidence": 0.25,
            "route_source": "button_fallback",
        }

    text = action_input.get("text") or ""
    allow_global_help = _is_explicit_help_intent(text)
    llm_available = [
        move_id
        for move_id in available
        if allow_global_help or move_id != GLOBAL_HELP_ME_PROGRESS_MOVE_ID
    ]
    if not llm_available:
        llm_available = list(available)

    state_values = ((state or {}).get("values") or {}) if isinstance(state, dict) else {}
    events = ((state or {}).get("events") or []) if isinstance(state, dict) else []
    if not isinstance(events, list):
        events = []
    beat_progress_map = beat_progress or {}
    scene_snapshot = {
        "scene_id": scene.id,
        "beat_id": scene.beat_id,
        "beat_index": beat_index,
        "present_npcs": list(scene.present_npcs),
        "scene_seed": scene.scene_seed,
        "beat_title": beat.title if beat is not None else "",
        "beat_required_events": list(beat.required_events) if beat is not None else [],
        "beat_step_budget": beat.step_budget if beat is not None else None,
        "beat_progress_value": int(beat_progress_map.get(scene.beat_id, 0)),
    }
    state_snapshot = {
        "last_move": state_values.get("last_move"),
        "pressure_tracks": {
            "public_trust": int(state_values.get("public_trust", 0)),
            "resource_stress": int(state_values.get("resource_stress", 0)),
            "coordination_noise": int(state_values.get("coordination_noise", 0)),
        },
        "time_spent": int(state_values.get("time_spent", 0)),
        "runtime_turn": int(state_values.get("runtime_turn", 0)),
        "cost_total": int(state_values.get("cost_total", 0)),
        "recent_events_tail": [str(event) for event in events[-8:]],
    }

    scene_context = {
        "moves": [
            {
                "id": move_id,
                "label": move_map[move_id].label,
                "intents": move_map[move_id].intents,
                "synonyms": move_map[move_id].synonyms,
                "is_global": move_id.startswith("global."),
            }
            for move_id in llm_available
            if move_id in move_map
        ],
        "fallback_move": GLOBAL_CLARIFY_MOVE_ID if not allow_global_help else fallback_move,
        "scene_seed": scene.scene_seed,
        "allow_global_help": allow_global_help,
        "scene_snapshot": scene_snapshot,
        "state_snapshot": state_snapshot,
    }
    provider_name = "openai"

    try:
        routed = provider.route_intent(scene_context, text)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeRouteError(
            error_code="llm_route_failed",
            message=f"route_intent failed after provider retries: {exc}",
            provider=provider_name,
        ) from exc

    chosen_move = routed.move_id
    confidence = float(routed.confidence)
    route_source = "llm"
    if chosen_move not in llm_available:
        raise RuntimeRouteError(
            error_code="llm_route_invalid_move",
            message=f"route_intent returned unavailable move_id: {chosen_move}",
            provider=provider_name,
        )
    elif confidence < threshold:
        raise RuntimeRouteError(
            error_code="llm_route_low_confidence",
            message=f"route_intent confidence {confidence:.4f} below threshold {threshold:.4f}",
            provider=provider_name,
        )

    return {
        "interpreted_intent": routed.interpreted_intent,
        "move_id": chosen_move,
        "confidence": confidence,
        "route_source": route_source,
    }
