from __future__ import annotations

import copy
import json
import threading
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlmodel import Session as DBSession

from rpg_backend.config.settings import get_settings
from rpg_backend.llm.factory import resolve_openai_models
from rpg_backend.llm.json_gateway import JsonGateway, JsonGatewayError
from rpg_backend.llm.worker_client import WorkerClientError, get_worker_client
from rpg_backend.storage.engine import engine

_probe_cache_lock = threading.Lock()
_probe_cache_entry: dict[str, Any] | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _monotonic() -> float:
    return time.monotonic()


def _build_check_result(
    *,
    ok: bool,
    latency_ms: int | None,
    checked_at: datetime,
    error_code: str | None,
    message: str | None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "latency_ms": latency_ms,
        "checked_at": checked_at,
        "error_code": error_code,
        "message": message,
        "meta": meta or {},
    }


def _resolved_probe_config() -> tuple[dict[str, Any], list[str]]:
    settings = get_settings()
    gateway_mode = str(getattr(settings, "llm_gateway_mode", "local") or "local").strip().lower()
    base_url = (settings.llm_openai_base_url or "").strip()
    api_key = (settings.llm_openai_api_key or "").strip()
    worker_base_url = (getattr(settings, "llm_worker_base_url", None) or "").strip()
    route_model, narration_model = resolve_openai_models(
        settings.llm_openai_route_model,
        settings.llm_openai_narration_model,
        settings.llm_openai_model,
    )
    probe_model = (settings.llm_openai_generator_model or "").strip() or route_model or narration_model
    missing: list[str] = []
    if gateway_mode == "worker":
        if not worker_base_url:
            missing.append("APP_LLM_WORKER_BASE_URL")
    else:
        if not base_url:
            missing.append("APP_LLM_OPENAI_BASE_URL")
        if not api_key:
            missing.append("APP_LLM_OPENAI_API_KEY")
        if not probe_model:
            missing.append(
                "one of APP_LLM_OPENAI_GENERATOR_MODEL / APP_LLM_OPENAI_ROUTE_MODEL / APP_LLM_OPENAI_NARRATION_MODEL / APP_LLM_OPENAI_MODEL"
            )
    return (
        {
            "gateway_mode": gateway_mode,
            "base_url": base_url,
            "api_key": api_key,
            "worker_base_url": worker_base_url,
            "probe_model": probe_model,
            "route_model": route_model,
            "narration_model": narration_model,
        },
        missing,
    )


