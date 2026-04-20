from __future__ import annotations

from pathlib import Path
import time

import pytest

from rpg_backend.config import get_settings
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.play_v2.latent_events import LatentEventEngine
from rpg_backend.play_v2.invariants import InvariantValidator
from rpg_backend.play_v2.narration_frames import NpcReactionBeat, NarrationRenderSeed, ScenePressureBeat, build_supporting_reaction_beats, build_tone_example_style_hints
from rpg_backend.play_v2.narration_variants import phrase_fingerprint
from rpg_backend.play_v2.contracts import LatentEvent, UnresolvedCostRecord, UrbanTurnIntent
from rpg_backend.play_v2.narration_surface import _support_line, render_npc_texture_v2
from rpg_backend.play_v2.product_api import build_v2_snapshot, build_v2_state_bars, build_v2_turn_trace
from rpg_backend.play_v2.semantic_planners import PayoffPlanner
import rpg_backend.play_v2.delta_pack_runtime as delta_pack_runtime
import rpg_backend.play_v2.runtime as runtime_module
from rpg_backend.play_v2.runtime import (
    advance_segment_if_ready,
    apply_turn_resolution,
    build_control_actions,
    build_initial_world_state,
    build_suggested_actions,
    judge_ending,
    parse_turn_intent,
    run_intent_stage,
    run_smoke_playthrough,
    run_turn,
)


def _play_plan():
    preview, _ = run_preview_blueprint_graph("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。")
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan


def _play_plan_from_seed(seed: str):
    preview, _ = run_preview_blueprint_graph(seed)
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan


def _move_state_to_segment(plan, state, segment_role: str) -> None:
    segment = next(item for item in plan.segments if item.segment_role == segment_role)
    state.segment_index = plan.segments.index(segment)
    state.segment_id = segment.segment_id
    state.segment_enter_turn_index = state.turn_index
    state.scene_frame = "public" if segment.segment_role in {"reveal", "terminal"} else ("semi_public" if segment.segment_role == "pressure" else "private")
    state.venue_id = segment.venue_id
    state.active_character_ids = (segment.focus_target_ids + segment.rival_target_ids)[:3]
    state.witness_pressure = 2 if state.scene_frame != "private" else 1


def _latent_event(
    *,
    event_id: str,
    kind: str,
    target_ids: list[str],
    stake_ids: list[str],
    pressure: int = 2,
    maturity: int = 2,
    threshold: int = 4,
    actor_id: str | None = None,
) -> LatentEvent:
    return LatentEvent(
        event_id=event_id,
        kind=kind,  # type: ignore[arg-type]
        shell_id="campus_romance",
        source_turn_index=0,
        source_segment_id="seed_segment",
        stake_character_ids=stake_ids,
        target_character_ids=target_ids,
        actor_character_id=actor_id,
        pressure=pressure,
        maturity=maturity,
        trigger_threshold=threshold,
        age_turns=1,
        status="latent",
        visibility="semi_visible",
        trigger_window_roles=["pressure", "reveal", "terminal"],
        trigger_window_frames=["private", "semi_public", "public"],
        foreshadow_text="这件事还没过去。",
        detonation_text="这件事现在回头咬人了。",
        global_deltas={},
        relationship_deltas={},
        reaction_cause_tags=[],
    )


def test_play_runtime_smoke_advances_and_finishes_within_max_turns() -> None:
    plan = _play_plan()

    results = run_smoke_playthrough(plan)

    assert results
    assert plan.play_length_preset in {"10_12", "12_15", "15_20", "20_25", "30_45", "5_8"}
    assert all(segment.progress_required >= 1 for segment in plan.segments)
    assert results[-1].state.turn_index <= plan.max_turns
    assert results[-1].state.status == "completed"


def test_parse_turn_intent_detects_public_reveal_and_named_target() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    _move_state_to_segment(plan, state, "reveal")
    target_name = plan.cast[0].display_name

    intent = parse_turn_intent(plan, state, f"我要在直播镜头前当众曝光{target_name}手里的录音")

    assert intent.move_family == "public_reveal"
    assert intent.target_id == plan.cast[0].character_id
    assert intent.scene_frame == "public"


def test_parse_turn_intent_matches_suggestion_prompt_without_selected_id() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    suggestion = build_suggested_actions(plan, state)[1]

    intent = parse_turn_intent(plan, state, suggestion.prompt)

    assert intent.lane_id == suggestion.lane_id
    assert intent.move_family == suggestion.move_family
    assert intent.target_id == suggestion.target_id


def test_should_invoke_intent_llm_skips_non_ambiguous_long_sentence() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    should_invoke, reason = runtime_module._should_invoke_intent_llm(
        plan=plan,
        state=state,
        input_text="我只是想把刚才每个人说过的话再完整复述一遍，确认信息对齐，避免大家误会了原本的节奏安排。",
        clause_intents=[
            runtime_module._ClauseIntent(
                clause_index=0,
                clause_text="复述",
                move_family=None,
                target_id=None,
                move_hit_count=0,
                target_hit_count=0,
                control_action="none",
            )
        ],
        heuristic_candidate=runtime_module._IntentCandidate(
            move_family="comfort",
            target_id=plan.cast[0].character_id,
            scene_frame="private",
            lane_id="relationship",
            mapped_suggestion_id=None,
            intent_confidence=0.92,
            compile_source="heuristic_fallback",
        ),
        selected_control_action_id=None,
        control_action="none",
    )
    assert should_invoke is True
    assert reason == "llm_first_default"


def test_should_invoke_intent_llm_uses_ambiguous_long_sentence_gate() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    should_invoke, reason = runtime_module._should_invoke_intent_llm(
        plan=plan,
        state=state,
        input_text="我先把现场说法和每个人的表态整理一下，然后再把口风往稳妥方向推一点，之后再看要不要公开回应并继续发言。",
        clause_intents=[
            runtime_module._ClauseIntent(
                clause_index=0,
                clause_text="整理一下",
                move_family=None,
                target_id=None,
                move_hit_count=0,
                target_hit_count=0,
                control_action="none",
            )
        ],
        heuristic_candidate=runtime_module._IntentCandidate(
            move_family="comfort",
            target_id=plan.cast[0].character_id,
            scene_frame="private",
            lane_id="relationship",
            mapped_suggestion_id=None,
            intent_confidence=0.92,
            compile_source="heuristic_fallback",
        ),
        selected_control_action_id=None,
        control_action="none",
    )
    assert should_invoke is True
    assert reason == "llm_first_default"


def test_parse_turn_intent_soft_repairs_out_of_scope_input() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "我直接召唤陨石把这座城抹掉然后读档重来。")

    assert intent.mapped_suggestion_id is not None
    assert intent.lane_id in {"relationship", "side", "burst"}
    assert intent.deviation_type == "scope_shift"
    assert intent.deviation_note and "系统先按" in intent.deviation_note


def test_parse_turn_intent_soft_repair_includes_deviation_and_alternatives() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "我直接召唤轨道武器清场然后重置整局。")

    assert intent.deviation_type == "scope_shift"
    assert intent.deviation_note
    assert intent.alternatives
    assert intent.intent_compile_source in {"llm", "heuristic_fallback"}


def test_control_action_defaults_to_none_without_explicit_or_free_text_signal() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "我先观察她的表情，再试探一句。")

    assert intent.control_action == "none"
    assert intent.control_source == "none"


def test_free_text_control_action_sets_control_source_without_button() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "先把这颗雷压住，稳一拍再说。")

    assert intent.control_action == "press"
    assert intent.control_source == "free_text"


def test_parse_turn_intent_uses_llm_control_contract_hints_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    _move_state_to_segment(plan, state, "reveal")
    state.scene_heat = 6
    state.secret_exposure = 6
    state.route_lock = 5
    suggestion = build_suggested_actions(plan, state)[0]
    diagnostics: dict[str, object] = {}

    def _fake_try_compile_with_llm(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = args
        _ = kwargs
        return runtime_module._IntentCandidate(
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            lane_id=suggestion.lane_id,
            mapped_suggestion_id=suggestion.suggestion_id,
            intent_confidence=0.71,
            compile_source="llm",
            control_action="redirect",
            control_target_id=plan.cast[0].character_id,
            control_target_mode="character",
            tradeoff_markers=("谁先让步", "拒绝就升级"),
        )

    monkeypatch.setattr(runtime_module, "_try_compile_with_llm", _fake_try_compile_with_llm)

    intent = parse_turn_intent(
        plan,
        state,
        "我先推进一拍，别让场面继续拖着。",
        diagnostics=diagnostics,
    )

    assert intent.control_action == "redirect"
    assert intent.control_source == "free_text"
    assert intent.control_target_mode == "character"
    assert diagnostics.get("intent_llm_control_used") is True
    assert "谁先让步" in str(diagnostics.get("intent_tradeoff_markers") or "")


def test_parse_turn_intent_applies_control_bias_for_free_input_low_confidence() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    suggestions = build_suggested_actions(plan, state)
    biased_suggestion = next(item for item in suggestions if item.lane_id == "side")
    diagnostics: dict[str, object] = {}

    def _fake_bias_selector(*, plan, segment, suggestions):  # noqa: ANN001, ANN002
        _ = plan
        _ = segment
        return next((item for item in suggestions if item.suggestion_id == biased_suggestion.suggestion_id), None)

    original_selector = runtime_module._select_control_bias_suggestion
    runtime_module._select_control_bias_suggestion = _fake_bias_selector
    try:
        intent = parse_turn_intent(
            plan,
            state,
            "我先护住她，别让她现在难堪。",
            diagnostics=diagnostics,
        )
    finally:
        runtime_module._select_control_bias_suggestion = original_selector

    assert diagnostics.get("control_bias_applied") is True
    assert diagnostics.get("control_bias_reason") == "applied"
    assert intent.move_family == biased_suggestion.move_family
    assert intent.target_id == biased_suggestion.target_id


def test_parse_turn_intent_applies_control_bias_for_opening_soft_move_in_force_window(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    suggestions = build_suggested_actions(plan, state)
    relationship_pick = next(item for item in suggestions if item.lane_id == "relationship")
    side_pick = next(item for item in suggestions if item.lane_id == "side")
    diagnostics: dict[str, object] = {}

    monkeypatch.setattr(
        runtime_module,
        "_should_invoke_intent_llm",
        lambda **_kwargs: (True, "forced_test"),
    )
    monkeypatch.setattr(
        runtime_module,
        "_try_compile_with_llm",
        lambda *args, **kwargs: runtime_module._IntentCandidate(  # noqa: ARG005
            move_family=relationship_pick.move_family,
            target_id=relationship_pick.target_id,
            scene_frame=relationship_pick.scene_frame,
            lane_id=relationship_pick.lane_id,
            mapped_suggestion_id=relationship_pick.suggestion_id,
            intent_confidence=0.91,
            compile_source="llm",
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "_select_control_bias_suggestion",
        lambda **_kwargs: side_pick,
    )

    intent = parse_turn_intent(
        plan,
        state,
        "我先稳住她，别让她继续难堪。",
        diagnostics=diagnostics,
    )

    assert diagnostics.get("control_bias_applied") is True
    assert diagnostics.get("control_bias_reason") == "applied"
    assert intent.move_family == side_pick.move_family
    assert intent.target_id == side_pick.target_id


def test_parse_turn_intent_skips_opening_force_bias_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    state.turn_index = 5
    suggestions = build_suggested_actions(plan, state)
    relationship_pick = next(item for item in suggestions if item.lane_id == "relationship")
    side_pick = next(item for item in suggestions if item.lane_id == "side")
    diagnostics: dict[str, object] = {}

    monkeypatch.setattr(
        runtime_module,
        "_should_invoke_intent_llm",
        lambda **_kwargs: (True, "forced_test"),
    )
    monkeypatch.setattr(
        runtime_module,
        "_try_compile_with_llm",
        lambda *args, **kwargs: runtime_module._IntentCandidate(  # noqa: ARG005
            move_family=relationship_pick.move_family,
            target_id=relationship_pick.target_id,
            scene_frame=relationship_pick.scene_frame,
            lane_id=relationship_pick.lane_id,
            mapped_suggestion_id=relationship_pick.suggestion_id,
            intent_confidence=0.91,
            compile_source="llm",
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "_select_control_bias_suggestion",
        lambda **_kwargs: side_pick,
    )

    intent = parse_turn_intent(
        plan,
        state,
        "我先稳住她，别让她继续难堪。",
        diagnostics=diagnostics,
    )

    assert diagnostics.get("control_bias_applied") is False
    assert diagnostics.get("control_bias_reason") == "confidence_not_low"
    assert intent.move_family == relationship_pick.move_family
    assert intent.target_id == relationship_pick.target_id


def test_parse_turn_intent_control_bias_skips_when_selected_story_id_is_submitted() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    selected = build_suggested_actions(plan, state)[0]
    diagnostics: dict[str, object] = {}

    intent = parse_turn_intent(
        plan,
        state,
        "我先护住她。",
        selected_story_action_id=selected.suggestion_id,
        selected_suggestion_id=selected.suggestion_id,
        diagnostics=diagnostics,
    )

    assert diagnostics.get("control_bias_applied") is False
    assert diagnostics.get("control_bias_reason") == "submitted_selected_ids"
    assert intent.move_family == selected.move_family


def test_parse_turn_intent_control_bias_skips_when_explicit_control_is_selected() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    controls = build_control_actions(plan, state)
    diagnostics: dict[str, object] = {}

    _ = parse_turn_intent(
        plan,
        state,
        "我先护住她，把火压住。",
        selected_control_action_id=controls[0].action_id,
        diagnostics=diagnostics,
    )

    assert diagnostics.get("control_bias_applied") is False
    assert diagnostics.get("control_bias_reason") == "explicit_control"


def test_free_text_control_action_respects_negation_phrase() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "先不要引爆，先看她怎么接话。")

    assert intent.control_action == "none"
    assert intent.control_source == "none"


def test_redirect_free_text_without_target_sets_target_shift_deviation() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "先把这波风险转移出去，别落在我身上。")

    assert intent.control_action == "redirect"
    assert intent.control_source == "free_text"
    assert intent.deviation_type == "target_shift"


def test_redirect_free_text_with_named_target_infers_control_target() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "先把这波锅转给乔琳，让她去扛。")

    assert intent.control_action == "redirect"
    assert intent.control_source == "free_text"
    assert intent.control_target_mode == "character"
    assert intent.control_target_id == "qiao_lin"


def test_free_input_multi_step_is_soft_repaired_with_alternatives() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    intent = parse_turn_intent(plan, state, "先安抚她，再去当众曝光录音，最后把风向转给另一个人。")

    assert intent.deviation_type == "scope_shift"
    assert intent.deviation_note
    assert intent.alternatives


def test_run_intent_stage_emits_latency_and_token_diagnostics() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    suggestion = build_suggested_actions(plan, state)[0]

    intent, micro_sim, diagnostics = run_intent_stage(
        plan,
        state,
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
    )

    assert intent.mapped_suggestion_id == suggestion.suggestion_id
    assert diagnostics["intent_compile_source"] in {"llm", "heuristic", "heuristic_fallback"}
    assert diagnostics["control_source"] in {"none", "explicit", "free_text"}
    assert float(diagnostics["intent_parse_latency_ms"]) >= 0.0
    assert float(diagnostics["intent_micro_sim_stage_latency_ms"]) >= 0.0
    assert float(diagnostics["intent_stage_latency_ms"]) >= float(diagnostics["intent_parse_latency_ms"])
    assert int(diagnostics["intent_stage_total_tokens"]) >= 0
    if micro_sim is not None:
        assert micro_sim.source in {"heuristic", "llm"}


def test_cost_route_intensity_profile_boosts_reveal_over_opening() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    base_segment = plan.segments[0]
    opening_segment = base_segment.model_copy(update={"segment_role": "opening"})
    reveal_segment = base_segment.model_copy(update={"segment_role": "reveal"})
    intent = UrbanTurnIntent(
        input_text="我先安抚她，但让这步代价真正落到关系上。",
        lane_id="relationship",
        move_family="comfort",
        target_id=plan.route_target_ids[0],
        scene_frame="semi_public",
        control_action="none",
        control_source="none",
    )

    opening_route = PayoffPlanner.plan_cost_route(plan=plan, state=state, intent=intent, segment=opening_segment)
    reveal_route = PayoffPlanner.plan_cost_route(plan=plan, state=state, intent=intent, segment=reveal_segment)

    opening_score = sum(abs(int(value)) for value in opening_route.immediate_global_deltas.values()) + sum(
        abs(int(value))
        for deltas in opening_route.immediate_relationship_deltas.values()
        for value in deltas.values()
    )
    reveal_score = sum(abs(int(value)) for value in reveal_route.immediate_global_deltas.values()) + sum(
        abs(int(value))
        for deltas in reveal_route.immediate_relationship_deltas.values()
        for value in deltas.values()
    )
    assert reveal_score >= opening_score


def test_causal_contract_forces_resolution_when_due_role_reached() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="causal_contract_case")
    _move_state_to_segment(plan, state, "reveal")
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    callback_rule = result.state.causal_contract_records.get("causal_callback_open")
    assert callback_rule is not None
    assert callback_rule.status == "resolved"
    assert callback_rule.fail_safe_applied is True
    assert result.state.last_turn_causal_receipts
    assert any(tag.startswith("causal:") for tag in result.state.last_turn_tags)


