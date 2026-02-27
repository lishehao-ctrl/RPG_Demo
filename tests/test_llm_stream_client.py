from __future__ import annotations

import asyncio

import httpx
import pytest

from app.modules.llm_boundary.client import LLMCallError, call_chat_completions_stream_text


def _base_kwargs() -> dict:
    return {
        "api_key": "k",
        "base_url": "https://example.com/v1",
        "path": "/chat/completions",
        "model": "demo-model",
        "messages": [{"role": "user", "content": "hello"}],
        "timeout_s": 5.0,
    }


def test_stream_client_concatenates_chunks_and_ignores_reasoning(monkeypatch) -> None:
    async def _fake_stream(**kwargs):
        del kwargs
        yield {"choices": [{"delta": {"content": "Hel"}}]}
        yield {"choices": [{"delta": {"reasoning_content": "internal reasoning"}}]}
        yield {"choices": [{"delta": {"content": "lo"}}]}

    monkeypatch.setattr("app.modules.llm_boundary.client._stream_chat_completion_chunks", _fake_stream)
    text = asyncio.run(call_chat_completions_stream_text(**_base_kwargs(), ignore_reasoning=True))
    assert text == "Hello"


def test_stream_client_can_include_reasoning_when_configured(monkeypatch) -> None:
    async def _fake_stream(**kwargs):
        del kwargs
        yield {"choices": [{"delta": {"reasoning_content": "think "}}]}
        yield {"choices": [{"delta": {"content": "answer"}}]}

    monkeypatch.setattr("app.modules.llm_boundary.client._stream_chat_completion_chunks", _fake_stream)
    text = asyncio.run(call_chat_completions_stream_text(**_base_kwargs(), ignore_reasoning=False))
    assert text == "think answer"


def test_stream_client_raises_on_empty_streamed_content(monkeypatch) -> None:
    async def _fake_stream(**kwargs):
        del kwargs
        yield {"choices": [{"delta": {"reasoning_content": "only reasoning"}}]}

    monkeypatch.setattr("app.modules.llm_boundary.client._stream_chat_completion_chunks", _fake_stream)
    with pytest.raises(LLMCallError):
        asyncio.run(call_chat_completions_stream_text(**_base_kwargs(), ignore_reasoning=True))


def test_stream_client_fails_fast_when_stream_breaks_midway(monkeypatch) -> None:
    async def _broken_stream(**kwargs):
        del kwargs
        yield {"choices": [{"delta": {"content": "partial"}}]}
        raise httpx.ReadError("broken", request=httpx.Request("POST", "https://example.com"))

    monkeypatch.setattr("app.modules.llm_boundary.client._stream_chat_completion_chunks", _broken_stream)
    with pytest.raises(LLMCallError):
        asyncio.run(call_chat_completions_stream_text(**_base_kwargs(), ignore_reasoning=True))


def test_stream_client_retries_before_stream_start(monkeypatch) -> None:
    state = {"attempt": 0}

    async def _flaky_stream(**kwargs):
        del kwargs
        state["attempt"] += 1
        if state["attempt"] < 3:
            raise httpx.ConnectError("connect failed", request=httpx.Request("POST", "https://example.com"))
        yield {"choices": [{"delta": {"content": "ok"}}]}

    monkeypatch.setattr("app.modules.llm_boundary.client._stream_chat_completion_chunks", _flaky_stream)
    text = asyncio.run(call_chat_completions_stream_text(**_base_kwargs(), ignore_reasoning=True))
    assert text == "ok"
    assert state["attempt"] == 3
