from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from rpg_backend.api.contracts.observability import ReadinessResponse
from rpg_backend.api.route_paths import HEALTH_PATH, READY_PATH
from rpg_backend.application.readiness.service import persist_readiness_probe, run_backend_readiness
from rpg_backend.observability.context import get_request_id
from rpg_backend.observability.logging import log_event

router = APIRouter(tags=["health"])


@router.get(HEALTH_PATH)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(READY_PATH, response_model=ReadinessResponse)
async def ready(request: Request, refresh: bool = Query(default=False)) -> ReadinessResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    report = ReadinessResponse.model_validate(await run_backend_readiness(refresh=refresh))
    db_ok = bool(report.checks.db.ok)
    llm_config_ok = bool(report.checks.llm_config.ok)
    llm_probe_ok = bool(report.checks.llm_probe.ok)
    llm_probe_cached = bool(report.checks.llm_probe.meta.get("cached"))
    latency_candidates = [
        report.checks.db.latency_ms,
        report.checks.llm_config.latency_ms,
        report.checks.llm_probe.latency_ms,
    ]
    latency_ms = max(int(item) for item in latency_candidates if isinstance(item, int)) if any(
        isinstance(item, int) for item in latency_candidates
    ) else None
    if report.status == "ready":
        await persist_readiness_probe(
            service="backend",
            ok=True,
            error_code=None,
            latency_ms=latency_ms,
            request_id=request_id,
        )
        log_event(
            "readiness_check_succeeded",
            level="INFO",
            request_id=request_id,
            status_code=200,
            db_ok=db_ok,
            llm_config_ok=llm_config_ok,
            llm_probe_ok=llm_probe_ok,
            llm_probe_cached=llm_probe_cached,
            refresh=bool(refresh),
        )
        return report

    first_error_code = (
        report.checks.db.error_code
        or report.checks.llm_config.error_code
        or report.checks.llm_probe.error_code
        or "readiness_failed"
    )
    await persist_readiness_probe(
        service="backend",
        ok=False,
        error_code=first_error_code,
        latency_ms=latency_ms,
        request_id=request_id,
    )
    log_event(
        "readiness_check_failed",
        level="ERROR",
        request_id=request_id,
        status_code=503,
        db_ok=db_ok,
        llm_config_ok=llm_config_ok,
        llm_probe_ok=llm_probe_ok,
        llm_probe_cached=llm_probe_cached,
        refresh=bool(refresh),
        error_code=first_error_code,
    )
    return JSONResponse(status_code=503, content=report.model_dump(mode="json"))
