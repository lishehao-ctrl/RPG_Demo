from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


def _token_external_ref(*, token: str, role: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return f"token:{role}:{digest}"


def ensure_token_user(db: Session, *, token: str, role: str) -> User:
    external_ref = _token_external_ref(token=token, role=role)
    row = db.execute(select(User).where(User.external_ref == external_ref)).scalar_one_or_none()
    if row:
        return row

    display = f"{role.title()} Token User"
    row = User(external_ref=external_ref, display_name=display)
    db.add(row)
    db.flush()
    return row


def resolve_token_user_id(db: Session, *, token: str | None, role: str) -> str | None:
    cleaned = str(token or "").strip()
    if not cleaned:
        return None
    return ensure_token_user(db, token=cleaned, role=role).id

