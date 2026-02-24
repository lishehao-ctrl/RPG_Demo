from __future__ import annotations

from typing import Literal

from app.modules.story.constants import AUTHOR_ASSIST_TASKS_V4

AuthorAssistTask = Literal[*AUTHOR_ASSIST_TASKS_V4]

ASSIST_MAX_SCENES = 4
ASSIST_MIN_SCENES = 4
ASSIST_ACTION_TYPES = {"study", "work", "rest", "date", "gift"}

LONG_WAIT_ASSIST_TASKS = frozenset({"story_ingest", "seed_expand", "continue_write"})
TWO_STAGE_ASSIST_TASKS = frozenset({"story_ingest", "seed_expand", "continue_write"})
ENDING_SYNC_ASSIST_TASKS = frozenset({
    "story_ingest",
    "seed_expand",
    "continue_write",
    "trim_content",
    "spice_branch",
    "tension_rebalance",
})
