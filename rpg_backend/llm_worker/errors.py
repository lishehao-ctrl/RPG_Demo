from __future__ import annotations

from dataclasses import dataclass

from rpg_backend.llm_worker.schemas import WorkerTaskErrorPayload


@dataclass
class WorkerTaskError(RuntimeError):
    error_code: str
    message: str
    retryable: bool = False
    provider_status: int | None = None
    model: str | None = None
    attempts: int = 1

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_payload(self) -> WorkerTaskErrorPayload:
        return WorkerTaskErrorPayload(
            error_code=self.error_code,
            message=self.message,
            retryable=self.retryable,
            provider_status=self.provider_status,
            model=self.model,
            attempts=max(1, int(self.attempts)),
        )
