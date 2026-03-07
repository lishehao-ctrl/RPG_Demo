from __future__ import annotations

from rpg_backend.application.errors import ApplicationError


class DraftPatchTargetNotFoundError(ApplicationError):
    def __init__(self, *, target_type: str, target_id: str) -> None:
        super().__init__(
            status_code=404,
            error_code="draft_target_not_found",
            message=f"{target_type} not found",
            retryable=False,
            details={"target_id": target_id, "target_type": target_type},
        )
        self.target_type = target_type
        self.target_id = target_id


class DraftPatchUnsupportedError(ApplicationError):
    def __init__(self, *, target_type: str, field: str) -> None:
        super().__init__(
            status_code=422,
            error_code="validation_error",
            message="unsupported draft patch",
            retryable=False,
            details={"target_type": target_type, "field": field},
        )
        self.target_type = target_type
        self.field = field


class DraftValidationError(ApplicationError):
    def __init__(self, *, errors: list[dict]) -> None:
        super().__init__(
            status_code=422,
            error_code="validation_error",
            message="draft patch invalid",
            retryable=False,
            details={"errors": errors},
        )
        self.errors = errors
