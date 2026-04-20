from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import rpg_backend.play_v2.runtime as runtime_module
from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.storylet_compiler import Storylet, StoryletCondition, StoryletEffect
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play.gateway import PlayLLMGateway
from rpg_backend.play_v2.runtime import build_initial_world_state, build_suggested_actions, run_turn
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
        response_id="resp_narration_live",
        usage={},
        input_characters=0,
    )


def _matching_storylet(plan: CompiledPlayPlan, *, target_id: str) -> dict[str, object]:
    current_segment = plan.segments[0]
    return Storylet(
        storylet_id="storylet_live_compose",
        narrative_function="hook",
        title="董事会暗线",
        scene_text="LIVE_STORYLET_ANCHOR_董事会议室里有人把旧账按到了桌边。",
        characters_involved=[member.character_id for member in plan.cast[:2]],
        venue_hint="董事会议室",
        dramatic_weight=0.7,
        preconditions=StoryletCondition(
            required_relationships=[target_id],
            required_segment_roles=[current_segment.segment_role],
        ),
        effects=StoryletEffect(),
    ).model_dump()


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


def test_run_turn_live_compose_prompt_contains_storylet_hints_and_memory_context(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    seeded_state = build_initial_world_state(v3_plan, session_id="narration_compose_live")
    action = next((item for item in build_suggested_actions(v3_plan, seeded_state) if item.target_id), build_suggested_actions(v3_plan, seeded_state)[0])
    target_id = action.target_id or v3_plan.cast[0].character_id
    plan = v3_plan.model_copy(
        update={"storylet_pool": [_matching_storylet(v3_plan, target_id=target_id)]},
        deep=True,
    )
    state = build_initial_world_state(plan, session_id="narration_compose_live")
    hook_id = next(iter(state.hook_states))
    state.hook_states[hook_id] = state.hook_states[hook_id].model_copy(
        update={"status": "active", "leverage_value": 0.83}
    )
    action = next((item for item in build_suggested_actions(plan, state) if item.target_id), build_suggested_actions(plan, state)[0])
    transport = MagicMock()
    transport.invoke_json.return_value = _make_response(
        {
            "narration": "她把话压进桌边那点空白里，所有人都听出了这一步的代价。",
            "coverage_marks": {
                "target": True,
                "move": True,
                "consequence": True,
                "relationship": True,
            },
            "length_profile": "normal",
        }
    )
    gateway = _make_play_gateway(transport)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda _settings: gateway)
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: type(
            "_SettingsStub",
            (),
            {
                "play_v2_dramatic_rewrite_max_output_tokens": 320,
                "play_v2_dramatic_rewrite_use_llm": True,
                "play_v2_intent_compiler_use_llm": False,
                "play_v2_micro_sim_use_llm": False,
                "internal_test_strict_no_repair_fallback": False,
            },
        )(),
    )

    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)

    assert result.narration.strip()
    assert transport.invoke_json.call_count >= 1
    kwargs = transport.invoke_json.call_args_list[0].kwargs
    assert kwargs["operation_name"] == "play_v2.narration_compose"
    system_prompt = str(kwargs["system_prompt"])
    compose_input = dict(kwargs["user_payload"]["compose_input"])
    assert "## 已选情境素材（storylet）" in system_prompt
    assert "## 当前局势（memory context）" in system_prompt
    assert "LIVE_STORYLET_ANCHOR_" in system_prompt
    assert compose_input["storylet_hints"]
    assert compose_input["memory_context"]["active_hook_summary"]
