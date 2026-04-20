from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rpg_backend.config import Settings
from rpg_backend.play.service import PlaySessionService
from tools.urban_author_play_benchmarks import llm_text_audit as llm_text_audit_tools
from tools.urban_author_play_benchmarks import play_eval as play_eval_tools
from tools.urban_author_play_benchmarks.gold_set import v1_topic_gold_14
from tools.urban_author_play_benchmarks.runner import run_case
from tools.urban_author_play_benchmarks.self_play_runner import (
    PERSONA_CONFIGS,
    PlayerAgentAdapter,
    PlayerDecision,
    PlayerTurnContext,
    ResponsesPlayBackend,
    ScriptedPlayerAdapter,
    SelfPlayComparisonSummary,
    SelfPlayRunSummary,
    SelfPlayTurnLog,
    SubagentPlayerAdapter,
    _ordered_persona_ids_for_plan,
    _resolve_persona_pack_for_plan,
    _build_comparison_summary,
    _sample_logs_for_llm_turn_audit,
    _session_llm_text_audit_payload,
    run_self_play_pilot,
)


class _LowConfidenceFirstAdapter(PlayerAgentAdapter):
    def __init__(self, persona_id: str) -> None:
        super().__init__(PERSONA_CONFIGS[persona_id])  # type: ignore[arg-type]
        self._used_first = False
        self._fallback = ScriptedPlayerAdapter(PERSONA_CONFIGS[persona_id])  # type: ignore[arg-type]

    def decide(self, context: PlayerTurnContext) -> PlayerDecision:
        if not self._used_first:
            self._used_first = True
            return PlayerDecision.model_construct(
                lane_id="invalid_lane",
                action_text="嗯。",
                reason="先看看系统会怎么修。",
                confidence="low",
            )
        return self._fallback.decide(context)


class _FailingAdapter(PlayerAgentAdapter):
    def __init__(self, persona_id: str) -> None:
        super().__init__(PERSONA_CONFIGS[persona_id])  # type: ignore[arg-type]

    def decide(self, context: PlayerTurnContext) -> PlayerDecision:
        raise RuntimeError("backend exploded")


class _SlowAdapter(PlayerAgentAdapter):
    def __init__(self, persona_id: str, *, sleep_seconds: float) -> None:
        super().__init__(PERSONA_CONFIGS[persona_id])  # type: ignore[arg-type]
        self._sleep_seconds = sleep_seconds

    def decide(self, context: PlayerTurnContext) -> PlayerDecision:
        import time

        time.sleep(self._sleep_seconds)
        return PlayerDecision(
            lane_id="relationship",
            action_text="我先护住他。",
            reason="超时测试。",
            confidence="medium",
        )


class _FakePersistentBackend:
    def __init__(self) -> None:
        self.open_calls = 0
        self.close_calls = 0
        self.decide_calls = 0

    def open_session(self, *, persona, system_prompt):  # noqa: ANN001, ANN201
        self.open_calls += 1
        return {"persona": persona.persona_id, "system_prompt": system_prompt}

    def decide(self, session, *, context):  # noqa: ANN001, ANN201
        self.decide_calls += 1
        return PlayerDecision(
            lane_id="burst",
            action_text="我要当众把证据甩出来。",
            reason=f"{session['persona']}保持同一条线程决策。",
            confidence="high",
        )

    def close_session(self, session):  # noqa: ANN001, ANN201
        self.close_calls += 1


def test_responses_play_backend_round_robin_samples_api_keys(monkeypatch) -> None:
    settings = Settings(
        responses_play_base_url="https://play.example/v1",
        responses_play_model="gpt-5.4-mini",
        responses_play_api_keys="key_a,key_b",
        responses_timeout_seconds=10.0,
    )
    captured_api_keys: list[str] = []
    captured_extra_bodies: list[dict[str, object]] = []

    class _FakeResponses:
        def __init__(self, api_key: str) -> None:
            self._api_key = api_key

        def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured_api_keys.append(self._api_key)
            captured_extra_bodies.append(dict(kwargs.get("extra_body") or {}))
            return SimpleNamespace(
                id="resp_fake",
                output_text='{"lane_id":"relationship","action_text":"测试动作","reason":"测试","confidence":"high"}',
                usage={"input_tokens": 10, "output_tokens": 4},
            )

    def _fake_build_openai_client(**kwargs):  # noqa: ANN001, ANN201
        return SimpleNamespace(responses=_FakeResponses(str(kwargs["api_key"])))

    monkeypatch.setattr("tools.urban_author_play_benchmarks.self_play_runner.build_openai_client", _fake_build_openai_client)
    backend = ResponsesPlayBackend(settings=settings)
    session = backend.open_session(
        persona=PERSONA_CONFIGS["wenjian"],  # type: ignore[arg-type]
        system_prompt="测试系统提示",
    )

    decision = backend.decide(session, context={"turn_index": 1})
    _ = backend.decide(session, context={"turn_index": 2})

    assert captured_api_keys == ["key_a", "key_b"]
    assert decision.lane_id == "relationship"
    assert captured_extra_bodies[0] == {"response_format": {"type": "json_object"}}


