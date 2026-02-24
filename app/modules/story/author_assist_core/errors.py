from __future__ import annotations

_ASSIST_RETRY_MESSAGE = "LLM unavailable, please retry."


class AuthorAssistError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool = True,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.retryable = bool(retryable)
        self.hint = str(hint) if hint is not None else None


class AuthorAssistUnavailableError(AuthorAssistError):
    def __init__(self, *, hint: str | None = None, detail: str | None = None) -> None:
        message = _ASSIST_RETRY_MESSAGE
        if detail:
            message = f"{message} ({detail})"
        super().__init__(
            code="ASSIST_LLM_UNAVAILABLE",
            message=message,
            retryable=True,
            hint=hint,
        )


class AuthorAssistInvalidOutputError(AuthorAssistError):
    def __init__(self, *, hint: str | None = None, detail: str | None = None) -> None:
        message = "Assist output was invalid. Please retry."
        if detail:
            message = f"{message} ({detail})"
        super().__init__(
            code="ASSIST_INVALID_OUTPUT",
            message=message,
            retryable=True,
            hint=hint,
        )
