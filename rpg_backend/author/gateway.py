from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from openai import OpenAI

from rpg_backend.config import Settings, get_settings

T = TypeVar("T")


class AuthorGatewayError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class GatewayJSONResponse:
    payload: dict[str, Any]
    response_id: str | None
    usage: dict[str, int]
    input_characters: int


@dataclass(frozen=True)
class GatewayStructuredResponse(Generic[T]):
    value: T
    response_id: str | None


@dataclass(frozen=True)
class AuthorLLMGateway:
    client: OpenAI
    model: str
    timeout_seconds: float
    max_output_tokens_overview: int | None
    max_output_tokens_beat_plan: int | None
    max_output_tokens_rulepack: int | None
    use_session_cache: bool = False
    call_trace: list[dict[str, Any]] = field(default_factory=list, repr=False, compare=False)

    @staticmethod
    def _usage_to_dict(usage: Any) -> dict[str, Any]:
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            raw = usage.model_dump()
        elif isinstance(usage, dict):
            raw = usage
        else:
            raw = {}
            for key in dir(usage):
                if key.startswith("_"):
                    continue
                try:
                    raw[key] = getattr(usage, key)
                except Exception:  # noqa: BLE001
                    continue
        normalized: dict[str, Any] = {}
        input_details = raw.get("input_tokens_details")
        if isinstance(input_details, dict):
            if isinstance(input_details.get("cached_tokens"), (int, float)):
                normalized["cached_input_tokens"] = int(input_details["cached_tokens"])
        output_details = raw.get("output_tokens_details")
        if isinstance(output_details, dict):
            if isinstance(output_details.get("reasoning_tokens"), (int, float)):
                normalized["reasoning_tokens"] = int(output_details["reasoning_tokens"])
        x_details = raw.get("x_details")
        if isinstance(x_details, list) and x_details:
            detail = x_details[0]
            if isinstance(detail, dict):
                if isinstance(detail.get("x_billing_type"), str):
                    normalized["billing_type"] = detail["x_billing_type"]
                prompt_details = detail.get("prompt_tokens_details")
                if isinstance(prompt_details, dict):
                    if isinstance(prompt_details.get("cached_tokens"), (int, float)):
                        normalized["cached_input_tokens"] = int(prompt_details["cached_tokens"])
                    if isinstance(prompt_details.get("cache_creation_input_tokens"), (int, float)):
                        normalized["cache_creation_input_tokens"] = int(prompt_details["cache_creation_input_tokens"])
                    cache_creation = prompt_details.get("cache_creation")
                    if isinstance(cache_creation, dict):
                        for key, value in cache_creation.items():
                            if isinstance(value, (int, float)):
                                normalized[str(key)] = int(value)
                    if isinstance(prompt_details.get("cache_type"), str):
                        normalized["cache_type"] = prompt_details["cache_type"]
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = raw.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                normalized[str(key)] = int(value)
        return normalized

    def _invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_output_tokens: int | None,
        previous_response_id: str | None = None,
        operation_name: str | None = None,
    ) -> GatewayJSONResponse:
        user_text = json.dumps(user_payload, ensure_ascii=False, sort_keys=True)
        input_characters = len(user_text)
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": user_text,
            "max_output_tokens": max_output_tokens,
            "timeout": self.timeout_seconds,
            "temperature": 0.2,
            "extra_body": {"enable_thinking": False},
        }
        if self.use_session_cache and previous_response_id:
            request_kwargs["previous_response_id"] = previous_response_id
        try:
            response = self.client.responses.create(**request_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_provider_failed",
                message=str(exc),
                status_code=502,
            ) from exc
        try:
            content = response.output_text
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_invalid_response",
                message="provider response did not include message content",
                status_code=502,
            ) from exc
        text = str(content or "").strip()
        if not text:
            raise AuthorGatewayError(
                code="llm_invalid_json",
                message="provider returned empty content",
                status_code=502,
            )
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        try:
            payload = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_invalid_json",
                message=str(exc),
                status_code=502,
            ) from exc
        if not isinstance(payload, dict):
            raise AuthorGatewayError(
                code="llm_invalid_json",
                message="provider returned a non-object JSON payload",
                status_code=502,
            )
        usage = self._usage_to_dict(getattr(response, "usage", None))
        self.call_trace.append(
            {
                "operation": operation_name or "unknown",
                "response_id": getattr(response, "id", None),
                "used_previous_response_id": bool(previous_response_id),
                "session_cache_enabled": bool(self.use_session_cache),
                "max_output_tokens": max_output_tokens,
                "input_characters": input_characters,
                "usage": usage,
            }
        )
        return GatewayJSONResponse(
            payload=payload,
            response_id=getattr(response, "id", None),
            usage=usage,
            input_characters=input_characters,
        )


def get_author_llm_gateway(settings: Settings | None = None) -> AuthorLLMGateway:
    resolved = settings or get_settings()
    base_url = (resolved.responses_base_url or "").strip()
    api_key = (resolved.responses_api_key or "").strip()
    model = (resolved.responses_model or "").strip()
    if not base_url or not api_key or not model:
        raise AuthorGatewayError(
            code="llm_config_missing",
            message="APP_RESPONSES_BASE_URL, APP_RESPONSES_API_KEY, and APP_RESPONSES_MODEL are required",
            status_code=500,
        )
    use_session_cache = resolved.responses_use_session_cache
    if use_session_cache is None:
        use_session_cache = "dashscope" in base_url.casefold()
    client_kwargs: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
    }
    if use_session_cache:
        client_kwargs["default_headers"] = {
            resolved.responses_session_cache_header: resolved.responses_session_cache_value,
        }
    client = OpenAI(**client_kwargs)
    return AuthorLLMGateway(
        client=client,
        model=model,
        timeout_seconds=float(resolved.responses_timeout_seconds),
        max_output_tokens_overview=resolved.responses_max_output_tokens_author_overview,
        max_output_tokens_beat_plan=resolved.responses_max_output_tokens_author_beat_plan,
        max_output_tokens_rulepack=resolved.responses_max_output_tokens_author_rulepack,
        use_session_cache=bool(use_session_cache),
    )