def test_responses_play_backend_can_attach_json_content_type_hint(monkeypatch) -> None:
    settings = Settings(
        responses_play_base_url="https://play.example/v1",
        responses_play_model="gpt-5.4-mini",
        responses_play_api_key="key_a",
        responses_timeout_seconds=10.0,
        responses_json_content_type_hint=True,
    )
    captured_extra_bodies: list[dict[str, object]] = []

    class _FakeResponses:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured_extra_bodies.append(dict(kwargs.get("extra_body") or {}))
            return SimpleNamespace(
                id="resp_fake",
                output_text='{"lane_id":"relationship","action_text":"测试动作","reason":"测试","confidence":"high"}',
                usage={"input_tokens": 10, "output_tokens": 4},
            )

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.self_play_runner.build_openai_client",
        lambda **kwargs: SimpleNamespace(responses=_FakeResponses()),
    )
    backend = ResponsesPlayBackend(settings=settings)
    session = backend.open_session(
        persona=PERSONA_CONFIGS["wenjian"],  # type: ignore[arg-type]
        system_prompt="测试系统提示",
    )

    _ = backend.decide(session, context={"turn_index": 1})

    assert captured_extra_bodies[0] == {"response_format": {"type": "json_object"}, "content_type": "json"}


def _turn_log(
    *,
    persona_id: str,
    turn_index: int,
    selected_move_family: str,
    selected_target_id: str | None,
    segment_id: str = "segment_1_opening",
    segment_role: str = "opening",
    content_quality_score: int = 4,
    persona_alignment_score: int = 4,
    total_turn_latency_ms: float = 12.0,
    ending_id: str | None = None,
    route_target_id: str | None = "su_qing",
) -> SelfPlayTurnLog:
    return SelfPlayTurnLog(
        turn_index=turn_index,
        persona_id=persona_id,  # type: ignore[arg-type]
        play_length_preset="12_15",
        arc_template_id="standard_4",
        progress_required_by_segment=[2, 3, 3, 1],
        raw_action_text="测试动作",
        reason="测试理由",
        parse_confidence="high",
        repaired=False,
        selected_lane_id="burst",
        selected_move_family=selected_move_family,
        selected_target_id=selected_target_id,
        narration="测试 narration",
        progress_summary="测试推进",
        consequence_tags=["focus_hit"],
        suggested_actions_snapshot=[],
        next_suggested_actions=[],
        state_before={"segment_id": segment_id, "current_route_target_id": route_target_id},
        state_after={"segment_id": segment_id, "current_route_target_id": route_target_id, "ending_id": ending_id},
        decision_latency_ms=4.0,
        runtime_latency_ms=8.0,
        total_turn_latency_ms=total_turn_latency_ms,
        content_quality_score=content_quality_score,
        persona_alignment_score=persona_alignment_score,
        notes=[],
        segment_id=segment_id,
        segment_role=segment_role,
        ending_triggered=ending_id is not None,
        agent_confidence="high",
    )


def _run_summary(
    *,
    persona_id: str,
    turn_count: int,
    best_turn_index: int | None,
    worst_turn_index: int | None,
) -> SelfPlayRunSummary:
    return SelfPlayRunSummary(
        persona_id=persona_id,  # type: ignore[arg-type]
        persona_label="测试",
        play_length_preset="12_15",
        arc_template_id="standard_4",
        progress_required_by_segment=[2, 3, 3, 1],
        worker_status="completed",
        ending_reached=True,
        ending_id="pyrrhic_control",
        ending_strength=2,
        turn_count=turn_count,
        avg_content_score=4.0,
        avg_persona_alignment_score=4.0,
        mean_turn_latency_ms=1000.0,
        max_turn_latency_ms=2000.0,
        repair_count=0,
        avg_parse_confidence=1.0,
        parse_confidence_distribution={"high": turn_count, "medium": 0, "low": 0},
        lane_counts={"relationship": turn_count},
        route_target_trajectory=["su_qing"] * turn_count,
        best_turn_index=best_turn_index,
        worst_turn_index=worst_turn_index,
        ending_summary="测试结局",
    )


def test_sample_logs_for_llm_turn_audit_prefers_opening_mid_terminal() -> None:
    logs = [
        _turn_log(
            persona_id="wenjian",
            turn_index=1,
            selected_move_family="comfort",
            selected_target_id="su_qing",
            segment_id="segment_1_opening",
            segment_role="opening",
        ),
        _turn_log(
            persona_id="wenjian",
            turn_index=2,
            selected_move_family="deflect",
            selected_target_id="su_qing",
            segment_id="segment_2_mid",
            segment_role="conflict",
        ),
        _turn_log(
            persona_id="wenjian",
            turn_index=3,
            selected_move_family="ally_with",
            selected_target_id="su_qing",
            segment_id="segment_2_mid",
            segment_role="conflict",
        ),
        _turn_log(
            persona_id="wenjian",
            turn_index=4,
            selected_move_family="public_reveal",
            selected_target_id="su_qing",
            segment_id="segment_3_reveal",
            segment_role="reveal",
        ),
        _turn_log(
            persona_id="wenjian",
            turn_index=5,
            selected_move_family="accuse",
            selected_target_id="su_qing",
            segment_id="segment_4_terminal",
            segment_role="terminal",
        ),
    ]

    sampled = _sample_logs_for_llm_turn_audit(logs, max_turns=3)
    sampled_indexes = [item.turn_index for item in sampled]

    assert sampled_indexes[0] == 1
    assert sampled_indexes[-1] == 5
    assert len(sampled_indexes) == 3
    assert sampled_indexes == sorted(sampled_indexes)
    assert any(item in sampled_indexes for item in (3, 4))


