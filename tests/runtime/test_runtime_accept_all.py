from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.pack_schema import StoryPack
from app.llm.base import LLMProvider, RouteIntentResult
from app.llm.fake_provider import FakeProvider
from app.runtime.errors import RuntimeNarrationError, RuntimeRouteError
from app.runtime.service import RuntimeService

PACK_PATH = Path("sample_data/story_pack_v1.json")


def _load_pack() -> StoryPack:
    return StoryPack.model_validate(json.loads(PACK_PATH.read_text(encoding="utf-8")))


def test_fail_forward_on_unmet_precondition() -> None:
    pack = _load_pack()
    runtime = RuntimeService(FakeProvider())
    _, _, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id="sc5",
        beat_index=1,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "button", "move_id": "decode_core"},
        dev_mode=True,
    )

    assert result["resolution"]["result"] == "fail_forward"
    assert result["resolution"]["consequences_summary"] != "none"


def test_low_confidence_text_routes_to_global_move() -> None:
    pack = _load_pack()
    runtime = RuntimeService(FakeProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "text", "text": "@@@ ???"},
    )

    assert result["recognized"]["move_id"] in {"global.help_me_progress", "global.clarify"}
    assert result["recognized"]["route_source"] == "fallback_low_confidence"


def test_accept_all_empty_text_still_progresses() -> None:
    pack = _load_pack()
    runtime = RuntimeService(FakeProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "text", "text": ""},
    )

    assert result["recognized"]["move_id"]
    assert result["scene_id"] != scene_id


class _RouteFailProvider(LLMProvider):
    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        raise RuntimeError("route failed")

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class _NarrationFailProvider(LLMProvider):
    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.9,
            interpreted_intent=text or "unclear intent",
        )

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        raise RuntimeError("narration failed")


class _StrictRouteFailProvider(_RouteFailProvider):
    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return True


class _StrictLowConfidenceProvider(LLMProvider):
    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return True

    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        fallback = scene_context.get("fallback_move", "global.help_me_progress")
        return RouteIntentResult(
            move_id=fallback,
            args={},
            confidence=0.1,
            interpreted_intent=text or "unclear intent",
        )

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class _StrictInvalidMoveProvider(LLMProvider):
    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return True

    def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
        return RouteIntentResult(
            move_id="move.not.available",
            args={},
            confidence=0.95,
            interpreted_intent=text or "invalid move intent",
        )

    def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
        return f"{slots['echo']} {slots['commit']} {slots['hook']}"


class _StrictNarrationFailProvider(_NarrationFailProvider):
    @property
    def runtime_failfast_on_narration_error(self) -> bool:
        return True


def test_route_failure_falls_back_to_global_move() -> None:
    pack = _load_pack()
    runtime = RuntimeService(_RouteFailProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "text", "text": "do something risky"},
    )

    assert result["recognized"]["move_id"] in {"global.help_me_progress", "global.clarify"}
    assert result["recognized"]["route_source"] == "fallback_error"
    assert result["resolution"]["result"] in {"success", "partial", "fail_forward"}


def test_narration_failure_uses_deterministic_template() -> None:
    pack = _load_pack()
    runtime = RuntimeService(_NarrationFailProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    result = runtime.process_step(
        pack,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state=state,
        beat_progress=beat_progress,
        action_input={"type": "text", "text": "help me progress"},
    )

    narration = result["narration_text"]
    assert narration.startswith("Echo:")
    assert "Commit:" in narration
    assert "Hook:" in narration


def test_openai_route_failure_raises_runtime_route_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(_StrictRouteFailProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeRouteError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "do something risky"},
        )

    assert exc_info.value.error_code == "llm_route_failed"
    assert exc_info.value.stage == "route"


def test_openai_low_confidence_raises_runtime_route_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(_StrictLowConfidenceProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeRouteError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "???"},
        )

    assert exc_info.value.error_code == "llm_route_low_confidence"
    assert exc_info.value.stage == "route"


def test_openai_narration_failure_raises_runtime_narration_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(_StrictNarrationFailProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeNarrationError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "help me progress"},
        )

    assert exc_info.value.error_code == "llm_narration_failed"
    assert exc_info.value.stage == "narration"


def test_openai_invalid_move_raises_runtime_route_error() -> None:
    pack = _load_pack()
    runtime = RuntimeService(_StrictInvalidMoveProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    with pytest.raises(RuntimeRouteError) as exc_info:
        runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "do a hidden action"},
        )

    assert exc_info.value.error_code == "llm_route_invalid_move"
    assert exc_info.value.stage == "route"
