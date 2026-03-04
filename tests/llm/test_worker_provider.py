from __future__ import annotations

from types import SimpleNamespace

import pytest

import rpg_backend.llm.factory as factory_module
from rpg_backend.llm.base import LLMNarrationError, LLMProviderConfigError, LLMRouteError
from rpg_backend.llm.worker_client import WorkerClientError
from rpg_backend.llm.worker_provider import WorkerProvider


class _FakeWorkerClient:
    def __init__(self) -> None:
        self.route_payload = {
            "move_id": "scan_signal",
            "args": {"target": "relay"},
            "confidence": 0.9,
            "interpreted_intent": "scan relay",
        }
        self.narration_payload = {"narration_text": "Narration text."}

    def route_intent(self, **_kwargs):  # noqa: ANN003, ANN201
        return dict(self.route_payload)

    def render_narration(self, **_kwargs):  # noqa: ANN003, ANN201
        return dict(self.narration_payload)


def test_worker_provider_route_success() -> None:
    provider = WorkerProvider(
        worker_client=_FakeWorkerClient(),
        route_model="route-model",
        narration_model="narration-model",
        timeout_seconds=20.0,
        route_max_retries=3,
        narration_max_retries=1,
        route_temperature=0.1,
        narration_temperature=0.4,
    )

    routed = provider.route_intent({"moves": []}, "scan the relay")
    assert routed.move_id == "scan_signal"
    assert routed.confidence == 0.9


def test_worker_provider_route_failure_maps_to_llmrouteerror() -> None:
    class _FailingClient(_FakeWorkerClient):
        def route_intent(self, **_kwargs):  # noqa: ANN003, ANN201
            raise WorkerClientError(
                error_code="llm_worker_unreachable",
                message="connection refused",
                retryable=True,
            )

    provider = WorkerProvider(
        worker_client=_FailingClient(),
        route_model="route-model",
        narration_model="narration-model",
        timeout_seconds=20.0,
        route_max_retries=3,
        narration_max_retries=1,
        route_temperature=0.1,
        narration_temperature=0.4,
    )

    with pytest.raises(LLMRouteError):
        provider.route_intent({"moves": []}, "scan the relay")


def test_worker_provider_narration_blank_raises() -> None:
    class _BlankNarrationClient(_FakeWorkerClient):
        def render_narration(self, **_kwargs):  # noqa: ANN003, ANN201
            return {"narration_text": ""}

    provider = WorkerProvider(
        worker_client=_BlankNarrationClient(),
        route_model="route-model",
        narration_model="narration-model",
        timeout_seconds=20.0,
        route_max_retries=3,
        narration_max_retries=1,
        route_temperature=0.1,
        narration_temperature=0.4,
    )

    with pytest.raises(LLMNarrationError):
        provider.render_narration({"echo": "x"}, "neutral")


def test_factory_returns_worker_provider(monkeypatch) -> None:
    settings = SimpleNamespace(
        llm_gateway_mode="worker",
        llm_openai_route_model="route-model",
        llm_openai_narration_model="narration-model",
        llm_openai_model="",
        llm_openai_base_url="",
        llm_openai_api_key="",
        llm_openai_timeout_seconds=20.0,
        llm_openai_route_max_retries=3,
        llm_openai_narration_max_retries=1,
        llm_openai_temperature_route=0.1,
        llm_openai_temperature_narration=0.4,
    )
    monkeypatch.setattr(factory_module, "get_settings", lambda: settings)
    monkeypatch.setattr(factory_module, "get_worker_client", lambda: _FakeWorkerClient())

    provider = factory_module.get_llm_provider()
    assert isinstance(provider, WorkerProvider)


def test_factory_invalid_gateway_mode_raises(monkeypatch) -> None:
    settings = SimpleNamespace(
        llm_gateway_mode="bad-mode",
        llm_openai_route_model="route-model",
        llm_openai_narration_model="narration-model",
        llm_openai_model="",
        llm_openai_base_url="https://example.com",
        llm_openai_api_key="key",
        llm_openai_timeout_seconds=20.0,
        llm_openai_route_max_retries=3,
        llm_openai_narration_max_retries=1,
        llm_openai_temperature_route=0.1,
        llm_openai_temperature_narration=0.4,
    )
    monkeypatch.setattr(factory_module, "get_settings", lambda: settings)

    with pytest.raises(LLMProviderConfigError):
        factory_module.get_llm_provider()