def test_session_llm_payload_uses_key_turns_and_compact_schema() -> None:
    logs = [
        _turn_log(persona_id="wenjian", turn_index=1, selected_move_family="comfort", selected_target_id="su_qing", segment_role="opening"),
        _turn_log(persona_id="wenjian", turn_index=2, selected_move_family="deflect", selected_target_id="su_qing", segment_role="misread"),
        _turn_log(persona_id="wenjian", turn_index=3, selected_move_family="ally_with", selected_target_id="su_qing", segment_role="pressure"),
        _turn_log(persona_id="wenjian", turn_index=4, selected_move_family="probe_secret", selected_target_id="su_qing", segment_role="reveal"),
        _turn_log(persona_id="wenjian", turn_index=5, selected_move_family="public_reveal", selected_target_id="su_qing", segment_role="terminal"),
    ]
    summary = _run_summary(persona_id="wenjian", turn_count=len(logs), best_turn_index=4, worst_turn_index=2)
    payload = _session_llm_text_audit_payload(
        case_id="case_payload",
        preview=SimpleNamespace(
            title_hint="测试标题",
            story_shell_id="entertainment_scandal",
            experience_band="standard",
            social_arena="颁奖礼",
            route_promise="一路升温",
            bomb_moment="当众翻盘",
            cost_of_truth="掉口碑",
            taboo_secret="旧账",
        ),
        plan=SimpleNamespace(
            story_shell_id="entertainment_scandal",
            title="测试故事",
            route_promise="一路升温",
            bomb_moment="当众翻盘",
        ),
        persona_pack=SimpleNamespace(
            source="template",
            source_key="entertainment_awards_seating_shift",
            ordered_persona_ids=["baodian", "fuchou", "zhandui", "wenjian", "qinggan"],
            entries=[SimpleNamespace(persona_id="wenjian", rank=4)],
        ),
        persona_id="wenjian",
        logs=logs,
        summary=summary,
        turn_llm_logs=[],
    )

    assert "turn_logs" not in payload
    assert "transcript_excerpts" not in payload
    assert "run_summary_compact" in payload
    assert 4 <= len(payload["key_turns"]) <= 6
    assert payload["payload_turn_count"] == len(payload["key_turns"])
    assert isinstance(payload["payload_estimated_tokens"], int)
    roles = {str(item["segment_role"]) for item in payload["key_turns"]}
    assert {"opening", "misread", "reveal", "terminal"}.issubset(roles)
    expected_turn_keys = {
        "turn_index",
        "segment_role",
        "raw_action_text",
        "narration",
        "progress_summary",
        "selected_lane_id",
        "selected_move_family",
        "selected_target_id",
        "consequence_tags",
    }
    for item in payload["key_turns"]:
        assert set(item.keys()) == expected_turn_keys
        assert "state_feedback" not in item
    assert payload["run_summary_compact"]["turn_count"] == len(logs)


def test_session_llm_payload_trims_to_token_budget() -> None:
    long_logs = []
    roles = ("opening", "misread", "pressure", "reveal", "lock", "terminal", "pressure", "reveal")
    for idx, role in enumerate(roles, start=1):
        base = _turn_log(
            persona_id="wenjian",
            turn_index=idx,
            selected_move_family="comfort",
            selected_target_id="su_qing",
            segment_role=role,
        )
        long_logs.append(
            base.model_copy(
                update={
                    "raw_action_text": "动" * 3500,
                    "narration": "叙" * 3500,
                    "progress_summary": "进" * 200,
                }
            )
        )
    summary = _run_summary(persona_id="wenjian", turn_count=len(long_logs), best_turn_index=7, worst_turn_index=2)
    payload = _session_llm_text_audit_payload(
        case_id="case_trim",
        preview=SimpleNamespace(
            title_hint="长文本压测",
            story_shell_id="office_power",
            experience_band="flagship",
            social_arena="董事会",
            route_promise="把人一步步逼到表态",
            bomb_moment="现场摊牌",
            cost_of_truth="利益清算",
            taboo_secret="并购旧案",
        ),
        plan=SimpleNamespace(
            story_shell_id="office_power",
            title="长文本压测故事",
            route_promise="把人一步步逼到表态",
            bomb_moment="现场摊牌",
        ),
        persona_pack=SimpleNamespace(
            source="shell",
            source_key="office_power",
            ordered_persona_ids=["wenjian", "zhandui", "baodian", "qinggan", "fuchou"],
            entries=[SimpleNamespace(persona_id="wenjian", rank=1)],
        ),
        persona_id="wenjian",
        logs=long_logs,
        summary=summary,
        turn_llm_logs=[],
    )

    assert payload["payload_trimmed"] is True
    assert payload["payload_estimated_tokens"] <= 10_000
    assert 4 <= payload["payload_turn_count"] <= 6
    assert max(len(str(item["narration"])) for item in payload["key_turns"]) <= 240
    assert max(len(str(item["raw_action_text"])) for item in payload["key_turns"]) <= 120
    assert max(len(str(item["progress_summary"])) for item in payload["key_turns"]) <= 90


