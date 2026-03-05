from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import json

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.api.errors import ApiError, register_error_handlers
from rpg_backend.config.settings import get_settings
from rpg_backend.llm.worker_client import close_worker_client_cache
from rpg_backend.llm_worker.dispatcher import WorkerDispatcher, WorkerQueueConfig
from rpg_backend.llm_worker.errors import WorkerTaskError
from rpg_backend.llm_worker.route_paths import (
    WORKER_HEALTH_PATH,
    WORKER_JSON_OBJECT_TASK_PATH,
    WORKER_READY_PATH,
    WORKER_RENDER_NARRATION_TASK_PATH,
    WORKER_ROUTE_INTENT_TASK_PATH,
)
from rpg_backend.llm_worker.schemas import (
    WorkerReadyResponse,
    WorkerTaskJsonObjectRequest,
    WorkerTaskJsonObjectResponse,
    WorkerTaskNarrationRequest,
    WorkerTaskNarrationResponse,
    WorkerTaskRouteIntentRequest,
    WorkerTaskRouteIntentResponse,
)
from rpg_backend.llm_worker.services.quota_service import QuotaService
from rpg_backend.llm_worker.services.readiness_service import WorkerReadinessService
from rpg_backend.llm_worker.services.task_service import WorkerTaskService
from rpg_backend.observability.context import get_request_id
from rpg_backend.observability.logging import configure_logging, log_event
from rpg_backend.observability.middleware import RequestIdMiddleware
from rpg_backend.security.bootstrap import assert_production_secret_requirements
from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.repositories.observability_async import save_readiness_probe_event
from rpg_backend.storage.migrations import assert_schema_current

task_service = WorkerTaskService()
readiness_service = WorkerReadinessService(task_service=task_service)
dispatcher: WorkerDispatcher | None = None


async def _save_worker_readiness_probe(
    *,
    ok: bool,
    error_code: str | None,
    latency_ms: int | None,
    request_id: str | None,
) -> None:
    try:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            await save_readiness_probe_event(
                db,
                service="worker",
                ok=ok,
                error_code=error_code,
                latency_ms=latency_ms,
                request_id=request_id,
            )
    except Exception:  # noqa: BLE001
        return


@asynccontextmanager
async def lifespan(_: FastAPI):
    global dispatcher
    configure_logging()
    assert_schema_current()
    assert_production_secret_requirements()
    await task_service.startup()
    settings = get_settings()
    weights_raw = (getattr(settings, "llm_worker_queue_weights_json", "") or "").strip()
    try:
        weights_payload = json.loads(weights_raw) if weights_raw else {}
    except Exception:  # noqa: BLE001
        weights_payload = {}
    queue_config = WorkerQueueConfig(
        max_size=int(getattr(settings, "llm_worker_queue_max_size", 1024)),
        wait_timeout_seconds=float(getattr(settings, "llm_worker_queue_wait_timeout_seconds", 8.0)),
        weights={
            "route_intent": int((weights_payload or {}).get("route_intent", 5)),
            "render_narration": int((weights_payload or {}).get("render_narration", 3)),
            "json_object": int((weights_payload or {}).get("json_object", 2)),
        },
        executor_concurrency=int(getattr(settings, "llm_worker_executor_concurrency", 16)),
        token_est_route_output=int(getattr(settings, "llm_worker_token_est_route_output", 96)),
        token_est_narration_output=int(getattr(settings, "llm_worker_token_est_narration_output", 192)),
        token_est_json_output=int(getattr(settings, "llm_worker_token_est_json_output", 256)),
    )
    dispatcher = WorkerDispatcher(
        service=task_service,
        quota_service=QuotaService(),
        config=queue_config,
    )
    await dispatcher.start()
    yield
    if dispatcher is not None:
        await dispatcher.stop()
        dispatcher = None
    await task_service.shutdown()
    await close_worker_client_cache()


app = FastAPI(title="RPG LLM Worker", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware, service_name="worker")
register_error_handlers(app)


def _task_error_response(exc: WorkerTaskError) -> JSONResponse:
    if exc.error_code in {"worker_queue_full", "worker_queue_timeout", "worker_rate_limited"}:
        status_code = 429
    elif exc.error_code == "worker_token_invalid":
        status_code = 401
    else:
        status_code = 503
    return JSONResponse(status_code=status_code, content=exc.to_payload().model_dump(mode="json"))


def _require_worker_internal_token(
    header_token: str | None = Header(default=None, alias="X-Internal-Worker-Token"),
) -> None:
    expected = (get_settings().internal_worker_token or "").strip()
    provided = (header_token or "").strip()
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        raise ApiError(
            status_code=401,
            code="worker_token_invalid",
            message="invalid worker internal token",
            retryable=False,
        )


