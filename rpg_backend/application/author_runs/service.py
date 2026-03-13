from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.application.author_runs.errors import AuthorRunNotFoundError, AuthorStoryNotReadyForPublishError
from rpg_backend.application.author_runs.models import (
    AuthorRunArtifactView,
    AuthorRunCreateView,
    AuthorRunEventView,
    AuthorRunView,
    AuthorStorySummaryView,
    AuthorStoryView,
    CreateAuthorRunCommand,
)
from rpg_backend.application.author_runs.workflow_graph import build_author_workflow_graph
from rpg_backend.application.author_runs.workflow_persistence import AuthorWorkflowRunPersistence
from rpg_backend.application.author_runs.workflow_state import build_initial_author_workflow_state
from rpg_backend.application.author_runs.workflow_vocabulary import (
    AuthorWorkflowArtifactType,
    AuthorWorkflowStatus,
)
from rpg_backend.generator.author_workflow_chains import BeatGenerationChain, StoryOverviewChain
from rpg_backend.generator.author_workflow_errors import PromptCompileError
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy, get_author_workflow_policy
from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.author_runs_async import (
    create_author_run,
    get_author_run,
    get_latest_author_run_for_story,
    list_author_run_artifacts,
    list_author_run_events,
    list_author_stories,
    upsert_author_run_artifact,
)
from rpg_backend.infrastructure.repositories.stories_async import create_story, get_latest_story_version, get_story


def _find_prompt_compile_error(exc: BaseException) -> PromptCompileError | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PromptCompileError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _placeholder_title(raw_brief: str) -> str:
    compact = " ".join((raw_brief or "").strip().split())
    if not compact:
        return "Author Run Draft"
    return compact[:80]


