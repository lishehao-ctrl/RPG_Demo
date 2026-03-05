from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from rpg_backend.config.settings import get_settings
from rpg_backend.llm.base import RouteIntentResult
from rpg_backend.llm.factory import resolve_openai_models
from rpg_backend.llm.task_executor import TaskUsage
from rpg_backend.llm.retry_policy import is_retriable_llm_error, retry_delay_seconds
from rpg_backend.llm_worker.upstream.base import WorkerUpstreamClient
from rpg_backend.llm_worker.upstream.factory import build_worker_upstream_client
from rpg_backend.llm_worker.errors import WorkerTaskError
from rpg_backend.llm_worker.schemas import (
    WorkerReadyCheckPayload,
    WorkerReadyResponse,
    WorkerTaskJsonObjectRequest,
    WorkerTaskJsonObjectResponse,
    WorkerTaskNarrationRequest,
    WorkerTaskNarrationResponse,
    WorkerTaskRouteIntentRequest,
    WorkerTaskRouteIntentResponse,
)


class LLMWorkerService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.base_url = (settings.llm_openai_base_url or "").strip()
        self.api_key = (settings.llm_openai_api_key or "").strip()
        route_model, narration_model = resolve_openai_models(
            settings.llm_openai_route_model,
            settings.llm_openai_narration_model,
            settings.llm_openai_model,
        )
        self.route_model = route_model
        self.narration_model = narration_model
        self.generator_model = (settings.llm_openai_generator_model or "").strip() or route_model
        self.upstream_api_format = (getattr(settings, "llm_worker_upstream_api_format", None) or "chat_completions").strip()

        self._client: httpx.AsyncClient | None = None
        self._upstream_client: WorkerUpstreamClient | None = None
        self._route_sem = asyncio.Semaphore(settings.llm_worker_route_max_inflight)
        self._narration_sem = asyncio.Semaphore(settings.llm_worker_narration_max_inflight)
        self._json_sem = asyncio.Semaphore(settings.llm_worker_json_max_inflight)

        self._probe_cache_lock = asyncio.Lock()
        self._probe_cache_key = ""
        self._probe_cache_expires = 0.0
        self._probe_cache_value: WorkerReadyCheckPayload | None = None

    async def startup(self) -> None:
        if self._client is not None:
            return

        limits = httpx.Limits(
            max_connections=self.settings.llm_worker_max_connections,
            max_keepalive_connections=self.settings.llm_worker_max_keepalive_connections,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(
            connect=self.settings.llm_worker_connect_timeout_seconds,
            read=self.settings.llm_worker_timeout_seconds,
            write=self.settings.llm_worker_timeout_seconds,
            pool=self.settings.llm_worker_timeout_seconds,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            http2=bool(self.settings.llm_worker_http2_enabled),
        )
        self._upstream_client = build_worker_upstream_client(
            http_client=self._client,
            api_format=self.upstream_api_format,
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None
        self._upstream_client = None

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _monotonic() -> float:
        return time.monotonic()

    @staticmethod
    def _check_payload(
        *,
        ok: bool,
        latency_ms: int | None,
        error_code: str | None = None,
        message: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> WorkerReadyCheckPayload:
        return WorkerReadyCheckPayload(
            ok=bool(ok),
            checked_at=LLMWorkerService._utc_now(),
            latency_ms=latency_ms,
            error_code=error_code,
            message=message,
            meta=meta or {},
        )

    def _config_missing(self) -> list[str]:
        missing: list[str] = []
        if not self.base_url:
            missing.append("APP_LLM_OPENAI_BASE_URL")
        if not self.api_key:
            missing.append("APP_LLM_OPENAI_API_KEY")
        if not self.generator_model:
            missing.append("one of APP_LLM_OPENAI_GENERATOR_MODEL / APP_LLM_OPENAI_ROUTE_MODEL / APP_LLM_OPENAI_NARRATION_MODEL / APP_LLM_OPENAI_MODEL")
        if self.upstream_api_format not in {"chat_completions", "responses"}:
            missing.append("APP_LLM_WORKER_UPSTREAM_API_FORMAT(chat_completions|responses)")
        return missing

    async def _call_upstream_json_object(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], TaskUsage]:
        if self._client is None:
            await self.startup()
        assert self._upstream_client is not None
        result = await self._upstream_client.call_json_object(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
        return result.payload, result.usage

    @staticmethod
    def _to_worker_error(
        *,
        exc: Exception,
        model: str,
        attempts: int,
        default_code: str,
    ) -> WorkerTaskError:
        if isinstance(exc, httpx.TimeoutException):
            return WorkerTaskError(
                error_code=f"{default_code}_timeout",
                message=str(exc),
                retryable=True,
                model=model,
                attempts=attempts,
            )
        if isinstance(exc, httpx.HTTPStatusError):
            return WorkerTaskError(
                error_code=f"{default_code}_http_error",
                message=f"status={exc.response.status_code}",
                retryable=exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504},
                provider_status=exc.response.status_code,
                model=model,
                attempts=attempts,
            )
        if isinstance(exc, (json.JSONDecodeError, ValueError)):
            return WorkerTaskError(
                error_code=f"{default_code}_invalid_response",
                message=str(exc),
                retryable=True,
                model=model,
                attempts=attempts,
            )
        if isinstance(exc, httpx.HTTPError):
            return WorkerTaskError(
                error_code=f"{default_code}_http_error",
                message=str(exc),
                retryable=True,
                model=model,
                attempts=attempts,
            )
        return WorkerTaskError(
            error_code=f"{default_code}_failed",
            message=str(exc),
            retryable=False,
            model=model,
            attempts=attempts,
        )

    async def _run_json_object_task(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
        error_code_prefix: str,
    ) -> tuple[dict[str, Any], int]:
        last_exc: Exception | None = None
        retries = max(1, min(max_retries, 3))

        for attempt in range(1, retries + 1):
            try:
                payload, _usage = await self._call_upstream_json_object(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    timeout_seconds=timeout_seconds,
                )
                return payload, attempt
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not is_retriable_llm_error(exc):
                    break
                if attempt < retries:
                    delay = retry_delay_seconds(attempt, exc)
                    if delay > 0:
                        await asyncio.sleep(delay)

        assert last_exc is not None
        raise self._to_worker_error(
            exc=last_exc,
            model=model,
            attempts=retries,
            default_code=error_code_prefix,
        )

    async def route_intent(self, payload: WorkerTaskRouteIntentRequest) -> WorkerTaskRouteIntentResponse:
        started = self._monotonic()
        system_prompt = (
            "You route player text to a move. "
            "Return JSON only with keys: move_id (string), args (object), confidence (0..1), interpreted_intent (string). "
            "Prefer scene-specific moves over global moves. "
            "Use scene_snapshot and state_snapshot to infer intent from current pressure, beat goals, and recent events. "
            "Use global.help_me_progress only when the user explicitly asks for help or says they are stuck."
        )
        user_prompt = json.dumps(
            {
                "task": "route_intent",
                "input_text": payload.text or "",
                "fallback_move": payload.scene_context.get("fallback_move"),
                "moves": payload.scene_context.get("moves", []),
                "scene_seed": payload.scene_context.get("scene_seed", ""),
                "scene_snapshot": payload.scene_context.get("scene_snapshot", {}),
                "state_snapshot": payload.scene_context.get("state_snapshot", {}),
                "route_policy": {
                    "prefer_scene_specific": True,
                    "allow_global_help": bool(payload.scene_context.get("allow_global_help", False)),
                },
            },
            ensure_ascii=False,
        )
        timeout_seconds = float(payload.timeout_seconds or self.settings.llm_openai_timeout_seconds)

        async with self._route_sem:
            result, attempts = await self._run_json_object_task(
                model=payload.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=float(payload.temperature),
                max_retries=int(payload.max_retries),
                timeout_seconds=timeout_seconds,
                error_code_prefix="route_task",
            )

        routed = RouteIntentResult.model_validate(result)
        if not routed.move_id.strip():
            raise WorkerTaskError(
                error_code="route_task_invalid_response",
                message="move_id is blank",
                retryable=True,
                model=payload.model,
                attempts=attempts,
            )
        if not routed.interpreted_intent.strip():
            raise WorkerTaskError(
                error_code="route_task_invalid_response",
                message="interpreted_intent is blank",
                retryable=True,
                model=payload.model,
                attempts=attempts,
            )

        return WorkerTaskRouteIntentResponse(
            move_id=routed.move_id.strip(),
            args=dict(routed.args),
            confidence=float(routed.confidence),
            interpreted_intent=routed.interpreted_intent.strip(),
            model=payload.model,
            attempts=attempts,
            retry_count=max(0, attempts - 1),
            duration_ms=int((self._monotonic() - started) * 1000),
        )

    async def render_narration(self, payload: WorkerTaskNarrationRequest) -> WorkerTaskNarrationResponse:
        started = self._monotonic()
        system_prompt = (
            "Write one concise narration paragraph from given slots. "
            "Return JSON only with key narration_text (string)."
        )
        user_prompt = json.dumps(
            {
                "task": "render_narration",
                "style_guard": payload.style_guard,
                "slots": payload.slots,
            },
            ensure_ascii=False,
        )
        timeout_seconds = float(payload.timeout_seconds or self.settings.llm_openai_timeout_seconds)

        async with self._narration_sem:
            result, attempts = await self._run_json_object_task(
                model=payload.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=float(payload.temperature),
                max_retries=int(payload.max_retries),
                timeout_seconds=timeout_seconds,
                error_code_prefix="narration_task",
            )

        narration_text = result.get("narration_text")
        if not isinstance(narration_text, str) or not narration_text.strip():
            raise WorkerTaskError(
                error_code="narration_task_invalid_response",
                message="narration_text is blank",
                retryable=True,
                model=payload.model,
                attempts=attempts,
            )

        return WorkerTaskNarrationResponse(
            narration_text=narration_text.strip(),
            model=payload.model,
            attempts=attempts,
            retry_count=max(0, attempts - 1),
            duration_ms=int((self._monotonic() - started) * 1000),
        )

    async def json_object(self, payload: WorkerTaskJsonObjectRequest) -> WorkerTaskJsonObjectResponse:
        started = self._monotonic()
        timeout_seconds = float(payload.timeout_seconds or self.settings.llm_openai_timeout_seconds)

        async with self._json_sem:
            result, attempts = await self._run_json_object_task(
                model=payload.model,
                system_prompt=payload.system_prompt,
                user_prompt=payload.user_prompt,
                temperature=float(payload.temperature),
                max_retries=int(payload.max_retries),
                timeout_seconds=timeout_seconds,
                error_code_prefix="json_task",
            )

        return WorkerTaskJsonObjectResponse(
            payload=result,
            model=payload.model,
            attempts=attempts,
            retry_count=max(0, attempts - 1),
            duration_ms=int((self._monotonic() - started) * 1000),
        )

    async def _run_probe(self) -> WorkerReadyCheckPayload:
        started = self._monotonic()
        probe_model = self.generator_model or self.route_model or self.narration_model
        if not probe_model:
            return self._check_payload(
                ok=False,
                latency_ms=None,
                error_code="worker_probe_misconfigured",
                message="probe model is missing",
                meta={"cached": False},
            )

        try:
            result, _attempts = await self._run_json_object_task(
                model=probe_model,
                system_prompt="Readiness probe. Return JSON only with keys ok, who.",
                user_prompt="who are you",
                temperature=0.0,
                max_retries=1,
                timeout_seconds=float(self.settings.ready_llm_probe_timeout_seconds),
                error_code_prefix="worker_probe",
            )
            ok_value = result.get("ok")
            who_value = result.get("who")
            if ok_value is not True:
                raise ValueError("probe response ok is not true")
            if not isinstance(who_value, str) or not who_value.strip():
                raise ValueError("probe response who is blank")
            return self._check_payload(
                ok=True,
                latency_ms=int((self._monotonic() - started) * 1000),
                meta={
                    "cached": False,
                    "probe_model": probe_model,
                    "base_url_host": urlparse(self.base_url).hostname,
                    "who_preview": who_value.strip()[:120],
                },
            )
        except WorkerTaskError as exc:
            return self._check_payload(
                ok=False,
                latency_ms=int((self._monotonic() - started) * 1000),
                error_code=exc.error_code,
                message=exc.message,
                meta={
                    "cached": False,
                    "probe_model": probe_model,
                    "base_url_host": urlparse(self.base_url).hostname,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return self._check_payload(
                ok=False,
                latency_ms=int((self._monotonic() - started) * 1000),
                error_code="worker_probe_invalid_response",
                message=str(exc),
                meta={
                    "cached": False,
                    "probe_model": probe_model,
                    "base_url_host": urlparse(self.base_url).hostname,
                },
            )

    async def ready(self, *, refresh: bool = False) -> WorkerReadyResponse:
        checked_at = self._utc_now()
        missing = self._config_missing()
        llm_config_ok = len(missing) == 0

        llm_config = self._check_payload(
            ok=llm_config_ok,
            latency_ms=None,
            error_code=None if llm_config_ok else "worker_llm_config_invalid",
            message=None if llm_config_ok else f"missing config: {', '.join(missing)}",
            meta={
                "route_model": self.route_model,
                "narration_model": self.narration_model,
                "generator_model": self.generator_model,
                "base_url_host": urlparse(self.base_url).hostname,
            },
        )

        if not llm_config_ok:
            llm_probe = self._check_payload(
                ok=False,
                latency_ms=None,
                error_code="worker_probe_misconfigured",
                message="worker probe skipped because llm config is invalid",
                meta={"cached": False, "skipped": True},
            )
            return WorkerReadyResponse(
                status="not_ready",
                checked_at=checked_at,
                checks={"llm_config": llm_config, "llm_probe": llm_probe},
            )

        cache_key = f"{self.base_url}|{self.generator_model or self.route_model or self.narration_model}"
        now = self._monotonic()
        ttl_seconds = int(self.settings.ready_llm_probe_cache_ttl_seconds)
        if not refresh:
            async with self._probe_cache_lock:
                if (
                    self._probe_cache_value is not None
                    and self._probe_cache_key == cache_key
                    and self._probe_cache_expires > now
                ):
                    cached = self._probe_cache_value.model_copy(deep=True)
                    cached.meta["cached"] = True
                    return WorkerReadyResponse(
                        status="ready" if cached.ok else "not_ready",
                        checked_at=checked_at,
                        checks={"llm_config": llm_config, "llm_probe": cached},
                    )

        llm_probe = await self._run_probe()
        async with self._probe_cache_lock:
            self._probe_cache_key = cache_key
            self._probe_cache_expires = self._monotonic() + ttl_seconds
            self._probe_cache_value = llm_probe.model_copy(deep=True)

        return WorkerReadyResponse(
            status="ready" if llm_probe.ok else "not_ready",
            checked_at=checked_at,
            checks={"llm_config": llm_config, "llm_probe": llm_probe},
        )
