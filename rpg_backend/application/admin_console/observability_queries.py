from __future__ import annotations

import asyncio
from typing import Any

from rpg_backend.infrastructure.repositories.observability_async import (
    aggregate_http_health,
    aggregate_llm_call_health,
    aggregate_readiness_health,
    aggregate_runtime_error_buckets,
)


async def query_runtime_errors(
    db,
    *,
    window_seconds: int,
    limit: int,
    stage: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return await aggregate_runtime_error_buckets(
        db,
        window_seconds=window_seconds,
        limit=limit,
        stage=stage,
        error_code=error_code,
    )


async def query_http_health(
    db,
    *,
    window_seconds: int,
    service: str,
    path_prefix: str | None = None,
    exclude_paths: list[str] | None = None,
) -> dict[str, Any]:
    return await aggregate_http_health(
        db,
        window_seconds=window_seconds,
        service=service,
        path_prefix=path_prefix,
        exclude_paths=exclude_paths,
    )


async def query_llm_health(
    db,
    *,
    window_seconds: int,
    stage: str | None = None,
    gateway_mode: str | None = None,
) -> dict[str, Any]:
    return await aggregate_llm_call_health(
        db,
        window_seconds=window_seconds,
        stage=stage,
        gateway_mode=gateway_mode,
    )


async def query_readiness_health(db, *, window_seconds: int) -> dict[str, Any]:
    return await aggregate_readiness_health(db, window_seconds=window_seconds)


async def build_observability_snapshot(
    db,
    *,
    window_seconds: int,
    limit: int,
) -> dict[str, Any]:
    runtime_errors, http_health, llm_health, readiness_health = await asyncio.gather(
        query_runtime_errors(db, window_seconds=window_seconds, limit=limit),
        query_http_health(
            db,
            window_seconds=window_seconds,
            service="backend",
            exclude_paths=["/health"],
        ),
        query_llm_health(db, window_seconds=window_seconds),
        query_readiness_health(db, window_seconds=window_seconds),
    )
    return {
        "runtime_errors": runtime_errors,
        "http_health": http_health,
        "llm_health": llm_health,
        "readiness_health": readiness_health,
    }
