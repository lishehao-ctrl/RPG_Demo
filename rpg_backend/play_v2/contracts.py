from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author_v2.contracts import (
    BeatDeltaJournalEntry,
    BeatDeltaJobStatus,
    BeatDeltaPack,
    CompiledPlayPlan,
    NpcPublicPosture,
    NpcSceneIntent,
    RelationshipSceneFrame,
    SegmentRoleId,
    SuggestionLaneId,
    TurnConfidence,
)


class UrbanRelationshipTargetState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=80)
    affection: int = 0
    trust: int = 0
    tension: int = 0
    suspicion: int = 0
    dependency: int = 0
    is_route_focus: bool = False


class NpcMindState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stance: Literal["ally", "guarded", "testing", "hostile", "dependent"] = "guarded"
    current_goal: str = Field(min_length=1, max_length=180)
    mask_integrity: int = Field(default=6, ge=0, le=6)
    pressure_load: int = Field(default=0, ge=0, le=6)
    humiliation_risk: int = Field(default=0, ge=0, le=6)
    jealousy: int = Field(default=0, ge=0, le=6)
    protectiveness: int = Field(default=0, ge=0, le=6)
    control_need: int = Field(default=0, ge=0, le=6)
    confession_readiness: int = Field(default=0, ge=0, le=6)
    betrayal_readiness: int = Field(default=0, ge=0, le=6)
    commitment_target_id: str | None = None
    commitment_streak: int = Field(default=0, ge=0, le=12)
    last_wound: str | None = Field(default=None, max_length=120)
    last_favor: str | None = Field(default=None, max_length=120)
    trust: int = Field(default=0, ge=-3, le=6)
    affection: int = Field(default=0, ge=-3, le=6)
    tension: int = Field(default=0, ge=0, le=6)
    suspicion: int = Field(default=0, ge=0, le=6)
    dependency: int = Field(default=0, ge=0, le=6)


class NpcSceneFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1)
    scene_intent: NpcSceneIntent
    public_posture: NpcPublicPosture
    target_focus_id: str | None = None
    most_feared_exposure: str = Field(min_length=1, max_length=180)
    line_about_to_break: bool = False
    reaction_priority: list[str] = Field(default_factory=list, max_length=5)


class HookState(BaseModel):
    hook_id: str
    holder_id: str
    target_id: str
    source_secret_id: str
    leverage_type: str
    status: Literal["dormant", "suspected", "active", "leveraged", "detonated"] = "dormant"
    leverage_value: float = Field(default=0.0, ge=0.0, le=1.0)


LatentEventKind = Literal["relationship_debt", "public_wave", "secret_pressure", "npc_action"]
LatentEventStatus = Literal["latent", "primed", "triggered", "cooled"]
LatentEventControl = Literal["press", "redirect", "detonate", "none"]
LatentRadarTrend = Literal["rising", "steady", "cooling", "triggered"]
ControlTargetKind = Literal["kind", "event", "character"]
IntentCompileSource = Literal["llm", "heuristic_fallback"]
ControlSource = Literal["explicit", "free_text", "none"]
IntentDeviationType = Literal["scope_shift", "target_shift", "move_downgrade", "none"]
UtilityReasonFamily = Literal["loss_position", "self_preserve", "old_debt", "opportunity_window", "blame_shift", "mixed"]
CostRouteKind = Literal["immediate_cost", "deferred_cost", "transferred_cost"]
SceneQuestionStatus = Literal["open", "tightening", "flip", "resolved"]
CallbackStatus = Literal["pending", "matured", "consumed", "expired"]
CausalContractStatus = Literal["pending", "resolved"]
CostQuestionFocus = Literal["who_pays", "who_takes_blame", "who_gets_chased"]
UnresolvedCostStatus = Literal["pending", "returned", "resolved", "expired"]
TurnPrimaryDriver = Literal["latent", "cost_return", "none"]


class NpcUtilityDeltaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    utility_delta: int = Field(default=0, ge=-12, le=12)
    reason_family: UtilityReasonFamily = "mixed"
    reason_text: str = Field(default="", max_length=220)


class CostRouteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(min_length=1, max_length=120)
    route_kind: CostRouteKind = "immediate_cost"
    source_move_family: RelationshipMoveFamily
    source_control_action: LatentEventControl = "none"
    source_scene_frame: RelationshipSceneFrame = "private"
    source_segment_role: SegmentRoleId
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    owner_character_ids: list[str] = Field(default_factory=list, max_length=3)
    payer_character_id: str | None = Field(default=None, max_length=80)
    beneficiary_character_id: str | None = Field(default=None, max_length=80)
    linked_scene_question_id: str | None = Field(default=None, max_length=120)
    scene_question_focus: CostQuestionFocus = "who_pays"
    return_due_turn: int | None = Field(default=None, ge=0)
    payoff_family: str = Field(default="mixed", min_length=1, max_length=80)
    immediate_global_deltas: dict[str, int] = Field(default_factory=dict)
    immediate_relationship_deltas: dict[str, dict[str, int]] = Field(default_factory=dict)
    deferred_kind: LatentEventKind | None = None
    deferred_callback_id: str | None = Field(default=None, max_length=120)
    transferred_to_character_id: str | None = Field(default=None, max_length=80)


class ShellPropagationEdgeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(min_length=1, max_length=120)
    shell_id: str = Field(min_length=1, max_length=80)
    from_node: str = Field(min_length=1, max_length=80)
    to_node: str = Field(min_length=1, max_length=80)
    anchor_token: str = Field(min_length=1, max_length=24)
    signal_family: str = Field(default="mixed", min_length=1, max_length=80)
    note: str = Field(default="", max_length=180)


class SceneQuestionStateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=220)
    status: SceneQuestionStatus = "open"
    previous_status: SceneQuestionStatus | None = None
    resolved_by: str | None = Field(default=None, max_length=120)
    updated_turn_index: int = Field(default=0, ge=0)
    summary: str = Field(default="", max_length=220)


class NarrationEventEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=0)
    fingerprint: str = Field(default="", max_length=20)
    phrase: str = Field(default="", max_length=320)
    pattern_fingerprint: str = Field(default="", max_length=20)
    move_family: str = Field(default="", max_length=30)
    target_id: str = Field(default="", max_length=120)
    relationship_deltas: dict[str, dict[str, float]] = Field(default_factory=dict)


class NarrationSegmentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: str = Field(default="", max_length=30)
    summary_text: str = Field(default="", max_length=600)
    key_events: list[str] = Field(default_factory=list, max_length=6)
    turn_range_start: int = Field(default=0, ge=0)
    turn_range_end: int = Field(default=0, ge=0)
    entry_count: int = Field(default=0, ge=0)


class CallbackQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    callback_id: str = Field(min_length=1, max_length=120)
    status: CallbackStatus = "pending"
    source_turn_index: int = Field(default=0, ge=0)
    source_segment_id: str = Field(min_length=1, max_length=120)
    source_move_family: RelationshipMoveFamily
    linked_shell_edge_id: str | None = Field(default=None, max_length=120)
    linked_scene_question_id: str | None = Field(default=None, max_length=120)
    due_turn_min: int = Field(ge=0)
    due_turn_max: int = Field(ge=0)
    kind: LatentEventKind
    payoff_kind: str = Field(default="mixed", min_length=1, max_length=80)
    stake_character_ids: list[str] = Field(default_factory=list, max_length=3)
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    actor_character_id: str | None = Field(default=None, max_length=80)
    cue_text: str = Field(min_length=1, max_length=220)
    detonation_text: str = Field(min_length=1, max_length=220)
    global_deltas: dict[str, int] = Field(default_factory=dict)
    relationship_deltas: dict[str, dict[str, int]] = Field(default_factory=dict)


class UnresolvedCostRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_id: str = Field(min_length=1, max_length=120)
    source_turn_index: int = Field(default=0, ge=0)
    source_segment_id: str = Field(min_length=1, max_length=120)
    route_kind: CostRouteKind
    owner_character_ids: list[str] = Field(default_factory=list, max_length=3)
    payer_character_id: str | None = Field(default=None, max_length=80)
    beneficiary_character_id: str | None = Field(default=None, max_length=80)
    linked_scene_question_id: str | None = Field(default=None, max_length=120)
    scene_question_focus: CostQuestionFocus = "who_pays"
    due_turn: int = Field(default=0, ge=0)
    status: UnresolvedCostStatus = "pending"
    linked_callback_id: str | None = Field(default=None, max_length=120)
    resolved_turn_index: int | None = Field(default=None, ge=0)
    ladder_stage: int = Field(default=1, ge=1, le=3)
    ladder_retry_bias_steps: int = Field(default=0, ge=0, le=6)
    ladder_defer_once_used: bool = False
    ladder_summary: str = Field(default="", max_length=220)
    summary: str = Field(default="", max_length=220)


class CallbackTurnStatusRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_count: int = Field(default=0, ge=0, le=4)
    matured_count: int = Field(default=0, ge=0, le=2)
    consumed_count: int = Field(default=0, ge=0, le=2)
    pending_count: int = Field(default=0, ge=0, le=8)
    triggered_callback_id: str | None = Field(default=None, max_length=120)
    triggered_kind: LatentEventKind | None = None
    summary: str = Field(default="", max_length=220)


class CausalContractStateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=120)
    source_kind: Literal["callback", "latent", "payoff"]
    required_kind: LatentEventKind | Literal["any"] = "any"
    open_by_role: SegmentRoleId
    resolve_by_role: SegmentRoleId
    min_resolution_count: int = Field(default=1, ge=1, le=3)
    status: CausalContractStatus = "pending"
    opened_turn_index: int = Field(default=0, ge=0)
    resolved_turn_index: int | None = Field(default=None, ge=0)
    resolution_count: int = Field(default=0, ge=0, le=12)
    fail_safe_applied: bool = False
    stale_escalation_count: int = Field(default=0, ge=0, le=6)
    last_stale_turn_index: int | None = Field(default=None, ge=0)
    summary: str = Field(default="", max_length=220)


class LatentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=80)
    kind: LatentEventKind
    shell_id: str = Field(min_length=1, max_length=80)
    source_turn_index: int = Field(ge=0)
    source_segment_id: str = Field(min_length=1, max_length=120)
    stake_family: str = Field(default="general", min_length=1, max_length=80)
    stake_character_ids: list[str] = Field(default_factory=list, max_length=3)
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    actor_character_id: str | None = Field(default=None, max_length=80)
    pressure: int = Field(default=0, ge=0, le=6)
    maturity: int = Field(default=0, ge=0, le=6)
    trigger_threshold: int = Field(default=4, ge=1, le=12)
    age_turns: int = Field(default=0, ge=0, le=12)
    status: LatentEventStatus = "latent"
    visibility: Literal["semi_visible"] = "semi_visible"
    trigger_window_roles: list[SegmentRoleId] = Field(default_factory=list, max_length=4)
    trigger_window_frames: list[RelationshipSceneFrame] = Field(default_factory=list, max_length=3)
    foreshadow_text: str = Field(min_length=1, max_length=220)
    detonation_text: str = Field(min_length=1, max_length=220)
    global_deltas: dict[str, int] = Field(default_factory=dict)
    relationship_deltas: dict[str, dict[str, int]] = Field(default_factory=dict)
    reaction_cause_tags: list[str] = Field(default_factory=list, max_length=6)


class TurnEscalationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["latent_event"] = "latent_event"
    event_id: str | None = Field(default=None, max_length=80)
    kind: LatentEventKind | None = None
    control: LatentEventControl = "none"
    family: str = Field(min_length=1, max_length=80)
    actor_character_id: str | None = Field(default=None, max_length=80)
    target_character_ids: list[str] = Field(default_factory=list, max_length=3)
    stake_character_ids: list[str] = Field(default_factory=list, max_length=3)
    text: str = Field(min_length=1, max_length=220)
    global_deltas: dict[str, int] = Field(default_factory=dict)
    relationship_deltas: dict[str, dict[str, int]] = Field(default_factory=dict)
    revealed_secret_ids: list[str] = Field(default_factory=list, max_length=4)


class UrbanControlAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=120)
    action_type: LatentEventControl
    label: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=220)
    target_kind: LatentEventKind | None = None
    target_id: str | None = Field(default=None, max_length=120)
    target_mode: ControlTargetKind = "kind"


class UrbanControlResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: LatentEventControl = "none"
    target_mode: ControlTargetKind | None = None
    target_kind: LatentEventKind | None = None
    target_id: str | None = Field(default=None, max_length=120)
    target_event_id: str | None = Field(default=None, max_length=80)
    applied: bool = False
    summary: str = Field(default="未执行控雷操作。", min_length=1, max_length=220)
    tags: list[str] = Field(default_factory=list, max_length=6)


class UrbanLatentRadarItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: LatentEventKind
    pressure: int = Field(default=0, ge=0, le=6)
    trend: LatentRadarTrend = "steady"
    note: str = Field(min_length=1, max_length=160)


class TurnSemanticQuestionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=220)
    before_status: SceneQuestionStatus = "open"
    expected_status: SceneQuestionStatus = "open"
    final_status: SceneQuestionStatus = "open"
    forced_advance: bool = False
    advance_reason: str | None = Field(default=None, max_length=120)
    resolved_by: str | None = Field(default=None, max_length=120)
    prioritized_cost_id: str | None = Field(default=None, max_length=120)
    prioritized_cost_focus: CostQuestionFocus | None = None
    prioritized_cost_due_turn: int | None = Field(default=None, ge=0)
    summary: str = Field(default="", max_length=220)


class TurnSemanticStakePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_shifts: list[NpcUtilityDeltaItem] = Field(default_factory=list, max_length=3)
    summary: str = Field(default="", max_length=220)


class TurnSemanticEventPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_event_id: str | None = Field(default=None, max_length=80)
    top_event_kind: LatentEventKind | None = None
    top_event_transition: str = Field(default="none", min_length=1, max_length=40)
    triggered_event_id: str | None = Field(default=None, max_length=80)
    triggered_kind: LatentEventKind | None = None
    primary_driver: TurnPrimaryDriver = "none"
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
    causal_pending_count: int = Field(default=0, ge=0, le=12)
    causal_resolved_this_turn: int = Field(default=0, ge=0, le=6)
    causal_fail_safe_applied: bool = False
    stale_escalations_this_turn: int = Field(default=0, ge=0, le=6)
    summary: str = Field(default="", max_length=220)


class TurnSemanticPayoffPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    committed: bool = False
    route_kind: CostRouteKind | None = None
    global_delta_keys: list[str] = Field(default_factory=list, max_length=8)
    relationship_delta_ids: list[str] = Field(default_factory=list, max_length=8)
    owner_character_ids: list[str] = Field(default_factory=list, max_length=3)
    payer_character_id: str | None = Field(default=None, max_length=80)
    beneficiary_character_id: str | None = Field(default=None, max_length=80)
    linked_scene_question_id: str | None = Field(default=None, max_length=120)
    return_due_turn: int | None = Field(default=None, ge=0)
    cost_recorded: bool = False
    control_signature_action: str = Field(default="none", min_length=1, max_length=20)
    control_signature_valid: bool = True
    control_signature_fail_safe_applied: bool = False
    fallback_applied: bool = False
    summary: str = Field(default="", max_length=220)


class TurnSemanticStylePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_segment: bool = False
    reason_family: str = Field(default="mixed", min_length=1, max_length=80)
    counter_reason_family: str = Field(default="mixed", min_length=1, max_length=80)
    crowd_reason_family: str = Field(default="mixed", min_length=1, max_length=80)
    signal_family: str = Field(default="mixed", min_length=1, max_length=80)
    cost_family: str = Field(default="mixed", min_length=1, max_length=80)
    cadence: str = Field(default="mixed", min_length=1, max_length=80)
    counter_function_role: str = Field(default="wait_flip", min_length=1, max_length=40)
    crowd_function_role: str = Field(default="wait_flip", min_length=1, max_length=40)
    counter_action_verb: str | None = Field(default=None, max_length=40)
    crowd_action_verb: str | None = Field(default=None, max_length=40)
    counter_receiver_template: str | None = Field(default=None, max_length=120)
    crowd_receiver_template: str | None = Field(default=None, max_length=120)
    role_lexicon_hit: bool = False
    force_main_clause_cost_subject: bool = False
    payer_character_id: str | None = Field(default=None, max_length=80)
    beneficiary_character_id: str | None = Field(default=None, max_length=80)
    cost_subject_focus: CostQuestionFocus | None = None
    shell_anchor_tokens: list[str] = Field(default_factory=list, max_length=6)
    shell_anchor_hit: bool = False
    summary: str = Field(default="", max_length=220)


class TurnSemanticPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(default=0, ge=0)
    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    question_plan: TurnSemanticQuestionPlan
    stake_plan: TurnSemanticStakePlan = Field(default_factory=TurnSemanticStakePlan)
    event_plan: TurnSemanticEventPlan = Field(default_factory=TurnSemanticEventPlan)
    payoff_plan: TurnSemanticPayoffPlan = Field(default_factory=TurnSemanticPayoffPlan)
    style_plan: TurnSemanticStylePlan = Field(default_factory=TurnSemanticStylePlan)
    summary: str = Field(default="", max_length=220)


