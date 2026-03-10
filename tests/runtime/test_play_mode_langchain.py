from __future__ import annotations

import asyncio
import json

from rpg_backend.llm.base import LLMJsonObjectResult, LLMProvider
from rpg_backend.llm.worker_provider import WorkerProvider
from rpg_backend.runtime_chains.play_mode import NarrationChain, RouteIntentChain


class _FakeWorkerClient:
    async def json_object(self, **_kwargs):  # pragma: no cover
        raise AssertionError("worker json_object should not be used directly by tests")


def _worker_provider() -> WorkerProvider:
    return WorkerProvider(
        worker_client=_FakeWorkerClient(),
        route_model="route-model",
        narration_model="narration-model",
        timeout_seconds=20.0,
        route_max_retries=3,
        narration_max_retries=1,
        route_temperature=0.1,
        narration_temperature=0.4,
    )


class _FakeJsonProvider(LLMProvider):
    gateway_mode = "unknown"
    route_model = "route-model"
    narration_model = "narration-model"
    timeout_seconds = 20.0
    route_max_retries = 3
    narration_max_retries = 1
    route_temperature = 0.1
    narration_temperature = 0.4

    async def invoke_json_object(self, **kwargs) -> LLMJsonObjectResult:  # noqa: ANN003
        payload = json.loads(kwargs["user_prompt"])
        task = payload["task"]
        if task == "select_route_candidate":
            fallback = payload["scene_context"]["fallback_key"]
            return LLMJsonObjectResult(
                payload={
                    "selected_key": fallback,
                    "confidence": 0.95,
                    "interpreted_intent": payload["player_text"] or "help me progress",
                },
                duration_ms=8,
            )
        return LLMJsonObjectResult(payload={"narration_text": "Echo Commit Hook"}, duration_ms=9)


def test_route_choice_chain_gateway_payload_uses_selected_key_only(monkeypatch) -> None:
    provider = _worker_provider()
    captured: dict[str, object] = {}

    async def _fake_invoke_json_object(self, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return LLMJsonObjectResult(
            payload={"selected_key": "m1", "confidence": 0.83, "interpreted_intent": "pick the second move"},
            duration_ms=12,
        )

    monkeypatch.setattr(WorkerProvider, "invoke_json_object", _fake_invoke_json_object)
    route_candidates = [
        {"key": "m0", "move_id": "move.a", "label": "A", "intents": ["a"], "synonyms": [], "is_global": False},
        {"key": "m1", "move_id": "move.b", "label": "B", "intents": ["b"], "synonyms": [], "is_global": False},
    ]
    scene_context = {
        "moves": [{"key": item["key"], "id": item["move_id"], "label": item["label"], "intents": item["intents"], "synonyms": item["synonyms"], "is_global": item["is_global"]} for item in route_candidates],
        "fallback_move": "move.a",
        "scene_seed": "seed",
        "allow_global_help": False,
        "scene_snapshot": {"scene_id": "s1"},
        "state_snapshot": {"runtime_turn": 1},
    }
    choice, duration_ms, gateway_mode = asyncio.run(RouteIntentChain(provider=provider).choose(scene_context=scene_context, route_candidates=route_candidates, text="pick second"))
    assert choice.selected_key == "m1"
    assert duration_ms == 12
    assert gateway_mode == "worker"
    payload = json.loads(captured["user_prompt"])
    assert "move_id" not in str(payload["scene_context"]["moves"])
    assert payload["scene_context"]["moves"][0]["key"] == "m0"


def test_route_choice_chain_generic_provider_maps_key() -> None:
    provider = _FakeJsonProvider()
    scene_context = {
        "moves": [{"id": "move.a", "label": "A", "intents": [], "synonyms": [], "is_global": False}],
        "fallback_move": "move.a",
        "scene_seed": "seed",
        "allow_global_help": False,
        "scene_snapshot": {},
        "state_snapshot": {},
    }
    route_candidates = [{"key": "m0", "move_id": "move.a", "label": "A", "intents": [], "synonyms": [], "is_global": False}]
    choice, _, _ = asyncio.run(RouteIntentChain(provider=provider).choose(scene_context=scene_context, route_candidates=route_candidates, text="anything"))
    assert choice.selected_key == "m0"
    assert choice.confidence == 0.95


def test_narration_chain_adapter_preserves_text_output() -> None:
    provider = _FakeJsonProvider()
    text, duration_ms, gateway_mode = asyncio.run(
        NarrationChain(provider=provider).render(
            narration_context={
                "scene_id": "s1",
                "next_scene_id": "s2",
                "interpreted_intent": "help",
                "move_label": "Help",
                "strategy_style": "steady_slow",
                "result": "success",
                "costs_summary": "none",
                "consequences_summary": "none",
                "stance_summary": "",
            },
            prompt_slots={"echo": "Echo", "commit": "Commit", "hook": "Hook"},
            style_guard="neutral",
        )
    )
    assert text == "Echo Commit Hook"
    assert duration_ms == 9
    assert gateway_mode == "unknown"
