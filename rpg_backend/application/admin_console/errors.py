from __future__ import annotations

from rpg_backend.application.errors import ApplicationError


class AdminUserNotFoundError(ApplicationError):
    def __init__(self, *, user_id: str) -> None:
        super().__init__(
            status_code=404,
            error_code="not_found",
            message="user not found",
            retryable=False,
            details={"user_id": user_id},
        )
