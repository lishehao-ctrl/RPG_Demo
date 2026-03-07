from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.api.contracts.sessions import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionGetResponse,
    SessionHistoryResponse,
    SessionHistoryTurn,
    SessionRecognizedPayload,
    SessionResolutionPayload,
    SessionStepRequest,
    SessionStepResponse,
    SessionUiPayload,
)
from rpg_backend.api.error_mapping import api_error_from_application_error
from rpg_backend.api.route_paths import API_SESSIONS_PREFIX
from rpg_backend.application.errors import ApplicationError
from rpg_backend.application.play_sessions.models import SessionStepCommand
from rpg_backend.application.play_sessions.service import (
    create_play_session,
    get_play_session,
    get_play_session_history,
)
from rpg_backend.application.session_step.use_case import process_step_command
from rpg_backend.infrastructure.db.async_session import get_async_session
from rpg_backend.llm.factory import get_llm_provider
from rpg_backend.observability.context import get_request_id
from rpg_backend.security.deps import require_current_user

router = APIRouter(
    prefix=API_SESSIONS_PREFIX,
    tags=["sessions"],
    dependencies=[Depends(require_current_user)],
)


def _step_command_from_request(payload: SessionStepRequest) -> SessionStepCommand:
    input_payload = payload.input
    return SessionStepCommand(
        client_action_id=payload.client_action_id,
        input_type=input_payload.type if input_payload is not None else None,
        move_id=input_payload.move_id if input_payload is not None else None,
        text=input_payload.text if input_payload is not None else None,
        dev_mode=bool(payload.dev_mode),
    )


def _step_response_from_result(result) -> SessionStepResponse:
    return SessionStepResponse(
        session_id=result.session_id,
        version=result.version,
        scene_id=result.scene_id,
        narration_text=result.narration_text,
        recognized=SessionRecognizedPayload.model_validate(result.recognized.to_payload()),
        resolution=SessionResolutionPayload.model_validate(result.resolution.to_payload()),
        ui=SessionUiPayload.model_validate(result.ui.to_payload()),
        debug=result.debug,
    )


@router.post("", response_model=SessionCreateResponse)
async def create_session_endpoint(
    payload: SessionCreateRequest,
    db: AsyncSession = Depends(get_async_session),
) -> SessionCreateResponse:
    try:
        view = await create_play_session(
            db=db,
            story_id=payload.story_id,
            version=payload.version,
            provider_factory=get_llm_provider,
        )
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc

    return SessionCreateResponse(
        session_id=view.session_id,
        story_id=view.story_id,
        version=view.version,
        scene_id=view.scene_id,
        state_summary=view.state_summary,
        opening_guidance=view.opening_guidance.to_payload(),
    )


@router.get("/{session_id}", response_model=SessionGetResponse)
async def get_session_endpoint(
    session_id: str,
    dev_mode: bool = Query(default=False),
    db: AsyncSession = Depends(get_async_session),
) -> SessionGetResponse:
    try:
        view = await get_play_session(db=db, session_id=session_id, dev_mode=dev_mode)
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc

    return SessionGetResponse(
        session_id=view.session_id,
        scene_id=view.scene_id,
        beat_progress=view.beat_progress,
        ended=view.ended,
        state_summary=view.state_summary,
        opening_guidance=view.opening_guidance.to_payload(),
        state=view.state,
    )


@router.get("/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history_endpoint(
    session_id: str,
    db: AsyncSession = Depends(get_async_session),
) -> SessionHistoryResponse:
    try:
        view = await get_play_session_history(db=db, session_id=session_id)
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc

    return SessionHistoryResponse(
        session_id=view.session_id,
        history=[
            SessionHistoryTurn(
                turn_index=item.turn_index,
                scene_id=item.scene_id,
                narration_text=item.narration_text,
                recognized=SessionRecognizedPayload.model_validate(item.recognized.to_payload()),
                resolution=SessionResolutionPayload.model_validate(item.resolution.to_payload()),
                ui=SessionUiPayload.model_validate(item.ui.to_payload()),
                ended=item.ended,
            )
            for item in view.history
        ],
    )


@router.post("/{session_id}/step", response_model=SessionStepResponse, response_model_exclude_none=True)
async def step_session_endpoint(
    session_id: str,
    payload: SessionStepRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> SessionStepResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    command = _step_command_from_request(payload)
    try:
        result = await process_step_command(
            db=db,
            session_id=session_id,
            command=command,
            request_id=request_id,
            provider_factory=get_llm_provider,
        )
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return _step_response_from_result(result)
