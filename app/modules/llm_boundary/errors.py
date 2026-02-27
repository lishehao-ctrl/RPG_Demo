from __future__ import annotations


class LLMUnavailableError(RuntimeError):
    """Raised when LLM output cannot be obtained/validated."""


class GrammarCheckError(RuntimeError):
    def __init__(self, message: str, *, error_kind: str, raw_snippet: str | None = None):
        super().__init__(message)
        self.error_kind = error_kind
        self.raw_snippet = raw_snippet


GRAMMAR_JSON_PARSE = "GRAMMAR_JSON_PARSE"
GRAMMAR_SCHEMA_VALIDATE = "GRAMMAR_SCHEMA_VALIDATE"
GRAMMAR_OUTPUT_SHAPE = "GRAMMAR_OUTPUT_SHAPE"