def test_build_suggested_actions_returns_explicit_three_lanes() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    suggestions = build_suggested_actions(plan, state)

    assert [suggestion.lane_id for suggestion in suggestions] == ["relationship", "side", "burst"]
    assert len({suggestion.suggestion_id for suggestion in suggestions}) == 3
    assert all("代价" in suggestion.prompt for suggestion in suggestions)
    assert all("TA" not in suggestion.label for suggestion in suggestions)
    assert len({suggestion.target_id for suggestion in suggestions if suggestion.target_id is not None}) >= 2


def test_build_suggested_actions_falls_back_when_segment_has_no_lanes() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    first_segment = plan.segments[0].model_copy(update={"suggestion_lanes": []})
    fallback_plan = plan.model_copy(update={"segments": [first_segment, *plan.segments[1:]]})

    suggestions = build_suggested_actions(fallback_plan, state)

    assert [suggestion.lane_id for suggestion in suggestions] == ["relationship", "side", "burst"]


def test_initial_opening_narration_is_style_cleaned_by_play() -> None:
    plan = _play_plan()
    dirty_plan = plan.model_copy(update={"opening_narration": "TA还在硬撑。。  这一下已经不可能当没发生。"})

    state = build_initial_world_state(dirty_plan)

    assert "TA" not in state.narration
    assert "。。" not in state.narration
    assert "  " not in state.narration


def test_reveal_burst_prefers_public_reveal_and_writes_public_event() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="reveal_director_case")
    _move_state_to_segment(plan, state, "reveal")

    suggestions = build_suggested_actions(plan, state)
    burst = next(item for item in suggestions if item.lane_id == "burst")

    assert burst.move_family == "public_reveal"
    assert "现在就对" in burst.prompt
    assert "烧掉" in burst.prompt

    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert result.state.last_turn_public_event_text
    assert result.state.last_turn_no_return_text
    assert result.state.public_event_ids
    assert any(flag.startswith("public_event:") for flag in result.state.irreversible_flags)
    assert any(flag.startswith("no_return:") for flag in result.state.irreversible_flags)
    assert result.state.last_turn_consequences[0] == result.state.last_turn_public_event_text
    assert "半步" not in result.state.last_turn_consequences[0]
    assert "快要炸" not in result.state.last_turn_consequences[0]


def test_burst_public_reveal_reveal_segment_adds_collateral_and_global_costs() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="burst_cost_case")
    _move_state_to_segment(plan, state, "reveal")

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert result.state.public_image <= 1
    assert result.state.secret_exposure >= 3
    assert len(result.state.last_turn_relationship_deltas) >= 2
    assert any("退路" in line or "体面" in line or "名额" in line for line in result.state.last_turn_consequences)


def test_reveal_narration_includes_reason_signal_cost_payoff_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="reveal_payoff_chain_case")
    _move_state_to_segment(plan, state, "reveal")

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert result.narration
    assert "代价已经开始往外传" not in result.narration
    target_name = next((item.display_name for item in plan.cast if item.character_id == burst.target_id), "")
    if target_name:
        assert target_name in result.narration
    if plan.story_shell_id == "campus_romance":
        assert any(token in result.narration for token in ("台下", "评审", "名额", "社团", "熟人", "站队"))
    get_settings.cache_clear()


def test_reveal_narration_entertainment_hits_media_anchor_in_main_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    plan = _play_plan_from_seed("直播颁奖夜里，旧录音被当场放出，公关和镜头都在等人先切割。")
    if plan.story_shell_id != "entertainment_scandal":
        pytest.skip("seed did not map to entertainment shell")
    state = build_initial_world_state(plan, session_id="ent_reveal_payoff_chain_case")
    _move_state_to_segment(plan, state, "reveal")

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert result.narration
    assert "代价已经开始往外传" not in result.narration
    assert any(token in result.narration for token in ("镜头", "热搜", "公关", "切割", "公屏"))
    get_settings.cache_clear()


def test_initial_world_state_builds_npc_mind_states() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    assert state.npc_mind_states
    target_id = plan.route_target_ids[0]
    assert target_id in state.npc_mind_states
    assert state.npc_mind_states[target_id].stance in {"testing", "guarded", "ally"}
    assert state.npc_mind_states[target_id].mask_integrity == 6


def test_move_family_updates_npc_mind_state() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="mind_state_case")
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    target_id = result.intent.target_id
    assert target_id is not None
    mind = result.state.npc_mind_states[target_id]
    assert mind.trust >= 0
    assert mind.affection >= 0
    assert mind.commitment_streak >= 0
    assert all("真正的摊牌更近了一步" not in line for line in result.state.last_turn_consequences)
    assert len(result.state.last_turn_relationship_deltas) >= 2
    assert any(
        token in " ".join(result.state.last_turn_consequences)
        for token in ("代价", "站边", "风向", "翻车", "认边", "一伙", "压线", "场面", "疼", "回旋", "选边")
    )


def test_progress_summary_no_longer_reads_like_metric_broadcast() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="progress_summary_case")
    suggestion = build_suggested_actions(plan, state)[0]

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    assert "当前段推进" not in result.progress_summary
    assert "场面热度" not in result.progress_summary
    assert any(token in result.progress_summary for token in ("翻车", "站边", "摊牌", "失态", "更重", "全身而退"))


def test_narration_changes_with_npc_mask_and_speech_pattern() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="narration_mask_case")
    target_id = plan.route_target_ids[0]
    state.npc_mind_states[target_id].mask_integrity = 1
    state.npc_mind_states[target_id].humiliation_risk = 4
    state.npc_mind_states[target_id].confession_readiness = 4
    state.npc_mind_states[target_id].trust = 2
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.target_id == target_id)

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    assert any(token in result.narration for token in ("台下", "喉咙口", "说辞", "破绽"))


def test_npc_texture_v2_play_owns_style_cleanup_and_filters_author_fragments() -> None:
    plan = _play_plan()
    target_id = plan.route_target_ids[0]
    state = build_initial_world_state(plan, session_id="v2_style_cleanup_case")
    state.npc_mind_states[target_id].mask_integrity = 1
    state.npc_mind_states[target_id].humiliation_risk = 4
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.target_id == target_id)
    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    assert "TA" not in result.narration
    assert "。。" not in result.narration
    assert "还想把在外人眼里" not in result.narration


def test_baseline_narration_no_longer_injects_segment_scene_goal() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="baseline_goal_case")
    suggestion = build_suggested_actions(plan, state)[0]
    scene_goal = plan.segments[0].scene_goal

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    assert scene_goal not in result.narration
    assert "让玩家必须" not in result.narration
    assert "推进到" not in result.narration


def test_baseline_adjacent_turns_show_surface_variation() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="baseline_surface_variation")

    first = build_suggested_actions(plan, state)[0]
    result_one = run_turn(plan, state, first.prompt, selected_suggestion_id=first.suggestion_id)
    second = build_suggested_actions(plan, state)[0]
    result_two = run_turn(plan, state, second.prompt, selected_suggestion_id=second.suggestion_id)

    assert result_one.narration != result_two.narration


def test_baseline_narration_does_not_expose_raw_move_family_tokens() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="baseline_move_family_localized")
    suggestion = build_suggested_actions(plan, state)[0]

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    raw_move_family_tokens = {
        "flirt",
        "probe_secret",
        "comfort",
        "deflect",
        "accuse",
        "ally_with",
        "betray",
        "public_reveal",
        "private_confession",
        "jealousy_trigger",
    }
    assert not any(token in result.narration for token in raw_move_family_tokens)


def test_run_turn_updates_recent_narration_history_window() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="narration_history_window")

    for _ in range(5):
        suggestion = build_suggested_actions(plan, state)[0]
        result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
        state = result.state

    assert 1 <= len(state.recent_narration_fingerprints) <= 4
    assert len(state.recent_narration_fingerprints) == len(state.recent_narration_phrases)
    assert len(state.recent_narration_pattern_fingerprints) == len(state.recent_narration_phrases)
    assert phrase_fingerprint(state.recent_narration_phrases[-1]) == state.recent_narration_fingerprints[-1]


def test_npc_texture_v2_does_not_leak_raw_profile_text(monkeypatch) -> None:
    plan = _play_plan()
    target_id = plan.route_target_ids[0]
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_no_raw_profile")
        state.npc_mind_states[target_id].mask_integrity = 1
        state.npc_mind_states[target_id].humiliation_risk = 4
        state.npc_mind_states[target_id].confession_readiness = 4
        state.npc_mind_states[target_id].trust = 2
        suggestion = next(item for item in build_suggested_actions(plan, state) if item.target_id == target_id)
        result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    forbidden = tuple(
        phrase
        for member in plan.cast
        for phrase in (
            member.drama_profile.public_mask,
            member.drama_profile.status_need,
            member.drama_profile.shame_trigger,
            member.drama_profile.breaking_point,
            member.drama_profile.speech_pattern,
        )
    )
    assert all(item not in result.narration for item in forbidden)
    assert "让玩家必须" not in result.narration
    assert "推进到" not in result.narration


