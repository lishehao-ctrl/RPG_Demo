from __future__ import annotations

import re

import pytest

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.author_v3.storylet_compiler import Storylet, StoryletCondition, StoryletEffect
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
import rpg_backend.play_v2.runtime as runtime_module
from rpg_backend.play_v2.runtime import build_initial_world_state, build_suggested_actions, run_turn


@pytest.fixture(scope="module")
def v3_plan() -> CompiledPlayPlan:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")["plan"]


@pytest.fixture(scope="module")
def v2_plan() -> CompiledPlayPlan:
    preview, _ = run_preview_blueprint_graph("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。")
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan


def _settings_stub(*, use_llm: bool):
    return type(
        "_SettingsStub",
        (),
        {
            "play_v2_dramatic_rewrite_max_output_tokens": 320,
            "play_v2_dramatic_rewrite_use_llm": use_llm,
            "play_v2_intent_compiler_use_llm": False,
            "play_v2_micro_sim_use_llm": False,
            "internal_test_strict_no_repair_fallback": False,
        },
    )()


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.usage = {}


class _ComposeCaptureClient:
    def __init__(self) -> None:
        self.call_records: list[dict[str, object]] = []

    def _invoke_json(self, **kwargs):  # noqa: ANN003, ANN204
        self.call_records.append(dict(kwargs))
        compose_input = kwargs.get("user_payload", {}).get("compose_input", {}) or {}
        target_name = compose_input.get("fact_pack", {}).get("target_name", "对方")
        shell_tokens = compose_input.get("style_card", {}).get("shell_tokens", [])
        shell_token = shell_tokens[0] if shell_tokens else "场上"
        return _FakeResponse(
            {
                "narration": f"{target_name}把话压进{shell_token}里，周围人都听见了代价。",
                "coverage_marks": {
                    "target": True,
                    "move": True,
                    "consequence": True,
                    "relationship": True,
                },
                "length_profile": "normal",
            }
        )


def _compose_record(gateway: _ComposeCaptureClient) -> dict[str, object]:
    return next(
        record
        for record in gateway.call_records
        if str(record.get("operation_name") or "") == "play_v2.narration_compose"
    )


def _storylet_dict(
    plan: CompiledPlayPlan,
    storylet_id: str,
    *,
    scene_text: str,
    venue_hint: str,
    preconditions: StoryletCondition | None = None,
) -> dict[str, object]:
    characters = [member.character_id for member in plan.cast[:2]]
    storylet = Storylet(
        storylet_id=storylet_id,
        narrative_function="hook",
        title=f"Title {storylet_id}",
        scene_text=scene_text,
        characters_involved=characters,
        venue_hint=venue_hint,
        dramatic_weight=0.5,
        preconditions=preconditions or StoryletCondition(),
        effects=StoryletEffect(),
    )
    return storylet.model_dump()


def _plan_with_storylets(
    plan: CompiledPlayPlan,
    storylets: list[dict[str, object]] | None,
) -> CompiledPlayPlan:
    return plan.model_copy(update={"storylet_pool": storylets}, deep=True)


def _run_llm_turn(
    monkeypatch: pytest.MonkeyPatch,
    plan: CompiledPlayPlan,
    *,
    state_session_id: str,
    state_updates: dict[str, object] | None = None,
):
    gateway = _ComposeCaptureClient()
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: gateway)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(runtime_module, "get_settings", lambda: _settings_stub(use_llm=True))

    state = build_initial_world_state(plan, session_id=state_session_id)
    if state_updates:
        state = state.model_copy(update=state_updates, deep=True)
    action = build_suggested_actions(plan, state)[0]
    result = run_turn(plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)
    return result, gateway


def _storylet_prompt_body(system_prompt: str) -> str:
    match = re.search(
        r"## 已选情境素材（storylet）\n以下 JSON 已根据当前世界状态匹配完成，不是可选灵感：\n(?P<body>.*?)(?:\n最终叙述必须把 scene_anchor)",
        system_prompt,
        flags=re.DOTALL,
    )
    assert match is not None
    return str(match.group("body"))