def test_self_play_runner_writes_artifacts_and_summaries(tmp_path) -> None:
    result = run_self_play_pilot(tmp_path, live_mode="deterministic", execution_mode="parallel")

    artifact_dir = Path(result["artifacts_dir"])
    assert (artifact_dir / "self_play_config.json").exists()
    assert (artifact_dir / "compiled_play_plan.json").exists()
    assert (artifact_dir / "persona_pack.json").exists()
    assert (artifact_dir / "comparison_summary.json").exists()
    assert (artifact_dir / "comparison_analysis.md").exists()
    persona_pack = json.loads((artifact_dir / "persona_pack.json").read_text())
    assert persona_pack["source"] in {"template", "shell", "default"}
    assert len(persona_pack["ordered_persona_ids"]) == 5
    assert len(persona_pack["entries"]) == 5
    comparison = json.loads((artifact_dir / "comparison_summary.json").read_text())
    assert "source_live_depth_score" in comparison
    assert "source_final_mode_path" in comparison
    for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou"):
        persona_dir = artifact_dir / "personas" / persona_id
        assert (persona_dir / "turn_logs.jsonl").exists()
        assert (persona_dir / "latest_state.json").exists()
        assert (persona_dir / "run_summary.partial.json").exists()
        assert (persona_dir / "run_summary.json").exists()
        latest_state = json.loads((persona_dir / "latest_state.json").read_text())
        assert latest_state["session_id"]
        first_line = (persona_dir / "turn_logs.jsonl").read_text().splitlines()[0]
        payload = json.loads(first_line)
        assert "state_before" in payload
        assert "state_after" in payload
        assert "selected_lane_id" in payload
        assert "decision_latency_ms" in payload
        assert "runtime_latency_ms" in payload
        assert "content_quality_score" in payload
        assert "persona_alignment_score" in payload
        assert "narration" in payload
        assert "progress_summary" in payload
        assert "next_suggested_actions" in payload


def test_self_play_runner_can_emit_chaos_shadow_artifacts_without_polluting_main_comparison(tmp_path) -> None:
    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        enable_turn_play_eval=True,
        enable_session_play_eval=True,
        enable_chaos_persona_shadow=True,
    )

    artifact_dir = Path(result["artifacts_dir"])
    shadow_dir = artifact_dir / "personas_shadow" / "chaos"
    assert shadow_dir.exists()
    assert (shadow_dir / "turn_logs.jsonl").exists()
    assert (shadow_dir / "run_summary.json").exists()
    assert (shadow_dir / "session_play_eval_report.json").exists()
    assert (artifact_dir / "shadow_persona_summary.json").exists()

    comparison = json.loads((artifact_dir / "comparison_summary.json").read_text())
    assert "chaos" not in comparison["persona_summaries"]
    assert "chaos" in result["shadow_persona_summaries"]


def test_self_play_runner_accepts_play_length_preset_override(tmp_path) -> None:
    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        play_length_preset="20_25",
    )

    assert result["compiled_play_plan"].play_length_preset == "20_25"
    assert result["compiled_play_plan"].arc_template_id == "flagship_6"
    assert [segment.progress_required for segment in result["compiled_play_plan"].segments] == [4, 5, 6, 6, 5, 4]
    assert all(summary.play_length_preset == "20_25" for summary in result["persona_summaries"].values())


def test_self_play_runner_repairs_low_confidence_free_text(tmp_path) -> None:
    adapters = {
        "baodian": _LowConfidenceFirstAdapter("baodian"),
        "qinggan": ScriptedPlayerAdapter(PERSONA_CONFIGS["qinggan"]),
        "wenjian": ScriptedPlayerAdapter(PERSONA_CONFIGS["wenjian"]),
    }

    result = run_self_play_pilot(tmp_path, live_mode="deterministic", execution_mode="sequential", adapters=adapters)  # type: ignore[arg-type]
    artifact_dir = Path(result["artifacts_dir"])
    first_line = (artifact_dir / "personas" / "baodian" / "turn_logs.jsonl").read_text().splitlines()[0]
    payload = json.loads(first_line)

    assert payload["parse_confidence"] == "low"
    assert payload["repaired"] is True
    assert payload["selected_lane_id"] in {"relationship", "side", "burst"}
    assert any(str(note).startswith("lane_repaired:") for note in payload["notes"])
    assert any(str(note).startswith("repair_applied:") for note in payload["notes"])


def test_self_play_runner_strict_mode_fails_on_repair(tmp_path) -> None:
    adapters = {
        "baodian": _LowConfidenceFirstAdapter("baodian"),
        "qinggan": ScriptedPlayerAdapter(PERSONA_CONFIGS["qinggan"]),
        "wenjian": ScriptedPlayerAdapter(PERSONA_CONFIGS["wenjian"]),
    }

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        adapters=adapters,  # type: ignore[arg-type]
        strict_no_repair_fallback=True,
    )

    summary = result["persona_summaries"]["baodian"]
    assert summary.worker_status == "failed"
    assert "strict_no_repair_fallback:repair_applied" in (summary.failure_reason or "")


def test_parallel_mode_isolates_worker_failure(tmp_path) -> None:
    adapters = {
        "baodian": _FailingAdapter("baodian"),
    }

    result = run_self_play_pilot(tmp_path, live_mode="deterministic", execution_mode="parallel", adapters=adapters)  # type: ignore[arg-type]
    artifact_dir = Path(result["artifacts_dir"])
    baodian_summary = json.loads((artifact_dir / "personas" / "baodian" / "run_summary.json").read_text())
    qinggan_summary = json.loads((artifact_dir / "personas" / "qinggan" / "run_summary.json").read_text())

    assert baodian_summary["worker_status"] == "failed"
    assert "backend exploded" in baodian_summary["failure_reason"]
    assert qinggan_summary["worker_status"] in {"completed", "stopped"}
    assert "baodian" in result["comparison_summary"].failed_persona_ids


