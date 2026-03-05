from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from rpg_backend.config.settings import get_settings
from rpg_backend.llm.factory import resolve_openai_models
from rpg_backend.llm.task_executor import TaskExecutionResult, TaskExecutorError, TaskUsage, execute_json_task
from rpg_backend.llm.task_specs import (
    TaskSpec,
    build_readiness_probe_task,
    build_render_narration_task,
    build_route_intent_task,
    validate_narration_payload,
    validate_readiness_probe_payload,
    validate_route_intent_payload,
)
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
from rpg_backend.llm_worker.upstream.base import WorkerUpstreamClient
from rpg_backend.llm_worker.upstream.factory import build_worker_upstream_client


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
        self.upstream_api_format = (
            getattr(settings, "llm_worker_upstream_api_format", None) or "chat_completions"
        ).strip()

        self._client: httpx.AsyncClient | None = None
        self._upstream_client: WorkerUpstreamClient | None = None

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
        return asyncio.get_running_loop().time()

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
            missing.append(
                "one of APP_LLM_OPENAI_GENERATOR_MODEL / APP_LLM_OPENAI_ROUTE_MODEL / APP_LLM_OPENAI_NARRATION_MODEL / APP_LLM_OPENAI_MODEL"
            )
        if self.upstream_api_format not in {"chat_completions", "responses"}:
            missing.append("APP_LLM_WORKER_UPSTREAM_API_FORMAT(chat_completions|responses)")
        return missing

    async def call_json_object(
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

    async def _execute_task(
        self,
        *,
        spec: TaskSpec,
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
        error_code_prefix: str,
    ) -> TaskExecutionResult:
        try:
            return await execute_json_task(
                caller=self,
                model=model,
                system_prompt=spec.system_prompt,
                user_payload=spec.user_payload,
                temperature=temperature,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                error_code_prefix=error_code_prefix,
            )
        except TaskExecutorError as exc:
            raise WorkerTaskError(
                error_code=exc.error_code,
                message=exc.message,
                retryable=exc.retryable,
                provider_status=exc.status_code,
                model=exc.model or model,
                attempts=exc.attempts,
            ) from exc

    async def execute_route_intent_task(
        self,
        payload: WorkerTaskRouteIntentRequest,
    ) -> tuple[WorkerTaskRouteIntentResponse, TaskUsage]:
        started = self._monotonic()
        timeout_seconds = float(payload.timeout_seconds or self.settings.llm_openai_timeout_seconds)
        spec = build_route_intent_task(scene_context=payload.scene_context, text=payload.text)
        execution = await self._execute_task(
            spec=spec,
            model=payload.model,
            temperature=float(payload.temperature),
            max_retries=int(payload.max_retries),
            timeout_seconds=timeout_seconds,
            error_code_prefix="route_task",
        )
        try:
            routed = validate_route_intent_payload(execution.payload)
        except ValueError as exc:
            raise WorkerTaskError(
                error_code="route_task_invalid_response",
                message=str(exc),
                retryable=True,
                model=payload.model,
                attempts=execution.attempts,
            ) from exc

        response = WorkerTaskRouteIntentResponse(
            move_id=routed.move_id.strip(),
            args=dict(routed.args),
            confidence=float(routed.confidence),
            interpreted_intent=routed.interpreted_intent.strip(),
            model=payload.model,
            attempts=execution.attempts,
            retry_count=max(0, execution.attempts - 1),
            duration_ms=int((self._monotonic() - started) * 1000),
        )
        return response, execution.usage

    async def route_intent(self, payload: WorkerTaskRouteIntentRequest) -> WorkerTaskRouteIntentResponse:
        response, _usage = await self.execute_route_intent_task(payload)
        return response

    async def execute_render_narration_task(
        self,
        payload: WorkerTaskNarrationRequest,
    ) -> tuple[WorkerTaskNarrationResponse, TaskUsage]:
        started = self._monotonic()
        timeout_seconds = float(payload.timeout_seconds or self.settings.llm_openai_timeout_seconds)
        spec = build_render_narration_task(slots=payload.slots, style_guard=payload.style_guard)
        execution = await self._execute_task(
            spec=spec,
            model=payload.model,
            temperature=float(payload.temperature),
            max_retries=int(payload.max_retries),
            timeout_seconds=timeout_seconds,
            error_code_prefix="narration_task",
        )
        try:
            narration = validate_narration_payload(execution.payload)
        except ValueError as exc:
            raise WorkerTaskError(
                error_code="narration_task_invalid_response",
                message=str(exc),
                retryable=True,
                model=payload.model,
                attempts=execution.attempts,
            ) from exc

        response = WorkerTaskNarrationResponse(
            narration_text=narration.narration_text.strip(),
            model=payload.model,
            attempts=execution.attempts,
            retry_count=max(0, execution.attempts - 1),
            duration_ms=int((self._monotonic() - started) * 1000),
        )
        return response, execution.usage

    async def render_narration(self, payload: WorkerTaskNarrationRequest) -> WorkerTaskNarrationResponse:
        response, _usage = await self.execute_render_narration_task(payload)
        return response

    async def execute_json_object_task(
        self,
        payload: WorkerTaskJsonObjectRequest,
    ) -> tuple[WorkerTaskJsonObjectResponse, TaskUsage]:
        started = self._monotonic()
        timeout_seconds = float(payload.timeout_seconds or self.settings.llm_openai_timeout_seconds)
        spec = TaskSpec(
            task_name="json_object",
            system_prompt=payload.system_prompt,
            user_payload=payload.user_prompt,
        )
        execution = await self._execute_task(
            spec=spec,
            model=payload.model,
            temperature=float(payload.temperature),
            max_retries=int(payload.max_retries),
            timeout_seconds=timeout_seconds,
            error_code_prefix="json_task",
        )
        response = WorkerTaskJsonObjectResponse(
            payload=execution.payload,
            model=payload.model,
            attempts=execution.attempts,
            retry_count=max(0, execution.attempts - 1),
            duration_ms=int((self._monotonic() - started) * 1000),
        )
        return response, execution.usage

    async def json_object(self, payload: WorkerTaskJsonObjectRequest) -> WorkerTaskJsonObjectResponse:
        response, _usage = await self.execute_json_object_task(payload)
        return response

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
            execution = await self._execute_task(
                spec=build_readiness_probe_task(),
                model=probe_model,
                temperature=0.0,
                max_retries=1,
                timeout_seconds=float(self.settings.ready_llm_probe_timeout_seconds),
                error_code_prefix="worker_probe",
            )
            parsed = validate_readiness_probe_payload(execution.payload)
            return self._check_payload(
                ok=True,
                latency_ms=int((self._monotonic() - started) * 1000),
                meta={
                    "cached": False,
                    "probe_model": probe_model,
                    "base_url_host": urlparse(self.base_url).hostname,
                    "who_preview": parsed.who.strip()[:120],
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
