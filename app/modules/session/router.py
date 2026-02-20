import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.session import service
from app.modules.session.schemas import SessionCreateOut, SessionCreateRequest, SessionStateOut, SnapshotOut, StepRequest, StepResponse

router = APIRouter(prefix="", tags=["sessions"])


@router.post("/sessions", response_model=SessionCreateOut)
def create_session(
    payload: SessionCreateRequest,
    db: Session = Depends(get_db),
):
    sess = service.create_session(db, story_id=payload.story_id, version=payload.version)
    return {"id": sess.id, "status": sess.status, "story_id": sess.story_id, "story_version": sess.story_version}


@router.get("/sessions/{session_id}", response_model=SessionStateOut)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    return service.get_session_state(db, session_id)


@router.post("/sessions/{session_id}/step", response_model=StepResponse)
def step_session(
    session_id: uuid.UUID,
    payload: StepRequest,
    x_idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return service.step_session(
        db,
        session_id,
        payload.choice_id,
        payload.player_input,
        idempotency_key=x_idempotency_key,
    )


@router.post("/sessions/{session_id}/snapshot", response_model=SnapshotOut)
def snapshot(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    snap = service.create_snapshot(db, session_id)
    return {"snapshot_id": snap.id}


@router.post("/sessions/{session_id}/rollback")
def rollback(
    session_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    sess = service.rollback_to_snapshot(db, session_id, snapshot_id)
    return {"id": str(sess.id), "status": sess.status, "current_node_id": sess.story_node_id}


@router.post("/sessions/{session_id}/end")
def end_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    return service.end_session(db, session_id)


@router.get("/sessions/{session_id}/replay")
def get_replay(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    return service.get_replay(db, session_id)
