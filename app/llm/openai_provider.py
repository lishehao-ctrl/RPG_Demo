from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from app.llm.base import LLMNarrationError, LLMProvider, LLMRouteError, RouteIntentResult


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider using Chat Completions with JSON mode."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str | None = None,
        route_model: str | None = None,
        narration_model: str | None = None,
        timeout_seconds: float = 20.0,
        route_max_retries: int = 3,
        narration_max_retries: int = 1,
        route_temperature: float = 0.1,
        narration_temperature: float = 0.4,
    ) -> None:
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()
        default_model = (model or "").strip()
        route = (route_model or "").strip()
        narration = (narration_model or "").strip()
        self.route_model = route or narration or default_model
        self.narration_model = narration or route or default_model
        self.timeout_seconds = timeout_seconds
        self.route_max_retries = max(1, min(route_max_retries, 3))
        self.narration_max_retries = max(1, min(narration_max_retries, 3))
        self.route_temperature = route_temperature
        self.narration_temperature = narration_temperature
        self.chat_completions_url = self._normalize_chat_completions_url(self.base_url)

    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return True

    @property
    def runtime_failfast_on_narration_error(self) -> bool:
        return True

    @staticmethod
    def _normalize_chat_completions_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        if normalized.endswith("/responses"):
            return f"{normalized[:-len('/responses')]}/chat/completions"
        if normalized.endswith("/v1"):
            return f"{normalized}/chat/completions"
        return f"{normalized}/v1/chat/completions"

    def _call_chat_completions(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> dict[str, Any]:
        body = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.chat_completions_url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _extract_chat_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("chat completions payload missing choices")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ValueError("chat completions payload missing message")

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content

        if isinstance(content, list):
            fragments: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    fragments.append(part["text"])
            combined = "".join(fragments).strip()
            if combined:
                return combined

        raise ValueError("chat completions payload missing message content")

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("response content is not a JSON object")
        return parsed

    @staticmethod
    def _is_retriable_error(exc: Exception) -> bool:
        if isinstance(exc, (json.JSONDecodeError, ValidationError, ValueError)):
            return True
        if isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status in {408, 409, 425, 429, 500, 502, 503, 504}
        return False

    @staticmethod
    def _retry_delay_seconds(attempt: int, exc: Exception) -> float:
        if isinstance(exc, (json.JSONDecodeError, ValidationError, ValueError)):
            return 0.0
        # attempt is 1-based
        retry_schedule = (0.25, 0.8, 1.5)
        index = min(max(attempt - 1, 0), len(retry_schedule) - 1)
        return retry_schedule[index]

    def route_intent(self, scene_context: dict[str, Any], text: str) -> RouteIntentResult:
        system_prompt = (
            "You route player text to a move. "
            "Return JSON only with keys: move_id (string), args (object), confidence (0..1), interpreted_intent (string)."
        )
        user_prompt = json.dumps(
            {
                "task": "route_intent",
                "input_text": text or "",
                "fallback_move": scene_context.get("fallback_move"),
                "moves": scene_context.get("moves", []),
                "scene_seed": scene_context.get("scene_seed", ""),
            },
            ensure_ascii=False,
        )
        last_error: Exception | None = None

        for attempt in range(1, self.route_max_retries + 1):
            try:
                raw_payload = self._call_chat_completions(
                    model=self.route_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=self.route_temperature,
                )
                content = self._extract_chat_content(raw_payload)
                parsed = self._parse_json_object(content)
                routed = RouteIntentResult.model_validate(parsed)
                if not routed.move_id.strip():
                    raise ValueError("move_id is blank")
                if not routed.interpreted_intent.strip():
                    raise ValueError("interpreted_intent is blank")
                routed.move_id = routed.move_id.strip()
                return routed
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._is_retriable_error(exc):
                    break
                if attempt < self.route_max_retries:
                    delay = self._retry_delay_seconds(attempt, exc)
                    if delay > 0:
                        time.sleep(delay)

        raise LLMRouteError("openai route_intent failed after retries") from last_error

    def render_narration(self, slots: dict[str, Any], style_guard: str) -> str:
        system_prompt = (
            "Write one concise narration paragraph from given slots. "
            "Return JSON only with key narration_text (string)."
        )
        user_prompt = json.dumps(
            {
                "task": "render_narration",
                "style_guard": style_guard,
                "slots": slots,
            },
            ensure_ascii=False,
        )
        last_error: Exception | None = None

        for attempt in range(1, self.narration_max_retries + 1):
            try:
                raw_payload = self._call_chat_completions(
                    model=self.narration_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=self.narration_temperature,
                )
                content = self._extract_chat_content(raw_payload)
                parsed = self._parse_json_object(content)
                text = parsed.get("narration_text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("narration_text is blank")
                return text.strip()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._is_retriable_error(exc):
                    break
                if attempt < self.narration_max_retries:
                    delay = self._retry_delay_seconds(attempt, exc)
                    if delay > 0:
                        time.sleep(delay)

        raise LLMNarrationError("openai render_narration failed after retries") from last_error
