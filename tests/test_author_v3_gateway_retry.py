from __future__ import annotations

from typing import Literal
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from rpg_backend.author_v3.gateway import AuthorV3GatewayError, AuthorV3LLMGateway, _format_validation_error
from rpg_backend.responses_transport import ResponsesJSONResponse


class _ShellResponse(BaseModel):
    detected_shell: Literal["office_power"]


def _make_gateway(transport: MagicMock) -> AuthorV3LLMGateway:
    gateway = AuthorV3LLMGateway(
        client=object(),
        model="test-model",
        profile_id="pure_gpt",
        timeout_seconds=1.0,
    )
    object.__setattr__(gateway, "_transport", transport)
    return gateway


def _make_response(payload: dict[str, object]) -> ResponsesJSONResponse:
    return ResponsesJSONResponse(
        payload=payload,
        response_id="resp_test",
        usage={},
        input_characters=0,
    )


def _make_invalid_json_error(message: str = "Expecting ',' delimiter: line 1 column 560 (char 559)") -> AuthorV3GatewayError:
    return AuthorV3GatewayError(code="llm_invalid_json", message=message, status_code=502)


def test_invoke_json_no_retry_needed() -> None:
    transport = MagicMock()
    transport.invoke_json.return_value = _make_response({"detected_shell": "office_power"})
    gateway = _make_gateway(transport)

    result = gateway.invoke_json(
        system_prompt="system",
        user_payload={"seed_text": "办公室权力斗争"},
        max_output_tokens=128,
        operation_name="author_v3.test.no_retry",
        response_model=_ShellResponse,
    )

    assert result.parsed == {"detected_shell": "office_power"}
    assert transport.invoke_json.call_count == 1


def test_retry_on_json_decode_error_then_success() -> None:
    transport = MagicMock()
    transport.invoke_json.side_effect = [
        _make_invalid_json_error(),
        _make_response({"detected_shell": "office_power"}),
    ]
    gateway = _make_gateway(transport)

    result = gateway.invoke_json(
        system_prompt="system",
        user_payload={"seed_text": "办公室权力斗争"},
        max_output_tokens=128,
        operation_name="author_v3.test.json_retry",
        response_model=_ShellResponse,
    )

    assert _ShellResponse.model_validate(result.parsed).detected_shell == "office_power"
    assert transport.invoke_json.call_count == 2
    retry_kwargs = transport.invoke_json.call_args_list[1].kwargs
    feedback = retry_kwargs["user_payload"]["json_retry_feedback"]
    assert "malformed" in feedback or "valid JSON" in feedback


def test_retry_exhausted_raises_json_error() -> None:
    transport = MagicMock()
    errors = [
        _make_invalid_json_error("Expecting ',' delimiter: line 1 column 560 (char 559)"),
        _make_invalid_json_error("Expecting property name enclosed in double quotes: line 1 column 17 (char 16)"),
        _make_invalid_json_error("Unterminated string starting at: line 1 column 42 (char 41)"),
    ]
    transport.invoke_json.side_effect = errors
    gateway = _make_gateway(transport)

    with pytest.raises(AuthorV3GatewayError) as exc_info:
        gateway.invoke_json(
            system_prompt="system",
            user_payload={"seed_text": "办公室权力斗争"},
            max_output_tokens=128,
            operation_name="author_v3.test.json_retry_exhausted",
            response_model=_ShellResponse,
            max_retries=2,
        )

    assert exc_info.value is errors[-1]
    assert exc_info.value.code == "llm_invalid_json"
    assert transport.invoke_json.call_count == 3


def test_retry_validation_error_still_works() -> None:
    transport = MagicMock()
    transport.invoke_json.side_effect = [
        _make_response({"detected_shell": "OfficePowerStruggle"}),
        _make_response({"detected_shell": "office_power"}),
    ]
    gateway = _make_gateway(transport)

    result = gateway.invoke_json(
        system_prompt="system",
        user_payload={"seed_text": "办公室权力斗争"},
        max_output_tokens=128,
        operation_name="author_v3.test.retry",
        response_model=_ShellResponse,
    )

    assert _ShellResponse.model_validate(result.parsed).detected_shell == "office_power"
    assert transport.invoke_json.call_count == 2
    retry_kwargs = transport.invoke_json.call_args_list[1].kwargs
    assert "上次输出验证失败" in retry_kwargs["system_prompt"]
    assert "validation_feedback" in retry_kwargs["user_payload"]


def test_invoke_json_raises_after_max_retries() -> None:
    transport = MagicMock()
    transport.invoke_json.side_effect = [
        _make_response({"detected_shell": "OfficePowerStruggle"}),
        _make_response({"detected_shell": "StillWrong"}),
        _make_response({"detected_shell": "WrongAgain"}),
    ]
    gateway = _make_gateway(transport)

    with pytest.raises(ValidationError):
        gateway.invoke_json(
            system_prompt="system",
            user_payload={"seed_text": "办公室权力斗争"},
            max_output_tokens=128,
            operation_name="author_v3.test.raise_after_retry",
            response_model=_ShellResponse,
            max_retries=2,
        )

    assert transport.invoke_json.call_count == 3


def test_format_validation_error_contains_field_and_type() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _ShellResponse.model_validate({"detected_shell": "OfficePowerStruggle"})

    output = _format_validation_error(exc_info.value)

    assert "detected_shell" in output
    assert "literal_error" in output


def test_invoke_json_without_response_model_no_retry() -> None:
    transport = MagicMock()
    transport.invoke_json.return_value = _make_response({"detected_shell": "OfficePowerStruggle"})
    gateway = _make_gateway(transport)

    result = gateway.invoke_json(
        system_prompt="system",
        user_payload={"seed_text": "办公室权力斗争"},
        max_output_tokens=128,
        operation_name="author_v3.test.no_response_model",
    )

    assert result.payload == {"detected_shell": "OfficePowerStruggle"}
    assert transport.invoke_json.call_count == 1