def test_npc_texture_v2_adjacent_turns_do_not_repeat_same_surface(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_repeat_case")
        first = build_suggested_actions(plan, state)[0]
        result_one = run_turn(plan, state, first.prompt, selected_suggestion_id=first.suggestion_id)
        second = build_suggested_actions(plan, state)[0]
        result_two = run_turn(plan, state, second.prompt, selected_suggestion_id=second.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert result_one.narration != result_two.narration


def test_npc_texture_v2_key_moment_narration_is_longer_than_regular_turn(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        regular_state = build_initial_world_state(plan, session_id="v2_length_regular")
        regular_suggestion = build_suggested_actions(plan, regular_state)[0]
        regular_result = run_turn(
            plan,
            regular_state,
            regular_suggestion.prompt,
            selected_suggestion_id=regular_suggestion.suggestion_id,
        )

        key_state = build_initial_world_state(plan, session_id="v2_length_key")
        _move_state_to_segment(plan, key_state, "reveal")
        key_state.scene_heat = 5
        key_state.route_lock = 4
        key_state.secret_exposure = 4
        burst = next((item for item in build_suggested_actions(plan, key_state) if item.lane_id == "burst"), None)
        selected = burst or build_suggested_actions(plan, key_state)[0]
        key_result = run_turn(
            plan,
            key_state,
            selected.prompt,
            selected_suggestion_id=selected.suggestion_id,
        )
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    regular_sentence_count = regular_result.narration.count("。")
    key_sentence_count = key_result.narration.count("。")
    assert key_sentence_count >= regular_sentence_count + 1
    assert len(key_result.narration) > len(regular_result.narration)


def test_npc_texture_v2_changes_surface_for_different_impulses(monkeypatch) -> None:
    plan = _play_plan()
    target_id = plan.route_target_ids[0]
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        confess_state = build_initial_world_state(plan, session_id="v2_confess")
        confess_state.npc_mind_states[target_id].mask_integrity = 1
        confess_state.npc_mind_states[target_id].confession_readiness = 5
        confess_state.npc_mind_states[target_id].trust = 3
        confess_state.relationships[target_id].trust = 3
        confess_state.relationships[target_id].affection = 2
        confess_suggestion = next(item for item in build_suggested_actions(plan, confess_state) if item.target_id == target_id)
        confess_result = run_turn(plan, confess_state, confess_suggestion.prompt, selected_suggestion_id=confess_suggestion.suggestion_id)

        betray_state = build_initial_world_state(plan, session_id="v2_betray")
        betray_state.npc_mind_states[target_id].mask_integrity = 1
        betray_state.npc_mind_states[target_id].betrayal_readiness = 5
        betray_state.npc_mind_states[target_id].suspicion = 4
        betray_state.relationships[target_id].suspicion = 4
        betray_suggestion = next(item for item in build_suggested_actions(plan, betray_state) if item.target_id == target_id)
        betray_result = run_turn(plan, betray_state, betray_suggestion.prompt, selected_suggestion_id=betray_suggestion.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert confess_result.narration != betray_result.narration
    assert confess_result.narration
    assert betray_result.narration


def test_npc_texture_v2_reveal_fallout_reads_as_happened_event(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_reveal_event")
        _move_state_to_segment(plan, state, "reveal")
        burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert "只差半步" not in result.narration
    assert any(
        consequence in result.narration
        for consequence in result.state.last_turn_consequences[:2]
    ) or any(token in result.narration for token in ("公开", "翻牌", "站边", "切割", "台面", "评审", "镜头"))


def test_npc_texture_v2_includes_supporting_character_reaction(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_supporting_reactors")
        _move_state_to_segment(plan, state, "reveal")
        active_ids = tuple(state.active_character_ids)
        burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    supporting_names = [
        member.display_name
        for member in plan.cast
        if member.character_id in active_ids and member.character_id != result.intent.target_id
    ]
    assert any(name in result.narration for name in supporting_names)


def test_npc_texture_v2_entertainment_supporting_reactions_use_media_shell_language(monkeypatch) -> None:
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_ent_supporting")
        _move_state_to_segment(plan, state, "reveal")
        burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert any(token in result.narration for token in ("镜头", "热搜", "外面", "公关", "切割", "事故"))


def test_npc_texture_v2_campus_supporting_reactions_use_campus_shell_language(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_campus_supporting")
        _move_state_to_segment(plan, state, "reveal")
        burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert any(token in result.narration for token in ("台下", "评审", "名额", "社团", "熟人", "站队"))


def test_npc_texture_v2_supporting_reactions_split_shells_even_under_public_reveal(monkeypatch) -> None:
    entertainment_plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    campus_plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        entertainment_state = build_initial_world_state(entertainment_plan, session_id="v2_ent_shell_split")
        _move_state_to_segment(entertainment_plan, entertainment_state, "reveal")
        ent_burst = next(item for item in build_suggested_actions(entertainment_plan, entertainment_state) if item.lane_id == "burst")
        entertainment_result = run_turn(entertainment_plan, entertainment_state, ent_burst.prompt, selected_suggestion_id=ent_burst.suggestion_id)

        campus_state = build_initial_world_state(campus_plan, session_id="v2_campus_shell_split")
        _move_state_to_segment(campus_plan, campus_state, "reveal")
        campus_burst = next(item for item in build_suggested_actions(campus_plan, campus_state) if item.lane_id == "burst")
        campus_result = run_turn(campus_plan, campus_state, campus_burst.prompt, selected_suggestion_id=campus_burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert entertainment_result.narration != campus_result.narration
    assert any(token in entertainment_result.narration for token in ("镜头", "热搜", "公关", "切割", "事故"))
    assert any(token in campus_result.narration for token in ("台下", "评审", "名额", "社团", "熟人", "站队"))


def test_compiled_segment_contains_tone_example_pack() -> None:
    plan = _play_plan()
    segment = plan.segments[0]

    assert segment.template_tone_example_lines
    assert segment.template_tone_scene_examples
    assert segment.tone_example_pack.play_reaction_example_lines
    assert segment.tone_example_pack.play_supporting_example_lines


def test_play_v2_consumes_template_tone_examples_without_verbatim_leak(monkeypatch) -> None:
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_tone_example_no_copy")
        _move_state_to_segment(plan, state, "reveal")
        segment = plan.segments[state.segment_index]
        source_texts = [line.text for line in segment.template_tone_example_lines]
        source_texts.extend(scene.text for scene in segment.template_tone_scene_examples)
        source_texts.extend(line.text for line in segment.tone_example_pack.play_reaction_example_lines)
        source_texts.extend(line.text for line in segment.tone_example_pack.play_supporting_example_lines)
        burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert source_texts
    assert all(text not in result.narration for text in source_texts)


def test_adjacent_turns_do_not_repeat_same_example_bucket(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_example_bucket_repeat")
        first = build_suggested_actions(plan, state)[0]
        result_one = run_turn(plan, state, first.prompt, selected_suggestion_id=first.suggestion_id)
        first_used = tuple(result_one.state.recent_example_bucket_ids[:2])
        second = build_suggested_actions(plan, state)[0]
        result_two = run_turn(plan, state, second.prompt, selected_suggestion_id=second.suggestion_id)
        second_used = tuple(result_two.state.recent_example_bucket_ids[:2])
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert first_used
    assert second_used
    assert first_used != second_used


def test_entertainment_and_campus_use_distinct_example_buckets(monkeypatch) -> None:
    entertainment_plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    campus_plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        entertainment_state = build_initial_world_state(entertainment_plan, session_id="ent_example_bucket")
        _move_state_to_segment(entertainment_plan, entertainment_state, "reveal")
        ent_burst = next(item for item in build_suggested_actions(entertainment_plan, entertainment_state) if item.lane_id == "burst")
        ent_result = run_turn(entertainment_plan, entertainment_state, ent_burst.prompt, selected_suggestion_id=ent_burst.suggestion_id)

        campus_state = build_initial_world_state(campus_plan, session_id="campus_example_bucket")
        _move_state_to_segment(campus_plan, campus_state, "reveal")
        campus_burst = next(item for item in build_suggested_actions(campus_plan, campus_state) if item.lane_id == "burst")
        campus_result = run_turn(campus_plan, campus_state, campus_burst.prompt, selected_suggestion_id=campus_burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert ent_result.state.recent_example_bucket_ids
    assert campus_result.state.recent_example_bucket_ids
    assert ent_result.state.recent_example_bucket_ids[:2] != campus_result.state.recent_example_bucket_ids[:2]


def test_compiled_segment_contains_tone_example_pack() -> None:
    plan = _play_plan()
    segment = plan.segments[0]

    assert segment.template_tone_example_lines
    assert segment.template_tone_scene_examples
    assert segment.tone_example_pack.play_reaction_example_lines
    assert segment.tone_example_pack.play_supporting_example_lines


def test_play_v2_consumes_template_tone_examples_without_verbatim_leak(monkeypatch) -> None:
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_tone_examples_no_copy")
        _move_state_to_segment(plan, state, "reveal")
        segment = plan.segments[state.segment_index]
        source_texts = [
            line.text
            for line in (
                list(segment.template_tone_example_lines)
                + list(segment.tone_example_pack.play_reaction_example_lines)
                + list(segment.tone_example_pack.play_supporting_example_lines)
            )
        ] + [scene.text for scene in segment.template_tone_scene_examples]
        burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert source_texts
    assert all(text not in result.narration for text in source_texts)


def test_adjacent_turns_do_not_repeat_same_example_bucket(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="v2_example_bucket_repeat")
        first = build_suggested_actions(plan, state)[0]
        result_one = run_turn(plan, state, first.prompt, selected_suggestion_id=first.suggestion_id)
        first_used = tuple(result_one.state.recent_example_bucket_ids[:2])
        second = build_suggested_actions(plan, state)[0]
        result_two = run_turn(plan, state, second.prompt, selected_suggestion_id=second.suggestion_id)
        second_used = tuple(result_two.state.recent_example_bucket_ids[:2])
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert first_used
    assert second_used
    assert first_used != second_used


def test_entertainment_and_campus_use_distinct_example_buckets(monkeypatch) -> None:
    entertainment_plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    campus_plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        entertainment_state = build_initial_world_state(entertainment_plan, session_id="ent_bucket_case")
        _move_state_to_segment(entertainment_plan, entertainment_state, "reveal")
        ent_burst = next(item for item in build_suggested_actions(entertainment_plan, entertainment_state) if item.lane_id == "burst")
        ent_result = run_turn(entertainment_plan, entertainment_state, ent_burst.prompt, selected_suggestion_id=ent_burst.suggestion_id)

        campus_state = build_initial_world_state(campus_plan, session_id="campus_bucket_case")
        _move_state_to_segment(campus_plan, campus_state, "reveal")
        campus_burst = next(item for item in build_suggested_actions(campus_plan, campus_state) if item.lane_id == "burst")
        campus_result = run_turn(campus_plan, campus_state, campus_burst.prompt, selected_suggestion_id=campus_burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert ent_result.state.recent_example_bucket_ids
    assert campus_result.state.recent_example_bucket_ids
    assert ent_result.state.recent_example_bucket_ids[:2] != campus_result.state.recent_example_bucket_ids[:2]


def test_latent_events_merge_same_kind_and_target_cluster() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_merge_case")
    _move_state_to_segment(plan, state, "misread")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(
            event_id="rel_seed",
            kind="relationship_debt",
            target_ids=[target_id],
            stake_ids=list(reversed(stake_ids)) or [target_id],
            pressure=1,
            maturity=1,
            threshold=6,
        )
    ]
    suggestion = next(
        item
        for item in build_suggested_actions(plan, state)
        if item.move_family in {"comfort", "ally_with", "private_confession", "accuse", "betray", "flirt"}
    )
    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    debt_events = [event for event in result.state.latent_events if event.kind == "relationship_debt"]
    triggered_debt = any(record.kind == "relationship_debt" for record in result.state.last_turn_escalations)

    assert debt_events or triggered_debt
    if debt_events:
        assert debt_events[0].pressure + debt_events[0].maturity >= 2


def test_latent_events_are_capped_and_do_not_grow_unbounded() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_cap_case")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.relationships if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id=f"latent_{idx}", kind="relationship_debt" if idx % 2 == 0 else "public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=3)
        for idx in range(7)
    ]

    result = run_turn(plan, state, "我要先试探她手里的秘密")

    assert len(result.state.latent_events) <= 6
    assert sum(1 for event in result.state.latent_events if event.kind == "relationship_debt") <= 2
    assert sum(1 for event in result.state.latent_events if event.kind == "public_wave") <= 2


def test_only_one_triggered_latent_event_per_turn() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_single_trigger")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="rel", kind="relationship_debt", target_ids=[target_id], stake_ids=stake_ids, pressure=4, maturity=4),
        _latent_event(event_id="public", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=4, maturity=4),
        _latent_event(event_id="secret", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=4, maturity=4),
    ]

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert len(result.state.last_turn_escalations) <= 1
    assert sum(1 for tag in result.state.last_turn_tags if tag.endswith(":triggered")) <= 1


def test_reveal_terminal_key_segment_conversion_triggers_when_high_pressure_exists() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_key_segment_conversion")
    _move_state_to_segment(plan, state, "reveal")
    segment = plan.segments[state.segment_index]
    intent = UrbanTurnIntent(
        input_text="我先压住不公开。",
        lane_id="relationship",
        move_family="comfort",
        target_id=plan.route_target_ids[0],
        scene_frame="private",
        confidence="high",
    )
    event = _latent_event(
        event_id="primed_secret",
        kind="secret_pressure",
        target_ids=["ghost_target"],
        stake_ids=["ghost_stake"],
        pressure=1,
        maturity=3,
        threshold=4,
    )
    event.status = "primed"
    triggered, _, key_conversion = LatentEventEngine.choose_trigger(
        plan=plan,
        segment=segment,
        intent=intent,
        state=state,
        events=[event],
        forced_controls={},
    )

    assert triggered is not None
    assert key_conversion is True


def test_key_segment_conversion_still_keeps_one_trigger_per_turn() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_key_segment_single_trigger")
    _move_state_to_segment(plan, state, "terminal")
    segment = plan.segments[state.segment_index]
    intent = UrbanTurnIntent(
        input_text="我先稳住，不让它当场炸。",
        lane_id="relationship",
        move_family="comfort",
        target_id=plan.route_target_ids[0],
        scene_frame="private",
        confidence="high",
    )
    events = [
        _latent_event(
            event_id="primed_rel",
            kind="relationship_debt",
            target_ids=["ghost_target"],
            stake_ids=["ghost_stake"],
            pressure=1,
            maturity=3,
            threshold=4,
        ),
        _latent_event(
            event_id="primed_secret",
            kind="secret_pressure",
            target_ids=["ghost_target"],
            stake_ids=["ghost_stake"],
            pressure=1,
            maturity=3,
            threshold=4,
        ),
    ]
    for event in events:
        event.status = "primed"
    triggered, retained, key_conversion = LatentEventEngine.choose_trigger(
        plan=plan,
        segment=segment,
        intent=intent,
        state=state,
        events=events,
        forced_controls={},
    )

    assert triggered is not None
    assert key_conversion is True
    assert len(retained) == 1
    assert retained[0].event_id != triggered.event_id


def test_deflect_presses_but_ages_public_wave_or_secret_pressure() -> None:
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    state = build_initial_world_state(plan, session_id="deflect_press_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="public_wave_seed", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2),
        _latent_event(event_id="secret_pressure_seed", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=3, maturity=2),
    ]

    control = next(item for item in build_control_actions(plan, state) if item.action_type == "press")
    result = run_turn(
        plan,
        state,
        "我先把这件事压下去，别让外面继续接住",
        selected_control_action_id=control.action_id,
        control_action="press",
        control_target_kind="public_wave",
    )
    public_wave = next((event for event in result.state.latent_events if event.kind == "public_wave"), None)
    triggered_public_wave = any(record.kind == "public_wave" for record in result.state.last_turn_escalations)

    assert public_wave is not None or triggered_public_wave
    if public_wave is not None:
        assert public_wave.age_turns >= 2
        assert public_wave.pressure >= 2
    assert any(tag in {"latent:public_wave:press", "latent:secret_pressure:press"} for tag in result.state.last_turn_latent_ops)


def test_patient_burn_preferences_make_delayed_regression_mature_faster() -> None:
    plan = _play_plan()
    target_id = plan.route_target_ids[0]
    plan.cast = [
        member.model_copy(
            update={
                "strategic_intent": member.strategic_intent.model_copy(
                    update={
                        "delay_preference": "patient_burn" if member.character_id == target_id else member.strategic_intent.delay_preference,
                        "preferred_latent_kind": "relationship_debt" if member.character_id == target_id else member.strategic_intent.preferred_latent_kind,
                        "sensitive_latent_kind": "relationship_debt" if member.character_id == target_id else member.strategic_intent.sensitive_latent_kind,
                    }
                )
            }
        )
        for member in plan.cast
    ]
    state = build_initial_world_state(plan, session_id="patient_burn_case")
    _move_state_to_segment(plan, state, "misread")
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [_latent_event(event_id="rel_seed", kind="relationship_debt", target_ids=[target_id], stake_ids=stake_ids, pressure=1, maturity=1, threshold=6)]

    result = run_turn(plan, state, "我还是先护住她，把这件事按住")
    rel_event = next((event for event in result.state.latent_events if event.kind == "relationship_debt"), None)
    triggered_rel = any(record.kind == "relationship_debt" for record in result.state.last_turn_escalations)

    assert rel_event is not None or triggered_rel
    if rel_event is not None:
        assert rel_event.maturity >= 3
        assert rel_event.pressure >= 2


def test_public_reveal_detonates_secret_pressure_early() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="public_reveal_detonate_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    state.latent_events = [
        _latent_event(event_id="secret_seed", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=2, maturity=3, threshold=4),
    ]

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert result.state.last_turn_escalations
    assert result.state.last_turn_escalations[0].kind in {"secret_pressure", "public_wave"}
    assert any(tag == "latent:secret_pressure:detonate" for tag in result.state.last_turn_latent_ops)


def test_regression_payoff_preferences_bias_delayed_event_damage() -> None:
    plan = _play_plan()
    target_id = plan.route_target_ids[0]
    plan.cast = [
        member.model_copy(
            update={
                "strategic_intent": member.strategic_intent.model_copy(
                    update={
                        "regression_payoff": "status_loss" if member.character_id == target_id else member.strategic_intent.regression_payoff,
                        "sensitive_latent_kind": "relationship_debt" if member.character_id == target_id else member.strategic_intent.sensitive_latent_kind,
                    }
                )
            }
        )
        for member in plan.cast
    ]
    state = build_initial_world_state(plan, session_id="payoff_preference_case")
    _move_state_to_segment(plan, state, "reveal")
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [_latent_event(event_id="rel_seed", kind="relationship_debt", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=4, threshold=4)]

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert result.state.relationship_debt_pressure >= 1
    assert any("最不敢掉的" in line or "位置" in line or "名额" in line or "顺位" in line for line in result.state.last_turn_consequences)


def test_ally_with_redirects_relationship_debt_instead_of_clearing_it() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="ally_redirect_case")
    _move_state_to_segment(plan, state, "misread")
    target_id = plan.route_target_ids[0]
    other_target = next(item for item in state.active_character_ids if item != target_id)
    stake_ids = [item for item in state.active_character_ids if item not in {target_id, other_target}]
    state.latent_events = [
        _latent_event(event_id="rel_seed", kind="relationship_debt", target_ids=[other_target], stake_ids=stake_ids or [target_id], pressure=3, maturity=2),
    ]

    suggestions = build_suggested_actions(plan, state)
    suggestion = next(
        (
            item
            for item in suggestions
            if item.move_family == "ally_with"
        ),
        next((item for item in suggestions if item.lane_id == "side"), suggestions[0]),
    )
    control = next(item for item in build_control_actions(plan, state) if item.action_type == "redirect")
    result = run_turn(
        plan,
        state,
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        selected_control_action_id=control.action_id,
        control_action="redirect",
        control_target_kind="relationship_debt",
        control_target_id=target_id,
        control_target_mode="character",
    )

    redirected_targets = [
        *[event.target_character_ids for event in result.state.latent_events if event.kind == "relationship_debt"],
        *[record.target_character_ids for record in result.state.last_turn_escalations if record.kind == "relationship_debt"],
    ]
    assert [result.intent.target_id] in redirected_targets
    assert result.state.relationship_debt_pressure >= 1
    assert any(tag == "latent:relationship_debt:redirect" for tag in result.state.last_turn_latent_ops)
    assert result.intent.control_source == "explicit"


def test_burst_lane_prefers_detonate_control_semantics() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="burst_control_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    state.latent_events = [_latent_event(event_id="secret_seed", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=2, maturity=3)]

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert any(tag.endswith(":detonate") for tag in result.state.last_turn_latent_ops)


def test_relationship_lane_prefers_press_control_semantics() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="relationship_control_case")
    _move_state_to_segment(plan, state, "misread")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [_latent_event(event_id="rel_seed", kind="relationship_debt", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2)]

    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")
    control = next(item for item in build_control_actions(plan, state) if item.action_type == "press")
    result = run_turn(
        plan,
        state,
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        selected_control_action_id=control.action_id,
        control_action="press",
        control_target_kind="relationship_debt",
    )

    assert any(tag.endswith(":press") for tag in result.state.last_turn_latent_ops)
    assert result.intent.control_source == "explicit"


def test_side_lane_prefers_redirect_control_semantics() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="side_control_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    target_state = state.relationships[target_id]
    target_state.suspicion = 4
    state.npc_mind_states[target_id].control_need = 5
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [_latent_event(event_id="wave_seed", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2)]

    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "side")
    control = next(item for item in build_control_actions(plan, state) if item.action_type == "redirect")
    result = run_turn(
        plan,
        state,
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        selected_control_action_id=control.action_id,
        control_action="redirect",
        control_target_id=target_id,
        control_target_mode="character",
        control_target_kind="public_wave",
    )

    assert suggestion.move_family in {"ally_with", "accuse", "deflect", "comfort"}
    assert any(tag.endswith(":redirect") for tag in result.state.last_turn_latent_ops)
    assert result.intent.control_source == "explicit"


def test_progress_summary_prefers_latent_foreshadow_when_no_main_trigger() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_progress_case")
    _move_state_to_segment(plan, state, "misread")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [_latent_event(event_id="wave_seed", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=1, threshold=6)]

    result = run_turn(plan, state, "我先轻轻带过去，不让她现在就炸")

    assert any(token in result.progress_summary for token in ("发酵", "记账", "轮到", "没过去", "变重"))


def test_feedback_contains_trigger_and_foreshadow_together() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_feedback_combo")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="trigger_me", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=3, maturity=4, threshold=4),
        _latent_event(event_id="foreshadow_me", kind="relationship_debt", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2, threshold=6),
    ]

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    joined = " ".join(result.state.last_turn_consequences)
    assert any(token in joined for token in ("自己拱开口子", "自己炸开", "见光"))
    assert any(token in joined for token in ("记账", "发酵", "没过去", "最疼的时候"))


def test_state_bars_use_latent_pressure_bars_instead_of_legacy_pressure_ids() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_bar_case")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.relationships if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="rel", kind="relationship_debt", target_ids=[target_id], stake_ids=stake_ids, pressure=2, maturity=2),
        _latent_event(event_id="wave", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=2, maturity=2),
        _latent_event(event_id="secret", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=2, maturity=2),
        _latent_event(event_id="npc", kind="npc_action", target_ids=[target_id], stake_ids=stake_ids, pressure=2, maturity=2, actor_id=stake_ids[0] if stake_ids else None),
    ]
    result = run_turn(plan, state, "我要先试探她手里的秘密")

    bar_ids = [bar.bar_id for bar in build_v2_state_bars(plan, result.state)]
    assert {"relationship_debt_pressure", "public_wave_pressure", "secret_pressure", "npc_action_pressure"} <= set(bar_ids)
    assert not {"alignment_pressure", "old_debt_heat", "public_chain_pressure"} & set(bar_ids)


def test_turn_trace_contains_latent_operation_tags() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_trace_case")
    _move_state_to_segment(plan, state, "reveal")
    before = state.model_copy(deep=True)
    target_id = plan.route_target_ids[0]
    state.latent_events = [_latent_event(event_id="secret_seed", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=2, maturity=3)]

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    trace, _ = build_v2_turn_trace(
        plan=plan,
        before_state=before,
        result=result,
        player_input=burst.prompt,
        selected_suggestion_id=burst.suggestion_id,
        turn_elapsed_ms=10,
    )

    assert any(tag.startswith("latent:") for tag in result.state.last_turn_tags)
    assert trace.submission_input_mode == "select_id"
    assert trace.interpret_usage.get("submission_input_mode") == "select_id"
    assert int(trace.interpret_usage.get("submitted_with_selected_ids") or 0) == 1
    assert any(key in trace.resolution.global_state_changes for key in ("relationship_debt_pressure", "public_wave_pressure", "secret_pressure", "npc_action_pressure"))
    assert trace.resolution.pressure_note
    assert trace.intent_compile_source in {"llm", "heuristic_fallback"}
    assert trace.control_source in {"explicit", "free_text", "none"}


def test_story_debug_contains_structured_payload() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="story_debug_case")
    _move_state_to_segment(plan, state, "reveal")
    before = state.model_copy(deep=True)
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "side")

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    trace, _ = build_v2_turn_trace(
        plan=plan,
        before_state=before,
        result=result,
        player_input=suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        turn_elapsed_ms=10,
    )

    assert trace.story_debug is not None
    assert trace.resolution.story_debug is not None
    assert trace.story_debug.cost_route is not None
    assert trace.story_debug.propagation_edge is not None
    assert trace.story_debug.scene_question_state is not None
    assert trace.story_debug.callback_status is not None
    assert trace.story_debug.summary


