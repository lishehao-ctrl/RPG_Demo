from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.application.play_sessions.models import SessionSnapshot, SessionStepCommand
from rpg_backend.runtime.service import RuntimeService


@dataclass(frozen=True)
class StepRequestContext:
    db: AsyncSession
    request_id: str
    session: SessionSnapshot
    command: SessionStepCommand
    normalized_input: dict[str, Any]
    turn_index_expected: int
    scene_id_before: str
    beat_index_before: int
    input_log_fields: dict[str, Any]


@dataclass(frozen=True)
class RuntimeExecutionContext:
    runtime: RuntimeService
    provider_name: str
    route_model: str | None
    narration_model: str | None


@dataclass(frozen=True)
class RuntimeExecutionSuccess:
    result: dict[str, Any]
    duration_ms: int
