from __future__ import annotations

from typing import Any

import httpx

from rpg_backend.llm.openai_compat import build_auth_headers, parse_json_object
from rpg_backend.llm.task_executor import TaskUsage
from rpg_backend.llm_worker.upstream.base import UpstreamJsonResult


def normalize_responses_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if normalized.endswith("/responses"):
        return normalized
    if normalized.endswith("/chat/completions"):
        return f"{normalized[:-len('/chat/completions')]}/responses"
    if normalized.endswith("/v1"):
        return f"{normalized}/responses"
    return f"{normalized}/v1/responses"


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = payload.get("output")
    if not isinstance(output, list):
        raise ValueError("responses payload missing output text")

    fragments: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        contents = item.get("content")
        if not isinstance(contents, list):
            continue
        for content in contents:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                fragments.append(text)
    joined = "".join(fragments).strip()
    if not joined:
        raise ValueError("responses payload missing output text")
    return joined


def _extract_usage(payload: dict[str, Any]) -> TaskUsage:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return TaskUsage()
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    return TaskUsage(
        input_tokens=int(input_tokens) if isinstance(input_tokens, int) else None,
        output_tokens=int(output_tokens) if isinstance(output_tokens, int) else None,
        total_tokens=int(total_tokens) if isinstance(total_tokens, int) else None,
    )


class ResponsesUpstreamClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
    ) -> None:
        self._http_client = http_client
        self._responses_url = normalize_responses_url(base_url)
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
        body = {
            "model": model,
            "temperature": temperature,
            "instructions": system_prompt,
            "input": user_prompt,
            "text": {"format": {"type": "json_object"}},
        }
        response = await self._http_client.post(
            self._responses_url,
            headers=build_auth_headers(self._api_key),
            json=body,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = _extract_output_text(payload)
        return UpstreamJsonResult(
            payload=parse_json_object(content),
            usage=_extract_usage(payload),
        )
