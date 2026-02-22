import pytest

from app.modules.llm.adapter import LLMRuntime, NarrativeParseError


def test_parse_narrative_accepts_json_string() -> None:
    out = LLMRuntime._parse_narrative('{"narrative_text":"ok"}')
    assert out.narrative_text == "ok"


def test_parse_narrative_accepts_fenced_json() -> None:
    raw = "```json\n{\"narrative_text\":\"hello\"}\n```"
    out = LLMRuntime._parse_narrative(raw)
    assert out.narrative_text == "hello"


def test_parse_narrative_non_json_raises_json_parse_error() -> None:
    with pytest.raises(NarrativeParseError) as excinfo:
        LLMRuntime._parse_narrative("this is not json")
    assert excinfo.value.error_kind == "NARRATIVE_JSON_PARSE"


def test_parse_narrative_missing_required_field_raises_schema_error() -> None:
    with pytest.raises(NarrativeParseError) as excinfo:
        LLMRuntime._parse_narrative("{}")
    assert excinfo.value.error_kind == "NARRATIVE_SCHEMA_VALIDATE"