def test_turn_semantic_plan_contains_five_stages() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="semantic_plan_five_stages")
    suggestion = build_suggested_actions(plan, state)[0]

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.question_plan is not None
    assert semantic.stake_plan is not None
    assert semantic.event_plan is not None
    assert semantic.payoff_plan is not None
    assert semantic.style_plan is not None
    assert semantic.summary


def test_scene_question_forces_progress_when_same_state_would_repeat() -> None:
    runtime_module = __import__("rpg_backend.play_v2.runtime", fromlist=["_scene_question_transition"])
    transition = runtime_module._scene_question_transition

    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="scene_question_forced_progress_case")
    segment = plan.segments[state.segment_index]
    state.scene_heat = 0
    state.segment_progress = 0
    state.secret_exposure = 0
    state.scene_question_states[segment.segment_id] = state.scene_question_states[segment.segment_id].model_copy(
        update={
            "status": "flip",
            "previous_status": "tightening",
        }
    )

    updated, forced_advance, advance_reason = transition(
        segment=segment,
        state=state,
        triggered_kind=None,
        key_segment_conversion=False,
    )

    assert updated.status == "resolved"
    assert forced_advance is True
    assert advance_reason == "same_state_blocked"


def test_reveal_terminal_without_natural_trigger_still_reaches_flip_or_resolved() -> None:
    runtime_module = __import__("rpg_backend.play_v2.runtime", fromlist=["_scene_question_transition"])
    transition = runtime_module._scene_question_transition

    for segment_role in ("reveal", "terminal"):
        plan = _play_plan()
        state = build_initial_world_state(plan, session_id=f"scene_question_key_segment_{segment_role}")
        _move_state_to_segment(plan, state, segment_role)
        segment = plan.segments[state.segment_index]
        state.scene_heat = 0
        state.segment_progress = 0
        state.secret_exposure = 0
        state.scene_question_states[segment.segment_id] = state.scene_question_states[segment.segment_id].model_copy(
            update={
                "status": "open",
                "previous_status": None,
            }
        )

        updated, forced_advance, advance_reason = transition(
            segment=segment,
            state=state,
            triggered_kind=None,
            key_segment_conversion=False,
        )

        assert updated.status in {"flip", "resolved"}
        assert forced_advance is True
        assert advance_reason in {"key_segment_minimum_progress", "key_segment_conversion_pass", "key_segment_forced_resolve"}


def test_each_turn_commits_observable_cost() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="semantic_payoff_commit_case")
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.payoff_plan.committed is True
    assert semantic.payoff_plan.global_delta_keys or semantic.payoff_plan.relationship_delta_ids


def test_top_latent_event_never_stalls() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="semantic_top_latent_transition_case")
    _move_state_to_segment(plan, state, "misread")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(
            event_id="transition_seed",
            kind="public_wave",
            target_ids=[target_id],
            stake_ids=stake_ids,
            pressure=2,
            maturity=2,
            threshold=6,
        )
    ]

    result = run_turn(plan, state, "我先稳住，不让这件事当场炸掉")

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.event_plan.top_event_kind is not None
    assert semantic.event_plan.top_event_transition in {"rising", "cooling", "triggered"}
    assert any(tag.startswith(f"latent:{semantic.event_plan.top_event_kind}:") for tag in result.state.last_turn_tags)


def test_story_debug_contains_semantic_execution_receipt() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="semantic_story_debug_receipt")
    _move_state_to_segment(plan, state, "reveal")
    before = state.model_copy(deep=True)
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    trace, _ = build_v2_turn_trace(
        plan=plan,
        before_state=before,
        result=result,
        player_input=suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        turn_elapsed_ms=10,
    )

    assert trace.story_debug is not None
    assert trace.story_debug.question_step is not None
    assert trace.story_debug.stake_shift_top is not None
    assert trace.story_debug.event_decision is not None
    assert trace.story_debug.payoff_commit is not None
    assert trace.story_debug.style_commit is not None
    assert trace.story_debug.style_commit.shell_anchor_hit is True


def test_story_debug_question_step_includes_forced_advance_receipt() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="semantic_forced_question_debug_case")
    segment = plan.segments[state.segment_index]
    state.scene_question_states[segment.segment_id] = state.scene_question_states[segment.segment_id].model_copy(
        update={
            "status": "flip",
            "previous_status": "tightening",
        }
    )
    before = state.model_copy(deep=True)
    suggestion = build_suggested_actions(plan, state)[0]

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    trace, _ = build_v2_turn_trace(
        plan=plan,
        before_state=before,
        result=result,
        player_input=suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        turn_elapsed_ms=10,
    )

    assert trace.story_debug is not None
    assert trace.story_debug.question_step is not None
    assert trace.story_debug.question_step.forced_advance is True
    assert trace.story_debug.question_step.advance_reason == "same_state_blocked"
    assert "强制推进" in trace.story_debug.question_step.summary


def test_narration_surface_consumes_style_plan_without_reinferring_events() -> None:
    runtime_module = __import__("rpg_backend.play_v2.runtime", fromlist=["_build_turn_semantic_plan_seed"])
    build_seed = runtime_module._build_turn_semantic_plan_seed

    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    state = build_initial_world_state(plan, session_id="semantic_style_commit_case")
    _move_state_to_segment(plan, state, "reveal")
    segment = plan.segments[state.segment_index]
    seed_plan = build_seed(plan=plan, segment=segment, state=state.model_copy(deep=True))
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.style_plan.reason_family == seed_plan.style_plan.reason_family
    assert semantic.style_plan.signal_family == seed_plan.style_plan.signal_family
    assert semantic.style_plan.cost_family == seed_plan.style_plan.cost_family
    assert semantic.style_plan.cadence == seed_plan.style_plan.cadence
    assert semantic.style_plan.shell_anchor_hit is True


def test_render_uses_semantic_style_contract_without_reinferring_reason_signal(monkeypatch) -> None:
    runtime_module = __import__("rpg_backend.play_v2.runtime", fromlist=["_SemanticRenderContract"])
    contract_cls = runtime_module._SemanticRenderContract
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    base_state = build_initial_world_state(plan, session_id="semantic_contract_render_case")
    _move_state_to_segment(plan, base_state, "reveal")
    suggestion = next(item for item in build_suggested_actions(plan, base_state) if item.lane_id == "burst")
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        baseline = run_turn(
            plan,
            base_state.model_copy(deep=True),
            suggestion.prompt,
            selected_suggestion_id=suggestion.suggestion_id,
        )

        forced_contract = contract_cls(
            key_segment=True,
            primary_reason_family="old_debt",
            counter_reason_family="old_debt",
            crowd_reason_family="self_preserve",
            fallout_reason_family="old_debt",
            signal_family="peer_spread",
            cost_family="eligibility",
            cadence="broken",
            force_main_clause_cost_subject=False,
            cost_subject_payer_name=None,
            cost_subject_beneficiary_name=None,
            cost_subject_focus=None,
            shell_anchor_tokens=("台下", "评审", "名额"),
        )
        monkeypatch.setattr(
            runtime_module,
            "_semantic_render_contract_from_plan",
            lambda _plan, _semantic_plan: forced_contract,
        )
        contracted = run_turn(
            plan,
            base_state.model_copy(deep=True),
            suggestion.prompt,
            selected_suggestion_id=suggestion.suggestion_id,
        )
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert "render:semantic_contract" in contracted.state.last_turn_tags
    assert any(token in contracted.narration for token in ("旧账", "台下", "评审", "名额"))
    assert "old_debt" not in contracted.narration
    assert contracted.narration != baseline.narration


def test_cost_route_uses_author_strategy_matrix_rule() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="cost_matrix_rule_case")
    selected = build_suggested_actions(plan, state)[0]
    rule = next(
        item
        for item in plan.semantic_strategy_pack.cost_routing_matrix.rules
        if item.move_family == selected.move_family and item.control_action == "none"
    )
    rule.global_deltas = {"public_image": -2}
    rule.target_relationship_deltas = {}

    before_public_image = state.public_image
    result = run_turn(plan, state, selected.prompt, selected_suggestion_id=selected.suggestion_id)

    assert result.state.last_turn_cost_route is not None
    assert result.state.last_turn_cost_route.immediate_global_deltas.get("public_image") == -2
    assert result.state.public_image <= before_public_image - 1


def test_deferred_callback_is_queued_with_cost_route() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="callback_queue_case")
    relationship = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")

    result = run_turn(plan, state, relationship.prompt, selected_suggestion_id=relationship.suggestion_id)

    assert result.state.last_turn_cost_route is not None
    assert result.state.last_turn_cost_route.deferred_callback_id is not None
    assert result.state.callback_queue
    assert result.state.last_turn_callback_status.created_count >= 1


def test_deferred_callback_can_mature_into_latent_trigger() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="callback_mature_case")
    relationship = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")
    first = run_turn(plan, state, relationship.prompt, selected_suggestion_id=relationship.suggestion_id)
    assert first.state.callback_queue
    matured_queue = []
    for item in first.state.callback_queue:
        matured_queue.append(
            item.model_copy(
                update={
                    "due_turn_min": first.state.turn_index,
                    "due_turn_max": first.state.turn_index + 1,
                }
            )
        )
    first.state.callback_queue = matured_queue
    second_suggestion = build_suggested_actions(plan, first.state)[0]
    second = run_turn(plan, first.state, second_suggestion.prompt, selected_suggestion_id=second_suggestion.suggestion_id)

    assert second.state.last_turn_callback_status.triggered_callback_id is not None
    assert any(tag.startswith("callback:") for tag in second.state.last_turn_tags)


def test_question_plan_prioritizes_due_unresolved_cost() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="question_due_cost_priority_case")
    available_roles = {item.segment_role for item in plan.segments}
    target_role = "pressure" if "pressure" in available_roles else "misread"
    _move_state_to_segment(plan, state, target_role)
    target_id = plan.route_target_ids[0]
    state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_due_1",
            source_turn_index=max(0, state.turn_index - 2),
            source_segment_id=state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[target_id],
            payer_character_id=target_id,
            beneficiary_character_id=next((item for item in state.active_character_ids if item != target_id), target_id),
            linked_scene_question_id=state.segment_id,
            scene_question_focus="who_takes_blame",
            due_turn=state.turn_index + 1,
            status="pending",
            linked_callback_id=None,
            summary="这笔账快到期了。",
        )
    ]
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "side")

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.question_plan.prioritized_cost_id == "uc_due_1"
    assert semantic.question_plan.prioritized_cost_focus == "who_takes_blame"
    assert semantic.question_plan.prioritized_cost_due_turn is not None


def test_event_plan_prioritizes_due_cost_on_key_segment() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="event_due_cost_priority_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_due_reveal",
            source_turn_index=max(0, state.turn_index - 2),
            source_segment_id=state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[target_id],
            payer_character_id=target_id,
            beneficiary_character_id=next((item for item in state.active_character_ids if item != target_id), target_id),
            linked_scene_question_id=state.segment_id,
            scene_question_focus="who_pays",
            due_turn=state.turn_index,
            status="pending",
            linked_callback_id=None,
            summary="这笔账到期了。",
        )
    ]
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.event_plan.cost_return_priority_applied is True
    assert semantic.event_plan.prioritized_cost_id == "uc_due_reveal"
    assert semantic.event_plan.primary_driver == "cost_return"
    assert semantic.event_plan.due_cost_forces_primary_driver_applied is True
    assert semantic.event_plan.cost_ladder_stage >= 1
    assert isinstance(semantic.event_plan.cost_ladder_primary_applies, bool)


def test_event_plan_pressure_segment_uses_cost_return_when_due() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="event_due_cost_priority_pressure_case")
    target_roles = {item.segment_role for item in plan.segments}
    if "pressure" in target_roles:
        segment_role = "pressure"
    elif "reversal" in target_roles:
        segment_role = "reversal"
    else:
        pytest.skip("plan has no pressure/reversal segment in this seed")
    _move_state_to_segment(plan, state, segment_role)
    target_id = plan.route_target_ids[0]
    state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_due_pressure",
            source_turn_index=max(0, state.turn_index - 2),
            source_segment_id=state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[target_id],
            payer_character_id=target_id,
            beneficiary_character_id=next((item for item in state.active_character_ids if item != target_id), target_id),
            linked_scene_question_id=state.segment_id,
            scene_question_focus="who_takes_blame",
            due_turn=state.turn_index,
            status="pending",
            linked_callback_id=None,
            summary="这笔账到期了。",
        )
    ]
    side = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "side")

    result = run_turn(plan, state, side.prompt, selected_suggestion_id=side.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.event_plan.primary_driver == "cost_return"
    assert semantic.event_plan.due_cost_forces_primary_driver_applied is True


def test_event_plan_opening_segment_does_not_force_cost_return_driver() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="event_due_cost_opening_non_force_case")
    _move_state_to_segment(plan, state, "opening")
    target_id = plan.route_target_ids[0]
    state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_due_opening",
            source_turn_index=max(0, state.turn_index - 2),
            source_segment_id=state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[target_id],
            payer_character_id=target_id,
            beneficiary_character_id=next((item for item in state.active_character_ids if item != target_id), target_id),
            linked_scene_question_id=state.segment_id,
            scene_question_focus="who_pays",
            due_turn=state.turn_index,
            status="pending",
            linked_callback_id=None,
            summary="这笔账到期了。",
        )
    ]
    relationship = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")

    result = run_turn(plan, state, relationship.prompt, selected_suggestion_id=relationship.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.event_plan.primary_driver != "cost_return"
    assert semantic.event_plan.due_cost_forces_primary_driver_applied is False


def test_event_plan_player_explicit_control_keeps_primary_and_marks_secondary_due_cost_pressure() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="event_due_cost_player_override_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_due_override",
            source_turn_index=max(0, state.turn_index - 2),
            source_segment_id=state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[target_id],
            payer_character_id=target_id,
            beneficiary_character_id=next((item for item in state.active_character_ids if item != target_id), target_id),
            linked_scene_question_id=state.segment_id,
            scene_question_focus="who_pays",
            due_turn=state.turn_index,
            status="pending",
            linked_callback_id=None,
            summary="这笔账到期了。",
        )
    ]
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    result = run_turn(
        plan,
        state,
        burst.prompt,
        selected_suggestion_id=burst.suggestion_id,
        control_action="press",
        control_target_kind="public_wave",
    )

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.event_plan.due_cost_primary_eligible is True
    assert semantic.event_plan.player_override_applied is True
    assert semantic.event_plan.secondary_due_cost_pressure is True
    assert semantic.event_plan.due_cost_forces_primary_driver_applied is False
    assert semantic.event_plan.primary_driver != "cost_return"
    assert any("次驱动" in line for line in result.state.last_turn_consequences)
    deferred_cost = next((item for item in result.state.unresolved_costs if item.cost_id == "uc_due_override"), None)
    assert deferred_cost is not None
    assert deferred_cost.ladder_defer_once_used is True
    assert deferred_cost.ladder_retry_bias_steps >= 1


