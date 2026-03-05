from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.llm.base import LLMProvider, RouteIntentResult
from rpg_backend.runtime.router import route_player_action

PACK_PATH = Path("sample_data/story_pack_v1.json")


class _CaptureProvider(LLMProvider):
    def __init__(self) -> None:
        self.contexts: list[dict] = []

    async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        self.contexts.append(scene_context)
        return RouteIntentResult(
            move_id=scene_context["moves"][0]["id"],
            args={},
            confidence=0.95,
            interpreted_intent=(text or "").strip() or "fallback",
        )

    async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


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
    assert context["scene_snapshot"]["beat_progress_value"] == 1
    assert context["state_snapshot"]["last_move"] == "trace_anomaly"
    assert context["state_snapshot"]["pressure_tracks"]["coordination_noise"] == 3
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
    assert all(move["id"] != "global.help_me_progress" for move in context["moves"])


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
    assert any(move["id"] == "global.help_me_progress" for move in context["moves"])
