from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import update
from sqlmodel import asc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.storage.models import Session, SessionAction


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(
    db: AsyncSession,
    *,
    story_id: str,
    version: int,
    current_scene_id: str,
    beat_index: int,
    state_json: dict,
    beat_progress_json: dict,
) -> Session:
    session = Session(
        story_id=story_id,
        version=version,
        current_scene_id=current_scene_id,
        beat_index=beat_index,
        state_json=state_json,
        beat_progress_json=beat_progress_json,
        ended=False,
        turn_count=0,
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(db: AsyncSession, session_id: str) -> Session | None:
    return await db.get(Session, session_id)


async def get_session_action(db: AsyncSession, session_id: str, client_action_id: str) -> SessionAction | None:
    stmt = select(SessionAction).where(
        SessionAction.session_id == session_id,
        SessionAction.client_action_id == client_action_id,
    )
    return (await db.exec(stmt)).first()


async def list_session_actions(db: AsyncSession, session_id: str) -> list[SessionAction]:
    stmt = (
        select(SessionAction)
        .where(SessionAction.session_id == session_id)
        .order_by(asc(SessionAction.created_at), asc(SessionAction.id))
    )
    return list((await db.exec(stmt)).all())


@dataclass(frozen=True)
class StepCommitResult:
    applied: bool
    actual_turn_count: int
    reason: str


async def apply_session_turn_update_if_matches(
    db: AsyncSession,
    *,
    session_id: str,
    expected_turn_count: int,
    new_scene_id: str,
    new_beat_index: int,
    new_state_json: dict,
    new_beat_progress_json: dict,
    new_ended: bool,
) -> StepCommitResult:
    next_turn_count = expected_turn_count + 1
    now = utc_now()
    update_stmt = (
        update(Session)
        .where(
            Session.id == session_id,
            Session.turn_count == expected_turn_count,
            Session.ended.is_(False),
        )
        .values(
            current_scene_id=new_scene_id,
            beat_index=new_beat_index,
            state_json=new_state_json,
            beat_progress_json=new_beat_progress_json,
            ended=new_ended,
            turn_count=next_turn_count,
            updated_at=now,
        )
    )
    update_result = await db.exec(update_stmt)
    if update_result.rowcount != 1:
        return StepCommitResult(
            applied=False,
            actual_turn_count=await read_turn_count(db, session_id, fallback=expected_turn_count),
            reason="turn_conflict",
        )
    return StepCommitResult(applied=True, actual_turn_count=next_turn_count, reason="applied")


async def insert_session_action(
    db: AsyncSession,
    *,
    session_id: str,
    client_action_id: str,
    request_json: dict,
    response_json: dict,
) -> SessionAction:
    action = SessionAction(
        session_id=session_id,
        client_action_id=client_action_id,
        request_json=request_json,
        response_json=response_json,
    )
    db.add(action)
    await db.flush()
    return action


async def read_turn_count(db: AsyncSession, session_id: str, *, fallback: int) -> int:
    session = await db.get(Session, session_id)
    if session is None:
        return fallback
    return int(session.turn_count)
