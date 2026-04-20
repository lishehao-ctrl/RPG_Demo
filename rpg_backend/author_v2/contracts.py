from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import RelationshipMoveFamily, StoryShellId

WorldlyDesireType = Literal[
    "love",
    "status",
    "money",
    "revenge",
    "freedom",
    "control",
    "identity",
]
SeedFitMode = Literal["direct_fit", "shell_fit", "out_of_scope"]
ConflictTemplateId = Literal[
    "wealth_banquet_will_flip",
    "wealth_engagement_sideswitch",
    "wealth_inheritance_evidence_drop",
    "wealth_private_heir_return",
    "office_board_vote_blackledger",
    "office_merger_scapegoat",
    "office_launch_contract_flip",
    "office_promotion_side_betrayal",
    "entertainment_awards_scandal",
    "entertainment_livestream_hotsearch_flip",
    "entertainment_variety_blackmail_flip",
    "campus_homecoming_recording",
    "campus_mentor_review_sideswitch",
    "campus_club_campaign_flip",
    "urban_supernatural_legacy_contract",
]
ArenaType = Literal[
    "family_banquet",
    "engagement_banquet",
    "will_reading",
    "board_vote",
    "merger_close",
    "launch_event",
    "promotion_review",
    "awards_backstage",
    "livestream_room",
    "variety_set",
    "homecoming_stage",
    "mentor_review",
    "club_event",
    "night_clubfront",
]
SecretClass = Literal[
    "will_evidence",
    "hidden_heir",
    "black_ledger",
    "contract_flip",
    "scandal_video",
    "old_recording",
    "legacy_contract_secret",
]
RelationshipGeometryId = Literal[
    "fiance_oldlove_lawyer",
    "heir_oldlove_secret_keeper",
    "boss_rival_legal",
    "power_circle_oldally",
    "idol_manager_ex",
    "scholarship_ex_recording",
    "legacy_danger_ally",
]
CostClass = Literal[
    "marriage_face",
    "inheritance_status",
    "career_position",
    "career_reputation",
    "public_reputation",
    "scholarship_future",
    "legacy_normal_life",
]
PublicBombFamily = Literal[
    "evidence_drop",
    "side_switch",
    "vote_reveal",
    "launch_crash",
    "hotsearch_flip",
    "recording_drop",
    "legacy_contract_exposure",
]
ProtagonistIdentityClass = Literal[
    "heiress_target",
    "project_lead",
    "industry_operator",
    "campus_core",
    "legacy_urban_outsider",
]
ToneBias = Literal["knife", "cold", "melodramatic", "wistful"]
RoutePreferenceBias = Literal["relationship", "side", "burst", "mixed"]
TemplateTier = Literal["hero", "light"]
ToneExampleSlot = Literal["hook", "route_promise", "bomb", "cost", "supporting"]
ToneSceneSlot = Literal["public_escalation", "private_aftermath"]
ToneExampleLayer = Literal["primary", "supporting", "fallout"]
DramaticBand = Literal["steady", "rising", "explosive", "aftermath"]
ToneReasonFamily = Literal["loss_position", "self_preserve", "old_debt", "opportunity_window", "blame_shift", "mixed"]
ToneSignalFamily = Literal["public_wave", "peer_spread", "institutional_shift", "relationship_pressure", "mixed"]
ToneCostFamily = Literal["face", "eligibility", "position", "relationship", "narrative_control", "mixed"]
ToneCadence = Literal["staccato", "slow_press", "broken", "contrast", "mixed"]
PlayLengthPresetId = Literal["5_8", "10_12", "12_15", "15_20", "20_25", "30_45"]
ExperienceBandId = Literal["5_8", "8_15", "15_25"]
ArcTemplateId = Literal["short_3", "compact_4", "standard_4", "long_5", "flagship_6", "super_flagship_8"]
SlotFunctionId = Literal[
    "lead_interest",
    "rival_interest",
    "hidden_ally",
    "public_witness",
    "secret_keeper",
    "supporting_pressure",
    "wildcard",
]
SegmentRoleId = Literal["opening", "misread", "pressure", "reversal", "reveal", "terminal"]
RelationshipSceneFrame = Literal["private", "semi_public", "public"]
TurnConfidence = Literal["high", "medium", "low"]
SuggestionLaneId = Literal["relationship", "side", "burst"]
NpcLoyaltyBias = Literal["self", "protagonist", "family", "institution", "chaos", "testing"]
NpcSceneIntent = Literal["protect", "test", "seduce", "corner", "deflect", "retaliate", "confess", "betray"]
NpcPublicPosture = Literal["composed", "brittle", "performative", "cornered"]
NpcPrimaryStake = Literal["position", "reputation", "eligibility", "lineage", "relationship", "narrative_control", "normal_life"]
NpcLossTrigger = Literal["public_humiliation", "seat_shift", "version_loss", "peer_rejection", "route_rejection", "debt_reopened"]
NpcPublicSurvivalMode = Literal["self_preserve", "cut_off", "hold_face", "claim_narrative", "align_early"]
NpcDebtMemoryBias = Literal["scorekeeping", "short_term", "flip_now", "late_payback"]
NpcPreferredLatentKind = Literal["relationship_debt", "public_wave", "secret_pressure", "npc_action"]
NpcDelayPreference = Literal["patient_burn", "quick_snap"]
NpcRegressionPayoff = Literal["public_shame", "status_loss", "secret_leak", "social_isolation"]
NpcGender = Literal["male", "female"]
SemanticQuestionStatus = Literal["open", "tightening", "flip", "resolved"]
SemanticRuleSceneFrame = Literal["private", "semi_public", "public", "any"]
SemanticRuleSegmentRole = Literal["opening", "misread", "pressure", "reversal", "reveal", "terminal", "any"]
SemanticControlAction = Literal["press", "redirect", "detonate", "none", "any"]
SemanticCostRouteKind = Literal["immediate_cost", "deferred_cost", "transferred_cost"]
CausalSourceKind = Literal["callback", "latent", "payoff"]
SemanticCostOwnerMode = Literal["target", "control_target", "rival", "focus", "route_target", "actor", "active"]
CostReturnQuestionFocus = Literal["who_pays", "who_takes_blame", "who_gets_chased"]
CostNarrativeDriver = Literal["primary", "secondary"]
CostNarrativeSubject = Literal["payer", "beneficiary", "blamed_party"]
CostPrimaryDriverPlayerOverrideMode = Literal["player_first"]
DivergenceFunctionRole = Literal["strike", "self_preserve", "debt_play", "wait_flip"]
ControlSignatureAction = Literal["press", "redirect", "detonate"]


class SeedSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_seed: str = Field(min_length=1, max_length=4000)
    protagonist_public_identity: str = Field(min_length=1, max_length=120)
    protagonist_hidden_need: str = Field(min_length=1, max_length=180)
    social_arena: str = Field(min_length=1, max_length=120)
    relationship_setup: str = Field(min_length=1, max_length=220)
    taboo_secret_type: str = Field(min_length=1, max_length=120)
    worldly_desire_type: WorldlyDesireType
    share_hook: str = Field(min_length=1, max_length=180)
    story_shell_id: StoryShellId
    desired_cast_count: int = Field(ge=3, le=7)


class SeedFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_shell_id: StoryShellId
    fit_mode: SeedFitMode
    arena_type: ArenaType
    secret_class: SecretClass
    relationship_geometry: RelationshipGeometryId
    cost_class: CostClass
    public_bomb_family: PublicBombFamily
    play_length_preset: PlayLengthPresetId
    protagonist_identity_class: ProtagonistIdentityClass
    tone_bias: ToneBias
    route_preference_bias: RoutePreferenceBias
    source_markers: list[str] = Field(default_factory=list, max_length=10)


class TemplateSpecBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: ConflictTemplateId
    shell_id: StoryShellId
    tier: TemplateTier
    allowed_arena_types: list[ArenaType] = Field(default_factory=list, min_length=1, max_length=4)
    allowed_secret_classes: list[SecretClass] = Field(default_factory=list, min_length=1, max_length=4)
    allowed_relationship_geometries: list[RelationshipGeometryId] = Field(default_factory=list, min_length=1, max_length=4)
    allowed_cost_classes: list[CostClass] = Field(default_factory=list, min_length=1, max_length=4)
    allowed_bomb_families: list[PublicBombFamily] = Field(default_factory=list, min_length=1, max_length=4)
    route_promise_verb_set: list[str] = Field(default_factory=list, min_length=3, max_length=6)
    target_archetype_mix: list[str] = Field(default_factory=list, min_length=2, max_length=4)
    arc_template_bias: ArcTemplateId | None = None
    relationship_setup_template: str = Field(min_length=1, max_length=260)
    share_hook_template: str = Field(min_length=1, max_length=220)
    route_promise_template: str = Field(min_length=1, max_length=260)
    bomb_moment_template: str = Field(min_length=1, max_length=260)
    cost_of_truth_template: str = Field(min_length=1, max_length=260)
    tone_example_pack: "TemplateToneExamplePack"


class ToneExampleLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_id: str = Field(min_length=1, max_length=80)
    slot: ToneExampleSlot
    layer: ToneExampleLayer = "primary"
    dramatic_band: DramaticBand = "steady"
    semantic_tag: "ToneExampleSemanticTag" = Field(default_factory=lambda: ToneExampleSemanticTag())
    text: str = Field(min_length=1, max_length=180)


class ToneSceneExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_id: str = Field(min_length=1, max_length=80)
    slot: ToneSceneSlot
    layer: ToneExampleLayer = "fallout"
    dramatic_band: DramaticBand = "rising"
    semantic_tag: "ToneExampleSemanticTag" = Field(default_factory=lambda: ToneExampleSemanticTag())
    text: str = Field(min_length=1, max_length=260)


class ToneExampleSemanticTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_family: ToneReasonFamily = "mixed"
    signal_family: ToneSignalFamily = "mixed"
    cost_family: ToneCostFamily = "mixed"
    cadence: ToneCadence = "mixed"


class TemplateToneExamplePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[ToneExampleLine] = Field(min_length=5, max_length=8)
    scenes: list[ToneSceneExample] = Field(min_length=2, max_length=2)


class CompiledToneExamplePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author_example_lines: list[ToneExampleLine] = Field(default_factory=list, max_length=4)
    author_example_scene: list[ToneSceneExample] = Field(default_factory=list, max_length=2)
    play_reaction_example_lines: list[ToneExampleLine] = Field(default_factory=list, max_length=4)
    play_supporting_example_lines: list[ToneExampleLine] = Field(default_factory=list, max_length=4)
    play_chain_example_lines: list[ToneExampleLine] = Field(default_factory=list, max_length=4)
    play_debt_example_lines: list[ToneExampleLine] = Field(default_factory=list, max_length=4)


class SegmentStyleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_families: list[ToneReasonFamily] = Field(default_factory=list, max_length=4)
    signal_families: list[ToneSignalFamily] = Field(default_factory=list, max_length=4)
    cost_families: list[ToneCostFamily] = Field(default_factory=list, max_length=4)
    cadence_order: list[ToneCadence] = Field(default_factory=list, max_length=4)
    shell_anchor_tokens: list[str] = Field(default_factory=list, max_length=6)
    explosive_boost: bool = False


class QuestionProgressPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_status_by_segment_role: dict[SegmentRoleId, SemanticQuestionStatus] = Field(default_factory=dict)
    key_segment_force_flip_if_no_trigger: bool = True
    key_segment_force_resolve_secret_exposure: int = Field(default=3, ge=0, le=6)
    key_segment_force_resolve_progress_threshold: int = Field(default=1, ge=0, le=4)


class QuestionArcSegmentPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    scene_question_id: str = Field(min_length=1, max_length=120)
    minimum_status: SemanticQuestionStatus = "open"
    key_segment_require_conversion_if_no_trigger: bool = True
    force_resolve_secret_exposure: int = Field(default=3, ge=0, le=6)
    force_resolve_progress_threshold: int = Field(default=1, ge=0, le=4)


class QuestionArcPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, QuestionArcSegmentPolicyV2] = Field(default_factory=dict)
    key_segment_roles: list[SegmentRoleId] = Field(default_factory=lambda: ["reveal", "terminal"], max_length=3)


class CostRoutingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=120)
    move_family: RelationshipMoveFamily
    control_action: SemanticControlAction = "any"
    scene_frame: SemanticRuleSceneFrame = "any"
    segment_role: SemanticRuleSegmentRole = "any"
    route_kind: SemanticCostRouteKind
    global_deltas: dict[str, int] = Field(default_factory=dict)
    target_relationship_deltas: dict[str, int] = Field(default_factory=dict)
    fallback_payoff_family: str = Field(default="mixed", min_length=1, max_length=80)
    deferred_kind: NpcPreferredLatentKind | None = None
    enable_callback: bool = False


class CostRoutingMatrixPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[CostRoutingRule] = Field(default_factory=list, min_length=1, max_length=80)
    public_scene_heat_bonus: int = Field(default=1, ge=0, le=3)
    key_segment_heat_bonus: int = Field(default=1, ge=0, le=3)
    fallback_global_delta_key: str = Field(default="scene_heat", min_length=1, max_length=80)
    fallback_global_delta_value: int = Field(default=1, ge=-6, le=6)
    fallback_target_relationship_delta_key: str = Field(default="tension", min_length=1, max_length=80)
    fallback_target_relationship_delta_value: int = Field(default=1, ge=-6, le=6)


class CallbackPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=120)
    move_family: RelationshipMoveFamily
    control_action: SemanticControlAction = "any"
    due_turn_min_offset: int = Field(default=1, ge=0, le=6)
    due_turn_max_offset: int = Field(default=2, ge=0, le=10)
    base_global_deltas: dict[str, int] = Field(default_factory=dict)
    base_target_relationship_deltas: dict[str, int] = Field(default_factory=dict)
    fallback_payoff_kind: NpcRegressionPayoff = "public_shame"
    enabled: bool = True


class CallbackPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_queue_size: int = Field(default=8, ge=1, le=12)
    per_turn_settle_cap: int = Field(default=1, ge=1, le=2)
    rules: list[CallbackPolicyRule] = Field(default_factory=list, min_length=1, max_length=80)


class CallbackCommitPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_queue_size: int = Field(default=8, ge=1, le=12)
    per_turn_settle_cap: int = Field(default=1, ge=1, le=2)
    rules: list[CallbackPolicyRule] = Field(default_factory=list, min_length=1, max_length=80)
    require_deferred_commit: bool = True
    require_state_commit_on_settle: bool = True


class CostReturnSegmentRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    max_return_turns: int = Field(default=3, ge=1, le=3)
    owner_priority_modes: list[SemanticCostOwnerMode] = Field(default_factory=list, min_length=1, max_length=4)
    scene_question_focus: CostReturnQuestionFocus = "who_pays"


class CostReturnPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, CostReturnSegmentRule] = Field(default_factory=dict)
    default_max_return_turns: int = Field(default=3, ge=1, le=3)
    default_owner_priority_modes: list[SemanticCostOwnerMode] = Field(default_factory=lambda: ["target", "rival", "focus"], min_length=1, max_length=4)
    default_scene_question_focus: CostReturnQuestionFocus = "who_pays"


class CostNarrativeBindingSegmentRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    due_cost_driver: CostNarrativeDriver = "secondary"
    due_primary_when_due: bool = False
    require_main_clause_payer_beneficiary: bool = True
    reason_family_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)


class CostNarrativeBindingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, CostNarrativeBindingSegmentRule] = Field(default_factory=dict)
    due_cost_forces_primary_driver: bool = True


class CostPrimaryDriverSegmentRuleV7(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    eligible_segment_roles: list[SegmentRoleId] = Field(default_factory=list, min_length=1, max_length=4)
    due_window_turns: int = Field(default=3, ge=1, le=3)
    player_override_mode: CostPrimaryDriverPlayerOverrideMode = "player_first"
    deferred_retry_bias: int = Field(default=1, ge=0, le=3)


class CostPrimaryDriverPolicyV7(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, CostPrimaryDriverSegmentRuleV7] = Field(default_factory=dict)
    due_cost_forces_primary_driver: bool = True


class CostEscalationLadderSegmentRuleV8(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    stage1_turn_offset: int = Field(default=1, ge=1, le=3)
    stage2_turn_offset: int = Field(default=2, ge=1, le=3)
    stage3_turn_offset: int = Field(default=3, ge=1, le=3)
    stage1_pressure_bonus: int = Field(default=1, ge=0, le=3)
    stage1_maturity_bonus: int = Field(default=1, ge=0, le=3)
    stage2_pressure_bonus: int = Field(default=2, ge=0, le=4)
    stage2_maturity_bonus: int = Field(default=2, ge=0, le=4)
    stage3_force_question_cost_focus: bool = True
    stage3_force_primary_driver: bool = True
    allow_player_defer_once: bool = True


class CostEscalationLadderPolicyV8(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, CostEscalationLadderSegmentRuleV8] = Field(default_factory=dict)
    enabled: bool = True


class CostVisibilitySegmentRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    max_return_turns: int = Field(default=3, ge=1, le=3)
    require_visible_owner: bool = True
    require_main_clause_subject: bool = True
    require_two_sided_exchange: bool = True
    min_payer_loss: int = Field(default=1, ge=1, le=3)
    min_beneficiary_gain: int = Field(default=1, ge=1, le=3)
    main_clause_subject_order: list[CostNarrativeSubject] = Field(
        default_factory=lambda: ["payer", "beneficiary", "blamed_party"],
        min_length=1,
        max_length=3,
    )


class CostVisibilityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, CostVisibilitySegmentRule] = Field(default_factory=dict)


class ControlSignatureRuleV8(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ControlSignatureAction
    expected_route_kind: SemanticCostRouteKind
    require_owner_beneficiary_split: bool = False
    require_pending_signal: bool = False
    require_immediate_impact: bool = False
    require_uncertainty_drop_signal: bool = False


class ControlSignaturePolicyV8(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_action: dict[ControlSignatureAction, ControlSignatureRuleV8] = Field(default_factory=dict)
    require_distinct_signatures: bool = True


class QuestionProgressSegmentRuleV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    minimum_status: SemanticQuestionStatus = "open"
    require_cost_focus_when_due: bool = True
    require_non_stall_advance: bool = True
    key_segment_force_flip_if_no_trigger: bool = True


class QuestionProgressPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, QuestionProgressSegmentRuleV2] = Field(default_factory=dict)


class RoleDivergenceSegmentRuleV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    min_distinct_functions: int = Field(default=2, ge=1, le=4)
    required_functions: list[DivergenceFunctionRole] = Field(
        default_factory=lambda: ["strike", "self_preserve"],
        min_length=1,
        max_length=4,
    )
    require_counter_crowd_reason_split: bool = True


class RoleDivergenceMatrixV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, RoleDivergenceSegmentRuleV2] = Field(default_factory=dict)


class RoleFunctionLexiconEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function_role: DivergenceFunctionRole
    verbs: list[str] = Field(default_factory=list, min_length=1, max_length=4)
    receiver_templates: list[str] = Field(default_factory=list, min_length=1, max_length=4)


class RoleFunctionLexiconSegmentRuleV8(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    counter_entries: list[RoleFunctionLexiconEntry] = Field(default_factory=list, min_length=1, max_length=8)
    crowd_entries: list[RoleFunctionLexiconEntry] = Field(default_factory=list, min_length=1, max_length=8)
    enforce_counter_crowd_slot_split: bool = True


class RoleFunctionLexiconPolicyV8(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, RoleFunctionLexiconSegmentRuleV8] = Field(default_factory=dict)


class UtilityWeightProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_hit_weight: int = Field(default=2, ge=1, le=6)
    stake_hit_weight: int = Field(default=1, ge=1, le=6)
    latent_pressure_weight: int = Field(default=1, ge=1, le=6)
    role_diversity_weight: int = Field(default=1, ge=1, le=6)
    utility_delta_weight: int = Field(default=1, ge=1, le=6)
    shell_bias_weight: int = Field(default=1, ge=0, le=4)
    shell_bias_cap: int = Field(default=3, ge=0, le=6)


class CostIntensityProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_role_multiplier: dict[SegmentRoleId, float] = Field(default_factory=dict)
    control_action_multiplier: dict[SemanticControlAction, float] = Field(default_factory=dict)
    shell_multiplier: dict[StoryShellId, float] = Field(default_factory=dict)
    payoff_family_multiplier: dict[NpcRegressionPayoff, float] = Field(default_factory=dict)
    latent_pressure_step_bonus: float = Field(default=0.04, ge=0, le=0.3)
    latent_pressure_bonus_cap: float = Field(default=0.24, ge=0, le=0.6)
    deferred_route_bonus: float = Field(default=0.1, ge=0, le=0.5)
    min_non_zero_delta: int = Field(default=1, ge=1, le=3)
    max_abs_delta_per_key: int = Field(default=3, ge=1, le=6)


class SegmentInterestPolicyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    dominant_reason_family: ToneReasonFamily = "mixed"
    reason_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)
    stake_priority: list[NpcPrimaryStake] = Field(default_factory=list, min_length=1, max_length=4)


class SegmentInterestPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, SegmentInterestPolicyItem] = Field(default_factory=dict)
    default_reason_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)
    default_stake_priority: list[NpcPrimaryStake] = Field(default_factory=list, min_length=1, max_length=4)


class RoleDivergenceSegmentRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    min_distinct_functions: int = Field(default=2, ge=1, le=4)
    require_counter_crowd_reason_split: bool = True
    counter_reason_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)
    crowd_reason_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)
    key_segment_required_pairs: list[SupportingReasonPair] = Field(default_factory=list, max_length=4)


class RoleDivergenceMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, RoleDivergenceSegmentRule] = Field(default_factory=dict)
    key_segment_roles: list[SegmentRoleId] = Field(default_factory=lambda: ["reveal", "terminal"], max_length=3)
    default_counter_reason_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)
    default_crowd_reason_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)


class StakeAxisPriorityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, list[NpcPrimaryStake]] = Field(default_factory=dict)
    default_priority: list[NpcPrimaryStake] = Field(default_factory=list, min_length=1, max_length=4)


class ReasonFamilyPriorityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_id: dict[str, list[ToneReasonFamily]] = Field(default_factory=dict)
    default_priority: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)


class SupportingReasonPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counter_reason: ToneReasonFamily
    crowd_reason: ToneReasonFamily


class SupportingDivergencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_reason_family_split: bool = True
    key_segment_roles: list[SegmentRoleId] = Field(default_factory=lambda: ["reveal", "terminal"], max_length=3)
    counter_reason_priority_by_segment_role: dict[SegmentRoleId, list[ToneReasonFamily]] = Field(default_factory=dict)
    crowd_reason_priority_by_segment_role: dict[SegmentRoleId, list[ToneReasonFamily]] = Field(default_factory=dict)
    key_segment_required_pairs: list[SupportingReasonPair] = Field(default_factory=list, min_length=1, max_length=4)


class CostOwnershipRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=120)
    move_family: RelationshipMoveFamily
    control_action: SemanticControlAction = "any"
    segment_role: SemanticRuleSegmentRole = "any"
    owner_mode: SemanticCostOwnerMode = "target"
    deferred_owner_mode: SemanticCostOwnerMode | None = None
    transferred_owner_mode: SemanticCostOwnerMode | None = None


class CostOwnershipPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[CostOwnershipRule] = Field(default_factory=list, min_length=1, max_length=80)
    fallback_owner_mode: SemanticCostOwnerMode = "target"


class CostOwnershipMatrixV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[CostOwnershipRule] = Field(default_factory=list, min_length=1, max_length=80)
    fallback_owner_mode: SemanticCostOwnerMode = "target"
    require_owner_commit: bool = True


class ShellPropagationEdgePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(min_length=1, max_length=120)
    from_node: str = Field(min_length=1, max_length=80)
    to_node: str = Field(min_length=1, max_length=80)
    anchor_token: str = Field(min_length=1, max_length=24)
    signal_family: ToneSignalFamily = "mixed"
    note: str = Field(default="", max_length=180)
    kind_hints: list[NpcPreferredLatentKind] = Field(default_factory=list, max_length=4)


class ShellPropagationGraphPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shell_id: StoryShellId
    edges: list[ShellPropagationEdgePolicy] = Field(default_factory=list, min_length=1, max_length=16)
    key_segment_preferred_edges: list[str] = Field(default_factory=list, max_length=8)


class PropagationPriorityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shell_id: StoryShellId
    edge_priority_by_segment_role: dict[SegmentRoleId, list[str]] = Field(default_factory=dict)
    signal_family_bias_by_segment_role: dict[SegmentRoleId, ToneSignalFamily] = Field(default_factory=dict)
    key_segment_require_edge_commit: bool = True


class ShellSignalGraphV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shell_id: StoryShellId
    edges: list[ShellPropagationEdgePolicy] = Field(default_factory=list, min_length=1, max_length=16)
    key_segment_preferred_edges: list[str] = Field(default_factory=list, max_length=8)


class PropagationPriorityBySegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shell_id: StoryShellId
    edge_priority_by_segment_role: dict[SegmentRoleId, list[str]] = Field(default_factory=dict)
    signal_family_bias_by_segment_role: dict[SegmentRoleId, ToneSignalFamily] = Field(default_factory=dict)
    key_segment_require_edge_commit: bool = True


class StyleRegisterSegmentRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_role: SegmentRoleId
    reason_families: list[ToneReasonFamily] = Field(default_factory=list, min_length=1, max_length=4)
    signal_families: list[ToneSignalFamily] = Field(default_factory=list, min_length=1, max_length=4)
    cost_families: list[ToneCostFamily] = Field(default_factory=list, min_length=1, max_length=4)
    cadence_order: list[ToneCadence] = Field(default_factory=list, min_length=1, max_length=4)
    shell_anchor_tokens: list[str] = Field(default_factory=list, max_length=6)
    require_reason_signal_main_clause_on_key_segment: bool = True


class StyleRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_segment_role: dict[SegmentRoleId, StyleRegisterSegmentRule] = Field(default_factory=dict)
    default_rule: StyleRegisterSegmentRule


class InvariantPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_question_progress: bool = True
    require_observable_cost: bool = True
    max_main_triggers_per_turn: int = Field(default=1, ge=1, le=2)
    require_key_segment_shell_anchor: bool = True
    require_divergence_reason_family_split: bool = True
    require_cost_ownership_committed: bool = True
    require_cost_return_within_window: bool = True
    require_cost_primary_driver_committed: bool = True
    require_cost_two_sided_exchange: bool = True
    require_cost_owner_visible: bool = True
    require_cost_owner_visible_main_clause: bool = True
    require_cost_linked_to_question: bool = True
    require_control_signature_distinct: bool = True
    require_propagation_edge_commit: bool = True
    key_segment_roles: list[SegmentRoleId] = Field(default_factory=lambda: ["reveal", "terminal"], max_length=3)
    fallback_global_delta_key: str = Field(default="scene_heat", min_length=1, max_length=80)
    fallback_global_delta_value: int = Field(default=1, ge=-6, le=6)
    trace_tag_prefix: str = Field(default="invariant", min_length=1, max_length=40)


class CausalContractRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=120)
    source_kind: CausalSourceKind
    required_kind: NpcPreferredLatentKind | Literal["any"] = "any"
    open_by_role: SegmentRoleId
    resolve_by_role: SegmentRoleId
    min_resolution_count: int = Field(default=1, ge=1, le=3)
    fail_safe_delta_key: str = Field(default="scene_heat", min_length=1, max_length=80)
    fail_safe_delta_value: int = Field(default=1, ge=-6, le=6)
    summary_hint: str = Field(default="", max_length=180)


class CausalContractPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[CausalContractRule] = Field(default_factory=list, min_length=1, max_length=12)
    force_resolve_on_terminal: bool = True
    max_open_rules: int = Field(default=6, ge=1, le=12)
    stale_pending_turns_threshold: int = Field(default=2, ge=1, le=8)
    stale_pending_global_delta_key: str = Field(default="scene_heat", min_length=1, max_length=80)
    stale_pending_global_delta_value: int = Field(default=1, ge=-6, le=6)
    stale_pending_max_escalations_per_rule: int = Field(default=2, ge=1, le=6)


class TurnSemanticStrategyPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_progress_policy: QuestionProgressPolicy
    question_progress_policy_v2: QuestionProgressPolicyV2
    question_arc_policy_v2: QuestionArcPolicyV2
    segment_interest_policy: SegmentInterestPolicy
    role_divergence_matrix: RoleDivergenceMatrix
    role_divergence_matrix_v2: RoleDivergenceMatrixV2
    stake_axis_priority: StakeAxisPriorityPolicy
    reason_family_priority: ReasonFamilyPriorityPolicy
    supporting_divergence_policy: SupportingDivergencePolicy
    cost_routing_matrix: CostRoutingMatrixPolicy
    cost_ownership_policy: CostOwnershipPolicy
    cost_ownership_matrix_v2: CostOwnershipMatrixV2
    callback_policy: CallbackPolicy
    callback_commit_policy_v2: CallbackCommitPolicyV2
    cost_return_policy: CostReturnPolicy
    cost_narrative_binding_policy: CostNarrativeBindingPolicy
    cost_primary_driver_policy_v7: CostPrimaryDriverPolicyV7
    cost_escalation_ladder_policy_v8: CostEscalationLadderPolicyV8
    cost_visibility_contract: CostVisibilityContract
    control_signature_policy_v8: ControlSignaturePolicyV8
    role_function_lexicon_policy_v8: RoleFunctionLexiconPolicyV8
    utility_weight_profile: UtilityWeightProfile
    cost_intensity_profile: CostIntensityProfile
    shell_propagation_graph: ShellPropagationGraphPolicy
    shell_signal_graph_v2: ShellSignalGraphV2
    propagation_priority_policy: PropagationPriorityPolicy
    propagation_priority_by_segment: PropagationPriorityBySegment
    style_register: StyleRegister
    invariant_policy: InvariantPolicy
    causal_contract_policy: CausalContractPolicy


class HeroTemplateSpec(TemplateSpecBase):
    tier: Literal["hero"] = "hero"


class LightTemplateSpec(TemplateSpecBase):
    tier: Literal["light"] = "light"


class UrbanPreviewBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(min_length=1)
    prompt_seed: str = Field(min_length=1, max_length=4000)
    fit_mode: SeedFitMode = "direct_fit"
    template_id: ConflictTemplateId
    seed_fingerprint: SeedFingerprint
    protagonist_public_identity: str = Field(min_length=1, max_length=120)
    protagonist_hidden_need: str = Field(min_length=1, max_length=180)
    social_arena: str = Field(min_length=1, max_length=120)
    relationship_setup: str = Field(min_length=1, max_length=220)
    taboo_secret: str = Field(min_length=1, max_length=180)
    worldly_desire_type: WorldlyDesireType
    share_hook: str = Field(min_length=1, max_length=180)
    hook: str = Field(min_length=1, max_length=220)
    route_promise: str = Field(min_length=1, max_length=220)
    bomb_moment: str = Field(min_length=1, max_length=220)
    cost_of_truth: str = Field(min_length=1, max_length=220)
    play_length_preset: PlayLengthPresetId
    cast_count_target: int = Field(ge=3, le=7)
    experience_band: ExperienceBandId
    story_shell_id: StoryShellId
    route_target_count: int = Field(ge=2, le=4)
    target_gender_pref: NpcGender | None = None


class PreviewSynthesisDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook: str = Field(min_length=1, max_length=220)
    bomb_moment: str = Field(min_length=1, max_length=220)
    cost_of_truth: str = Field(min_length=1, max_length=220)
    protagonist_public_identity: str | None = Field(default=None, min_length=1, max_length=120)
    protagonist_hidden_need: str | None = Field(default=None, min_length=1, max_length=180)
    social_arena: str | None = Field(default=None, min_length=1, max_length=120)
    relationship_setup: str | None = Field(default=None, min_length=1, max_length=220)
    taboo_secret: str | None = Field(default=None, min_length=1, max_length=180)
    share_hook: str | None = Field(default=None, min_length=1, max_length=180)


class BlueprintEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protagonist_public_identity: str | None = Field(default=None, max_length=120)
    protagonist_hidden_need: str | None = Field(default=None, max_length=180)
    social_arena: str | None = Field(default=None, max_length=120)
    relationship_setup: str | None = Field(default=None, max_length=220)
    taboo_secret: str | None = Field(default=None, max_length=180)
    route_promise: str | None = Field(default=None, max_length=220)
    play_length_preset: PlayLengthPresetId | None = None
    cast_count_target: int | None = Field(default=None, ge=3, le=7)
    experience_band: ExperienceBandId | None = None
    story_shell_id: StoryShellId | None = None
    bomb_moment: str | None = Field(default=None, max_length=220)
    target_gender_pref: NpcGender | None = None


class AcceptedBlueprint(UrbanPreviewBlueprint):
    accepted_id: str = Field(min_length=1)


class CastSlotPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=1)
    slot_function: SlotFunctionId
    public_role_hint: str = Field(min_length=1, max_length=120)
    chemistry_hook: str = Field(min_length=1, max_length=180)
    danger_hook: str = Field(min_length=1, max_length=180)
    secret_pressure: str = Field(min_length=1, max_length=180)
    public_mask: str = Field(min_length=1, max_length=180)
    route_eligible: bool = False


class IPCharacterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ip_character_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=80)
    portrait_asset: str = Field(min_length=1, max_length=160)
    charisma_hook: str = Field(min_length=1, max_length=180)
    danger_hook: str = Field(min_length=1, max_length=180)
    speech_pattern: str = Field(min_length=1, max_length=180)
    gender: NpcGender
    is_adult: bool = True
    worldly_desire_type: WorldlyDesireType
    taboo_triggers: list[str] = Field(default_factory=list, max_length=6)
    persona_traits: list[str] = Field(default_factory=list, max_length=8)
    catchphrase_pool: list[str] = Field(default_factory=list, max_length=6)
    voice_register_tags: list[str] = Field(default_factory=list, max_length=8)
    secret_affinity_tags: list[str] = Field(default_factory=list, max_length=8)
    shareable_labels: list[str] = Field(default_factory=list, max_length=6)
    compatible_slot_functions: list[SlotFunctionId] = Field(default_factory=list, min_length=1, max_length=6)
    compatible_shells: list[StoryShellId] = Field(default_factory=list, min_length=1, max_length=5)
    disallowed_with: list[str] = Field(default_factory=list, max_length=6)


class StoryRoleBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=1)
    ip_character_id: str = Field(min_length=1)
    role_label: str = Field(min_length=1, max_length=120)
    chemistry_hook: str = Field(min_length=1, max_length=180)
    danger_hook: str = Field(min_length=1, max_length=180)
    public_mask: str = Field(min_length=1, max_length=180)
    secret_pressure: str = Field(min_length=1, max_length=180)
    relationship_to_protagonist: str = Field(min_length=1, max_length=180)
    route_eligible: bool = False


class CastSelectionChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=1)
    candidate_index: int = Field(ge=0, le=31)
    selection_reason: str = Field(min_length=1, max_length=220)


class CastSelectionDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selections: list[CastSelectionChoice] = Field(default_factory=list, min_length=1, max_length=7)


class FrozenSlotCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(ge=0, le=31)
    ip_character_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    gender: NpcGender
    score: float = Field(ge=-8.0, le=16.0)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    persona_traits: list[str] = Field(default_factory=list, max_length=4)
    voice_register_tags: list[str] = Field(default_factory=list, max_length=4)
    secret_affinity_tags: list[str] = Field(default_factory=list, max_length=4)


class FrozenCandidatePool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=80)
    by_slot: dict[str, list[FrozenSlotCandidate]] = Field(default_factory=dict)


class AuthorDecisionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: ConflictTemplateId
    template_rule_hits: list[str] = Field(default_factory=list, max_length=16)
    template_axis_hits: list[str] = Field(default_factory=list, max_length=16)
    template_hint_hits: list[str] = Field(default_factory=list, max_length=16)
    frozen_candidate_pool: FrozenCandidatePool | None = None


class NpcDramaProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1)
    public_role: str = Field(min_length=1, max_length=120)
    archetype_label: str = Field(min_length=1, max_length=80)
    charisma_hook: str = Field(min_length=1, max_length=180)
    danger_hook: str = Field(min_length=1, max_length=180)
    speech_pattern: str = Field(min_length=1, max_length=180)
    public_mask: str = Field(min_length=1, max_length=180)
    private_need: str = Field(min_length=1, max_length=180)
    status_need: str = Field(min_length=1, max_length=180)
    fear: str = Field(min_length=1, max_length=180)
    shame_trigger: str = Field(min_length=1, max_length=180)
    breaking_point: str = Field(min_length=1, max_length=180)
    loyalty_bias: NpcLoyaltyBias
    secret_owner_ids: list[str] = Field(default_factory=list, max_length=6)
    history_tags: list[str] = Field(default_factory=list, max_length=8)
    line_they_wont_cross: str = Field(min_length=1, max_length=180)


class NpcStrategicIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1)
    primary_stake: NpcPrimaryStake
    loss_trigger: NpcLossTrigger
    opportunism_target_ids: list[str] = Field(default_factory=list, max_length=3)
    public_survival_mode: NpcPublicSurvivalMode
    debt_memory_bias: NpcDebtMemoryBias
    preferred_latent_kind: NpcPreferredLatentKind = "relationship_debt"
    sensitive_latent_kind: NpcPreferredLatentKind = "public_wave"
    delay_preference: NpcDelayPreference = "quick_snap"
    regression_payoff: NpcRegressionPayoff = "public_shame"
    protect_target_ids: list[str] = Field(default_factory=list, max_length=3)
    sacrifice_target_ids: list[str] = Field(default_factory=list, max_length=3)


class BoundIPCastMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=80)
    slot_id: str = Field(min_length=1)
    slot_function: SlotFunctionId
    portrait_asset: str = Field(min_length=1, max_length=160)
    charisma_hook: str = Field(min_length=1, max_length=180)
    danger_hook: str = Field(min_length=1, max_length=180)
    speech_pattern: str = Field(min_length=1, max_length=180)
    gender: NpcGender
    public_role: str = Field(min_length=1, max_length=120)
    public_mask: str = Field(min_length=1, max_length=180)
    secret_pressure: str = Field(min_length=1, max_length=180)
    relationship_to_protagonist: str = Field(min_length=1, max_length=180)
    shareable_labels: list[str] = Field(default_factory=list, max_length=6)
    route_eligible: bool = False
    is_route_target: bool = False
    selection_reason: str = Field(default="", max_length=220)
    drama_profile: NpcDramaProfile
    strategic_intent: NpcStrategicIntent


class SegmentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    segment_role: SegmentRoleId
    focus_target_ids: list[str] = Field(default_factory=list, max_length=2)
    rival_target_ids: list[str] = Field(default_factory=list, max_length=2)
    allocated_secret_ids: list[str] = Field(default_factory=list, max_length=3)
    entry_contract: str = Field(min_length=1, max_length=220)
    exit_contract: str = Field(min_length=1, max_length=220)
    handoff_contract: str = Field(min_length=1, max_length=220)
    is_terminal: bool = False
    progress_required: int = Field(default=2, ge=1, le=8)
    segment_turn_floor: int = Field(default=6, ge=1, le=12)
    allowed_move_families: list[RelationshipMoveFamily] = Field(default_factory=list, min_length=2, max_length=6)
    venue_id: str = Field(min_length=1, max_length=120)


class SegmentPlaybook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    scene_goal: str = Field(min_length=1, max_length=220)
    emotional_goal: str = Field(min_length=1, max_length=220)
    move_priorities: list[RelationshipMoveFamily] = Field(min_length=2, max_length=6)
    public_pressure_cue: str = Field(min_length=1, max_length=220)
    private_pressure_cue: str = Field(min_length=1, max_length=220)
    progression_rule_summary: str = Field(min_length=1, max_length=220)
    suggestion_lanes: list["SegmentSuggestionLane"] = Field(default_factory=list, max_length=3)
    render_cues: list[str] = Field(default_factory=list, min_length=2, max_length=5)
    template_tone_example_lines: list[ToneExampleLine] = Field(default_factory=list, max_length=4)
    template_tone_scene_examples: list[ToneSceneExample] = Field(default_factory=list, max_length=2)
    tone_example_pack: CompiledToneExamplePack = Field(default_factory=CompiledToneExamplePack)
    segment_style_profile: SegmentStyleProfile = Field(default_factory=SegmentStyleProfile)
    scene_active_cap: int = Field(default=3, ge=1, le=3)


class SegmentPlaybookDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_pressure_cue: str | None = Field(default=None, min_length=1, max_length=220)
    private_pressure_cue: str | None = Field(default=None, min_length=1, max_length=220)
    progression_rule_summary: str | None = Field(default=None, min_length=1, max_length=220)
    render_cues: list[str] | None = Field(default=None, min_length=2, max_length=5)


class VoiceAtom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    intent_tag: str = Field(min_length=1, max_length=80)
    line_stub: str = Field(min_length=1, max_length=220)
    catchphrase_hint: str | None = Field(default=None, max_length=60)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=6)
    weight: float = Field(default=0.5, ge=0.05, le=1.0)
    style_tags: list[str] = Field(default_factory=list, max_length=8)


class VoiceAtomDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_id: str = Field(min_length=1, max_length=120)
    line_stub: str = Field(min_length=1, max_length=220)
    catchphrase_hint: str | None = Field(default=None, max_length=60)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=6)
    weight: float | None = Field(default=None, ge=0.05, le=1.0)
    style_tags: list[str] = Field(default_factory=list, max_length=8)


class VoiceAtomsDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_atom_deltas_by_character: dict[str, list[VoiceAtomDelta]] = Field(default_factory=dict)


BeatDeltaSource = Literal["author_initial", "runtime_rollover"]
BeatDeltaJobStatus = Literal["idle", "scheduled", "ready", "applied", "failed", "timeout", "ignored"]


class BeatDeltaKernel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kernel_id: str = Field(min_length=1, max_length=80)
    story_shell_id: StoryShellId
    template_id: ConflictTemplateId
    route_promise_anchor: str = Field(min_length=1, max_length=220)
    bomb_moment_anchor: str = Field(min_length=1, max_length=220)
    cost_of_truth_anchor: str = Field(min_length=1, max_length=220)
    protagonist_need_anchor: str = Field(min_length=1, max_length=180)
    route_target_ids: list[str] = Field(default_factory=list, max_length=4)
    semantic_anchor_tokens: list[str] = Field(default_factory=list, max_length=8)
    character_voice_axes: dict[str, str] = Field(default_factory=dict)


class BeatDeltaTurnCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directive: str = Field(default="", max_length=220)
    lane_focus: list[SuggestionLaneId] = Field(default_factory=list, max_length=3)
    move_focus: list[RelationshipMoveFamily] = Field(default_factory=list, max_length=4)
    voice_focus_character_ids: list[str] = Field(default_factory=list, max_length=3)


class BeatDeltaMicroSimHintBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preferred_actor_ids: list[str] = Field(default_factory=list, max_length=3)
    reason_family_hints: dict[str, str] = Field(default_factory=dict)
    action_family_hints: dict[str, str] = Field(default_factory=dict)
    summary: str = Field(default="", max_length=220)


class BeatDeltaComposePayloadHintBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style_case_bucket_ids: list[str] = Field(default_factory=list, max_length=4)
    key_cues: list[str] = Field(default_factory=list, max_length=6)
    cue_summary: str = Field(default="", max_length=220)


class BeatDeltaPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=80)
    source: BeatDeltaSource = "runtime_rollover"
    beat_index: int = Field(default=0, ge=0)
    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    move_priority_boosts: dict[RelationshipMoveFamily, float] = Field(default_factory=dict)
    progression_bias_summary: str = Field(default="", max_length=220)
    render_cue_bias: list[str] = Field(default_factory=list, max_length=5)
    lane_objective_bias_by_lane: dict[SuggestionLaneId, str] = Field(default_factory=dict)
    lane_target_bias_by_lane: dict[SuggestionLaneId, list[str]] = Field(default_factory=dict)
    voice_atom_weight_bias_by_character: dict[str, dict[str, float]] = Field(default_factory=dict)
    normal_turn_card: BeatDeltaTurnCard = Field(default_factory=BeatDeltaTurnCard)
    burst_turn_card: BeatDeltaTurnCard = Field(default_factory=BeatDeltaTurnCard)
    micro_sim_hint_bundle: BeatDeltaMicroSimHintBundle = Field(default_factory=BeatDeltaMicroSimHintBundle)
    compose_payload_hint_bundle: BeatDeltaComposePayloadHintBundle = Field(default_factory=BeatDeltaComposePayloadHintBundle)


class PlayQualityTuningProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_bias_low_confidence: float = Field(default=0.62, ge=0.0, le=1.0)
    control_bias_opening_force_until_turn_index: int = Field(default=1, ge=0, le=4)
    control_bias_segment_lane: dict[SegmentRoleId, SuggestionLaneId] = Field(
        default_factory=lambda: {
            "opening": "side",
            "misread": "side",
            "pressure": "burst",
            "reversal": "burst",
        }
    )
    control_bias_soft_moves: list[RelationshipMoveFamily] = Field(
        default_factory=lambda: ["comfort", "flirt", "ally_with"],
        min_length=1,
        max_length=6,
    )
    control_bias_leverage_bonus: float = Field(default=3.0, ge=0.0, le=6.0)
    intent_llm_high_risk_segment_roles: list[SegmentRoleId] = Field(
        default_factory=lambda: ["reveal", "terminal"],
        min_length=1,
        max_length=4,
    )
    intent_llm_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    intent_llm_min_semantic_clause_count: int = Field(default=3, ge=1, le=4)
    intent_llm_scene_heat_threshold: int = Field(default=6, ge=0, le=6)
    intent_llm_secret_exposure_threshold: int = Field(default=5, ge=0, le=6)
    micro_sim_llm_high_risk_segment_roles: list[SegmentRoleId] = Field(
        default_factory=lambda: ["reveal", "terminal"],
        min_length=1,
        max_length=4,
    )
    micro_sim_llm_scene_heat_threshold: int = Field(default=6, ge=0, le=6)
    micro_sim_llm_secret_exposure_threshold: int = Field(default=6, ge=0, le=6)
    normal_style_case_max: int = Field(default=2, ge=1, le=3)
    key_burst_style_case_max: int = Field(default=3, ge=1, le=4)
    normal_supporting_payload_limit: int = Field(default=1, ge=0, le=2)
    key_burst_supporting_payload_limit: int = Field(default=2, ge=0, le=3)
    normal_consequence_tag_limit: int = Field(default=3, ge=1, le=6)
    key_burst_consequence_tag_limit: int = Field(default=6, ge=2, le=10)
    normal_shell_token_limit: int = Field(default=5, ge=1, le=8)
    key_burst_shell_token_limit: int = Field(default=8, ge=2, le=10)
    key_burst_pass2_enabled: bool = True
    key_burst_pass2_high_risk_segment_roles: list[SegmentRoleId] = Field(
        default_factory=lambda: ["reveal", "terminal"],
        min_length=1,
        max_length=4,
    )
    key_burst_pass2_scene_heat_threshold: int = Field(default=6, ge=0, le=6)
    key_burst_pass2_secret_exposure_threshold: int = Field(default=6, ge=0, le=6)
    key_burst_pass2_route_lock_threshold: int = Field(default=5, ge=0, le=6)
    key_burst_pass2_max_retry: int = Field(default=1, ge=0, le=2)
    key_burst_pass2_max_output_tokens: int = Field(default=280, ge=120, le=800)
    key_burst_pass2_latency_budget_ms: float = Field(default=8000.0, ge=1000.0, le=60000.0)
    compose_style_guidance_weight: float = Field(default=1.0, ge=0.3, le=2.0)
    compose_voice_hint_weight: float = Field(default=1.0, ge=0.3, le=2.0)
    intent_control_contract_hint_weight: float = Field(default=1.0, ge=0.3, le=2.0)
    compose_control_contract_hint_weight: float = Field(default=1.0, ge=0.3, le=2.0)
    compose_evidence_hint_weight: float = Field(default=1.0, ge=0.3, le=2.0)


class AuthorQualityTuningProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    move_priority_promote_by_segment: dict[SegmentRoleId, list[RelationshipMoveFamily]] = Field(default_factory=dict)
    progression_intensity_by_segment: dict[SegmentRoleId, float] = Field(default_factory=dict)
    render_cue_boost_by_segment: dict[SegmentRoleId, list[str]] = Field(default_factory=dict)
    control_contract_hint_weight: float = Field(default=1.0, ge=0.3, le=2.0)


class QualityTuningProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    round_label: str = Field(default="base", min_length=1, max_length=60)
    note: str = Field(default="", max_length=220)
    play: PlayQualityTuningProfile = Field(default_factory=PlayQualityTuningProfile)
    author: AuthorQualityTuningProfile = Field(default_factory=AuthorQualityTuningProfile)


class BeatDeltaJournalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=80)
    beat_index: int = Field(default=0, ge=0)
    segment_id: str = Field(min_length=1, max_length=120)
    source: BeatDeltaSource
    status: BeatDeltaJobStatus
    created_turn_index: int = Field(default=0, ge=0)
    elapsed_ms: float | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=220)


class SegmentSuggestionLane(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: SuggestionLaneId
    label: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=220)
    candidate_move_families: list[RelationshipMoveFamily] = Field(min_length=1, max_length=4)
    target_priority_ids: list[str] = Field(default_factory=list, max_length=3)
    scene_frame_hint: RelationshipSceneFrame = "private"


class RouteEndingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=220)
    lane_id: SuggestionLaneId | None = None
    target_id: str | None = None
    min_lane_count: int = Field(default=0, ge=0, le=8)
    min_route_lock: int = Field(default=0, ge=0, le=6)
    min_affection: int = Field(default=-3, ge=-3, le=6)
    min_trust: int = Field(default=-3, ge=-3, le=6)
    min_dependency: int = Field(default=0, ge=0, le=6)
    min_scene_heat: int = Field(default=0, ge=0, le=6)
    max_scene_heat: int | None = Field(default=None, ge=0, le=6)
    min_secret_exposure: int = Field(default=0, ge=0, le=6)
    max_secret_exposure: int | None = Field(default=None, ge=0, le=6)
    min_public_events: int = Field(default=0, ge=0, le=8)
    max_public_image: int | None = Field(default=None, ge=0, le=6)
    max_suspicion: int | None = Field(default=None, ge=0, le=6)
    required_secret_ids: list[str] = Field(default_factory=list, max_length=3)
    terminal_segment_id: str = Field(min_length=1)


class EndingMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endings: list[RouteEndingSpec] = Field(min_length=4, max_length=12)


class CompiledSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    segment_role: SegmentRoleId
    focus_target_ids: list[str] = Field(default_factory=list, max_length=2)
    rival_target_ids: list[str] = Field(default_factory=list, max_length=2)
    allocated_secret_ids: list[str] = Field(default_factory=list, max_length=3)
    is_terminal: bool = False
    progress_required: int = Field(default=2, ge=1, le=8)
    segment_turn_floor: int = Field(default=6, ge=1, le=12)
    allowed_move_families: list[RelationshipMoveFamily] = Field(default_factory=list, min_length=2, max_length=6)
    venue_id: str = Field(min_length=1, max_length=120)
    scene_goal: str = Field(min_length=1, max_length=220)
    emotional_goal: str = Field(min_length=1, max_length=220)
    move_priorities: list[RelationshipMoveFamily] = Field(min_length=2, max_length=6)
    public_pressure_cue: str = Field(min_length=1, max_length=220)
    private_pressure_cue: str = Field(min_length=1, max_length=220)
    progression_rule_summary: str = Field(min_length=1, max_length=220)
    suggestion_lanes: list[SegmentSuggestionLane] = Field(default_factory=list, max_length=3)
    render_cues: list[str] = Field(default_factory=list, min_length=2, max_length=5)
    template_tone_example_lines: list[ToneExampleLine] = Field(default_factory=list, max_length=4)
    template_tone_scene_examples: list[ToneSceneExample] = Field(default_factory=list, max_length=2)
    tone_example_pack: CompiledToneExamplePack = Field(default_factory=CompiledToneExamplePack)
    segment_style_profile: SegmentStyleProfile = Field(default_factory=SegmentStyleProfile)
    scene_active_cap: int = Field(default=3, ge=1, le=3)


class UrbanAuthorBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    accepted_blueprint: AcceptedBlueprint
    fit_mode: SeedFitMode
    template_id: ConflictTemplateId
    seed_fingerprint: SeedFingerprint
    arc_template_id: ArcTemplateId
    cast_slots: list[CastSlotPlan] = Field(min_length=3, max_length=7)
    bound_cast: list[BoundIPCastMember] = Field(min_length=3, max_length=7)
    voice_atoms_by_character: dict[str, list[VoiceAtom]] = Field(default_factory=dict)
    segment_contracts: list[SegmentContract] = Field(min_length=3, max_length=8)
    segment_playbooks: list[SegmentPlaybook] = Field(min_length=3, max_length=8)
    ending_matrix: EndingMatrix
    opening_narration: str = Field(min_length=1, max_length=320)


class CompiledPlayPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    story_shell_id: StoryShellId
    fit_mode: SeedFitMode
    template_id: ConflictTemplateId
    seed_fingerprint: SeedFingerprint
    arc_template_id: ArcTemplateId
    protagonist_public_identity: str = Field(min_length=1, max_length=120)
    protagonist_hidden_need: str = Field(min_length=1, max_length=180)
    social_arena: str = Field(min_length=1, max_length=120)
    play_length_preset: PlayLengthPresetId
    route_promise: str = Field(min_length=1, max_length=220)
    bomb_moment: str = Field(min_length=1, max_length=220)
    cost_of_truth: str = Field(min_length=1, max_length=220)
    cast: list[BoundIPCastMember] = Field(min_length=3, max_length=7)
    voice_atoms_by_character: dict[str, list[VoiceAtom]] = Field(default_factory=dict)
    route_target_ids: list[str] = Field(min_length=2, max_length=4)
    delta_pack_contract_version: Literal[4, 5]
    delta_kernel: BeatDeltaKernel
    initial_beat_delta_pack: BeatDeltaPack
    segments: list[CompiledSegment] = Field(min_length=3, max_length=8)
    ending_matrix: EndingMatrix
    opening_narration: str = Field(min_length=1, max_length=320)
    max_turns: int = Field(ge=4, le=56)
    semantic_strategy_version: Literal[8, 9]
    semantic_strategy_pack: TurnSemanticStrategyPack
    quality_tuning_profile: QualityTuningProfile = Field(default_factory=QualityTuningProfile)
    author_version: Literal["v2", "v3"] = "v2"
    relationship_matrix: dict[str, Any] | None = None
    secret_chains: list[dict[str, Any]] | None = None
    tension_score: float | None = None
    storylet_pool: list[dict[str, Any]] | None = None
    organic_secrets: list[dict[str, Any]] | None = None
    hooks: list[dict[str, Any]] | None = None


class UrbanPipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    bundle: UrbanAuthorBundle
    play_plan: CompiledPlayPlan
    state: dict[str, Any]
