from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rpg_backend.domain.conflict_tags import NPCConflictTag
from rpg_backend.generator.spec_schema import EndingShape, MoveBiasTag


class StoryOutlineBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=140)
    conflict: str = Field(min_length=1, max_length=140)
    required_event: str | None = Field(default=None, max_length=80)


class StoryOutlineNPC(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    role: str = Field(min_length=1, max_length=100)
    motivation: str = Field(min_length=1, max_length=140)
    red_line: str = Field(min_length=1, max_length=160)
    conflict_tags: list[NPCConflictTag] = Field(min_length=1, max_length=3)


class StorySpecOutline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=90)
    premise_core: str = Field(min_length=1, max_length=240)
    tone: str = Field(min_length=1, max_length=100)
    stakes_core: str = Field(min_length=1, max_length=220)
    beats: list[StoryOutlineBeat] = Field(min_length=4, max_length=4)
    npcs: list[StoryOutlineNPC] = Field(min_length=4, max_length=4)
    scene_constraints: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        min_length=4,
        max_length=4,
    )
    move_bias: list[MoveBiasTag] = Field(min_length=2, max_length=5)
    ending_shape: EndingShape

    @model_validator(mode="after")
    def _ensure_unique_beat_titles(self) -> "StorySpecOutline":
        normalized = [beat.title.strip().casefold() for beat in self.beats]
        if len(set(normalized)) != len(normalized):
            raise ValueError("beats titles must be unique (case-insensitive)")
        return self
