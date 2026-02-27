from __future__ import annotations

import json

from app.config import settings
from app.modules.llm_boundary.service import LLMBoundary


def test_map_free_input_uses_non_stream_schema_single_channel_real_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "https://unified.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "test-model")

    captured: dict = {}

    async def _fake_chat_completion(**kwargs):
        captured.update(kwargs)
        return json.dumps(
            {
                "schema_version": "3.0",
                "decision_code": "SELECT_CHOICE",
                "target_type": "choice",
                "target_id": "c1",
                "confidence": 0.88,
                "intensity_tier": 1,
                "fallback_reason_code": None,
                "reason": "match",
                "top_candidates": [
                    {"target_type": "choice", "target_id": "c1", "confidence": 0.88},
                ],
            }
        )

    monkeypatch.setattr("app.modules.llm_boundary.service.call_chat_completions", _fake_chat_completion)

    out = LLMBoundary().map_free_input_v3(
        player_input="study now",
        scene_brief="campus",
        visible_choices=[{"choice_id": "c1", "text": "study", "intent_tags": ["study"]}],
        available_fallbacks=[{"fallback_id": "fb_no_match", "reason_code": "NO_MATCH"}],
        input_policy_flag=False,
    )
    assert out.target_type == "choice"
    assert out.decision_code == "SELECT_CHOICE"
    assert out.intensity_tier == 1
    assert captured["base_url"] == "https://unified.example/v1"
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "test-model"
    assert captured["path"] == "/chat/completions"
    assert captured["max_attempts"] == 1
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert "strict RPG free-input selector" in captured["messages"][0]["content"]
    assert "confidence_policy=" in captured["messages"][1]["content"]


def test_auto_mode_without_key_uses_fake_path(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_api_key", "")

    async def _should_not_be_called(**kwargs):
        del kwargs
        raise AssertionError("real llm should not be called when api key is empty")

    monkeypatch.setattr("app.modules.llm_boundary.service.call_chat_completions", _should_not_be_called)

    out = LLMBoundary().map_free_input_v3(
        player_input="study now",
        scene_brief="campus",
        visible_choices=[{"choice_id": "c1", "text": "study", "intent_tags": ["study"]}],
        available_fallbacks=[{"fallback_id": "fb_no_match", "reason_code": "NO_MATCH"}],
        input_policy_flag=False,
    )
    assert out.target_type in {"choice", "fallback"}


def test_narrative_uses_stream_text_channel_in_real_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "https://unified.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "test-model")

    captured: dict = {}

    async def _fake_stream_text(**kwargs):
        captured.update(kwargs)
        return "Streamed narrative."

    monkeypatch.setattr("app.modules.llm_boundary.service.call_chat_completions_stream_text", _fake_stream_text)

    out = LLMBoundary().narrative(system_prompt="sys", user_prompt="user")
    assert out.narrative_text == "Streamed narrative."
    assert captured["base_url"] == "https://unified.example/v1"
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "test-model"
    assert captured["path"] == "/chat/completions"


def test_ending_bundle_keeps_schema_first_in_real_mode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_base_url", "https://unified.example/v1")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "test-model")

    captured: dict = {}

    async def _fake_chat_completion(**kwargs):
        captured.update(kwargs)
        return json.dumps(
            {
                "narrative_text": "final text",
                "ending_report": {
                    "title": "title",
                    "one_liner": "line",
                    "life_summary": "summary",
                    "highlights": [{"title": "h1", "detail": "d1"}],
                    "stats": {
                        "total_steps": 3,
                        "fallback_count": 1,
                        "fallback_rate": 0.33,
                        "explicit_count": 1,
                        "rule_count": 1,
                        "llm_count": 0,
                        "fallback_source_count": 1,
                        "energy_delta": -1,
                        "money_delta": 2,
                        "knowledge_delta": 1,
                        "affection_delta": 0,
                    },
                    "persona_tags": ["steady"],
                },
            }
        )

    monkeypatch.setattr("app.modules.llm_boundary.service.call_chat_completions", _fake_chat_completion)

    out = LLMBoundary().ending_bundle(
        slots={
            "ending_id": "ending_forced_fail",
            "ending_outcome": "fail",
            "tone": "somber",
            "epilogue": "ep",
            "language": "English",
            "session_stats_json": '{"total_steps":3}',
            "recent_action_beats_json": '[{"step_index":1}]',
            "session_stats": {"total_steps": 3},
            "recent_action_beats": [{"step_index": 1}],
        }
    )

    assert out.narrative_text == "final text"
    assert captured["base_url"] == "https://unified.example/v1"
    assert captured["path"] == "/chat/completions"
    assert captured["response_format"]["type"] == "json_schema"


def test_provider_trace_label_auto() -> None:
    settings.llm_api_key = ""
    assert LLMBoundary().provider_trace_label() == "fake_auto"
    settings.llm_api_key = "abc"
    assert LLMBoundary().provider_trace_label() == "real_auto"
