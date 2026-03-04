from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DBSession
from sqlmodel import desc, select

from rpg_backend.storage.models import AdminUser


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def get_admin_user_by_email(db: DBSession, email: str) -> AdminUser | None:
    normalized = normalize_email(email)
    if not normalized:
        return None
    stmt = select(AdminUser).where(AdminUser.email == normalized)
    return db.exec(stmt).first()


def get_admin_user_by_id(db: DBSession, user_id: str) -> AdminUser | None:
    return db.get(AdminUser, user_id)


def list_admin_users(db: DBSession, *, limit: int = 100) -> list[AdminUser]:
    stmt = select(AdminUser).order_by(desc(AdminUser.created_at)).limit(limit)
    return list(db.exec(stmt).all())


def update_admin_user_last_login(db: DBSession, user: AdminUser) -> AdminUser:
    user.last_login_at = utc_now()
    user.updated_at = utc_now()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def upsert_bootstrap_admin(
    db: DBSession,
    *,
    email: str,
    password_hash: str,
) -> AdminUser:
    normalized = normalize_email(email)
    if not normalized:
        raise ValueError("bootstrap email is empty")

    existing = get_admin_user_by_email(db, normalized)
    now = utc_now()
    if existing is not None:
        existing.email = normalized
        existing.password_hash = password_hash
        existing.role = "admin"
        existing.is_active = True
        existing.updated_at = now
        db.add(existing)
        db.commit()
        db.refresh(existing)
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
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_after_conflict = get_admin_user_by_email(db, normalized)
        if existing_after_conflict is None:
            raise
        existing_after_conflict.password_hash = password_hash
        existing_after_conflict.role = "admin"
        existing_after_conflict.is_active = True
        existing_after_conflict.updated_at = utc_now()
        db.add(existing_after_conflict)
        db.commit()
        db.refresh(existing_after_conflict)
        return existing_after_conflict

    db.refresh(created)
    return created
