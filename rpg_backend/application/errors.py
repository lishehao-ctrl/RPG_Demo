from __future__ import annotations

from typing import Any


class ApplicationError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.error_code = str(error_code)
        self.message = str(message)
        self.retryable = bool(retryable)
        self.details = dict(details or {})
