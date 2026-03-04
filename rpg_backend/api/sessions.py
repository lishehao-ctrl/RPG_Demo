from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session

from rpg_backend.api.errors import ApiError
from rpg_backend.api.route_paths import API_V2_SESSIONS_PREFIX
from rpg_backend.api.schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionGetResponse,
    SessionStepRequest,
    SessionStepResponse,
)
from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import get_llm_provider
from rpg_backend.observability.context import get_request_id
from rpg_backend.runtime.service import RuntimeService
from rpg_backend.runtime.session_step.orchestrator import process_step_request
from rpg_backend.storage.engine import get_session
from rpg_backend.storage.repositories.sessions import create_session, get_session as get_session_record
from rpg_backend.storage.repositories.stories import get_story, get_story_version

router = APIRouter(prefix=API_V2_SESSIONS_PREFIX, tags=["sessions"])


def _state_summary(state: dict) -> dict[str, int]:
    values = state.get("values", {})
    return {
        "events": len(state.get("events", [])),
        "inventory": len(state.get("inventory", [])),
        "cost_total": int(values.get("cost_total", 0)),
    }


def _build_runtime_or_503() -> RuntimeService:
    try:
        provider = get_llm_provider()
    except LLMProviderConfigError as exc:
        raise ApiError(
            status_code=503,
            code="service_unavailable",
            message=f"llm provider misconfigured: {exc}",
            retryable=False,
        ) from exc
    return RuntimeService(provider)


@router.post("", response_model=SessionCreateResponse)
def create_session_endpoint(payload: SessionCreateRequest, db: Session = Depends(get_session)) -> SessionCreateResponse:
    story = get_story(db, payload.story_id)
    if story is None:
        raise ApiError(status_code=404, code="not_found", message="story not found", retryable=False)

    story_version = get_story_version(db, payload.story_id, payload.version)
    if story_version is None:
        raise ApiError(status_code=404, code="not_found", message="story version not found", retryable=False)

    pack = StoryPack.model_validate(story_version.pack_json)
    runtime = _build_runtime_or_503()
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    session = create_session(
        db,
        story_id=payload.story_id,
        version=payload.version,
        current_scene_id=scene_id,
        beat_index=beat_index,
        state_json=state,
        beat_progress_json=beat_progress,
    )

    return SessionCreateResponse(
        session_id=session.id,
        story_id=payload.story_id,
        version=payload.version,
        scene_id=scene_id,
        state_summary=_state_summary(state),
    )


@router.get("/{session_id}", response_model=SessionGetResponse)
def get_session_endpoint(
    session_id: str,
    dev_mode: bool = Query(default=False),
    db: Session = Depends(get_session),
) -> SessionGetResponse:
    session = get_session_record(db, session_id)
    if session is None:
        raise ApiError(status_code=404, code="not_found", message="session not found", retryable=False)

    return SessionGetResponse(
        session_id=session.id,
        scene_id=session.current_scene_id,
        beat_progress=session.beat_progress_json,
        ended=session.ended,
        state_summary=_state_summary(session.state_json),
        state=session.state_json if dev_mode else None,
    )


@router.post("/{session_id}/step", response_model=SessionStepResponse, response_model_exclude_none=True)
def step_session_endpoint(
    session_id: str,
    payload: SessionStepRequest,
    request: Request,
    db: Session = Depends(get_session),
) -> SessionStepResponse:
    request_id = getattr(request.state, "request_id", None) or get_request_id()
    return process_step_request(
        db=db,
        session_id=session_id,
        payload=payload,
        request_id=request_id,
        provider_factory=get_llm_provider,
    )
