from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AxisKind = Literal["pressure", "resource", "relationship", "exposure", "time"]
StoryFunction = Literal["advance", "reveal", "stabilize", "detour", "pay_cost"]
BeatMilestoneKind = Literal["reveal", "exposure", "fracture", "concession", "containment", "commitment"]
AxisTemplateId = Literal[
    "external_pressure",
    "public_panic",
    "political_leverage",
    "resource_strain",
    "system_integrity",
    "ally_trust",
    "exposure_risk",
    "time_window",
]
AffordanceTag = Literal[
    "reveal_truth",
    "build_trust",
    "contain_chaos",
    "shift_public_narrative",
    "protect_civilians",
    "secure_resources",
    "unlock_ally",
    "pay_cost",
]


class FocusedBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_kernel: str = Field(min_length=1, max_length=220)
    setting_signal: str = Field(min_length=1, max_length=220)
    core_conflict: str = Field(min_length=1, max_length=220)
    tone_signal: str = Field(min_length=1, max_length=120)
    hard_constraints: list[str] = Field(default_factory=list, max_length=4)
    forbidden_tones: list[str] = Field(default_factory=list, max_length=4)


class CastMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    agenda: str = Field(min_length=1, max_length=220)
    red_line: str = Field(min_length=1, max_length=220)
    pressure_signature: str = Field(min_length=1, max_length=220)


class TruthItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    truth_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=220)
    importance: Literal["core", "optional"] = "core"


class EndingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=220)


class StoryBible(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    premise: str = Field(min_length=1, max_length=320)
    tone: str = Field(min_length=1, max_length=120)
    stakes: str = Field(min_length=1, max_length=240)
    style_guard: str = Field(min_length=1, max_length=220)
    cast: list[CastMember] = Field(min_length=3, max_length=5)
    world_rules: list[str] = Field(min_length=2, max_length=5)
    truth_catalog: list[TruthItem] = Field(min_length=1, max_length=8)
    ending_catalog: list[EndingItem] = Field(min_length=3, max_length=5)


class AxisDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: AxisKind
    min_value: int = 0
    max_value: int = Field(default=5, ge=1)
    starting_value: int = 0


class StanceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stance_id: str = Field(min_length=1)
    npc_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    min_value: int = -2
    max_value: int = 3
    starting_value: int = 0


class FlagDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    starting_value: bool = False


class StateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axes: list[AxisDefinition] = Field(min_length=2, max_length=6)
    stances: list[StanceDefinition] = Field(default_factory=list, max_length=5)
    flags: list[FlagDefinition] = Field(default_factory=list, max_length=8)


class AffordanceWeight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: AffordanceTag
    weight: int = Field(ge=1, le=3)


class BeatSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=220)
    focus_npcs: list[str] = Field(default_factory=list, max_length=3)
    conflict_npcs: list[str] = Field(default_factory=list, max_length=2)
    pressure_axis_id: str | None = None
    milestone_kind: BeatMilestoneKind = "reveal"
    route_pivot_tag: AffordanceTag | None = None
    required_truths: list[str] = Field(default_factory=list, max_length=4)
    required_events: list[str] = Field(default_factory=list, max_length=4)
    detour_budget: int = Field(default=1, ge=0, le=2)
    progress_required: int = Field(default=2, ge=1, le=3)
    return_hooks: list[str] = Field(min_length=1, max_length=3)
    affordances: list[AffordanceWeight] = Field(min_length=2, max_length=6)
    blocked_affordances: list[AffordanceTag] = Field(default_factory=list, max_length=4)


class ConditionBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_axes: dict[str, int] = Field(default_factory=dict)
    max_axes: dict[str, int] = Field(default_factory=dict)
    min_stances: dict[str, int] = Field(default_factory=dict)
    required_truths: list[str] = Field(default_factory=list)
    required_events: list[str] = Field(default_factory=list)
    required_flags: list[str] = Field(default_factory=list)


class RouteUnlockRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1)
    beat_id: str = Field(min_length=1)
    conditions: ConditionBlock = Field(default_factory=ConditionBlock)
    unlock_route_id: str = Field(min_length=1)
    unlock_affordance_tag: AffordanceTag


class EndingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str = Field(min_length=1)
    priority: int = Field(default=100, ge=1)
    conditions: ConditionBlock = Field(default_factory=ConditionBlock)


class AffordanceEffectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affordance_tag: AffordanceTag
    default_story_function: StoryFunction
    axis_deltas: dict[str, int] = Field(default_factory=dict)
    stance_deltas: dict[str, int] = Field(default_factory=dict)
    can_add_truth: bool = False
    can_add_event: bool = False


class RulePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_unlock_rules: list[RouteUnlockRule] = Field(default_factory=list, max_length=8)
    ending_rules: list[EndingRule] = Field(min_length=1, max_length=6)
    affordance_effect_profiles: list[AffordanceEffectProfile] = Field(min_length=2, max_length=12)


class RouteAffordancePackDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_unlock_rules: list[RouteUnlockRule] = Field(default_factory=list, max_length=8)
    affordance_effect_profiles: list[AffordanceEffectProfile] = Field(min_length=2, max_length=12)


class EndingRulesDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_rules: list[EndingRule] = Field(min_length=1, max_length=6)


class EndingIntentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str = Field(min_length=1)
    priority: int = Field(default=100, ge=1)
    axis_ids: list[str] = Field(default_factory=list, max_length=2)
    required_truth_ids: list[str] = Field(default_factory=list, max_length=2)
    required_event_ids: list[str] = Field(default_factory=list, max_length=2)
    required_flag_ids: list[str] = Field(default_factory=list, max_length=2)
    fallback: bool = False


class EndingIntentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_intents: list[EndingIntentSpec] = Field(min_length=1, max_length=6)


class EndingAnchorSuggestionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: Literal["collapse", "pyrrhic"]
    axis_ids: list[str] = Field(default_factory=list, max_length=2)
    required_truth_ids: list[str] = Field(default_factory=list, max_length=2)
    required_event_ids: list[str] = Field(default_factory=list, max_length=2)
    required_flag_ids: list[str] = Field(default_factory=list, max_length=2)


class EndingAnchorSuggestionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_anchor_suggestions: list[EndingAnchorSuggestionSpec] = Field(default_factory=list, max_length=2)


class RouteOpportunityTriggerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["truth", "axis", "stance", "flag", "event"]
    target_id: str = Field(min_length=1)
    min_value: int | None = None


class RouteOpportunityDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(min_length=1)
    unlock_route_id: str = Field(min_length=1)
    unlock_affordance_tag: AffordanceTag
    triggers: list[RouteOpportunityTriggerDraft] = Field(min_length=1, max_length=2)


class RouteOpportunityPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunities: list[RouteOpportunityDraft] = Field(default_factory=list, max_length=8)


class DesignBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focused_brief: FocusedBrief
    story_bible: StoryBible
    state_schema: StateSchema
    beat_spine: list[BeatSpec] = Field(min_length=1, max_length=6)
    rule_pack: RulePack


class OverviewCastDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=120)
    agenda: str = Field(min_length=1, max_length=220)
    red_line: str = Field(min_length=1, max_length=220)
    pressure_signature: str = Field(min_length=1, max_length=220)


class CastMemberSemanticsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    agenda_detail: str = Field(min_length=1, max_length=180)
    red_line_detail: str = Field(min_length=1, max_length=180)
    pressure_detail: str = Field(min_length=1, max_length=180)


class OverviewTruthDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=220)
    importance: Literal["core", "optional"] = "core"


class OverviewAxisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: AxisTemplateId
    story_label: str = Field(min_length=1, max_length=80)
    starting_value: int = Field(default=0, ge=0, le=3)


class OverviewFlagDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    starting_value: bool = False


class StoryFrameScaffoldDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_seed: str = Field(min_length=1, max_length=80)
    setting_frame: str = Field(min_length=1, max_length=180)
    protagonist_mandate: str = Field(min_length=1, max_length=220)
    opposition_force: str = Field(min_length=1, max_length=220)
    stakes_core: str = Field(min_length=1, max_length=220)
    tone: str = Field(min_length=1, max_length=120)
    world_rules: list[str] = Field(min_length=2, max_length=5)
    truths: list[OverviewTruthDraft] = Field(min_length=2, max_length=6)
    state_axis_choices: list[OverviewAxisDraft] = Field(min_length=2, max_length=5)
    flags: list[OverviewFlagDraft] = Field(default_factory=list, max_length=4)


class BeatDraftSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=220)
    focus_names: list[str] = Field(default_factory=list, max_length=3)
    conflict_pair: list[str] = Field(default_factory=list, max_length=2)
    pressure_axis_id: AxisTemplateId | None = None
    milestone_kind: BeatMilestoneKind = "reveal"
    route_pivot_tag: AffordanceTag | None = None
    required_truth_texts: list[str] = Field(default_factory=list, max_length=3)
    detour_budget: int = Field(default=1, ge=0, le=2)
    progress_required: int = Field(default=2, ge=1, le=3)
    return_hooks: list[str] = Field(min_length=1, max_length=3)
    affordance_tags: list[AffordanceTag] = Field(min_length=2, max_length=6)
    blocked_affordances: list[AffordanceTag] = Field(default_factory=list, max_length=4)


class BeatSkeletonSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_seed: str = Field(min_length=1, max_length=80)
    goal_seed: str = Field(min_length=1, max_length=180)
    focus_names: list[str] = Field(default_factory=list, max_length=3)
    conflict_pair: list[str] = Field(default_factory=list, max_length=2)
    pressure_axis_id: AxisTemplateId | None = None
    milestone_kind: BeatMilestoneKind = "reveal"
    route_pivot_tag: AffordanceTag | None = None
    required_truth_texts: list[str] = Field(default_factory=list, max_length=3)
    detour_budget: int = Field(default=1, ge=0, le=2)
    progress_required: int = Field(default=2, ge=1, le=3)
    affordance_tags: list[AffordanceTag] = Field(min_length=2, max_length=6)
    blocked_affordances: list[AffordanceTag] = Field(default_factory=list, max_length=4)


class BeatPlanSkeletonDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beats: list[BeatSkeletonSpec] = Field(min_length=2, max_length=4)


class StoryFrameDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    premise: str = Field(min_length=1, max_length=320)
    tone: str = Field(min_length=1, max_length=120)
    stakes: str = Field(min_length=1, max_length=240)
    style_guard: str = Field(min_length=1, max_length=220)
    world_rules: list[str] = Field(min_length=2, max_length=5)
    truths: list[OverviewTruthDraft] = Field(min_length=2, max_length=6)
    state_axis_choices: list[OverviewAxisDraft] = Field(min_length=2, max_length=5)
    flags: list[OverviewFlagDraft] = Field(default_factory=list, max_length=4)


class CastOverviewSlotDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_label: str = Field(min_length=1, max_length=80)
    public_role: str = Field(min_length=1, max_length=120)
    relationship_to_protagonist: str = Field(min_length=1, max_length=180)
    agenda_anchor: str = Field(min_length=1, max_length=220)
    red_line_anchor: str = Field(min_length=1, max_length=220)
    pressure_vector: str = Field(min_length=1, max_length=220)
    archetype_id: str | None = None
    relationship_dynamic_id: str | None = None
    counter_trait: str | None = None
    pressure_tell: str | None = None


class CastOverviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cast_slots: list[CastOverviewSlotDraft] = Field(min_length=3, max_length=5)
    relationship_summary: list[str] = Field(min_length=2, max_length=6)


class CastDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cast: list[OverviewCastDraft] = Field(min_length=3, max_length=5)


class BeatPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beats: list[BeatDraftSpec] = Field(min_length=2, max_length=4)


class AuthorBundleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_brief: str = Field(min_length=1, max_length=4000)


class AuthorPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_seed: str = Field(min_length=1, max_length=4000)
    random_seed: int | None = None


class AuthorPreviewFlashcard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: str = Field(min_length=1)
    kind: Literal["stable", "draft"]
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=220)


class AuthorLoadingCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: Literal[
        "theme",
        "tone",
        "structure",
        "cast_count",
        "beat_count",
        "working_title",
        "core_conflict",
        "generation_status",
        "token_budget",
    ]
    emphasis: Literal["stable", "draft", "live"]
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=220)


class AuthorPreviewTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_theme: str = Field(min_length=1)
    modifiers: list[str] = Field(default_factory=list, max_length=8)
    router_reason: str = Field(min_length=1)


class AuthorPreviewStrategies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_frame_strategy: str = Field(min_length=1)
    cast_strategy: str = Field(min_length=1)
    beat_plan_strategy: str = Field(min_length=1)


class AuthorPreviewStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cast_topology: str = Field(min_length=1)
    expected_npc_count: int = Field(ge=1)
    expected_beat_count: int = Field(ge=1)


