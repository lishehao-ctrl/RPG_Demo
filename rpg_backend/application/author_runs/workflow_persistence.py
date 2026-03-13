from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.application.author_runs.workflow_artifacts import (
    artifact_payload_from_state,
    build_persisted_artifacts_for_update,
)
from rpg_backend.application.author_runs.workflow_state import AuthorWorkflowState, resolve_workflow_failure_errors
from rpg_backend.application.author_runs.workflow_vocabulary import (
    AuthorWorkflowArtifactType,
    AuthorWorkflowErrorCode,
    AuthorWorkflowEventType,
    AuthorWorkflowNode,
    AuthorWorkflowStatus,
)
from rpg_backend.generator.author_workflow_errors import PromptCompileError
from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.author_runs_async import (
    create_author_run_event,
    get_author_run,
    update_author_run_status,
    upsert_author_run_artifact,
)
from rpg_backend.infrastructure.repositories.stories_async import get_story, update_story_draft


class AuthorWorkflowRunPersistence:
    async def persist_run_update(self, *, run_id: str, node_name: str, update: dict[str, Any]) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            run = await get_author_run(db, run_id)
            if run is None:
                return
            async with transactional(db):
                await update_author_run_status(
                    db,
                    run,
                    status=AuthorWorkflowStatus.RUNNING,
                    current_node=node_name,
                )
                await create_author_run_event(
                    db,
                    run_id=run_id,
                    node_name=node_name,
                    event_type=AuthorWorkflowEventType.NODE_COMPLETED,
                    payload_json={key: artifact_payload_from_state(value) for key, value in update.items()},
                )
                for artifact in build_persisted_artifacts_for_update(update):
                    await upsert_author_run_artifact(
                        db,
                        run_id=run_id,
                        artifact_type=artifact.artifact_type,
                        artifact_key=artifact.artifact_key,
                        payload_json=artifact.payload,
                    )

    async def record_run_node_event(
        self,
        *,
        run_id: str,
        node_name: str,
        event_type: str,
        payload_json: dict[str, Any] | None = None,
    ) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            run = await get_author_run(db, run_id)
            if run is None:
                return
            async with transactional(db):
                await update_author_run_status(
                    db,
                    run,
                    status=AuthorWorkflowStatus.RUNNING,
                    current_node=node_name,
                )
                await create_author_run_event(
                    db,
                    run_id=run_id,
                    node_name=node_name,
                    event_type=event_type,
                    payload_json=payload_json or {},
                )

    async def mark_run_node_started(
        self,
        *,
        run_id: str,
        node_name: str,
        payload_json: dict[str, Any] | None = None,
    ) -> None:
        await self.record_run_node_event(
            run_id=run_id,
            node_name=node_name,
            event_type=AuthorWorkflowEventType.NODE_STARTED,
            payload_json=payload_json,
        )

    async def complete_run(self, *, run_id: str, final_state: AuthorWorkflowState) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            run = await get_author_run(db, run_id)
            if run is None:
                return
            story = await get_story(db, run.story_id)
            async with transactional(db):
                if (
                    final_state.get("status") == AuthorWorkflowStatus.REVIEW_READY
                    and story is not None
                    and final_state.get("story_pack")
                ):
                    await update_story_draft(
                        db,
                        story,
                        title=final_state["overview"].title,
                        draft_pack_json=final_state["story_pack"],
                    )
                    await update_author_run_status(
                        db,
                        run,
                        status=AuthorWorkflowStatus.REVIEW_READY,
                        current_node=AuthorWorkflowNode.REVIEW_READY,
                        completed=True,
                    )
                    await create_author_run_event(
                        db,
                        run_id=run_id,
                        node_name=AuthorWorkflowNode.REVIEW_READY,
                        event_type=AuthorWorkflowEventType.RUN_COMPLETED,
                        payload_json={"status": AuthorWorkflowStatus.REVIEW_READY},
                    )
                    return

                latest_error = resolve_workflow_failure_errors(final_state)
                await update_author_run_status(
                    db,
                    run,
                    status=AuthorWorkflowStatus.FAILED,
                    current_node=AuthorWorkflowNode.WORKFLOW_FAILED,
                    error_code=AuthorWorkflowErrorCode.AUTHOR_WORKFLOW_FAILED,
                    error_message=latest_error[0],
                    completed=True,
                )
                await create_author_run_event(
                    db,
                    run_id=run_id,
                    node_name=AuthorWorkflowNode.WORKFLOW_FAILED,
                    event_type=AuthorWorkflowEventType.RUN_COMPLETED,
                    payload_json={"status": AuthorWorkflowStatus.FAILED, "errors": latest_error},
                )

    async def fail_run_with_prompt_compile_error(self, *, run_id: str, exc: PromptCompileError) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            run = await get_author_run(db, run_id)
            if run is None:
                return
            error_node_name = run.current_node or AuthorWorkflowNode.WORKFLOW_ROOT
            async with transactional(db):
                await update_author_run_status(
                    db,
                    run,
                    status=AuthorWorkflowStatus.FAILED,
                    current_node=run.current_node,
                    error_code=exc.error_code,
                    error_message=exc.errors[0] if exc.errors else str(exc),
                    completed=True,
                )
                await create_author_run_event(
                    db,
                    run_id=run_id,
                    node_name=error_node_name,
                    event_type=AuthorWorkflowEventType.RUN_EXCEPTION,
                    payload_json={
                        "message": str(exc),
                        "error_code": exc.error_code,
                        "errors": list(exc.errors),
                        "notes": list(exc.notes),
                    },
                )
                await upsert_author_run_artifact(
                    db,
                    run_id=run_id,
                    artifact_type=AuthorWorkflowArtifactType.WORKFLOW_ERROR,
                    artifact_key=error_node_name,
                    payload_json={
                        "error_code": exc.error_code,
                        "errors": list(exc.errors),
                        "notes": list(exc.notes),
                    },
                )

    async def fail_run_with_exception(self, *, run_id: str, exc: Exception) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            run = await get_author_run(db, run_id)
            if run is None:
                return
            error_node_name = run.current_node or AuthorWorkflowNode.WORKFLOW_ROOT
            async with transactional(db):
                await update_author_run_status(
                    db,
                    run,
                    status=AuthorWorkflowStatus.FAILED,
                    current_node=run.current_node,
                    error_code=AuthorWorkflowErrorCode.AUTHOR_WORKFLOW_EXCEPTION,
                    error_message=str(exc),
                    completed=True,
                )
                await create_author_run_event(
                    db,
                    run_id=run_id,
                    node_name=error_node_name,
                    event_type=AuthorWorkflowEventType.RUN_EXCEPTION,
                    payload_json={"message": str(exc)},
                )
