from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from rpg_backend.llm.http_pool import get_shared_sync_client
from rpg_backend.llm.openai_compat import (
    build_auth_headers,
    build_json_mode_body,
    extract_chat_content,
    normalize_chat_completions_url,
    parse_json_object,
)
from rpg_backend.llm.retry_policy import is_retriable_llm_error, retry_delay_seconds
from rpg_backend.llm.worker_client import WorkerClient, WorkerClientError


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
        gateway_mode: str,
        base_url: str,
        api_key: str,
        default_timeout_seconds: float,
        connect_timeout_seconds: float,
        max_connections: int,
        max_keepalive_connections: int,
        http2_enabled: bool,
        worker_client: WorkerClient | None = None,
    ) -> None:
        self.gateway_mode = (gateway_mode or "local").strip().lower()
        self.base_url = (base_url or "").strip()
        self.api_key = (api_key or "").strip()
        self.default_timeout_seconds = float(default_timeout_seconds)
        self.connect_timeout_seconds = float(connect_timeout_seconds)
        self.max_connections = int(max_connections)
        self.max_keepalive_connections = int(max_keepalive_connections)
        self.http2_enabled = bool(http2_enabled)
        self.worker_client = worker_client
        self.chat_completions_url = normalize_chat_completions_url(self.base_url) if self.base_url else ""

    def _call_local_json_object(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
    ) -> JsonGatewayResult:
        if not self.base_url or not self.api_key:
            raise JsonGatewayError(
                error_code="json_gateway_misconfigured",
                message="missing base_url/api_key for local gateway",
                retryable=False,
            )

        body = build_json_mode_body(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
        )
        headers = build_auth_headers(self.api_key)
        client = get_shared_sync_client(
            timeout_seconds=timeout_seconds,
            connect_timeout_seconds=self.connect_timeout_seconds,
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections,
            http2_enabled=self.http2_enabled,
        )

        started_at = time.perf_counter()
        last_error: Exception | None = None
        bounded_retries = max(1, min(int(max_retries), 3))
        for attempt in range(1, bounded_retries + 1):
            try:
                response = client.post(self.chat_completions_url, headers=headers, json=body, timeout=timeout_seconds)
                response.raise_for_status()
                parsed = parse_json_object(extract_chat_content(response.json()))
                return JsonGatewayResult(
                    payload=parsed,
                    attempts=attempt,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not is_retriable_llm_error(exc) or attempt >= bounded_retries:
                    break
                delay = retry_delay_seconds(attempt, exc)
                if delay > 0:
                    time.sleep(delay)

        status_code = None
        if isinstance(last_error, httpx.HTTPStatusError):
            status_code = int(last_error.response.status_code)
        message = str(last_error) if last_error else "json-object request failed"
        raise JsonGatewayError(
            error_code="json_gateway_request_failed",
            message=message,
            retryable=is_retriable_llm_error(last_error) if last_error is not None else False,
            status_code=status_code,
            attempts=bounded_retries,
        ) from last_error

    def _call_worker_json_object(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
    ) -> JsonGatewayResult:
        if self.worker_client is None:
            raise JsonGatewayError(
                error_code="llm_worker_misconfigured",
                message="worker client is not initialized",
                retryable=False,
            )

        started_at = time.perf_counter()
        try:
            response = self.worker_client.json_object(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=float(temperature),
                max_retries=int(max_retries),
                timeout_seconds=float(timeout_seconds),
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

    def call_json_object(
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
        if self.gateway_mode == "worker":
            return self._call_worker_json_object(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=temperature,
                max_retries=max_retries,
                timeout_seconds=effective_timeout,
            )
        return self._call_local_json_object(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            max_retries=max_retries,
            timeout_seconds=effective_timeout,
        )
