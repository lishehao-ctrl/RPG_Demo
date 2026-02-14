import uuid

from fastapi import Header

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_user_id(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> uuid.UUID:
    if not x_user_id:
        return DEFAULT_USER_ID
    return uuid.UUID(x_user_id)
