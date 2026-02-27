from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.config import settings


def require_author_token(
    x_author_token: str | None = Header(default=None, alias="X-Author-Token"),
) -> str | None:
    expected = str(settings.author_api_token or "").strip()
    if not expected:
        return None

    provided = str(x_author_token or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid author token"},
        )
    return provided


def require_player_token(
    x_player_token: str | None = Header(default=None, alias="X-Player-Token"),
) -> str | None:
    expected = str(settings.player_api_token or "").strip()
    if not expected:
        return None

    provided = str(x_player_token or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid player token"},
        )
    return provided
