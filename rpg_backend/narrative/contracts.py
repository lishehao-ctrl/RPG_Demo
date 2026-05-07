from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Cast / story / advisor primitives (unchanged from v1)
# --------------------------------------------------------------------------


class NPCLeverageOverNPC(BaseModel):
    """A leverage card one NPC holds over another NPC.

    Enables N×N political dynamics: NPC A may know something damaging
    about NPC B, which lets the LLM write scenes where A threatens B,
    and lets the player deliberately leak knowledge between NPCs to
    trigger inter-NPC conflict ("挑拨").
    """

    model_config = ConfigDict(extra="forbid")

    target_npc_id: str = Field(min_length=1, max_length=64)
    leverage: str = Field(min_length=1, max_length=200)


class CastMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=40)
    role: str = Field(min_length=1, max_length=80)
    relation_to_protagonist: str = Field(min_length=1, max_length=120)
    # Gauntlet-mode adversarial fields. None for story-mode templates.
    hidden_objective: str | None = Field(default=None, max_length=200)
    leverage_over_player: str | None = Field(default=None, max_length=200)
    # Inter-NPC leverage network. Each NPC may hold 0-3 leverages over
    # *other* NPCs, mirroring the existing leverage_over_player field
    # but pointed at the cast instead of the player. Backwards-compatible
    # default to empty list so legacy templates still parse cleanly.
    leverages_over_other_npcs: list[NPCLeverageOverNPC] = Field(
        default_factory=list, max_length=4,
    )


class PlayerGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=120)
    stakes: str = Field(min_length=1, max_length=160)


# --------------------------------------------------------------------------
# Player as cast — the player isn't a faceless "you" anymore. Every
# template ships 3-5 selectable role cards; picking a different card
# replays the same template as a different person, with their own
# hidden_objective + leverage cards + starting assets.
# --------------------------------------------------------------------------


class PlayerLeverageOverNPC(BaseModel):
    """A counter-card the player holds against a specific NPC.

    Surfaces in the turn prompt so the LLM knows the player has
    something to play back when an NPC threatens with leverage_over_player.
    """

    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(min_length=1, max_length=64)
    leverage: str = Field(min_length=1, max_length=200)


class PlayerRole(BaseModel):
    """One selectable identity the player can wear in a template.

    A template generates 3-5 roles; the player picks one when starting
    a session. Same template + different role = different story.
    """

    model_config = ConfigDict(extra="forbid")

    role_id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=24)
    public_persona: str = Field(min_length=1, max_length=200)
    hidden_objective: str = Field(min_length=1, max_length=200)
    leverages_over_npcs: list[PlayerLeverageOverNPC] = Field(default_factory=list, max_length=8)
    starting_assets: list[str] = Field(default_factory=list, max_length=4)


class FailureCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)  # short trigger name
    description: str = Field(min_length=1, max_length=200)  # readable rule


class NPCPulse(BaseModel):
    """Per-turn snapshot of how each NPC is shifting. Generated alongside
    each narrator beat. Front-end shows these as small chips between turns
    so the player feels their choices register."""

    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(min_length=1, max_length=64)
    state: str = Field(min_length=1, max_length=80)
    shift: Literal["warmer", "colder", "steady", "wary", "broken"] = "steady"
    # Optional 12-30 char causal attribution: WHY did this NPC just shift?
    # References a specific player action or narrative event from this turn.
    # Without it, pulse chips are mystery symbols — players can't connect
    # color change to their own choices.
    reason: str | None = Field(default=None, max_length=80)


class StoryOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=60)
    hint: str = Field(default="", max_length=120)


class InventoryDelta(BaseModel):
    """A narrator turn may emit a delta describing what objects/info the
    player gained or lost in this beat. Walked-on-read: the session's
    current inventory = role.starting_assets + sum(added) - sum(removed)
    over all narrator messages in order."""

    model_config = ConfigDict(extra="forbid")

    added: list[str] = Field(default_factory=list, max_length=4)
    removed: list[str] = Field(default_factory=list, max_length=4)
    reason: str = Field(default="", max_length=120)


class StoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ord: int = Field(ge=0)
    role: Literal["narrator", "player"]
    content: str = Field(min_length=1)
    options: list[StoryOption] = Field(default_factory=list)
    chosen_option_index: int | None = None
    # Optional per-turn NPC pulse — emitted by gauntlet-mode turns and
    # rendered as chips between story beats. None for story-mode runs
    # (or for player messages, which never have a pulse).
    npc_pulse: list[NPCPulse] = Field(default_factory=list)
    # Optional per-turn inventory delta. None on most turns (objects
    # don't change hands every beat); fires on real "物件交接" moments.
    inventory_delta: InventoryDelta | None = None
    # Optional inner monologue the player wrote alongside their action.
    # Only present on player messages. NPCs cannot read this — only
    # the LLM uses it to calibrate the inner-state register of
    # subsequent narration. Empty/missing on most turns.
    diary: str | None = Field(default=None, max_length=600)


class AdvisorMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ord: int = Field(ge=0)
    role: Literal["player", "advisor"]
    content: str = Field(min_length=1)


# --------------------------------------------------------------------------
# Template (the shareable story shell)
# --------------------------------------------------------------------------


TemplateVisibility = Literal["private", "unlisted", "public"]
Difficulty = Literal["story", "gauntlet"]
EndingTier = Literal["victory", "compromised", "collapsed"]
# Locale a template's narration / NPC dialogue is generated in. The
# field is set at template creation and is immutable thereafter — every
# session forking the same template inherits the same language. Adding
# a new locale requires extending this Literal AND adding a prompt-
# language branch in `engine.py`.
TemplateLanguage = Literal["zh", "en"]
DEFAULT_TEMPLATE_LANGUAGE: TemplateLanguage = "zh"


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
    # Gauntlet-mode shared scaffolding (lives on the template so all sessions
    # forking the same template fight the same fight). Always populated by
    # the opening engine; only ENFORCED when session.difficulty == "gauntlet".
    player_goals: list[PlayerGoal] = Field(default_factory=list)
    failure_conditions: list[FailureCondition] = Field(default_factory=list)
    # 3-5 selectable player identities. Each session picks one role at
    # start. Empty list on legacy templates created before this feature.
    player_role_options: list[PlayerRole] = Field(default_factory=list, max_length=6)
    visibility: TemplateVisibility = "private"
    # The locale narration / NPC dialogue is generated in. Pre-i18n
    # templates default to "zh" via the migration backfill.
    language: TemplateLanguage = DEFAULT_TEMPLATE_LANGUAGE
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
    player_goals: list[PlayerGoal] = Field(default_factory=list)
    failure_conditions: list[FailureCondition] = Field(default_factory=list)
    player_role_options: list[PlayerRole] = Field(default_factory=list)
    visibility: TemplateVisibility
    language: TemplateLanguage = DEFAULT_TEMPLATE_LANGUAGE
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
    difficulty: Difficulty = "story"
    # role_id of the PlayerRole picked from template.player_role_options.
    # None for legacy sessions or templates without role options.
    selected_player_role_id: str | None = None
    ending_label: str | None = None
    ending_subtitle: str | None = None
    ending_passage: str | None = None
    ending_tier: EndingTier | None = None
    early_terminated: bool = False
    failure_trigger: str | None = None
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
    difficulty: Difficulty = "story"
    # The actual PlayerRole the session is using (resolved from role_id),
    # surfaced for UI rendering. None on legacy sessions.
    player_role: PlayerRole | None = None
    ending_label: str | None = None
    ending_subtitle: str | None = None
    ending_tier: EndingTier | None = None
    early_terminated: bool = False
    created_at: str
    last_active_at: str


class Highlight(BaseModel):
    """One pivotal moment in a finished session, surfaced as a card on
    the post-game replay reel. The five highlights together form the
    'shareable summary' of how this run played out — what mattered, why
    it mattered, and where the LLM thinks the player decided their tier.
    """

    model_config = ConfigDict(extra="forbid")

    # Which narrator beat this highlight points at (ord of that message).
    # Always references a narrator beat the player actually saw.
    beat_ord: int = Field(ge=0)
    # Short title of the moment, shown as the card header. ≤30 chars.
    headline: str = Field(min_length=1, max_length=30)
    # The most dramatic 1-3 sentence chunk lifted from that beat's
    # narration, verbatim or near-verbatim. ≤400 chars after truncation.
    body_excerpt: str = Field(min_length=1, max_length=400)
    # The LLM's read on why this moment was pivotal — references the
    # player's choices, hidden_objective, leverage, or inventory in a
    # one-line analysis. ≤200 chars.
    why_pivotal: str = Field(min_length=1, max_length=200)