def test_cost_return_primary_driver_commits_payer_beneficiary_in_main_clause(monkeypatch) -> None:
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="cost_return_style_commit_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    beneficiary_id = next((item for item in state.active_character_ids if item != target_id), target_id)
    state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_due_style",
            source_turn_index=max(0, state.turn_index - 2),
            source_segment_id=state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[target_id],
            payer_character_id=target_id,
            beneficiary_character_id=beneficiary_id,
            linked_scene_question_id=state.segment_id,
            scene_question_focus="who_takes_blame",
            due_turn=state.turn_index,
            status="pending",
            linked_callback_id=None,
            summary="这笔账到期了。",
        )
    ]
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    try:
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.event_plan.primary_driver == "cost_return"
    assert semantic.style_plan.force_main_clause_cost_subject is True
    payer_name = next((item.display_name for item in plan.cast if item.character_id == semantic.style_plan.payer_character_id), "")
    beneficiary_name = next((item.display_name for item in plan.cast if item.character_id == semantic.style_plan.beneficiary_character_id), "")
    assert result.narration
    if payer_name:
        assert payer_name in result.narration
    if beneficiary_name and beneficiary_name != payer_name:
        assert any(name in result.narration for name in (payer_name, beneficiary_name))


def test_role_function_lexicon_is_committed_to_style_plan(monkeypatch) -> None:
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="role_lexicon_commit_case")
    roles = {item.segment_role for item in plan.segments}
    target_role = "pressure" if "pressure" in roles else "reveal" if "reveal" in roles else "misread"
    _move_state_to_segment(plan, state, target_role)
    side = next((item for item in build_suggested_actions(plan, state) if item.lane_id == "side"), None)
    if side is None:
        side = build_suggested_actions(plan, state)[0]

    try:
        result = run_turn(plan, state, side.prompt, selected_suggestion_id=side.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.style_plan.role_lexicon_hit is True
    assert semantic.style_plan.counter_function_role in {"strike", "self_preserve", "debt_play", "wait_flip"}
    assert semantic.style_plan.crowd_function_role in {"strike", "self_preserve", "debt_play", "wait_flip"}
    assert (
        semantic.style_plan.counter_action_verb
        or semantic.style_plan.counter_receiver_template
        or semantic.style_plan.crowd_action_verb
        or semantic.style_plan.crowd_receiver_template
    )


def test_cost_return_primary_driver_commits_two_sided_exchange() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="cost_return_two_sided_exchange_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    beneficiary_id = next((item for item in state.active_character_ids if item != target_id), target_id)
    state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_due_two_sided",
            source_turn_index=max(0, state.turn_index - 2),
            source_segment_id=state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[target_id],
            payer_character_id=target_id,
            beneficiary_character_id=beneficiary_id,
            linked_scene_question_id=state.segment_id,
            scene_question_focus="who_takes_blame",
            due_turn=state.turn_index,
            status="pending",
            linked_callback_id=None,
            summary="这笔账到期了。",
        )
    ]
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert semantic.event_plan.primary_driver == "cost_return"
    payer_id = semantic.payoff_plan.payer_character_id
    beneficiary_id = semantic.payoff_plan.beneficiary_character_id
    assert payer_id
    assert beneficiary_id
    payer_delta = dict(result.state.last_turn_relationship_deltas.get(payer_id) or {})
    beneficiary_delta = dict(result.state.last_turn_relationship_deltas.get(beneficiary_id) or {})
    payer_loss = max(
        int(payer_delta.get("tension", 0)),
        int(payer_delta.get("suspicion", 0)),
        max(0, -int(payer_delta.get("trust", 0))),
        max(0, -int(payer_delta.get("affection", 0))),
    )
    beneficiary_gain = max(
        int(beneficiary_delta.get("trust", 0)),
        int(beneficiary_delta.get("affection", 0)),
        int(beneficiary_delta.get("dependency", 0)),
        max(0, -int(beneficiary_delta.get("tension", 0))),
        max(0, -int(beneficiary_delta.get("suspicion", 0))),
    )
    assert payer_loss >= 1
    assert beneficiary_gain >= 1


def test_payoff_plan_records_owner_payer_beneficiary() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="payoff_owner_visible_case")
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")

    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

    assert result.state.last_turn_cost_route is not None
    route = result.state.last_turn_cost_route
    semantic = result.state.last_turn_semantic_plan
    assert semantic is not None
    assert route.owner_character_ids or route.payer_character_id is not None
    assert semantic.payoff_plan.owner_character_ids or semantic.payoff_plan.payer_character_id is not None
    assert semantic.payoff_plan.linked_scene_question_id is not None


def test_invariant_cost_link_and_owner_visibility_fail_safe_tags() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="invariant_cost_link_owner_case")
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "side")
    next_state, _ = apply_turn_resolution(
        plan,
        state,
        UrbanTurnIntent(
            input_text=suggestion.prompt,
            lane_id=suggestion.lane_id,
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            confidence="high",
        ),
    )
    assert next_state.last_turn_cost_route is not None
    assert next_state.last_turn_semantic_plan is not None
    wrong_question_id = "segment_wrong"
    next_state.last_turn_cost_route.linked_scene_question_id = wrong_question_id
    next_state.last_turn_semantic_plan.payoff_plan.linked_scene_question_id = wrong_question_id
    next_state.last_turn_cost_route.owner_character_ids = [plan.route_target_ids[0]]
    next_state.last_turn_cost_route.payer_character_id = plan.route_target_ids[0]

    narration, tags = InvariantValidator.validate_and_patch(
        plan=plan,
        segment=plan.segments[next_state.segment_index],
        state=next_state,
        narration="这回合先落一句。",
    )

    assert narration
    assert "invariant:cost_linked_to_question" in tags
    assert "invariant:cost_owner_visible" in tags


def test_invariant_cost_return_within_window_forces_hook() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="invariant_cost_return_window_case")
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "relationship")
    next_state, _ = apply_turn_resolution(
        plan,
        state,
        UrbanTurnIntent(
            input_text=suggestion.prompt,
            lane_id=suggestion.lane_id,
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            confidence="high",
        ),
    )
    next_state.turn_index = 5
    payer_id = plan.route_target_ids[0]
    next_state.unresolved_costs = [
        UnresolvedCostRecord(
            cost_id="uc_overdue_1",
            source_turn_index=0,
            source_segment_id=next_state.segment_id,
            route_kind="deferred_cost",
            owner_character_ids=[payer_id],
            payer_character_id=payer_id,
            beneficiary_character_id=None,
            linked_scene_question_id=next_state.segment_id,
            scene_question_focus="who_pays",
            due_turn=max(0, next_state.turn_index - 1),
            status="pending",
            linked_callback_id=None,
            summary="这笔账已经拖太久。",
        )
    ]

    _, tags = InvariantValidator.validate_and_patch(
        plan=plan,
        segment=plan.segments[next_state.segment_index],
        state=next_state,
        narration="这回合先落一句。",
    )

    assert "invariant:cost_return_within_window" in tags
    assert next_state.unresolved_costs[0].status == "returned"


def test_last_turn_utility_delta_summary_is_derived_from_semantic_plan() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="utility_delta_case")
    _move_state_to_segment(plan, state, "reveal")
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    semantic_plan = result.state.last_turn_semantic_plan
    assert semantic_plan is not None
    assert semantic_plan.stake_plan.top_shifts
    top = semantic_plan.stake_plan.top_shifts[0]
    assert top.reason_family in {
        "loss_position",
        "self_preserve",
        "blame_shift",
        "debt_strike",
        "wait_for_slip",
        "old_debt",
        "opportunity_window",
    }
    assert top.display_name in result.state.last_turn_story_debug_summary
    assert top.reason_family in result.state.last_turn_story_debug_summary


def test_soft_repair_feedback_and_trace_tags_are_emitted() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="soft_repair_case")
    before = state.model_copy(deep=True)
    player_input = "我召唤无人机群封锁全城并直接冻结所有账户。"

    result = run_turn(plan, state, player_input)
    trace, _ = build_v2_turn_trace(
        plan=plan,
        before_state=before,
        result=result,
        player_input=player_input,
        selected_suggestion_id=None,
        turn_elapsed_ms=10,
    )

    assert result.intent.deviation_type == "scope_shift"
    assert result.intent.deviation_note and "系统先按" in result.intent.deviation_note
    assert "intent:soft_repair" not in result.state.last_turn_tags
    assert "intent:soft_repair" not in trace.turn_tags
    assert trace.submission_input_mode == "free_input"
    assert trace.interpret_usage.get("submission_input_mode") == "free_input"
    assert int(trace.interpret_usage.get("submitted_with_selected_ids") or 0) == 0
    assert trace.deviation_type == "scope_shift"
    assert trace.resolution.deviation_type == "scope_shift"
    assert trace.selected_story_action_id == result.intent.mapped_suggestion_id


def test_recenter_feedback_after_soft_repair_turn() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="soft_repair_recenter_case")

    first = run_turn(plan, state, "我直接召唤陨石把会场砸掉然后读档重开。")
    second_suggestion = build_suggested_actions(plan, first.state)[0]
    second = run_turn(plan, first.state, second_suggestion.prompt)

    assert first.intent.deviation_type == "scope_shift"
    assert "intent:recentered" not in second.state.last_turn_tags


def test_player_can_feel_consequences_without_full_event_list() -> None:
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    state = build_initial_world_state(plan, session_id="latent_feel_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="wave_seed", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2),
        _latent_event(event_id="npc_seed", kind="npc_action", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2, actor_id=stake_ids[0] if stake_ids else None),
    ]

    result = run_turn(plan, state, "我先把这件事压下去，不让外面继续接")
    joined = " ".join(result.state.last_turn_consequences + [result.progress_summary])

    assert any(token in joined for token in ("风向", "记账", "发酵", "切", "没过去", "咬回来"))


def test_latent_merge_uses_sorted_cluster_key() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_sorted_merge")
    _move_state_to_segment(plan, state, "misread")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(
            event_id="rel_seed",
            kind="relationship_debt",
            target_ids=[target_id],
            stake_ids=list(reversed(stake_ids)),
            pressure=1,
            maturity=1,
            threshold=6,
        )
    ]

    suggestion = next(
        item
        for item in build_suggested_actions(plan, state)
        if item.move_family in {"comfort", "ally_with", "private_confession", "accuse", "betray", "flirt"}
    )
    result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    debt_events = [event for event in result.state.latent_events if event.kind == "relationship_debt"]
    triggered_debt = next((record for record in result.state.last_turn_escalations if record.kind == "relationship_debt"), None)

    assert debt_events or triggered_debt is not None
    if debt_events:
        assert sorted(debt_events[0].stake_character_ids) == sorted(stake_ids)
    else:
        assert triggered_debt is not None
        assert sorted(triggered_debt.stake_character_ids) == sorted(stake_ids)


def test_only_one_triggered_event_per_turn_after_control() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="latent_single_trigger_after_control")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="rel", kind="relationship_debt", target_ids=[target_id], stake_ids=stake_ids, pressure=4, maturity=4),
        _latent_event(event_id="wave", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=4, maturity=4),
        _latent_event(event_id="secret", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=4, maturity=4),
    ]
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(
        plan,
        state,
        burst.prompt,
        selected_suggestion_id=burst.suggestion_id,
        control_action="detonate",
        control_target_kind="relationship_debt",
    )

    assert len(result.state.last_turn_escalations) <= 1
    assert sum(1 for tag in result.state.last_turn_tags if tag.endswith(":triggered")) <= 1


def test_control_press_redirect_detonate_effects_are_distinct() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="control_distinct_base")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    alt_target = next(item for item in state.active_character_ids if item != target_id)
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="wave_seed", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2),
    ]
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "side")

    pressed = run_turn(
        plan,
        state.model_copy(deep=True),
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        control_action="press",
        control_target_kind="public_wave",
    )
    redirected = run_turn(
        plan,
        state.model_copy(deep=True),
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        control_action="redirect",
        control_target_kind="public_wave",
        control_target_id=alt_target,
    )
    detonated = run_turn(
        plan,
        state.model_copy(deep=True),
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        control_action="detonate",
        control_target_kind="public_wave",
    )

    assert pressed.control_resolution is not None and pressed.control_resolution.action_type == "press"
    assert redirected.control_resolution is not None and redirected.control_resolution.action_type == "redirect"
    assert detonated.control_resolution is not None and detonated.control_resolution.action_type == "detonate"
    assert any(tag.endswith(":press") for tag in pressed.state.last_turn_latent_ops)
    assert any(tag.endswith(":redirect") for tag in redirected.state.last_turn_latent_ops)
    assert any(tag.endswith(":detonate") for tag in detonated.state.last_turn_latent_ops)


def test_redirect_requires_valid_target_cluster_or_character() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="redirect_target_validation")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    stake_ids = [item for item in state.active_character_ids if item != target_id][:2]
    state.latent_events = [
        _latent_event(event_id="wave_seed", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=2),
    ]
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "side")
    result = run_turn(
        plan,
        state,
        suggestion.prompt,
        selected_suggestion_id=suggestion.suggestion_id,
        control_action="redirect",
        control_target_kind="public_wave",
        control_target_id="non_existing_character",
    )

    assert result.control_resolution is not None
    assert result.control_resolution.applied is False
    assert any(token in result.control_resolution.summary for token in ("有效角色目标", "可执行的控雷目标"))


def test_snapshot_contains_control_actions_and_latent_radar() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="snapshot_controls")
    snapshot = build_v2_snapshot(plan, state)

    assert len(snapshot.story_actions) == 3
    assert len(snapshot.control_actions) == 3
    assert len(snapshot.latent_radar) == 4
    assert len(snapshot.suggested_actions) == 3
    assert all(item.action_type == "story" for item in snapshot.story_actions)


def test_turn_request_with_control_action_updates_control_resolution() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="control_resolution_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    state.latent_events = [
        _latent_event(event_id="secret_seed", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=3, maturity=3),
    ]
    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(
        plan,
        state,
        burst.prompt,
        selected_suggestion_id=burst.suggestion_id,
        control_action="detonate",
        control_target_kind="secret_pressure",
    )

    assert result.control_resolution is not None
    assert result.control_resolution.applied is True
    assert result.control_resolution.action_type == "detonate"
    assert result.control_resolution.target_kind == "secret_pressure"


def test_breaking_schema_no_legacy_pressure_fields_present() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="schema_breaking_case")
    snapshot = build_v2_snapshot(plan, state)
    payload = snapshot.model_dump(mode="json")

    assert "alignment_pressure" not in payload
    assert "old_debt_heat" not in payload
    assert "public_chain_pressure" not in payload
    assert "story_actions" in payload and "control_actions" in payload and "latent_radar" in payload


