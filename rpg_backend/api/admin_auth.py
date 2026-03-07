from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.api.errors import ApiError
from rpg_backend.api.route_paths import API_ADMIN_AUTH_PREFIX
from rpg_backend.api.contracts.admin import AdminAuthLoginRequest, AdminAuthLoginResponse, AdminUserPublic
from rpg_backend.config.settings import get_settings
from rpg_backend.infrastructure.db.async_session import get_async_session
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.admin_users_async import (
    get_admin_user_by_email,
    normalize_email,
    update_admin_user_last_login,
)
from rpg_backend.security.tokens import create_access_token
from rpg_backend.security.passwords import verify_password

router = APIRouter(prefix=API_ADMIN_AUTH_PREFIX, tags=["admin-auth"])


@router.post("/login", response_model=AdminAuthLoginResponse)
async def admin_login_endpoint(
    payload: AdminAuthLoginRequest,
    db: AsyncSession = Depends(get_async_session),
) -> AdminAuthLoginResponse:
    email = normalize_email(payload.email)
    user = await get_admin_user_by_email(db, email)
    if user is None:
        raise ApiError(status_code=401, code="invalid_credentials", message="invalid credentials", retryable=False)
    if not bool(user.is_active):
        raise ApiError(status_code=403, code="account_inactive", message="account is inactive", retryable=False)
    if not verify_password(payload.password, user.password_hash):
        raise ApiError(status_code=401, code="invalid_credentials", message="invalid credentials", retryable=False)

    async with transactional(db):
        user = await update_admin_user_last_login(db, user)
    settings = get_settings()
    access_token, expires_at = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        issuer=settings.auth_jwt_issuer,
        secret=settings.auth_jwt_secret,
        expire_minutes=int(settings.auth_jwt_expire_minutes),
    )
    return AdminAuthLoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_at=expires_at,
        user=AdminUserPublic(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=bool(user.is_active),
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
        ),
    )