class BranchHypothetical(BaseModel):
    """One 'what-if' fork point identified by the LLM after a session
    finishes. Anchored to a specific narrator beat, showing what the
    player picked vs an alternate option, and the LLM's plausibility-
    grade prediction of which ending label the alternate path would
    have hit.

    These are not authoritative — the LLM is hypothesizing, not
    simulating. The alternate_ending_label must be in the closed
    ENDING_LABELS pool so the player sees it as "another tier-marked
    outcome they could have collected", not a free-form spoiler.
    """

    model_config = ConfigDict(extra="forbid")

    # Which narrator beat the branch forks from. Always references a
    # real narrator beat from this session.
    pivot_beat_ord: int = Field(ge=0)
    # Short summary of what the player actually did at this turn.
    chosen_path_summary: str = Field(min_length=1, max_length=80)
    # Short summary of the alternate move the player could have made.
    alternate_path_summary: str = Field(min_length=1, max_length=80)
    # The ending label the LLM predicts for the alternate path. Must
    # be one of the closed ENDING_LABELS values (validator drops misses).
    alternate_ending_label: str = Field(min_length=1, max_length=20)
    # Tier of that hypothetical ending — derived server-side from
    # alternate_ending_label so the UI can color-grade the card.
    alternate_ending_tier: EndingTier = "compromised"
    # 1-2 sentence narrative justification — why this alt path likely
    # leads to that label. ≤200 chars.
    rationale: str = Field(min_length=1, max_length=200)


class NarrativeEnding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40)
    subtitle: str = Field(min_length=1, max_length=80)
    passage: str = Field(min_length=1, max_length=4000)
    tier: EndingTier = "compromised"
    early_terminated: bool = False
    failure_trigger: str | None = None
    # Up to 5 pivotal moments from the run, surfaced as a post-game
    # highlight reel. Empty list on legacy sessions or if the
    # synthesize_highlights call failed (non-fatal).
    highlights: list[Highlight] = Field(default_factory=list, max_length=6)
    # Up to 3 hypothetical fork points showing alternate endings the
    # player could have hit. Drives replay intent: "you didn't take
    # these 2 paths, here's roughly what they'd have looked like."
    branches: list[BranchHypothetical] = Field(default_factory=list, max_length=4)


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
    player_goals: list[PlayerGoal] = Field(default_factory=list)
    player_role: PlayerRole | None = None
    turn_budget: int
    turn_count: int
    difficulty: Difficulty = "story"
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
    difficulty: Difficulty = "story"
    # Narration / NPC dialogue locale. Immutable after creation —
    # all sessions forking this template share the same language.
    language: TemplateLanguage = DEFAULT_TEMPLATE_LANGUAGE


class CreateTemplateResponse(BaseModel):
    """Returned when a user creates a new template.

    A session is auto-created so the creator can immediately start playing.
    """

    model_config = ConfigDict(extra="forbid")

    template: NarrativeTemplateSummary
    session: NarrativeSessionSummary
    opening: StoryMessage


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_budget: int = Field(default=12, ge=4, le=40)
    difficulty: Difficulty = "story"
    # Index into template.player_role_options. None or out-of-range
    # falls back to the first option (or no role at all if template
    # was created before player roles existed).
    player_role_index: int | None = Field(default=None, ge=0, le=10)


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
    # Optional inner monologue. Stored on the player message and fed to
    # the LLM as private context, never shown to NPC characters in the
    # fiction. Lets the player record what they're really thinking
    # while playing the role.
    diary: str | None = Field(default=None, max_length=600)


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
    # Oracle mode: advisor uses privileged info (NPC hidden_objectives,
    # pulse trends, unused leverage) to give the player a mood-appropriate
    # hint. Costs 1 turn from session.turn_budget. Off by default.
    oracle_mode: bool = False


class AdvisorAskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_message: AdvisorMessage
    advisor_message: AdvisorMessage
    # Filled when oracle_mode was true. Shows the new turn_budget so the
    # frontend can update the budget chip without a refetch.
    turn_budget_after: int | None = None
    # Marks the advisor reply as oracle so the UI can render it
    # differently (e.g. gold-tinted "情报").
    oracle_used: bool = False


class AdvisorHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: str
    messages: list[AdvisorMessage]