def test_timeout_writes_partial_summary_and_marks_worker_failed(tmp_path) -> None:
    adapters = {
        "baodian": _SlowAdapter("baodian", sleep_seconds=0.05),
    }

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        decision_timeout_seconds=0.01,
        adapters=adapters,  # type: ignore[arg-type]
    )
    artifact_dir = Path(result["artifacts_dir"])
    baodian_dir = artifact_dir / "personas" / "baodian"
    summary = json.loads((baodian_dir / "run_summary.json").read_text())
    partial = json.loads((baodian_dir / "run_summary.partial.json").read_text())

    assert summary["worker_status"] == "failed"
    assert "decision timed out" in summary["failure_reason"]
    assert partial["worker_status"] == "failed"


def test_self_play_runner_free_input_mode_submits_without_selected_ids(tmp_path, monkeypatch) -> None:
    submitted_pairs: list[tuple[str | None, str | None]] = []
    original_submit_turn = PlaySessionService.submit_turn

    def _wrapped_submit_turn(self, session_id, request, actor_user_id=None):  # noqa: ANN001, ANN201
        submitted_pairs.append((request.selected_suggestion_id, request.selected_story_action_id))
        return original_submit_turn(self, session_id, request, actor_user_id=actor_user_id)

    monkeypatch.setattr(PlaySessionService, "submit_turn", _wrapped_submit_turn)

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        select_id_probability=0.0,
    )

    assert submitted_pairs
    assert all(suggestion_id is None and story_action_id is None for suggestion_id, story_action_id in submitted_pairs)
    summary = result["persona_summaries"]["baodian"]
    assert summary.turn_count >= 1
    assert summary.free_input_turn_count == summary.turn_count
    assert summary.select_id_turn_count == 0
    artifact_dir = Path(result["artifacts_dir"])
    first_turn_log = json.loads((artifact_dir / "personas" / "baodian" / "turn_logs.jsonl").read_text().splitlines()[0])
    assert first_turn_log["turn_input_mode"] == "free_input"
    assert first_turn_log["submitted_with_selected_ids"] is False


def test_self_play_runner_free_input_typing_rhythm_calls_draft_intent(tmp_path, monkeypatch) -> None:
    submitted_draft_ids: list[str | None] = []
    draft_call_inputs: list[str] = []
    draft_call_final_flags: list[bool] = []
    original_submit_turn = PlaySessionService.submit_turn
    original_draft_intent = PlaySessionService.draft_intent

    def _wrapped_submit_turn(self, session_id, request, actor_user_id=None):  # noqa: ANN001, ANN201
        submitted_draft_ids.append(request.draft_intent_id)
        return original_submit_turn(self, session_id, request, actor_user_id=actor_user_id)

    def _wrapped_draft_intent(self, session_id, request, actor_user_id=None):  # noqa: ANN001, ANN201
        draft_call_inputs.append(request.input_text)
        draft_call_final_flags.append(bool(getattr(request, "is_final_draft", False)))
        response = original_draft_intent(self, session_id, request, actor_user_id=actor_user_id)
        return response.model_copy(
            update={
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            }
        )

    monkeypatch.setattr(PlaySessionService, "submit_turn", _wrapped_submit_turn)
    monkeypatch.setattr(PlaySessionService, "draft_intent", _wrapped_draft_intent)

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        select_id_probability=0.0,
        typing_rhythm_enabled=True,
        draft_intent_probability=1.0,
        draft_call_count_min=2,
        draft_call_count_max=2,
    )

    assert draft_call_inputs
    assert draft_call_final_flags
    assert draft_call_final_flags[-1] is True
    assert any(flag is False for flag in draft_call_final_flags[:-1])
    assert any(bool(item) for item in submitted_draft_ids)
    artifact_dir = Path(result["artifacts_dir"])
    first_turn_log = json.loads((artifact_dir / "personas" / "baodian" / "turn_logs.jsonl").read_text().splitlines()[0])
    assert int(first_turn_log["draft_call_count"]) >= 1
    assert int(first_turn_log["draft_total_tokens"]) >= 18
    assert int(first_turn_log["pre_submit_total_tokens"]) >= int(first_turn_log["draft_total_tokens"])
    assert int(first_turn_log["play_turn_total_tokens"]) >= int(first_turn_log["post_submit_total_tokens"])
    assert "compose_prewarm_total_tokens" in first_turn_log
    assert "typing_phase_prewarm_tokens" in first_turn_log
    assert "read_phase_prewarm_tokens" in first_turn_log
    assert "submit_phase_tokens" in first_turn_log


def test_self_play_runner_select_id_mode_submits_selected_ids(tmp_path, monkeypatch) -> None:
    submitted_pairs: list[tuple[str | None, str | None]] = []
    original_submit_turn = PlaySessionService.submit_turn

    def _wrapped_submit_turn(self, session_id, request, actor_user_id=None):  # noqa: ANN001, ANN201
        submitted_pairs.append((request.selected_suggestion_id, request.selected_story_action_id))
        return original_submit_turn(self, session_id, request, actor_user_id=actor_user_id)

    monkeypatch.setattr(PlaySessionService, "submit_turn", _wrapped_submit_turn)

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        select_id_probability=1.0,
    )

    assert submitted_pairs
    assert all(bool(suggestion_id) and bool(story_action_id) for suggestion_id, story_action_id in submitted_pairs)
    summary = result["persona_summaries"]["baodian"]
    assert summary.turn_count >= 1
    assert summary.select_id_turn_count == summary.turn_count
    assert summary.free_input_turn_count == 0
    artifact_dir = Path(result["artifacts_dir"])
    first_turn_log = json.loads((artifact_dir / "personas" / "baodian" / "turn_logs.jsonl").read_text().splitlines()[0])
    assert first_turn_log["turn_input_mode"] == "select_id"
    assert first_turn_log["submitted_with_selected_ids"] is True


