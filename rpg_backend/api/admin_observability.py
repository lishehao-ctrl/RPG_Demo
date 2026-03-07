from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.api.contracts.observability import (
    HttpHealthAggregateResponse,
    LLMCallByGatewayModePayload,
    LLMCallByStagePayload,
    LLMCallGroupHealthPayload,
    LLMCallHealthAggregateResponse,
    RuntimeErrorBucketPayload,
    RuntimeErrorsAggregateResponse,
    ReadinessHealthAggregateResponse,
)
from rpg_backend.api.route_paths import API_ADMIN_OBSERVABILITY_PREFIX, HEALTH_PATH
from rpg_backend.application.admin_console.observability_queries import (
    query_http_health,
    query_llm_health,
    query_readiness_health,
    query_runtime_errors,
)
from rpg_backend.infrastructure.db.async_session import get_async_session
from rpg_backend.security.deps import require_admin

router = APIRouter(
    prefix=API_ADMIN_OBSERVABILITY_PREFIX,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _empty_llm_group() -> LLMCallGroupHealthPayload:
    return LLMCallGroupHealthPayload(total_calls=0, failed_calls=0, failure_rate=0.0, p95_ms=None)


def _stable_stage_groups(raw: dict[str, dict]) -> LLMCallByStagePayload:
    return LLMCallByStagePayload(
        route=LLMCallGroupHealthPayload.model_validate(raw.get("route") or _empty_llm_group().model_dump()),
        narration=LLMCallGroupHealthPayload.model_validate(raw.get("narration") or _empty_llm_group().model_dump()),
        json_stage=LLMCallGroupHealthPayload.model_validate(raw.get("json") or _empty_llm_group().model_dump()),
        unknown=LLMCallGroupHealthPayload.model_validate(raw.get("unknown") or _empty_llm_group().model_dump()),
    )


def _stable_gateway_groups(raw: dict[str, dict]) -> LLMCallByGatewayModePayload:
    return LLMCallByGatewayModePayload(
        worker=LLMCallGroupHealthPayload.model_validate(raw.get("worker") or _empty_llm_group().model_dump()),
        unknown=LLMCallGroupHealthPayload.model_validate(raw.get("unknown") or _empty_llm_group().model_dump()),
    )


@router.get("/runtime-errors", response_model=RuntimeErrorsAggregateResponse)
async def get_runtime_errors_aggregate_endpoint(
    window_seconds: int = Query(default=300, ge=60, le=3600),
    limit: int = Query(default=20, ge=1, le=100),
    stage: Literal["route", "narration"] | None = Query(default=None),
    error_code: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> RuntimeErrorsAggregateResponse:
    aggregated = await query_runtime_errors(
        db,
        window_seconds=window_seconds,
        limit=limit,
        stage=stage,
        error_code=error_code,
    )
    return RuntimeErrorsAggregateResponse(
        generated_at=aggregated.get("generated_at") or datetime.now(UTC),
        window_seconds=window_seconds,
        started_total=int(aggregated["started_total"]),
        failed_total=int(aggregated["failed_total"]),
        step_error_rate=float(aggregated["step_error_rate"]),
        buckets=[
            RuntimeErrorBucketPayload(
                error_code=bucket.error_code,
                stage=bucket.stage,
                model=bucket.model,
                failed_count=bucket.failed_count,
                error_share=bucket.error_share,
                last_seen_at=bucket.last_seen_at,
                sample_session_ids=list(bucket.sample_session_ids),
                sample_request_ids=list(bucket.sample_request_ids),
            )
            for bucket in aggregated["buckets"]
        ],
    )


@router.get("/http-health", response_model=HttpHealthAggregateResponse)
async def get_http_health_endpoint(
    window_seconds: int = Query(default=300, ge=60, le=3600),
    service: Literal["backend", "worker"] = Query(default="backend"),
    path_prefix: str | None = Query(default=None),
    exclude_paths: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> HttpHealthAggregateResponse:
    excluded = [item.strip() for item in (exclude_paths or "").split(",") if item.strip()]
    if service == "backend" and not excluded:
        excluded = [HEALTH_PATH]
    aggregated = await query_http_health(
        db,
        window_seconds=window_seconds,
        service=service,
        path_prefix=path_prefix,
        exclude_paths=excluded,
    )
    return HttpHealthAggregateResponse(
        generated_at=aggregated.get("generated_at") or datetime.now(UTC),
        window_started_at=aggregated.get("window_started_at") or datetime.now(UTC),
        window_ended_at=aggregated.get("window_ended_at") or datetime.now(UTC),
        window_seconds=window_seconds,
        service=service,
        total_requests=int(aggregated["total_requests"]),
        failed_5xx=int(aggregated["failed_5xx"]),
        error_rate=float(aggregated["error_rate"]),
        p95_ms=int(aggregated["p95_ms"]) if aggregated.get("p95_ms") is not None else None,
        top_5xx_paths=list(aggregated["top_5xx_paths"]),
    )


@router.get("/llm-call-health", response_model=LLMCallHealthAggregateResponse)
async def get_llm_call_health_endpoint(
    window_seconds: int = Query(default=300, ge=60, le=3600),
    stage: Literal["route", "narration", "json"] | None = Query(default=None),
    gateway_mode: Literal["worker", "unknown"] | None = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
) -> LLMCallHealthAggregateResponse:
    aggregated = await query_llm_health(
        db,
        window_seconds=window_seconds,
        stage=stage,
        gateway_mode=gateway_mode,
    )
    return LLMCallHealthAggregateResponse(
        generated_at=aggregated.get("generated_at") or datetime.now(UTC),
        window_started_at=aggregated.get("window_started_at") or datetime.now(UTC),
        window_ended_at=aggregated.get("window_ended_at") or datetime.now(UTC),
        window_seconds=window_seconds,
        total_calls=int(aggregated["total_calls"]),
        failed_calls=int(aggregated["failed_calls"]),
        failure_rate=float(aggregated["failure_rate"]),
        p95_ms=int(aggregated["p95_ms"]) if aggregated.get("p95_ms") is not None else None,
        by_stage=_stable_stage_groups(dict(aggregated["by_stage"])),
        by_gateway_mode=_stable_gateway_groups(dict(aggregated["by_gateway_mode"])),
    )


@router.get("/readiness-health", response_model=ReadinessHealthAggregateResponse)
async def get_readiness_health_endpoint(
    window_seconds: int = Query(default=300, ge=60, le=3600),
    db: AsyncSession = Depends(get_async_session),
) -> ReadinessHealthAggregateResponse:
    aggregated = await query_readiness_health(db, window_seconds=window_seconds)
    return ReadinessHealthAggregateResponse(
        generated_at=aggregated.get("generated_at") or datetime.now(UTC),
        window_started_at=aggregated.get("window_started_at") or datetime.now(UTC),
        window_ended_at=aggregated.get("window_ended_at") or datetime.now(UTC),
        window_seconds=window_seconds,
        backend_ready_fail_count=int(aggregated["backend_ready_fail_count"]),
        worker_ready_fail_count=int(aggregated["worker_ready_fail_count"]),
        backend_fail_streak=int(aggregated["backend_fail_streak"]),
        worker_fail_streak=int(aggregated["worker_fail_streak"]),
        last_failures=list(aggregated["last_failures"]),
    )