@app.get(WORKER_HEALTH_PATH)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(WORKER_READY_PATH, response_model=WorkerReadyResponse)
async def ready(request: Request, refresh: bool = Query(default=False)) -> WorkerReadyResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    report = await readiness_service.ready(refresh=refresh)
    llm_config_ok = bool(report.checks["llm_config"].ok)
    llm_probe_ok = bool(report.checks["llm_probe"].ok)

    if report.status == "ready":
        latency_ms = report.checks["llm_probe"].latency_ms
        await _save_worker_readiness_probe(
            ok=True,
            error_code=None,
            latency_ms=latency_ms,
            request_id=request_id,
        )
        log_event(
            "llm_worker_ready_succeeded",
            level="INFO",
            request_id=request_id,
            status_code=200,
            llm_config_ok=llm_config_ok,
            llm_probe_ok=llm_probe_ok,
            llm_probe_cached=bool(report.checks["llm_probe"].meta.get("cached")),
            refresh=bool(refresh),
        )
        return report

    error_code = report.checks["llm_probe"].error_code or report.checks["llm_config"].error_code
    await _save_worker_readiness_probe(
        ok=False,
        error_code=error_code,
        latency_ms=report.checks["llm_probe"].latency_ms,
        request_id=request_id,
    )
    log_event(
        "llm_worker_ready_failed",
        level="ERROR",
        request_id=request_id,
        status_code=503,
        llm_config_ok=llm_config_ok,
        llm_probe_ok=llm_probe_ok,
        llm_probe_cached=bool(report.checks["llm_probe"].meta.get("cached")),
        refresh=bool(refresh),
        error_code=error_code,
    )
    return JSONResponse(status_code=503, content=report.model_dump(mode="json"))


@app.post(WORKER_ROUTE_INTENT_TASK_PATH, response_model=WorkerTaskRouteIntentResponse)
async def route_intent_task(
    payload: WorkerTaskRouteIntentRequest,
    request: Request,
    _: None = Depends(_require_worker_internal_token),
) -> WorkerTaskRouteIntentResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    try:
        assert dispatcher is not None
        result = await dispatcher.submit_route_intent(payload=payload, request_id=request_id)
    except WorkerTaskError as exc:
        log_event(
            "llm_worker_task_failed",
            level="ERROR",
            request_id=request_id,
            llm_task="route_intent",
            model=payload.model,
            error_code=exc.error_code,
            retryable=exc.retryable,
            provider_status=exc.provider_status,
            attempts=exc.attempts,
        )
        return _task_error_response(exc)

    log_event(
        "llm_worker_task_succeeded",
        level="INFO",
        request_id=request_id,
        llm_task="route_intent",
        model=result.model,
        attempts=result.attempts,
        retry_count=result.retry_count,
        duration_ms=result.duration_ms,
    )
    return result


@app.post(WORKER_RENDER_NARRATION_TASK_PATH, response_model=WorkerTaskNarrationResponse)
async def render_narration_task(
    payload: WorkerTaskNarrationRequest,
    request: Request,
    _: None = Depends(_require_worker_internal_token),
) -> WorkerTaskNarrationResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    try:
        assert dispatcher is not None
        result = await dispatcher.submit_render_narration(payload=payload, request_id=request_id)
    except WorkerTaskError as exc:
        log_event(
            "llm_worker_task_failed",
            level="ERROR",
            request_id=request_id,
            llm_task="render_narration",
            model=payload.model,
            error_code=exc.error_code,
            retryable=exc.retryable,
            provider_status=exc.provider_status,
            attempts=exc.attempts,
        )
        return _task_error_response(exc)

    log_event(
        "llm_worker_task_succeeded",
        level="INFO",
        request_id=request_id,
        llm_task="render_narration",
        model=result.model,
        attempts=result.attempts,
        retry_count=result.retry_count,
        duration_ms=result.duration_ms,
    )
    return result


@app.post(WORKER_JSON_OBJECT_TASK_PATH, response_model=WorkerTaskJsonObjectResponse)
async def json_object_task(
    payload: WorkerTaskJsonObjectRequest,
    request: Request,
    _: None = Depends(_require_worker_internal_token),
) -> WorkerTaskJsonObjectResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    try:
        assert dispatcher is not None
        result = await dispatcher.submit_json_object(payload=payload, request_id=request_id)
    except WorkerTaskError as exc:
        log_event(
            "llm_worker_task_failed",
            level="ERROR",
            request_id=request_id,
            llm_task="json_object",
            model=payload.model,
            error_code=exc.error_code,
            retryable=exc.retryable,
            provider_status=exc.provider_status,
            attempts=exc.attempts,
        )
        return _task_error_response(exc)

    log_event(
        "llm_worker_task_succeeded",
        level="INFO",
        request_id=request_id,
        llm_task="json_object",
        model=result.model,
        attempts=result.attempts,
        retry_count=result.retry_count,
        duration_ms=result.duration_ms,
    )
    return result
