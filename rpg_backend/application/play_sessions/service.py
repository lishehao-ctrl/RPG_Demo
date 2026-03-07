from __future__ import annotations

from typing import Any, Callable

from rpg_backend.application.play_sessions.errors import (
    ProviderMisconfiguredError,
    SessionNotFoundError,
    StoryNotFoundError,
    StoryVersionNotFoundError,
)
from rpg_backend.application.play_sessions.models import (
    SessionCreateView,
    SessionHistoryTurnView,
    SessionHistoryView,
    SessionStepResult,
    SessionView,
)
from rpg_backend.application.story_draft import resolve_opening_guidance
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.infrastructure.repositories.sessions_async import (
    create_session,
    get_session as get_session_record,
    list_session_actions,
)
from rpg_backend.infrastructure.repositories.stories_async import get_story, get_story_version
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.runtime.service import RuntimeService


def build_state_summary(state: dict[str, Any]) -> dict[str, int]:
    values = state.get("values", {})
    return {
        "events": len(state.get("events", [])),
        "inventory": len(state.get("inventory", [])),
        "cost_total": int(values.get("cost_total", 0)),
    }


def build_runtime(provider_factory: Callable[[], Any]) -> RuntimeService:
    try:
        provider = provider_factory()
    except LLMProviderConfigError as exc:
        raise ProviderMisconfiguredError(message=f"llm provider misconfigured: {exc}") from exc
    return RuntimeService(provider)


async def create_play_session(
    *,
    db,
    story_id: str,
    version: int,
    provider_factory: Callable[[], Any],
) -> SessionCreateView:
    story = await get_story(db, story_id)
    if story is None:
        raise StoryNotFoundError(story_id=story_id)

    story_version = await get_story_version(db, story_id, version)
    if story_version is None:
        raise StoryVersionNotFoundError(story_id=story_id, version=version)

    pack = StoryPack.model_validate(story_version.pack_json)
    runtime = build_runtime(provider_factory)
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)
    async with transactional(db):
        session = await create_session(
            db,
            story_id=story_id,
            version=version,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state_json=state,
            beat_progress_json=beat_progress,
        )
    return SessionCreateView(
        session_id=session.id,
        story_id=story_id,
        version=version,
        scene_id=scene_id,
        state_summary=build_state_summary(state),
        opening_guidance=resolve_opening_guidance(pack),
    )


async def get_play_session(*, db, session_id: str, dev_mode: bool) -> SessionView:
    session = await get_session_record(db, session_id)
    if session is None:
        raise SessionNotFoundError(session_id=session_id)

    story_version = await get_story_version(db, session.story_id, session.version)
    if story_version is None:
        raise StoryVersionNotFoundError(story_id=session.story_id, version=session.version)
    pack = StoryPack.model_validate(story_version.pack_json)

    return SessionView(
        session_id=session.id,
        scene_id=session.current_scene_id,
        beat_progress=session.beat_progress_json,
        ended=bool(session.ended),
        state_summary=build_state_summary(session.state_json),
        opening_guidance=resolve_opening_guidance(pack),
        state=session.state_json if dev_mode else None,
    )


async def get_play_session_history(*, db, session_id: str) -> SessionHistoryView:
    session = await get_session_record(db, session_id)
    if session is None:
        raise SessionNotFoundError(session_id=session_id)

    actions = await list_session_actions(db, session_id)
    history = []
    for index, action in enumerate(actions, start=1):
        step_result = SessionStepResult.from_payload(action.response_json)
        history.append(
            SessionHistoryTurnView.from_step_result(
                index,
                step_result,
                ended=bool(session.ended and index == len(actions)),
            )
        )
    return SessionHistoryView(session_id=session.id, history=tuple(history))
