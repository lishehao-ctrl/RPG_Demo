from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import (
    AffordanceEffectProfile,
    AffordanceTag,
    AxisDefinition,
    BeatSpec,
    CastMember,
    EndingItem,
    EndingRule,
    FlagDefinition,
    RelationshipMoveFamily,
    StanceDefinition,
    StoryShellId,
    StoryFunction,
    TruthItem,
)

ExecutionFrame = Literal["procedural", "coalition", "public", "coercive"]
PlayStoryMode = Literal["legacy_civic", "relationship_drama"]
RelationshipSceneFrame = Literal["private", "semi_public", "public"]
RelationshipIntimacyRisk = Literal["low", "medium", "high"]
LatentEventKind = Literal["relationship_debt", "public_wave", "secret_pressure", "npc_action"]
LatentEventControl = Literal["press", "redirect", "detonate", "none"]
LatentRadarTrend = Literal["rising", "steady", "cooling", "triggered"]
ControlTargetKind = Literal["kind", "event", "character"]
IntentCompileSource = Literal["llm", "heuristic_fallback"]
ControlSource = Literal["explicit", "free_text", "none"]
IntentDeviationType = Literal["scope_shift", "target_shift", "move_downgrade", "none"]


class PlaySessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1)


class PlayTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_text: str = Field(min_length=1, max_length=2000)
    draft_intent_id: str | None = Field(default=None, max_length=120)
    selected_suggestion_id: str | None = None
    selected_story_action_id: str | None = None
    selected_control_action_id: str | None = None
    control_action: LatentEventControl = "none"
    control_target_kind: LatentEventKind | None = None
    control_target_id: str | None = Field(default=None, max_length=120)
    control_target_mode: ControlTargetKind | None = None


class PlayDraftIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_text: str = Field(min_length=1, max_length=2000)
    is_final_draft: bool = False
    selected_suggestion_id: str | None = None
    selected_story_action_id: str | None = None
    selected_control_action_id: str | None = None
    control_action: LatentEventControl = "none"
    control_target_kind: LatentEventKind | None = None
    control_target_id: str | None = Field(default=None, max_length=120)
    control_target_mode: ControlTargetKind | None = None


class PlayDraftIntentPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str = Field(min_length=1, max_length=80)
    move_family: RelationshipMoveFamily
    target_id: str | None = Field(default=None, max_length=120)
    scene_frame: RelationshipSceneFrame
    control_action: LatentEventControl = "none"
    control_source: ControlSource = "none"
    control_target_kind: LatentEventKind | None = None
    control_target_id: str | None = Field(default=None, max_length=120)
    control_target_mode: ControlTargetKind | None = None
    intent_compile_source: IntentCompileSource = "heuristic_fallback"
    intent_confidence: float = Field(default=0.0, ge=0, le=1)
    deviation_type: IntentDeviationType = "none"
    deviation_note: str | None = Field(default=None, max_length=220)
    mapped_suggestion_id: str | None = Field(default=None, max_length=120)
    alternatives: list[str] = Field(default_factory=list, max_length=3)


class PlayDraftIntentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    draft_intent_id: str = Field(min_length=1, max_length=120)
    state_snapshot_id: str = Field(min_length=1, max_length=120)
    normalized_text_hash: str = Field(min_length=1, max_length=80)
    expires_at: datetime
    intent: PlayDraftIntentPreview
    diagnostics: dict[str, int | float | str | bool] = Field(default_factory=dict)
    usage: dict[str, int] = Field(default_factory=dict)


class PlayStateBar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bar_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=120)
    category: Literal["axis", "stance", "global", "relationship"]
    current_value: int
    min_value: int
    max_value: int


class PlaySuggestedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str = Field(min_length=1)
    action_type: Literal["story", "control"] = "story"
    label: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=220)


class PlayControlAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1)
    action_type: LatentEventControl
    target_mode: ControlTargetKind | None = None
    target_kind: LatentEventKind | None = None
    target_id: str | None = Field(default=None, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=220)


class PlayLatentRadarItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LatentEventKind
    pressure: int = Field(ge=0, le=6)
    trend: LatentRadarTrend = "steady"
    note: str = Field(min_length=1, max_length=160)


class PlayControlResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: LatentEventControl = "none"
    target_mode: ControlTargetKind | None = None
    target_kind: LatentEventKind | None = None
    target_id: str | None = Field(default=None, max_length=120)
    target_event_id: str | None = Field(default=None, max_length=120)
    applied: bool = False
    summary: str = Field(min_length=1, max_length=220)
    tags: list[str] = Field(default_factory=list, max_length=6)


class PlayUtilityShiftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    delta: int = Field(ge=-12, le=12)
    reason_family: str = Field(min_length=1, max_length=80)
    reason_text: str = Field(default="", max_length=220)


class PlayCostRouteDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(min_length=1, max_length=120)
    route_kind: str = Field(min_length=1, max_length=80)
    source_move_family: str = Field(min_length=1, max_length=80)
    source_control_action: str = Field(min_length=1, max_length=40)
    source_scene_frame: str = Field(min_length=1, max_length=40)
    source_segment_role: str = Field(min_length=1, max_length=80)
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    owner_character_ids: list[str] = Field(default_factory=list, max_length=3)
    payer_character_id: str | None = Field(default=None, max_length=120)
    beneficiary_character_id: str | None = Field(default=None, max_length=120)
    linked_scene_question_id: str | None = Field(default=None, max_length=120)
    scene_question_focus: str | None = Field(default=None, max_length=80)
    return_due_turn: int | None = Field(default=None, ge=0)
    payoff_family: str = Field(min_length=1, max_length=80)
    deferred_kind: str | None = Field(default=None, max_length=80)
    deferred_callback_id: str | None = Field(default=None, max_length=120)
    transferred_to_character_id: str | None = Field(default=None, max_length=120)


class PlayPropagationEdgeDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(min_length=1, max_length=120)
    shell_id: str = Field(min_length=1, max_length=80)
    from_node: str = Field(min_length=1, max_length=80)
    to_node: str = Field(min_length=1, max_length=80)
    anchor_token: str = Field(min_length=1, max_length=24)
    signal_family: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=180)


class PlaySceneQuestionDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=220)
    status: str = Field(min_length=1, max_length=40)
    previous_status: str | None = Field(default=None, max_length=40)
    resolved_by: str | None = Field(default=None, max_length=120)
    updated_turn_index: int = Field(default=0, ge=0)
    summary: str = Field(default="", max_length=220)


class PlayCallbackStatusDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_count: int = Field(default=0, ge=0, le=8)
    matured_count: int = Field(default=0, ge=0, le=4)
    consumed_count: int = Field(default=0, ge=0, le=4)
    pending_count: int = Field(default=0, ge=0, le=16)
    triggered_callback_id: str | None = Field(default=None, max_length=120)
    triggered_kind: str | None = Field(default=None, max_length=80)
    summary: str = Field(default="", max_length=220)


class PlayQuestionStepDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    before_status: str = Field(min_length=1, max_length=40)
    expected_status: str = Field(min_length=1, max_length=40)
    final_status: str = Field(min_length=1, max_length=40)
    forced_advance: bool = False
    advance_reason: str | None = Field(default=None, max_length=120)
    resolved_by: str | None = Field(default=None, max_length=120)
    summary: str = Field(default="", max_length=220)


class PlayEventDecisionDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_event_id: str | None = Field(default=None, max_length=80)
    top_event_kind: str | None = Field(default=None, max_length=80)
    top_event_transition: str = Field(default="none", min_length=1, max_length=40)
    triggered_event_id: str | None = Field(default=None, max_length=80)
    triggered_kind: str | None = Field(default=None, max_length=80)
    primary_driver: str = Field(default="none", min_length=1, max_length=40)
    due_cost_primary_eligible: bool = False
    due_cost_forces_primary_driver_applied: bool = False
    cost_ladder_stage: int = Field(default=0, ge=0, le=3)
    cost_ladder_primary_applies: bool = False
    player_override_applied: bool = False
    secondary_due_cost_pressure: bool = False
    key_segment_conversion: bool = False
    prioritized_cost_id: str | None = Field(default=None, max_length=120)
    prioritized_cost_due_turn: int | None = Field(default=None, ge=0)
    cost_return_priority_applied: bool = False
    summary: str = Field(default="", max_length=220)


class PlayPayoffCommitDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    committed: bool = False
    route_kind: str | None = Field(default=None, max_length=80)
    global_delta_keys: list[str] = Field(default_factory=list, max_length=8)
    relationship_delta_ids: list[str] = Field(default_factory=list, max_length=8)
    owner_character_ids: list[str] = Field(default_factory=list, max_length=3)
    payer_character_id: str | None = Field(default=None, max_length=120)
    beneficiary_character_id: str | None = Field(default=None, max_length=120)
    linked_scene_question_id: str | None = Field(default=None, max_length=120)
    return_due_turn: int | None = Field(default=None, ge=0)
    cost_recorded: bool = False
    control_signature_action: str = Field(default="none", min_length=1, max_length=20)
    control_signature_valid: bool = True
    control_signature_fail_safe_applied: bool = False
    fallback_applied: bool = False
    summary: str = Field(default="", max_length=220)


class PlayStyleCommitDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_segment: bool = False
    reason_family: str = Field(default="mixed", min_length=1, max_length=80)
    signal_family: str = Field(default="mixed", min_length=1, max_length=80)
    cost_family: str = Field(default="mixed", min_length=1, max_length=80)
    cadence: str = Field(default="mixed", min_length=1, max_length=80)
    counter_function_role: str = Field(default="wait_flip", min_length=1, max_length=40)
    crowd_function_role: str = Field(default="wait_flip", min_length=1, max_length=40)
    counter_action_verb: str | None = Field(default=None, max_length=40)
    crowd_action_verb: str | None = Field(default=None, max_length=40)
    role_lexicon_hit: bool = False
    force_main_clause_cost_subject: bool = False
    payer_character_id: str | None = Field(default=None, max_length=120)
    beneficiary_character_id: str | None = Field(default=None, max_length=120)
    cost_subject_focus: str | None = Field(default=None, max_length=80)
    shell_anchor_tokens: list[str] = Field(default_factory=list, max_length=6)
    shell_anchor_hit: bool = False
    summary: str = Field(default="", max_length=220)


class PlayStoryDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utility_top_shift: list[PlayUtilityShiftItem] = Field(default_factory=list, max_length=3)
    stake_shift_top: PlayUtilityShiftItem | None = None
    question_step: PlayQuestionStepDebug | None = None
    event_decision: PlayEventDecisionDebug | None = None
    payoff_commit: PlayPayoffCommitDebug | None = None
    style_commit: PlayStyleCommitDebug | None = None
    cost_route: PlayCostRouteDebug | None = None
    propagation_edge: PlayPropagationEdgeDebug | None = None
    scene_question_state: PlaySceneQuestionDebug | None = None
    callback_status: PlayCallbackStatusDebug | None = None
    summary: str = Field(default="", max_length=220)


class PlayEnding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=220)


class PlayProtagonist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    mandate: str = Field(min_length=1, max_length=220)
    identity_summary: str = Field(min_length=1, max_length=320)
    role_label: str | None = Field(default=None, max_length=120)
    core_desire: str | None = Field(default=None, max_length=220)
    hidden_risk: str | None = Field(default=None, max_length=220)


class PlaySuccessLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proof_progress: int = Field(ge=0)
    coalition_progress: int = Field(ge=0)
    order_progress: int = Field(ge=0)
    settlement_progress: int = Field(ge=0)


class PlayCostLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_cost: int = Field(ge=0)
    relationship_cost: int = Field(ge=0)
    procedural_cost: int = Field(ge=0)
    coercion_cost: int = Field(ge=0)


class PlayLedgerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: PlaySuccessLedger
    cost: PlayCostLedger


class PlayFeedbackSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ledgers: PlayLedgerSnapshot
    last_turn_axis_deltas: dict[str, int] = Field(default_factory=dict)
    last_turn_stance_deltas: dict[str, int] = Field(default_factory=dict)
    last_turn_global_deltas: dict[str, int] = Field(default_factory=dict)
    last_turn_relationship_deltas: dict[str, dict[str, int]] = Field(default_factory=dict)
    last_turn_tags: list[str] = Field(default_factory=list, max_length=8)
    last_turn_consequences: list[str] = Field(default_factory=list, max_length=8)
    last_turn_revealed_secret_ids: list[str] = Field(default_factory=list, max_length=4)


class PlaySessionHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Literal["gm", "player"]
    text: str = Field(min_length=1, max_length=4000)
    created_at: datetime
    turn_index: int = Field(ge=0)


class PlaySessionHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    entries: list[PlaySessionHistoryEntry] = Field(default_factory=list)


class PlaySessionProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed_beats: int = Field(ge=0)
    total_beats: int = Field(ge=1)
    current_beat_progress: int = Field(ge=0)
    current_beat_goal: int = Field(ge=1)
    turn_index: int = Field(ge=0)
    max_turns: int = Field(ge=1)
    completion_ratio: float = Field(ge=0, le=1)
    display_percent: int = Field(ge=0, le=100)


class PlaySupportSurface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    disabled_reason: str | None = Field(default=None, max_length=220)


class PlaySupportSurfaces(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory: PlaySupportSurface = Field(default_factory=PlaySupportSurface)
    map: PlaySupportSurface = Field(default_factory=PlaySupportSurface)


class PlayRelationshipTargetState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    affection: int
    trust: int
    tension: int
    suspicion: int
    dependency: int
    is_route_focus: bool = False


class PlayRelationshipStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_heat: int
    public_image: int
    secret_exposure: int
    route_lock: int
    current_route_target_id: str | None = None
    targets: list[PlayRelationshipTargetState] = Field(default_factory=list, max_length=8)


class PlaySessionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    story_mode: PlayStoryMode = "relationship_drama"
    story_shell_id: StoryShellId | None = None
    status: Literal["active", "completed", "expired"]
    turn_index: int = Field(ge=0)
    beat_index: int = Field(ge=1)
    beat_title: str = Field(min_length=1, max_length=120)
    story_title: str = Field(min_length=1, max_length=120)
    narration: str = Field(min_length=1, max_length=4000)
    protagonist: PlayProtagonist | None = None
    feedback: PlayFeedbackSnapshot | None = None
    progress: PlaySessionProgress | None = None
    support_surfaces: PlaySupportSurfaces | None = None
    state_bars: list[PlayStateBar] = Field(default_factory=list, max_length=16)
    current_route_target_id: str | None = None
    relationship_state: PlayRelationshipStateSnapshot | None = None
    suggested_actions: list[PlaySuggestedAction] = Field(default_factory=list, max_length=3)
    story_actions: list[PlaySuggestedAction] = Field(default_factory=list, max_length=3)
    control_actions: list[PlayControlAction] = Field(default_factory=list, max_length=3)
    latent_radar: list[PlayLatentRadarItem] = Field(default_factory=list, max_length=4)
    ending: PlayEnding | None = None


class PlayTurnIntentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affordance_tag: AffordanceTag | None = None
    target_npc_ids: list[str] = Field(default_factory=list, max_length=3)
    risk_level: Literal["low", "medium", "high"] | None = "medium"
    execution_frame: ExecutionFrame = "procedural"
    tactic_summary: str = Field(min_length=1, max_length=220)
    move_family: RelationshipMoveFamily | None = None
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    intimacy_risk: RelationshipIntimacyRisk = "medium"
    scene_frame: RelationshipSceneFrame = "private"
    intent_summary: str | None = Field(default=None, max_length=220)


class PlayRenderActionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=220)


class PlayRenderDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narration: str = Field(min_length=1, max_length=4000)
    suggested_actions: list[PlayRenderActionDraft] = Field(min_length=3, max_length=3)


class PlayEndingIntentJudgeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str


class PlayPyrrhicCriticDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str


class PlayPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1)
    story_mode: PlayStoryMode = "relationship_drama"
    story_shell_id: StoryShellId | None = None
    story_title: str = Field(min_length=1, max_length=120)
    protagonist: PlayProtagonist
    protagonist_name: str | None = None
    protagonist_npc_id: str | None = None
    closeout_profile: str = Field(min_length=1, max_length=80)
    closeout_router_reason: str = Field(min_length=1, max_length=120)
    runtime_policy_profile: str = Field(min_length=1, max_length=80)
    runtime_router_reason: str = Field(min_length=1, max_length=120)
    premise: str = Field(min_length=1, max_length=320)
    tone: str = Field(min_length=1, max_length=120)
    style_guard: str = Field(min_length=1, max_length=220)
    cast: list[CastMember] = Field(min_length=3, max_length=5)
    truths: list[TruthItem] = Field(min_length=1, max_length=8)
    endings: list[EndingItem] = Field(min_length=3, max_length=5)
    axes: list[AxisDefinition] = Field(min_length=2, max_length=6)
    stances: list[StanceDefinition] = Field(default_factory=list, max_length=5)
    flags: list[FlagDefinition] = Field(default_factory=list, max_length=8)
    beats: list[BeatSpec] = Field(min_length=1, max_length=6)
    route_unlock_rules: list = Field(default_factory=list)
    ending_rules: list[EndingRule] = Field(min_length=1, max_length=6)
    affordance_effect_profiles: list[AffordanceEffectProfile] = Field(min_length=2, max_length=12)
    available_affordance_tags: list[AffordanceTag] = Field(min_length=2, max_length=12)
    max_turns: int = Field(ge=1)
    opening_narration: str = Field(min_length=1, max_length=4000)
    relationship_hook: str | None = Field(default=None, max_length=320)
    secret_hook: str | None = Field(default=None, max_length=320)
    route_target_ids: list[str] = Field(default_factory=list, max_length=5)


class PlayResolutionEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affordance_tag: AffordanceTag | None = None
    risk_level: Literal["low", "medium", "high"] | None = None
    execution_frame: ExecutionFrame = "procedural"
    target_npc_ids: list[str] = Field(default_factory=list, max_length=3)
    tactic_summary: str = Field(min_length=1, max_length=220)
    off_route: bool = False
    axis_changes: dict[str, int] = Field(default_factory=dict)
    stance_changes: dict[str, int] = Field(default_factory=dict)
    flag_changes: dict[str, bool] = Field(default_factory=dict)
    revealed_truth_ids: list[str] = Field(default_factory=list, max_length=4)
    added_event_ids: list[str] = Field(default_factory=list, max_length=4)
    beat_completed: bool = False
    advanced_to_next_beat: bool = False
    ending_id: str | None = None
    ending_trigger_reason: str | None = Field(default=None, max_length=120)
    pressure_note: str = Field(min_length=1, max_length=220)
    move_family: RelationshipMoveFamily | None = None
    scene_frame: RelationshipSceneFrame | None = None
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    intimacy_risk: RelationshipIntimacyRisk | None = None
    global_state_changes: dict[str, int] = Field(default_factory=dict)
    relationship_state_changes: dict[str, dict[str, int]] = Field(default_factory=dict)
    revealed_secret_ids: list[str] = Field(default_factory=list, max_length=4)
    route_focus_character_id: str | None = None
    control_action: LatentEventControl = "none"
    control_source: ControlSource = "none"
    control_target_kind: LatentEventKind | None = None
    control_target_id: str | None = Field(default=None, max_length=120)
    control_resolution: PlayControlResolution | None = None
    intent_compile_source: IntentCompileSource | None = None
    intent_confidence: float | None = Field(default=None, ge=0, le=1)
    deviation_type: IntentDeviationType = "none"
    deviation_note: str | None = Field(default=None, max_length=220)
    alternatives: list[str] = Field(default_factory=list, max_length=3)
    latent_radar: list[PlayLatentRadarItem] = Field(default_factory=list, max_length=4)
    story_debug: PlayStoryDebug | None = None


class PlayTurnTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=1)
    created_at: datetime
    player_input: str = Field(min_length=1, max_length=2000)
    selected_suggestion_id: str | None = None
    selected_story_action_id: str | None = None
    submission_input_mode: Literal["free_input", "select_id"] | None = None
    selected_control_action_id: str | None = None
    turn_tags: list[str] = Field(default_factory=list, max_length=12)
    interpret_source: Literal["llm", "llm_repair", "heuristic"]
    render_source: Literal["llm", "llm_repair", "heuristic", "fallback"]
    execution_frame: ExecutionFrame = "procedural"
    interpret_attempts: int = Field(ge=0)
    ending_judge_source: Literal["llm", "heuristic", "failed", "skipped"]
    pyrrhic_critic_source: Literal["llm", "heuristic", "failed", "skipped"]
    ending_judge_attempts: int = Field(ge=0)
    pyrrhic_critic_attempts: int = Field(ge=0)
    ending_judge_proposed_id: str | None = None
    pyrrhic_critic_proposed_id: str | None = None
    ending_judge_failure_reason: str | None = Field(default=None, max_length=120)
    pyrrhic_critic_failure_reason: str | None = Field(default=None, max_length=120)
    ending_judge_response_id: str | None = None
    pyrrhic_critic_response_id: str | None = None
    ending_judge_usage: dict[str, int | str] = Field(default_factory=dict)
    pyrrhic_critic_usage: dict[str, int | str] = Field(default_factory=dict)
    render_attempts: int = Field(ge=0)
    interpret_failure_reason: str | None = Field(default=None, max_length=120)
    render_failure_reason: str | None = Field(default=None, max_length=120)
    interpret_response_id: str | None = None
    render_response_id: str | None = None
    interpret_usage: dict[str, int | str] = Field(default_factory=dict)
    render_usage: dict[str, int | str] = Field(default_factory=dict)
    turn_elapsed_ms: int = Field(default=0, ge=0)
    interpret_elapsed_ms: int = Field(default=0, ge=0)
    ending_judge_elapsed_ms: int = Field(default=0, ge=0)
    pyrrhic_critic_elapsed_ms: int = Field(default=0, ge=0)
    render_elapsed_ms: int = Field(default=0, ge=0)
    session_cache_enabled: bool = False
    used_previous_response_id: bool = False
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    beat_index_before: int = Field(ge=1)
    beat_title_before: str = Field(min_length=1, max_length=120)
    beat_index_after: int = Field(ge=1)
    beat_title_after: str = Field(min_length=1, max_length=120)
    status_after: Literal["active", "completed", "expired"]
    lane_id: str | None = None
    intent_compile_source: IntentCompileSource | None = None
    intent_confidence: float | None = Field(default=None, ge=0, le=1)
    control_source: ControlSource = "none"
    deviation_type: IntentDeviationType = "none"
    move_family: RelationshipMoveFamily | None = None
    scene_frame: RelationshipSceneFrame | None = None
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    global_state_changes: dict[str, int] = Field(default_factory=dict)
    relationship_state_changes: dict[str, dict[str, int]] = Field(default_factory=dict)
    revealed_secret_ids: list[str] = Field(default_factory=list, max_length=4)
    resolution: PlayResolutionEffect
    story_debug: PlayStoryDebug | None = None
