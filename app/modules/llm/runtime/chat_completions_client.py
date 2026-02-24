from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Literal, TypedDict

import httpx

STRICT_SYSTEM_PROMPT = "Return STRICT JSON. No markdown. No explanation."
CHAT_COMPLETIONS_URL = "https://api.xiaocaseai.cloud/v1/chat/completions"
_LABEL_ENUM = {"notify", "archive", "drop", "review"}


class ChatCompletionMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionPayload(TypedDict):
    model: str
    messages: list[ChatCompletionMessage]
    temperature: int


class LLMCallError(RuntimeError):
    """Raised when the proxy chat/completions request fails after retries."""


class LLMOutputValidationError(ValueError):
    """Raised when model output JSON is invalid or missing required fields."""


def _retry_delays_s() -> tuple[float, float]:
    return (0.5, 1.0)


def _build_messages(user_input: str) -> list[ChatCompletionMessage]:
    return [
        {"role": "system", "content": STRICT_SYSTEM_PROMPT},
        {"role": "user", "content": str(user_input)},
    ]


def _prepend_strict_system(messages: list[ChatCompletionMessage]) -> list[ChatCompletionMessage]:
    filtered: list[ChatCompletionMessage] = []
    for item in messages:
        role = item["role"]
        content = item["content"]
        if role == "system" and content.strip() == STRICT_SYSTEM_PROMPT:
            continue
        filtered.append({"role": role, "content": content})
    return [{"role": "system", "content": STRICT_SYSTEM_PROMPT}, *filtered]


def _normalize_messages(messages: list[dict[str, str]]) -> list[ChatCompletionMessage]:
    normalized_messages: list[ChatCompletionMessage] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role not in {"system", "user", "assistant"}:
            continue
        normalized_messages.append(
            {
                "role": role,
                "content": content,
            }
        )
    return normalized_messages


def _build_chat_completion_payload(*, model: str, messages: list[ChatCompletionMessage]) -> ChatCompletionPayload:
    return {
        "model": str(model),
        "messages": list(messages),
        "temperature": 0,
    }


async def _post_chat_completions(
    *,
    api_key: str,
    model: str,
    messages: list[ChatCompletionMessage],
    timeout_s: float = 30.0,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = _build_chat_completion_payload(model=model, messages=messages)
    timeout = httpx.Timeout(timeout=timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(CHAT_COMPLETIONS_URL, headers=headers, json=payload)
    if response.status_code != 200:
        request = response.request
        raise httpx.HTTPStatusError(
            f"chat/completions non-200: {response.status_code}",
            request=request,
            response=response,
        )
    return response.json()


def _extract_content(response_payload: dict) -> str:
    try:
        choices = response_payload["choices"]
        if not isinstance(choices, list) or not choices:
            raise KeyError("choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise KeyError("choices[0]")
        message = first_choice["message"]
        if not isinstance(message, dict):
            raise KeyError("message")
        content = message["content"]
    except Exception as exc:  # noqa: BLE001
        raise LLMOutputValidationError("Missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMOutputValidationError("Missing choices[0].message.content")
    return content


def parse_llm_output(raw_content: str, required_fields: tuple[str, ...] = ("label",)) -> dict:
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise LLMOutputValidationError(f"Model output is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMOutputValidationError("Model output must be a JSON object")

    for field in required_fields:
        if field not in parsed:
            raise LLMOutputValidationError(f"Missing required field: {field}")

    if "label" in required_fields:
        label_value = parsed.get("label")
        if not isinstance(label_value, str) or not label_value.strip():
            raise LLMOutputValidationError("Field 'label' must be a non-empty string")

    return parsed


async def _call_llm_with_validation(
    *,
    api_key: str,
    model: str,
    messages: list[ChatCompletionMessage],
    validator: Callable[[str], object] | None,
) -> dict:
    delays = _retry_delays_s()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response_payload = await _post_chat_completions(api_key=api_key, model=model, messages=messages)
            if validator is not None:
                content = _extract_content(response_payload)
                validator(content)
            return response_payload
        except (httpx.HTTPError, json.JSONDecodeError, LLMOutputValidationError, ValueError) as exc:
            last_error = exc
            if attempt >= 2:
                break
            await asyncio.sleep(delays[attempt])
    raise LLMCallError(f"LLM call failed after retries: {last_error}") from last_error


async def call_llm(api_key: str, model: str, user_input: str) -> dict:
    messages = _prepend_strict_system(_build_messages(user_input))
    return await _call_llm_with_validation(
        api_key=api_key,
        model=model,
        messages=messages,
        validator=None,
    )


async def call_llm_messages(api_key: str, model: str, messages: list[dict[str, str]]) -> dict:
    normalized_messages = _normalize_messages(messages)
    if not normalized_messages:
        normalized_messages = _build_messages("")
    return await _call_llm_with_validation(
        api_key=api_key,
        model=model,
        messages=_prepend_strict_system(normalized_messages),
        validator=None,
    )


async def classify_email(api_key: str, model: str, user_input: str) -> dict:
    def _validate_email_label(content: str) -> dict:
        parsed_local = parse_llm_output(content, required_fields=("label",))
        label_local = str(parsed_local.get("label") or "").strip().lower()
        if label_local not in _LABEL_ENUM:
            raise LLMOutputValidationError("Field 'label' must be one of notify|archive|drop|review")
        return {"label": label_local}

    response_payload = await _call_llm_with_validation(
        api_key=api_key,
        model=model,
        messages=_build_messages(user_input),
        validator=_validate_email_label,
    )
    content = _extract_content(response_payload)
    return _validate_email_label(content)


__all__ = [
    "ChatCompletionMessage",
    "ChatCompletionPayload",
    "CHAT_COMPLETIONS_URL",
    "STRICT_SYSTEM_PROMPT",
    "LLMCallError",
    "LLMOutputValidationError",
    "call_llm",
    "call_llm_messages",
    "parse_llm_output",
    "classify_email",
]
