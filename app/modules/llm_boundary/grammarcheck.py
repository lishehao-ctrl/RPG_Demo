from __future__ import annotations

import json

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JSONSchemaValidationError

from app.modules.llm_boundary.errors import (
    GRAMMAR_JSON_PARSE,
    GRAMMAR_OUTPUT_SHAPE,
    GRAMMAR_SCHEMA_VALIDATE,
    GrammarCheckError,
)


def _snippet(raw: object, limit: int = 240) -> str | None:
    if raw is None:
        return None
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    text = " ".join(str(text).split())
    if not text:
        return None
    return text[:limit]


def parse_payload(raw: str | dict | list) -> object:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise GrammarCheckError(
                "empty json content",
                error_kind=GRAMMAR_JSON_PARSE,
                raw_snippet=_snippet(raw),
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GrammarCheckError(
                f"json parse failed: {exc}",
                error_kind=GRAMMAR_JSON_PARSE,
                raw_snippet=_snippet(raw),
            ) from exc
    if isinstance(raw, (dict, list)):
        return raw
    raise GrammarCheckError(
        "payload must be string/object/array",
        error_kind=GRAMMAR_JSON_PARSE,
        raw_snippet=_snippet(raw),
    )


def validate_schema(payload: object, schema: dict) -> None:
    if not isinstance(schema, dict) or not schema:
        raise GrammarCheckError("schema missing", error_kind=GRAMMAR_SCHEMA_VALIDATE)
    try:
        Draft202012Validator(schema).validate(payload)
    except JSONSchemaValidationError as exc:
        raise GrammarCheckError(
            f"schema validate failed: {exc.message}",
            error_kind=GRAMMAR_SCHEMA_VALIDATE,
            raw_snippet=_snippet(payload),
        ) from exc


def ensure_object(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise GrammarCheckError(
            "top-level output must be object",
            error_kind=GRAMMAR_OUTPUT_SHAPE,
            raw_snippet=_snippet(payload),
        )
    return payload


def validate_structured_output(raw: object, *, schema_name: str, schema: dict) -> dict:
    del schema_name
    parsed = parse_payload(raw if isinstance(raw, (str, dict, list)) else str(raw))
    validate_schema(parsed, schema)
    return ensure_object(parsed)
