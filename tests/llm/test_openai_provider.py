from __future__ import annotations

import json

import httpx
import pytest

from rpg_backend.llm.base import LLMNarrationError, LLMRouteError
from rpg_backend.llm.openai_provider import OpenAIProvider


def _chat_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _provider(*, route_retries: int = 3, narration_retries: int = 1) -> OpenAIProvider:
    return OpenAIProvider(
        base_url="http://localhost:11434",
        api_key="test-key",
        route_model="route-model",
        narration_model="narration-model",
        route_max_retries=route_retries,
        narration_max_retries=narration_retries,
    )


def test_route_intent_accepts_valid_json(monkeypatch) -> None:
    provider = _provider()

    monkeypatch.setattr(
        provider,
        "_call_chat_completions",
        lambda **_: _chat_payload(
            '{"move_id":"scan_signal","args":{"target":"relay"},'
            '"confidence":0.82,"interpreted_intent":"scan relay"}'
        ),
    )

    result = provider.route_intent(
        {
            "moves": [{"id": "scan_signal", "label": "Scan", "intents": ["scan"], "synonyms": ["signal"]}],
            "fallback_move": "global.help_me_progress",
            "scene_seed": "test",
        },
        "scan the relay",
    )
    assert result.move_id == "scan_signal"
    assert result.confidence == 0.82


def test_route_intent_retries_until_valid(monkeypatch) -> None:
    provider = _provider(route_retries=3)
    payloads = [
        _chat_payload("not-json"),
        _chat_payload('{"move_id":"","confidence":2,"interpreted_intent":""}'),
        _chat_payload(
            '{"move_id":"global.help_me_progress","args":{},'
            '"confidence":0.4,"interpreted_intent":"unclear"}'
        ),
    ]

    def _next_payload(**_):
        return payloads.pop(0)

    monkeypatch.setattr(provider, "_call_chat_completions", _next_payload)

    result = provider.route_intent(
        {"moves": [], "fallback_move": "global.help_me_progress", "scene_seed": "test"},
        "???",
    )
    assert result.move_id == "global.help_me_progress"
    assert result.confidence == 0.4


def test_route_intent_raises_after_max_retries(monkeypatch) -> None:
    provider = _provider(route_retries=3)
    monkeypatch.setattr(
        provider,
        "_call_chat_completions",
        lambda **_: _chat_payload("still-not-json"),
    )

    with pytest.raises(LLMRouteError):
        provider.route_intent(
            {"moves": [], "fallback_move": "global.help_me_progress", "scene_seed": "test"},
            "???",
        )


def test_render_narration_raises_on_invalid_payload(monkeypatch) -> None:
    provider = _provider(narration_retries=1)
    monkeypatch.setattr(
        provider,
        "_call_chat_completions",
        lambda **_: _chat_payload('{"not_text":"x"}'),
    )

    with pytest.raises(LLMNarrationError):
        provider.render_narration({"echo": "Echo", "commit": "Commit", "hook": "Hook"}, "neutral")


def test_route_intent_does_not_retry_on_401(monkeypatch) -> None:
    provider = _provider(route_retries=3)
    call_count = 0

    def _unauthorized(**_):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("POST", provider.chat_completions_url)
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr(provider, "_call_chat_completions", _unauthorized)

    with pytest.raises(LLMRouteError):
        provider.route_intent(
            {"moves": [], "fallback_move": "global.help_me_progress", "scene_seed": "test"},
            "help",
        )
    assert call_count == 1


def test_route_intent_retries_on_503_then_succeeds(monkeypatch) -> None:
    provider = _provider(route_retries=3)
    call_count = 0

    def _temporary_failure_then_success(**_):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            request = httpx.Request("POST", provider.chat_completions_url)
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("temporary failure", request=request, response=response)
        return _chat_payload(
            '{"move_id":"global.help_me_progress","args":{},'
            '"confidence":0.9,"interpreted_intent":"help me progress"}'
        )

    monkeypatch.setattr(provider, "_call_chat_completions", _temporary_failure_then_success)
    monkeypatch.setattr("rpg_backend.llm.openai_provider.time.sleep", lambda _delay: None)

    result = provider.route_intent(
        {"moves": [], "fallback_move": "global.help_me_progress", "scene_seed": "test"},
        "help",
    )
    assert result.move_id == "global.help_me_progress"
    assert call_count == 3


