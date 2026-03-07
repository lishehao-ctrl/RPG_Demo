from __future__ import annotations

from rpg_backend.application.play_sessions.models import SessionStepResult
from rpg_backend.application.session_step.contracts import StepRequestContext
from rpg_backend.application.session_step.event_logger import emit_step_replayed_event
from rpg_backend.infrastructure.repositories.sessions_async import get_session_action


async def idempotency_precheck(ctx: StepRequestContext) -> SessionStepResult | None:
    existing = await get_session_action(ctx.db, ctx.session.id, ctx.command.client_action_id)
    if existing is None:
        return None

    await emit_step_replayed_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index=ctx.session.turn_count,
        client_action_id=ctx.command.client_action_id,
        session_action_id=existing.id,
        request_id=ctx.request_id,
        note="idempotency_replay",
    )
    return SessionStepResult.from_payload(existing.response_json)
