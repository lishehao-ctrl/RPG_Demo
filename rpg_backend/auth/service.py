from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
import sqlite3
from uuid import uuid4

from fastapi import Request

from rpg_backend.auth.contracts import (
    AuthLoginRequest,
    AuthSessionResponse,
    AuthUserResponse,
    CurrentActorResponse,
)
from rpg_backend.auth.storage import SQLiteAuthStorage
from rpg_backend.config import Settings, get_settings

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class AuthServiceError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class RequestUser:
    user_id: str
    display_name: str


@dataclass(frozen=True)
class AuthenticatedSession:
    user: RequestUser
    session_id: str
    session_token: str
    expires_at: datetime


def _normalize_username(value: str) -> str:
    # Case-insensitive: "Shehao" and "shehao" should resolve to the same account.
    # We lowercase before validating so display_name stays consistent across logins.
    normalized = value.strip().lower()
    if not (2 <= len(normalized) <= 20) or not _USERNAME_PATTERN.match(normalized):
        raise AuthServiceError(
            code="auth_username_invalid",
            message="Username must be 2-20 characters: letters, digits, or underscore.",
            status_code=400,
        )
    return normalized


def _hash_session_token(session_token: str) -> str:
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()


def _user_response(user: RequestUser) -> AuthUserResponse:
    return AuthUserResponse(user_id=user.user_id, display_name=user.display_name)


class AuthService:
    def __init__(
        self,
        *,
        storage: SQLiteAuthStorage | None = None,
        settings: Settings | None = None,
        now_provider=None,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage or SQLiteAuthStorage(self._settings.runtime_state_db_path)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self._now_provider()

    def _session_expiry(self, now: datetime | None = None) -> datetime:
        started_at = now or self._now()
        return started_at + timedelta(seconds=self._settings.auth_session_ttl_seconds)

    def _build_request_user(self, user_payload: dict[str, str]) -> RequestUser:
        return RequestUser(
            user_id=str(user_payload["user_id"]),
            display_name=str(user_payload["display_name"]),
        )

    def login(self, request: AuthLoginRequest) -> AuthenticatedSession:
        """Username-only upsert login. Creates the user on first sight; returns a session either way."""
        username = _normalize_username(request.username)
        user_payload = self._storage.get_user_by_username(username)
        now = self._now()
        if user_payload is None:
            user_id = f"usr_{uuid4().hex[:12]}"
            try:
                self._storage.create_user(
                    user_id=user_id,
                    username=username,
                    display_name=username,
                    created_at=now,
                )
            except sqlite3.IntegrityError:
                # Race: someone else just created the same username — re-fetch.
                user_payload = self._storage.get_user_by_username(username)
                if user_payload is None:
                    raise AuthServiceError(
                        code="auth_username_unavailable",
                        message="Username unavailable, try another.",
                        status_code=409,
                    )
                user = self._build_request_user(user_payload)
            else:
                user = RequestUser(user_id=user_id, display_name=username)
        else:
            user = self._build_request_user(user_payload)
        return self._create_authenticated_session(user=user, created_at=now)

    def _create_authenticated_session(self, *, user: RequestUser, created_at: datetime) -> AuthenticatedSession:
        session_token = secrets.token_urlsafe(32)
        session_id = f"ses_{uuid4().hex[:16]}"
        expires_at = self._session_expiry(created_at)
        self._storage.create_session(
            session_id=session_id,
            user_id=user.user_id,
            token_hash=_hash_session_token(session_token),
            created_at=created_at,
            expires_at=expires_at,
            last_seen_at=created_at,
        )
        return AuthenticatedSession(
            user=user,
            session_id=session_id,
            session_token=session_token,
            expires_at=expires_at,
        )

    def resolve_session(self, request: Request) -> AuthenticatedSession | None:
        session_token = request.cookies.get(self._settings.auth_session_cookie_name)
        if not session_token:
            return None
        payload = self._storage.get_session_with_user(_hash_session_token(session_token))
        if payload is None:
            return None
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
        now = self._now()
        if expires_at <= now:
            self._storage.delete_session_by_token_hash(str(payload["token_hash"]))
            return None
        refreshed_expiry = self._session_expiry(now)
        self._storage.touch_session(
            session_id=str(payload["session_id"]),
            expires_at=refreshed_expiry,
            last_seen_at=now,
        )
        return AuthenticatedSession(
            user=self._build_request_user(payload),
            session_id=str(payload["session_id"]),
            session_token=session_token,
            expires_at=refreshed_expiry,
        )

    def logout(self, request: Request) -> None:
        session_token = request.cookies.get(self._settings.auth_session_cookie_name)
        if not session_token:
            return
        self._storage.delete_session_by_token_hash(_hash_session_token(session_token))

    def build_session_response(self, session: AuthenticatedSession | None) -> AuthSessionResponse:
        if session is None:
            return AuthSessionResponse(authenticated=False, user=None)
        return AuthSessionResponse(authenticated=True, user=_user_response(session.user))

    def build_current_actor_response(self, session: AuthenticatedSession) -> CurrentActorResponse:
        return CurrentActorResponse(
            user_id=session.user.user_id,
            display_name=session.user.display_name,
            is_default=False,
        )

    def require_session(self, request: Request) -> AuthenticatedSession:
        session = self.resolve_session(request)
        if session is None:
            raise AuthServiceError(
                code="auth_session_required",
                message="Sign in required.",
                status_code=401,
            )
        return session
