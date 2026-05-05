from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Cast / story / advisor primitives (unchanged from v1)
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# Template (the shareable story shell)
# --------------------------------------------------------------------------


TemplateVisibility = Literal["private", "unlisted", "public"]


class NarrativeTemplate(BaseModel):
    """Full template record (used internally by the service)."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=80)
    owner_user_id: str = Field(min_length=1, max_length=80)
    seed: str = Field(min_length=1, max_length=4000)
    title: str = Field(min_length=1, max_length=120)
    cast: list[CastMember] = Field(min_length=2, max_length=8)
    advisor_persona: str = Field(min_length=1, max_length=200)
    opening_passage: str = Field(min_length=1, max_length=4000)
    opening_options: list[StoryOption] = Field(default_factory=list)
    visibility: TemplateVisibility = "private"
    play_count: int = Field(default=0, ge=0)
    created_at: str = Field(min_length=1)


class NarrativeTemplateSummary(BaseModel):
    """Public-facing template summary (for list pages and details)."""

    model_config = ConfigDict(extra="forbid")

    template_id: str
    owner_user_id: str
    seed: str
    title: str
    cast: list[CastMember]
    advisor_persona: str
    visibility: TemplateVisibility
    play_count: int
    created_at: str
    is_owner: bool = False


# --------------------------------------------------------------------------
# Session (one player's playthrough of a template)
# --------------------------------------------------------------------------


class NarrativeSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=80)
    template_id: str = Field(min_length=1, max_length=80)
    player_user_id: str = Field(min_length=1, max_length=80)
    turn_count: int = Field(ge=0)
    turn_budget: int = Field(default=12, ge=4, le=40)
    ending_label: str | None = None
    ending_subtitle: str | None = None
    ending_passage: str | None = None
    created_at: str
    last_active_at: str


class NarrativeSessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    template_id: str
    template_title: str
    template_seed: str
    player_user_id: str
    turn_count: int
    turn_budget: int = 12
    ending_label: str | None = None
    ending_subtitle: str | None = None
    created_at: str
    last_active_at: str


class NarrativeEnding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40)
    subtitle: str = Field(min_length=1, max_length=80)
    passage: str = Field(min_length=1, max_length=4000)


class EndingDistributionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    count: int


class EndingDistributionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    total_completed: int
    entries: list[EndingDistributionEntry]


class PublicReplayResponse(BaseModel):
    """A public, auth-free read of a completed session for sharing.

    Includes story messages, final ending, and the advisor sidechat (which
    is part of the unique 'how I felt while playing' shareable content).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    template_title: str
    template_seed: str
    cast: list[CastMember]
    advisor_persona: str
    turn_budget: int
    turn_count: int
    completed: bool
    ending: NarrativeEnding | None
    messages: list[StoryMessage]
    advisor_messages: list[AdvisorMessage]
    created_at: str


# --------------------------------------------------------------------------
# Request / response payloads
# --------------------------------------------------------------------------


class CreateTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: str = Field(min_length=1, max_length=4000)
    visibility: TemplateVisibility = "private"
    turn_budget: int = Field(default=12, ge=4, le=40)


class CreateTemplateResponse(BaseModel):
    """Returned when a user creates a new template.

    A session is auto-created so the creator can immediately start playing.
    """

    model_config = ConfigDict(extra="forbid")

    template: NarrativeTemplateSummary
    session: NarrativeSessionSummary
    opening: StoryMessage


class StartSessionResponse(BaseModel):
    """Returned when a user starts a fresh session on an existing template."""

    model_config = ConfigDict(extra="forbid")

    template: NarrativeTemplateSummary
    session: NarrativeSessionSummary
    opening: StoryMessage


class TemplateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NarrativeTemplateSummary]


class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NarrativeSessionSummary]


class UpdateTemplateVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: TemplateVisibility


class StoryHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: NarrativeTemplateSummary
    session: NarrativeSessionSummary
    messages: list[StoryMessage]


class AdvanceTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chosen_option_index: int | None = None
    free_input: str | None = Field(default=None, max_length=400)


class AdvanceTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_message: StoryMessage
    narrator_message: StoryMessage
    # Surfaced when this turn was the last of the budget — the engine has
    # already generated and persisted the ending. Frontend uses this to
    # render the ending screen without a follow-up GET.
    ending: NarrativeEnding | None = None
    is_complete: bool = False


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
