from __future__ import annotations

from typing import Any

import httpx

from rpg_backend.llm.openai_compat import (
    build_auth_headers,
    build_json_mode_body,
    extract_chat_content,
    normalize_chat_completions_url,
    parse_json_object,
)
from rpg_backend.llm.task_executor import TaskUsage
from rpg_backend.llm_worker.upstream.base import UpstreamJsonResult


def _extract_usage(payload: dict[str, Any]) -> TaskUsage:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return TaskUsage()
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    return TaskUsage(
        input_tokens=int(prompt_tokens) if isinstance(prompt_tokens, int) else None,
        output_tokens=int(completion_tokens) if isinstance(completion_tokens, int) else None,
        total_tokens=int(total_tokens) if isinstance(total_tokens, int) else None,
    )


class ChatCompletionsUpstreamClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
    ) -> None:
        self._http_client = http_client
        self._chat_completions_url = normalize_chat_completions_url(base_url)
        self._api_key = api_key

    async def call_json_object(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        timeout_seconds: float,
    ) -> UpstreamJsonResult:
        body = build_json_mode_body(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
        )
        response = await self._http_client.post(
            self._chat_completions_url,
            headers=build_auth_headers(self._api_key),
            json=body,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return UpstreamJsonResult(
            payload=parse_json_object(extract_chat_content(payload)),
            usage=_extract_usage(payload),
        )