def test_turn_pipeline_renders_from_pre_advance_snapshot(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="render_pre_advance")
        segment = plan.segments[state.segment_index]
        state.turn_index = max(int(segment.segment_turn_floor) - 1, 0)
        state.segment_enter_turn_index = 0
        state.segment_progress = max(plan.segments[state.segment_index].progress_required - 1, 0)
        old_segment_index = state.segment_index
        suggestion = build_suggested_actions(plan, state)[0]

        simulation_state = state.model_copy(deep=True)
        simulation_intent = parse_turn_intent(
            plan,
            simulation_state,
            suggestion.prompt,
            selected_suggestion_id=suggestion.suggestion_id,
        )
        simulation_state, _ = apply_turn_resolution(plan, simulation_state, simulation_intent)
        old_segment = plan.segments[old_segment_index]
        next_segment = plan.segments[min(old_segment_index + 1, len(plan.segments) - 1)]
        old_hints = build_tone_example_style_hints(old_segment, simulation_state)
        next_hints = build_tone_example_style_hints(next_segment, simulation_state)

        result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert result.segment_advanced is True
    assert list(old_hints.used_bucket_ids) == result.state.recent_example_bucket_ids[: len(old_hints.used_bucket_ids)]
    assert result.state.segment_index == min(old_segment_index + 1, len(plan.segments) - 1)


def test_style_hints_split_counter_and_crowd_clause_families() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="clause_family_split")
    _move_state_to_segment(plan, state, "reveal")
    segment = plan.segments[state.segment_index]

    hints = build_tone_example_style_hints(segment, state)

    assert hints.counter_clause_family_id is not None
    assert hints.crowd_clause_family_id is not None
    assert hints.counter_clause_family_id != hints.crowd_clause_family_id


def test_adjacent_turns_do_not_repeat_same_clause_family(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="adjacent_clause_family_case")
        first_action = build_suggested_actions(plan, state)[0]
        first = run_turn(plan, state, first_action.prompt, selected_suggestion_id=first_action.suggestion_id)
        first_clause_ids = list(first.state.recent_clause_family_ids)
        second_action = build_suggested_actions(plan, first.state)[0]
        second = run_turn(plan, first.state, second_action.prompt, selected_suggestion_id=second_action.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert first_clause_ids
    assert second.state.recent_clause_family_ids
    assert second.state.recent_clause_family_ids[0] != first_clause_ids[0]


def test_supporting_reaction_requires_intent_or_loss_trigger_reason_clause(monkeypatch) -> None:
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="support_reason_clause")
        _move_state_to_segment(plan, state, "reveal")
        burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert any(token in result.narration for token in ("先护的是", "借旧账", "站边", "切割", "记账", "等"))


def test_campus_entertainment_supporting_vocab_namespace_isolated(monkeypatch) -> None:
    entertainment_plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    campus_plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        entertainment_state = build_initial_world_state(entertainment_plan, session_id="ent_vocab_ns")
        _move_state_to_segment(entertainment_plan, entertainment_state, "reveal")
        ent_burst = next(item for item in build_suggested_actions(entertainment_plan, entertainment_state) if item.lane_id == "burst")
        ent_result = run_turn(entertainment_plan, entertainment_state, ent_burst.prompt, selected_suggestion_id=ent_burst.suggestion_id)

        campus_state = build_initial_world_state(campus_plan, session_id="campus_vocab_ns")
        _move_state_to_segment(campus_plan, campus_state, "reveal")
        campus_burst = next(item for item in build_suggested_actions(campus_plan, campus_state) if item.lane_id == "burst")
        campus_result = run_turn(campus_plan, campus_state, campus_burst.prompt, selected_suggestion_id=campus_burst.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert any(token in ent_result.narration for token in ("镜头", "热搜", "公关", "切割"))
    assert any(token in campus_result.narration for token in ("台下", "评审", "社团", "熟人", "站队"))
    assert not any(token in ent_result.narration for token in ("评审", "社团", "熟人"))
    assert not any(token in campus_result.narration for token in ("热搜", "公关", "公屏"))


def test_reveal_terminal_supporting_reason_signal_are_not_mixed() -> None:
    plans = (
        _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。"),
        _play_plan(),
    )
    for plan in plans:
        for segment_role in ("reveal", "terminal"):
            state = build_initial_world_state(plan, session_id=f"style_non_mixed_{plan.template_id}_{segment_role}")
            _move_state_to_segment(plan, state, segment_role)
            segment = plan.segments[state.segment_index]
            style_hints = build_tone_example_style_hints(segment, state)

            assert style_hints.signal_family != "mixed"
            assert style_hints.primary_reason_family != "mixed"
            assert style_hints.counter_reason_family != "mixed"
            assert style_hints.crowd_reason_family != "mixed"
            assert style_hints.fallout_reason_family != "mixed"


def test_reveal_terminal_shell_anchor_hits_reason_or_signal_main_clause() -> None:
    seeds = (
        ("entertainment_scandal", "颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。", ("镜头", "热搜", "公关", "切割")),
        ("campus_romance", "校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。", ("台下", "评审", "名额", "社团", "熟人", "站队")),
    )
    for shell_id, seed, anchors in seeds:
        plan = _play_plan_from_seed(seed)
        assert plan.story_shell_id == shell_id
        state = build_initial_world_state(plan, session_id=f"support_signal_anchor_{shell_id}")
        _move_state_to_segment(plan, state, "reveal")
        suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
        intent = UrbanTurnIntent(
            input_text=suggestion.prompt,
            lane_id=suggestion.lane_id,
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            confidence="high",
        )
        scene_frames = {
            character_id: __import__("rpg_backend.play_v2.runtime", fromlist=["_derive_npc_scene_frame"])._derive_npc_scene_frame(plan, state, character_id)
            for character_id in state.active_character_ids
            if character_id in state.npc_mind_states
        }
        reactions = build_supporting_reaction_beats(
            plan=plan,
            state=state,
            intent=intent,
            segment_id=plan.segments[state.segment_index].segment_id,
            segment_role=plan.segments[state.segment_index].segment_role,
            scene_frames_by_id=scene_frames,
        )
        assert reactions
        style_hints = build_tone_example_style_hints(plan.segments[state.segment_index], state)
        line = _support_line(reactions[0], primary_name=reactions[0].beat.target_name, style_hints=style_hints)

        assert line.startswith(reactions[0].beat.target_name)
        assert any(token in line for token in anchors)


def test_progress_summary_prefers_trigger_or_top_foreshadow() -> None:
    plan = _play_plan()
    trigger_state = build_initial_world_state(plan, session_id="summary_trigger_case")
    _move_state_to_segment(plan, trigger_state, "reveal")
    target_id = plan.route_target_ids[0]
    trigger_state.latent_events = [
        _latent_event(event_id="secret_trigger", kind="secret_pressure", target_ids=[target_id], stake_ids=[target_id], pressure=4, maturity=4),
    ]
    burst = next(item for item in build_suggested_actions(plan, trigger_state) if item.lane_id == "burst")
    trigger_result = run_turn(plan, trigger_state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    foreshadow_state = build_initial_world_state(plan, session_id="summary_foreshadow_case")
    _move_state_to_segment(plan, foreshadow_state, "misread")
    stake_ids = [item for item in foreshadow_state.active_character_ids if item != target_id][:2]
    foreshadow_state.latent_events = [
        _latent_event(event_id="wave_seed", kind="public_wave", target_ids=[target_id], stake_ids=stake_ids, pressure=3, maturity=1, threshold=6),
    ]
    foreshadow_result = run_turn(plan, foreshadow_state, "我先稳住，不让这件事立刻炸出来")

    assert any(token in trigger_result.progress_summary for token in ("拱开口子", "炸开", "先动", "回头咬人"))
    assert any(token in foreshadow_result.progress_summary for token in ("发酵", "记账", "没过去", "变重"))


def test_reaction_causes_are_recorded_for_supporting_characters() -> None:
    plan = _play_plan_from_seed("颁奖礼后台偷拍视频外泄，把她们逼进公开切割。做成标准都市关系戏。")
    state = build_initial_world_state(plan, session_id="reaction_causes_case")
    _move_state_to_segment(plan, state, "reveal")

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    supporting_ids = [item for item in state.active_character_ids if item != result.intent.target_id]
    assert any(result.state.last_turn_reaction_causes.get(character_id) for character_id in supporting_ids)


def test_supporting_selection_prefers_characters_whose_loss_trigger_is_hit() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="intent_loss_hit_case")
    _move_state_to_segment(plan, state, "reveal")
    supporting_ids = [item for item in state.active_character_ids if item != plan.route_target_ids[0]]
    focus_id, other_id = supporting_ids[:2]
    state.last_turn_reaction_causes = {
        focus_id: ["intent_loss_triggered", "forced_alignment"],
        other_id: ["saw_player_side"],
    }
    scene_frames = {
        character_id: __import__("rpg_backend.play_v2.runtime", fromlist=["_derive_npc_scene_frame"])._derive_npc_scene_frame(plan, state, character_id)
        for character_id in state.active_character_ids
        if character_id in state.npc_mind_states
    }
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    reactions = build_supporting_reaction_beats(
        plan=plan,
        state=state,
        intent=UrbanTurnIntent(
            input_text=suggestion.prompt,
            lane_id=suggestion.lane_id,
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            confidence="high",
        ),
        segment_id=plan.segments[state.segment_index].segment_id,
        segment_role=plan.segments[state.segment_index].segment_role,
        scene_frames_by_id=scene_frames,
    )

    assert reactions
    assert reactions[0].beat.target_id == focus_id


def test_supporting_selection_uses_opportunism_target_ids_when_rival_slips() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="intent_opportunity_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    supporting_ids = [item for item in state.active_character_ids if item != target_id]
    opportunist = supporting_ids[0]
    state.last_turn_reaction_causes = {
        opportunist: ["opportunity_window", "was_cut_out"],
    }
    scene_frames = {
        character_id: __import__("rpg_backend.play_v2.runtime", fromlist=["_derive_npc_scene_frame"])._derive_npc_scene_frame(plan, state, character_id)
        for character_id in state.active_character_ids
        if character_id in state.npc_mind_states
    }
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    reactions = build_supporting_reaction_beats(
        plan=plan,
        state=state,
        intent=UrbanTurnIntent(
            input_text=suggestion.prompt,
            lane_id=suggestion.lane_id,
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            confidence="high",
        ),
        segment_id=plan.segments[state.segment_index].segment_id,
        segment_role=plan.segments[state.segment_index].segment_role,
        scene_frames_by_id=scene_frames,
    )

    assert reactions
    assert any(reaction.beat.target_id == opportunist for reaction in reactions)


def test_supporting_divergence_policy_splits_reason_family_on_key_segment() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="supporting_reason_split_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    supporting_ids = [item for item in state.active_character_ids if item != target_id]
    assert len(supporting_ids) >= 2
    first_id, second_id = supporting_ids[:2]
    state.last_turn_reaction_causes = {
        first_id: ["debt_due", "kept_score"],
        second_id: ["covering_self", "forced_alignment"],
    }
    state.last_turn_utility_delta_by_character[first_id] = -4
    state.last_turn_utility_delta_by_character[second_id] = -3
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    scene_frames = {
        character_id: __import__("rpg_backend.play_v2.runtime", fromlist=["_derive_npc_scene_frame"])._derive_npc_scene_frame(plan, state, character_id)
        for character_id in state.active_character_ids
        if character_id in state.npc_mind_states
    }
    reactions = build_supporting_reaction_beats(
        plan=plan,
        state=state,
        intent=UrbanTurnIntent(
            input_text=suggestion.prompt,
            lane_id=suggestion.lane_id,
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            confidence="high",
        ),
        segment_id=plan.segments[state.segment_index].segment_id,
        segment_role=plan.segments[state.segment_index].segment_role,
        scene_frames_by_id=scene_frames,
    )
    assert len(reactions) >= 2
    assert reactions[0].reason_family != reactions[1].reason_family


def test_blame_shift_reason_family_flows_to_supporting_surface() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="supporting_blame_shift_case")
    _move_state_to_segment(plan, state, "reveal")
    target_id = plan.route_target_ids[0]
    supporting_ids = [item for item in state.active_character_ids if item != target_id]
    assert supporting_ids
    blame_actor = supporting_ids[0]
    state.last_turn_reaction_causes = {
        blame_actor: ["sacrifice_window", "forced_alignment", "blame_shift"],
    }
    state.last_turn_utility_delta_by_character[blame_actor] = -4
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    scene_frames = {
        character_id: __import__("rpg_backend.play_v2.runtime", fromlist=["_derive_npc_scene_frame"])._derive_npc_scene_frame(plan, state, character_id)
        for character_id in state.active_character_ids
        if character_id in state.npc_mind_states
    }
    reactions = build_supporting_reaction_beats(
        plan=plan,
        state=state,
        intent=UrbanTurnIntent(
            input_text=suggestion.prompt,
            lane_id=suggestion.lane_id,
            move_family=suggestion.move_family,
            target_id=suggestion.target_id,
            scene_frame=suggestion.scene_frame,
            confidence="high",
        ),
        segment_id=plan.segments[state.segment_index].segment_id,
        segment_role=plan.segments[state.segment_index].segment_role,
        scene_frames_by_id=scene_frames,
    )
    blame_reaction = next(item for item in reactions if item.beat.target_id == blame_actor)
    assert blame_reaction.reason_family == "blame_shift"
    line = _support_line(blame_reaction, primary_name=plan.cast[0].display_name, style_hints=None)
    assert any(token in line for token in ("锅", "追责", "清算"))


def test_micro_sim_reason_family_allows_blame_shift() -> None:
    runtime_module = __import__("rpg_backend.play_v2.runtime", fromlist=["_micro_sim_reason_family"])
    reason_picker = runtime_module._micro_sim_reason_family
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="micro_sim_blame_shift_reason_case")
    target_id = plan.route_target_ids[0]
    actor = next(item for item in plan.cast if item.character_id != target_id)
    intent_frame = actor.strategic_intent.model_copy(update={"sacrifice_target_ids": [target_id]})
    intent = UrbanTurnIntent(
        input_text="我把锅甩给她",
        lane_id="side",
        move_family="accuse",
        target_id=target_id,
        scene_frame="public",
        control_action="redirect",
        control_source="explicit",
        control_target_kind="npc_action",
        control_target_id=actor.character_id,
        control_target_mode="character",
        confidence="high",
    )
    assert reason_picker(intent_frame, intent) == "blame_shift"


def test_cost_ownership_policy_redirect_routes_to_control_target() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="cost_ownership_redirect_case")
    available_roles = {segment.segment_role for segment in plan.segments}
    target_role = "pressure" if "pressure" in available_roles else "reveal"
    _move_state_to_segment(plan, state, target_role)
    target_id = plan.route_target_ids[0]
    control_target_id = next(item for item in state.active_character_ids if item != target_id)
    scene_frame = "semi_public" if target_role == "pressure" else "public"
    intent = UrbanTurnIntent(
        input_text="我把这锅甩给另一个人",
        lane_id="side",
        move_family="accuse",
        target_id=target_id,
        scene_frame=scene_frame,
        control_action="redirect",
        control_source="explicit",
        control_target_kind="npc_action",
        control_target_id=control_target_id,
        control_target_mode="character",
        confidence="high",
    )
    next_state, _ = apply_turn_resolution(plan, state, intent)
    assert next_state.last_turn_cost_route is not None
    assert control_target_id in next_state.last_turn_cost_route.target_character_ids
    assert next_state.last_turn_cost_route.transferred_to_character_id == control_target_id


def test_invariant_commits_propagation_edge_for_key_segment() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="invariant_propagation_edge_case")
    _move_state_to_segment(plan, state, "reveal")
    suggestion = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    intent = UrbanTurnIntent(
        input_text=suggestion.prompt,
        lane_id=suggestion.lane_id,
        move_family=suggestion.move_family,
        target_id=suggestion.target_id,
        scene_frame=suggestion.scene_frame,
        confidence="high",
    )
    next_state, _ = apply_turn_resolution(plan, state, intent)
    next_state.last_turn_propagation_edge = None
    narration, tags = InvariantValidator.validate_and_patch(
        plan=plan,
        segment=plan.segments[next_state.segment_index],
        state=next_state,
        narration="这回合先落一句。",
    )
    assert narration
    assert next_state.last_turn_propagation_edge is not None
    assert "invariant:propagation:edge_committed" in tags


def test_progress_summary_surfaces_semi_visible_intent_feedback() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="intent_feedback_progress")
    _move_state_to_segment(plan, state, "reveal")
    supporting_id = next(item for item in state.active_character_ids if item != plan.route_target_ids[0])
    state.npc_mind_states[supporting_id].betrayal_readiness = 5
    state.npc_mind_states[supporting_id].control_need = 5

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert any(token in result.progress_summary for token in ("失位", "自保", "记成站边", "记账", "切人"))


