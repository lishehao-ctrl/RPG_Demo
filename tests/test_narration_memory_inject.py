from __future__ import annotations

import re

import pytest

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import HookState, NarrationEventEntry, NarrationSegmentSummary, UrbanTurnIntent, UrbanWorldState
from rpg_backend.play_v2.narration_memory import append_narration_event, build_narration_memory_context
import rpg_backend.play_v2.runtime as runtime_module
from rpg_backend.play_v2.runtime import (
    NarrationComposeInput,
    _memory_context_prompt_section,
    _render_narration_npc_texture_v2,
    build_initial_world_state,
    build_suggested_actions,
    run_turn,
)


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


def _extract_memory_section(system_prompt: str) -> str | None:
    match = re.search(
        r"(?P<section>\n\n## 当前局势（memory context）.*?叙述必须与上述状态保持一致，不得自相矛盾。)",
        system_prompt,
        flags=re.DOTALL,
    )
    if match is None:
        return None
    return str(match.group("section"))


def _make_hook_state(
    *,
    hook_id: str,
    holder_id: str,
    target_id: str,
    status: str,
    leverage_value: float,
    leverage_type: str = "pressure",
) -> HookState:
    return HookState(
        hook_id=hook_id,
        holder_id=holder_id,
        target_id=target_id,
        source_secret_id=f"{hook_id}_secret",
        leverage_type=leverage_type,
        status=status,  # type: ignore[arg-type]
        leverage_value=leverage_value,
    )


def _render_with_gateway(
    monkeypatch: pytest.MonkeyPatch,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    *,
    use_llm: bool,
):
    gateway = _ComposeCaptureClient()
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(runtime_module, "get_settings", lambda: _settings_stub(use_llm=use_llm))
    narration, diagnostics = _render_narration_npc_texture_v2(
        plan,
        state,
        intent,
        gateway=gateway,
    )
    return narration, diagnostics, gateway


def _normalized_relationship_deltas(raw_relationship_deltas: dict[str, dict[str, int]] | None) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    for character_id, raw_deltas in dict(raw_relationship_deltas or {}).items():
        normalized[str(character_id)] = {
            str(dimension): float(value)
            for dimension, value in dict(raw_deltas).items()
            if dimension in {"affection", "trust", "tension", "suspicion", "dependency"}
        }
    return normalized


