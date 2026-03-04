from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from rpg_backend.generator.prompt_compiler import PromptCompileError, PromptCompiler


def _settings_stub(*, max_retries: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        llm_openai_base_url="https://example.com/compatible-mode",
        llm_openai_api_key="test-key",
        llm_openai_model="test-model",
        llm_openai_route_model=None,
        llm_openai_narration_model=None,
        llm_openai_generator_model=None,
        llm_openai_timeout_seconds=5.0,
        llm_openai_generator_temperature=0.15,
        llm_openai_generator_max_retries=max_retries,
    )


def _outline_payload() -> dict[str, object]:
    return {
        "title": "Signal Rift Outline",
        "premise_core": "A city control signal fractures during peak load, forcing responders to coordinate under pressure.",
        "tone": "tense and practical",
        "stakes_core": "Containment delays will cascade into district-wide outages.",
        "beats": [
            {
                "title": "Fault Ignition",
                "objective": "Identify the real source of the fault",
                "conflict": "Telemetry conflicts under political pressure",
                "required_event": "b1.root_cause_locked",
            },
            {
                "title": "Checkpoint Friction",
                "objective": "Secure transit corridors",
                "conflict": "Security lockdown slows operations",
                "required_event": "b2.lockdown_rerouted",
            },
            {
                "title": "Core Arbitration",
                "objective": "Resolve split command directives",
                "conflict": "Teams disagree on stabilization strategy",
                "required_event": "b3.command_resolution",
            },
            {
                "title": "Dawn Commit",
                "objective": "Execute irreversible stabilization",
                "conflict": "Resources are depleted near deadline",
                "required_event": "b4.final_commit",
            },
        ],
        "npcs": [
            {
                "name": "Mara",
                "role": "engineer",
                "motivation": "prevent collapse",
                "red_line": "Never abandon hospitals to save critical infrastructure.",
                "conflict_tags": ["anti_noise"],
            },
            {
                "name": "Rook",
                "role": "security lead",
                "motivation": "protect civilians",
                "red_line": "No plan may sacrifice evacuee corridors for speed.",
                "conflict_tags": ["anti_speed"],
            },
            {
                "name": "Sera",
                "role": "analyst",
                "motivation": "preserve evidence",
                "red_line": "Do not erase audit trails even under pressure.",
                "conflict_tags": ["anti_noise"],
            },
            {
                "name": "Vale",
                "role": "director",
                "motivation": "hold control",
                "red_line": "Do not lose chain of command in public view.",
                "conflict_tags": ["anti_resource_burn"],
            },
        ],
        "scene_constraints": [
            "Open with immediate infrastructure damage.",
            "Escalate with conflicting command priorities.",
            "Force at least one costly compromise.",
            "End with irreversible civic consequences.",
        ],
        "move_bias": ["technical", "investigate", "social"],
        "ending_shape": "pyrrhic",
    }


def _spec_payload(*, premise: str) -> dict[str, object]:
    return {
        "title": "Signal Rift Protocol",
        "premise": premise,
        "tone": "tense and practical",
        "stakes": "Containment failure will cascade through the district grid.",
        "beats": [
            {
                "title": "Fault Ignition",
                "objective": "Find primary signal fault",
                "conflict": "Contradictory telemetry",
                "required_event": "b1.root_cause_locked",
            },
            {
                "title": "Checkpoint Friction",
                "objective": "Cross lockdown corridors",
                "conflict": "Security pressure",
                "required_event": "b2.lockdown_rerouted",
            },
            {
                "title": "Core Arbitration",
                "objective": "Resolve competing plans",
                "conflict": "Team split",
                "required_event": "b3.command_resolution",
            },
            {
                "title": "Dawn Commit",
                "objective": "Execute final stabilization",
                "conflict": "Resources are near exhaustion",
                "required_event": "b4.final_commit",
            },
        ],
        "npcs": [
            {
                "name": "Mara",
                "role": "engineer",
                "motivation": "prevent collapse",
                "red_line": "Never abandon hospitals to save critical infrastructure.",
                "conflict_tags": ["anti_noise"],
            },
            {
                "name": "Rook",
                "role": "security lead",
                "motivation": "protect civilians",
                "red_line": "No plan may sacrifice evacuee corridors for speed.",
                "conflict_tags": ["anti_speed"],
            },
            {
                "name": "Sera",
                "role": "analyst",
                "motivation": "preserve evidence",
                "red_line": "Do not erase audit trails even under pressure.",
                "conflict_tags": ["anti_noise"],
            },
            {
                "name": "Vale",
                "role": "director",
                "motivation": "hold control",
                "red_line": "Do not lose chain of command in public view.",
                "conflict_tags": ["anti_resource_burn"],
            },
        ],
        "scene_constraints": [
            "Open with immediate operational damage.",
            "Escalate with conflicting directives.",
            "Maintain pressure with visible tradeoffs.",
            "Close on a decisive civic consequence.",
        ],
        "move_bias": ["technical", "investigate"],
        "ending_shape": "pyrrhic",
    }