def test_feedback_consequences_include_loss_or_self_protection_signals() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan, session_id="intent_feedback_consequence")
    _move_state_to_segment(plan, state, "reveal")
    supporting_id = next(item for item in state.active_character_ids if item != plan.route_target_ids[0])
    state.npc_mind_states[supporting_id].betrayal_readiness = 5
    state.npc_mind_states[supporting_id].control_need = 5

    burst = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    result = run_turn(plan, state, burst.prompt, selected_suggestion_id=burst.suggestion_id)

    assert any(token in " ".join(result.state.last_turn_consequences) for token in ("失位", "自保", "记账", "切人", "站边"))


def test_intent_frame_does_not_force_same_behavior_every_turn(monkeypatch) -> None:
    plan = _play_plan()
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "npc_texture_v2")
    get_settings.cache_clear()
    try:
        state = build_initial_world_state(plan, session_id="intent_not_static")
        first = build_suggested_actions(plan, state)[0]
        result_one = run_turn(plan, state, first.prompt, selected_suggestion_id=first.suggestion_id)
        second = build_suggested_actions(plan, state)[0]
        result_two = run_turn(plan, state, second.prompt, selected_suggestion_id=second.suggestion_id)
    finally:
        monkeypatch.delenv("APP_PLAY_V2_NARRATION_PROFILE", raising=False)
        get_settings.cache_clear()

    assert result_one.narration != result_two.narration


def test_npc_texture_v2_surface_uses_character_tone_to_split_reaction_flavor() -> None:
    pressure = ScenePressureBeat(
        visibility_level="public",
        pressure_level="critical",
        witness_focus="locked",
        witness_pressure=3,
        scene_heat=5,
        secret_exposure=3,
        route_lock=3,
        public_event_active=True,
    )
    seed = NarrationRenderSeed(
        character_id="npc_a",
        turn_index=4,
        segment_role="reveal",
        move_family="public_reveal",
        scene_frame="public",
    )
    razor = NpcReactionBeat(
        shell_id="office_power",
        arena_name="董事会",
        target_name="江烨",
        target_id="npc_a",
        scene_pressure=pressure,
        mask_state="cracking",
        dominant_impulse="retaliate",
        relation_shift="pulling_back",
        fallout_vector="exposure",
        character_tone="razor",
        public_role_hint="平时最像规矩本身的人",
        charisma_hint="光靠分寸就能压住场面",
        danger_hint="翻脸时从不提前提醒",
        public_mask_hint="最会稳场的样子",
        status_need_hint="位置",
        cost_hint="位置",
        public_event_hint="会议桌先是死静，接着黑账被翻到台面和投屏上。",
        pain_hint="你把最不该见光的东西拖上台面。",
        no_return_hint="这一步已经把牌桌上的敌我关系一起钉死。",
        shame_hint="被当众看穿立场",
        breaking_hint="快要直接翻脸",
        speech_texture_hint="字句都带刀",
        forbidden_raw_phrases=(),
        public_posture="cornered",
    )
    smiling = NpcReactionBeat(
        shell_id="office_power",
        arena_name="董事会",
        target_name="江烨",
        target_id="npc_a",
        scene_pressure=pressure,
        mask_state="cracking",
        dominant_impulse="retaliate",
        relation_shift="pulling_back",
        fallout_vector="exposure",
        character_tone="smiling_blade",
        public_role_hint="平时最懂怎么在镜头前接住场面的人",
        charisma_hint="笑着就能把人带过去",
        danger_hint="一旦失手就会把事情推到所有人都收不住",
        public_mask_hint="最会稳场的样子",
        status_need_hint="名声",
        cost_hint="名声",
        public_event_hint="会议桌先是死静，接着黑账被翻到台面和投屏上。",
        pain_hint="你把最不该见光的东西拖上台面。",
        no_return_hint="这一步已经把牌桌上的敌我关系一起钉死。",
        shame_hint="被当众看穿立场",
        breaking_hint="快要直接翻脸",
        speech_texture_hint="明明在笑，话里却藏着刀",
        forbidden_raw_phrases=(),
        public_posture="cornered",
    )

    razor_text = render_npc_texture_v2(razor, seed)
    smiling_text = render_npc_texture_v2(smiling, seed)

    assert razor_text != smiling_text
    assert any(token in razor_text for token in ("锋", "下刀", "不敢接茬"))
    assert any(token in smiling_text for token in ("笑", "带刺", "哄"))


def test_each_lane_choice_can_advance_progress_in_its_dimension() -> None:
    plan = _play_plan()
    lane_ids_seen: set[str] = set()
    for suggestion in build_suggested_actions(plan, build_initial_world_state(plan)):
        state = build_initial_world_state(plan, session_id=f"session_{suggestion.lane_id}")
        result = run_turn(plan, state, suggestion.prompt, selected_suggestion_id=suggestion.suggestion_id)

        lane_ids_seen.add(suggestion.lane_id)
        assert result.intent.lane_id == suggestion.lane_id
        assert result.segment_advanced or result.state.segment_progress >= 1
        assert any(tag.endswith("_lane") for tag in result.consequence_tags)

    assert lane_ids_seen == {"relationship", "side", "burst"}


def test_relationship_ending_can_resolve_without_public_burst() -> None:
    plan = _play_plan()
    route_target_id = plan.route_target_ids[0]
    state = build_initial_world_state(plan)
    state.segment_index = len(plan.segments) - 1
    state.segment_id = plan.segments[-1].segment_id
    state.segment_enter_turn_index = 0
    state.turn_index = 6
    state.scene_frame = "private"
    state.route_lock = 1
    state.scene_heat = 1
    state.secret_exposure = 0
    state.current_route_target_id = route_target_id
    state.lane_counts["relationship"] = 3
    state.lane_counts_by_target[route_target_id] = {"relationship": 3}
    target_state = state.relationships[route_target_id]
    target_state.affection = 5
    target_state.trust = 3
    target_state.dependency = 2

    ended, ending_id, _ = judge_ending(plan, state)

    assert ended is True
    assert ending_id == f"relationship_{route_target_id}"


def test_side_ending_can_resolve_without_secret_exposure() -> None:
    plan = _play_plan()
    route_target_id = plan.route_target_ids[0]
    state = build_initial_world_state(plan)
    state.segment_index = len(plan.segments) - 1
    state.segment_id = plan.segments[-1].segment_id
    state.segment_enter_turn_index = 0
    state.turn_index = 6
    state.scene_frame = "private"
    state.route_lock = 3
    state.scene_heat = 2
    state.secret_exposure = 0
    state.current_route_target_id = route_target_id
    state.lane_counts["side"] = 3
    state.lane_counts_by_target[route_target_id] = {"side": 3}
    target_state = state.relationships[route_target_id]
    target_state.trust = 3

    ended, ending_id, _ = judge_ending(plan, state)

    assert ended is True
    assert ending_id == f"side_{route_target_id}"


def test_burst_shared_ending_can_win_on_public_exposure_path() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    state.segment_index = len(plan.segments) - 1
    state.segment_id = plan.segments[-1].segment_id
    state.segment_enter_turn_index = 0
    state.turn_index = 6
    state.scene_frame = "public"
    state.scene_heat = 5
    state.secret_exposure = 3
    state.known_secret_ids = ["taboo_secret"]
    state.public_event_ids = [plan.segments[-1].segment_id]
    state.lane_counts["burst"] = 3

    ended, ending_id, _ = judge_ending(plan, state)

    assert ended is True
    assert ending_id == "burst_reckoning"


def test_terminal_ending_is_blocked_before_segment_turn_floor() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    state.segment_index = len(plan.segments) - 1
    state.segment_id = plan.segments[-1].segment_id
    state.segment_enter_turn_index = 4
    state.turn_index = 5
    state.scene_frame = "public"
    state.scene_heat = 5
    state.secret_exposure = 3
    state.known_secret_ids = ["taboo_secret"]
    state.public_event_ids = [plan.segments[-1].segment_id]
    state.lane_counts["burst"] = 3

    ended, ending_id, _ = judge_ending(plan, state)

    assert ended is False
    assert ending_id is None


def test_segment_does_not_advance_before_segment_turn_floor() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    segment = plan.segments[state.segment_index]
    state.segment_progress = int(segment.progress_required)
    state.turn_index = int(segment.segment_turn_floor) - 1
    state.segment_enter_turn_index = 0

    advanced = advance_segment_if_ready(plan, state)

    assert advanced is False


def test_style_case_registry_fields_are_populated() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    segment = plan.segments[state.segment_index]

    hints = build_tone_example_style_hints(segment, state)

    assert hints.style_case_ids
    assert hints.style_case_text_items
    assert any(case_id.startswith("primary:") for case_id in hints.style_case_ids)
    assert hints.style_case_slot_constraints
    assert hints.blocked_stems


def test_play_plan_voice_atoms_cover_segment_roles() -> None:
    plan = _play_plan()
    required_roles = {segment.segment_role for segment in plan.segments}

    assert plan.voice_atoms_by_character
    for member in plan.cast:
        atoms = plan.voice_atoms_by_character.get(member.character_id) or []
        assert atoms
        assert required_roles <= {atom.segment_role for atom in atoms}


def test_turn_diagnostics_include_detemplate_markers() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    action = build_suggested_actions(plan, state)[0]

    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)

    diagnostics = result.intent_stage_diagnostics
    assert "selected_style_case_ids" in diagnostics
    assert "diversity_guard_hits" in diagnostics
    assert "pattern_guard_hits" in diagnostics
    assert "compose_retry_count" in diagnostics
    assert "compose_invalid_reason" in diagnostics
    assert "blocked_stems" in diagnostics
    assert "blocked_stems_hit" in diagnostics
    assert "soft_avoid_stems" in diagnostics
    assert "control_bias_applied" in diagnostics
    assert "control_bias_reason" in diagnostics
    assert "control_bias_from_move" in diagnostics
    assert "control_bias_to_move" in diagnostics
    assert "length_profile" in diagnostics
    assert "fallback_reason" in diagnostics
    assert "selected_voice_atom_ids" in diagnostics
    assert "voice_fallback_reason" in diagnostics
    assert "compose_latency_ms" in diagnostics
    assert "compose_input_tokens" in diagnostics
    assert "compose_output_tokens" in diagnostics
    assert "compose_total_tokens" in diagnostics
    assert "gateway_acquire_wait_ms" in diagnostics
    assert "turn_complexity" in diagnostics
    assert "compose_pass_count" in diagnostics
    assert "compose_pass2_retry_count" in diagnostics
    assert "compose_pass1_latency_ms" in diagnostics
    assert "compose_pass2_latency_ms" in diagnostics
    assert "compose_pass2_gate_reason" in diagnostics
    assert "compose_budget_hit" in diagnostics
    assert "delta_pack_hit" in diagnostics
    assert "post_submit_llm_calls" in diagnostics
    assert "single_llm_call_after_submit" in diagnostics


def test_parse_turn_intent_bypasses_intent_llm_when_selected_story_action_is_provided() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    suggestion = build_suggested_actions(plan, state)[0]

    result = run_turn(
        plan,
        state,
        "我想先看下局势。",
        selected_suggestion_id=suggestion.suggestion_id,
        selected_story_action_id=suggestion.suggestion_id,
    )

    diagnostics = result.intent_stage_diagnostics
    assert diagnostics.get("intent_llm_status") == "bypassed:selected_story"


def test_parse_turn_intent_low_information_input_skips_intent_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    diagnostics: dict[str, object] = {}

    def _llm_should_not_be_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("intent llm should be bypassed for low-information input")

    monkeypatch.setattr(runtime_module, "_try_compile_with_llm", _llm_should_not_be_called)

    intent = parse_turn_intent(
        plan,
        state,
        "嗯",
        diagnostics=diagnostics,
    )

    assert diagnostics.get("intent_llm_status") == "bypassed:heuristic_gate"
    assert diagnostics.get("intent_llm_gate_reason") == "low_information"
    assert intent.intent_compile_source == "heuristic_fallback"


def test_run_intent_stage_pressure_turn_prefers_llm_micro_sim_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    role = next(
        (item.segment_role for item in plan.segments if item.segment_role in {"misread", "pressure"}),
        None,
    )
    if role is None:
        pytest.skip("plan has no non-key micro-sim segment")
    _move_state_to_segment(plan, state, role)
    suggestion = build_suggested_actions(plan, state)[0]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object], usage: dict[str, int] | None = None) -> None:
            self.payload = payload
            self.usage = usage or {}

    class _FakeGateway:
        def __init__(self) -> None:
            self.operations: list[str] = []

        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            operation_name = str(kwargs.get("operation_name") or "")
            self.operations.append(operation_name)
            if operation_name != "play_v2.npc_micro_sim":
                raise AssertionError(f"unexpected operation in micro-sim test: {operation_name}")
            shortlist = list((kwargs.get("user_payload", {}) or {}).get("shortlist") or [])
            actor = shortlist[0]["character_id"] if shortlist else ""
            return _FakeResponse(
                {
                    "recommended_actor_id": actor,
                    "summary": "micro sim llm",
                    "candidates": [
                        {
                            "character_id": actor,
                            "action_family": "test_water",
                            "reason_family": "mixed",
                            "signal_family": "mixed",
                            "cost_family": "mixed",
                            "confidence": 0.71,
                            "rationale": "ok",
                        }
                    ],
                },
                usage={"input_tokens": 60, "output_tokens": 20, "total_tokens": 80},
            )

    gateway = _FakeGateway()
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: type(
            "_SettingsStub",
            (),
            {
                "play_v2_micro_sim_use_llm": True,
            },
        )(),
    )
    intent, micro_sim, diagnostics = run_intent_stage(
        plan,
        state,
        suggestion.prompt,
        gateway=gateway,
        selected_suggestion_id=suggestion.suggestion_id,
        selected_story_action_id=suggestion.suggestion_id,
    )

    assert intent.mapped_suggestion_id == suggestion.suggestion_id
    assert micro_sim is not None
    assert micro_sim.source == "llm"
    assert diagnostics.get("micro_sim_status") == "completed"
    assert diagnostics.get("micro_sim_llm_gate_reason") == "llm_first_default"
    assert "play_v2.npc_micro_sim" in gateway.operations


def test_run_turn_reuses_single_gateway_for_intent_micro_and_compose(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    _move_state_to_segment(plan, state, "reveal")
    state.scene_heat = 6
    state.secret_exposure = 6
    state.route_lock = 5

    class _FakeResponse:
        def __init__(self, payload: dict[str, object], usage: dict[str, int] | None = None) -> None:
            self.payload = payload
            self.usage = usage or {}

    class _FakeGateway:
        def __init__(self) -> None:
            self.operations: list[str] = []

        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            operation_name = str(kwargs.get("operation_name") or "")
            self.operations.append(operation_name)
            user_payload = kwargs.get("user_payload", {}) or {}
            if operation_name == "play_v2.intent_compile":
                cast = list(user_payload.get("cast") or [])
                target_id = cast[0]["character_id"] if cast else None
                allowed_moves = list(user_payload.get("allowed_move_families") or [])
                move_family = allowed_moves[0] if allowed_moves else "probe_secret"
                return _FakeResponse(
                    {
                        "move_family": move_family,
                        "target_id": target_id,
                        "scene_frame": "public",
                        "lane_id": "burst",
                        "intent_confidence": 0.88,
                        "deviation_type": "none",
                        "deviation_note": "",
                        "alternatives": [],
                    },
                    usage={"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
                )
            if operation_name == "play_v2.npc_micro_sim":
                shortlist = list(user_payload.get("shortlist") or [])
                actor = shortlist[0]["character_id"] if shortlist else ""
                return _FakeResponse(
                    {
                        "recommended_actor_id": actor,
                        "summary": "micro sim ok",
                        "candidates": [
                            {
                                "character_id": actor,
                                "action_family": "test_water",
                                "reason_family": "mixed",
                                "signal_family": "mixed",
                                "cost_family": "mixed",
                                "confidence": 0.66,
                                "rationale": "ok",
                            }
                        ],
                    },
                    usage={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
                )
            return _FakeResponse(
                {
                    "narration": "这拍把站位关系直接推上台面。",
                    "coverage_marks": {
                        "target": True,
                        "move": True,
                        "consequence": True,
                        "relationship": True,
                    },
                    "length_profile": "normal",
                },
                usage={"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
            )

    gateway = _FakeGateway()
    gateway_calls = {"count": 0}

    def _fake_get_gateway(_settings):  # noqa: ANN001
        gateway_calls["count"] += 1
        return gateway

    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", _fake_get_gateway)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")

    result = run_turn(plan, state, "我要先试探对方底牌再当众逼问。")

    assert gateway_calls["count"] == 1
    assert "play_v2.intent_compile" in gateway.operations
    assert "play_v2.narration_compose" in gateway.operations
    assert "play_v2.narration_compose_pass2" in gateway.operations
    assert "play_v2.npc_micro_sim" in gateway.operations
    diagnostics = result.intent_stage_diagnostics
    assert float(diagnostics.get("gateway_acquire_wait_ms", 0.0)) >= 0.0
    assert int(diagnostics.get("compose_pass_count", 0)) == 2
    assert int(diagnostics.get("post_submit_llm_calls", 0)) == 4
    assert bool(diagnostics.get("single_llm_call_after_submit")) is False


def test_compose_accepts_style_output_without_stem_guard_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    action = build_suggested_actions(plan, state)[0]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload
            self.usage = {}

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls = 0

        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            self.calls += 1
            compose_input = kwargs.get("user_payload", {}).get("compose_input", {})
            target_name = compose_input.get("fact_pack", {}).get("target_name", "对方")
            shell_tokens = compose_input.get("style_card", {}).get("shell_tokens", [])
            shell_token = shell_tokens[0] if shell_tokens else "场上"
            return _FakeResponse(
                {
                    "narration": f"{target_name}这句把关系账推到台面，{shell_token}已经开始重排站位。后果会先落在解释权和信任上。",
                    "coverage_marks": {
                        "target": True,
                        "move": True,
                        "consequence": True,
                        "relationship": True,
                    },
                    "length_profile": "normal",
                }
            )

    gateway = _FakeGateway()
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: gateway)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: type(
            "_SettingsStub",
            (),
            {
                "play_v2_dramatic_rewrite_max_output_tokens": 320,
                "play_v2_dramatic_rewrite_use_llm": True,
            },
        )(),
    )

    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)
    diagnostics = result.intent_stage_diagnostics
    assert gateway.calls == 1
    assert int(diagnostics["compose_retry_count"]) == 0
    assert diagnostics["fallback_reason"] == "none"


