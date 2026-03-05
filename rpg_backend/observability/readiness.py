from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.config.settings import get_settings
from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.llm.factory import resolve_openai_models
from rpg_backend.llm.worker_client import WorkerClientError, get_worker_client
from rpg_backend.observability.readiness_core import (
    AsyncTTLProbeCache,
    build_check_payload,
    monotonic as _core_monotonic,
    utc_now as _core_utc_now,
    validate_required_config,
)

_probe_cache: AsyncTTLProbeCache[dict[str, Any]] = AsyncTTLProbeCache()


def _utc_now() -> datetime:
    return _core_utc_now()


def _monotonic() -> float:
    return _core_monotonic()


def _build_check_result(
    *,
    ok: bool,
    latency_ms: int | None,
    checked_at: datetime,
    error_code: str | None,
    message: str | None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_check_payload(
        ok=ok,
        latency_ms=latency_ms,
        checked_at=checked_at,
        error_code=error_code,
        message=message,
        meta=meta,
    )


def _resolved_probe_config() -> tuple[dict[str, Any], list[str]]:
    settings = get_settings()
    worker_base_url = (getattr(settings, "llm_worker_base_url", None) or "").strip()
    internal_worker_token = (getattr(settings, "internal_worker_token", None) or "").strip()
    route_model, narration_model = resolve_openai_models(
        settings.llm_openai_route_model,
        settings.llm_openai_narration_model,
        settings.llm_openai_model,
    )
    probe_model = (settings.llm_openai_generator_model or "").strip() or route_model or narration_model
    missing = validate_required_config(
        {
            "APP_LLM_WORKER_BASE_URL": worker_base_url,
            "APP_INTERNAL_WORKER_TOKEN": internal_worker_token,
        }
    )
    return (
        {
            "gateway_mode": "worker",
            "worker_base_url": worker_base_url,
            "probe_model": probe_model,
            "route_model": route_model,
            "narration_model": narration_model,
        },
        missing,
    )


async def check_db() -> dict[str, Any]:
    started_at = _monotonic()
    checked_at = _utc_now()
    try:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            await db.exec(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=checked_at,
            error_code="db_unavailable",
            message=str(exc),
        )
    return _build_check_result(
        ok=True,
        latency_ms=int((_monotonic() - started_at) * 1000),
        checked_at=checked_at,
        error_code=None,
        message=None,
    )


def check_llm_config() -> dict[str, Any]:
    checked_at = _utc_now()
    config, missing = _resolved_probe_config()
    worker_base_url = str(config.get("worker_base_url") or "")
    meta = {
        "gateway_mode": "worker",
        "probe_model": config.get("probe_model"),
        "route_model": config.get("route_model"),
        "narration_model": config.get("narration_model"),
        "worker_host": urlparse(worker_base_url).hostname,
    }
    if missing:
        return _build_check_result(
            ok=False,
            latency_ms=None,
            checked_at=checked_at,
            error_code="llm_config_invalid",
            message=f"missing config: {', '.join(missing)}",
            meta=meta,
        )
    return _build_check_result(
        ok=True,
        latency_ms=None,
        checked_at=checked_at,
        error_code=None,
        message=None,
        meta=meta,
    )


async def reset_llm_probe_cache() -> None:
    await _probe_cache.reset()


def _mark_cached_probe_result(payload: dict[str, Any]) -> dict[str, Any]:
    meta = dict(payload.get("meta") or {})
    meta["cached"] = True
    payload["meta"] = meta
    return payload


async def check_llm_probe(*, refresh: bool = False) -> dict[str, Any]:
    settings = get_settings()
    checked_at = _utc_now()
    if not settings.ready_llm_probe_enabled:
        return _build_check_result(
            ok=True,
            latency_ms=None,
            checked_at=checked_at,
            error_code=None,
            message=None,
            meta={"cached": False, "skipped": True, "reason": "probe_disabled", "gateway_mode": "worker"},
        )

    config, missing = _resolved_probe_config()
    probe_model = str(config.get("probe_model") or "")
    worker_base_url = str(config.get("worker_base_url") or "")
    worker_host = urlparse(worker_base_url).hostname
    cache_key = f"worker|{worker_base_url}|{probe_model}"
    ttl_seconds = settings.ready_llm_probe_cache_ttl_seconds

    if missing:
        return _build_check_result(
            ok=False,
            latency_ms=None,
            checked_at=checked_at,
            error_code="llm_probe_misconfigured",
            message=f"missing config: {', '.join(missing)}",
            meta={
                "cached": False,
                "gateway_mode": "worker",
                "probe_model": probe_model or None,
                "worker_host": worker_host,
            },
        )

    async def _compute_probe_result() -> dict[str, Any]:
        started_at = _monotonic()
        try:
            worker_client = get_worker_client()
            status_code, worker_payload = await worker_client.probe_ready(refresh=refresh)
            if status_code >= 400:
                error_message = str(
                    worker_payload.get("checks", {}).get("llm_probe", {}).get("error_code")
                    or worker_payload.get("status")
                    or f"worker status={status_code}"
                )
                return _build_check_result(
                    ok=False,
                    latency_ms=int((_monotonic() - started_at) * 1000),
                    checked_at=_utc_now(),
                    error_code="llm_probe_worker_not_ready",
                    message=error_message,
                    meta={
                        "cached": False,
                        "gateway_mode": "worker",
                        "probe_model": probe_model,
                        "worker_host": worker_host,
                        "worker_status_code": status_code,
                    },
                )

            worker_status = str(worker_payload.get("status") or "")
            if worker_status != "ready":
                raise ValueError(f"worker /ready returned unexpected status: {worker_status}")
            llm_probe = (worker_payload.get("checks") or {}).get("llm_probe") or {}
            return _build_check_result(
                ok=True,
                latency_ms=int((_monotonic() - started_at) * 1000),
                checked_at=_utc_now(),
                error_code=None,
                message=None,
                meta={
                    "cached": False,
                    "gateway_mode": "worker",
                    "probe_model": probe_model,
                    "worker_host": worker_host,
                    "worker_probe_cached": bool((llm_probe.get("meta") or {}).get("cached", False)),
                },
            )
        except WorkerClientError as exc:
            return _build_check_result(
                ok=False,
                latency_ms=int((_monotonic() - started_at) * 1000),
                checked_at=_utc_now(),
                error_code="llm_probe_worker_unreachable",
                message=f"{exc.error_code}: {exc.message}",
                meta={
                    "cached": False,
                    "gateway_mode": "worker",
                    "probe_model": probe_model,
                    "worker_host": worker_host,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return _build_check_result(
                ok=False,
                latency_ms=int((_monotonic() - started_at) * 1000),
                checked_at=_utc_now(),
                error_code="llm_probe_failed",
                message=str(exc),
                meta={
                    "cached": False,
                    "gateway_mode": "worker",
                    "probe_model": probe_model,
                    "worker_host": worker_host,
                },
            )

    return await _probe_cache.get_or_compute(
        refresh=refresh,
        cache_key=cache_key,
        ttl_seconds=float(ttl_seconds),
        compute=_compute_probe_result,
        mark_cached=_mark_cached_probe_result,
        now_provider=_monotonic,
    )


async def run_readiness_checks_async(*, refresh: bool = False) -> dict[str, Any]:
    checked_at = _utc_now()
    db_check = dict(await check_db())
    llm_config_check = check_llm_config()
    if llm_config_check["ok"]:
        llm_probe_check = dict(await check_llm_probe(refresh=refresh))
    else:
        llm_probe_check = _build_check_result(
            ok=False,
            latency_ms=None,
            checked_at=_utc_now(),
            error_code="llm_probe_misconfigured",
            message="llm probe skipped because llm_config is invalid",
            meta={"cached": False, "skipped": True, "gateway_mode": "worker"},
        )

    is_ready = bool(db_check["ok"] and llm_config_check["ok"] and llm_probe_check["ok"])
    return {
        "status": "ready" if is_ready else "not_ready",
        "checked_at": checked_at,
        "checks": {
            "db": db_check,
            "llm_config": llm_config_check,
            "llm_probe": llm_probe_check,
        },
    }
