from __future__ import annotations

from typing import Any

from rpg_backend.application.play_sessions.errors import SessionInactiveError, SessionNotFoundError
from rpg_backend.application.play_sessions.models import SessionSnapshot, SessionStepCommand
from rpg_backend.application.session_step.contracts import StepRequestContext
from rpg_backend.config.settings import get_settings
from rpg_backend.domain.constants import GLOBAL_HELP_ME_PROGRESS_MOVE_ID
from rpg_backend.infrastructure.repositories.sessions_async import get_session as get_session_record
from rpg_backend.observability.logging import build_input_log_fields


def normalize_step_input(command: SessionStepCommand) -> dict[str, str]:
    raw_type = (command.input_type or "").strip().lower()
    move_id = (command.move_id or "").strip() if command.move_id is not None else ""
    text = command.text or ""

    if raw_type == "button":
        if move_id:
            return {"type": "button", "move_id": move_id}
        return {"type": "button", "move_id": GLOBAL_HELP_ME_PROGRESS_MOVE_ID}

    return {"type": "text", "text": text}


def _session_snapshot(session: Any) -> SessionSnapshot:
    return SessionSnapshot(
        id=str(session.id),
        story_id=str(session.story_id),
        version=int(session.version),
        current_scene_id=str(session.current_scene_id),
        beat_index=int(session.beat_index),
        state_json=dict(session.state_json or {}),
        beat_progress_json=dict(session.beat_progress_json or {}),
        ended=bool(session.ended),
        turn_count=int(session.turn_count),
    )


async def validate_request(
    *,
    db,
    session_id: str,
    command: SessionStepCommand,
    request_id: str,
) -> StepRequestContext:
    settings = get_settings()
    session_record = await get_session_record(db, session_id)
    if session_record is None:
        raise SessionNotFoundError(session_id=session_id)
    session = _session_snapshot(session_record)
    if session.ended:
        raise SessionInactiveError(session_id=session_id)

    normalized_input = normalize_step_input(command)
    turn_index_expected = session.turn_count + 1
    scene_id_before = session.current_scene_id
    beat_index_before = session.beat_index
    input_log_fields = build_input_log_fields(normalized_input, redact_text=settings.obs_redact_input_text)

    return StepRequestContext(
        db=db,
        request_id=request_id,
        session=session,
        command=command,
        normalized_input=normalized_input,
        turn_index_expected=turn_index_expected,
        scene_id_before=scene_id_before,
        beat_index_before=beat_index_before,
        input_log_fields=input_log_fields,
    )
