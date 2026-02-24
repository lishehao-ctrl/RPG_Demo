import uuid

import pytest

from app.config import settings
from app.modules.llm.adapter import AuthorAssistParseError, LLMRuntime
from app.modules.llm.base import LLMProvider


class _DbStub:
    def add(self, row) -> None:  # noqa: ANN001
        return None


class _SequenceProvider(LLMProvider):
    name = "fake"

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt: str,
        *,
        request_id: str,
        timeout_s: float | None,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
    ):
        _ = messages_override
        self.calls.append(
            {
                "prompt": prompt,
                "timeout_s": timeout_s,
                "max_tokens_override": max_tokens_override,
                "temperature_override": temperature_override,
            }
        )
        if self._responses:
            payload = self._responses.pop(0)
        else:
            payload = {"suggestions": {}, "patch_preview": [], "warnings": []}
        return (
            payload,
            {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "latency_ms": 1,
                "status": "success",
                "error_message": None,
            },
        )


def _build_runtime(monkeypatch: pytest.MonkeyPatch, responses: list[object]) -> tuple[LLMRuntime, _SequenceProvider]:
    runtime = LLMRuntime()
    provider = _SequenceProvider(responses)
    runtime.providers = {"fake": provider}

    monkeypatch.setattr(settings, "llm_model_generate", "fake-model")
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "llm_retry_attempts_network", 1)

    return runtime, provider


def _valid_blueprint() -> dict:
    return {
        "core_conflict": {
            "protagonist": "student",
            "opposition_actor": "roommate",
            "scarce_resource": "scholarship",
            "deadline": "one week",
            "irreversible_risk": "lose funding",
        },
        "tension_loop_plan": {
            "pressure_open": {"objective": "open", "stakes": "high", "required_entities": ["student"], "risk_level": 3},
            "pressure_escalation": {
                "objective": "escalate",
                "stakes": "higher",
                "required_entities": ["roommate"],
                "risk_level": 4,
            },
            "recovery_window": {
                "objective": "recover",
                "stakes": "tempo",
                "required_entities": ["student"],
                "risk_level": 2,
            },
            "decision_gate": {
                "objective": "decide",
                "stakes": "final",
                "required_entities": ["scholarship"],
                "risk_level": 5,
            },
        },
        "branch_design": {
            "high_risk_push": {
                "short_term_gain": "fast clarity",
                "long_term_cost": "relationship damage",
                "signature_action_type": "study",
            },
            "recovery_stabilize": {
                "short_term_gain": "stability",
                "long_term_cost": "lost tempo",
                "signature_action_type": "rest",
            },
        },
        "lexical_anchors": {
            "must_include_terms": ["roommate", "scholarship"],
            "avoid_generic_labels": ["Option A"],
        },
    }


def _valid_cast_blueprint() -> dict:
    return {
        "target_npc_count": 4,
        "npc_roster": [
            {
                "name": "Alice",
                "role": "support friend",
                "motivation": "Protect team morale",
                "tension_hook": "Pushes back on reckless plans",
                "relationship_to_protagonist": "Close ally under pressure",
            },
            {
                "name": "Reed",
                "role": "rival competitor",
                "motivation": "Win recognition quickly",
                "tension_hook": "Escalates conflicts for short-term gain",
                "relationship_to_protagonist": "Academic rival",
            },
            {
                "name": "Professor Lin",
                "role": "gatekeeper advisor",
                "motivation": "Guard process quality",
                "tension_hook": "Blocks weak evidence",
                "relationship_to_protagonist": "Advisor with approval power",
            },
        ],
        "beat_presence": {
            "pressure_open": ["Alice", "Reed"],
            "pressure_escalation": ["Reed", "Professor Lin"],
            "recovery_window": ["Alice", "Professor Lin"],
            "decision_gate": ["Alice", "Reed", "Professor Lin"],
        },
    }


def _context_with_diverse_npcs() -> dict:
    return {
        "draft": {
            "characters": {
                "npcs": [
                    {"name": "Alice", "role": "support friend", "traits": ["warm"]},
                    {"name": "Reed", "role": "rival competitor", "traits": ["sharp"]},
                    {"name": "Professor Lin", "role": "gatekeeper advisor", "traits": ["strict"]},
                ]
            }
        }
    }


