from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class OpeningGuidanceView:
    intro_text: str
    goal_hint: str
    starter_prompts: tuple[str, str, str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "intro_text": self.intro_text,
            "goal_hint": self.goal_hint,
            "starter_prompts": list(self.starter_prompts),
        }


@dataclass(frozen=True)
class DraftPatchChange:
    target_type: Literal["story", "beat", "scene", "npc", "opening_guidance"]
    field: str
    value: str
    target_id: str | None = None


@dataclass(frozen=True)
class StoryDraftView:
    story_id: str
    title: str
    created_at: datetime
    draft_pack: dict[str, Any]
    latest_published_version: int | None = None
    latest_published_at: datetime | None = None
