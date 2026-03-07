from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlmodel.ext.asyncio.session import AsyncSession


def _session_has_active_transaction(session: object) -> bool:
    probe = getattr(session, "in_transaction", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001
            return False
    return False


@asynccontextmanager
async def transactional(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    try:
        yield session
        if _session_has_active_transaction(session):
            await session.commit()
    except Exception:  # noqa: BLE001
        if _session_has_active_transaction(session):
            await session.rollback()
        raise