def test_author_assist_with_fallback_accepts_structured_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, provider = _build_runtime(
        monkeypatch,
        responses=[
            {
                "suggestions": {"flow": {"scenes": []}},
                "patch_preview": [{"id": "p1", "path": "meta.title", "label": "Set title", "value": "Demo"}],
                "warnings": ["note"],
            }
        ],
    )
    out, used_llm = runtime.author_assist_with_fallback(
        _DbStub(),
        prompt='{"task":"seed_expand"}',
        session_id=None,
        step_id=uuid.uuid4(),
        max_tokens_override=2048,
    )
    assert used_llm is True
    assert isinstance(out.get("suggestions"), dict)
    assert isinstance(out.get("patch_preview"), list)
    assert isinstance(out.get("warnings"), list)
    assert provider.calls[0]["max_tokens_override"] == 2048
    assert provider.calls[0]["temperature_override"] == 0.0


def test_author_assist_with_fallback_retries_same_prompt_without_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, provider = _build_runtime(
        monkeypatch,
        responses=[
            {"foo": "bar"},
            {
                "suggestions": {"meta": {"title": "Recovered"}},
                "patch_preview": [],
                "warnings": [],
            },
        ],
    )
    out, used_llm = runtime.author_assist_with_fallback(
        _DbStub(),
        prompt='{"task":"seed_expand"}',
        session_id=None,
        step_id=uuid.uuid4(),
    )
    assert used_llm is True
    assert out.get("suggestions", {}).get("meta", {}).get("title") == "Recovered"
    assert len(provider.calls) == 2
    assert provider.calls[0]["prompt"] == '{"task":"seed_expand"}'
    assert provider.calls[1]["prompt"] == '{"task":"seed_expand"}'


def test_author_assist_with_fallback_invalid_payload_raises_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _provider = _build_runtime(
        monkeypatch,
        responses=[
            {"foo": "bar"},
            {"narrative_text": "still wrong"},
            {"another": "bad"},
        ],
    )

    with pytest.raises(AuthorAssistParseError) as excinfo:
        runtime.author_assist_with_fallback(
            _DbStub(),
            prompt='{"task":"seed_expand"}',
            session_id=None,
            step_id=uuid.uuid4(),
        )
    assert excinfo.value.error_kind == "ASSIST_SCHEMA_VALIDATE"


