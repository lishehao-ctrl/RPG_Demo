from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from rpg_backend.config.settings import get_settings
from rpg_backend.llm_worker.route_paths import (
    WORKER_JSON_OBJECT_TASK_PATH,
    WORKER_READY_PATH,
    WORKER_RENDER_NARRATION_TASK_PATH,
    WORKER_ROUTE_INTENT_TASK_PATH,
)


@dataclass
class WorkerClientError(RuntimeError):
    error_code: str
    message: str
    retryable: bool = False
    status_code: int | None = None
    model: str | None = None
    attempts: int | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)


class WorkerClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        connect_timeout_seconds: float,
        max_connections: int,
        max_keepalive_connections: int,
        http2_enabled: bool,
        internal_token: str,
    ) -> None:
        normalized = (base_url or "").strip().rstrip("/")
        if not normalized:
            raise WorkerClientError(
                error_code="llm_worker_misconfigured",
                message="APP_LLM_WORKER_BASE_URL is required",
                retryable=False,
            )
        self.base_url = normalized
        self.host = urlparse(normalized).hostname
        self.internal_token = (internal_token or "").strip()
        if not self.internal_token:
            raise WorkerClientError(
                error_code="llm_worker_misconfigured",
                message="APP_INTERNAL_WORKER_TOKEN is required",
                retryable=False,
            )

        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits, http2=bool(http2_enabled))

    async def aclose(self) -> None:
        await self._client.aclose()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _parse_error_payload(payload: dict[str, Any]) -> tuple[str, str, bool, int | None, str | None, int | None]:
        if isinstance(payload.get("error"), dict):
            err = payload["error"]
            return (
                str(err.get("code") or "llm_worker_request_failed"),
                str(err.get("message") or "worker request failed"),
                bool(err.get("retryable", False)),
                None,
                None,
                None,
            )
        return (
            str(payload.get("error_code") or "llm_worker_request_failed"),
            str(payload.get("message") or "worker request failed"),
            bool(payload.get("retryable", False)),
            int(payload["provider_status"]) if payload.get("provider_status") is not None else None,
            str(payload.get("model")) if payload.get("model") else None,
            int(payload["attempts"]) if payload.get("attempts") is not None else None,
        )

    async def _post_json(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        headers = {"X-Internal-Worker-Token": self.internal_token}
        try:
            response = await self._client.post(
                self._url(path),
                json=payload,
                timeout=timeout_seconds,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise WorkerClientError(
                error_code="llm_worker_timeout",
                message=str(exc),
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise WorkerClientError(
                error_code="llm_worker_unreachable",
                message=str(exc),
                retryable=True,
            ) from exc

        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            data = {}

        if response.status_code >= 400:
            error_code, message, retryable, status_code, model, attempts = self._parse_error_payload(
                data if isinstance(data, dict) else {}
            )
            raise WorkerClientError(
                error_code=error_code,
                message=message,
                retryable=retryable,
                status_code=status_code or response.status_code,
                model=model,
                attempts=attempts,
            )

        if not isinstance(data, dict):
            raise WorkerClientError(
                error_code="llm_worker_invalid_response",
                message="worker returned non-object response",
                retryable=True,
            )
        return data

    async def route_intent(
        self,
        *,
        scene_context: dict[str, Any],
        text: str,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return await self._post_json(
            path=WORKER_ROUTE_INTENT_TASK_PATH,
            payload={
                "scene_context": scene_context,
                "text": text or "",
                "model": model,
                "temperature": temperature,
                "max_retries": max_retries,
                "timeout_seconds": timeout_seconds,
            },
            timeout_seconds=timeout_seconds,
        )

    async def render_narration(
        self,
        *,
        slots: dict[str, Any],
        style_guard: str,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return await self._post_json(
            path=WORKER_RENDER_NARRATION_TASK_PATH,
            payload={
                "slots": slots,
                "style_guard": style_guard,
                "model": model,
                "temperature": temperature,
                "max_retries": max_retries,
                "timeout_seconds": timeout_seconds,
            },
            timeout_seconds=timeout_seconds,
        )

    async def json_object(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        response = await self._post_json(
            path=WORKER_JSON_OBJECT_TASK_PATH,
            payload={
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
                "temperature": temperature,
                "max_retries": max_retries,
                "timeout_seconds": timeout_seconds,
            },
            timeout_seconds=timeout_seconds,
        )
        payload = response.get("payload")
        if not isinstance(payload, dict):
            raise WorkerClientError(
                error_code="llm_worker_invalid_response",
                message="worker json-object task did not return payload object",
                retryable=True,
            )
        return response

    async def probe_ready(self, *, refresh: bool = False) -> tuple[int, dict[str, Any]]:
        try:
            response = await self._client.get(
                self._url(WORKER_READY_PATH),
                params={"refresh": str(bool(refresh)).lower()},
            )
        except httpx.TimeoutException as exc:
            raise WorkerClientError(
                error_code="llm_worker_timeout",
                message=str(exc),
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise WorkerClientError(
                error_code="llm_worker_unreachable",
                message=str(exc),
                retryable=True,
            ) from exc

        try:
            data = response.json()
        except Exception:  # noqa: BLE001
            data = {}

        if not isinstance(data, dict):
            raise WorkerClientError(
                error_code="llm_worker_invalid_response",
                message="worker /ready returned non-object response",
                retryable=True,
            )
        return response.status_code, data


_worker_client: WorkerClient | None = None
_worker_client_base_url: str | None = None


def get_worker_client() -> WorkerClient:
    global _worker_client, _worker_client_base_url
    settings = get_settings()
    base_url = (settings.llm_worker_base_url or "").strip().rstrip("/")
    if _worker_client is None or _worker_client_base_url != base_url:
        old_client = _worker_client
        _worker_client = WorkerClient(
            base_url=base_url,
            timeout_seconds=float(settings.llm_worker_timeout_seconds),
            connect_timeout_seconds=float(settings.llm_worker_connect_timeout_seconds),
            max_connections=int(settings.llm_worker_max_connections),
            max_keepalive_connections=int(settings.llm_worker_max_keepalive_connections),
            http2_enabled=bool(settings.llm_worker_http2_enabled),
            internal_token=settings.internal_worker_token or "",
        )
        _worker_client_base_url = base_url
        if old_client is not None:
            try:
                asyncio.get_running_loop().create_task(old_client.aclose())
            except RuntimeError:
                asyncio.run(old_client.aclose())
    return _worker_client


async def close_worker_client_cache() -> None:
    global _worker_client, _worker_client_base_url
    client = _worker_client
    _worker_client = None
    _worker_client_base_url = None
    if client is not None:
        await client.aclose()
