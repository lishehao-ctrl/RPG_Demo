from __future__ import annotations

from typing import Any

from sqlmodel import Session

from rpg_backend.runtime.errors import RuntimeNarrationError, RuntimeRouteError
from rpg_backend.storage.repositories.observability import save_llm_call_event


def provider_name() -> str:
    return "openai"


def model_for_stage(*, stage: str, route_model: str | None, narration_model: str | None) -> str:
    if stage == "route":
        return str(route_model or narration_model or "unknown")
    if stage == "narration":
        return str(narration_model or route_model or "unknown")
    return str(route_model or narration_model or "unknown")


def llm_runtime_failure_detail(exc: RuntimeRouteError | RuntimeNarrationError) -> dict[str, Any]:
    detail = {
        "error_code": exc.error_code,
        "stage": exc.stage,
        "message": exc.message,
        "provider": exc.provider,
        "retryable": True,
    }
    if exc.provider_error_code:
        detail["provider_error_code"] = exc.provider_error_code
    if exc.llm_duration_ms is not None:
        detail["llm_duration_ms"] = int(exc.llm_duration_ms)
    if exc.gateway_mode:
        detail["llm_gateway_mode"] = exc.gateway_mode
    return detail


def record_llm_failure_event(
    *,
    db: Session,
    session_id: str,
    turn_index_expected: int,
    request_id: str,
    exc: RuntimeRouteError | RuntimeNarrationError,
    route_model: str | None,
    narration_model: str | None,
    fallback_duration_ms: int,
    provider_gateway_mode: str,
) -> tuple[int, str, str]:
    failed_stage_model = model_for_stage(
        stage=exc.stage,
        route_model=route_model,
        narration_model=narration_model,
    )
    gateway_mode = str(exc.gateway_mode or provider_gateway_mode or "local")
    llm_duration_ms = int(exc.llm_duration_ms) if exc.llm_duration_ms is not None else fallback_duration_ms

    save_llm_call_event(
        db,
        session_id=session_id,
        turn_index=turn_index_expected,
        stage=exc.stage,
        gateway_mode=gateway_mode,
        model=failed_stage_model,
        success=False,
        error_code=exc.provider_error_code or exc.error_code,
        duration_ms=llm_duration_ms,
        request_id=request_id,
    )
    return llm_duration_ms, gateway_mode, failed_stage_model


def record_llm_success_events(
    *,
    db: Session,
    session_id: str,
    turn_index_expected: int,
    request_id: str,
    route_model: str | None,
    narration_model: str | None,
    runtime_metrics: dict[str, Any],
    provider_gateway_mode: str,
) -> tuple[int | None, int | None, str, str]:
    route_llm_duration_ms = runtime_metrics.get("route_llm_duration_ms")
    narration_llm_duration_ms = runtime_metrics.get("narration_llm_duration_ms")
    route_llm_gateway_mode = str(runtime_metrics.get("route_llm_gateway_mode") or provider_gateway_mode or "local")
    narration_llm_gateway_mode = str(
        runtime_metrics.get("narration_llm_gateway_mode") or provider_gateway_mode or "local"
    )

    if isinstance(route_llm_duration_ms, int):
        save_llm_call_event(
            db,
            session_id=session_id,
            turn_index=turn_index_expected,
            stage="route",
            gateway_mode=route_llm_gateway_mode,
            model=model_for_stage(stage="route", route_model=route_model, narration_model=narration_model),
            success=True,
            error_code=None,
            duration_ms=route_llm_duration_ms,
            request_id=request_id,
        )
    if isinstance(narration_llm_duration_ms, int):
        save_llm_call_event(
            db,
            session_id=session_id,
            turn_index=turn_index_expected,
            stage="narration",
            gateway_mode=narration_llm_gateway_mode,
            model=model_for_stage(stage="narration", route_model=route_model, narration_model=narration_model),
            success=True,
            error_code=None,
            duration_ms=narration_llm_duration_ms,
            request_id=request_id,
        )

    return route_llm_duration_ms, narration_llm_duration_ms, route_llm_gateway_mode, narration_llm_gateway_mode
