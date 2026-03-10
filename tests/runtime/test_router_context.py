from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.llm.base import LLMJsonObjectResult, LLMProvider
from rpg_backend.runtime.router import route_player_action

PACK_PATH = Path("sample_data/story_pack_v1.json")


class _CaptureProvider(LLMProvider):
    gateway_mode = "fake"
    route_model = "route-model"
    narration_model = "narration-model"
    timeout_seconds = 20.0
    route_max_retries = 3
    narration_max_retries = 1
    route_temperature = 0.1
    narration_temperature = 0.4

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    async def invoke_json_object(self, **kwargs) -> LLMJsonObjectResult:  # noqa: ANN003
        payload = json.loads(kwargs["user_prompt"])
        if payload.get("task") == "select_route_candidate":
            self.contexts.append(payload["scene_context"])
            return LLMJsonObjectResult(
                payload={
                    "selected_key": payload["scene_context"]["moves"][0]["key"],
                    "confidence": 0.95,
                    "interpreted_intent": (payload.get("player_text") or "").strip() or "fallback",
                },
                duration_ms=5,
            )
        return LLMJsonObjectResult(payload={"narration_text": "x"}, duration_ms=5)


def _load_pack() -> StoryPack:
    return StoryPack.model_validate(json.loads(PACK_PATH.read_text(encoding="utf-8")))


def test_route_context_includes_rich_snapshot_fields() -> None:
    pack = _load_pack()
    scene = pack.scenes[0]
    beat = pack.beats[0]
    move_map = {move.id: move for move in pack.moves}
    provider = _CaptureProvider()

    _ = asyncio.run(
        route_player_action(
            provider,
            scene,
            move_map,
            {"type": "text", "text": "trace the source and keep trust stable"},
            state={
                "events": ["b1.root_cause_locked", "redline_hit::Kael"],
                "values": {
                    "last_move": "trace_anomaly",
                    "public_trust": -2,
                    "resource_stress": 1,
                    "coordination_noise": 3,
                    "time_spent": 2,
                    "runtime_turn": 5,
                    "cost_total": 4,
                },
            },
            beat_progress={scene.beat_id: 1},
            beat=beat,
            beat_index=0,
        )
    )

    assert provider.contexts
    context = provider.contexts[0]
    assert context["scene_snapshot"]["scene_id"] == scene.id
    assert context["scene_snapshot"]["beat_title"] == beat.title
    assert context["state_snapshot"]["runtime_turn"] == 5
    assert context["state_snapshot"]["recent_events_tail"][-1] == "redline_hit::Kael"


def test_route_context_excludes_global_help_for_non_help_text() -> None:
    pack = _load_pack()
    scene = pack.scenes[0]
    move_map = {move.id: move for move in pack.moves}
    provider = _CaptureProvider()

    _ = asyncio.run(
        route_player_action(
            provider,
            scene,
            move_map,
            {"type": "text", "text": "stabilize corridor and reduce noise"},
        )
    )

    context = provider.contexts[0]
    assert context["allow_global_help"] is False
    assert all(not (move["is_global"] and move["label"] == "Help Me Progress") for move in context["moves"])


def test_route_context_allows_global_help_for_help_text() -> None:
    pack = _load_pack()
    scene = pack.scenes[0]
    move_map = {move.id: move for move in pack.moves}
    provider = _CaptureProvider()

    _ = asyncio.run(
        route_player_action(
            provider,
            scene,
            move_map,
            {"type": "text", "text": "help I am stuck what now"},
        )
    )

    context = provider.contexts[0]
    assert context["allow_global_help"] is True
    assert any(move["is_global"] for move in context["moves"])
