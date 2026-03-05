from __future__ import annotations

import httpx

from rpg_backend.llm_worker.upstream.base import WorkerUpstreamClient
from rpg_backend.llm_worker.upstream.chat_completions_client import ChatCompletionsUpstreamClient
from rpg_backend.llm_worker.upstream.responses_client import ResponsesUpstreamClient


def build_worker_upstream_client(
    *,
    http_client: httpx.AsyncClient,
    api_format: str,
    base_url: str,
    api_key: str,
) -> WorkerUpstreamClient:
    normalized = (api_format or "chat_completions").strip().lower()
    if normalized == "chat_completions":
        return ChatCompletionsUpstreamClient(
            http_client=http_client,
            base_url=base_url,
            api_key=api_key,
        )
    if normalized == "responses":
        return ResponsesUpstreamClient(
            http_client=http_client,
            base_url=base_url,
            api_key=api_key,
        )
    raise ValueError(f"unsupported upstream api format: {api_format}")
