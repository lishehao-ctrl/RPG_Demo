from __future__ import annotations

from time import perf_counter

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.modules.auth.deps import require_player_token
from app.modules.auth.identity import resolve_token_user_id
from app.modules.llm_boundary.errors import LLMUnavailableError
from app.modules.llm_boundary.service import get_llm_boundary
from app.modules.runtime.schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStateResponse,
    StepRequest,
    StepResponse,
)
from app.modules.runtime.service import (
    IdempotencyInProgressError,
    IdempotencyPayloadMismatchError,
    RuntimeChoiceLockedError,
    RuntimeConflictError,
    RuntimeForbiddenError,
    RuntimeInvalidChoiceError,
    RuntimeNotFoundError,
    SessionStepConflictError,
    create_session,
    get_session_state,
    run_step,
)
from app.modules.telemetry.service import record_step_failure, record_step_success

router = APIRouter(prefix="/api/v1", tags=["runtime"])


def _actor_user_id(*, player_token: str | None) -> str | None:
    cleaned = str(player_token or "").strip()
    if not cleaned:
        return None

    with SessionLocal() as identity_db:
        user_id = resolve_token_user_id(identity_db, token=cleaned, role="player")
        identity_db.commit()
        return user_id


@router.post("/sessions", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_session_api(
    payload: SessionCreateRequest,
    db: Session = Depends(get_db),
    player_token: str | None = Depends(require_player_token),
) -> SessionCreateResponse:
    actor_user_id = _actor_user_id(player_token=player_token)
    requested_user_id = payload.user_id
    if actor_user_id:
        if requested_user_id and requested_user_id != actor_user_id:
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "session user mismatch"})
        requested_user_id = actor_user_id

    try:
        return create_session(
            db,
            story_id=payload.story_id,
            version=payload.version,
            user_id=requested_user_id,
        )
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)}) from exc


@router.get("/sessions/{session_id}", response_model=SessionStateResponse)
def get_session_api(
    session_id: str,
    db: Session = Depends(get_db),
    player_token: str | None = Depends(require_player_token),
) -> SessionStateResponse:
    actor_user_id = _actor_user_id(player_token=player_token)
    try:
        return get_session_state(db, session_id=session_id, actor_user_id=actor_user_id)
    except RuntimeForbiddenError as exc:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except RuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc


@router.post("/sessions/{session_id}/step", response_model=StepResponse)
def step_api(
    session_id: str,
    payload: StepRequest,
    db: Session = Depends(get_db),
    x_idempotency_key: str | None = Header(default=None),
    player_token: str | None = Depends(require_player_token),
) -> StepResponse:
    started = perf_counter()

    idem_key = str(x_idempotency_key or "").strip()
    if not idem_key:
        record_step_failure(error_code="MISSING_IDEMPOTENCY_KEY")
        raise HTTPException(
            status_code=400,
            detail={"code": "MISSING_IDEMPOTENCY_KEY", "message": "X-Idempotency-Key header is required"},
        )

    actor_user_id = _actor_user_id(player_token=player_token)
    try:
        response = run_step(
            db,
            session_id=session_id,
            payload=payload,
            idempotency_key=idem_key,
            llm_boundary=get_llm_boundary(),
            actor_user_id=actor_user_id,
        )
        elapsed_ms = (perf_counter() - started) * 1000.0
        record_step_success(latency_ms=elapsed_ms, step=response)
        return response
    except RuntimeForbiddenError as exc:
        record_step_failure(error_code="FORBIDDEN")
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": str(exc)}) from exc
    except RuntimeNotFoundError as exc:
        record_step_failure(error_code="NOT_FOUND")
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}) from exc
    except RuntimeChoiceLockedError as exc:
        record_step_failure(error_code="CHOICE_LOCKED")
        raise HTTPException(status_code=422, detail={"code": "CHOICE_LOCKED", "message": str(exc)}) from exc
    except RuntimeInvalidChoiceError as exc:
        record_step_failure(error_code="INVALID_CHOICE")
        raise HTTPException(status_code=422, detail={"code": "INVALID_CHOICE", "message": str(exc)}) from exc
    except IdempotencyInProgressError as exc:
        record_step_failure(error_code="REQUEST_IN_PROGRESS")
        raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS", "message": str(exc)}) from exc
    except IdempotencyPayloadMismatchError as exc:
        record_step_failure(error_code="IDEMPOTENCY_PAYLOAD_MISMATCH")
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_PAYLOAD_MISMATCH", "message": str(exc)}) from exc
    except SessionStepConflictError as exc:
        record_step_failure(error_code="SESSION_STEP_CONFLICT")
        raise HTTPException(status_code=409, detail={"code": "SESSION_STEP_CONFLICT", "message": str(exc)}) from exc
    except RuntimeConflictError as exc:
        record_step_failure(error_code="RUNTIME_CONFLICT")
        raise HTTPException(status_code=409, detail={"code": "RUNTIME_CONFLICT", "message": str(exc)}) from exc
    except LLMUnavailableError as exc:
        record_step_failure(error_code="LLM_UNAVAILABLE")
        raise HTTPException(status_code=503, detail={"code": "LLM_UNAVAILABLE", "message": str(exc)}) from exc
    except ValueError as exc:
        record_step_failure(error_code="BAD_REQUEST")
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(exc)}) from exc

