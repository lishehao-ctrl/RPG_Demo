from __future__ import annotations

from dataclasses import dataclass

from rpg_backend.config.settings import get_settings


@dataclass(frozen=True)
class AuthorWorkflowPolicy:
    max_attempts: int
    timeout_seconds: float
    llm_call_max_retries: int = 1


def get_author_workflow_policy() -> AuthorWorkflowPolicy:
    settings = get_settings()
    return AuthorWorkflowPolicy(
        max_attempts=int(settings.author_workflow_max_attempts),
        timeout_seconds=float(settings.author_workflow_timeout_seconds),
    )