def check_db() -> dict[str, Any]:
    started_at = _monotonic()
    checked_at = _utc_now()
    try:
        with DBSession(engine) as db:
            db.exec(text("SELECT 1")).one()
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
    gateway_mode = str(config.get("gateway_mode") or "local")
    meta = {
        "gateway_mode": gateway_mode,
        "probe_model": config.get("probe_model"),
        "route_model": config.get("route_model"),
        "narration_model": config.get("narration_model"),
        "base_url_host": urlparse(str(config.get("base_url") or "")).hostname,
        "worker_host": urlparse(str(config.get("worker_base_url") or "")).hostname,
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


def _perform_llm_probe_request(
    *,
    base_url: str,
    api_key: str,
    probe_model: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    gateway = JsonGateway(
        gateway_mode="local",
        base_url=base_url,
        api_key=api_key,
        default_timeout_seconds=float(timeout_seconds),
        connect_timeout_seconds=5.0,
        max_connections=100,
        max_keepalive_connections=20,
        http2_enabled=False,
        worker_client=None,
    )
    result = gateway.call_json_object(
        system_prompt="Readiness probe. Return JSON only with keys ok, who.",
        user_prompt="who are you",
        model=probe_model,
        temperature=0.0,
        max_retries=1,
        timeout_seconds=timeout_seconds,
    )
    return result.payload


def _validate_probe_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    ok_value = payload.get("ok")
    who_value = payload.get("who")
    if ok_value is not True:
        raise ValueError("probe response ok is not true")
    if not isinstance(who_value, str) or not who_value.strip():
        raise ValueError("probe response who is blank")
    return True, who_value.strip()


def reset_llm_probe_cache() -> None:
    global _probe_cache_entry
    with _probe_cache_lock:
        _probe_cache_entry = None


def check_llm_probe(*, refresh: bool = False) -> dict[str, Any]:
    global _probe_cache_entry

    settings = get_settings()
    checked_at = _utc_now()
    if not settings.ready_llm_probe_enabled:
        return _build_check_result(
            ok=True,
            latency_ms=None,
            checked_at=checked_at,
            error_code=None,
            message=None,
            meta={"cached": False, "skipped": True, "reason": "probe_disabled"},
        )

    config, missing = _resolved_probe_config()
    gateway_mode = str(config.get("gateway_mode") or "local")
    base_url = str(config.get("base_url") or "")
    api_key = str(config.get("api_key") or "")
    probe_model = str(config.get("probe_model") or "")
    worker_base_url = str(config.get("worker_base_url") or "")
    cache_key = f"{gateway_mode}|{worker_base_url or base_url}|{probe_model}"
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
                "gateway_mode": gateway_mode,
                "probe_model": probe_model or None,
                "base_url_host": urlparse(base_url).hostname,
                "worker_host": urlparse(worker_base_url).hostname,
            },
        )

    now_monotonic = _monotonic()
    if not refresh:
        with _probe_cache_lock:
            cache_entry = _probe_cache_entry
            if (
                cache_entry is not None
                and cache_entry.get("cache_key") == cache_key
                and float(cache_entry.get("expires_at_monotonic", 0.0)) > now_monotonic
            ):
                cached_result = copy.deepcopy(cache_entry["result"])
                meta = dict(cached_result.get("meta") or {})
                meta["cached"] = True
                cached_result["meta"] = meta
                return cached_result

    started_at = _monotonic()
    timeout_seconds = settings.ready_llm_probe_timeout_seconds
    host = urlparse(base_url).hostname
    worker_host = urlparse(worker_base_url).hostname
    try:
        if gateway_mode == "worker":
            worker_client = get_worker_client()
            status_code, worker_payload = worker_client.probe_ready(refresh=refresh)
            if status_code >= 400:
                error_message = str(
                    worker_payload.get("checks", {})
                    .get("llm_probe", {})
                    .get("error_code")
                    or worker_payload.get("status")
                    or f"worker status={status_code}"
                )
                result = _build_check_result(
                    ok=False,
                    latency_ms=int((_monotonic() - started_at) * 1000),
                    checked_at=_utc_now(),
                    error_code="llm_probe_worker_not_ready",
                    message=error_message,
                    meta={
                        "cached": False,
                        "gateway_mode": gateway_mode,
                        "probe_model": probe_model,
                        "worker_host": worker_host,
                        "worker_status_code": status_code,
                    },
                )
            else:
                worker_status = str(worker_payload.get("status") or "")
                if worker_status != "ready":
                    raise ValueError(f"worker /ready returned unexpected status: {worker_status}")
                llm_probe = (worker_payload.get("checks") or {}).get("llm_probe") or {}
                result = _build_check_result(
                    ok=True,
                    latency_ms=int((_monotonic() - started_at) * 1000),
                    checked_at=_utc_now(),
                    error_code=None,
                    message=None,
                    meta={
                        "cached": False,
                        "gateway_mode": gateway_mode,
                        "probe_model": probe_model,
                        "worker_host": worker_host,
                        "worker_probe_cached": bool((llm_probe.get("meta") or {}).get("cached", False)),
                    },
                )
        else:
            raw_payload = _perform_llm_probe_request(
                base_url=base_url,
                api_key=api_key,
                probe_model=probe_model,
                timeout_seconds=timeout_seconds,
            )
            _, who = _validate_probe_payload(raw_payload)
            result = _build_check_result(
                ok=True,
                latency_ms=int((_monotonic() - started_at) * 1000),
                checked_at=_utc_now(),
                error_code=None,
                message=None,
                meta={
                    "cached": False,
                    "gateway_mode": gateway_mode,
                    "probe_model": probe_model,
                    "base_url_host": host,
                    "who_preview": who[:120],
                },
            )
    except WorkerClientError as exc:
        result = _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=_utc_now(),
            error_code="llm_probe_worker_unreachable",
            message=f"{exc.error_code}: {exc.message}",
            meta={
                "cached": False,
                "gateway_mode": gateway_mode,
                "probe_model": probe_model,
                "worker_host": worker_host,
            },
        )
    except JsonGatewayError as exc:
        result = _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=_utc_now(),
            error_code="llm_probe_http_error",
            message=f"{exc.error_code}: {exc.message}",
            meta={"cached": False, "gateway_mode": gateway_mode, "probe_model": probe_model, "base_url_host": host},
        )
    except httpx.TimeoutException as exc:
        result = _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=_utc_now(),
            error_code="llm_probe_timeout",
            message=str(exc),
            meta={"cached": False, "gateway_mode": gateway_mode, "probe_model": probe_model, "base_url_host": host},
        )
    except httpx.HTTPStatusError as exc:
        result = _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=_utc_now(),
            error_code="llm_probe_http_error",
            message=f"status={exc.response.status_code}",
            meta={"cached": False, "gateway_mode": gateway_mode, "probe_model": probe_model, "base_url_host": host},
        )
    except (json.JSONDecodeError, ValueError) as exc:
        result = _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=_utc_now(),
            error_code="llm_probe_invalid_response",
            message=str(exc),
            meta={"cached": False, "gateway_mode": gateway_mode, "probe_model": probe_model, "base_url_host": host},
        )
    except httpx.HTTPError as exc:
        result = _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=_utc_now(),
            error_code="llm_probe_http_error",
            message=str(exc),
            meta={"cached": False, "gateway_mode": gateway_mode, "probe_model": probe_model, "base_url_host": host},
        )
    except Exception as exc:  # noqa: BLE001
        result = _build_check_result(
            ok=False,
            latency_ms=int((_monotonic() - started_at) * 1000),
            checked_at=_utc_now(),
            error_code="llm_probe_failed",
            message=str(exc),
            meta={"cached": False, "gateway_mode": gateway_mode, "probe_model": probe_model, "base_url_host": host},
        )

    with _probe_cache_lock:
        _probe_cache_entry = {
            "cache_key": cache_key,
            "expires_at_monotonic": _monotonic() + ttl_seconds,
            "result": copy.deepcopy(result),
        }
    return result


def run_readiness_checks(*, refresh: bool = False) -> dict[str, Any]:
    checked_at = _utc_now()
    db_check = check_db()
    llm_config_check = check_llm_config()
    if llm_config_check["ok"]:
        llm_probe_check = check_llm_probe(refresh=refresh)
    else:
        llm_probe_check = _build_check_result(
            ok=False,
            latency_ms=None,
            checked_at=_utc_now(),
            error_code="llm_probe_misconfigured",
            message="llm probe skipped because llm_config is invalid",
            meta={"cached": False, "skipped": True},
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
