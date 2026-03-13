from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rpg_backend.generator.author_workflow_models import (
    AuthorMemory,
    BeatDraft,
    BeatOverviewContext,
    BeatPrefixSummary,
    StoryOverview,
)
from rpg_backend.generator.author_workflow_validators import (
    build_author_memory,
    build_structured_prefix_summary,
    project_overview_for_beat_generation,
)


@dataclass(frozen=True)
class BeatGenerationContext:
    prefix_summary: BeatPrefixSummary
    author_memory: AuthorMemory
    overview_context: BeatOverviewContext
    last_accepted_beat: dict[str, Any] | None


def build_beat_generation_context(*, overview: StoryOverview, prior_beats: list[BeatDraft]) -> BeatGenerationContext:
    prefix_summary = build_structured_prefix_summary(prior_beats)
    author_memory = build_author_memory(prior_beats)
    overview_context = project_overview_for_beat_generation(overview)
    last_accepted_beat = (
        author_memory.recent_beats[-1].model_dump(mode="json")
        if author_memory.recent_beats
        else None
    )
    return BeatGenerationContext(
        prefix_summary=prefix_summary,
        author_memory=author_memory,
        overview_context=overview_context,
        last_accepted_beat=last_accepted_beat,
    )
