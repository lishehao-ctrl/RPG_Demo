from __future__ import annotations

import json
import time
from typing import Any, Callable

from sqlmodel import Session

from rpg_backend.api.errors import ApiError
from rpg_backend.api.schemas import SessionStepRequest, SessionStepResponse
from rpg_backend.config.settings import get_settings
from rpg_backend.domain.constants import GLOBAL_HELP_ME_PROGRESS_MOVE_ID
from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import get_llm_provider
from rpg_backend.observability.logging import build_input_log_fields
from rpg_backend.runtime.errors import RuntimeNarrationError, RuntimeRouteError
from rpg_backend.runtime.service import RuntimeService
from rpg_backend.runtime.session_step.conflict import (
    build_session_conflict_detail,
    session_conflict_code,
)
from rpg_backend.runtime.session_step.contracts import (
    RuntimeExecutionContext,
    RuntimeExecutionSuccess,
    StepRequestContext,
)
from rpg_backend.runtime.session_step.event_logger import (
    emit_step_conflicted_event,
    emit_step_failed_event,
    emit_step_replayed_event,
    emit_step_started_event,
    emit_step_succeeded_event,
)
from rpg_backend.runtime.session_step.llm_telemetry import (
    llm_runtime_failure_detail,
    provider_name,
    record_llm_failure_event,
    record_llm_success_events,
)
from rpg_backend.storage.repositories.sessions import (
    StepCommitResult,
    commit_step_transition_if_turn_matches,
    get_session as get_session_record,
    get_session_action,
)
from rpg_backend.storage.repositories.stories import get_story_version


def _normalize_step_input(raw_input) -> dict[str, str]:
    if raw_input is None:
        return {"type": "text", "text": ""}

    raw_type = (raw_input.type or "").strip().lower()
    move_id = (raw_input.move_id or "").strip() if raw_input.move_id is not None else ""
    text = raw_input.text or ""

    if raw_type == "button":
        if move_id:
            return {"type": "button", "move_id": move_id}
        return {"type": "button", "move_id": GLOBAL_HELP_ME_PROGRESS_MOVE_ID}

    if raw_type == "text":
        return {"type": "text", "text": text}

    return {"type": "text", "text": text}


def _build_runtime_or_503(provider_factory: Callable[[], Any]) -> RuntimeService:
    try:
        provider = provider_factory()
    except LLMProviderConfigError as exc:
        raise ApiError(
            status_code=503,
            code="service_unavailable",
            message=f"llm provider misconfigured: {exc}",
            retryable=False,
        ) from exc
    return RuntimeService(provider)


def _build_execution_context(provider_factory: Callable[[], Any]) -> RuntimeExecutionContext:
    runtime = _build_runtime_or_503(provider_factory)
    return RuntimeExecutionContext(
        runtime=runtime,
        provider_name=provider_name(),
        route_model=getattr(runtime.provider, "route_model", None),
        narration_model=getattr(runtime.provider, "narration_model", None),
    )


def load_and_validate_session(
    *,
    db: Session,
    session_id: str,
    payload: SessionStepRequest,
    request_id: str,
) -> StepRequestContext:
    settings = get_settings()
    session = get_session_record(db, session_id)
    if session is None:
        raise ApiError(status_code=404, code="not_found", message="session not found", retryable=False)
    if session.ended:
        raise ApiError(status_code=409, code="session_inactive", message="inactive session", retryable=False)

    normalized_input = _normalize_step_input(payload.input)
    turn_index_expected = session.turn_count + 1
    scene_id_before = session.current_scene_id
    beat_index_before = session.beat_index
    input_log_fields = build_input_log_fields(normalized_input, redact_text=settings.obs_redact_input_text)

    return StepRequestContext(
        db=db,
        request_id=request_id,
        session=session,
        payload=payload,
        normalized_input=normalized_input,
        turn_index_expected=turn_index_expected,
        scene_id_before=scene_id_before,
        beat_index_before=beat_index_before,
        input_log_fields=input_log_fields,
    )


