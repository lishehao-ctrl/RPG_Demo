import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dev_auth import get_current_user_id
from app.modules.session import service
from app.modules.session.schemas import SessionCreateOut, SessionStateOut, SnapshotOut, StepRequest, StepResponse

router = APIRouter(prefix="", tags=["sessions"])


@router.post("/sessions", response_model=SessionCreateOut)
def create_session(
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    sess = service.create_session(db, user_id)
    return {"id": sess.id, "status": sess.status, "token_budget_remaining": sess.token_budget_remaining}


@router.get("/sessions/{session_id}", response_model=SessionStateOut)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    return service.get_session_state(db, session_id, user_id)


@router.post("/sessions/{session_id}/step", response_model=StepResponse)
def step_session(
    session_id: uuid.UUID,
    payload: StepRequest,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    return service.step_session(db, session_id, user_id, payload.input_text, payload.choice_id)


@router.post("/sessions/{session_id}/snapshot", response_model=SnapshotOut)
def snapshot(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    snap = service.create_snapshot(db, session_id, user_id)
    return {"snapshot_id": snap.id}


@router.post("/sessions/{session_id}/rollback")
def rollback(
    session_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    sess = service.rollback_to_snapshot(db, session_id, user_id, snapshot_id)
    return {"id": str(sess.id), "status": sess.status, "current_node_id": str(sess.current_node_id) if sess.current_node_id else None}


@router.post("/sessions/{session_id}/end")
def end_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    sess = service.end_session(db, session_id, user_id)
    return {"id": str(sess.id), "status": sess.status}


@router.get("/sessions/{session_id}/replay")
def get_replay(session_id: uuid.UUID):
    raise HTTPException(status_code=501, detail="Replay not implemented yet")