def test_self_play_runner_select_id_mode_does_not_call_draft_intent(tmp_path, monkeypatch) -> None:
    draft_call_count = 0
    original_draft_intent = PlaySessionService.draft_intent

    def _wrapped_draft_intent(self, session_id, request, actor_user_id=None):  # noqa: ANN001, ANN201
        nonlocal draft_call_count
        draft_call_count += 1
        return original_draft_intent(self, session_id, request, actor_user_id=actor_user_id)

    monkeypatch.setattr(PlaySessionService, "draft_intent", _wrapped_draft_intent)

    _ = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        select_id_probability=1.0,
        typing_rhythm_enabled=True,
        draft_intent_probability=1.0,
    )

    assert draft_call_count == 0


def test_self_play_runner_can_reuse_author_artifacts_from_custom_catalog(tmp_path, monkeypatch) -> None:
    case = v1_topic_gold_14()[0]
    benchmark_root = tmp_path / "benchmark"
    run_case(case, benchmark_root, mode="deterministic")
    source_artifacts_dir = benchmark_root / "smoke" / case.case_id / "deterministic"

    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.self_play_runner.run_preview_blueprint_graph",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preview should not rerun")),
    )
    monkeypatch.setattr(
        "tools.urban_author_play_benchmarks.self_play_runner.run_author_play_graph",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("author graph should not rerun")),
    )

    result = run_self_play_pilot(
        tmp_path,
        case_id=case.case_id,
        case_catalog=[case],
        live_mode="deterministic",
        execution_mode="sequential",
        source_artifacts_dir=source_artifacts_dir,
    )

    assert result["compiled_play_plan"].template_id == case.expected_template_id


def test_self_play_runner_writes_turn_and_session_play_eval_artifacts(tmp_path, monkeypatch) -> None:
    def _fake_turn_play_eval(payload):  # noqa: ANN001, ANN201
        return play_eval_tools.TurnPlayEvalRecord(
            case_id=str(payload["case_id"]),
            persona_id=str(payload["persona_id"]),
            turn_index=int(payload["turn_index"]),
            story_shell_id=str(payload["story_shell_id"]),
            segment_role=str(payload["segment_role"]),
            play_eval_status="completed",
            scores=play_eval_tools.TurnPlayEvalScores(
                consequence_impact=4,
                intent_binding=4,
                pressure_exchange=5,
                control_effectiveness=4,
                trigger_conversion=3,
                foreshadow_clarity=4,
                shell_signal_fidelity=4,
                npc_agency_reversal=4,
            ),
            strongest_signal="这一拍风险转化很清楚。",
            main_issue="还可以更狠。",
            flags=["角色反应太泛"],
        )

    def _fake_session_play_eval(payload):  # noqa: ANN001, ANN201
        assert payload["persona_selection"]["source"] in {"template", "shell", "default"}
        assert payload["persona_selection"]["rank"] is not None
        assert len(payload["persona_selection"]["ordered_persona_ids"]) == 5
        return play_eval_tools.SessionPlayEvalReport(
            case_id=str(payload["case_id"]),
            persona_id=str(payload["persona_id"]),
            play_eval_status="completed",
            scores=play_eval_tools.SessionPlayEvalScores(
                strategic_tension_curve=4,
                consequence_legibility=4,
                payoff_realization=3,
                npc_interest_divergence=4,
                control_tradeoff_quality=4,
                shell_system_activation=4,
                ending_cost_integrity=4,
                replay_variance=3,
            ),
            best_moment="最好的一下是当众失控。",
            worst_moment="最弱的是中段略平。",
            one_sentence_verdict="整体可玩，而且像中文。",
            top_issues=["中段张力还能再抬"],
            top_strengths=["人物反应有区分"],
        )

    monkeypatch.setattr(play_eval_tools, "evaluate_turn", _fake_turn_play_eval)
    monkeypatch.setattr(play_eval_tools, "evaluate_session", _fake_session_play_eval)

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        enable_turn_play_eval=True,
        enable_session_play_eval=True,
    )

    artifact_dir = Path(result["artifacts_dir"])
    for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou"):
        persona_dir = artifact_dir / "personas" / persona_id
        turn_play_eval_path = persona_dir / "turn_play_eval_logs.jsonl"
        session_play_eval_path = persona_dir / "session_play_eval_report.json"
        assert turn_play_eval_path.exists()
        assert session_play_eval_path.exists()
        turn_record = json.loads(turn_play_eval_path.read_text().splitlines()[0])
        session_record = json.loads(session_play_eval_path.read_text())
        assert turn_record["play_eval_status"] == "completed"
        assert turn_record["scores"]["npc_agency_reversal"] == 4
        assert session_record["play_eval_status"] == "completed"
        assert session_record["scores"]["strategic_tension_curve"] == 4


