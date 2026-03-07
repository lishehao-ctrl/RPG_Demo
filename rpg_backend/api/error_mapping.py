from __future__ import annotations

from rpg_backend.api.errors import ApiError
from rpg_backend.application.errors import ApplicationError


def api_error_from_application_error(exc: ApplicationError) -> ApiError:
    return ApiError(
        status_code=exc.status_code,
        code=exc.error_code,
        message=exc.message,
        retryable=exc.retryable,
        details=exc.details,
    )
