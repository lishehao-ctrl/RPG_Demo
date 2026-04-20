from __future__ import annotations

from typing import Literal
from unittest.mock import MagicMock

from pydantic import BaseModel

from rpg_backend.author_v3.gateway import AuthorV3LLMGateway
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
        response_id="resp_author_live",
        usage={},
        input_characters=0,
    )


def test_author_v3_gateway_retries_with_feedback_on_enum_violation() -> None:
    transport = MagicMock()
    transport.invoke_json.side_effect = [
        _make_response({"detected_shell": "OfficePowerStruggle"}),
        _make_response({"detected_shell": "office_power"}),
    ]
    gateway = _make_gateway(transport)

    response = gateway.invoke_json(
        system_prompt="system",
        user_payload={"seed_text": "办公室权力斗争"},
        max_output_tokens=128,
        operation_name="author_v3.live_retry",
        response_model=_ShellResponse,
    )

    parsed = _ShellResponse.model_validate(response.payload)

    assert parsed.detected_shell == "office_power"
    assert transport.invoke_json.call_count == 2
    retry_kwargs = transport.invoke_json.call_args_list[1].kwargs
    assert "上次输出验证失败" in retry_kwargs["system_prompt"]
    assert "validation_feedback" in retry_kwargs["user_payload"]
    assert retry_kwargs["user_payload"]["validation_retry"] == 1
