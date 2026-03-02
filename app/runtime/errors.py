from __future__ import annotations


class RuntimeLLMError(RuntimeError):
    def __init__(self, *, error_code: str, stage: str, provider: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.stage = stage
        self.provider = provider
        self.message = message


class RuntimeRouteError(RuntimeLLMError):
    def __init__(self, *, error_code: str, message: str, provider: str = "openai"):
        super().__init__(error_code=error_code, stage="route", provider=provider, message=message)


class RuntimeNarrationError(RuntimeLLMError):
    def __init__(self, *, error_code: str, message: str, provider: str = "openai"):
        super().__init__(error_code=error_code, stage="narration", provider=provider, message=message)
