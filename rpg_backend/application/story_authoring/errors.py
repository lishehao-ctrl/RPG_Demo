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


class PublishedStoryVersionNotFoundError(ApplicationError):
    def __init__(self, *, story_id: str, version: int | None = None) -> None:
        super().__init__(
            status_code=404,
            error_code="not_found",
            message="published version not found",
            retryable=False,
            details={"story_id": story_id, "version": version},
        )


class StoryLintFailedError(ApplicationError):
    def __init__(self, *, errors: list[str], warnings: list[str]) -> None:
        super().__init__(
            status_code=422,
            error_code="validation_error",
            message="story lint failed",
            retryable=False,
            details={"errors": errors, "warnings": warnings},
        )


class StoryGenerationFailedError(ApplicationError):
    def __init__(self, *, error_code: str, details: dict[str, Any]) -> None:
        super().__init__(
            status_code=422,
            error_code=error_code,
            message="story generation failed",
            retryable=False,
            details=details,
        )