def idempotency_precheck(ctx: StepRequestContext) -> SessionStepResponse | None:
    existing = get_session_action(ctx.db, ctx.session.id, ctx.payload.client_action_id)
    if existing is None:
        return None

    emit_step_replayed_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index=ctx.session.turn_count,
        client_action_id=ctx.payload.client_action_id,
        session_action_id=existing.id,
        request_id=ctx.request_id,
        note="idempotency_replay",
    )
    return SessionStepResponse.model_validate(existing.response_json)


def execute_runtime_step(
    ctx: StepRequestContext,
    *,
    execution_context: RuntimeExecutionContext,
) -> tuple[RuntimeExecutionSuccess, dict[str, Any], dict[str, Any]]:
    story_version = get_story_version(ctx.db, ctx.session.story_id, ctx.session.version)
    if story_version is None:
        raise ApiError(status_code=404, code="not_found", message="story version not found", retryable=False)

    pack = StoryPack.model_validate(story_version.pack_json)
    emit_step_started_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index_expected=ctx.turn_index_expected,
        client_action_id=ctx.payload.client_action_id,
        normalized_input=ctx.normalized_input,
        scene_id_before=ctx.scene_id_before,
        beat_index_before=ctx.beat_index_before,
        provider_name=execution_context.provider_name,
        request_id=ctx.request_id,
        route_model=execution_context.route_model,
        narration_model=execution_context.narration_model,
        input_log_fields=ctx.input_log_fields,
    )

    working_state = json.loads(json.dumps(ctx.session.state_json))
    working_beat_progress = json.loads(json.dumps(ctx.session.beat_progress_json))
    started_at = time.perf_counter()

    result = execution_context.runtime.process_step(
        pack,
        current_scene_id=ctx.session.current_scene_id,
        beat_index=ctx.session.beat_index,
        state=working_state,
        beat_progress=working_beat_progress,
        action_input=ctx.normalized_input,
        dev_mode=ctx.payload.dev_mode,
    )
    duration_ms = int((time.perf_counter() - started_at) * 1000)

    execution_success = RuntimeExecutionSuccess(result=result, duration_ms=duration_ms)
    return execution_success, working_state, working_beat_progress


def record_llm_call_events(
    ctx: StepRequestContext,
    *,
    execution_context: RuntimeExecutionContext,
    execution_success: RuntimeExecutionSuccess | None = None,
    runtime_exc: RuntimeRouteError | RuntimeNarrationError | None = None,
    fallback_duration_ms: int | None = None,
) -> tuple[int | None, int | None, str, str]:
    provider = execution_context.runtime.provider
    provider_gateway_mode = str(getattr(provider, "gateway_mode", "local") or "local")

    if runtime_exc is not None:
        llm_duration_ms, llm_gateway_mode, _stage_model = record_llm_failure_event(
            db=ctx.db,
            session_id=ctx.session.id,
            turn_index_expected=ctx.turn_index_expected,
            request_id=ctx.request_id,
            exc=runtime_exc,
            route_model=execution_context.route_model,
            narration_model=execution_context.narration_model,
            fallback_duration_ms=int(fallback_duration_ms or 0),
            provider_gateway_mode=provider_gateway_mode,
        )
        return None, llm_duration_ms, llm_gateway_mode, llm_gateway_mode

    if execution_success is None:
        return None, None, provider_gateway_mode, provider_gateway_mode

    runtime_metrics = execution_success.result.get("runtime_metrics") or {}
    return record_llm_success_events(
        db=ctx.db,
        session_id=ctx.session.id,
        turn_index_expected=ctx.turn_index_expected,
        request_id=ctx.request_id,
        route_model=execution_context.route_model,
        narration_model=execution_context.narration_model,
        runtime_metrics=runtime_metrics,
        provider_gateway_mode=provider_gateway_mode,
    )


