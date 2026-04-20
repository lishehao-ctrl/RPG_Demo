from __future__ import annotations

from functools import lru_cache

import pytest

import rpg_backend.play_v2.runtime as runtime_module
from rpg_backend.author.contracts import (
    AffordanceEffectProfile,
    AffordanceWeight,
    AxisDefinition,
    BeatSpec,
    CastMember,
    ConditionBlock,
    EndingItem,
    EndingRule,
    TruthItem,
)
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play.closeout_judge import judge_ending_intent
from rpg_backend.play.contracts import PlayPlan, PlayProtagonist, PlayResolutionEffect
from rpg_backend.play.runtime import PlaySessionState, TurnEndingGateContext
from rpg_backend.play_v2.runtime import build_initial_world_state, build_suggested_actions, run_turn


@lru_cache(maxsize=1)
def _cached_v2_plan():
    return run_author_v3_pipeline("office board power", run_mode="deterministic")["plan"]


def _v2_plan():
    return _cached_v2_plan().model_copy(deep=True)


def _v2_settings_stub(**overrides):
    values = {
        "play_v2_intent_compiler_use_llm": False,
        "play_v2_intent_compiler_max_output_tokens": 220,
        "play_v2_dramatic_rewrite_use_llm": False,
        "play_v2_dramatic_rewrite_max_output_tokens": 320,
        "play_v2_micro_sim_use_llm": False,
        "internal_test_strict_no_repair_fallback": False,
    }
    values.update(overrides)
    return type("_SettingsStub", (), values)()


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        response_id: str,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.payload = payload
        self.response_id = response_id
        self.usage = usage or {
            "input_tokens": 42,
            "output_tokens": 18,
            "total_tokens": 60,
        }


class _QueuedTransport:
    def __init__(self, queued_payloads: list[dict[str, object]]) -> None:
        self.queued_payloads = list(queued_payloads)
        self.calls: list[dict[str, object]] = []
        self.max_output_tokens_interpret_repair = 320
        self.max_output_tokens_ending_judge = 80
        self.max_output_tokens_ending_judge_repair = 60
        self.max_output_tokens_pyrrhic_critic = 60

    def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
        self.calls.append(dict(kwargs))
        payload = self.queued_payloads.pop(0)
        return _FakeResponse(payload, response_id=f"resp-{len(self.calls)}")


def _closeout_plan() -> PlayPlan:
    cast = [
        CastMember(
            npc_id="lin",
            name="林蔓",
            role="对手",
            agenda="逼你当众选边。",
            red_line="不能再让秘密继续埋着。",
            pressure_signature="越冷静越危险。",
        ),
        CastMember(
            npc_id="gu",
            name="顾承野",
            role="盟友",
            agenda="守住体面和控制权。",
            red_line="不能公开失控。",
            pressure_signature="越失位越想控场。",
        ),
        CastMember(
            npc_id="xu",
            name="许知遥",
            role="证人",
            agenda="保住证据链。",
            red_line="不能让文件被偷换。",
            pressure_signature="总在最后一页补刀。",
        ),
    ]
    return PlayPlan(
        story_id="closeout_live_case",
        story_mode="relationship_drama",
        story_title="结局判定压测",
        protagonist=PlayProtagonist(
            title="卷入豪门局的主角",
            mandate="先活着走出这间厅。",
            identity_summary="你手里有能让所有人翻脸的证据。",
        ),
        protagonist_name="沈知微",
        closeout_profile="legacy_civic_placeholder",
        closeout_router_reason="relationship_drama_transition",
        runtime_policy_profile="legacy_civic_placeholder",
        runtime_router_reason="relationship_drama_transition",
        premise="订婚宴在证据曝光后逼近失控。",
        tone="轻奢都市抓马",
        style_guard="先写关系代价，再写制度背景。",
        cast=cast,
        truths=[TruthItem(truth_id="video", text="偷拍视频能改写站队。")],
        endings=[
            EndingItem(ending_id="collapse", label="失控崩盘", summary="所有体面一起炸开。"),
            EndingItem(ending_id="pyrrhic", label="带血成局", summary="局面稳住了，但代价已经写在脸上。"),
            EndingItem(ending_id="mixed", label="勉强收束", summary="局面收住，却没人真正赢。"),
        ],
        axes=[
            AxisDefinition(axis_id="pressure", label="Pressure", kind="pressure", max_value=5),
            AxisDefinition(axis_id="exposure", label="Exposure", kind="exposure", max_value=5),
        ],
        stances=[],
        flags=[],
        beats=[
            BeatSpec(
                beat_id="finale",
                title="宴会落锤",
                goal="判断这一拍是崩盘、带血成局，还是勉强收束。",
                return_hooks=["所有人都在等最后一句。"],
                affordances=[
                    AffordanceWeight(tag="reveal_truth", weight=2),
                    AffordanceWeight(tag="build_trust", weight=1),
                ],
                phase="lock",
                focus_npcs=["lin"],
                conflict_npcs=["gu"],
            )
        ],
        route_unlock_rules=[],
        ending_rules=[EndingRule(ending_id="mixed", conditions=ConditionBlock())],
        affordance_effect_profiles=[
            AffordanceEffectProfile(affordance_tag="reveal_truth", default_story_function="reveal"),
            AffordanceEffectProfile(affordance_tag="build_trust", default_story_function="advance"),
        ],
        available_affordance_tags=["reveal_truth", "build_trust"],
        max_turns=5,
        opening_narration="大厅里没有一个人真准备好收场。",
        relationship_hook="你知道谁在说谎，但公开代价会先落在你身上。",
        secret_hook="证据一旦亮出，就没有人能装作没看见。",
        route_target_ids=["lin", "gu", "xu"],
    )