def test_llm_path_injects_storylet_hints_into_compose_prompt(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    current_segment = v3_plan.segments[0]
    target_id = v3_plan.cast[0].character_id
    plan = _plan_with_storylets(
        v3_plan,
        [
            _storylet_dict(
                v3_plan,
                "storylet_prompt_hit",
                scene_text="PROMPT_MATCH_片段" + "甲" * 80,
                venue_hint="董事会议室内侧",
                preconditions=StoryletCondition(
                    required_relationships=[target_id],
                    required_segment_roles=[current_segment.segment_role],
                ),
            )
        ],
    )

    _result, gateway = _run_llm_turn(monkeypatch, plan, state_session_id="storylet_prompt_hit")
    record = _compose_record(gateway)
    system_prompt = str(record.get("system_prompt") or "")
    compose_input = dict(record.get("user_payload", {}).get("compose_input", {}) or {})

    assert "## 已选情境素材（storylet）" in system_prompt
    assert "PROMPT_MATCH_片段" in system_prompt
    assert "\"storylet_id\":\"storylet_prompt_hit\"" in system_prompt
    assert "\"preconditions\"" in system_prompt
    assert isinstance(compose_input.get("storylet_hints"), list)
    assert compose_input["storylet_hints"][0]["scene_text"].startswith("PROMPT_MATCH_片段")
    assert compose_input["storylet_hints"][0]["storylet_id"] == "storylet_prompt_hit"


def test_v2_plan_without_storylet_pool_does_not_emit_storylet_prompt_section(
    monkeypatch: pytest.MonkeyPatch,
    v2_plan: CompiledPlayPlan,
) -> None:
    _result, gateway = _run_llm_turn(monkeypatch, v2_plan, state_session_id="storylet_v2_none")
    record = _compose_record(gateway)
    system_prompt = str(record.get("system_prompt") or "")
    compose_input = dict(record.get("user_payload", {}).get("compose_input", {}) or {})

    assert "## 已选情境素材（storylet）" not in system_prompt
    assert compose_input.get("storylet_hints") == []


def test_empty_storylet_matches_do_not_emit_storylet_prompt_section(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    plan = _plan_with_storylets(
        v3_plan,
        [
            _storylet_dict(
                v3_plan,
                "storylet_no_match",
                scene_text="EMPTY_MATCH_片段" + "乙" * 80,
                venue_hint="无人知晓的角落",
                preconditions=StoryletCondition(
                    required_secrets_known=["missing_secret"],
                    required_relationships=["missing_character"],
                    min_tension_score=1.0,
                    required_segment_roles=["terminal"],
                ),
            )
        ],
    )

    _result, gateway = _run_llm_turn(monkeypatch, plan, state_session_id="storylet_empty_match")
    record = _compose_record(gateway)
    system_prompt = str(record.get("system_prompt") or "")
    compose_input = dict(record.get("user_payload", {}).get("compose_input", {}) or {})

    assert "## 已选情境素材（storylet）" not in system_prompt
    assert compose_input.get("storylet_hints") == []


def test_storylet_prompt_section_keeps_structured_selected_storylet_under_seven_hundred_characters(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    current_segment = v3_plan.segments[0]
    target_id = v3_plan.cast[0].character_id
    plan = _plan_with_storylets(
        v3_plan,
        [
            _storylet_dict(
                v3_plan,
                "storylet_keep_high_1",
                scene_text="KEEP_HIGH_1_" + "甲" * 220,
                venue_hint="高层会议室" * 12,
                preconditions=StoryletCondition(
                    required_secrets_known=["secret_keep_high_1"],
                    required_relationships=[target_id],
                    min_tension_score=0.8,
                    required_segment_roles=[current_segment.segment_role],
                ),
            ),
            _storylet_dict(
                v3_plan,
                "storylet_keep_high_2",
                scene_text="KEEP_HIGH_2_" + "乙" * 220,
                venue_hint="签约长桌" * 12,
                preconditions=StoryletCondition(
                    required_secrets_known=["secret_keep_high_2"],
                    required_relationships=[target_id],
                    min_tension_score=0.8,
                    required_segment_roles=["terminal"],
                ),
            ),
            _storylet_dict(
                v3_plan,
                "storylet_drop_low",
                scene_text="DROP_LOW_" + "丙" * 220,
                venue_hint="玻璃走廊" * 12,
                preconditions=StoryletCondition(
                    required_secrets_known=["secret_drop_low_missing"],
                    required_relationships=[target_id],
                    min_tension_score=1.0,
                    required_segment_roles=[current_segment.segment_role],
                ),
            ),
        ],
    )

    _result, gateway = _run_llm_turn(
        monkeypatch,
        plan,
        state_session_id="storylet_truncate",
        state_updates={
            "known_secret_ids": ["secret_keep_high_1", "secret_keep_high_2"],
            "scene_heat": 6,
            "secret_exposure": 6,
            "witness_pressure": 2,
        },
    )
    record = _compose_record(gateway)
    body = _storylet_prompt_body(str(record.get("system_prompt") or ""))

    assert len(body) <= 700
    assert "KEEP_HIGH_1_" in body
    assert "\"storylet_id\":\"storylet_keep_high_1\"" in body
    assert "\"preconditions\"" in body
    assert "\"effects\"" in body
    assert "KEEP_HIGH_2_" not in body
    assert "DROP_LOW_" not in body


def test_deterministic_path_output_is_unchanged_by_storylet_hints(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    current_segment = v3_plan.segments[0]
    target_id = v3_plan.cast[0].character_id
    plan_with_storylets = _plan_with_storylets(
        v3_plan,
        [
            _storylet_dict(
                v3_plan,
                "storylet_det_path",
                scene_text="DET_PATH_片段" + "丁" * 80,
                venue_hint="董事会长桌",
                preconditions=StoryletCondition(
                    required_relationships=[target_id],
                    required_segment_roles=[current_segment.segment_role],
                ),
            )
        ],
    )
    plan_without_storylets = _plan_with_storylets(v3_plan, None)

    monkeypatch.setattr(runtime_module, "get_settings", lambda: _settings_stub(use_llm=False))

    state_with = build_initial_world_state(plan_with_storylets, session_id="storylet_det_with")
    state_without = build_initial_world_state(plan_without_storylets, session_id="storylet_det_without")
    action_with = build_suggested_actions(plan_with_storylets, state_with)[0]
    action_without = build_suggested_actions(plan_without_storylets, state_without)[0]

    result_with = run_turn(
        plan_with_storylets,
        state_with,
        action_with.prompt,
        selected_suggestion_id=action_with.suggestion_id,
    )
    result_without = run_turn(
        plan_without_storylets,
        state_without,
        action_without.prompt,
        selected_suggestion_id=action_without.suggestion_id,
    )

    assert result_with.narration == result_without.narration
    assert result_with.intent_stage_diagnostics["narration_compose_source"] == "deterministic"
    assert result_without.intent_stage_diagnostics["narration_compose_source"] == "deterministic"


def test_diagnostics_include_storylet_match_count_and_ids(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    current_segment = v3_plan.segments[0]
    target_id = v3_plan.cast[0].character_id
    plan = _plan_with_storylets(
        v3_plan,
        [
            _storylet_dict(
                v3_plan,
                "storylet_diag_high",
                scene_text="DIAG_HIGH_" + "甲" * 80,
                venue_hint="董事会议室",
                preconditions=StoryletCondition(
                    required_secrets_known=["secret_diag_high"],
                    required_relationships=[target_id],
                    min_tension_score=0.8,
                    required_segment_roles=[current_segment.segment_role],
                ),
            ),
            _storylet_dict(
                v3_plan,
                "storylet_diag_mid",
                scene_text="DIAG_MID_" + "乙" * 80,
                venue_hint="签约长桌",
                preconditions=StoryletCondition(
                    required_secrets_known=["secret_diag_mid"],
                    required_relationships=[target_id],
                    min_tension_score=0.8,
                    required_segment_roles=["terminal"],
                ),
            ),
            _storylet_dict(
                v3_plan,
                "storylet_diag_low",
                scene_text="DIAG_LOW_" + "丙" * 80,
                venue_hint="玻璃走廊",
                preconditions=StoryletCondition(
                    required_secrets_known=["secret_diag_low_missing"],
                    required_relationships=[target_id],
                    min_tension_score=1.0,
                    required_segment_roles=[current_segment.segment_role],
                ),
            ),
        ],
    )

    result, _gateway = _run_llm_turn(
        monkeypatch,
        plan,
        state_session_id="storylet_diag_ids",
        state_updates={
            "known_secret_ids": ["secret_diag_high", "secret_diag_mid"],
            "scene_heat": 6,
            "secret_exposure": 6,
            "witness_pressure": 2,
        },
    )
    diagnostics = result.intent_stage_diagnostics

    assert diagnostics["storylet_matches_count"] == 1
    assert diagnostics["storylet_matches_ids"] == [
        "storylet_diag_high",
    ]
