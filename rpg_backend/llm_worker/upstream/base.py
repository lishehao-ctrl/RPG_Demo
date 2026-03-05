from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from rpg_backend.llm.task_executor import TaskUsage


@dataclass(frozen=True)
class UpstreamJsonResult:
    payload: dict[str, Any]
    usage: TaskUsage


class WorkerUpstreamClient(Protocol):
    async def call_json_object(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        timeout_seconds: float,
    ) -> UpstreamJsonResult:
        raise NotImplementedError
