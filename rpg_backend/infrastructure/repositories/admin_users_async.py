from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import desc, select
from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.storage.models import AdminUser


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


async def get_admin_user_by_email(db: AsyncSession, email: str) -> AdminUser | None:
    stmt = select(AdminUser).where(AdminUser.email == normalize_email(email))
    return (await db.exec(stmt)).first()


async def get_admin_user_by_id(db: AsyncSession, user_id: str) -> AdminUser | None:
    return await db.get(AdminUser, user_id)


async def list_admin_users(db: AsyncSession, *, limit: int = 100) -> list[AdminUser]:
    stmt = select(AdminUser).order_by(desc(AdminUser.created_at)).limit(limit)
    return list((await db.exec(stmt)).all())


async def update_admin_user_last_login(db: AsyncSession, user: AdminUser) -> AdminUser:
    user.last_login_at = utc_now()
    user.updated_at = utc_now()
    db.add(user)
    await db.flush()
    return user


async def upsert_bootstrap_admin(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
) -> AdminUser:
    normalized = normalize_email(email)
    if not normalized:
        raise ValueError("bootstrap email is empty")

    existing = await get_admin_user_by_email(db, normalized)
    now = utc_now()
    if existing is not None:
        existing.email = normalized
        existing.password_hash = password_hash
        existing.role = "admin"
        existing.is_active = True
        existing.updated_at = now
        db.add(existing)
        await db.flush()
        return existing

    created = AdminUser(
        email=normalized,
        password_hash=password_hash,
        role="admin",
        is_active=True,
        last_login_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(created)
    try:
        await db.flush()
    except IntegrityError:
        raise
    return created