def test_self_play_runner_keeps_running_when_play_eval_fails(tmp_path, monkeypatch) -> None:
    def _failed_turn_play_eval(payload):  # noqa: ANN001, ANN201
        return play_eval_tools.TurnPlayEvalRecord(
            case_id=str(payload["case_id"]),
            persona_id=str(payload["persona_id"]),
            turn_index=int(payload["turn_index"]),
            story_shell_id=str(payload["story_shell_id"]),
            segment_role=str(payload["segment_role"]),
            play_eval_status="failed",
            play_eval_error="play eval exploded",
        )

    def _failed_session_play_eval(payload):  # noqa: ANN001, ANN201
        return play_eval_tools.SessionPlayEvalReport(
            case_id=str(payload["case_id"]),
            persona_id=str(payload["persona_id"]),
            play_eval_status="failed",
            play_eval_error="session play eval exploded",
        )

    monkeypatch.setattr(play_eval_tools, "evaluate_turn", _failed_turn_play_eval)
    monkeypatch.setattr(play_eval_tools, "evaluate_session", _failed_session_play_eval)

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="parallel",
        enable_turn_play_eval=True,
        enable_session_play_eval=True,
    )

    assert result["comparison_summary"].case_id
    artifact_dir = Path(result["artifacts_dir"])
    baodian_turn = json.loads((artifact_dir / "personas" / "baodian" / "turn_play_eval_logs.jsonl").read_text().splitlines()[0])
    baodian_session = json.loads((artifact_dir / "personas" / "baodian" / "session_play_eval_report.json").read_text())
    assert baodian_turn["play_eval_status"] == "failed"
    assert baodian_session["play_eval_status"] == "failed"


def test_self_play_runner_writes_turn_and_session_llm_text_audit_artifacts(tmp_path, monkeypatch) -> None:
    def _fake_turn_text_audit(payload):  # noqa: ANN001, ANN201
        return llm_text_audit_tools.TurnLlmTextAuditRecord(
            case_id=str(payload["case_id"]),
            persona_id=str(payload["persona_id"]),
            turn_index=int(payload["turn_index"]),
            story_shell_id=str(payload["story_shell_id"]),
            segment_role=str(payload["segment_role"]),
            llm_audit_status="completed",
            scores=llm_text_audit_tools.TurnLlmTextAuditScores(
                tone_naturalness=4.0,
                character_specificity=4.0,
                dramatic_tension=4.5,
                shell_fidelity=4.0,
                consequence_clarity=4.0,
                anti_template_stiffness=3.5,
            ),
            strongest_signal="语气贴场。",
            main_issue="中段略平。",
            flags=["角色反应太泛"],
        )

    def _fake_session_text_audit(payload):  # noqa: ANN001, ANN201
        return llm_text_audit_tools.SessionLlmTextAuditReport(
            case_id=str(payload["case_id"]),
            persona_id=str(payload["persona_id"]),
            llm_audit_status="completed",
            scores=llm_text_audit_tools.SessionLlmTextAuditScores(
                arc_coherence=4.0,
                payoff_strength=4.0,
                npc_presence=4.5,
                style_consistency=4.0,
                shell_distinctiveness=4.0,
                memorable_moments=3.5,
            ),
            best_moment="评审席换边那下。",
            worst_moment="中段慢了一拍。",
            one_sentence_verdict="可读且有戏。",
            top_issues=["中段张力还能再抬"],
            top_strengths=["人物反应有区分"],
        )

    monkeypatch.setattr(llm_text_audit_tools, "evaluate_turn_text", _fake_turn_text_audit)
    monkeypatch.setattr(llm_text_audit_tools, "evaluate_session_text", _fake_session_text_audit)

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        enable_llm_text_audit=True,
        llm_text_audit_max_workers=2,
    )

    artifact_dir = Path(result["artifacts_dir"])
    for persona_id in ("baodian", "qinggan", "wenjian", "zhandui", "fuchou"):
        persona_dir = artifact_dir / "personas" / persona_id
        turn_llm_path = persona_dir / "turn_llm_text_audit_logs.jsonl"
        session_llm_path = persona_dir / "session_llm_text_audit_report.json"
        assert turn_llm_path.exists()
        assert session_llm_path.exists()
        turn_record = json.loads(turn_llm_path.read_text().splitlines()[0])
        session_record = json.loads(session_llm_path.read_text())
        assert turn_record["llm_audit_status"] == "completed"
        assert session_record["llm_audit_status"] == "completed"


def test_persona_order_prefers_template_specific_pack() -> None:
    persona_ids = _ordered_persona_ids_for_plan(
        SimpleNamespace(
            template_id="entertainment_livestream_hotsearch_flip",
            story_shell_id="entertainment_scandal",
        )
    )

    assert persona_ids[0] == "baodian"
    assert persona_ids[1] == "fuchou"
    assert set(persona_ids) == {"baodian", "qinggan", "wenjian", "zhandui", "fuchou"}


def test_resolve_persona_pack_exposes_template_source_and_ranked_entries() -> None:
    persona_pack = _resolve_persona_pack_for_plan(
        SimpleNamespace(
            template_id="entertainment_livestream_hotsearch_flip",
            story_shell_id="entertainment_scandal",
        )
    )

    assert persona_pack.source == "template"
    assert persona_pack.source_key == "entertainment_livestream_hotsearch_flip"
    assert persona_pack.ordered_persona_ids[0] == "baodian"
    assert persona_pack.entries[0].rank == 1
    assert persona_pack.entries[0].persona_id == "baodian"


def test_subagent_adapter_reuses_single_persistent_session() -> None:
    backend = _FakePersistentBackend()
    adapter = SubagentPlayerAdapter(PERSONA_CONFIGS["baodian"], backend=backend)
    context = PlayerTurnContext(
        persona=PERSONA_CONFIGS["baodian"],
        turn_index=1,
        story_id="story_demo",
        social_arena="订婚宴",
        segment_id="segment_1_opening",
        segment_role="opening",
        segment_summary="测试段落",
        active_characters=[],
        suggested_actions=[],
        state_snapshot={"active_character_ids": []},
        last_turn_outcome=None,
    )

    adapter.open()
    adapter.decide(context)
    adapter.decide(context)
    adapter.close()

    assert backend.open_calls == 1
    assert backend.decide_calls == 2
    assert backend.close_calls == 1


def test_comparison_summary_identifies_best_ending_content_and_speed() -> None:
    summaries = {
        "baodian": SelfPlayRunSummary(
            persona_id="baodian",
            persona_label="爆点型",
            play_length_preset="12_15",
            arc_template_id="standard_4",
            progress_required_by_segment=[2, 3, 3, 1],
            worker_status="completed",
            ending_reached=True,
            ending_id="burned_alone",
            ending_strength=1,
            turn_count=3,
            avg_content_score=4.5,
            avg_persona_alignment_score=4.0,
            mean_turn_latency_ms=16.0,
            max_turn_latency_ms=18.0,
            repair_count=1,
            avg_parse_confidence=0.7,
            parse_confidence_distribution={"high": 2, "medium": 0, "low": 1},
            route_target_trajectory=["lu_jue", "lu_jue"],
            best_turn_index=2,
            worst_turn_index=1,
            ending_summary="烧穿体面",
        ),
        "qinggan": SelfPlayRunSummary(
            persona_id="qinggan",
            persona_label="情感型",
            play_length_preset="12_15",
            arc_template_id="standard_4",
            progress_required_by_segment=[2, 3, 3, 1],
            worker_status="completed",
            ending_reached=True,
            ending_id="route_su_qing",
            ending_strength=3,
            turn_count=3,
            avg_content_score=4.2,
            avg_persona_alignment_score=4.8,
            mean_turn_latency_ms=20.0,
            max_turn_latency_ms=22.0,
            repair_count=0,
            avg_parse_confidence=1.0,
            parse_confidence_distribution={"high": 3, "medium": 0, "low": 0},
            route_target_trajectory=["su_qing", "su_qing"],
            best_turn_index=3,
            worst_turn_index=1,
            ending_summary="苏清线",
        ),
        "wenjian": SelfPlayRunSummary(
            persona_id="wenjian",
            persona_label="稳健型",
            play_length_preset="12_15",
            arc_template_id="standard_4",
            progress_required_by_segment=[2, 3, 3, 1],
            worker_status="completed",
            ending_reached=True,
            ending_id="pyrrhic_control",
            ending_strength=2,
            turn_count=3,
            avg_content_score=3.8,
            avg_persona_alignment_score=4.6,
            mean_turn_latency_ms=10.0,
            max_turn_latency_ms=11.0,
            repair_count=0,
            avg_parse_confidence=1.0,
            parse_confidence_distribution={"high": 3, "medium": 0, "low": 0},
            route_target_trajectory=["su_qing", "su_qing"],
            best_turn_index=2,
            worst_turn_index=1,
            ending_summary="赢了局，输了真心",
        ),
    }
    logs = {
        "baodian": [
            _turn_log(persona_id="baodian", turn_index=1, selected_move_family="public_reveal", selected_target_id="lu_jue"),
            _turn_log(persona_id="baodian", turn_index=2, selected_move_family="accuse", selected_target_id="lu_jue", segment_id="segment_2_reveal", segment_role="reveal"),
        ],
        "qinggan": [
            _turn_log(persona_id="qinggan", turn_index=1, selected_move_family="comfort", selected_target_id="su_qing"),
            _turn_log(persona_id="qinggan", turn_index=2, selected_move_family="private_confession", selected_target_id="su_qing", segment_id="segment_2_reveal", segment_role="reveal"),
        ],
        "wenjian": [
            _turn_log(persona_id="wenjian", turn_index=1, selected_move_family="deflect", selected_target_id="su_qing"),
            _turn_log(persona_id="wenjian", turn_index=2, selected_move_family="ally_with", selected_target_id="su_qing", segment_id="segment_2_reveal", segment_role="reveal"),
        ],
    }

    comparison = _build_comparison_summary("wealth_short_wedding", summaries, logs)

    assert isinstance(comparison, SelfPlayComparisonSummary)
    assert comparison.strongest_ending_persona_id == "qinggan"
    assert comparison.strongest_content_persona_id == "baodian"
    assert comparison.fastest_persona_id == "wenjian"
    assert comparison.supports_distinct_playstyles is True


def test_lane_first_resolution_ignores_misleading_text_when_lane_is_valid(tmp_path) -> None:
    class _MisleadingTextAdapter(PlayerAgentAdapter):
        def __init__(self) -> None:
            super().__init__(PERSONA_CONFIGS["qinggan"])

        def decide(self, context: PlayerTurnContext) -> PlayerDecision:
            return PlayerDecision(
                lane_id="relationship",
                action_text="我要当众曝光所有黑账，立刻炸穿全场。",
                reason="文本故意偏爆点，但 lane 明确要求关系线。",
                confidence="high",
                target_hint="gu_shaoting",
            )

    result = run_self_play_pilot(
        tmp_path,
        live_mode="deterministic",
        execution_mode="sequential",
        select_id_probability=1.0,
        adapters={"qinggan": _MisleadingTextAdapter()},  # type: ignore[arg-type]
    )
    artifact_dir = Path(result["artifacts_dir"])
    first_line = (artifact_dir / "personas" / "qinggan" / "turn_logs.jsonl").read_text().splitlines()[0]
    payload = json.loads(first_line)

    assert payload["selected_lane_id"] == "relationship"
    assert any(str(note) == "text_parse_bypassed" for note in payload["notes"])
