from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from rpg_backend.llm.agents import AuthorAgent, PlayAgent


class _FakeSessionStore:
    def __init__(self) -> None:
        self.last_model: str | None = None

    async def call_with_cursor(self, *, scope_type: str, scope_id: str, channel: str, model: str, invoke):  # noqa: ANN001, ANN201, ANN003
        del scope_type, scope_id, channel
        self.last_model = model
        return await invoke(None)


def test_play_agent_forces_thinking_off() -> None:
    captured_extra_body: list[dict | None] = []

    class _FakeTransport:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured_extra_body.append(kwargs.get("extra_body"))
            return SimpleNamespace(
                response_id="resp_1",
                output_text='{"selected_key":"m0","confidence":0.9,"interpreted_intent":"help me progress"}',
                reasoning_summary="short",
                duration_ms=8,
                usage=SimpleNamespace(input_tokens=10, output_tokens=4, total_tokens=14),
                raw_payload={},
            )

    session_store = _FakeSessionStore()
    agent = PlayAgent(
        transport=_FakeTransport(),  # type: ignore[arg-type]
        session_store=session_store,  # type: ignore[arg-type]
        model="qwen-plus",
        timeout_seconds=20.0,
        enable_thinking=False,
    )

    result = asyncio.run(
        agent.interpret_turn(
            session_id="session-1",
            scene_context={"fallback_move": "global.help_me_progress"},
            route_candidates=[
                {
                    "key": "m0",
                    "move_id": "global.help_me_progress",
                    "label": "Help",
                    "intents": ["help"],
                    "synonyms": ["advance"],
                    "is_global": True,
                }
            ],
            text="help me progress",
        )
    )

    assert result.selected_key == "m0"
    assert captured_extra_body == [{"enable_thinking": False}]


def test_author_agent_overview_forces_thinking_off_and_beat_forces_on() -> None:
    captured_extra_body: list[dict | None] = []
    captured_payloads: list[dict[str, object]] = []

    class _FakeTransport:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured_extra_body.append(kwargs.get("extra_body"))
            payload = json.loads(kwargs["input"][1]["content"][0]["text"])
            captured_payloads.append(payload)
            output_text = '{"ok": true}'
            return SimpleNamespace(
                response_id="resp_1",
                output_text=output_text,
                reasoning_summary="short",
                duration_ms=8,
                usage=SimpleNamespace(input_tokens=10, output_tokens=4, total_tokens=14),
                raw_payload={},
            )

    session_store = _FakeSessionStore()
    agent = AuthorAgent(
        transport=_FakeTransport(),  # type: ignore[arg-type]
        session_store=session_store,  # type: ignore[arg-type]
        model="qwen-plus",
        timeout_seconds=20.0,
        overview_enable_thinking=False,
        beat_enable_thinking=True,
    )

    overview_result = asyncio.run(
        agent.generate_overview(
            run_id="run-1",
            raw_brief="brief",
            output_schema={"type": "object"},
        )
    )
    beat_result = asyncio.run(
        agent.generate_beat(
            run_id="run-1",
            payload={"story_id": "story-1", "output_schema": {"type": "object"}},
        )
    )

    assert overview_result.payload == {"ok": True}
    assert beat_result.payload == {"ok": True}
    assert captured_payloads[0]["task"] == "generate_overview"
    assert captured_payloads[1]["task"] == "generate_beat"
    assert captured_extra_body == [
        {"enable_thinking": False},
        {"enable_thinking": True},
    ]
