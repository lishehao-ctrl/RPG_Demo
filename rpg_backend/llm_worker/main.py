from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from rpg_backend.llm_worker.errors import WorkerTaskError
from rpg_backend.llm_worker.schemas import (
    WorkerReadyResponse,
    WorkerTaskJsonObjectRequest,
    WorkerTaskJsonObjectResponse,
    WorkerTaskNarrationRequest,
    WorkerTaskNarrationResponse,
    WorkerTaskRouteIntentRequest,
    WorkerTaskRouteIntentResponse,
)
from rpg_backend.llm_worker.service import LLMWorkerService
from rpg_backend.observability.context import get_request_id
from rpg_backend.observability.logging import configure_logging, log_event
from rpg_backend.observability.middleware import RequestIdMiddleware

service = LLMWorkerService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    await service.startup()
    yield
    await service.shutdown()


app = FastAPI(title="RPG LLM Worker", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)


def _task_error_response(exc: WorkerTaskError) -> JSONResponse:
    return JSONResponse(status_code=503, content=exc.to_payload().model_dump(mode="json"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", response_model=WorkerReadyResponse)
async def ready(request: Request, refresh: bool = Query(default=False)) -> WorkerReadyResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    report = await service.ready(refresh=refresh)
    llm_config_ok = bool(report.checks["llm_config"].ok)
    llm_probe_ok = bool(report.checks["llm_probe"].ok)

    if report.status == "ready":
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

    log_event(
        "llm_worker_ready_failed",
        level="ERROR",
        request_id=request_id,
        status_code=503,
        llm_config_ok=llm_config_ok,
        llm_probe_ok=llm_probe_ok,
        llm_probe_cached=bool(report.checks["llm_probe"].meta.get("cached")),
        refresh=bool(refresh),
        error_code=report.checks["llm_probe"].error_code or report.checks["llm_config"].error_code,
    )
    return JSONResponse(status_code=503, content=report.model_dump(mode="json"))


@app.post("/v1/tasks/route-intent", response_model=WorkerTaskRouteIntentResponse)
async def route_intent_task(
    payload: WorkerTaskRouteIntentRequest,
    request: Request,
) -> WorkerTaskRouteIntentResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    try:
        result = await service.route_intent(payload)
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


@app.post("/v1/tasks/render-narration", response_model=WorkerTaskNarrationResponse)
async def render_narration_task(
    payload: WorkerTaskNarrationRequest,
    request: Request,
) -> WorkerTaskNarrationResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    try:
        result = await service.render_narration(payload)
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


@app.post("/v1/tasks/json-object", response_model=WorkerTaskJsonObjectResponse)
async def json_object_task(
    payload: WorkerTaskJsonObjectRequest,
    request: Request,
) -> WorkerTaskJsonObjectResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    try:
        result = await service.json_object(payload)
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
