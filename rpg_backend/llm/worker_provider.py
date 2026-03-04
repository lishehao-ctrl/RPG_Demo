from __future__ import annotations

from typing import Any

from rpg_backend.llm.base import LLMNarrationError, LLMProvider, LLMRouteError, RouteIntentResult
from rpg_backend.llm.worker_client import WorkerClient, WorkerClientError


class WorkerProvider(LLMProvider):
    def __init__(
        self,
        *,
        worker_client: WorkerClient,
        route_model: str,
        narration_model: str,
        timeout_seconds: float,
        route_max_retries: int,
        narration_max_retries: int,
        route_temperature: float,
        narration_temperature: float,
    ) -> None:
        self.worker_client = worker_client
        self.route_model = route_model
        self.narration_model = narration_model
        self.timeout_seconds = timeout_seconds
        self.route_max_retries = max(1, min(route_max_retries, 3))
        self.narration_max_retries = max(1, min(narration_max_retries, 3))
        self.route_temperature = route_temperature
        self.narration_temperature = narration_temperature

    def route_intent(self, scene_context: dict[str, Any], text: str) -> RouteIntentResult:
        try:
            payload = self.worker_client.route_intent(
                scene_context=scene_context,
                text=text,
                model=self.route_model,
                temperature=self.route_temperature,
                max_retries=self.route_max_retries,
                timeout_seconds=self.timeout_seconds,
            )
        except WorkerClientError as exc:
            raise LLMRouteError(f"worker route_intent failed: {exc.error_code}: {exc.message}") from exc

        try:
            routed = RouteIntentResult.model_validate(
                {
                    "move_id": payload.get("move_id"),
                    "args": payload.get("args") or {},
                    "confidence": payload.get("confidence"),
                    "interpreted_intent": payload.get("interpreted_intent"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMRouteError(f"worker route_intent invalid payload: {exc}") from exc

        if not routed.move_id.strip() or not routed.interpreted_intent.strip():
            raise LLMRouteError("worker route_intent invalid payload: blank fields")
        routed.move_id = routed.move_id.strip()
        return routed

    def render_narration(self, slots: dict[str, Any], style_guard: str) -> str:
        try:
            payload = self.worker_client.render_narration(
                slots=slots,
                style_guard=style_guard,
                model=self.narration_model,
                temperature=self.narration_temperature,
                max_retries=self.narration_max_retries,
                timeout_seconds=self.timeout_seconds,
            )
        except WorkerClientError as exc:
            raise LLMNarrationError(f"worker render_narration failed: {exc.error_code}: {exc.message}") from exc

        text = payload.get("narration_text")
        if not isinstance(text, str) or not text.strip():
            raise LLMNarrationError("worker render_narration returned blank text")
        return text.strip()
