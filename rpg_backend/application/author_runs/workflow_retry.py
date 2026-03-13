from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from rpg_backend.application.author_runs.workflow_state import AuthorWorkflowState
from rpg_backend.application.author_runs.workflow_vocabulary import (
    AuthorWorkflowErrorCode,
    AuthorWorkflowEventType,
)
from rpg_backend.generator.author_workflow_errors import PromptCompileError
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy


AuthorRunEventRecorder = Callable[[str, str, str, dict[str, Any] | None], Awaitable[None]]
AuthorRunNodeStartRecorder = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]
AuthorWorkflowNodeHandler = Callable[[AuthorWorkflowState], Awaitable[dict[str, Any]] | dict[str, Any]]


def tracked_node(
    *,
    node_name: str,
    func: AuthorWorkflowNodeHandler,
    policy: AuthorWorkflowPolicy,
    mark_run_node_started: AuthorRunNodeStartRecorder,
    record_run_node_event: AuthorRunEventRecorder,
) -> Callable[[AuthorWorkflowState], Awaitable[dict[str, Any]]]:
    async def _invoke_once(state: AuthorWorkflowState) -> dict[str, Any]:
        result = func(state)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _wrapped(state: AuthorWorkflowState) -> dict[str, Any]:
        max_attempts = int(policy.max_attempts)
        effective_timeout_seconds = float(policy.timeout_seconds)
        for attempt in range(1, max_attempts + 1):
            await mark_run_node_started(
                state["run_id"],
                node_name,
                {
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "timeout_seconds": effective_timeout_seconds,
                },
            )
            try:
                return await asyncio.wait_for(_invoke_once(state), timeout=effective_timeout_seconds)
            except asyncio.TimeoutError as exc:
                if attempt < max_attempts:
                    await record_run_node_event(
                        state["run_id"],
                        node_name,
                        AuthorWorkflowEventType.NODE_RETRY,
                        {
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "reason": "timeout",
                            "timeout_seconds": effective_timeout_seconds,
                        },
                    )
                    continue
                raise PromptCompileError(
                    error_code=AuthorWorkflowErrorCode.AUTHOR_NODE_TIMEOUT,
                    errors=[f"author workflow node '{node_name}' timed out after {effective_timeout_seconds:.1f}s"],
                    notes=[f"node exceeded timeout after {max_attempts} attempts"],
                ) from exc
            except PromptCompileError as exc:
                if exc.error_code == AuthorWorkflowErrorCode.PROMPT_COMPILE_FAILED and attempt < max_attempts:
                    await record_run_node_event(
                        state["run_id"],
                        node_name,
                        AuthorWorkflowEventType.NODE_RETRY,
                        {
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "reason": exc.error_code,
                            "message": str(exc),
                        },
                    )
                    continue
                raise

    return _wrapped
