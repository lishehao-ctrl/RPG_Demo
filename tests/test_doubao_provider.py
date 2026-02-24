from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.modules.llm.adapter import LLMRuntime
from app.modules.llm.providers.doubao import DoubaoProvider


def test_doubao_generate_uses_proxy_chat_completions_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _fake_call_llm_messages(*, api_key: str, model: str, messages: list[dict[str, str]]) -> dict:
        captured["api_key"] = api_key
        captured["model"] = model
        captured["messages"] = messages
        return {
            "choices": [{"message": {"content": '{"narrative_text":"ok"}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 34},
        }

    monkeypatch.setattr("app.modules.llm.providers.doubao.call_llm_messages", _fake_call_llm_messages)
    provider = DoubaoProvider(
        api_key="test-key",
        base_url="http://example.test/ignored",
        temperature=0.7,
        max_tokens=512,
    )

    result, usage = asyncio.run(
        provider.generate(
            "hello",
            request_id="req-1",
            timeout_s=30.0,
            model="Qwen/Qwen3.5-397B-A17B",
            messages_override=[
                {"role": "system", "content": "runtime system"},
                {"role": "user", "content": "runtime user"},
            ],
            temperature_override=0.9,
        )
    )

    assert provider.base_url == "https://api.xiaocaseai.cloud"
    assert provider.temperature == pytest.approx(0.0)
    assert result == '{"narrative_text":"ok"}'
    assert usage["prompt_tokens"] == 12
    assert usage["completion_tokens"] == 34

    assert captured["api_key"] == "test-key"
    assert captured["model"] == "Qwen/Qwen3.5-397B-A17B"
    # Strict system prompt must always be prepended by the shared chat client.
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][0]["content"] == "runtime system"


def test_doubao_generate_defaults_user_message_when_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _fake_call_llm_messages(*, api_key: str, model: str, messages: list[dict[str, str]]) -> dict:
        captured["messages"] = messages
        return {
            "choices": [{"message": {"content": '{"narrative_text":"ok"}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr("app.modules.llm.providers.doubao.call_llm_messages", _fake_call_llm_messages)
    provider = DoubaoProvider(api_key="k", base_url="http://ignored")

    asyncio.run(
        provider.generate(
            "legacy prompt text",
            request_id="req-2",
            timeout_s=20.0,
            model="Qwen/Qwen3.5-397B-A17B",
        )
    )

    assert captured["messages"] == [{"role": "user", "content": "legacy prompt text"}]


def test_llm_runtime_wires_doubao_provider_from_settings() -> None:
    original_temp = settings.llm_doubao_temperature
    original_max_tokens = settings.llm_doubao_max_tokens
    settings.llm_doubao_temperature = 0.07
    settings.llm_doubao_max_tokens = 321
    try:
        runtime = LLMRuntime()
        provider = runtime.providers["proxy"]
        assert isinstance(provider, DoubaoProvider)
        # Provider is hard-forced to zero temperature in fail-fast proxy mode.
        assert provider.temperature == pytest.approx(0.0)
        assert provider.max_tokens == 321
    finally:
        settings.llm_doubao_temperature = original_temp
        settings.llm_doubao_max_tokens = original_max_tokens