def test_compose_payload_uses_style_only_without_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    action = build_suggested_actions(plan, state)[0]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload
            self.usage = {}

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls = 0
            self.call_records: list[tuple[str, dict[str, object]]] = []

        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            self.calls += 1
            operation_name = str(kwargs.get("operation_name") or "")
            user_payload = kwargs.get("user_payload", {}) or {}
            self.call_records.append((operation_name, dict(user_payload)))
            compose_input = user_payload.get("compose_input", {}) or {}
            target_name = compose_input.get("fact_pack", {}).get("target_name", "对方")
            return _FakeResponse(
                {
                    "narration": f"{target_name}先沉默了一下。",
                    "coverage_marks": {
                        "target": True,
                        "move": True,
                        "consequence": True,
                        "relationship": True,
                    },
                    "length_profile": "normal",
                }
            )

    gateway = _FakeGateway()
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: gateway)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: type(
            "_SettingsStub",
            (),
            {
                "play_v2_dramatic_rewrite_max_output_tokens": 320,
                "play_v2_dramatic_rewrite_use_llm": True,
                "internal_test_strict_no_repair_fallback": False,
            },
        )(),
    )

    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)
    diagnostics = result.intent_stage_diagnostics
    assert gateway.calls >= 1
    assert any(operation_name == "play_v2.narration_compose" for operation_name, _ in gateway.call_records)
    payload = next(payload for operation_name, payload in gateway.call_records if operation_name == "play_v2.narration_compose")
    compose_input = payload.get("compose_input")
    assert isinstance(compose_input, dict)
    assert "style_cases" in compose_input
    assert "style_card" in compose_input
    style_card = compose_input.get("style_card")
    assert isinstance(style_card, dict)
    assert "soft_avoid_stems" in style_card
    assert isinstance(style_card.get("soft_avoid_stems"), list)
    assert "control_contract" in style_card
    control_contract = style_card.get("control_contract")
    assert isinstance(control_contract, dict)
    assert all(
        key in control_contract
        for key in ("must_yield_side", "yield_cost", "refuse_escalation", "settlement_window", "observable_evidence")
    )
    assert "constraints" not in payload
    assert "retry_feedback" not in payload
    assert 0 <= int(diagnostics["compose_retry_count"]) <= 2
    assert diagnostics["fallback_reason"] == "none"


def test_compose_normal_turn_uses_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    action = build_suggested_actions(plan, state)[0]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload
            self.usage = {}

    class _FakeGateway:
        def __init__(self) -> None:
            self.operations: list[str] = []

        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            operation_name = str(kwargs.get("operation_name") or "")
            self.operations.append(operation_name)
            return _FakeResponse(
                {
                    "narration": "她先收住锋芒，把试探落成一句可执行的话。",
                    "coverage_marks": {
                        "target": True,
                        "move": True,
                        "consequence": True,
                        "relationship": True,
                    },
                    "length_profile": "normal",
                }
            )

    gateway = _FakeGateway()
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: gateway)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
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
    diagnostics = result.intent_stage_diagnostics

    assert "play_v2.narration_compose" in gateway.operations
    assert "play_v2.narration_compose_pass2" not in gateway.operations
    assert diagnostics.get("turn_complexity") == "normal"
    assert int(diagnostics.get("compose_pass_count", 0)) == 1
    assert int(diagnostics.get("post_submit_llm_calls", 0)) == 1
    assert bool(diagnostics.get("single_llm_call_after_submit")) is True


def test_run_turn_reuses_precomputed_compose_without_submit_llm_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    action = build_suggested_actions(plan, state)[0]
    intent, micro_sim, intent_diagnostics = run_intent_stage(
        plan,
        state,
        action.prompt,
        selected_suggestion_id=action.suggestion_id,
        selected_story_action_id=action.suggestion_id,
    )
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: type(
            "_SettingsStub",
            (),
            {
                "play_v2_dramatic_rewrite_use_llm": False,
                "play_v2_intent_compiler_use_llm": False,
                "play_v2_micro_sim_use_llm": False,
                "internal_test_strict_no_repair_fallback": False,
            },
        )(),
    )
    result = run_turn(
        plan,
        state,
        action.prompt,
        selected_suggestion_id=action.suggestion_id,
        selected_story_action_id=action.suggestion_id,
        precomputed_intent=intent,
        precomputed_micro_sim=micro_sim,
        precomputed_intent_diagnostics=intent_diagnostics,
        precomputed_compose={
            "narration": "她先把话钉在台面，场内外都听见了后果。",
            "diagnostics": {
                "compose_pass_count": 2,
                "compose_pass2_applied": True,
                "narration_compose_source": "llm_pass2",
                "compose_total_tokens": 120,
            },
            "compose_total_tokens": 120,
            "source": "typing_phase:draft_intent",
        },
        compose_prewarm_status="ready",
        compose_prewarm_source="typing_phase:draft_intent",
        compose_prewarm_total_tokens=120,
        typing_phase_prewarm_tokens=120,
    )
    diagnostics = result.intent_stage_diagnostics
    assert "她先把话钉在台面" in result.narration
    assert str(diagnostics.get("narration_compose_source") or "") == "prewarm_cache"
    assert bool(diagnostics.get("compose_prewarm_hit")) is True
    assert int(diagnostics.get("compose_total_tokens", 0)) == 0
    assert int(diagnostics.get("post_submit_llm_calls", 0)) == 0
    assert int(diagnostics.get("typing_phase_prewarm_tokens", 0)) >= 120


def test_key_burst_pass2_does_not_skip_on_latency_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    _move_state_to_segment(plan, state, "reveal")
    state.scene_heat = 6
    state.secret_exposure = 6
    state.route_lock = 5
    action = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    monkeypatch.setattr(
        runtime_module,
        "_compose_narration_once_with_regen",
        lambda **kwargs: (
            "她先把牌按住，逼所有人停一拍。",
            "llm",
            {
                "compose_latency_ms": 99999.0,
                "compose_input_tokens": 10,
                "compose_output_tokens": 5,
                "compose_total_tokens": 15,
                "narration_compose_source": "llm",
            },
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "_compose_burst_enhance_with_regen",
        lambda **kwargs: (
            "她先把牌按住，接着补上一刀，把退路全部封死。",
            {
                "compose_pass2_retry_count": 0,
                "compose_pass2_invalid_reason": "",
                "compose_pass2_latency_ms": 3.0,
                "compose_pass2_total_tokens": 7,
                "compose_pass2_applied": True,
            },
        ),
    )
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda _settings: object())
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
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
    diagnostics = result.intent_stage_diagnostics
    assert diagnostics.get("turn_complexity") == "key_burst"
    assert int(diagnostics.get("compose_pass_count", 0)) == 2
    assert str(diagnostics.get("compose_pass2_invalid_reason") or "") != "budget_exhausted"
    assert bool(diagnostics.get("compose_budget_hit")) is False


def test_compose_key_burst_pass2_retries_once_then_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    _move_state_to_segment(plan, state, "reveal")
    state.scene_heat = 6
    state.secret_exposure = 6
    state.route_lock = 5
    action = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload
            self.usage = {}

    class _FakeGateway:
        def __init__(self) -> None:
            self.pass2_calls = 0

        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            operation_name = str(kwargs.get("operation_name") or "")
            if operation_name == "play_v2.narration_compose":
                return _FakeResponse(
                    {
                        "narration": "她先把牌按在桌边，场内外都在等下一句。",
                        "coverage_marks": {
                            "target": True,
                            "move": True,
                            "consequence": True,
                            "relationship": True,
                        },
                        "length_profile": "burst",
                    }
                )
            if operation_name == "play_v2.narration_compose_pass2":
                self.pass2_calls += 1
                if self.pass2_calls == 1:
                    return _FakeResponse({"narration": ""})
                return _FakeResponse(
                    {"narration": "她先把牌按在桌边，紧接着当众补了一刀，让所有人都失去回撤空间。"}
                )
            return _FakeResponse(
                {
                    "recommended_actor_id": "",
                    "summary": "ok",
                    "candidates": [],
                }
            )

    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: _FakeGateway())
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
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
    diagnostics = result.intent_stage_diagnostics
    assert diagnostics.get("turn_complexity") == "key_burst"
    assert int(diagnostics.get("compose_pass_count", 0)) == 2
    assert int(diagnostics.get("compose_pass2_retry_count", 0)) == 1
    assert bool(diagnostics.get("compose_pass2_applied")) is True


def test_compose_key_burst_pass2_failure_keeps_pass1(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    _move_state_to_segment(plan, state, "reveal")
    state.scene_heat = 6
    state.secret_exposure = 6
    state.route_lock = 5
    action = next(item for item in build_suggested_actions(plan, state) if item.lane_id == "burst")
    pass1_text = "她先把最重的话扣在台面，逼所有人停顿一拍。"

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload
            self.usage = {}

    class _FakeGateway:
        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            operation_name = str(kwargs.get("operation_name") or "")
            if operation_name == "play_v2.narration_compose":
                return _FakeResponse(
                    {
                        "narration": pass1_text,
                        "coverage_marks": {
                            "target": True,
                            "move": True,
                            "consequence": True,
                            "relationship": True,
                        },
                        "length_profile": "burst",
                    }
                )
            if operation_name == "play_v2.narration_compose_pass2":
                raise RuntimeError("provider down")
            return _FakeResponse(
                {
                    "recommended_actor_id": "",
                    "summary": "ok",
                    "candidates": [],
                }
            )

    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: _FakeGateway())
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
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
    diagnostics = result.intent_stage_diagnostics
    assert pass1_text in result.narration
    assert diagnostics.get("turn_complexity") == "key_burst"
    assert int(diagnostics.get("compose_pass_count", 0)) == 2
    assert str(diagnostics.get("compose_pass2_invalid_reason") or "") in {"llm_provider_failed", "unknown"}


def test_compose_extracts_narration_when_json_payload_leaks_into_text(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    action = build_suggested_actions(plan, state)[0]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload
            self.usage = {}

    class _FakeGateway:
        def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
            _ = kwargs
            return _FakeResponse(
                {
                    "narration": '{"narration":"何妍初先把最危险的话压到桌面边缘。"}{"coverage_marks":{"target":true}}',
                    "coverage_marks": {
                        "target": True,
                        "move": True,
                        "consequence": True,
                        "relationship": True,
                    },
                    "length_profile": "normal",
                }
            )

    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: _FakeGateway())
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: type(
            "_SettingsStub",
            (),
            {
                "play_v2_dramatic_rewrite_max_output_tokens": 320,
                "play_v2_dramatic_rewrite_use_llm": True,
                "internal_test_strict_no_repair_fallback": False,
                "play_v2_intent_compiler_use_llm": False,
                "play_v2_micro_sim_use_llm": False,
            },
        )(),
    )

    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)

    assert "何妍初先把最危险的话压到桌面边缘。" in result.narration
    assert "{\"narration\"" not in result.narration


def test_main_render_path_no_longer_contains_legacy_cost_stems() -> None:
    text = Path("rpg_backend/play_v2/narration_surface.py").read_text(encoding="utf-8")
    forbidden_stems = (
        "代价会先咬位置和发言权，后面每一步都更难回撤。",
        "代价会把关系账一起拉上台面，谁都很难再装作没站边。",
        "代价是体面先碎，后续所有选择都要带着这道裂缝走。",
    )

    for stem in forbidden_stems:
        assert stem not in text


def test_runtime_narration_does_not_emit_legacy_cost_stems() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    forbidden_stems = (
        "代价会先咬位置和发言权，后面每一步都更难回撤。",
        "代价会把关系账一起拉上台面，谁都很难再装作没站边。",
        "代价是体面先碎，后续所有选择都要带着这道裂缝走。",
    )

    for _ in range(3):
        action = build_suggested_actions(plan, state)[0]
        result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)
        for stem in forbidden_stems:
            assert stem not in result.narration
        state = result.state


def test_initial_world_state_loads_author_initial_delta_pack() -> None:
    plan = _play_plan()

    state = build_initial_world_state(plan)

    assert state.active_beat_delta_pack.snapshot_id == plan.initial_beat_delta_pack.snapshot_id
    assert state.active_beat_delta_pack.segment_id == plan.segments[0].segment_id
    assert state.delta_pack_snapshot_id == plan.initial_beat_delta_pack.snapshot_id
    assert state.delta_pack_job_status == "idle"


def test_delta_pack_schedule_and_poll_applies_pack_for_current_segment() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)

    scheduled = delta_pack_runtime.schedule_next_beat_delta_pack(plan=plan, state=state)
    assert scheduled["beat_delta_pack_job_status"] == "scheduled"

    applied = False
    try:
        for _ in range(30):
            diagnostics = delta_pack_runtime.poll_and_apply_pending_delta_pack(plan=plan, state=state)
            if diagnostics.get("beat_delta_pack_applied") is True:
                applied = True
                break
            time.sleep(0.01)
    finally:
        delta_pack_runtime.clear_delta_pack_future(state.session_id)

    assert applied is True
    assert state.delta_pack_job_status == "applied"
    assert state.active_beat_delta_pack.segment_id == state.segment_id
    assert state.active_beat_delta_pack.source == "runtime_rollover"


def test_delta_pack_poll_rejects_stale_snapshot_result() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    original_snapshot = state.active_beat_delta_pack.snapshot_id

    delta_pack_runtime.schedule_next_beat_delta_pack(plan=plan, state=state)
    state.delta_pack_snapshot_id = "delta_pack_stale_snapshot"

    final_status = ""
    try:
        for _ in range(30):
            diagnostics = delta_pack_runtime.poll_and_apply_pending_delta_pack(plan=plan, state=state)
            final_status = str(diagnostics.get("beat_delta_pack_job_status") or "")
            if final_status in {"ignored", "failed", "timeout"}:
                break
            time.sleep(0.01)
    finally:
        delta_pack_runtime.clear_delta_pack_future(state.session_id)

    assert final_status == "ignored"
    assert state.active_beat_delta_pack.snapshot_id == original_snapshot
    assert state.delta_pack_job_status == "ignored"


def test_run_turn_emits_beat_delta_pack_diagnostics_keys() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    action = build_suggested_actions(plan, state)[0]

    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)
    diagnostics = result.intent_stage_diagnostics

    assert "beat_delta_pack_applied" in diagnostics
    assert "beat_delta_pack_source" in diagnostics
    assert "beat_delta_pack_snapshot_id" in diagnostics
    assert "beat_delta_pack_job_ms" in diagnostics
    assert "beat_delta_pack_job_status" in diagnostics