def cas_commit_transition(
    ctx: StepRequestContext,
    *,
    execution_success: RuntimeExecutionSuccess,
    working_state: dict[str, Any],
    working_beat_progress: dict[str, Any],
    response_payload: dict[str, Any],
) -> StepCommitResult:
    result = execution_success.result
    return commit_step_transition_if_turn_matches(
        ctx.db,
        session_id=ctx.session.id,
        expected_turn_count=ctx.turn_index_expected - 1,
        new_scene_id=result["scene_id"],
        new_beat_index=result["beat_index"],
        new_state_json=working_state,
        new_beat_progress_json=working_beat_progress,
        new_ended=bool(result["ended"]),
        client_action_id=ctx.payload.client_action_id,
        request_json=ctx.payload.model_dump(),
        response_json=response_payload,
    )


def resolve_conflict_or_replay(
    ctx: StepRequestContext,
    *,
    commit_result: StepCommitResult,
) -> SessionStepResponse:
    replayed = get_session_action(ctx.db, ctx.session.id, ctx.payload.client_action_id)
    if replayed is not None:
        replay_turn_index = max(commit_result.actual_turn_count, ctx.session.turn_count)
        emit_step_replayed_event(
            db=ctx.db,
            session_id=ctx.session.id,
            story_id=ctx.session.story_id,
            turn_index=replay_turn_index,
            client_action_id=ctx.payload.client_action_id,
            session_action_id=replayed.id,
            request_id=ctx.request_id,
            note="idempotency_replay_after_conflict",
        )
        return SessionStepResponse.model_validate(replayed.response_json)

    actual_turn_index = commit_result.actual_turn_count + 1
    emit_step_conflicted_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index_expected=ctx.turn_index_expected,
        actual_turn_index=actual_turn_index,
        client_action_id=ctx.payload.client_action_id,
        scene_id_before=ctx.scene_id_before,
        beat_index_before=ctx.beat_index_before,
        request_id=ctx.request_id,
        input_log_fields=ctx.input_log_fields,
        error_code=session_conflict_code(),
    )
    raise ApiError(
        status_code=409,
        code=session_conflict_code(),
        message="session advanced by another action; retry with new client_action_id",
        retryable=True,
        details=build_session_conflict_detail(
            session_id=ctx.session.id,
            expected_turn_index=ctx.turn_index_expected,
            actual_turn_index=actual_turn_index,
        ),
    )


def emit_success_or_failure_events(
    ctx: StepRequestContext,
    *,
    execution_context: RuntimeExecutionContext,
    execution_success: RuntimeExecutionSuccess | None = None,
    runtime_exc: RuntimeRouteError | RuntimeNarrationError | None = None,
    failure_duration_ms: int | None = None,
    llm_duration_ms: int | None = None,
    llm_gateway_mode: str | None = None,
    route_llm_duration_ms: int | None = None,
    narration_llm_duration_ms: int | None = None,
    route_llm_gateway_mode: str | None = None,
    narration_llm_gateway_mode: str | None = None,
    turn_index_applied: int | None = None,
) -> None:
    if runtime_exc is not None:
        emit_step_failed_event(
            db=ctx.db,
            session_id=ctx.session.id,
            story_id=ctx.session.story_id,
            turn_index_expected=ctx.turn_index_expected,
            client_action_id=ctx.payload.client_action_id,
            scene_id_before=ctx.scene_id_before,
            beat_index_before=ctx.beat_index_before,
            request_id=ctx.request_id,
            route_model=execution_context.route_model,
            narration_model=execution_context.narration_model,
            duration_ms=int(failure_duration_ms or 0),
            llm_duration_ms=int(llm_duration_ms or failure_duration_ms or 0),
            llm_gateway_mode=str(llm_gateway_mode or "local"),
            exc=runtime_exc,
            input_log_fields=ctx.input_log_fields,
        )
        return

    if execution_success is None or turn_index_applied is None:
        return

    emit_step_succeeded_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index_applied=turn_index_applied,
        client_action_id=ctx.payload.client_action_id,
        scene_id_before=ctx.scene_id_before,
        beat_index_before=ctx.beat_index_before,
        request_id=ctx.request_id,
        route_model=execution_context.route_model,
        narration_model=execution_context.narration_model,
        duration_ms=execution_success.duration_ms,
        route_llm_duration_ms=route_llm_duration_ms,
        narration_llm_duration_ms=narration_llm_duration_ms,
        route_llm_gateway_mode=str(route_llm_gateway_mode or "local"),
        narration_llm_gateway_mode=str(narration_llm_gateway_mode or "local"),
        result=execution_success.result,
        provider_name=execution_context.provider_name,
        input_log_fields=ctx.input_log_fields,
    )


