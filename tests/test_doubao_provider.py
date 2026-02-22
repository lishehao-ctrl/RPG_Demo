import asyncio

import pytest

from app.config import settings
from app.modules.llm.adapter import LLMRuntime
from app.modules.llm.providers.doubao import DoubaoProvider


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


class _FakeAsyncClient:
    last_init_timeout = None
    last_request = None

    def __init__(self, *, timeout):
        _FakeAsyncClient.last_init_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, headers: dict, json: dict):
        _FakeAsyncClient.last_request = {
            "url": url,
            "headers": headers,
            "json": json,
        }
        return _FakeResponse(
            {
                "choices": [{"message": {"content": '{"narrative_text":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34},
            }
        )


def test_doubao_payload_uses_configured_temperature_and_max_tokens(monkeypatch) -> None:
    monkeypatch.setattr("app.modules.llm.providers.doubao.httpx.AsyncClient", _FakeAsyncClient)
    provider = DoubaoProvider(
        api_key="test-key",
        base_url="http://example.test/v1",
        temperature=0.1,
        max_tokens=512,
    )

    result, usage = asyncio.run(
        provider.generate(
            "hello",
            request_id="req-1",
            timeout_s=30.0,
            model="Qwen/Qwen3.5-397B-A17B",
            connect_timeout_s=12.0,
            read_timeout_s=30.0,
            write_timeout_s=30.0,
            pool_timeout_s=8.0,
        )
    )

    assert result == '{"narrative_text":"ok"}'
    assert usage["prompt_tokens"] == 12
    assert usage["completion_tokens"] == 34

    req = _FakeAsyncClient.last_request or {}
    assert req["url"] == "http://example.test/v1/chat/completions"
    assert req["headers"]["authorization"] == "Bearer test-key"
    assert req["json"]["temperature"] == 0.1
    assert req["json"]["max_tokens"] == 512


@pytest.mark.parametrize("max_tokens", [0, None])
def test_doubao_payload_omits_max_tokens_when_disabled(monkeypatch, max_tokens) -> None:
    monkeypatch.setattr("app.modules.llm.providers.doubao.httpx.AsyncClient", _FakeAsyncClient)
    provider = DoubaoProvider(
        api_key="test-key",
        base_url="http://example.test/v1",
        temperature=0.2,
        max_tokens=max_tokens,
    )

    asyncio.run(
        provider.generate(
            "hello",
            request_id="req-2",
            timeout_s=30.0,
            model="Qwen/Qwen3.5-397B-A17B",
        )
    )

    req = _FakeAsyncClient.last_request or {}
    assert "max_tokens" not in (req.get("json") or {})
    assert req["json"]["temperature"] == 0.2


def test_llm_runtime_wires_doubao_provider_from_settings() -> None:
    original_temp = settings.llm_doubao_temperature
    original_max_tokens = settings.llm_doubao_max_tokens
    settings.llm_doubao_temperature = 0.07
    settings.llm_doubao_max_tokens = 321
    try:
        runtime = LLMRuntime()
        provider = runtime.providers["doubao"]
        assert isinstance(provider, DoubaoProvider)
        assert provider.temperature == pytest.approx(0.07)
        assert provider.max_tokens == 321
    finally:
        settings.llm_doubao_temperature = original_temp
        settings.llm_doubao_max_tokens = original_max_tokens
