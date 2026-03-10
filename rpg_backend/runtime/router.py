from __future__ import annotations

import re
import time
from typing import Any

from rpg_backend.config.settings import get_settings
from rpg_backend.domain.constants import GLOBAL_CLARIFY_MOVE_ID, GLOBAL_HELP_ME_PROGRESS_MOVE_ID
from rpg_backend.domain.pack_schema import Beat, Move, Scene
from rpg_backend.llm.base import LLMProvider
from rpg_backend.runtime.errors import RuntimeRouteError
from rpg_backend.runtime_chains import RouteIntentChain

_HELP_INTENT_RE = re.compile(
    r"\b(help|stuck|next step|what now|guide me|dont know|don't know|how do i proceed)\b",
    flags=re.IGNORECASE,
)


def _is_explicit_help_intent(text: str) -> bool:
    return bool(_HELP_INTENT_RE.search(text or ""))


def _route_candidates(*, llm_available: list[str], move_map: dict[str, Move]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, move_id in enumerate(llm_available):
        if move_id not in move_map:
            continue
        move = move_map[move_id]
        candidates.append(
            {
                "key": f"m{index}",
                "move_id": move_id,
                "label": move.label,
                "intents": list(move.intents),
                "synonyms": list(move.synonyms),
                "is_global": move_id.startswith("global."),
            }
        )
    return candidates


async def route_player_action(
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
                "key": item["key"],
                "id": move_id,
                "label": move_map[move_id].label,
                "intents": move_map[move_id].intents,
                "synonyms": move_map[move_id].synonyms,
                "is_global": move_id.startswith("global."),
            }
            for item in _route_candidates(llm_available=llm_available, move_map=move_map)
            for move_id in [item["move_id"]]
        ],
        "fallback_move": GLOBAL_CLARIFY_MOVE_ID if not allow_global_help else fallback_move,
        "scene_seed": scene.scene_seed,
        "allow_global_help": allow_global_help,
        "scene_snapshot": scene_snapshot,
        "state_snapshot": state_snapshot,
    }
    provider_name = "openai"
    gateway_mode = str(getattr(provider, "gateway_mode", "unknown") or "unknown").strip().lower()
    route_started_at = time.perf_counter()
    route_candidates = _route_candidates(llm_available=llm_available, move_map=move_map)
    route_key_map = {item["key"]: item["move_id"] for item in route_candidates}

    try:
        routed, route_duration_ms, gateway_mode = await RouteIntentChain(provider=provider).choose(
            scene_context=scene_context,
            route_candidates=route_candidates,
            text=text,
        )
    except Exception as exc:  # noqa: BLE001
        route_duration_ms = int((time.perf_counter() - route_started_at) * 1000)
        raise RuntimeRouteError(
            error_code="llm_route_failed",
            message=f"route chain failed after provider retries: {exc}",
            provider=provider_name,
            provider_error_code=getattr(exc, "provider_error_code", None),
            llm_duration_ms=route_duration_ms,
            gateway_mode=str(getattr(exc, "gateway_mode", gateway_mode) or gateway_mode),
        ) from exc

    route_duration_ms = int(route_duration_ms or ((time.perf_counter() - route_started_at) * 1000))
    chosen_move = route_key_map.get(routed.selected_key)
    confidence = float(routed.confidence)
    route_source = "llm"
    if chosen_move not in llm_available:
        raise RuntimeRouteError(
            error_code="llm_route_invalid_move",
            message=f"route chain returned unavailable selected_key: {routed.selected_key}",
            provider=provider_name,
            llm_duration_ms=route_duration_ms,
            gateway_mode=gateway_mode,
        )
    elif confidence < threshold:
        raise RuntimeRouteError(
            error_code="llm_route_low_confidence",
            message=f"route chain confidence {confidence:.4f} below threshold {threshold:.4f}",
            provider=provider_name,
            llm_duration_ms=route_duration_ms,
            gateway_mode=gateway_mode,
        )

    return {
        "interpreted_intent": routed.interpreted_intent,
        "move_id": chosen_move,
        "confidence": confidence,
        "route_source": route_source,
        "llm_duration_ms": route_duration_ms,
        "llm_gateway_mode": gateway_mode,
    }
