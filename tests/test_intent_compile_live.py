from __future__ import annotations

from typing import get_args
from unittest.mock import MagicMock

import pytest

import rpg_backend.play_v2.runtime as runtime_module
from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play.gateway import PlayLLMGateway
from rpg_backend.play_v2.runtime import build_initial_world_state, build_suggested_actions, parse_turn_intent
from rpg_backend.responses_transport import ResponsesJSONResponse


def _make_play_gateway(transport: MagicMock) -> PlayLLMGateway:
    gateway = PlayLLMGateway(
        client=object(),
        model="test-model",
        timeout_seconds=1.0,
        max_output_tokens_interpret=220,
        max_output_tokens_interpret_repair=220,
        max_output_tokens_ending_judge=220,
        max_output_tokens_ending_judge_repair=220,
        max_output_tokens_pyrrhic_critic=220,
        max_output_tokens_render=320,
        max_output_tokens_render_repair=320,
    )
    object.__setattr__(gateway, "_transport", transport)
    return gateway


def _make_response(payload: dict[str, object]) -> ResponsesJSONResponse:
    return ResponsesJSONResponse(
        payload=payload,
        response_id="resp_intent_live",
        usage={},
        input_characters=0,
    )


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


def test_parse_turn_intent_live_path_accepts_valid_json_payload(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    state = build_initial_world_state(v3_plan, session_id="intent_compile_live")
    suggestions = build_suggested_actions(v3_plan, state)
    selected = next((item for item in suggestions if item.target_id), suggestions[0])
    target_id = selected.target_id or v3_plan.cast[0].character_id
    transport = MagicMock()
    transport.invoke_json.return_value = _make_response(
        {
            "move_family": "probe_secret",
            "target_id": target_id,
            "scene_frame": "private",
            "lane_id": selected.lane_id,
            "intent_confidence": 0.92,
            "deviation_type": "none",
            "deviation_note": "",
            "alternatives": ["先继续试探", "换个角度追问"],
            "semantic_effects": [
                {
                    "effect_type": "secret_reveal",
                    "target_id": target_id,
                    "detail": "继续追问她手里的秘密。",
                }
            ],
        }
    )
    gateway = _make_play_gateway(transport)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: type(
            "_SettingsStub",
            (),
            {
                "play_v2_intent_compiler_use_llm": True,
                "play_v2_intent_compiler_max_output_tokens": 220,
            },
        )(),
    )

    intent = parse_turn_intent(
        v3_plan,
        state,
        "我先把她手里那张牌摸清楚。",
        gateway=gateway,
        prefetched_suggestions=tuple(suggestions),
    )

    assert intent.move_family in set(get_args(RelationshipMoveFamily))
    assert intent.move_family == "probe_secret"
    assert intent.intent_compile_source == "llm"
    assert intent.target_id == target_id
    transport.invoke_json.assert_called_once()
    assert transport.invoke_json.call_args.kwargs["operation_name"] == "play_v2.intent_compile"
