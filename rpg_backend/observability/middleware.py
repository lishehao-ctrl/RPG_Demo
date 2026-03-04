from __future__ import annotations

import re
import time
from uuid import uuid4

from fastapi import Request
from sqlmodel import Session as DBSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from rpg_backend.config.settings import get_settings
from rpg_backend.observability.context import reset_request_id, set_request_id
from rpg_backend.observability.logging import log_event
from rpg_backend.storage.engine import engine
from rpg_backend.storage.repositories.observability import save_http_request_event

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _resolve_request_id(raw: str | None) -> str:
    value = (raw or "").strip()
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid4().hex


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, service_name: str = "backend") -> None:
        super().__init__(app)
        normalized = str(service_name or "backend").strip().lower()
        self._service_name = normalized or "backend"

    @staticmethod
    def _persist_http_request_event(
        *,
        service: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        request_id: str,
    ) -> None:
        try:
            with DBSession(engine) as db:
                save_http_request_event(
                    db,
                    service=service,
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    request_id=request_id,
                )
        except Exception:  # noqa: BLE001
            # Never fail a live request because observability persistence failed.
            return

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        settings = get_settings()
        header_name = settings.obs_request_id_header
        request_id = _resolve_request_id(request.headers.get(header_name))
        request.state.request_id = request_id
        token = set_request_id(request_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            self._persist_http_request_event(
                service=self._service_name,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
                request_id=request_id,
            )
            log_event(
                "http_request_completed",
                level="ERROR",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
            )
            raise
        finally:
            reset_request_id(token)

        response.headers[header_name] = request_id
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        self._persist_http_request_event(
            service=self._service_name,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        log_event(
            "http_request_completed",
            level="INFO",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
