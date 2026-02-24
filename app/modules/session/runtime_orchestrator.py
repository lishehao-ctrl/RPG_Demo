from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.models import Session as StorySession
from app.modules.narrative.ending_engine import resolve_run_ending
from app.modules.narrative.event_engine import advance_runtime_events
from app.modules.narrative.quest_engine import advance_quest_state, summarize_quest_for_narration
from app.modules.session import runtime_deps
from app.modules.session.story_runtime.pipeline import run_story_runtime_pipeline

STORY_FALLBACK_BUILTIN_TEXT = "[fallback] The scene advances quietly. Choose the next move."


def run_story_runtime_step(
    *,
    db: Session,
    sess: StorySession,
    choice_id: str | None,
    player_input: str | None,
    llm_runtime_getter,
    stage_emitter: Callable[[object], None] | None = None,
) -> dict:
    deps = runtime_deps.build_story_runtime_pipeline_deps(
        db=db,
        sess=sess,
        llm_runtime_getter=llm_runtime_getter,
        advance_quest_state=advance_quest_state,
        advance_runtime_events=advance_runtime_events,
        resolve_run_ending=resolve_run_ending,
        summarize_quest_for_narration=summarize_quest_for_narration,
        stage_emitter=stage_emitter,
    )
    return run_story_runtime_pipeline(
        db=db,
        sess=sess,
        choice_id=choice_id,
        player_input=player_input,
        fallback_builtin_text=STORY_FALLBACK_BUILTIN_TEXT,
        deps=deps,
        stage_emitter=stage_emitter,
    )