class UrbanWorldState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    story_id: str = Field(min_length=1)
    status: Literal["active", "completed", "expired"] = "active"
    turn_index: int = Field(default=0, ge=0)
    segment_index: int = Field(default=0, ge=0)
    segment_enter_turn_index: int = Field(default=0, ge=0)
    segment_progress: int = Field(default=0, ge=0)
    scene_heat: int = Field(default=0, ge=0, le=6)
    public_image: int = Field(default=3, ge=0, le=6)
    relationship_debt_pressure: int = Field(default=0, ge=0, le=6)
    public_wave_pressure: int = Field(default=0, ge=0, le=6)
    secret_pressure: int = Field(default=0, ge=0, le=6)
    npc_action_pressure: int = Field(default=0, ge=0, le=6)
    secret_exposure: int = Field(default=0, ge=0, le=6)
    route_lock: int = Field(default=0, ge=0, le=6)
    current_route_target_id: str | None = None
    route_scores_by_target: dict[str, int] = Field(default_factory=dict)
    active_beat_delta_pack: BeatDeltaPack
    pending_beat_delta_pack: BeatDeltaPack | None = None
    delta_pack_snapshot_id: str = Field(min_length=1, max_length=80)
    delta_pack_job_status: BeatDeltaJobStatus = "idle"
    delta_pack_journal: list[BeatDeltaJournalEntry] = Field(default_factory=list, max_length=12)
    lane_counts: dict[str, int] = Field(default_factory=dict)
    lane_counts_by_target: dict[str, dict[str, int]] = Field(default_factory=dict)
    irreversible_flags: list[str] = Field(default_factory=list, max_length=8)
    relationships: dict[str, UrbanRelationshipTargetState] = Field(default_factory=dict)
    npc_mind_states: dict[str, NpcMindState] = Field(default_factory=dict)
    hook_states: dict[str, HookState] = Field(default_factory=dict)
    known_secret_ids: list[str] = Field(default_factory=list, max_length=8)
    public_event_ids: list[str] = Field(default_factory=list, max_length=8)
    promise_ids: list[str] = Field(default_factory=list, max_length=8)
    betrayal_ids: list[str] = Field(default_factory=list, max_length=8)
    recent_example_bucket_ids: list[str] = Field(default_factory=list, max_length=6)
    recent_clause_family_ids: list[str] = Field(default_factory=list, max_length=6)
    recent_narration_fingerprints: list[str] = Field(default_factory=list, max_length=4)
    recent_narration_phrases: list[str] = Field(default_factory=list, max_length=4)
    recent_narration_pattern_fingerprints: list[str] = Field(default_factory=list, max_length=4)
    narration_event_log: list[NarrationEventEntry] = Field(default_factory=list, max_length=16)
    narration_segment_summaries: list[NarrationSegmentSummary] = Field(default_factory=list, max_length=4)
    scene_question_states: dict[str, SceneQuestionStateRecord] = Field(default_factory=dict)
    callback_queue: list[CallbackQueueItem] = Field(default_factory=list, max_length=8)
    unresolved_costs: list[UnresolvedCostRecord] = Field(default_factory=list, max_length=12)
    causal_contract_records: dict[str, CausalContractStateRecord] = Field(default_factory=dict)
    latent_events: list[LatentEvent] = Field(default_factory=list, max_length=6)
    segment_id: str = Field(min_length=1)
    scene_frame: RelationshipSceneFrame = "private"
    venue_id: str = Field(min_length=1, max_length=120)
    active_character_ids: list[str] = Field(default_factory=list, max_length=3)
    witness_pressure: int = Field(default=1, ge=0, le=3)
    ending_id: str | None = None
    ending_summary: str | None = Field(default=None, max_length=220)
    narration: str = Field(default="", max_length=4000)
    story_actions: list[UrbanSuggestedAction] = Field(default_factory=list, max_length=3)
    control_actions: list[UrbanControlAction] = Field(default_factory=list, max_length=3)
    suggested_actions: list[UrbanSuggestedAction] = Field(default_factory=list, max_length=3)
    last_turn_global_deltas: dict[str, int] = Field(default_factory=dict)
    last_turn_relationship_deltas: dict[str, dict[str, int]] = Field(default_factory=dict)
    last_turn_reaction_causes: dict[str, list[str]] = Field(default_factory=dict)
    last_turn_latent_ops: list[str] = Field(default_factory=list, max_length=6)
    last_turn_latent_feedback: list[str] = Field(default_factory=list, max_length=4)
    last_turn_triggered_event_id: str | None = Field(default=None, max_length=80)
    last_turn_control_resolution: UrbanControlResolution | None = None
    last_turn_utility_delta_by_character: dict[str, int] = Field(default_factory=dict)
    last_turn_utility_delta_top: list[NpcUtilityDeltaItem] = Field(default_factory=list, max_length=3)
    last_turn_cost_route: CostRouteRecord | None = None
    last_turn_propagation_edge: ShellPropagationEdgeRecord | None = None
    last_turn_scene_question_state: SceneQuestionStateRecord | None = None
    last_turn_callback_status: CallbackTurnStatusRecord | None = None
    last_turn_causal_receipts: list[str] = Field(default_factory=list, max_length=6)
    last_turn_semantic_plan: TurnSemanticPlan | None = None
    last_turn_story_debug_summary: str | None = Field(default=None, max_length=220)
    latent_radar: list[UrbanLatentRadarItem] = Field(default_factory=list, max_length=4)
    last_turn_intent_feedback: list[str] = Field(default_factory=list, max_length=4)
    last_turn_tags: list[str] = Field(default_factory=list, max_length=8)
    last_turn_consequences: list[str] = Field(default_factory=list, max_length=8)
    last_turn_revealed_secret_ids: list[str] = Field(default_factory=list, max_length=4)
    last_turn_escalations: list[TurnEscalationRecord] = Field(default_factory=list, max_length=1)
    last_turn_public_event_text: str | None = Field(default=None, max_length=220)
    last_turn_pain_text: str | None = Field(default=None, max_length=220)
    last_turn_no_return_text: str | None = Field(default=None, max_length=220)


class UrbanSuggestedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str = Field(min_length=1)
    lane_id: SuggestionLaneId
    label: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=220)
    move_family: RelationshipMoveFamily
    target_id: str | None = None
    scene_frame: RelationshipSceneFrame = "private"


class SemanticEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_type: str = Field(min_length=1, max_length=60)
    target_id: str | None = Field(default=None, max_length=120)
    detail: str = Field(default="", max_length=220)


class UrbanTurnIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_text: str = Field(min_length=1, max_length=2000)
    lane_id: SuggestionLaneId | None = None
    move_family: RelationshipMoveFamily
    target_id: str | None = None
    scene_frame: RelationshipSceneFrame = "private"
    control_action: LatentEventControl = "none"
    control_source: ControlSource = "none"
    control_target_kind: LatentEventKind | None = None
    control_target_id: str | None = Field(default=None, max_length=120)
    control_target_mode: ControlTargetKind | None = None
    confidence: TurnConfidence = "medium"
    intent_confidence: float = Field(default=0.5, ge=0, le=1)
    intent_compile_source: IntentCompileSource = "heuristic_fallback"
    deviation_type: IntentDeviationType = "none"
    deviation_note: str | None = Field(default=None, max_length=220)
    alternatives: list[str] = Field(default_factory=list, max_length=3)
    mapped_suggestion_id: str | None = Field(default=None, max_length=120)
    semantic_effects: list[SemanticEffect] = Field(default_factory=list, max_length=6)


class UrbanTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: CompiledPlayPlan
    state: UrbanWorldState
    narration: str = Field(min_length=1, max_length=4000)
    story_actions: list[UrbanSuggestedAction] = Field(default_factory=list, max_length=3)
    control_actions: list[UrbanControlAction] = Field(default_factory=list, max_length=3)
    suggested_actions: list[UrbanSuggestedAction] = Field(default_factory=list, max_length=3)
    triggered_latent_event: TurnEscalationRecord | None = None
    latent_radar: list[UrbanLatentRadarItem] = Field(default_factory=list, max_length=4)
    control_resolution: UrbanControlResolution | None = None
    segment_advanced: bool = False
    ending_triggered: bool = False
    consequence_tags: list[str] = Field(default_factory=list, max_length=8)
    progress_summary: str = Field(min_length=1, max_length=220)
    intent: UrbanTurnIntent
    intent_stage_diagnostics: dict[str, int | float | str | bool | list[str]] = Field(default_factory=dict)