class AuthorPreviewStory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    premise: str = Field(min_length=1, max_length=320)
    tone: str = Field(min_length=1, max_length=120)
    stakes: str = Field(min_length=1, max_length=240)


class AuthorPreviewCastSlotSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_label: str = Field(min_length=1, max_length=80)
    public_role: str = Field(min_length=1, max_length=120)


class AuthorPreviewBeatSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=220)
    milestone_kind: str = Field(min_length=1, max_length=32)


class AuthorPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(min_length=1)
    prompt_seed: str = Field(min_length=1, max_length=4000)
    focused_brief: FocusedBrief
    theme: AuthorPreviewTheme
    strategies: AuthorPreviewStrategies
    structure: AuthorPreviewStructure
    story: AuthorPreviewStory
    cast_slots: list[AuthorPreviewCastSlotSummary] = Field(default_factory=list, max_length=5)
    beats: list[AuthorPreviewBeatSummary] = Field(default_factory=list, max_length=4)
    flashcards: list[AuthorPreviewFlashcard] = Field(default_factory=list, max_length=16)
    stage: str = Field(min_length=1, max_length=64)


class AuthorJobProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=64)
    stage_index: int = Field(ge=1)
    stage_total: int = Field(ge=1)


class AuthorCacheMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_cache_enabled: bool = False
    cache_path_used: bool = False
    total_call_count: int = Field(ge=0)
    previous_response_call_count: int = Field(ge=0)
    total_input_characters: int = Field(ge=0)
    estimated_input_tokens_from_chars: int = Field(ge=0)
    provider_usage: dict[str, int] = Field(default_factory=dict)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_hit_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    cache_type: str | None = Field(default=None, max_length=32)
    billing_type: str | None = Field(default=None, max_length=32)
    cache_metrics_source: str = Field(min_length=1, max_length=80)


class AuthorJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_seed: str = Field(min_length=1, max_length=4000)
    random_seed: int | None = None
    preview_id: str | None = None


class AuthorJobStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: Literal["queued", "running", "completed", "failed"]
    prompt_seed: str = Field(min_length=1, max_length=4000)
    preview: AuthorPreviewResponse
    progress: AuthorJobProgress
    progress_snapshot: AuthorJobProgressSnapshot | None = None
    cache_metrics: AuthorCacheMetrics | None = None
    error: dict[str, str] | None = None


class AuthorStorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    one_liner: str = Field(min_length=1, max_length=220)
    premise: str = Field(min_length=1, max_length=320)
    tone: str = Field(min_length=1, max_length=120)
    theme: str = Field(min_length=1, max_length=80)
    npc_count: int = Field(ge=1)
    beat_count: int = Field(ge=1)


class AuthorJobResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    status: Literal["queued", "running", "completed", "failed"]
    summary: AuthorStorySummary | None = None
    bundle: DesignBundle | None = None
    progress_snapshot: AuthorJobProgressSnapshot | None = None
    cache_metrics: AuthorCacheMetrics | None = None


class AuthorJobProgressSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=64)
    stage_label: str = Field(min_length=1, max_length=120)
    stage_index: int = Field(ge=1)
    stage_total: int = Field(ge=1)
    completion_ratio: float = Field(ge=0, le=1)
    primary_theme: str = Field(min_length=1)
    cast_topology: str = Field(min_length=1)
    expected_npc_count: int = Field(ge=1)
    expected_beat_count: int = Field(ge=1)
    preview_title: str = Field(min_length=1, max_length=120)
    preview_premise: str = Field(min_length=1, max_length=320)
    flashcards: list[AuthorPreviewFlashcard] = Field(default_factory=list, max_length=16)
    loading_cards: list[AuthorLoadingCard] = Field(default_factory=list, max_length=12)


class AuthorTokenCostEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, max_length=120)
    currency: Literal["RMB"] = "RMB"
    input_price_per_million_tokens_rmb: float = Field(ge=0)
    output_price_per_million_tokens_rmb: float = Field(ge=0)
    session_cache_hit_multiplier: float = Field(ge=0)
    session_cache_creation_multiplier: float = Field(ge=0)
    uncached_input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    cache_creation_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_input_cost_rmb: float = Field(ge=0)
    estimated_output_cost_rmb: float = Field(ge=0)
    estimated_total_cost_rmb: float = Field(ge=0)
    notes: str | None = Field(default=None, max_length=240)
