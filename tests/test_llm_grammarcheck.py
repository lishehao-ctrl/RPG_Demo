from __future__ import annotations

import pytest

from app.modules.llm_boundary.errors import (
    GRAMMAR_JSON_PARSE,
    GRAMMAR_OUTPUT_SHAPE,
    GRAMMAR_SCHEMA_VALIDATE,
    GrammarCheckError,
)
from app.modules.llm_boundary.grammarcheck import validate_structured_output
from app.modules.llm_boundary.schemas import ENDING_REPORT_SCHEMA


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["narrative_text"],
    "properties": {"narrative_text": {"type": "string"}},
}


def test_grammarcheck_valid_json_passes() -> None:
    out = validate_structured_output('{"narrative_text":"ok"}', schema_name="s", schema=SCHEMA)
    assert out["narrative_text"] == "ok"


def test_grammarcheck_invalid_json_raises() -> None:
    with pytest.raises(GrammarCheckError) as exc:
        validate_structured_output('{"narrative_text":', schema_name="s", schema=SCHEMA)
    assert exc.value.error_kind == GRAMMAR_JSON_PARSE


def test_grammarcheck_schema_mismatch_raises() -> None:
    with pytest.raises(GrammarCheckError) as exc:
        validate_structured_output('{"foo":"bar"}', schema_name="s", schema=SCHEMA)
    assert exc.value.error_kind == GRAMMAR_SCHEMA_VALIDATE


def test_grammarcheck_non_object_raises() -> None:
    array_schema = {"type": "array", "items": {"type": "number"}}
    with pytest.raises(GrammarCheckError) as exc:
        validate_structured_output("[1,2]", schema_name="s", schema=array_schema)
    assert exc.value.error_kind == GRAMMAR_OUTPUT_SHAPE


def test_ending_report_schema_rejects_invalid_shape() -> None:
    bad_payload = {
        "title": "End",
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
            "money_delta": 0,
            "knowledge_delta": 2,
            # missing affection_delta
        },
        "persona_tags": ["a"],
    }
    with pytest.raises(GrammarCheckError) as exc:
        validate_structured_output(bad_payload, schema_name="ending", schema=ENDING_REPORT_SCHEMA)
    assert exc.value.error_kind == GRAMMAR_SCHEMA_VALIDATE
