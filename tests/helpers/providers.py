from __future__ import annotations

from threading import Barrier

from rpg_backend.llm.base import LLMProvider, RouteIntentResult


class DeterministicProvider(LLMProvider):
    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.95,
            interpreted_intent=(text or "").strip() or "help me progress",
        )

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class RouteFailureProvider(LLMProvider):
    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        raise RuntimeError("route failed")

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class LowConfidenceProvider(LLMProvider):
    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.1,
            interpreted_intent=text or "unclear intent",
        )

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class InvalidMoveProvider(LLMProvider):
    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        return RouteIntentResult(
            move_id="move.not.available",
            args={},
            confidence=0.95,
            interpreted_intent=text or "invalid move intent",
        )

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class NarrationFailureProvider(LLMProvider):
    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.9,
            interpreted_intent=text or "unclear intent",
        )

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        raise RuntimeError("narration failed")


class AlwaysGlobalHelpProvider(LLMProvider):
    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        return RouteIntentResult(
            move_id="global.help_me_progress",
            args={},
            confidence=0.95,
            interpreted_intent=text or "help me progress",
        )

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class BarrierDeterministicProvider(LLMProvider):
    def __init__(self, barrier: Barrier):
        self._barrier = barrier

    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        self._barrier.wait(timeout=3)
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.95,
            interpreted_intent=(text or "").strip() or "help me progress",
        )

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"
