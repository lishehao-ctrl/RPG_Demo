from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from rpg_backend.llm.worker_client import WorkerClient, WorkerClientError, get_worker_client


@dataclass(frozen=True)
class JsonGatewayResult:
    payload: dict[str, Any]
    attempts: int
    duration_ms: int


class JsonGatewayError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        retryable: bool,
        status_code: int | None = None,
        attempts: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        self.attempts = attempts


class JsonGateway:
    def __init__(
        self,
        *,
        default_timeout_seconds: float,
        worker_client: WorkerClient | None = None,
        **_unused: Any,
    ) -> None:
        self.default_timeout_seconds = float(default_timeout_seconds)
        self.worker_client = worker_client or get_worker_client()

    async def call_json_object(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float | None = None,
    ) -> JsonGatewayResult:
        effective_timeout = float(timeout_seconds or self.default_timeout_seconds)
        started_at = time.perf_counter()
        try:
            response = await self.worker_client.json_object(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=float(temperature),
                max_retries=int(max_retries),
                timeout_seconds=effective_timeout,
            )
        except WorkerClientError as exc:
            raise JsonGatewayError(
                error_code=exc.error_code,
                message=exc.message,
                retryable=exc.retryable,
                status_code=exc.status_code,
                attempts=exc.attempts,
            ) from exc

        payload = response.get("payload")
        if not isinstance(payload, dict):
            raise JsonGatewayError(
                error_code="llm_worker_invalid_response",
                message="worker json-object response payload is invalid",
                retryable=True,
            )
        attempts = int(response.get("attempts") or 1)
        return JsonGatewayResult(
            payload=payload,
            attempts=attempts,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
