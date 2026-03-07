from __future__ import annotations

from typing import Any

from rpg_backend.application.errors import ApplicationError


class StoryNotFoundError(ApplicationError):
    def __init__(self, *, story_id: str) -> None:
        super().__init__(
            status_code=404,
            error_code="not_found",
            message="story not found",
            retryable=False,
            details={"story_id": story_id},
        )


class StoryVersionNotFoundError(ApplicationError):
    def __init__(self, *, story_id: str, version: int) -> None:
        super().__init__(
            status_code=404,
            error_code="not_found",
            message="story version not found",
            retryable=False,
            details={"story_id": story_id, "version": version},
        )


class SessionNotFoundError(ApplicationError):
    def __init__(self, *, session_id: str) -> None:
        super().__init__(
            status_code=404,
            error_code="not_found",
            message="session not found",
            retryable=False,
            details={"session_id": session_id},
        )


class SessionInactiveError(ApplicationError):
    def __init__(self, *, session_id: str) -> None:
        super().__init__(
            status_code=409,
            error_code="session_inactive",
            message="inactive session",
            retryable=False,
            details={"session_id": session_id},
        )


class SessionConflictError(ApplicationError):
    def __init__(self, *, session_id: str, expected_turn_index: int, actual_turn_index: int) -> None:
        super().__init__(
            status_code=409,
            error_code="session_conflict_retry",
            message="session advanced by another action; retry with new client_action_id",
            retryable=True,
            details={
                "session_id": session_id,
                "expected_turn_index": expected_turn_index,
                "actual_turn_index": actual_turn_index,
            },
        )


class ProviderMisconfiguredError(ApplicationError):
    def __init__(self, *, message: str) -> None:
        super().__init__(
            status_code=503,
            error_code="service_unavailable",
            message=message,
            retryable=False,
        )


class RuntimeStepFailedError(ApplicationError):
    def __init__(self, *, error_code: str, message: str, retryable: bool, details: dict[str, Any]) -> None:
        super().__init__(
            status_code=503,
            error_code=error_code,
            message=message,
            retryable=retryable,
            details=details,
        )
