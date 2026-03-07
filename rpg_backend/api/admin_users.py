from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.api.contracts.admin import AdminUserListResponse, AdminUserPublic
from rpg_backend.api.error_mapping import api_error_from_application_error
from rpg_backend.api.route_paths import API_ADMIN_USERS_PREFIX
from rpg_backend.application.admin_console.service import get_admin_user_view, list_admin_user_views
from rpg_backend.application.errors import ApplicationError
from rpg_backend.infrastructure.db.async_session import get_async_session
from rpg_backend.security.deps import require_admin

router = APIRouter(
    prefix=API_ADMIN_USERS_PREFIX,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=AdminUserListResponse)
async def list_admin_users_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_async_session),
) -> AdminUserListResponse:
    users = await list_admin_user_views(db=db, limit=limit)
    return AdminUserListResponse(
        items=[
            AdminUserPublic(
                id=user.id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login_at=user.last_login_at,
            )
            for user in users
        ]
    )


@router.get("/{user_id}", response_model=AdminUserPublic)
async def get_admin_user_endpoint(
    user_id: str,
    db: AsyncSession = Depends(get_async_session),
) -> AdminUserPublic:
    try:
        user = await get_admin_user_view(db=db, user_id=user_id)
    except ApplicationError as exc:
        raise api_error_from_application_error(exc) from exc
    return AdminUserPublic(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )
