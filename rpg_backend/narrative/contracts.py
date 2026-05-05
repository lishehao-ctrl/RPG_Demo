from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CastMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=40)
    role: str = Field(min_length=1, max_length=80)
    relation_to_protagonist: str = Field(min_length=1, max_length=120)


class StoryOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=60)
    hint: str = Field(default="", max_length=120)


class StoryMessage(BaseModel):
    """A single beat of the main narrative stream.

    Each `narrator` message contains a passage plus the options offered to
    the player. The matching `player` message records what the player chose
    (or typed). This pairing is the unit of one turn.
    """

    model_config = ConfigDict(extra="forbid")

    ord: int = Field(ge=0)
    role: Literal["narrator", "player"]
    content: str = Field(min_length=1)
    options: list[StoryOption] = Field(default_factory=list)
    chosen_option_index: int | None = None


class AdvisorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ord: int = Field(ge=0)
    role: Literal["player", "advisor"]
    content: str = Field(min_length=1)


class NarrativeWorld(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str = Field(min_length=1, max_length=80)
    owner_user_id: str = Field(min_length=1, max_length=80)
    seed: str = Field(min_length=1, max_length=4000)
    title: str = Field(min_length=1, max_length=120)
    cast: list[CastMember] = Field(min_length=2, max_length=8)
    advisor_persona: str = Field(min_length=1, max_length=200)
    created_at: str = Field(min_length=1)


class NarrativeWorldSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str
    seed: str
    title: str
    cast: list[CastMember]
    advisor_persona: str
    turn_count: int = Field(ge=0)
    created_at: str


class CreateNarrativeWorldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: str = Field(min_length=1, max_length=4000)


class CreateNarrativeWorldResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world: NarrativeWorldSummary
    opening: StoryMessage


class StoryHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world: NarrativeWorldSummary
    messages: list[StoryMessage]


class AdvanceTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chosen_option_index: int | None = None
    free_input: str | None = Field(default=None, max_length=400)


class AdvanceTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_message: StoryMessage
    narrator_message: StoryMessage


class AdvisorAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=400)


class AdvisorAskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_message: AdvisorMessage
    advisor_message: AdvisorMessage


class AdvisorHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: str
    messages: list[AdvisorMessage]
