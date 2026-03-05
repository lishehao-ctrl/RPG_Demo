from __future__ import annotations
import json
import time
from typing import Any, Callable

from rpg_backend.api.errors import ApiError
from rpg_backend.application.session_step.contracts import RuntimeExecutionContext, RuntimeExecutionSuccess, StepRequestContext
from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.infrastructure.repositories.stories_async import get_story_version
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.runtime.service import RuntimeService
from rpg_backend.runtime.session_step.event_logger import emit_step_started_event
from rpg_backend.runtime.session_step.llm_telemetry import provider_name


def build_runtime_or_503(provider_factory: Callable[[], Any]) -> RuntimeService:
    try:
        provider = provider_factory()
    except LLMProviderConfigError as exc:
        raise ApiError(
            status_code=503,
            code="service_unavailable",
            message=f"llm provider misconfigured: {exc}",
            retryable=False,
        ) from exc
    return RuntimeService(provider)


def build_execution_context(provider_factory: Callable[[], Any]) -> RuntimeExecutionContext:
    runtime = build_runtime_or_503(provider_factory)
    return RuntimeExecutionContext(
        runtime=runtime,
        provider_name=provider_name(),
        route_model=getattr(runtime.provider, "route_model", None),
        narration_model=getattr(runtime.provider, "narration_model", None),
    )


async def execute_runtime_step(
    ctx: StepRequestContext,
    *,
    execution_context: RuntimeExecutionContext,
) -> tuple[RuntimeExecutionSuccess, dict[str, Any], dict[str, Any]]:
    story_version = await get_story_version(ctx.db, ctx.session.story_id, ctx.session.version)
    if story_version is None:
        raise ApiError(status_code=404, code="not_found", message="story version not found", retryable=False)

    pack = StoryPack.model_validate(story_version.pack_json)
    await emit_step_started_event(
        db=ctx.db,
        session_id=ctx.session.id,
        story_id=ctx.session.story_id,
        turn_index_expected=ctx.turn_index_expected,
        client_action_id=ctx.payload.client_action_id,
        normalized_input=ctx.normalized_input,
        scene_id_before=ctx.scene_id_before,
        beat_index_before=ctx.beat_index_before,
        provider_name=execution_context.provider_name,
        request_id=ctx.request_id,
        route_model=execution_context.route_model,
        narration_model=execution_context.narration_model,
        input_log_fields=ctx.input_log_fields,
    )

    working_state = json.loads(json.dumps(ctx.session.state_json))
    working_beat_progress = json.loads(json.dumps(ctx.session.beat_progress_json))
    started_at = time.perf_counter()

    result = await execution_context.runtime.process_step(
        pack,
        ctx.session.current_scene_id,
        ctx.session.beat_index,
        working_state,
        working_beat_progress,
        ctx.normalized_input,
        dev_mode=ctx.payload.dev_mode,
    )
    duration_ms = int((time.perf_counter() - started_at) * 1000)

    execution_success = RuntimeExecutionSuccess(result=result, duration_ms=duration_ms)
    return execution_success, working_state, working_beat_progress