def test_two_stage_compile_success_within_three_calls(monkeypatch) -> None:
    import rpg_backend.generator.prompt_compiler as prompt_module

    monkeypatch.setattr(prompt_module, "get_settings", lambda: _settings_stub(max_retries=3))

    queued = [_outline_payload(), _spec_payload(premise="A compact premise that fits all schema limits.")]
    captured_prompts: list[dict[str, object]] = []

    def _fake_call(self, *, system_prompt: str, payload: dict[str, object]):  # noqa: ANN001, ANN201
        del system_prompt
        captured_prompts.append(dict(payload))
        return queued.pop(0)

    monkeypatch.setattr(prompt_module.PromptCompiler, "_call_json_object", _fake_call)
    compiled = PromptCompiler().compile(
        prompt_text="Generate a concise emergency scenario",
        target_minutes=10,
        npc_count=4,
        style="neutral",
    )

    assert compiled.attempts == 2
    assert captured_prompts[0]["task"] == "compile_story_outline"
    assert captured_prompts[1]["task"] == "compile_story_spec_from_outline"
    assert captured_prompts[1]["validation_feedback"] == []
    assert captured_prompts[1]["field_limits"]["premise"] == "<=400 chars"


def test_two_stage_compile_stage2_validation_feedback_then_success(monkeypatch) -> None:
    import rpg_backend.generator.prompt_compiler as prompt_module

    monkeypatch.setattr(prompt_module, "get_settings", lambda: _settings_stub(max_retries=3))
    queued = [
        _outline_payload(),
        _spec_payload(premise="x" * 401),
        _spec_payload(premise="Schema-safe premise after feedback."),
    ]
    captured_prompts: list[dict[str, object]] = []

    def _fake_call(self, *, system_prompt: str, payload: dict[str, object]):  # noqa: ANN001, ANN201
        del system_prompt
        captured_prompts.append(dict(payload))
        return queued.pop(0)

    monkeypatch.setattr(prompt_module.PromptCompiler, "_call_json_object", _fake_call)
    compiled = PromptCompiler().compile(
        prompt_text="Generate a concise emergency scenario",
        target_minutes=10,
        npc_count=4,
        style="neutral",
    )

    assert compiled.attempts == 3
    assert captured_prompts[2]["task"] == "compile_story_spec_from_outline"
    assert captured_prompts[2]["validation_feedback"]
    assert any("premise" in item for item in captured_prompts[2]["validation_feedback"])
    assert "retry_instruction" in captured_prompts[2]


def test_two_stage_compile_outline_invalid_raises_prompt_outline_invalid(monkeypatch) -> None:
    import rpg_backend.generator.prompt_compiler as prompt_module

    monkeypatch.setattr(prompt_module, "get_settings", lambda: _settings_stub(max_retries=3))

    invalid_outline = _outline_payload()
    invalid_outline["beats"][1]["title"] = invalid_outline["beats"][0]["title"]
    calls = {"count": 0}

    def _always_invalid_outline(self, *, system_prompt: str, payload: dict[str, object]):  # noqa: ANN001, ANN201
        del system_prompt, payload
        calls["count"] += 1
        return invalid_outline

    monkeypatch.setattr(prompt_module.PromptCompiler, "_call_json_object", _always_invalid_outline)

    with pytest.raises(PromptCompileError) as exc_info:
        PromptCompiler().compile(
            prompt_text="Generate a concise emergency scenario",
            target_minutes=10,
            npc_count=4,
        )

    assert exc_info.value.error_code == "prompt_outline_invalid"
    assert calls["count"] == 1