def test_route_intent_uses_route_model(monkeypatch) -> None:
    provider = _provider()
    captured_models: list[str] = []

    def _capture_call(**kwargs):
        captured_models.append(kwargs["model"])
        return _chat_payload(
            '{"move_id":"global.help_me_progress","args":{},'
            '"confidence":0.9,"interpreted_intent":"help me progress"}'
        )

    monkeypatch.setattr(provider, "_call_chat_completions", _capture_call)
    _ = provider.route_intent(
        {"moves": [], "fallback_move": "global.help_me_progress", "scene_seed": "test"},
        "help me progress",
    )
    assert captured_models == ["route-model"]


def test_route_intent_prompt_includes_route_policy_and_is_global(monkeypatch) -> None:
    provider = _provider()
    captured_payloads: list[dict] = []

    def _capture_call(**kwargs):
        captured_payloads.append(kwargs)
        return _chat_payload(
            '{"move_id":"scan_signal","args":{},'
            '"confidence":0.9,"interpreted_intent":"trace signal"}'
        )

    monkeypatch.setattr(provider, "_call_chat_completions", _capture_call)
    _ = provider.route_intent(
        {
            "moves": [
                {
                    "id": "scan_signal",
                    "label": "Trace",
                    "intents": ["scan"],
                    "synonyms": ["trace"],
                    "is_global": False,
                },
                {
                    "id": "global.help_me_progress",
                    "label": "Help",
                    "intents": ["help"],
                    "synonyms": ["stuck"],
                    "is_global": True,
                },
            ],
            "fallback_move": "global.clarify",
            "scene_seed": "signal corridor",
            "allow_global_help": False,
            "scene_snapshot": {
                "scene_id": "sc3",
                "beat_id": "b1",
                "beat_index": 0,
                "present_npcs": ["Kael", "Niko"],
                "beat_title": "Fault Ignition",
            },
            "state_snapshot": {
                "last_move": "trace_anomaly",
                "pressure_tracks": {"public_trust": -1, "resource_stress": 2, "coordination_noise": 3},
                "recent_events_tail": ["b1.root_cause_locked"],
            },
        },
        "trace the fault",
    )
    assert captured_payloads
    user_payload = json.loads(captured_payloads[0]["user_prompt"])
    assert user_payload["route_policy"]["prefer_scene_specific"] is True
    assert user_payload["route_policy"]["allow_global_help"] is False
    assert user_payload["moves"][0]["is_global"] is False
    assert user_payload["scene_snapshot"]["scene_id"] == "sc3"
    assert user_payload["state_snapshot"]["pressure_tracks"]["coordination_noise"] == 3


def test_render_narration_uses_narration_model(monkeypatch) -> None:
    provider = _provider()
    captured_models: list[str] = []

    def _capture_call(**kwargs):
        captured_models.append(kwargs["model"])
        return _chat_payload('{"narration_text":"ok"}')

    monkeypatch.setattr(provider, "_call_chat_completions", _capture_call)
    _ = provider.render_narration({"echo": "Echo", "commit": "Commit", "hook": "Hook"}, "neutral")
    assert captured_models == ["narration-model"]


def test_normalize_uses_chat_completions_endpoint() -> None:
    provider = _provider()
    assert provider.chat_completions_url.endswith("/v1/chat/completions")


def test_constructor_resolves_models_from_route_only() -> None:
    provider = OpenAIProvider(
        base_url="https://example.com/compatible-mode",
        api_key="test-key",
        route_model="route-only-model",
        narration_model="",
        model="",
    )
    assert provider.route_model == "route-only-model"
    assert provider.narration_model == "route-only-model"


def test_constructor_resolves_models_from_narration_only() -> None:
    provider = OpenAIProvider(
        base_url="https://example.com/compatible-mode",
        api_key="test-key",
        route_model="",
        narration_model="narration-only-model",
        model="",
    )
    assert provider.route_model == "narration-only-model"
    assert provider.narration_model == "narration-only-model"


def test_constructor_resolves_models_from_default_model_only() -> None:
    provider = OpenAIProvider(
        base_url="https://example.com/compatible-mode",
        api_key="test-key",
        route_model="",
        narration_model="",
        model="default-model",
    )
    assert provider.route_model == "default-model"
    assert provider.narration_model == "default-model"