def test_llm_path_injects_memory_context_section_with_active_hook(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    state = build_initial_world_state(v3_plan, session_id="memory_prompt_llm")
    target_id = v3_plan.cast[0].character_id
    holder_id = v3_plan.cast[1].character_id
    secret_ids = [str(getattr(secret, "secret_id", "")) for secret in list(getattr(v3_plan, "organic_secrets", []) or [])]
    state.hook_states = {
        "hook_active": _make_hook_state(
            hook_id="hook_active",
            holder_id=holder_id,
            target_id=target_id,
            status="active",
            leverage_value=0.87,
            leverage_type="blackmail",
        )
    }
    state.last_turn_revealed_secret_ids = [secret_ids[0] if secret_ids else "sec_memory_prompt"]
    intent = UrbanTurnIntent(
        input_text="先把话压住她",
        move_family="comfort",
        target_id=target_id,
        scene_frame="private",
    )

    _narration, diagnostics, gateway = _render_with_gateway(
        monkeypatch,
        v3_plan,
        state,
        intent,
        use_llm=True,
    )
    record = _compose_record(gateway)
    system_prompt = str(record.get("system_prompt") or "")

    assert "## 当前局势（memory context）" in system_prompt
    assert f"{holder_id}→{target_id}" in system_prompt
    assert "筹码强度 0.87" in system_prompt
    assert int(diagnostics["memory_context_active_hooks"]) == 1
    assert int(diagnostics["memory_context_total_chars_sent"]) > 0


def test_v2_plan_without_hooks_or_revealed_secrets_does_not_emit_memory_section(
    monkeypatch: pytest.MonkeyPatch,
    v2_plan: CompiledPlayPlan,
) -> None:
    state = build_initial_world_state(v2_plan, session_id="memory_prompt_v2_empty")
    state.hook_states = {}
    state.active_character_ids = []
    state.narration_event_log = []
    state.narration_segment_summaries = []
    state.last_turn_revealed_secret_ids = []
    state.last_turn_relationship_deltas = {}
    intent = UrbanTurnIntent(
        input_text="先稳住场面",
        move_family="comfort",
        target_id=None,
        scene_frame="private",
    )

    _narration, diagnostics, gateway = _render_with_gateway(
        monkeypatch,
        v2_plan,
        state,
        intent,
        use_llm=True,
    )
    record = _compose_record(gateway)
    system_prompt = str(record.get("system_prompt") or "")

    assert "## 当前局势（memory context）" not in system_prompt
    assert int(diagnostics["memory_context_total_chars_sent"]) == 0


def test_memory_context_section_truncates_to_nine_hundred_chars_and_keeps_hooks() -> None:
    compose_input = NarrationComposeInput(
        fact_pack={"target_id": "target_0"},
        style_cases=[{"case_id": "fallback", "text": "保持张力。"}],
        style_card={},
        storylet_hints=[],
        memory_context={
            "active_hook_summary": [
                {
                    "holder_id": f"holder_{index}",
                    "target_id": f"target_{index}",
                    "leverage_type": "blackmail",
                    "status": "active",
                    "leverage_value": 0.95 - index * 0.01,
                }
                for index in range(20)
            ],
            "relationship_trajectory": {
                "target_0": {
                    "affection": "rising",
                    "trust": "rising",
                    "tension": "falling",
                    "suspicion": "stable",
                }
            },
            "revealed_secret_summary": [
                {
                    "secret_id": f"secret_{index}",
                    "title": f"SECRET_{index}",
                    "description_excerpt": "秘密外泄" * 18,
                }
                for index in range(15)
            ],
            "npc_pressure_snapshot": {
                f"npc_{index}": {
                    "pressure_load": 5.0,
                    "humiliation_risk": 4.0,
                    "betrayal_readiness": 3.0,
                }
                for index in range(10)
            },
            "summary_texts": [f"SCENE_SUMMARY_{index}_" + ("旧账回流" * 40) for index in range(2)],
        },
    )

    section, char_count = _memory_context_prompt_section(compose_input)

    assert section
    assert char_count == len(section)
    assert char_count <= 400
    assert len(section) <= 400
    assert "holder_0→target_0" in section
    assert "holder_1→target_1" in section
    assert "SCENE_SUMMARY_0" not in section


def test_narration_event_entry_relationship_deltas_round_trip() -> None:
    entry = NarrationEventEntry(
        turn_index=3,
        fingerprint="fp_round",
        phrase="她先把旧账摆到台面。",
        pattern_fingerprint="pat_round",
        move_family="accuse",
        target_id="npc_a",
        relationship_deltas={
            "npc_a": {"trust": -2.0, "tension": 1.0},
            "npc_b": {"suspicion": 0.5},
        },
    )

    decoded = NarrationEventEntry.model_validate_json(entry.model_dump_json())

    assert decoded.relationship_deltas == entry.relationship_deltas


def test_relationship_trajectory_activates_after_three_written_event_entries() -> None:
    state = UrbanWorldState.model_construct(narration_event_log=[])
    deltas_by_turn = (
        {"npc_a": {"affection": 1.0, "trust": -1.0}},
        {"npc_a": {"affection": 1.0, "trust": -1.0}},
        {"npc_a": {"tension": 1.0, "suspicion": 1.0}},
    )

    for turn_index, relationship_deltas in enumerate(deltas_by_turn, start=1):
        append_narration_event(
            state,
            turn_index=turn_index,
            narration=f"第{turn_index}回合把旧账又往前推了一步。",
            move_family="accuse",
            target_id="npc_a",
        )
        state.narration_event_log[-1] = state.narration_event_log[-1].model_copy(
            update={"relationship_deltas": relationship_deltas}
        )

    context = build_narration_memory_context(state, current_turn_npc_ids=["npc_a"])

    assert context["relationship_trajectory"] == {
        "npc_a": {
            "affection": "rising",
            "trust": "falling",
            "tension": "rising",
            "suspicion": "rising",
        }
    }


def test_deterministic_compose_output_is_unchanged_by_memory_context(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    monkeypatch.setattr(runtime_module, "get_settings", lambda: _settings_stub(use_llm=False))
    base_state = build_initial_world_state(v3_plan, session_id="memory_det_base")
    rich_state = base_state.model_copy(deep=True)
    target_id = v3_plan.cast[0].character_id
    holder_id = v3_plan.cast[1].character_id
    rich_state.hook_states = {
        "hook_det": _make_hook_state(
            hook_id="hook_det",
            holder_id=holder_id,
            target_id=target_id,
            status="active",
            leverage_value=0.91,
        )
    }
    rich_state.last_turn_revealed_secret_ids = ["sec_deterministic"]
    rich_state.narration_event_log = [
        NarrationEventEntry(
            turn_index=1,
            fingerprint="fp_det",
            phrase="她把话压在桌边。",
            pattern_fingerprint="pat_det",
            move_family="comfort",
            target_id=target_id,
            relationship_deltas={target_id: {"trust": 1.0}},
        )
    ]
    rich_state.narration_segment_summaries = [
        NarrationSegmentSummary(
            segment_id="seg_det",
            segment_role="opening",
            summary_text="旧账已经被重新翻到台面。",
            key_events=["旧账翻面"],
            turn_range_start=1,
            turn_range_end=1,
            entry_count=1,
        )
    ]
    intent = UrbanTurnIntent(
        input_text="先把态度按住",
        move_family="comfort",
        target_id=target_id,
        scene_frame="private",
    )

    base_narration, base_diagnostics = _render_narration_npc_texture_v2(v3_plan, base_state, intent)
    rich_narration, rich_diagnostics = _render_narration_npc_texture_v2(v3_plan, rich_state, intent)

    assert base_narration == rich_narration
    assert base_diagnostics["narration_compose_source"] == "deterministic"
    assert rich_diagnostics["narration_compose_source"] == "deterministic"


def test_run_turn_diagnostics_include_memory_context_counts_and_event_write(
    monkeypatch: pytest.MonkeyPatch,
    v3_plan: CompiledPlayPlan,
) -> None:
    gateway = _ComposeCaptureClient()
    monkeypatch.setattr(runtime_module, "get_play_llm_gateway", lambda settings: gateway)
    monkeypatch.setenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "true")
    monkeypatch.setattr(runtime_module, "get_settings", lambda: _settings_stub(use_llm=True))

    state = build_initial_world_state(v3_plan, session_id="memory_diag_turn")
    target_id = v3_plan.cast[0].character_id
    holder_id = v3_plan.cast[1].character_id
    state.hook_states = {
        "hook_diag_a": _make_hook_state(
            hook_id="hook_diag_a",
            holder_id=holder_id,
            target_id=target_id,
            status="active",
            leverage_value=0.88,
            leverage_type="blackmail",
        ),
        "hook_diag_b": _make_hook_state(
            hook_id="hook_diag_b",
            holder_id=target_id,
            target_id=holder_id,
            status="suspected",
            leverage_value=0.52,
            leverage_type="pressure",
        ),
    }

    action = build_suggested_actions(v3_plan, state)[0]
    result = run_turn(v3_plan, state, action.prompt, selected_suggestion_id=action.suggestion_id)
    diagnostics = result.intent_stage_diagnostics
    record = _compose_record(gateway)
    compose_input = dict(record.get("user_payload", {}).get("compose_input", {}) or {})
    memory_context = dict(compose_input.get("memory_context") or {})
    system_prompt = str(record.get("system_prompt") or "")
    memory_section = _extract_memory_section(system_prompt)

    assert int(diagnostics["memory_context_active_hooks"]) == len(memory_context.get("active_hook_summary") or [])
    assert int(diagnostics["memory_context_revealed_secrets"]) == len(memory_context.get("revealed_secret_summary") or [])
    assert int(diagnostics["memory_context_npc_pressure_count"]) == len(memory_context.get("npc_pressure_snapshot") or {})
    assert int(diagnostics["memory_context_total_chars_sent"]) == len(memory_section or "")
    assert int(diagnostics["memory_context_total_chars_sent"]) > 0
    assert result.state.narration_event_log[-1].relationship_deltas == _normalized_relationship_deltas(
        result.state.last_turn_relationship_deltas
    )
