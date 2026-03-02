from __future__ import annotations

from datetime import datetime

from sqlmodel import Session as DBSession
from sqlmodel import asc, desc, select

from rpg_backend.storage.models import RuntimeEvent


def save_runtime_event(
    db: DBSession,
    *,
    session_id: str,
    turn_index: int,
    event_type: str,
    payload_json: dict,
) -> RuntimeEvent:
    event = RuntimeEvent(
        session_id=session_id,
        turn_index=turn_index,
        event_type=event_type,
        payload_json=payload_json,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_runtime_events(
    db: DBSession,
    *,
    session_id: str,
    limit: int,
    order: str = "asc",
    event_type: str | None = None,
    created_after: datetime | None = None,
) -> list[RuntimeEvent]:
    stmt = select(RuntimeEvent).where(RuntimeEvent.session_id == session_id)
    if event_type:
        stmt = stmt.where(RuntimeEvent.event_type == event_type)
    if created_after is not None:
        stmt = stmt.where(RuntimeEvent.created_at >= created_after)
    if order == "desc":
        stmt = stmt.order_by(desc(RuntimeEvent.created_at))
    else:
        stmt = stmt.order_by(asc(RuntimeEvent.created_at))
    stmt = stmt.limit(limit)
    return list(db.exec(stmt).all())
