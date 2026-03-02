from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionGetResponse,
    SessionStepRequest,
    SessionStepResponse,
)
from app.domain.constants import GLOBAL_HELP_ME_PROGRESS_MOVE_ID
from app.domain.pack_schema import StoryPack
from app.llm.base import LLMProviderConfigError
from app.llm.factory import get_llm_provider
from app.runtime.errors import RuntimeNarrationError, RuntimeRouteError
from app.runtime.service import RuntimeService
from app.storage.engine import get_session
from app.storage.repositories.sessions import (
    create_session,
    get_session as get_session_record,
    get_session_action,
    save_session,
    save_session_action,
)
from app.storage.repositories.stories import get_story, get_story_version

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _state_summary(state: dict) -> dict[str, int]:
    values = state.get("values", {})
    return {
        "events": len(state.get("events", [])),
        "inventory": len(state.get("inventory", [])),
        "cost_total": int(values.get("cost_total", 0)),
    }


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

    # Invalid or missing type is downgraded to text input.
    return {"type": "text", "text": text}


def _build_runtime_or_503() -> RuntimeService:
    try:
        provider = get_llm_provider()
    except LLMProviderConfigError as exc:
        raise HTTPException(status_code=503, detail=f"llm provider misconfigured: {exc}") from exc
    return RuntimeService(provider)


def _llm_runtime_failure_detail(exc: RuntimeRouteError | RuntimeNarrationError) -> dict[str, str]:
    return {
        "error_code": exc.error_code,
        "stage": exc.stage,
        "message": exc.message,
        "provider": exc.provider,
    }


@router.post("", response_model=SessionCreateResponse)
def create_session_endpoint(payload: SessionCreateRequest, db: Session = Depends(get_session)) -> SessionCreateResponse:
    story = get_story(db, payload.story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="story not found")

    story_version = get_story_version(db, payload.story_id, payload.version)
    if story_version is None:
        raise HTTPException(status_code=404, detail="story version not found")

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
        raise HTTPException(status_code=404, detail="session not found")

    return SessionGetResponse(
        session_id=session.id,
        scene_id=session.current_scene_id,
        beat_progress=session.beat_progress_json,
        ended=session.ended,
        state_summary=_state_summary(session.state_json),
        state=session.state_json if dev_mode else None,
    )


@router.post("/{session_id}/step", response_model=SessionStepResponse)
def step_session_endpoint(
    session_id: str,
    payload: SessionStepRequest,
    db: Session = Depends(get_session),
) -> SessionStepResponse:
    session = get_session_record(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.ended:
        raise HTTPException(status_code=409, detail="inactive session")

    existing = get_session_action(db, session_id, payload.client_action_id)
    if existing is not None:
        return SessionStepResponse.model_validate(existing.response_json)

    story_version = get_story_version(db, session.story_id, session.version)
    if story_version is None:
        raise HTTPException(status_code=404, detail="story version not found")

    pack = StoryPack.model_validate(story_version.pack_json)
    runtime = _build_runtime_or_503()
    working_state = json.loads(json.dumps(session.state_json))
    working_beat_progress = json.loads(json.dumps(session.beat_progress_json))

    try:
        result = runtime.process_step(
            pack,
            current_scene_id=session.current_scene_id,
            beat_index=session.beat_index,
            state=working_state,
            beat_progress=working_beat_progress,
            action_input=_normalize_step_input(payload.input),
            dev_mode=payload.dev_mode,
        )
    except (RuntimeRouteError, RuntimeNarrationError) as exc:
        raise HTTPException(status_code=503, detail=_llm_runtime_failure_detail(exc)) from exc

    session.current_scene_id = result["scene_id"]
    session.beat_index = result["beat_index"]
    session.state_json = working_state
    session.beat_progress_json = working_beat_progress
    session.ended = result["ended"]
    session.turn_count += 1
    save_session(db, session)

    response_payload = {
        "session_id": session.id,
        "version": session.version,
        "scene_id": result["scene_id"],
        "narration_text": result["narration_text"],
        "recognized": result["recognized"],
        "resolution": result["resolution"],
        "ui": result["ui"],
        "debug": result.get("debug"),
    }

    save_session_action(
        db,
        session_id=session.id,
        client_action_id=payload.client_action_id,
        request_json=payload.model_dump(),
        response_json=response_payload,
    )

    return SessionStepResponse.model_validate(response_payload)