def test_author_assist_two_stage_with_fallback_runs_expand_and_build(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, provider = _build_runtime(
        monkeypatch,
        responses=[
            _valid_blueprint(),
            _valid_cast_blueprint(),
            {
                "suggestions": {"flow": {"scenes": []}},
                "patch_preview": [],
                "warnings": [],
            },
        ],
    )
    out, used_llm = runtime.author_assist_two_stage_with_fallback(
        _DbStub(),
        task="seed_expand",
        locale="en",
        context={"seed_text": "Roommate conflict"},
        session_id=None,
        step_id=uuid.uuid4(),
        expand_max_tokens_override=1400,
        build_max_tokens_override=2048,
        repair_max_tokens_override=900,
        expand_temperature_override=0.65,
        build_temperature_override=0.15,
        repair_temperature_override=0.0,
    )
    assert used_llm is True
    assert isinstance(out.get("suggestions"), dict)
    assert len(provider.calls) == 3
    assert provider.calls[0]["max_tokens_override"] == 1400
    assert provider.calls[0]["temperature_override"] == 0.0
    assert provider.calls[1]["max_tokens_override"] == 1400
    assert provider.calls[1]["temperature_override"] == 0.0
    assert provider.calls[2]["max_tokens_override"] == 2048
    assert provider.calls[2]["temperature_override"] == 0.0


def test_author_assist_two_stage_with_fallback_retries_expand_and_build_without_repair_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, provider = _build_runtime(
        monkeypatch,
        responses=[
            {"foo": "bar"},
            _valid_blueprint(),
            {"foo": "bar"},
            {"suggestions": {}, "patch_preview": [], "warnings": []},
        ],
    )
    out, used_llm = runtime.author_assist_two_stage_with_fallback(
        _DbStub(),
        task="seed_expand",
        locale="en",
        context=_context_with_diverse_npcs(),
        session_id=None,
        step_id=uuid.uuid4(),
    )
    assert used_llm is True
    assert isinstance(out.get("patch_preview"), list)
    assert len(provider.calls) == 4
    assert provider.calls[0]["prompt"].startswith("Author idea expansion task.")
    assert provider.calls[1]["prompt"].startswith("Author idea expansion task.")
    assert provider.calls[2]["prompt"].startswith("Author story build task.")
    assert provider.calls[3]["prompt"].startswith("Author story build task.")


def test_author_assist_two_stage_with_fallback_triggers_cast_stage_when_npc_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, provider = _build_runtime(
        monkeypatch,
        responses=[
            _valid_blueprint(),
            _valid_cast_blueprint(),
            {"suggestions": {}, "patch_preview": [], "warnings": []},
        ],
    )
    runtime.author_assist_two_stage_with_fallback(
        _DbStub(),
        task="story_ingest",
        locale="en",
        context={"source_text": "single protagonist draft"},
        session_id=None,
        step_id=uuid.uuid4(),
    )
    assert len(provider.calls) == 3
    assert provider.calls[0]["prompt"].startswith("Author idea expansion task.")
    assert provider.calls[1]["prompt"].startswith("Author cast expansion task.")
    assert provider.calls[2]["prompt"].startswith("Author story build task.")


def test_author_assist_two_stage_with_fallback_skips_cast_stage_when_existing_cast_sufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, provider = _build_runtime(
        monkeypatch,
        responses=[
            _valid_blueprint(),
            {"suggestions": {}, "patch_preview": [], "warnings": []},
        ],
    )
    runtime.author_assist_two_stage_with_fallback(
        _DbStub(),
        task="continue_write",
        locale="en",
        context=_context_with_diverse_npcs(),
        session_id=None,
        step_id=uuid.uuid4(),
    )
    assert len(provider.calls) == 2
    assert provider.calls[0]["prompt"].startswith("Author idea expansion task.")
    assert provider.calls[1]["prompt"].startswith("Author story build task.")


def test_author_assist_two_stage_with_fallback_emits_build_stage_overview_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _provider = _build_runtime(
        monkeypatch,
        responses=[
            _valid_blueprint(),
            _valid_cast_blueprint(),
            {"suggestions": {}, "patch_preview": [], "warnings": []},
        ],
    )
    events: list[object] = []
    runtime.author_assist_two_stage_with_fallback(
        _DbStub(),
        task="continue_write",
        locale="en",
        context={"continue_input": "continue writing with higher pressure"},
        session_id=None,
        step_id=uuid.uuid4(),
        stage_emitter=events.append,
    )

    build_event = next(event for event in events if getattr(event, "stage_code", "") == "author.build.start")
    assert getattr(build_event, "overview_source", "") == "author_idea_blueprint_v1"
    overview_rows = getattr(build_event, "overview_rows", None)
    assert isinstance(overview_rows, list) and len(overview_rows) == 5
    assert any(isinstance(row, dict) and row.get("label") == "Core Conflict" for row in overview_rows)
    assert any(isinstance(row, dict) and row.get("label") == "Task Focus" for row in overview_rows)


def test_author_assist_two_stage_with_fallback_cast_stage_parse_failure_blocks_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, provider = _build_runtime(
        monkeypatch,
        responses=[
            _valid_blueprint(),
            {"bad": "cast"},
            {"still": "bad"},
            {"again": "bad"},
        ],
    )
    events: list[object] = []
    with pytest.raises(AuthorAssistParseError) as excinfo:
        runtime.author_assist_two_stage_with_fallback(
            _DbStub(),
            task="seed_expand",
            locale="en",
            context={"seed_text": "need more npcs"},
            session_id=None,
            step_id=uuid.uuid4(),
            stage_emitter=events.append,
        )
    assert excinfo.value.error_kind == "ASSIST_SCHEMA_VALIDATE"
    stage_codes = [getattr(event, "stage_code", "") for event in events]
    assert "author.cast.start" in stage_codes
    assert "author.build.start" not in stage_codes
    assert len(provider.calls) == 4


def test_author_assist_two_stage_with_fallback_does_not_emit_build_stage_when_expand_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _provider = _build_runtime(
        monkeypatch,
        responses=[
            {"foo": "bar"},
            {"foo": "bar"},
            {"foo": "bar"},
        ],
    )
    events: list[object] = []

    with pytest.raises(AuthorAssistParseError) as excinfo:
        runtime.author_assist_two_stage_with_fallback(
            _DbStub(),
            task="seed_expand",
            locale="en",
            context={},
            session_id=None,
            step_id=uuid.uuid4(),
            stage_emitter=events.append,
        )

    assert excinfo.value.error_kind == "ASSIST_SCHEMA_VALIDATE"
    stage_codes = [getattr(event, "stage_code", "") for event in events]
    assert "author.expand.start" in stage_codes
    assert "author.build.start" not in stage_codes
