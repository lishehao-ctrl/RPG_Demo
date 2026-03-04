from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.domain.conflict_tags import NPCConflictTag

MoveBiasTag = Literal[
    "social",
    "stealth",
    "technical",
    "investigate",
    "support",
    "resource",
    "conflict",
    "mobility",
]

EndingShape = Literal["triumph", "pyrrhic", "uncertain", "sacrifice"]


class StorySpecBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    conflict: str = Field(min_length=1)
    required_event: str | None = None


class StorySpecNPC(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    motivation: str = Field(min_length=1)
    red_line: str = Field(min_length=1, max_length=160)
    conflict_tags: list[NPCConflictTag] = Field(min_length=1, max_length=3)


class StorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    premise: str = Field(min_length=1, max_length=400)
    tone: str = Field(min_length=1, max_length=120)
    stakes: str = Field(min_length=1, max_length=300)
    beats: list[StorySpecBeat] = Field(min_length=3, max_length=5)
    npcs: list[StorySpecNPC] = Field(min_length=3, max_length=5)
    scene_constraints: list[str] = Field(min_length=3, max_length=5)
    move_bias: list[MoveBiasTag] = Field(min_length=1, max_length=6)
    ending_shape: EndingShape

    def compact_summary(self) -> dict[str, object]:
        return {
            "title": self.title,
            "tone": self.tone,
            "ending_shape": self.ending_shape,
            "beat_titles": [beat.title for beat in self.beats],
            "npc_names": [npc.name for npc in self.npcs],
            "npc_red_lines": {npc.name: npc.red_line for npc in self.npcs},
            "npc_conflict_tags": {npc.name: list(npc.conflict_tags) for npc in self.npcs},
            "move_bias": list(self.move_bias),
        }
