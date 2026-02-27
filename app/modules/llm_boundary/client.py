from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable, Literal, TypedDict

import httpx

STRICT_SYSTEM_PROMPT = "Return STRICT JSON. No markdown. No explanation."


class ChatCompletionMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class JSONSchemaConfig(TypedDict):
    name: str
    schema: dict
    strict: bool


class JSONSchemaResponseFormat(TypedDict):
    type: Literal["json_schema"]
    json_schema: JSONSchemaConfig


class LLMCallError(RuntimeError):
    pass


def _normalize_messages(messages: list[dict]) -> list[ChatCompletionMessage]:
    normalized: list[ChatCompletionMessage] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role not in {"system", "user", "assistant"}:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _prepend_strict_system(messages: list[ChatCompletionMessage]) -> list[ChatCompletionMessage]:
    trimmed = [m for m in messages if not (m["role"] == "system" and m["content"].strip() == STRICT_SYSTEM_PROMPT)]
    return [{"role": "system", "content": STRICT_SYSTEM_PROMPT}, *trimmed]


def _endpoint_url(*, base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


async def _post_chat_completions(
    *,
    api_key: str,
    endpoint_url: str,
    model: str,
    messages: list[ChatCompletionMessage],
    response_format: dict | None,
    timeout_s: float,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    timeout = httpx.Timeout(timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(endpoint_url, headers=headers, json=payload)
    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            f"chat/completions non-200: {response.status_code}",
            request=response.request,
            response=response,
        )
    return response.json()


def extract_message_content(data: dict) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise LLMCallError("missing choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMCallError("empty model content")
    return content


def _extract_stream_chunk_text(chunk: dict, *, ignore_reasoning: bool) -> str:
    if not isinstance(chunk, dict):
        return ""
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""

    fragments: list[str] = []
    reasoning = delta.get("reasoning_content")
    if not ignore_reasoning and isinstance(reasoning, str) and reasoning:
        fragments.append(reasoning)
    content = delta.get("content")
    if isinstance(content, str) and content:
        fragments.append(content)
    return "".join(fragments)


async def _stream_chat_completion_chunks(
    *,
    api_key: str,
    endpoint_url: str,
    model: str,
    messages: list[ChatCompletionMessage],
    timeout_s: float,
) -> AsyncIterator[dict]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "stream": True,
    }
    timeout = httpx.Timeout(timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", endpoint_url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"chat/completions stream non-200: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            async for line in response.aiter_lines():
                text = str(line or "").strip()
                if not text or not text.startswith("data:"):
                    continue
                payload_text = text[len("data:") :].strip()
                if not payload_text:
                    continue
                if payload_text == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload_text)
                except json.JSONDecodeError as exc:
                    raise LLMCallError("invalid streamed json chunk") from exc
                if isinstance(chunk, dict):
                    yield chunk


async def call_chat_completions(
    *,
    api_key: str,
    base_url: str,
    path: str,
    model: str,
    messages: list[dict],
    response_format: dict,
    timeout_s: float,
    max_attempts: int = 3,
) -> str:
    normalized = _normalize_messages(messages)
    if not normalized:
        normalized = [{"role": "user", "content": ""}]
    endpoint = _endpoint_url(base_url=base_url, path=path)

    attempts = max(1, int(max_attempts))
    delays = (0.2, 0.5)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            data = await _post_chat_completions(
                api_key=api_key,
                endpoint_url=endpoint,
                model=model,
                messages=_prepend_strict_system(normalized),
                response_format=response_format,
                timeout_s=timeout_s,
            )
            return extract_message_content(data)
        except (httpx.HTTPError, ValueError, LLMCallError) as exc:
            last_error = exc
            if attempt >= attempts - 1:
                break
            pause_idx = min(attempt, len(delays) - 1)
            await asyncio.sleep(delays[pause_idx])
    raise LLMCallError(f"chat completions failed after retries: {last_error}")


async def call_chat_completions_text(
    *,
    api_key: str,
    base_url: str,
    path: str,
    model: str,
    messages: list[dict],
    timeout_s: float,
) -> str:
    normalized = _normalize_messages(messages)
    if not normalized:
        normalized = [{"role": "user", "content": ""}]
    endpoint = _endpoint_url(base_url=base_url, path=path)

    delays = (0.2, 0.5)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            data = await _post_chat_completions(
                api_key=api_key,
                endpoint_url=endpoint,
                model=model,
                messages=normalized,
                response_format=None,
                timeout_s=timeout_s,
            )
            return extract_message_content(data)
        except (httpx.HTTPError, ValueError, LLMCallError) as exc:
            last_error = exc
            if attempt >= 2:
                break
            await asyncio.sleep(delays[attempt])
    raise LLMCallError(f"chat completions text failed after retries: {last_error}")


async def call_chat_completions_stream_text(
    *,
    api_key: str,
    base_url: str,
    path: str,
    model: str,
    messages: list[dict],
    timeout_s: float,
    ignore_reasoning: bool = True,
    on_delta: Callable[[str], None] | None = None,
) -> str:
    normalized = _normalize_messages(messages)
    if not normalized:
        normalized = [{"role": "user", "content": ""}]
    endpoint = _endpoint_url(base_url=base_url, path=path)

    delays = (0.2, 0.5)
    last_error: Exception | None = None
    for attempt in range(3):
        fragments: list[str] = []
        stream_started = False
        try:
            async for chunk in _stream_chat_completion_chunks(
                api_key=api_key,
                endpoint_url=endpoint,
                model=model,
                messages=normalized,
                timeout_s=timeout_s,
            ):
                stream_started = True
                piece = _extract_stream_chunk_text(chunk, ignore_reasoning=ignore_reasoning)
                if piece:
                    fragments.append(piece)
                    if on_delta is not None:
                        try:
                            on_delta(piece)
                        except Exception:
                            # Streaming callbacks are best-effort UI hooks and
                            # should not break core runtime completion behavior.
                            pass

            text = "".join(fragments).strip()
            if not text:
                raise LLMCallError("empty streamed content")
            return text
        except (httpx.HTTPError, ValueError, LLMCallError) as exc:
            last_error = exc
            # Fail fast when stream has started; do not accept partial outputs.
            if stream_started or attempt >= 2:
                break
            await asyncio.sleep(delays[attempt])
    raise LLMCallError(f"chat completions stream failed after retries: {last_error}")
