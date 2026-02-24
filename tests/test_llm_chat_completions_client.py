from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.modules.llm.runtime import chat_completions_client as client


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.request = httpx.Request("POST", client.CHAT_COMPLETIONS_URL)

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    scenarios: list[object] = []
    requests: list[dict] = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, headers: dict, json: dict):
        _FakeAsyncClient.requests.append({"url": url, "headers": headers, "json": json})
        if not _FakeAsyncClient.scenarios:
            raise RuntimeError("no fake scenario configured")
        outcome = _FakeAsyncClient.scenarios.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _make_payload(content: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                }
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5},
    }


def test_call_llm_uses_fixed_proxy_endpoint_and_strict_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.scenarios = [_FakeResponse(status_code=200, payload=_make_payload('{"label":"notify"}'))]
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _FakeAsyncClient)

    payload = asyncio.run(client.call_llm("k", "m", "email body"))
    assert isinstance(payload, dict)

    assert len(_FakeAsyncClient.requests) == 1
    req = _FakeAsyncClient.requests[0]
    assert req["url"] == "https://api.xiaocaseai.cloud/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer k"
    assert req["headers"]["Content-Type"] == "application/json"
    assert set(req["json"].keys()) == {"model", "messages", "temperature"}
    assert req["json"]["model"] == "m"
    assert req["json"]["temperature"] == 0
    assert req["json"]["messages"][0] == {
        "role": "system",
        "content": "Return STRICT JSON. No markdown. No explanation.",
    }
    assert req["json"]["messages"][1]["role"] == "user"


def test_call_llm_messages_keeps_strict_system_first_and_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.scenarios = [_FakeResponse(status_code=200, payload=_make_payload('{"label":"notify"}'))]
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _FakeAsyncClient)

    payload = asyncio.run(
        client.call_llm_messages(
            "k",
            "model-from-env",
            [
                {"role": "system", "content": "Return STRICT JSON. No markdown. No explanation."},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "prev"},
            ],
        )
    )
    assert isinstance(payload, dict)
    assert len(_FakeAsyncClient.requests) == 1
    req = _FakeAsyncClient.requests[0]
    assert set(req["json"].keys()) == {"model", "messages", "temperature"}
    assert req["json"]["model"] == "model-from-env"
    assert req["json"]["temperature"] == 0
    assert req["json"]["messages"][0]["role"] == "system"
    assert req["json"]["messages"][0]["content"] == "Return STRICT JSON. No markdown. No explanation."
    assert req["json"]["messages"][1]["role"] == "user"
    assert req["json"]["messages"][2]["role"] == "assistant"


def test_classify_email_retries_on_http_non_200_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.scenarios = [
        _FakeResponse(status_code=500, payload={"error": "boom"}),
        _FakeResponse(status_code=200, payload=_make_payload('{"label":"archive"}')),
    ]
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(client.classify_email("k", "m", "msg"))
    assert result == {"label": "archive"}
    assert len(_FakeAsyncClient.requests) == 2


def test_classify_email_retries_on_invalid_json_and_missing_field(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.scenarios = [
        _FakeResponse(status_code=200, payload=_make_payload("not json")),
        _FakeResponse(status_code=200, payload=_make_payload('{"foo":"bar"}')),
        _FakeResponse(status_code=200, payload=_make_payload('{"label":"review"}')),
    ]
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(client.classify_email("k", "m", "msg"))
    assert result == {"label": "review"}
    assert len(_FakeAsyncClient.requests) == 3


def test_classify_email_raises_after_retry_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.scenarios = [
        _FakeResponse(status_code=200, payload=_make_payload('{"label":"unknown"}')),
        _FakeResponse(status_code=200, payload=_make_payload('{"label":"unknown"}')),
        _FakeResponse(status_code=200, payload=_make_payload('{"label":"unknown"}')),
    ]
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _FakeAsyncClient)

    with pytest.raises(client.LLMCallError):
        asyncio.run(client.classify_email("k", "m", "msg"))


def test_parse_llm_output_requires_non_empty_label() -> None:
    parsed = client.parse_llm_output(json.dumps({"label": "notify"}), required_fields=("label",))
    assert parsed["label"] == "notify"

    with pytest.raises(client.LLMOutputValidationError):
        client.parse_llm_output(json.dumps({"label": ""}), required_fields=("label",))