def test_compile_never_truncates_premise_locally(monkeypatch) -> None:
    import rpg_backend.generator.prompt_compiler as prompt_module

    monkeypatch.setattr(prompt_module, "get_settings", lambda: _settings_stub(max_retries=3))
    queued = [
        _outline_payload(),
        _spec_payload(premise="z" * 430),
        _spec_payload(premise="z" * 430),
    ]
    calls = {"count": 0}

    def _always_invalid_spec(self, *, system_prompt: str, payload: dict[str, object]):  # noqa: ANN001, ANN201
        del system_prompt, payload
        calls["count"] += 1
        return queued.pop(0)

    monkeypatch.setattr(prompt_module.PromptCompiler, "_call_json_object", _always_invalid_spec)

    with pytest.raises(PromptCompileError) as exc_info:
        PromptCompiler().compile(
            prompt_text="Generate strict StorySpec without truncation",
            target_minutes=10,
            npc_count=4,
        )

    assert exc_info.value.error_code == "prompt_spec_invalid"
    assert calls["count"] == 3
    assert any("at most 400" in err or "max_length" in err for err in exc_info.value.errors)


def test_build_validation_feedback_adds_style_targets_for_outline_fields() -> None:
    invalid_outline = _outline_payload()
    invalid_outline["premise_core"] = "p" * 260
    invalid_outline["beats"][1]["required_event"] = "required_event_token_" + ("verylong_" * 10)
    invalid_outline["beats"][2]["conflict"] = "conflict_phrase " * 20
    invalid_outline["npcs"][0]["conflict_tags"] = ["invalid_tag"]

    with pytest.raises(ValidationError) as exc_info:
        from rpg_backend.generator.spec_outline_schema import StorySpecOutline

        StorySpecOutline.model_validate(invalid_outline)

    feedback = PromptCompiler._build_validation_feedback(exc_info.value)
    assert any("premise_core" in item and "target: Write 1-2 sentences" in item for item in feedback)
    assert any("beats.1.required_event" in item and "target: Use snake_case tag style, 3-5 words" in item for item in feedback)
    assert any("beats.2.conflict" in item and "target: Write one short sentence, 8-14 words." in item for item in feedback)
    assert any("npcs.0.conflict_tags" in item and "target: Choose 1-3 tags" in item for item in feedback)


def test_outline_payload_contains_style_targets(monkeypatch) -> None:
    import rpg_backend.generator.prompt_compiler as prompt_module

    monkeypatch.setattr(prompt_module, "get_settings", lambda: _settings_stub(max_retries=3))
    queued = [_outline_payload(), _spec_payload(premise="A compact premise that fits all schema limits.")]
    captured_prompts: list[dict[str, object]] = []

    def _fake_call(self, *, system_prompt: str, payload: dict[str, object]):  # noqa: ANN001, ANN201
        del system_prompt
        captured_prompts.append(dict(payload))
        return queued.pop(0)

    monkeypatch.setattr(prompt_module.PromptCompiler, "_call_json_object", _fake_call)
    _ = PromptCompiler().compile(
        prompt_text="Generate a concise emergency scenario",
        target_minutes=10,
        npc_count=4,
        style="neutral",
    )

    assert captured_prompts[0]["task"] == "compile_story_outline"
    style_targets = captured_prompts[0]["style_targets"]
    assert style_targets["premise_core"] == "Write 1-2 sentences, concise and concrete."
    assert style_targets["beats.*.required_event"] == "Use snake_case tag style, 3-5 words, no full sentence."
    assert style_targets["beats.*.conflict"] == "Write one short sentence, 8-14 words."
    assert style_targets["npcs.*.conflict_tags"] == "Choose 1-3 tags from {anti_noise, anti_speed, anti_resource_burn}."
    assert captured_prompts[0]["npc_conflict_tag_catalog"]["anti_noise"]
    assert captured_prompts[1]["npc_conflict_tag_catalog"]["anti_speed"]


def test_outline_invalid_error_notes_include_outline_feedback(monkeypatch) -> None:
    import rpg_backend.generator.prompt_compiler as prompt_module

    monkeypatch.setattr(prompt_module, "get_settings", lambda: _settings_stub(max_retries=3))
    invalid_outline = _outline_payload()
    invalid_outline["premise_core"] = "x" * 300

    def _always_invalid_outline(self, *, system_prompt: str, payload: dict[str, object]):  # noqa: ANN001, ANN201
        del system_prompt, payload
        return invalid_outline

    monkeypatch.setattr(prompt_module.PromptCompiler, "_call_json_object", _always_invalid_outline)

    with pytest.raises(PromptCompileError) as exc_info:
        PromptCompiler().compile(
            prompt_text="Generate a concise emergency scenario",
            target_minutes=10,
            npc_count=4,
        )

    assert exc_info.value.error_code == "prompt_outline_invalid"
    assert any(note.startswith("outline_feedback:") for note in exc_info.value.notes)
    assert any("target: Write 1-2 sentences" in note for note in exc_info.value.notes)
