from __future__ import annotations


class LLMUnavailableError(RuntimeError):
    """Raised when generation fails across the full provider chain."""


class NarrativeParseError(ValueError):
    """Raised when narrative payload cannot be parsed/validated."""

    def __init__(self, message: str, *, error_kind: str, raw_snippet: str | None = None):
        super().__init__(message)
        self.error_kind = str(error_kind)
        self.raw_snippet = raw_snippet


class AuthorAssistParseError(ValueError):
    """Raised when author-assist payload cannot be parsed/validated."""

    def __init__(self, message: str, *, error_kind: str, raw_snippet: str | None = None):
        super().__init__(message)
        self.error_kind = str(error_kind)
        self.raw_snippet = raw_snippet


NARRATIVE_ERROR_TIMEOUT = "NARRATIVE_TIMEOUT"
NARRATIVE_ERROR_NETWORK = "NARRATIVE_NETWORK"
NARRATIVE_ERROR_HTTP_STATUS = "NARRATIVE_HTTP_STATUS"
NARRATIVE_ERROR_JSON_PARSE = "NARRATIVE_JSON_PARSE"
NARRATIVE_ERROR_SCHEMA_VALIDATE = "NARRATIVE_SCHEMA_VALIDATE"
ASSIST_ERROR_TIMEOUT = "ASSIST_TIMEOUT"
ASSIST_ERROR_NETWORK = "ASSIST_NETWORK"
ASSIST_ERROR_HTTP_STATUS = "ASSIST_HTTP_STATUS"
ASSIST_ERROR_JSON_PARSE = "ASSIST_JSON_PARSE"
ASSIST_ERROR_SCHEMA_VALIDATE = "ASSIST_SCHEMA_VALIDATE"
