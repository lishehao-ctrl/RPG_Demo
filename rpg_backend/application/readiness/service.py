from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.observability_async import save_readiness_probe_event
from rpg_backend.observability.readiness import run_readiness_checks_async


async def persist_readiness_probe(
    *,
    service: str,
    ok: bool,
    error_code: str | None,
    latency_ms: int | None,
    request_id: str | None,
) -> None:
    try:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            async with transactional(db):
                await save_readiness_probe_event(
                    db,
                    service=service,
                    ok=ok,
                    error_code=error_code,
                    latency_ms=latency_ms,
                    request_id=request_id,
                )
    except Exception:  # noqa: BLE001
        return


async def run_backend_readiness(*, refresh: bool) -> dict[str, Any]:
    return await run_readiness_checks_async(refresh=refresh)
