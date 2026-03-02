from __future__ import annotations

from rpg_backend.observability.logging import build_input_log_fields, text_digest_12


def test_build_input_log_fields_redacts_text_by_default() -> None:
    payload = build_input_log_fields(
        {"type": "text", "text": "my secret player input"},
        redact_text=True,
    )
    assert payload["input_type"] == "text"
    assert payload["input_text_len"] == 22
    assert payload["input_text_sha256_12"] == text_digest_12("my secret player input")
    assert "input_text" not in payload


def test_build_input_log_fields_includes_text_when_redaction_disabled() -> None:
    payload = build_input_log_fields(
        {"type": "text", "text": "visible"},
        redact_text=False,
    )
    assert payload["input_type"] == "text"
    assert payload["input_text"] == "visible"
    assert payload["input_text_len"] == 7
    assert payload["input_text_sha256_12"] == text_digest_12("visible")
