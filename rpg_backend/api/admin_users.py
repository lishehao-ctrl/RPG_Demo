from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from rpg_backend.api.errors import ApiError
from rpg_backend.api.route_paths import API_ADMIN_USERS_PREFIX
from rpg_backend.api.schemas import AdminUserListResponse, AdminUserPublic
from rpg_backend.security.deps import require_admin
from rpg_backend.storage.engine import get_session
from rpg_backend.storage.repositories.admin_users import get_admin_user_by_id, list_admin_users

router = APIRouter(
    prefix=API_ADMIN_USERS_PREFIX,
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=AdminUserListResponse)
def list_admin_users_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_session),
) -> AdminUserListResponse:
    users = list_admin_users(db, limit=limit)
    return AdminUserListResponse(
        items=[
            AdminUserPublic(
                id=user.id,
                email=user.email,
                role=user.role,
                is_active=bool(user.is_active),
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login_at=user.last_login_at,
            )
            for user in users
        ]
    )


@router.get("/{user_id}", response_model=AdminUserPublic)
def get_admin_user_endpoint(user_id: str, db: Session = Depends(get_session)) -> AdminUserPublic:
    user = get_admin_user_by_id(db, user_id)
    if user is None:
        raise ApiError(status_code=404, code="not_found", message="user not found", retryable=False)
    return AdminUserPublic(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=bool(user.is_active),
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )
