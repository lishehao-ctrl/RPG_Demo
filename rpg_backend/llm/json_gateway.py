from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rpg_backend.llm.responses_transport import ResponsesTransport, ResponsesTransportError


@dataclass(frozen=True)
class JsonGatewayResult:
    payload: dict[str, Any]
    attempts: int
    duration_ms: int
    response_id: str | None = None


@dataclass
class JsonGatewayError(RuntimeError):
    error_code: str
    message: str
    retryable: bool = False
    status_code: int | None = None
    attempts: int = 1

    def __post_init__(self) -> None:
        super().__init__(self.message)


class ResponsesJsonGateway:
    def __init__(self, *, transport: ResponsesTransport) -> None:
        self._transport = transport

    async def call_json_object(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        timeout_seconds: float,
        enable_thinking: bool,
        previous_response_id: str | None = None,
    ) -> JsonGatewayResult:
        del temperature
        try:
            response = await self._transport.create(
                model=model,
                input=[
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_prompt}],
                    },
                ],
                previous_response_id=previous_response_id,
                timeout=float(timeout_seconds),
                extra_body={"enable_thinking": bool(enable_thinking)},
            )
        except ResponsesTransportError as exc:
            status_code: int | None = None
            message = str(exc.message or "")
            if message.startswith("status="):
                try:
                    status_code = int(message.split("=", 1)[1].strip())
                except Exception:  # noqa: BLE001
                    status_code = None
            raise JsonGatewayError(
                error_code=exc.error_code,
                message=exc.message,
                retryable=exc.retryable,
                status_code=status_code,
                attempts=1,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise JsonGatewayError(
                error_code="json_task_failed",
                message=str(exc),
                retryable=False,
                status_code=None,
                attempts=1,
            ) from exc

        try:
            payload = json.loads(response.output_text)
        except Exception as exc:  # noqa: BLE001
            raise JsonGatewayError(
                error_code="json_task_invalid_response",
                message=str(exc),
                retryable=False,
                status_code=None,
                attempts=1,
            ) from exc

        if not isinstance(payload, dict):
            raise JsonGatewayError(
                error_code="json_task_invalid_response",
                message="payload is not a JSON object",
                retryable=False,
                status_code=None,
                attempts=1,
            )

        return JsonGatewayResult(
            payload=payload,
            attempts=1,
            duration_ms=int(response.duration_ms),
            response_id=response.response_id,
        )