def test_live_llm_intent_compile_retries_after_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _v2_plan()
    state = build_initial_world_state(plan, session_id="live_intent_compile_case")
    suggestions = build_suggested_actions(plan, state)
    expected = suggestions[0]
    gateway = _QueuedTransport(
        [
            {"move_family": "not_allowed", "intent_confidence": 0.8},
            {
                "move_family": expected.move_family,
                "target_id": expected.target_id,
                "scene_frame": expected.scene_frame,
                "lane_id": expected.lane_id,
                "intent_confidence": 0.78,
                "deviation_type": "none",
                "alternatives": [expected.label],
                "semantic_effects": [
                    {
                        "effect_type": "trust_action",
                        "target_id": expected.target_id or "",
                        "detail": "先稳住场面再推进下一句。",
                    }
                ],
            },
        ]
    )
    diagnostics: dict[str, object] = {}

    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: _v2_settings_stub(
            play_v2_intent_compiler_use_llm=True,
            play_v2_intent_compiler_max_output_tokens=220,
        ),
    )

    candidate = runtime_module._try_compile_with_llm(
        plan,
        state,
        "我先稳住她，再把真正的账翻出来。",
        suggestions,
        gateway=gateway,
        diagnostics=diagnostics,
    )

    assert candidate is not None
    assert candidate.compile_source == "llm"
    assert candidate.move_family == expected.move_family
    assert diagnostics["intent_llm_status"] == "completed_retry"
    assert int(diagnostics["intent_llm_retry_count"]) == 1
    assert int(diagnostics["intent_llm_attempts"]) == 2
    assert [str(call.get("operation_name") or "") for call in gateway.calls] == [
        "play_v2.intent_compile",
        "play_v2.intent_compile_repair",
    ]
    assert gateway.calls[1]["user_payload"]["retry_feedback"] == "invalid_move_family"
    assert gateway.calls[1]["previous_response_id"] == "resp-1"


def test_live_llm_compose_retries_after_schema_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _v2_plan()
    state = build_initial_world_state(plan, session_id="live_compose_case")
    action = build_suggested_actions(plan, state)[0]
    gateway = _QueuedTransport(
        [
            {"coverage_marks": {"target": True, "move": True, "consequence": True, "relationship": True}},
            {
                "narration": "她先把话按住，逼那张桌子上的每个人都重新站位。",
                "coverage_marks": {
                    "target": True,
                    "move": True,
                    "consequence": True,
                    "relationship": True,
                },
                "length_profile": "normal",
            },
        ]
    )

    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda _settings: gateway)
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: _v2_settings_stub(
            play_v2_dramatic_rewrite_use_llm=True,
            play_v2_dramatic_rewrite_max_output_tokens=320,
        ),
    )

    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)

    assert "重新站位" in result.narration
    assert int(result.intent_stage_diagnostics["compose_retry_count"]) == 1
    assert result.intent_stage_diagnostics["narration_compose_source"] == "llm_retry"
    assert [str(call.get("operation_name") or "") for call in gateway.calls] == [
        "play_v2.narration_compose",
        "play_v2.narration_compose",
    ]
    assert gateway.calls[1]["user_payload"]["retry_mode"] is True


def test_live_llm_ending_judge_repairs_invalid_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    plan = _closeout_plan()
    state = PlaySessionState(
        session_id="closeout_live_case",
        story_id=plan.story_id,
        status="active",
        turn_index=4,
        beat_index=0,
        beat_progress=2,
        beat_detours_used=0,
        axis_values={"pressure": 4, "exposure": 3},
        stance_values={},
        flag_values={},
        discovered_truth_ids=["video"],
        success_ledger={"proof_progress": 2, "coalition_progress": 0},
        cost_ledger={"public_cost": 2, "relationship_cost": 1},
        last_turn_axis_deltas={"pressure": 1},
        last_turn_stance_deltas={},
        last_turn_tags=["live_llm_test"],
        last_turn_consequences=["你把最不该公开的东西拖上了台面。"],
    )
    resolution = PlayResolutionEffect(
        affordance_tag="reveal_truth",
        risk_level="high",
        execution_frame="public",
        target_npc_ids=["lin"],
        tactic_summary="你当众揭开偷拍视频的来路。",
        pressure_note="这一步稳住了局，但代价已经写在现场表情里。",
    )
    gateway = _QueuedTransport(
        [
            {"ending": "pyrrhic"},
            {"ending_id": "pyrrhic"},
        ]
    )

    result = judge_ending_intent(
        plan=plan,
        state=state,
        resolution=resolution,
        ending_context=TurnEndingGateContext(final_beat_completed=True, final_beat_handoff=False),
        input_text="我把视频直接投到大屏上。",
        selected_action=None,
        gateway=gateway,
        previous_response_id="base-response",
        enable_ending_intent_judge=True,
    )

    assert result.proposed_ending_id == "pyrrhic"
    assert result.source == "llm"
    assert result.attempts == 2
    assert result.failure_reason == "play_ending_judge_schema_invalid"
    assert [str(call.get("operation_name") or "") for call in gateway.calls] == [
        "play_ending_intent_judge",
        "play_ending_intent_judge_repair",
    ]
    assert gateway.calls[1]["previous_response_id"] == "base-response"
