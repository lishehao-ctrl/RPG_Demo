from __future__ import annotations

import json
from threading import Barrier
from typing import Any

from rpg_backend.llm.base import LLMJsonObjectResult, LLMProvider


class _BaseFakeProvider(LLMProvider):
    gateway_mode = "unknown"
    route_model = "route-model"
    narration_model = "narration-model"
    timeout_seconds = 20.0
    route_max_retries = 3
    narration_max_retries = 1
    route_temperature = 0.1
    narration_temperature = 0.4

    async def invoke_json_object(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
    ) -> LLMJsonObjectResult:
        del system_prompt, model, temperature, max_retries, timeout_seconds
        payload = json.loads(user_prompt)
        task = payload.get("task")
        if task == "select_route_candidate":
            return LLMJsonObjectResult(payload=self._route_payload(payload), duration_ms=5)
        if task == "render_runtime_narration":
            return LLMJsonObjectResult(payload=self._narration_payload(payload), duration_ms=5)
        raise AssertionError(f"unexpected task: {task}")

    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _narration_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_slots = payload.get("prompt_slots") or {}
        return {"narration_text": f"{prompt_slots['echo']} {prompt_slots['commit']} {prompt_slots['hook']}"}


class DeterministicProvider(_BaseFakeProvider):
    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scene_context = payload["scene_context"]
        fallback = scene_context.get("fallback_key", "m0")
        return {
            "selected_key": fallback,
            "confidence": 0.95,
            "interpreted_intent": (payload.get("player_text") or "").strip() or "help me progress",
        }


class RouteFailureProvider(_BaseFakeProvider):
    async def invoke_json_object(self, **kwargs):  # noqa: ANN003, ANN201
        payload = json.loads(kwargs["user_prompt"])
        if payload.get("task") == "select_route_candidate":
            raise RuntimeError("route failed")
        return await super().invoke_json_object(**kwargs)

    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("unreachable")


class LowConfidenceProvider(_BaseFakeProvider):
    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scene_context = payload["scene_context"]
        fallback = scene_context.get("fallback_key", "m0")
        return {
            "selected_key": fallback,
            "confidence": 0.1,
            "interpreted_intent": payload.get("player_text") or "unclear intent",
        }


class InvalidMoveProvider(_BaseFakeProvider):
    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "selected_key": "m999",
            "confidence": 0.95,
            "interpreted_intent": payload.get("player_text") or "invalid move intent",
        }


class NarrationFailureProvider(_BaseFakeProvider):
    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scene_context = payload["scene_context"]
        fallback = scene_context.get("fallback_key", "m0")
        return {
            "selected_key": fallback,
            "confidence": 0.9,
            "interpreted_intent": payload.get("player_text") or "unclear intent",
        }

    def _narration_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("narration failed")


class AlwaysGlobalHelpProvider(_BaseFakeProvider):
    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        scene_context = payload["scene_context"]
        help_key = next((move["key"] for move in scene_context.get("moves", []) if move.get("is_global") and ("help" in (move.get("label", "").lower()) or "help" in [str(item).lower() for item in move.get("intents", [])])), None)
        return {
            "selected_key": help_key or "m999",
            "confidence": 0.95,
            "interpreted_intent": payload.get("player_text") or "help me progress",
        }


class BarrierDeterministicProvider(_BaseFakeProvider):
    def __init__(self, barrier: Barrier):
        self._barrier = barrier

    def _route_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._barrier.wait(timeout=3)
        scene_context = payload["scene_context"]
        fallback = scene_context.get("fallback_key", "m0")
        return {
            "selected_key": fallback,
            "confidence": 0.95,
            "interpreted_intent": (payload.get("player_text") or "").strip() or "help me progress",
        }
