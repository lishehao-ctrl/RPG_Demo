from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from rpg_backend.api.schemas import SessionStepRequest
from rpg_backend.runtime.service import RuntimeService
from rpg_backend.storage.models.entities import Session as SessionRecord


@dataclass(frozen=True)
class StepRequestContext:
    db: Session
    request_id: str
    session: SessionRecord
    payload: SessionStepRequest
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
