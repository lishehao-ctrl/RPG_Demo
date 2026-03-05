from __future__ import annotations

from rpg_backend.api.errors import ApiError
from rpg_backend.api.schemas import SessionStepResponse
from rpg_backend.application.session_step.contracts import RuntimeExecutionSuccess, StepRequestContext
from rpg_backend.infrastructure.repositories.sessions_async import (
    StepCommitResult,
    commit_step_transition_if_turn_matches,
    get_session_action,
)
from rpg_backend.application.session_step.conflict import (
    build_session_conflict_detail,
    session_conflict_code,
)
from rpg_backend.application.session_step.event_logger import (
    emit_step_conflicted_event,
    emit_step_replayed_event,
)


async def cas_commit_transition(
    ctx: StepRequestContext,
    *,
    execution_success: RuntimeExecutionSuccess,
    working_state: dict,
    working_beat_progress: dict,
    response_payload: dict,
) -> StepCommitResult:
    result = execution_success.result
    return await commit_step_transition_if_turn_matches(
        ctx.db,
        session_id=ctx.session.id,
        expected_turn_count=ctx.turn_index_expected - 1,
        new_scene_id=result["scene_id"],
        new_beat_index=result["beat_index"],
        new_state_json=working_state,
        new_beat_progress_json=working_beat_progress,
        new_ended=bool(result["ended"]),
        client_action_id=ctx.payload.client_action_id,
        request_json=ctx.payload.model_dump(),
        response_json=response_payload,
    )


async def resolve_conflict_or_replay(
    ctx: StepRequestContext,
    *,
    commit_result: StepCommitResult,
) -> SessionStepResponse:
    replayed = await get_session_action(ctx.db, ctx.session.id, ctx.payload.client_action_id)
    if replayed is not None:
        replay_turn_index = max(commit_result.actual_turn_count, ctx.session.turn_count)
        await emit_step_replayed_event(
            db=ctx.db,
            session_id=ctx.session.id,
            story_id=ctx.session.story_id,
            turn_index=replay_turn_index,
            client_action_id=ctx.payload.client_action_id,
            session_action_id=replayed.id,
            request_id=ctx.request_id,
            note="idempotency_replay_after_conflict",
        )
        return SessionStepResponse.model_validate(replayed.response_json)

    actual_turn_index = commit_result.actual_turn_count + 1
    await emit_step_conflicted_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index_expected=ctx.turn_index_expected,
        actual_turn_index=actual_turn_index,
        client_action_id=ctx.payload.client_action_id,
        scene_id_before=ctx.scene_id_before,
        beat_index_before=ctx.beat_index_before,
        request_id=ctx.request_id,
        input_log_fields=ctx.input_log_fields,
        error_code=session_conflict_code(),
    )
    raise ApiError(
        status_code=409,
        code=session_conflict_code(),
        message="session advanced by another action; retry with new client_action_id",
        retryable=True,
        details=build_session_conflict_detail(
            session_id=ctx.session.id,
            expected_turn_index=ctx.turn_index_expected,
            actual_turn_index=actual_turn_index,
        ),
    )
