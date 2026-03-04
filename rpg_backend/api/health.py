from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session as DBSession

from rpg_backend.api.schemas import ReadinessResponse
from rpg_backend.observability.context import get_request_id
from rpg_backend.observability.logging import log_event
from rpg_backend.observability.readiness import run_readiness_checks
from rpg_backend.storage.engine import engine
from rpg_backend.storage.repositories.observability import save_readiness_probe_event

router = APIRouter(tags=["health"])


def _save_backend_readiness_probe(
    *,
    ok: bool,
    error_code: str | None,
    latency_ms: int | None,
    request_id: str | None,
) -> None:
    try:
        with DBSession(engine) as db:
            save_readiness_probe_event(
                db,
                service="backend",
                ok=ok,
                error_code=error_code,
                latency_ms=latency_ms,
                request_id=request_id,
            )
    except Exception:  # noqa: BLE001
        return


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=ReadinessResponse)
def ready(request: Request, refresh: bool = Query(default=False)) -> ReadinessResponse | JSONResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    report = ReadinessResponse.model_validate(run_readiness_checks(refresh=refresh))
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
        _save_backend_readiness_probe(
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
    _save_backend_readiness_probe(
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
