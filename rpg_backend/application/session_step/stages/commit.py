from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from rpg_backend.application.play_sessions.errors import SessionConflictError
from rpg_backend.application.play_sessions.models import SessionStepResult
from rpg_backend.application.session_step.contracts import RuntimeExecutionSuccess, StepRequestContext
from rpg_backend.application.session_step.event_logger import emit_step_conflicted_event, emit_step_replayed_event
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.sessions_async import (
    StepCommitResult,
    apply_session_turn_update_if_matches,
    get_session_action,
    insert_session_action,
    read_turn_count,
)


async def cas_commit_transition(
    ctx: StepRequestContext,
    *,
    execution_success: RuntimeExecutionSuccess,
    result: SessionStepResult,
    working_state: dict,
    working_beat_progress: dict,
) -> StepCommitResult:
    runtime_result = execution_success.result
    async with transactional(ctx.db):
        commit_result = await apply_session_turn_update_if_matches(
            ctx.db,
            session_id=ctx.session.id,
            expected_turn_count=ctx.turn_index_expected - 1,
            new_scene_id=result.scene_id,
            new_beat_index=int(runtime_result["beat_index"]),
            new_state_json=working_state,
            new_beat_progress_json=working_beat_progress,
            new_ended=bool(runtime_result["ended"]),
        )
        if not commit_result.applied:
            return commit_result
        try:
            await insert_session_action(
                ctx.db,
                session_id=ctx.session.id,
                client_action_id=ctx.command.client_action_id,
                request_json=ctx.command.to_request_payload(),
                response_json=result.to_payload(),
            )
        except IntegrityError:
            await ctx.db.rollback()
            return StepCommitResult(
                applied=False,
                actual_turn_count=await read_turn_count(ctx.db, ctx.session.id, fallback=ctx.turn_index_expected - 1),
                reason="idempotency_conflict",
            )
        return commit_result


async def resolve_conflict_or_replay(
    ctx: StepRequestContext,
    *,
    commit_result: StepCommitResult,
) -> SessionStepResult:
    replayed = await get_session_action(ctx.db, ctx.session.id, ctx.command.client_action_id)
    if replayed is not None:
        replay_turn_index = max(commit_result.actual_turn_count, ctx.session.turn_count)
        await emit_step_replayed_event(
            db=ctx.db,
            session_id=ctx.session.id,
            story_id=ctx.session.story_id,
            turn_index=replay_turn_index,
            client_action_id=ctx.command.client_action_id,
            session_action_id=replayed.id,
            request_id=ctx.request_id,
            note="idempotency_replay_after_conflict",
        )
        return SessionStepResult.from_payload(replayed.response_json)

    actual_turn_index = commit_result.actual_turn_count + 1
    await emit_step_conflicted_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index_expected=ctx.turn_index_expected,
        actual_turn_index=actual_turn_index,
        client_action_id=ctx.command.client_action_id,
        scene_id_before=ctx.scene_id_before,
        beat_index_before=ctx.beat_index_before,
        request_id=ctx.request_id,
        input_log_fields=ctx.input_log_fields,
        error_code="session_conflict_retry",
    )
    raise SessionConflictError(
        session_id=ctx.session.id,
        expected_turn_index=ctx.turn_index_expected,
        actual_turn_index=actual_turn_index,
    )