@dataclass
class _InlineScheduler:
    schedule_func: Callable[[str], Awaitable[None]]
    tasks: set[asyncio.Task]

    async def schedule(self, run_id: str) -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(self.schedule_func(run_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


class AuthorWorkflowService:
    def __init__(
        self,
        *,
        overview_chain_factory: Callable[..., StoryOverviewChain] | None = None,
        beat_chain_factory: Callable[..., BeatGenerationChain] | None = None,
        policy_factory: Callable[[], AuthorWorkflowPolicy] | None = None,
        run_persistence: AuthorWorkflowRunPersistence | None = None,
    ) -> None:
        self.overview_chain_factory = overview_chain_factory or StoryOverviewChain
        self.beat_chain_factory = beat_chain_factory or BeatGenerationChain
        self.policy_factory = policy_factory or get_author_workflow_policy
        self.run_persistence = run_persistence or AuthorWorkflowRunPersistence()
        self._tasks: set[asyncio.Task] = set()
        self.scheduler = _InlineScheduler(schedule_func=self._execute_run, tasks=self._tasks)

    async def create_run(self, *, db: AsyncSession, command: CreateAuthorRunCommand) -> AuthorRunCreateView:
        async with transactional(db):
            story = await create_story(db, title=_placeholder_title(command.raw_brief), pack_json={})
            run = await create_author_run(
                db,
                story_id=story.id,
                raw_brief=command.raw_brief,
                status=AuthorWorkflowStatus.PENDING,
            )
            await upsert_author_run_artifact(
                db,
                run_id=run.id,
                artifact_type=AuthorWorkflowArtifactType.RAW_BRIEF,
                artifact_key="",
                payload_json={"text": command.raw_brief},
            )
        await self.scheduler.schedule(run.id)
        return AuthorRunCreateView(story_id=story.id, run_id=run.id, status=run.status, created_at=run.created_at)

    async def rerun(self, *, db: AsyncSession, story_id: str, command: CreateAuthorRunCommand) -> AuthorRunCreateView:
        story = await get_story(db, story_id)
        if story is None:
            raise AuthorRunNotFoundError(run_id=story_id)
        async with transactional(db):
            run = await create_author_run(
                db,
                story_id=story_id,
                raw_brief=command.raw_brief,
                status=AuthorWorkflowStatus.PENDING,
            )
            await upsert_author_run_artifact(
                db,
                run_id=run.id,
                artifact_type=AuthorWorkflowArtifactType.RAW_BRIEF,
                artifact_key="",
                payload_json={"text": command.raw_brief},
            )
        await self.scheduler.schedule(run.id)
        return AuthorRunCreateView(story_id=story_id, run_id=run.id, status=run.status, created_at=run.created_at)

    async def get_run_view(self, *, db: AsyncSession, run_id: str) -> AuthorRunView:
        run = await get_author_run(db, run_id)
        if run is None:
            raise AuthorRunNotFoundError(run_id=run_id)
        artifacts = await list_author_run_artifacts(db, run.id)
        return AuthorRunView(
            run_id=run.id,
            story_id=run.story_id,
            status=run.status,
            current_node=run.current_node,
            raw_brief=run.raw_brief,
            error_code=run.error_code,
            error_message=run.error_message,
            created_at=run.created_at,
            updated_at=run.updated_at,
            completed_at=run.completed_at,
            artifacts=[
                AuthorRunArtifactView(
                    artifact_type=item.artifact_type,
                    artifact_key=item.artifact_key,
                    payload=item.payload_json,
                    updated_at=item.updated_at,
                )
                for item in artifacts
            ],
        )

    async def get_run_events_view(self, *, db: AsyncSession, run_id: str) -> list[AuthorRunEventView]:
        run = await get_author_run(db, run_id)
        if run is None:
            raise AuthorRunNotFoundError(run_id=run_id)
        return [
            AuthorRunEventView(
                event_id=item.id,
                node_name=item.node_name,
                event_type=item.event_type,
                payload=item.payload_json,
                created_at=item.created_at,
            )
            for item in await list_author_run_events(db, run_id)
        ]

    async def list_story_summaries(self, *, db: AsyncSession, limit: int) -> list[AuthorStorySummaryView]:
        stories = await list_author_stories(db, limit=limit)
        views: list[AuthorStorySummaryView] = []
        for story in stories:
            latest_run = await get_latest_author_run_for_story(db, story.id)
            latest_version = await get_latest_story_version(db, story.id)
            views.append(
                AuthorStorySummaryView(
                    story_id=story.id,
                    title=story.title,
                    created_at=story.created_at,
                    latest_run_id=latest_run.id if latest_run else None,
                    latest_run_status=latest_run.status if latest_run else None,
                    latest_run_current_node=latest_run.current_node if latest_run else None,
                    latest_run_updated_at=latest_run.updated_at if latest_run else None,
                    latest_published_version=latest_version.version if latest_version else None,
                    latest_published_at=latest_version.created_at if latest_version else None,
                )
            )
        return views

    async def get_story_view(self, *, db: AsyncSession, story_id: str) -> AuthorStoryView:
        story = await get_story(db, story_id)
        if story is None:
            raise AuthorRunNotFoundError(run_id=story_id)
        latest_run = await get_latest_author_run_for_story(db, story_id)
        latest_version = await get_latest_story_version(db, story.id)
        return AuthorStoryView(
            story_id=story.id,
            title=story.title,
            created_at=story.created_at,
            latest_run=await self.get_run_view(db=db, run_id=latest_run.id) if latest_run else None,
            latest_published_version=latest_version.version if latest_version else None,
            latest_published_at=latest_version.created_at if latest_version else None,
            draft_pack=story.draft_pack_json,
        )

    async def assert_publishable(self, *, db: AsyncSession, story: Any) -> None:
        latest_run = await get_latest_author_run_for_story(db, story.id)
        if latest_run is None or latest_run.status != AuthorWorkflowStatus.REVIEW_READY:
            raise AuthorStoryNotReadyForPublishError(
                story_id=story.id,
                latest_run_status=latest_run.status if latest_run else None,
            )

    async def _execute_run(self, run_id: str) -> None:
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            run = await get_author_run(db, run_id)
            if run is None:
                return
            story = await get_story(db, run.story_id)
            if story is None:
                return
            raw_brief = run.raw_brief

        policy = self.policy_factory()

        async def _mark_run_node_started(run_id_value: str, node_name: str, payload_json: dict[str, Any] | None) -> None:
            await self.run_persistence.mark_run_node_started(
                run_id=run_id_value,
                node_name=node_name,
                payload_json=payload_json,
            )

        async def _record_run_node_event(
            run_id_value: str,
            node_name: str,
            event_type: str,
            payload_json: dict[str, Any] | None,
        ) -> None:
            await self.run_persistence.record_run_node_event(
                run_id=run_id_value,
                node_name=node_name,
                event_type=event_type,
                payload_json=payload_json,
            )

        graph = build_author_workflow_graph(
            overview_chain_factory=self.overview_chain_factory,
            beat_chain_factory=self.beat_chain_factory,
            policy=policy,
            mark_run_node_started=_mark_run_node_started,
            record_run_node_event=_record_run_node_event,
        )

        final_state = build_initial_author_workflow_state(
            story_id=story.id,
            run_id=run.id,
            raw_brief=raw_brief,
        )

        try:
            async for mode, payload in graph.astream(final_state, stream_mode=["updates", "values"]):
                if mode == "updates":
                    for node_name, update in payload.items():
                        await self.run_persistence.persist_run_update(
                            run_id=run_id,
                            node_name=node_name,
                            update=update,
                        )
                else:
                    final_state = payload
        except PromptCompileError as exc:
            await self.run_persistence.fail_run_with_prompt_compile_error(run_id=run_id, exc=exc)
            return
        except Exception as exc:  # noqa: BLE001
            prompt_exc = _find_prompt_compile_error(exc)
            if prompt_exc is not None:
                await self.run_persistence.fail_run_with_prompt_compile_error(run_id=run_id, exc=prompt_exc)
            else:
                await self.run_persistence.fail_run_with_exception(run_id=run_id, exc=exc)
            return

        await self.run_persistence.complete_run(run_id=run_id, final_state=final_state)


author_workflow_service = AuthorWorkflowService()