def process_step_request(
    *,
    db: Session,
    session_id: str,
    payload: SessionStepRequest,
    request_id: str,
    provider_factory: Callable[[], Any] = get_llm_provider,
) -> SessionStepResponse:
    ctx = load_and_validate_session(
        db=db,
        session_id=session_id,
        payload=payload,
        request_id=request_id,
    )

    replay_response = idempotency_precheck(ctx)
    if replay_response is not None:
        return replay_response

    execution_context = _build_execution_context(provider_factory)
    started_at = time.perf_counter()
    try:
        execution_success, working_state, working_beat_progress = execute_runtime_step(
            ctx,
            execution_context=execution_context,
        )
    except (RuntimeRouteError, RuntimeNarrationError) as exc:
        failure_duration_ms = int((time.perf_counter() - started_at) * 1000)
        _route_ms, llm_duration_ms, llm_gateway_mode, _narration_gateway_mode = record_llm_call_events(
            ctx,
            execution_context=execution_context,
            runtime_exc=exc,
            fallback_duration_ms=failure_duration_ms,
        )
        emit_success_or_failure_events(
            ctx,
            execution_context=execution_context,
            runtime_exc=exc,
            failure_duration_ms=failure_duration_ms,
            llm_duration_ms=llm_duration_ms,
            llm_gateway_mode=llm_gateway_mode,
        )
        detail = llm_runtime_failure_detail(exc)
        raise ApiError(
            status_code=503,
            code=str(detail.get("error_code") or "service_unavailable"),
            message=str(detail.get("message") or "runtime step failed"),
            retryable=bool(detail.get("retryable", True)),
            details={
                key: value
                for key, value in detail.items()
                if key not in {"error_code", "message", "retryable"}
            },
        ) from exc

    route_llm_duration_ms, narration_llm_duration_ms, route_gateway_mode, narration_gateway_mode = record_llm_call_events(
        ctx,
        execution_context=execution_context,
        execution_success=execution_success,
    )

    result = execution_success.result
    response_payload = {
        "session_id": ctx.session.id,
        "version": ctx.session.version,
        "scene_id": result["scene_id"],
        "narration_text": result["narration_text"],
        "recognized": result["recognized"],
        "resolution": result["resolution"],
        "ui": result["ui"],
    }
    if ctx.payload.dev_mode and isinstance(result.get("debug"), dict):
        response_payload["debug"] = result["debug"]

    commit_result = cas_commit_transition(
        ctx,
        execution_success=execution_success,
        working_state=working_state,
        working_beat_progress=working_beat_progress,
        response_payload=response_payload,
    )

    if not commit_result.applied:
        return resolve_conflict_or_replay(ctx, commit_result=commit_result)

    turn_index_applied = commit_result.actual_turn_count
    emit_success_or_failure_events(
        ctx,
        execution_context=execution_context,
        execution_success=execution_success,
        route_llm_duration_ms=route_llm_duration_ms,
        narration_llm_duration_ms=narration_llm_duration_ms,
        route_llm_gateway_mode=route_gateway_mode,
        narration_llm_gateway_mode=narration_gateway_mode,
        turn_index_applied=turn_index_applied,
    )

    return SessionStepResponse.model_validate(response_payload)
