from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.response_sessions_async import (
    delete_response_session_cursor,
    get_response_session_cursor,
    upsert_response_session_cursor,
)
from rpg_backend.llm.task_specs import AUTHOR_BEAT_CHANNEL, AUTHOR_OVERVIEW_CHANNEL, PLAY_CHANNEL

PLAY_SCOPE_TYPE = "play_session"
AUTHOR_SCOPE_TYPE = "author_run"


@dataclass(frozen=True)
class ResponseSessionCursorValue:
    previous_response_id: str
    model: str


class ResponseIdResult(Protocol):
    response_id: str | None


TResponseIdResult = TypeVar("TResponseIdResult", bound=ResponseIdResult)


def is_cursor_invalid_error(exc: Exception) -> bool:
    message = str(exc or "").strip().lower()
    if not message:
        return False
    cursor_markers = {
        "previous_response_id",
        "response id",
        "invalid response",
        "unknown response",
        "response expired",
        "not found",
        "expired",
    }
    return any(marker in message for marker in cursor_markers)


class ResponseSessionStore:
    async def get_cursor(
        self,
        *,
        scope_type: str,
        scope_id: str,
        channel: str,
    ) -> ResponseSessionCursorValue | None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            item = await get_response_session_cursor(
                db,
                scope_type=scope_type,
                scope_id=scope_id,
                channel=channel,
            )
        if item is None:
            return None
        return ResponseSessionCursorValue(
            previous_response_id=item.previous_response_id,
            model=item.model,
        )

    async def set_cursor(
        self,
        *,
        scope_type: str,
        scope_id: str,
        channel: str,
        model: str,
        response_id: str,
    ) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            async with transactional(db):
                await upsert_response_session_cursor(
                    db,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    channel=channel,
                    model=model,
                    previous_response_id=response_id,
                )

    async def clear_cursor(
        self,
        *,
        scope_type: str,
        scope_id: str,
        channel: str,
    ) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            async with transactional(db):
                await delete_response_session_cursor(
                    db,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    channel=channel,
                )

    async def call_with_cursor(
        self,
        *,
        scope_type: str,
        scope_id: str,
        channel: str,
        model: str,
        invoke,
    ) -> TResponseIdResult:
        cursor = await self.get_cursor(scope_type=scope_type, scope_id=scope_id, channel=channel)
        if cursor is not None and cursor.model != model:
            await self.clear_cursor(scope_type=scope_type, scope_id=scope_id, channel=channel)
            cursor = None
        previous_response_id = cursor.previous_response_id if cursor else None

        try:
            result = await invoke(previous_response_id)
        except Exception as exc:  # noqa: BLE001
            if previous_response_id and is_cursor_invalid_error(exc):
                await self.clear_cursor(scope_type=scope_type, scope_id=scope_id, channel=channel)
                result = await invoke(None)
            else:
                raise

        if getattr(result, "response_id", None):
            await self.set_cursor(
                scope_type=scope_type,
                scope_id=scope_id,
                channel=channel,
                model=model,
                response_id=str(result.response_id),
            )
        return result
