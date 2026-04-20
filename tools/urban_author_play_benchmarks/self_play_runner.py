from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed, wait
import json
import random
import threading
import time
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author_v2.contracts import (
    AcceptedBlueprint,
    CompiledPlayPlan,
    CompiledSegment,
    SuggestionLaneId,
    TurnConfidence,
    UrbanPreviewBlueprint,
)
from rpg_backend.author_v2.product_adapters import author_preview_from_blueprint, author_story_summary_from_package
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.config import Settings, get_settings
from rpg_backend.library.service import StoryLibraryService
from rpg_backend.library.storage import SQLiteStoryLibraryStorage
from rpg_backend.play.contracts import PlayDraftIntentRequest, PlayTurnRequest, PlayTurnTrace
from rpg_backend.play.service import PlaySessionService
from rpg_backend.play.storage import SQLitePlaySessionStorage
from rpg_backend.play_v2.contracts import (
    UrbanSuggestedAction,
    UrbanTurnIntent,
    UrbanTurnResult,
    UrbanWorldState,
)
from rpg_backend.play_v2.runtime import build_suggested_actions, parse_turn_intent
from rpg_backend.responses_transport import build_openai_client
from tools.urban_author_play_benchmarks import llm_text_audit as llm_text_audit_tools
from tools.urban_author_play_benchmarks import play_eval as play_eval_tools
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase, mini_gold_set, native_cn_gold_10, v1_topic_gold_14

SelfPlayPersonaId = Literal["baodian", "qinggan", "wenjian", "zhandui", "fuchou", "chaos"]
SelfPlayExecutionMode = Literal["parallel", "sequential"]
SelfPlayTurnInputMode = Literal["free_input", "select_id"]
PersonaOrderSource = Literal["template", "shell", "default"]
SELF_PLAY_PERSONA_ORDER: tuple[SelfPlayPersonaId, ...] = ("baodian", "qinggan", "wenjian", "zhandui", "fuchou")
LIVE_AUTHOR_MODE: Literal["live_priority"] = "live_priority"
PILOT_CASE_ID = "wealth_short_wedding"
DEFAULT_DECISION_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_REPAIR_ONLY_TURNS = 2
DEFAULT_SELECT_ID_PROBABILITY = 0.1
DEFAULT_TYPING_RHYTHM_ENABLED = False
DEFAULT_DRAFT_INTENT_PROBABILITY = 0.3
DEFAULT_DRAFT_CALL_COUNT_MIN = 1
DEFAULT_DRAFT_CALL_COUNT_MAX = 2
DEFAULT_DRAFT_DEBOUNCE_MS = 350
DEFAULT_MAX_LLM_TURN_AUDITS_PER_PERSONA = 2
LLM_SESSION_AUDIT_MIN_KEY_TURNS = 4
LLM_SESSION_AUDIT_MAX_KEY_TURNS = 4
LLM_SESSION_AUDIT_MAX_ESTIMATED_TOKENS = 7_000
LLM_SESSION_AUDIT_CHARS_PER_TOKEN = 2
LLM_SESSION_AUDIT_TEXT_CAP_STEPS: tuple[tuple[int, int, int], ...] = (
    (240, 120, 90),
    (200, 96, 72),
    (160, 80, 56),
    (120, 64, 48),
)
VALID_LANE_IDS: tuple[SuggestionLaneId, ...] = ("relationship", "side", "burst")
PLAY_LENGTH_PRESETS: tuple[str, ...] = ("5_8", "10_12", "12_15", "15_20", "20_25", "30_45")
AUTHOR_LIVE_STAGES: tuple[str, ...] = (
    "synthesize_preview_blueprint",
    "plan_cast_slots",
    "allocate_segment_contracts",
    "compile_segment_playbooks",
)
CONFIDENCE_TO_SCORE: dict[TurnConfidence, float] = {"high": 1.0, "medium": 0.5, "low": 0.0}
ENDING_STRENGTH: dict[str, int] = {
    "burned_alone": 1,
    "pyrrhic_control": 2,
}


def _source_live_metrics(quality_trace: list[dict[str, Any]]) -> tuple[int, str]:
    by_stage = {
        str(record.get("stage")): record
        for record in quality_trace
        if isinstance(record, dict) and str(record.get("stage")) in AUTHOR_LIVE_STAGES
    }
    live_depth_score = sum(1 for stage in AUTHOR_LIVE_STAGES if bool(by_stage.get(stage, {}).get("used_live_output")))
    mode_tokens: list[str] = []
    for stage in AUTHOR_LIVE_STAGES:
        record = by_stage.get(stage, {})
        actual_mode = str(record.get("actual_mode") or record.get("source") or "deterministic")
        actual_modes = [str(mode) for mode in list(record.get("actual_modes") or []) if str(mode)]
        if actual_mode == "mixed" and actual_modes:
            mode_tokens.append("+".join(actual_modes))
        else:
            mode_tokens.append(actual_mode)
    return live_depth_score, "->".join(mode_tokens)


def _strict_no_repair_fallback_enabled() -> bool:
    return bool(get_settings().internal_test_strict_no_repair_fallback)


def _first_quality_trace_repair_or_fallback(quality_trace: list[dict[str, Any]]) -> str | None:
    for record in quality_trace:
        outcome = str(record.get("outcome") or "").strip().casefold()
        if outcome not in {"repaired", "fallback"}:
            continue
        stage = str(record.get("stage") or "unknown")
        reasons = ",".join(str(item) for item in list(record.get("reasons") or [])[:6]) or "none"
        return f"{stage}:{outcome}:{reasons}"
    return None


def _strict_runtime_repair_or_fallback_reason(
    *,
    turn_trace: PlayTurnTrace | None,
    state: UrbanWorldState,
) -> str | None:
    usage = dict(turn_trace.interpret_usage or {}) if turn_trace is not None else {}
    reasons: list[str] = []
    compose_fallback = str(usage.get("fallback_reason") or "").strip()
    if compose_fallback and compose_fallback != "none":
        reasons.append(f"compose:{compose_fallback}")
    voice_fallback = str(usage.get("voice_fallback_reason") or "").strip()
    if voice_fallback and voice_fallback != "none":
        reasons.append(f"voice:{voice_fallback}")
    return ";".join(reasons) if reasons else None


def _draft_fragments(input_text: str, *, call_count: int) -> list[str]:
    text = str(input_text or "").strip()
    if not text:
        return []
    target_count = max(1, int(call_count))
    if target_count == 1 or len(text) <= 1:
        return [text]
    fragments: list[str] = []
    for index in range(target_count):
        if index == target_count - 1:
            fragment = text
        else:
            ratio = float(index + 1) / float(target_count)
            cut = max(1, min(len(text) - 1, int(round(len(text) * ratio))))
            fragment = text[:cut].strip() or text
        if not fragments or fragment != fragments[-1]:
            fragments.append(fragment)
    if fragments[-1] != text:
        fragments.append(text)
    return fragments


def _dedupe_persona_ids(ordered: tuple[SelfPlayPersonaId, ...]) -> tuple[SelfPlayPersonaId, ...]:
    deduped: list[SelfPlayPersonaId] = []
    seen: set[SelfPlayPersonaId] = set()
    for persona_id in ordered:
        if persona_id in PERSONA_CONFIGS and persona_id not in seen:
            seen.add(persona_id)
            deduped.append(persona_id)
    for persona_id in SELF_PLAY_PERSONA_ORDER:
        if persona_id not in seen:
            deduped.append(persona_id)
            seen.add(persona_id)
    return tuple(deduped)


def _ordered_persona_ids_for_plan(plan: CompiledPlayPlan) -> tuple[SelfPlayPersonaId, ...]:
    return tuple(_resolve_persona_pack_for_plan(plan).ordered_persona_ids)


class PersonaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: SelfPlayPersonaId
    label: str = Field(min_length=1, max_length=32)
    objective: str = Field(min_length=1, max_length=220)
    preference_summary: str = Field(min_length=1, max_length=220)
    preferred_moves: list[str] = Field(min_length=2, max_length=8)
    avoids_public_until_terminal: bool = False


class PersonaPackEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: SelfPlayPersonaId
    label: str = Field(min_length=1, max_length=32)
    rank: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1, max_length=220)
    objective: str = Field(min_length=1, max_length=220)
    preferred_moves: list[str] = Field(min_length=2, max_length=8)


class PersonaPackResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: PersonaOrderSource
    source_key: str = Field(min_length=1, max_length=80)
    ordered_persona_ids: list[SelfPlayPersonaId] = Field(min_length=3, max_length=5)
    entries: list[PersonaPackEntry] = Field(min_length=3, max_length=5)


PERSONA_CONFIGS: dict[SelfPlayPersonaId, PersonaConfig] = {
    "baodian": PersonaConfig(
        persona_id="baodian",
        label="爆点型",
        objective="最大化公开失控、秘密曝光和可传播的场面张力。",
        preference_summary="偏好公开撕破、逼问、曝光和把局势推到不可逆转。",
        preferred_moves=["public_reveal", "accuse", "probe_secret", "jealousy_trigger", "betray"],
    ),
    "qinggan": PersonaConfig(
        persona_id="qinggan",
        label="情感型",
        objective="最大化亲密推进、路线情感 payoff 和被站在一起的感觉。",
        preference_summary="偏好护人、暧昧、坦白和稳定推进一条关系线。",
        preferred_moves=["flirt", "comfort", "private_confession", "ally_with"],
    ),
    "wenjian": PersonaConfig(
        persona_id="wenjian",
        label="稳健型",
        objective="尽量控住风险，拿到干净、可控的结局。",
        preference_summary="偏好稳场、低风险推进和尽量避免不必要的公开翻车。",
        preferred_moves=["comfort", "deflect", "private_confession", "ally_with"],
        avoids_public_until_terminal=True,
    ),
    "zhandui": PersonaConfig(
        persona_id="zhandui",
        label="站队型",
        objective="尽早锁定阵营，把故事往不可逆的站队结局推进。",
        preference_summary="偏好站边、压场、逼表态和尽快形成不可逆立场。",
        preferred_moves=["ally_with", "comfort", "accuse", "deflect"],
    ),
    "fuchou": PersonaConfig(
        persona_id="fuchou",
        label="复仇型",
        objective="优先惩罚最危险的人，即使要付出额外代价。",
        preference_summary="偏好逼问、公开揭露、反手出卖和把秘密撬出来。",
        preferred_moves=["accuse", "public_reveal", "betray", "probe_secret"],
    ),
    "chaos": PersonaConfig(
        persona_id="chaos",
        label="失控型",
        objective="用非常规表达和越界动作去压测系统回正轨能力与后果可感知性。",
        preference_summary="偏好自由文本、反常策略、突然转向和对控雷语义的极限拉扯。",
        preferred_moves=["public_reveal", "betray", "probe_secret", "deflect", "jealousy_trigger"],
    ),
}

PERSONA_ORDER_BY_SHELL: dict[str, tuple[SelfPlayPersonaId, ...]] = {
    "wealth_families": ("zhandui", "wenjian", "baodian", "fuchou", "qinggan"),
    "office_power": ("wenjian", "zhandui", "baodian", "qinggan", "fuchou"),
    "entertainment_scandal": ("baodian", "fuchou", "zhandui", "wenjian", "qinggan"),
    "campus_romance": ("qinggan", "zhandui", "wenjian", "baodian", "fuchou"),
}

PERSONA_ORDER_BY_TEMPLATE: dict[str, tuple[SelfPlayPersonaId, ...]] = {
    "entertainment_livestream_hotsearch_flip": ("baodian", "fuchou", "zhandui", "wenjian", "qinggan"),
    "entertainment_awards_seating_shift": ("zhandui", "baodian", "wenjian", "fuchou", "qinggan"),
    "campus_homecoming_recording": ("qinggan", "zhandui", "wenjian", "baodian", "fuchou"),
    "campus_mentor_review_sideswitch": ("zhandui", "wenjian", "qinggan", "baodian", "fuchou"),
    "campus_club_campaign_flip": ("zhandui", "qinggan", "wenjian", "baodian", "fuchou"),
}


def _persona_order_source(
    plan: CompiledPlayPlan,
) -> tuple[PersonaOrderSource, str, tuple[SelfPlayPersonaId, ...]]:
    template_order = PERSONA_ORDER_BY_TEMPLATE.get(plan.template_id)
    if template_order is not None:
        return "template", plan.template_id, template_order
    shell_order = PERSONA_ORDER_BY_SHELL.get(plan.story_shell_id)
    if shell_order is not None:
        return "shell", plan.story_shell_id, shell_order
    return "default", "default", SELF_PLAY_PERSONA_ORDER


def _persona_selection_reason(
    *,
    source: PersonaOrderSource,
    source_key: str,
    rank: int,
    persona: PersonaConfig,
) -> str:
    if source == "template":
        return f"模板 `{source_key}` 的优先顺位第{rank}位，主打{persona.label}的推进方式。"
    if source == "shell":
        return f"壳子 `{source_key}` 的优先顺位第{rank}位，优先观察{persona.label}路径。"
    return f"默认 persona pack 顺位第{rank}位，用于保留策略覆盖面。"


def _resolve_persona_pack_for_plan(plan: CompiledPlayPlan) -> PersonaPackResolution:
    source, source_key, ordered = _persona_order_source(plan)
    persona_ids = _dedupe_persona_ids(ordered)
    entries: list[PersonaPackEntry] = []
    for rank, persona_id in enumerate(persona_ids, start=1):
        persona = PERSONA_CONFIGS[persona_id]
        entries.append(
            PersonaPackEntry(
                persona_id=persona.persona_id,
                label=persona.label,
                rank=rank,
                reason=_persona_selection_reason(
                    source=source,
                    source_key=source_key,
                    rank=rank,
                    persona=persona,
                ),
                objective=persona.objective,
                preferred_moves=list(persona.preferred_moves),
            )
        )
    return PersonaPackResolution(
        source=source,
        source_key=source_key,
        ordered_persona_ids=list(persona_ids),
        entries=entries,
    )


class PlayerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str = Field(min_length=1, max_length=32)
    action_text: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=220)
    confidence: TurnConfidence = "medium"
    target_hint: str | None = Field(default=None, max_length=80)


class SelfPlayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    live_mode: str = Field(min_length=1)
    execution_mode: SelfPlayExecutionMode = "parallel"
    max_workers: int = Field(default=3, ge=1, le=8)
    decision_timeout_seconds: float = Field(default=DEFAULT_DECISION_TIMEOUT_SECONDS, gt=0)
    max_repair_only_turns: int = Field(default=DEFAULT_MAX_REPAIR_ONLY_TURNS, ge=1, le=8)
    select_id_probability: float = Field(default=DEFAULT_SELECT_ID_PROBABILITY, ge=0, le=1)
    typing_rhythm_enabled: bool = DEFAULT_TYPING_RHYTHM_ENABLED
    draft_intent_probability: float = Field(default=DEFAULT_DRAFT_INTENT_PROBABILITY, ge=0, le=1)
    draft_call_count_min: int = Field(default=DEFAULT_DRAFT_CALL_COUNT_MIN, ge=1, le=8)
    draft_call_count_max: int = Field(default=DEFAULT_DRAFT_CALL_COUNT_MAX, ge=1, le=8)
    draft_debounce_ms: int = Field(default=DEFAULT_DRAFT_DEBOUNCE_MS, ge=0, le=5000)
    session_play_eval_persona_limit: int | None = Field(default=None, ge=1, le=5)
    llm_text_audit_persona_limit: int | None = Field(default=None, ge=1, le=5)
    latency_bucket_rule: Literal["submitted_ids"] = "submitted_ids"
    decision_surface: str = Field(min_length=1)
    scoring_mode: str = Field(min_length=1)
    play_length_preset: str | None = Field(default=None, max_length=16)
    personas: list[PersonaConfig] = Field(min_length=3, max_length=5)


class SelfPlayTurnLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=1)
    persona_id: SelfPlayPersonaId
    play_length_preset: str = Field(min_length=1, max_length=16)
    arc_template_id: str = Field(min_length=1, max_length=32)
    progress_required_by_segment: list[int] = Field(default_factory=list, max_length=8)
    raw_action_text: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=220)
    parse_confidence: TurnConfidence
    repaired: bool = False
    turn_input_mode: SelfPlayTurnInputMode = "free_input"
    submitted_with_selected_ids: bool = False
    selected_lane_id: str | None = None
    selected_move_family: str = Field(min_length=1, max_length=64)
    selected_target_id: str | None = None
    narration: str = Field(min_length=1, max_length=4000)
    progress_summary: str = Field(min_length=1, max_length=220)
    consequence_tags: list[str] = Field(default_factory=list, max_length=8)
    suggested_actions_snapshot: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    next_suggested_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    decision_latency_ms: float = Field(ge=0)
    runtime_latency_ms: float = Field(ge=0)
    total_turn_latency_ms: float = Field(ge=0)
    intent_stage_latency_ms: float = Field(default=0, ge=0)
    intent_stage_input_tokens: int = Field(default=0, ge=0)
    intent_stage_output_tokens: int = Field(default=0, ge=0)
    intent_stage_total_tokens: int = Field(default=0, ge=0)
    intent_llm_total_tokens: int = Field(default=0, ge=0)
    micro_sim_total_tokens: int = Field(default=0, ge=0)
    draft_call_count: int = Field(default=0, ge=0, le=12)
    draft_intent_status: str = Field(default="", max_length=120)
    draft_input_tokens: int = Field(default=0, ge=0)
    draft_output_tokens: int = Field(default=0, ge=0)
    draft_total_tokens: int = Field(default=0, ge=0)
    pre_submit_total_tokens: int = Field(default=0, ge=0)
    post_submit_total_tokens: int = Field(default=0, ge=0)
    play_turn_total_tokens: int = Field(default=0, ge=0)
    compose_input_tokens: int = Field(default=0, ge=0)
    compose_output_tokens: int = Field(default=0, ge=0)
    compose_total_tokens: int = Field(default=0, ge=0)
    compose_latency_ms: float = Field(default=0, ge=0)
    turn_complexity: str = Field(default="normal", max_length=24)
    compose_pass_count: int = Field(default=1, ge=0)
    compose_pass2_retry_count: int = Field(default=0, ge=0)
    compose_pass1_latency_ms: float = Field(default=0, ge=0)
    compose_pass2_latency_ms: float = Field(default=0, ge=0)
    compose_pass2_invalid_reason: str = Field(default="", max_length=120)
    compose_budget_hit: bool = False
    delta_pack_hit: bool = False
    compose_pass2_applied: bool = False
    compose_prewarm_status: str = Field(default="", max_length=120)
    compose_prewarm_hit: bool = False
    compose_prewarm_wait_ms: float = Field(default=0, ge=0)
    compose_prewarm_source: str = Field(default="", max_length=120)
    compose_prewarm_total_tokens: int = Field(default=0, ge=0)
    typing_final_draft_seen: bool = False
    typing_scope_cleared_count: int = Field(default=0, ge=0)
    compose_prewarm_stale_fragment_count: int = Field(default=0, ge=0)
    read_phase_prewarm_tokens: int = Field(default=0, ge=0)
    typing_phase_prewarm_tokens: int = Field(default=0, ge=0)
    submit_phase_tokens: int = Field(default=0, ge=0)
    gateway_acquire_wait_ms: float = Field(default=0, ge=0)
    post_submit_llm_calls: int = Field(default=0, ge=0, le=4)
    single_llm_call_after_submit: bool = False
    intent_llm_gate_reason: str = Field(default="", max_length=120)
    micro_sim_llm_gate_reason: str = Field(default="", max_length=120)
    compose_pass2_gate_reason: str = Field(default="", max_length=120)
    selected_style_case_ids: str = Field(default="", max_length=240)
    soft_avoid_stems: str = Field(default="", max_length=360)
    diversity_guard_hits: int = Field(default=0, ge=0)
    compose_retry_count: int = Field(default=0, ge=0)
    compose_invalid_reason: str = Field(default="", max_length=240)
    blocked_stems: str = Field(default="", max_length=300)
    blocked_stems_hit: bool = False
    storylet_matches_count: int = Field(default=0, ge=0)
    storylet_matches_ids: list[str] = Field(default_factory=list, max_length=3)
    memory_context_active_hooks: int = Field(default=0, ge=0)
    memory_context_revealed_secrets: int = Field(default=0, ge=0)
    memory_context_total_chars_sent: int = Field(default=0, ge=0)
    memory_context_npc_pressure_count: int = Field(default=0, ge=0)
    control_bias_applied: bool = False
    control_bias_reason: str = Field(default="", max_length=120)
    control_bias_from_move: str = Field(default="", max_length=64)
    control_bias_to_move: str = Field(default="", max_length=64)
    content_quality_score: int = Field(ge=0, le=5)
    persona_alignment_score: int = Field(ge=0, le=5)
    notes: list[str] = Field(default_factory=list, max_length=12)
    segment_id: str = Field(min_length=1)
    segment_role: str = Field(min_length=1)
    ending_triggered: bool = False
    agent_confidence: TurnConfidence = "medium"


class SelfPlayRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: SelfPlayPersonaId
    persona_label: str = Field(min_length=1, max_length=32)
    play_length_preset: str = Field(min_length=1, max_length=16)
    arc_template_id: str = Field(min_length=1, max_length=32)
    progress_required_by_segment: list[int] = Field(default_factory=list, max_length=8)
    worker_status: Literal["completed", "stopped", "failed"] = "completed"
    failure_reason: str | None = Field(default=None, max_length=240)
    ending_reached: bool = False
    ending_id: str | None = None
    ending_strength: int = Field(default=0, ge=0, le=3)
    turn_count: int = Field(default=0, ge=0)
    free_input_turn_count: int = Field(default=0, ge=0)
    select_id_turn_count: int = Field(default=0, ge=0)
    avg_content_score: float = Field(default=0, ge=0, le=5)
    avg_persona_alignment_score: float = Field(default=0, ge=0, le=5)
    mean_turn_latency_ms: float = Field(default=0, ge=0)
    max_turn_latency_ms: float = Field(default=0, ge=0)
    repair_count: int = Field(default=0, ge=0)
    avg_parse_confidence: float = Field(default=0, ge=0, le=1)
    parse_confidence_distribution: dict[str, int] = Field(default_factory=dict)
    lane_counts: dict[str, int] = Field(default_factory=dict)
    route_target_trajectory: list[str] = Field(default_factory=list)
    play_total_tokens: int = Field(default=0, ge=0)
    pre_submit_total_tokens: int = Field(default=0, ge=0)
    post_submit_total_tokens: int = Field(default=0, ge=0)
    pre_submit_share: float = Field(default=0, ge=0, le=1)
    post_submit_share: float = Field(default=0, ge=0, le=1)
    free_input_play_total_tokens: int = Field(default=0, ge=0)
    select_id_play_total_tokens: int = Field(default=0, ge=0)
    best_turn_index: int | None = None
    worst_turn_index: int | None = None
    ending_summary: str | None = Field(default=None, max_length=220)


class SelfPlayComparisonSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    strongest_ending_persona_id: SelfPlayPersonaId
    strongest_content_persona_id: SelfPlayPersonaId
    fastest_persona_id: SelfPlayPersonaId
    failed_persona_ids: list[SelfPlayPersonaId] = Field(default_factory=list)
    source_live_depth_score: int = Field(default=0, ge=0)
    source_final_mode_path: str = Field(default="deterministic", min_length=1)
    supports_distinct_playstyles: bool = False
    playstyle_collapse: bool = False
    divergence_by_segment: dict[str, dict[str, Any]] = Field(default_factory=dict)
    failure_patterns: list[str] = Field(default_factory=list, max_length=8)
    persona_summaries: dict[str, SelfPlayRunSummary]


class PlayerTurnContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: PersonaConfig
    turn_index: int = Field(ge=1)
    story_id: str = Field(min_length=1)
    social_arena: str = Field(min_length=1, max_length=120)
    segment_id: str = Field(min_length=1)
    segment_role: str = Field(min_length=1, max_length=32)
    segment_summary: str = Field(min_length=1, max_length=600)
    active_characters: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    suggested_actions: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    state_snapshot: dict[str, Any]
    last_turn_outcome: dict[str, Any] | None = None


class PlayerAgentAdapter(ABC):
    def __init__(self, persona: PersonaConfig) -> None:
        self.persona = persona

    def open(self) -> None:
        return None

    def allow_decision_fallback(self) -> bool:
        return False

    @abstractmethod
    def decide(self, context: PlayerTurnContext) -> PlayerDecision:
        raise NotImplementedError

    def close(self) -> None:
        return None


class PersistentPlayerBackend(Protocol):
    def open_session(self, *, persona: PersonaConfig, system_prompt: str) -> Any: ...

    def decide(self, session: Any, *, context: dict[str, Any]) -> PlayerDecision: ...

    def close_session(self, session: Any) -> None: ...


class SubagentPlayerAdapter(PlayerAgentAdapter):
    def __init__(
        self,
        persona: PersonaConfig,
        *,
        backend: PersistentPlayerBackend,
        allow_decision_fallback: bool = True,
    ) -> None:
        super().__init__(persona)
        self._backend = backend
        self._allow_decision_fallback = allow_decision_fallback
        self._session: Any = None
        self._system_prompt = _persona_system_prompt(persona)

    def open(self) -> None:
        if self._session is None:
            self._session = self._backend.open_session(persona=self.persona, system_prompt=self._system_prompt)

    def decide(self, context: PlayerTurnContext) -> PlayerDecision:
        self.open()
        assert self._session is not None
        return self._backend.decide(self._session, context=context.model_dump(mode="json"))

    def close(self) -> None:
        if self._session is not None:
            self._backend.close_session(self._session)
            self._session = None

    def allow_decision_fallback(self) -> bool:
        return self._allow_decision_fallback


class ScriptedPlayerAdapter(PlayerAgentAdapter):
    def __init__(
        self,
        persona: PersonaConfig,
        *,
        scripted_decisions: list[PlayerDecision] | None = None,
        decision_delay_ms: int = 0,
    ) -> None:
        super().__init__(persona)
        self._scripted_decisions = list(scripted_decisions or [])
        self._decision_delay_ms = max(0, decision_delay_ms)

    def decide(self, context: PlayerTurnContext) -> PlayerDecision:
        if self._decision_delay_ms:
            time.sleep(self._decision_delay_ms / 1000)
        if self._scripted_decisions:
            return self._scripted_decisions.pop(0)
        suggestion = _best_suggestion_for_persona(
            self.persona.persona_id,
            [UrbanSuggestedAction(**item) for item in context.suggested_actions],
            context.state_snapshot,
            context.segment_role,
        )
        target_name = _character_name_by_id(context.active_characters, suggestion.target_id) or "他"
        action_templates = {
            "public_reveal": f"我要当众把证据甩给{target_name}，让所有人现在就听见真相。",
            "accuse": f"我现在就逼问{target_name}，让他把最难听的话自己说出来。",
            "probe_secret": f"先试探{target_name}手里到底握着什么秘密，再决定要不要翻桌。",
            "jealousy_trigger": f"我要故意刺激{target_name}，逼他先失控。",
            "betray": f"如果必须翻盘，我会先卖掉{target_name}保住主动权。",
            "flirt": f"我先靠近{target_name}，让他在最乱的时候只看我这边。",
            "comfort": f"我先护住{target_name}，让他知道我不会在这个场面丢下他。",
            "private_confession": f"我想私下对{target_name}坦白真正的底牌，换他站我。",
            "ally_with": f"我准备和{target_name}站到同一边，先把局稳住。",
            "deflect": "我先把场面压住，不让别人抢走主动权。",
        }
        reason_templates = {
            "baodian": "我要把这一回合打成能被记住的名场面。",
            "qinggan": "我要把关系推进到足够让人上头的位置。",
            "wenjian": "我要先保住节奏和退路，再决定要不要冒险。",
            "zhandui": "我要尽快把阵营钉死，不给局面留模糊空间。",
            "fuchou": "我要先让最危险的人付出代价，再谈别的。",
            "chaos": "我要用自由动作压测系统能不能把离谱输入稳稳拉回剧情。",
        }
        return PlayerDecision(
            lane_id=suggestion.lane_id,
            action_text=action_templates[suggestion.move_family],
            reason=reason_templates[self.persona.persona_id],
            confidence="high",
            target_hint=target_name,
        )


def _persona_system_prompt(persona: PersonaConfig) -> str:
    return (
        f"你是都市关系戏自玩 agent，当前人格是{persona.label}。\n"
        f"目标：{persona.objective}\n"
        f"偏好：{persona.preference_summary}\n"
        "每回合只返回一个 JSON 对象："
        '{"lane_id":"relationship|side|burst","action_text":"...","reason":"...","confidence":"high|medium|low","target_hint":"可选"}。\n'
        "lane_id 是强约束，表示你想走关系线、站队线还是爆点线。\n"
        "不要解释，不要输出 markdown，不要输出额外字段。"
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if not candidate:
        raise ValueError("empty response")
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except Exception:  # noqa: BLE001
        pass
    left = candidate.find("{")
    right = candidate.rfind("}")
    if left >= 0 and right > left:
        payload = json.loads(candidate[left : right + 1])
        if isinstance(payload, dict):
            return payload
    raise ValueError("response is not a json object")


class ResponsesPlayBackend(PersistentPlayerBackend):
    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._base_url = self._settings.resolved_play_responses_base_url()
        self._use_session_cache = self._settings.resolved_play_responses_use_session_cache()
        self._json_content_type_hint = bool(self._settings.responses_json_content_type_hint)
        self._api_key_pool = tuple(self._settings.play_responses_api_key_pool())
        if not self._api_key_pool and self._settings.resolved_play_responses_api_key().strip():
            self._api_key_pool = (self._settings.resolved_play_responses_api_key().strip(),)
        self._api_key_cursor = 0
        self._api_key_lock = threading.Lock()
        self._model = self._settings.resolved_play_responses_model()
        self._timeout = self._settings.responses_timeout_seconds

    def _sample_api_key(self) -> str:
        if not self._api_key_pool:
            raise RuntimeError("missing APP_RESPONSES_PLAY_API_KEY/APP_RESPONSES_PLAY_API_KEYS for llm player backend")
        if len(self._api_key_pool) == 1:
            return self._api_key_pool[0]
        with self._api_key_lock:
            index = self._api_key_cursor
            self._api_key_cursor = (self._api_key_cursor + 1) % len(self._api_key_pool)
        return self._api_key_pool[index]

    def _build_client(self, api_key: str) -> Any:
        return build_openai_client(
            base_url=self._base_url,
            api_key=api_key,
            use_session_cache=self._use_session_cache,
            session_cache_header=self._settings.responses_session_cache_header,
            session_cache_value=self._settings.responses_session_cache_value,
            requests_per_minute=self._settings.responses_play_requests_per_minute,
            rate_limit_scope="play_eval:llm_player",
        )

    def open_session(self, *, persona: PersonaConfig, system_prompt: str) -> dict[str, Any]:
        return {
            "persona_id": persona.persona_id,
            "system_prompt": system_prompt,
            "previous_response_id": None,
        }

    def decide(self, session: dict[str, Any], *, context: dict[str, Any]) -> PlayerDecision:
        payload = {
            "task": "为当前回合选择一个动作",
            "context": context,
            "output_contract": {
                "lane_id": "relationship|side|burst",
                "action_text": "string",
                "reason": "string",
                "confidence": "high|medium|low",
                "target_hint": "optional string",
            },
        }
        request_kwargs = {
            "model": self._model,
            "instructions": str(session["system_prompt"]),
            "input": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "timeout": self._timeout,
            "max_output_tokens": 320,
            "temperature": 0.0,
            "extra_body": {
                "response_format": {"type": "json_object"},
                **({"content_type": "json"} if self._json_content_type_hint else {}),
            },
        }
        api_key = self._sample_api_key()
        client = self._build_client(api_key)
        try:
            response = client.responses.create(**request_kwargs)
        except Exception:  # noqa: BLE001
            fallback_kwargs = dict(request_kwargs)
            fallback_kwargs.pop("extra_body", None)
            response = client.responses.create(**fallback_kwargs)
        parsed = _parse_json_object(str(getattr(response, "output_text", "") or ""))
        session["previous_response_id"] = getattr(response, "id", None)
        return PlayerDecision.model_validate(parsed)

    def close_session(self, session: dict[str, Any]) -> None:
        session["previous_response_id"] = None


def _to_jsonable(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json")
    if isinstance(payload, list):
        return [_to_jsonable(item) for item in payload]
    if isinstance(payload, tuple):
        return [_to_jsonable(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _to_jsonable(value) for key, value in payload.items()}
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True))


def _write_jsonl(path: Path, rows: list[BaseModel]) -> None:
    path.write_text("\n".join(json.dumps(row.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) for row in rows))


def _write_failure_report(path: Path, *, stage: str, detail: str) -> None:
    path.write_text("\n".join(["# Self-Play Failure", "", f"- stage: `{stage}`", f"- detail: {detail}"]))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _pilot_case(case_id: str = PILOT_CASE_ID, *, case_catalog: list[UrbanGoldCase] | None = None) -> UrbanGoldCase:
    catalogs = [list(case_catalog or []), native_cn_gold_10(), v1_topic_gold_14()]
    for catalog in catalogs:
        for case in catalog:
            if case.case_id == case_id:
                return case
    raise ValueError(f"unknown pilot case: {case_id}")


def _load_author_artifacts(
    source_artifacts_dir: Path,
) -> tuple[RelationshipDramaV2Package, list[dict[str, Any]], list[dict[str, Any]]]:
    preview = UrbanPreviewBlueprint.model_validate(_read_json(source_artifacts_dir / "preview_blueprint.json"))
    accepted = AcceptedBlueprint.model_validate(_read_json(source_artifacts_dir / "accepted_blueprint.json"))
    urban_bundle_payload = _read_json(source_artifacts_dir / "urban_bundle.json")
    play_plan = CompiledPlayPlan.model_validate(_read_json(source_artifacts_dir / "compiled_play_plan.json"))
    quality_trace = list(_read_json(source_artifacts_dir / "quality_trace.json"))
    llm_call_trace = list(_read_json(source_artifacts_dir / "llm_call_trace.json"))
    package = RelationshipDramaV2Package(
        preview_blueprint=preview,
        accepted_blueprint=accepted,
        urban_bundle=urban_bundle_payload,
        compiled_play_plan=play_plan,
        quality_trace=quality_trace,
        llm_call_trace=llm_call_trace,
    )
    return package, quality_trace, llm_call_trace


def _character_name_by_id(active_characters: list[dict[str, Any]], target_id: str | None) -> str | None:
    if target_id is None:
        return None
    for character in active_characters:
        if character.get("character_id") == target_id:
            return str(character.get("display_name") or character.get("name") or "")
    return None


def _segment_for_state(plan: CompiledPlayPlan, state: UrbanWorldState) -> CompiledSegment:
    return plan.segments[min(state.segment_index, len(plan.segments) - 1)]


def _active_character_snapshot(plan: CompiledPlayPlan, state: UrbanWorldState) -> list[dict[str, Any]]:
    cast_by_id = {member.character_id: member for member in plan.cast}
    snapshot: list[dict[str, Any]] = []
    for character_id in state.active_character_ids[:3]:
        member = cast_by_id.get(character_id)
        if member is None:
            continue
        snapshot.append(
            {
                "character_id": member.character_id,
                "display_name": member.display_name,
                "public_role": member.public_role,
                "is_route_target": member.is_route_target,
                "charisma_hook": member.charisma_hook,
                "danger_hook": member.danger_hook,
            }
        )
    return snapshot


def _state_snapshot(plan: CompiledPlayPlan, state: UrbanWorldState) -> dict[str, Any]:
    relationships = {
        character_id: relationship.model_dump(mode="json")
        for character_id, relationship in state.relationships.items()
        if character_id in set(state.active_character_ids + ([state.current_route_target_id] if state.current_route_target_id else []))
    }
    return {
        "segment_id": state.segment_id,
        "segment_index": state.segment_index,
        "scene_heat": state.scene_heat,
        "public_image": state.public_image,
        "secret_exposure": state.secret_exposure,
        "route_lock": state.route_lock,
        "current_route_target_id": state.current_route_target_id,
        "route_scores_by_target": dict(state.route_scores_by_target),
        "known_secret_ids": list(state.known_secret_ids),
        "active_character_ids": list(state.active_character_ids),
        "relationships": relationships,
        "social_arena": plan.social_arena,
    }


def _last_turn_snapshot(last_result: UrbanTurnResult | None) -> dict[str, Any] | None:
    if last_result is None:
        return None
    return {
        "narration": last_result.narration,
        "progress_summary": last_result.progress_summary,
        "consequence_tags": list(last_result.consequence_tags),
        "segment_advanced": last_result.segment_advanced,
        "ending_triggered": last_result.ending_triggered,
        "selected_lane_id": last_result.intent.lane_id,
        "selected_move_family": last_result.intent.move_family,
        "selected_target_id": last_result.intent.target_id,
    }


def _build_turn_context(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    *,
    persona: PersonaConfig,
    last_result: UrbanTurnResult | None,
) -> PlayerTurnContext:
    segment = _segment_for_state(plan, state)
    suggestions = build_suggested_actions(plan, state)
    return PlayerTurnContext(
        persona=persona,
        turn_index=state.turn_index + 1,
        story_id=plan.story_id,
        social_arena=plan.social_arena,
        segment_id=segment.segment_id,
        segment_role=segment.segment_role,
        segment_summary=(
            f"{segment.scene_goal} {segment.emotional_goal} "
            f"重点推进：{segment.progression_rule_summary}"
        )[:600],
        active_characters=_active_character_snapshot(plan, state),
        suggested_actions=[item.model_dump(mode="json") for item in suggestions],
        state_snapshot=_state_snapshot(plan, state),
        last_turn_outcome=_last_turn_snapshot(last_result),
    )


def _suggestion_score_for_persona(
    persona_id: SelfPlayPersonaId,
    suggestion: UrbanSuggestedAction,
    state_snapshot: dict[str, Any],
    segment_role: str,
) -> tuple[int, int, int, str]:
    score = 0
    route_target_id = state_snapshot.get("current_route_target_id")
    active_ids = set(state_snapshot.get("active_character_ids", []))
    if suggestion.target_id in active_ids:
        score += 2
    if suggestion.target_id and suggestion.target_id == route_target_id:
        score += 2
    if persona_id == "baodian":
        if suggestion.lane_id == "burst":
            score += 4
        if suggestion.move_family in {"public_reveal", "accuse", "probe_secret", "jealousy_trigger", "betray"}:
            score += 4
        if suggestion.scene_frame == "public":
            score += 3
        if segment_role in {"reveal", "terminal"}:
            score += 2
    elif persona_id == "qinggan":
        if suggestion.lane_id == "relationship":
            score += 4
        if suggestion.move_family in {"flirt", "comfort", "private_confession", "ally_with"}:
            score += 4
        if suggestion.target_id and suggestion.target_id == route_target_id:
            score += 2
        if suggestion.scene_frame == "private":
            score += 1
    elif persona_id == "wenjian":
        if suggestion.lane_id in {"relationship", "side"}:
            score += 2
        if suggestion.move_family in {"comfort", "deflect", "private_confession", "ally_with"}:
            score += 4
        if suggestion.scene_frame != "public":
            score += 2
        if segment_role == "terminal" and suggestion.move_family in {"private_confession", "ally_with", "public_reveal"}:
            score += 1
    elif persona_id == "zhandui":
        if suggestion.lane_id == "side":
            score += 4
        if suggestion.move_family in {"ally_with", "comfort", "accuse", "deflect"}:
            score += 4
        if suggestion.target_id and suggestion.target_id == route_target_id:
            score += 3
    elif persona_id == "chaos":
        if suggestion.lane_id in {"burst", "side"}:
            score += 3
        if suggestion.move_family in {"public_reveal", "betray", "probe_secret", "jealousy_trigger", "accuse"}:
            score += 3
        if suggestion.scene_frame == "public":
            score += 2
        if segment_role in {"pressure", "reveal", "terminal"}:
            score += 2
    else:
        if suggestion.lane_id == "burst":
            score += 4
        if suggestion.move_family in {"accuse", "public_reveal", "betray", "probe_secret"}:
            score += 4
        if suggestion.scene_frame == "public":
            score += 2
    tie_breaker = 1 if suggestion.scene_frame == "public" else 0
    route_bias = 1 if suggestion.target_id and suggestion.target_id == route_target_id else 0
    return score, route_bias, tie_breaker, suggestion.suggestion_id


def _best_suggestion_for_persona(
    persona_id: SelfPlayPersonaId,
    suggestions: list[UrbanSuggestedAction],
    state_snapshot: dict[str, Any],
    segment_role: str,
) -> UrbanSuggestedAction:
    if not suggestions:
        raise ValueError("no suggestions available for repair")
    return max(
        suggestions,
        key=lambda item: _suggestion_score_for_persona(persona_id, item, state_snapshot, segment_role),
    )


def _lane_priority_for_persona(persona_id: SelfPlayPersonaId) -> tuple[SuggestionLaneId, ...]:
    if persona_id == "baodian":
        return ("burst", "side", "relationship")
    if persona_id == "qinggan":
        return ("relationship", "side", "burst")
    if persona_id == "wenjian":
        return ("relationship", "side", "burst")
    if persona_id == "zhandui":
        return ("side", "relationship", "burst")
    if persona_id == "chaos":
        return ("burst", "side", "relationship")
    return ("burst", "side", "relationship")


def _resolve_suggestion_from_lane(
    *,
    persona_id: SelfPlayPersonaId,
    decision: PlayerDecision,
    suggestions: list[UrbanSuggestedAction],
) -> tuple[UrbanSuggestedAction, bool, list[str]]:
    notes: list[str] = []
    lane_map = {suggestion.lane_id: suggestion for suggestion in suggestions}
    requested_lane = decision.lane_id
    notes.append(f"lane_requested:{requested_lane}")
    if requested_lane in lane_map:
        selected = lane_map[requested_lane]
        repaired = False
    else:
        selected = next(
            (
                lane_map[lane_id]
                for lane_id in _lane_priority_for_persona(persona_id)
                if lane_id in lane_map
            ),
            suggestions[0],
        )
        repaired = True
        notes.append(f"lane_repaired:{selected.lane_id}")
    if decision.target_hint and selected.target_id and decision.target_hint != selected.target_id:
        notes.append("target_hint_ignored")
    notes.append("text_parse_bypassed")
    return selected, repaired, notes


def _resolve_repair(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    decision: PlayerDecision,
    persona_id: SelfPlayPersonaId,
) -> tuple[bool, UrbanSuggestedAction, list[str], TurnConfidence]:
    diagnostics = parse_turn_intent(plan, state, decision.action_text)
    suggestions = build_suggested_actions(plan, state)
    selected, repaired, notes = _resolve_suggestion_from_lane(
        persona_id=persona_id,
        decision=decision,
        suggestions=suggestions,
    )
    if repaired:
        notes.append(f"repair_applied:{selected.move_family}")
    return repaired, selected, notes, diagnostics.confidence


def _has_meaningful_delta(before: UrbanWorldState, after: UrbanWorldState, target_id: str | None) -> bool:
    if before.scene_heat != after.scene_heat or before.public_image != after.public_image or before.secret_exposure != after.secret_exposure:
        return True
    if before.route_lock != after.route_lock or before.current_route_target_id != after.current_route_target_id:
        return True
    if target_id and target_id in before.relationships and target_id in after.relationships:
        before_rel = before.relationships[target_id]
        after_rel = after.relationships[target_id]
        return (
            before_rel.affection != after_rel.affection
            or before_rel.trust != after_rel.trust
            or before_rel.tension != after_rel.tension
            or before_rel.suspicion != after_rel.suspicion
            or before_rel.dependency != after_rel.dependency
        )
    return False


def _score_content_quality(
    plan: CompiledPlayPlan,
    before: UrbanWorldState,
    result: UrbanTurnResult,
    *,
    original_confidence: TurnConfidence,
) -> tuple[int, list[str]]:
    segment = _segment_for_state(plan, before)
    score = 0
    notes: list[str] = []
    if original_confidence != "low":
        score += 1
        notes.append("parse_ok")
    if result.intent.target_id in set(segment.focus_target_ids + segment.rival_target_ids):
        score += 1
        notes.append("target_hits_segment_core")
    if result.intent.move_family in set(segment.move_priorities[:2]):
        score += 1
        notes.append("top_priority_move")
    if "focus_hit" in result.consequence_tags or "priority_move" in result.consequence_tags:
        score += 1
        notes.append("consequence_hit")
    if _has_meaningful_delta(before, result.state, result.intent.target_id):
        score += 1
        notes.append("meaningful_delta")
    if result.intent.lane_id:
        notes.append(f"lane:{result.intent.lane_id}")
    return score, notes


def _score_persona_alignment(
    plan: CompiledPlayPlan,
    before: UrbanWorldState,
    result: UrbanTurnResult,
    *,
    persona_id: SelfPlayPersonaId,
) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []
    target_id = result.intent.target_id
    segment = _segment_for_state(plan, before)
    before_rel = before.relationships.get(target_id or "")
    after_rel = result.state.relationships.get(target_id or "")
    if persona_id == "baodian":
        if result.intent.lane_id == "burst":
            score += 1
            notes.append("burst_lane")
        if result.intent.scene_frame == "public":
            score += 1
            notes.append("public_play")
        if result.intent.move_family in {"public_reveal", "accuse", "probe_secret", "jealousy_trigger", "betray"}:
            score += 1
            notes.append("explosive_move")
        if result.state.scene_heat > before.scene_heat or result.state.secret_exposure > before.secret_exposure:
            score += 1
            notes.append("pressure_up")
        if segment.segment_role in {"reveal", "terminal"}:
            score += 1
            notes.append("late_stage_pressure")
        if "public_reveal" == result.intent.move_family or result.state.scene_heat >= 4:
            score += 1
            notes.append("irreversible_feel")
    elif persona_id == "qinggan":
        if result.intent.lane_id == "relationship":
            score += 1
            notes.append("relationship_lane")
        if result.intent.move_family in {"flirt", "comfort", "private_confession", "ally_with"}:
            score += 1
            notes.append("intimacy_move")
        if target_id in set(plan.route_target_ids):
            score += 1
            notes.append("route_target_hit")
        if before_rel and after_rel and (after_rel.affection > before_rel.affection or after_rel.trust > before_rel.trust):
            score += 1
            notes.append("relationship_gain")
        if target_id and result.state.route_scores_by_target.get(target_id, 0) > before.route_scores_by_target.get(target_id, 0):
            score += 1
            notes.append("route_gain")
        if len(result.state.betrayal_ids) <= len(before.betrayal_ids):
            score += 1
            notes.append("no_betrayal")
    elif persona_id == "wenjian":
        if result.intent.lane_id in {"relationship", "side"}:
            score += 1
            notes.append("safe_lane")
        if result.intent.move_family in {"comfort", "deflect", "private_confession", "ally_with"}:
            score += 1
            notes.append("conservative_move")
        if target_id in set(before.active_character_ids):
            score += 1
            notes.append("active_target_hit")
        if result.state.public_image >= before.public_image:
            score += 1
            notes.append("public_image_stable")
        if before_rel and after_rel and (after_rel.suspicion - before_rel.suspicion) <= 1:
            score += 1
            notes.append("low_suspicion_spike")
        if (result.state.scene_heat - before.scene_heat) <= 1:
            score += 1
            notes.append("controlled_heat")
    elif persona_id == "zhandui":
        if result.intent.lane_id == "side":
            score += 1
            notes.append("side_lane")
        if result.intent.move_family in {"ally_with", "comfort", "accuse", "deflect"}:
            score += 1
            notes.append("camp_move")
        if target_id in set(plan.route_target_ids):
            score += 1
            notes.append("route_target_hit")
        if result.state.route_lock > before.route_lock:
            score += 1
            notes.append("route_lock_gain")
        if target_id and result.state.route_scores_by_target.get(target_id, 0) > before.route_scores_by_target.get(target_id, 0):
            score += 1
            notes.append("route_commitment")
    elif persona_id == "chaos":
        if result.intent.lane_id in {"burst", "side"}:
            score += 1
            notes.append("aggressive_lane")
        if result.intent.move_family in {"public_reveal", "betray", "probe_secret", "jealousy_trigger", "accuse"}:
            score += 1
            notes.append("chaos_move")
        if result.intent.scene_frame == "public":
            score += 1
            notes.append("public_shock")
        if result.state.scene_heat > before.scene_heat or result.state.secret_exposure > before.secret_exposure:
            score += 1
            notes.append("pressure_up")
    else:
        if result.intent.lane_id == "burst":
            score += 1
            notes.append("burst_lane")
        if result.intent.move_family in {"accuse", "public_reveal", "betray", "probe_secret"}:
            score += 1
            notes.append("punishment_move")
        if target_id in set(before.active_character_ids):
            score += 1
            notes.append("hostile_target_focus")
        if result.state.scene_heat > before.scene_heat or result.state.secret_exposure > before.secret_exposure:
            score += 1
            notes.append("pressure_up")
        if result.intent.scene_frame == "public":
            score += 1
            notes.append("public_confrontation")
    return min(score, 5), notes[:8]


def _turn_log_from_result(
    *,
    plan: CompiledPlayPlan,
    persona_id: SelfPlayPersonaId,
    decision: PlayerDecision,
    original_confidence: TurnConfidence,
    repaired: bool,
    repair_notes: list[str],
    before_state: UrbanWorldState,
    result: UrbanTurnResult,
    suggested_actions: list[UrbanSuggestedAction],
    decision_latency_ms: float,
    runtime_latency_ms: float,
    turn_input_mode: SelfPlayTurnInputMode,
    submitted_with_selected_ids: bool,
    draft_call_count: int = 0,
    draft_input_tokens: int = 0,
    draft_output_tokens: int = 0,
    draft_total_tokens: int = 0,
    turn_trace: PlayTurnTrace | None = None,
) -> SelfPlayTurnLog:
    content_score, content_notes = _score_content_quality(plan, before_state, result, original_confidence=original_confidence)
    alignment_score, alignment_notes = _score_persona_alignment(plan, before_state, result, persona_id=persona_id)
    segment = _segment_for_state(plan, before_state)
    interpret_usage = dict(turn_trace.interpret_usage or {}) if turn_trace is not None else {}
    result_diagnostics = dict(result.intent_stage_diagnostics or {})

    def _usage_int(key: str) -> int:
        value = interpret_usage.get(key, 0)
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return max(int(round(float(value))), 0)
        return 0

    def _usage_text(key: str) -> str:
        value = interpret_usage.get(key, "")
        return str(value).strip() if isinstance(value, str) else ""

    def _usage_bool(key: str) -> bool:
        value = interpret_usage.get(key, False)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _usage_float(key: str) -> float:
        value = interpret_usage.get(key, 0.0)
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return max(float(value), 0.0)
        return 0.0

    def _diagnostic_int(key: str) -> int:
        value = result_diagnostics.get(key, interpret_usage.get(key, 0))
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return max(int(round(float(value))), 0)
        return 0

    def _diagnostic_list(key: str) -> list[str]:
        value = result_diagnostics.get(key, interpret_usage.get(key, []))
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:3]

    mode_from_usage = str(interpret_usage.get("submission_input_mode") or "").strip().lower()
    resolved_turn_input_mode: SelfPlayTurnInputMode = "select_id" if mode_from_usage == "select_id" else turn_input_mode
    resolved_submitted_with_selected_ids = (
        _usage_bool("submitted_with_selected_ids")
        if "submitted_with_selected_ids" in interpret_usage
        else submitted_with_selected_ids
    )
    usage_draft_call_count = _usage_int("draft_call_count")
    resolved_draft_call_count = max(int(draft_call_count), usage_draft_call_count)
    resolved_draft_input_tokens = max(int(draft_input_tokens), _usage_int("draft_input_tokens"))
    resolved_draft_output_tokens = max(int(draft_output_tokens), _usage_int("draft_output_tokens"))
    resolved_draft_total_tokens = max(int(draft_total_tokens), _usage_int("draft_total_tokens"))
    if resolved_draft_total_tokens <= 0:
        resolved_draft_total_tokens = resolved_draft_input_tokens + resolved_draft_output_tokens
    resolved_typing_phase_prewarm_tokens = _usage_int("typing_phase_prewarm_tokens")
    resolved_read_phase_prewarm_tokens = _usage_int("read_phase_prewarm_tokens")
    resolved_pre_submit_total_tokens = max(
        _usage_int("pre_submit_total_tokens"),
        resolved_draft_total_tokens + resolved_typing_phase_prewarm_tokens + resolved_read_phase_prewarm_tokens,
    )
    resolved_post_submit_total_tokens = max(
        _usage_int("post_submit_total_tokens"),
        _usage_int("intent_stage_total_tokens") + _usage_int("compose_total_tokens"),
    )
    resolved_play_turn_total_tokens = max(
        _usage_int("play_turn_total_tokens"),
        resolved_pre_submit_total_tokens + resolved_post_submit_total_tokens,
    )

    return SelfPlayTurnLog(
        turn_index=result.state.turn_index,
        persona_id=persona_id,
        play_length_preset=plan.play_length_preset,
        arc_template_id=plan.arc_template_id,
        progress_required_by_segment=[segment.progress_required for segment in plan.segments],
        raw_action_text=decision.action_text,
        reason=decision.reason,
        parse_confidence=original_confidence,
        repaired=repaired,
        turn_input_mode=resolved_turn_input_mode,
        submitted_with_selected_ids=resolved_submitted_with_selected_ids,
        selected_lane_id=result.intent.lane_id,
        selected_move_family=result.intent.move_family,
        selected_target_id=result.intent.target_id,
        narration=result.narration,
        progress_summary=result.progress_summary,
        consequence_tags=list(result.consequence_tags),
        suggested_actions_snapshot=[item.model_dump(mode="json") for item in suggested_actions],
        next_suggested_actions=[item.model_dump(mode="json") for item in result.suggested_actions],
        state_before=before_state.model_dump(mode="json"),
        state_after=result.state.model_dump(mode="json"),
        decision_latency_ms=round(decision_latency_ms, 4),
        runtime_latency_ms=round(runtime_latency_ms, 4),
        total_turn_latency_ms=round(decision_latency_ms + runtime_latency_ms, 4),
        intent_stage_latency_ms=float(_usage_int("intent_stage_latency_ms")),
        intent_stage_input_tokens=_usage_int("intent_stage_input_tokens"),
        intent_stage_output_tokens=_usage_int("intent_stage_output_tokens"),
        intent_stage_total_tokens=_usage_int("intent_stage_total_tokens"),
        intent_llm_total_tokens=_usage_int("intent_llm_total_tokens"),
        micro_sim_total_tokens=_usage_int("micro_sim_total_tokens"),
        draft_call_count=resolved_draft_call_count,
        draft_intent_status=_usage_text("draft_intent_status"),
        draft_input_tokens=resolved_draft_input_tokens,
        draft_output_tokens=resolved_draft_output_tokens,
        draft_total_tokens=resolved_draft_total_tokens,
        pre_submit_total_tokens=resolved_pre_submit_total_tokens,
        post_submit_total_tokens=resolved_post_submit_total_tokens,
        play_turn_total_tokens=resolved_play_turn_total_tokens,
        compose_input_tokens=_usage_int("compose_input_tokens"),
        compose_output_tokens=_usage_int("compose_output_tokens"),
        compose_total_tokens=_usage_int("compose_total_tokens"),
        compose_latency_ms=round(_usage_float("compose_latency_ms"), 4),
        turn_complexity=_usage_text("turn_complexity") or "normal",
        compose_pass_count=_usage_int("compose_pass_count"),
        compose_pass2_retry_count=_usage_int("compose_pass2_retry_count"),
        compose_pass1_latency_ms=round(_usage_float("compose_pass1_latency_ms"), 4),
        compose_pass2_latency_ms=round(_usage_float("compose_pass2_latency_ms"), 4),
        compose_pass2_invalid_reason=_usage_text("compose_pass2_invalid_reason"),
        compose_budget_hit=_usage_bool("compose_budget_hit"),
        delta_pack_hit=_usage_bool("delta_pack_hit"),
        compose_pass2_applied=_usage_bool("compose_pass2_applied"),
        compose_prewarm_status=_usage_text("compose_prewarm_status"),
        compose_prewarm_hit=_usage_bool("compose_prewarm_hit"),
        compose_prewarm_wait_ms=round(_usage_float("compose_prewarm_wait_ms"), 4),
        compose_prewarm_source=_usage_text("compose_prewarm_source"),
        compose_prewarm_total_tokens=_usage_int("compose_prewarm_total_tokens"),
        typing_final_draft_seen=_usage_bool("typing_final_draft_seen"),
        typing_scope_cleared_count=_usage_int("typing_scope_cleared_count"),
        compose_prewarm_stale_fragment_count=_usage_int("compose_prewarm_stale_fragment_count"),
        read_phase_prewarm_tokens=resolved_read_phase_prewarm_tokens,
        typing_phase_prewarm_tokens=resolved_typing_phase_prewarm_tokens,
        submit_phase_tokens=max(_usage_int("submit_phase_tokens"), resolved_post_submit_total_tokens),
        gateway_acquire_wait_ms=round(_usage_float("gateway_acquire_wait_ms"), 4),
        post_submit_llm_calls=_usage_int("post_submit_llm_calls"),
        single_llm_call_after_submit=_usage_bool("single_llm_call_after_submit"),
        intent_llm_gate_reason=_usage_text("intent_llm_gate_reason"),
        micro_sim_llm_gate_reason=_usage_text("micro_sim_llm_gate_reason"),
        compose_pass2_gate_reason=_usage_text("compose_pass2_gate_reason"),
        selected_style_case_ids=_usage_text("selected_style_case_ids") or _usage_text("style_case_ids"),
        soft_avoid_stems=_usage_text("soft_avoid_stems"),
        diversity_guard_hits=_usage_int("diversity_guard_hits"),
        compose_retry_count=_usage_int("compose_retry_count"),
        compose_invalid_reason=_usage_text("compose_invalid_reason"),
        blocked_stems=_usage_text("blocked_stems"),
        blocked_stems_hit=_usage_bool("blocked_stems_hit"),
        storylet_matches_count=_diagnostic_int("storylet_matches_count"),
        storylet_matches_ids=_diagnostic_list("storylet_matches_ids"),
        memory_context_active_hooks=_diagnostic_int("memory_context_active_hooks"),
        memory_context_revealed_secrets=_diagnostic_int("memory_context_revealed_secrets"),
        memory_context_total_chars_sent=_diagnostic_int("memory_context_total_chars_sent"),
        memory_context_npc_pressure_count=_diagnostic_int("memory_context_npc_pressure_count"),
        control_bias_applied=_usage_bool("control_bias_applied"),
        control_bias_reason=_usage_text("control_bias_reason"),
        control_bias_from_move=_usage_text("control_bias_from_move"),
        control_bias_to_move=_usage_text("control_bias_to_move"),
        content_quality_score=content_score,
        persona_alignment_score=alignment_score,
        notes=[*repair_notes, *content_notes, *alignment_notes][:12],
        segment_id=segment.segment_id,
        segment_role=segment.segment_role,
        ending_triggered=result.ending_triggered,
        agent_confidence=decision.confidence,
    )


def _ending_strength(ending_id: str | None) -> int:
    if not ending_id:
        return 0
    if ending_id.startswith("relationship_"):
        return 3
    if ending_id.startswith("side_"):
        return 2
    if ending_id == "burst_reckoning":
        return 3
    return ENDING_STRENGTH.get(ending_id, 0)


def _summarize_persona_run(persona: PersonaConfig, logs: list[SelfPlayTurnLog]) -> SelfPlayRunSummary:
    ending_id = logs[-1].state_after.get("ending_id") if logs else None
    ending_summary = logs[-1].state_after.get("ending_summary") if logs else None
    confidence_dist: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for log in logs:
        confidence_dist[log.parse_confidence] = confidence_dist.get(log.parse_confidence, 0) + 1
    lane_counts: dict[str, int] = {}
    for log in logs:
        if log.selected_lane_id:
            lane_counts[log.selected_lane_id] = lane_counts.get(log.selected_lane_id, 0) + 1
    free_input_turn_count = sum(1 for log in logs if log.turn_input_mode == "free_input")
    select_id_turn_count = sum(1 for log in logs if log.turn_input_mode == "select_id")
    pre_submit_total_tokens = sum(int(log.pre_submit_total_tokens) for log in logs)
    post_submit_total_tokens = sum(int(log.post_submit_total_tokens) for log in logs)
    play_total_tokens = sum(int(log.play_turn_total_tokens) for log in logs)
    free_input_play_total_tokens = sum(
        int(log.play_turn_total_tokens)
        for log in logs
        if log.turn_input_mode == "free_input"
    )
    select_id_play_total_tokens = sum(
        int(log.play_turn_total_tokens)
        for log in logs
        if log.turn_input_mode == "select_id"
    )
    if logs:
        best_turn = max(logs, key=lambda item: (item.content_quality_score + item.persona_alignment_score, -item.total_turn_latency_ms))
        worst_turn = min(logs, key=lambda item: (item.content_quality_score + item.persona_alignment_score, -item.total_turn_latency_ms))
    else:
        best_turn = worst_turn = None
    return SelfPlayRunSummary(
        persona_id=persona.persona_id,
        persona_label=persona.label,
        play_length_preset=logs[0].play_length_preset if logs else "unknown",
        arc_template_id=logs[0].arc_template_id if logs else "unknown",
        progress_required_by_segment=logs[0].progress_required_by_segment if logs else [],
        ending_reached=bool(ending_id),
        ending_id=ending_id,
        ending_strength=_ending_strength(ending_id),
        turn_count=len(logs),
        free_input_turn_count=free_input_turn_count,
        select_id_turn_count=select_id_turn_count,
        avg_content_score=round(mean(log.content_quality_score for log in logs), 4) if logs else 0.0,
        avg_persona_alignment_score=round(mean(log.persona_alignment_score for log in logs), 4) if logs else 0.0,
        mean_turn_latency_ms=round(mean(log.total_turn_latency_ms for log in logs), 4) if logs else 0.0,
        max_turn_latency_ms=round(max((log.total_turn_latency_ms for log in logs), default=0.0), 4),
        repair_count=sum(1 for log in logs if log.repaired),
        avg_parse_confidence=round(mean(CONFIDENCE_TO_SCORE[log.parse_confidence] for log in logs), 4) if logs else 0.0,
        parse_confidence_distribution=confidence_dist,
        lane_counts=lane_counts,
        route_target_trajectory=[
            str(log.state_after.get("current_route_target_id") or "")
            for log in logs
            if log.state_after.get("current_route_target_id")
        ],
        play_total_tokens=play_total_tokens,
        pre_submit_total_tokens=pre_submit_total_tokens,
        post_submit_total_tokens=post_submit_total_tokens,
        pre_submit_share=round((pre_submit_total_tokens / play_total_tokens), 4) if play_total_tokens > 0 else 0.0,
        post_submit_share=round((post_submit_total_tokens / play_total_tokens), 4) if play_total_tokens > 0 else 0.0,
        free_input_play_total_tokens=free_input_play_total_tokens,
        select_id_play_total_tokens=select_id_play_total_tokens,
        best_turn_index=best_turn.turn_index if best_turn else None,
        worst_turn_index=worst_turn.turn_index if worst_turn else None,
        ending_summary=ending_summary,
    )


def _segment_divergence(logs_by_persona: dict[str, list[SelfPlayTurnLog]]) -> dict[str, dict[str, Any]]:
    divergence: dict[str, dict[str, Any]] = {}
    for persona_id, logs in logs_by_persona.items():
        for log in logs:
            entry = divergence.setdefault(log.segment_id, {"persona_moves": {}, "persona_targets": {}, "persona_lanes": {}, "segment_role": log.segment_role})
            entry["persona_moves"].setdefault(persona_id, []).append(log.selected_move_family)
            entry["persona_targets"].setdefault(persona_id, []).append(log.selected_target_id)
            entry["persona_lanes"].setdefault(persona_id, []).append(log.selected_lane_id)
    for segment_id, payload in divergence.items():
        move_set = {
            move
            for moves in payload["persona_moves"].values()
            for move in moves
            if isinstance(move, str)
        }
        lane_set = {
            lane_id
            for lane_ids in payload["persona_lanes"].values()
            for lane_id in lane_ids
            if isinstance(lane_id, str) and lane_id
        }
        target_set = {
            target
            for targets in payload["persona_targets"].values()
            for target in targets
            if isinstance(target, str) and target
        }
        payload["unique_move_families"] = len(move_set)
        payload["unique_lanes"] = len(lane_set)
        payload["unique_targets"] = len(target_set)
    return divergence


def _detect_failure_patterns(
    summaries: dict[str, SelfPlayRunSummary],
    logs_by_persona: dict[str, list[SelfPlayTurnLog]],
    divergence: dict[str, dict[str, Any]],
) -> list[str]:
    patterns: list[str] = []
    avg_content = mean(summary.avg_content_score for summary in summaries.values())
    all_endings = {summary.ending_id for summary in summaries.values()}
    final_targets = {
        summary.route_target_trajectory[-1]
        for summary in summaries.values()
        if summary.route_target_trajectory
    }
    reveal_logs = [
        log
        for logs in logs_by_persona.values()
        for log in logs
        if log.segment_role in {"reveal", "terminal"}
    ]
    if avg_content < 3.0:
        patterns.append("temptation_too_weak")
    if len(final_targets) <= 1 and len(all_endings) <= 1:
        patterns.append("route_differentiation_too_weak")
    if reveal_logs and mean(log.content_quality_score for log in reveal_logs) < 3.0:
        patterns.append("reveal_payoff_too_soft")
    if all(summary.ending_reached for summary in summaries.values()) and avg_content < 3.2 and len(all_endings) == 1:
        patterns.append("stable_but_boring")
    baodian = summaries.get("baodian")
    if baodian and baodian.ending_id == "burned_alone" and baodian.avg_content_score >= 3.0:
        patterns.append("explosive_but_self_defeating")
    return patterns[:8]


def _build_comparison_summary(
    case_id: str,
    run_summaries: dict[str, SelfPlayRunSummary],
    logs_by_persona: dict[str, list[SelfPlayTurnLog]],
    *,
    source_live_depth_score: int = 0,
    source_final_mode_path: str = "deterministic",
) -> SelfPlayComparisonSummary:
    comparable_summaries = [summary for summary in run_summaries.values() if summary.worker_status != "failed"] or list(run_summaries.values())
    strongest_ending = max(
        comparable_summaries,
        key=lambda item: (item.ending_strength, item.avg_content_score, -item.mean_turn_latency_ms, item.persona_id),
    )
    strongest_content = max(
        comparable_summaries,
        key=lambda item: (item.avg_content_score, item.ending_strength, -item.mean_turn_latency_ms, item.persona_id),
    )
    fastest = min(
        comparable_summaries,
        key=lambda item: (item.mean_turn_latency_ms, -item.avg_content_score, item.persona_id),
    )
    divergence = _segment_divergence(logs_by_persona)
    distinct_playstyles = (
        len({summary.ending_id for summary in run_summaries.values()}) > 1
        or len({tuple(summary.route_target_trajectory) for summary in run_summaries.values()}) > 1
        or any(payload["unique_move_families"] > 1 for payload in divergence.values())
    )
    playstyle_collapse = not distinct_playstyles
    return SelfPlayComparisonSummary(
        case_id=case_id,
        strongest_ending_persona_id=strongest_ending.persona_id,
        strongest_content_persona_id=strongest_content.persona_id,
        fastest_persona_id=fastest.persona_id,
        failed_persona_ids=[
            summary.persona_id
            for summary in run_summaries.values()
            if summary.worker_status == "failed"
        ],
        source_live_depth_score=source_live_depth_score,
        source_final_mode_path=source_final_mode_path,
        supports_distinct_playstyles=distinct_playstyles,
        playstyle_collapse=playstyle_collapse,
        divergence_by_segment=divergence,
        failure_patterns=_detect_failure_patterns(run_summaries, logs_by_persona, divergence),
        persona_summaries=run_summaries,
    )


def _analysis_markdown(
    *,
    plan: CompiledPlayPlan,
    comparison: SelfPlayComparisonSummary,
    persona_pack: PersonaPackResolution,
) -> str:
    lines = [
        f"# Self-Play Analysis: {plan.title}",
        "",
        f"- Story shell: `{plan.story_shell_id}`",
        f"- Social arena: {plan.social_arena}",
        f"- Route promise: {plan.route_promise}",
        f"- Bomb moment: {plan.bomb_moment}",
        "",
        "## Persona Pack",
        "",
        f"- Source: `{persona_pack.source}` (`{persona_pack.source_key}`)",
        f"- Ordered personas: `{','.join(persona_pack.ordered_persona_ids)}`",
        "",
        "| Rank | Persona | Reason |",
        "| ---: | --- | --- |",
    ]
    for entry in persona_pack.entries:
        lines.append(f"| {entry.rank} | {entry.label} (`{entry.persona_id}`) | {entry.reason} |")
    lines.extend(
        [
            "",
        "## Persona Outcomes",
        "",
        "| Persona | Ending | Turns | Avg Content | Avg Alignment | Mean Latency (ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    ordered_persona_ids = [
        persona_id
        for persona_id in SELF_PLAY_PERSONA_ORDER
        if persona_id in comparison.persona_summaries
    ]
    ordered_persona_ids.extend(
        sorted(
            persona_id
            for persona_id in comparison.persona_summaries
            if persona_id not in set(ordered_persona_ids)
        )
    )
    for persona_id in ordered_persona_ids:
        summary = comparison.persona_summaries[persona_id]
        lines.append(
            f"| {summary.persona_label} | {summary.ending_id or 'none'} | {summary.turn_count} | "
            f"{summary.avg_content_score:.2f} | {summary.avg_persona_alignment_score:.2f} | {summary.mean_turn_latency_ms:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Comparison",
            "",
            f"- Strongest ending: `{comparison.strongest_ending_persona_id}`",
            f"- Strongest content: `{comparison.strongest_content_persona_id}`",
            f"- Fastest: `{comparison.fastest_persona_id}`",
            f"- Failed personas: `{','.join(comparison.failed_persona_ids) if comparison.failed_persona_ids else 'none'}`",
            f"- Distinct playstyles supported: `{comparison.supports_distinct_playstyles}`",
            f"- Playstyle collapse: `{comparison.playstyle_collapse}`",
            "",
            "## Segment Divergence",
            "",
        ]
    )
    for segment_id, payload in comparison.divergence_by_segment.items():
        lines.append(
            f"- `{segment_id}` ({payload['segment_role']}): unique moves={payload['unique_move_families']}, "
            f"unique targets={payload['unique_targets']}"
        )
    lines.extend(["", "## Failure Patterns", ""])
    if comparison.failure_patterns:
        for pattern in comparison.failure_patterns:
            lines.append(f"- `{pattern}`")
    else:
        lines.append("- None")
    return "\n".join(lines)


def _default_adapter_factory(
    persona_ids: tuple[SelfPlayPersonaId, ...],
    *,
    prefer_llm: bool,
    allow_decision_fallback: bool,
) -> dict[SelfPlayPersonaId, PlayerAgentAdapter]:
    settings = get_settings()
    if (
        prefer_llm
        and settings.resolved_play_responses_base_url().strip()
        and settings.resolved_play_responses_api_key().strip()
        and settings.resolved_play_responses_model().strip()
    ):
        backend = ResponsesPlayBackend(settings=settings)
        return {
            persona_id: SubagentPlayerAdapter(
                PERSONA_CONFIGS[persona_id],
                backend=backend,
                allow_decision_fallback=allow_decision_fallback,
            )
            for persona_id in persona_ids
        }
    return {
        persona_id: ScriptedPlayerAdapter(PERSONA_CONFIGS[persona_id], decision_delay_ms=index * 2)
        for index, persona_id in enumerate(persona_ids, start=1)
    }


def _merge_adapter_map(
    persona_ids: tuple[SelfPlayPersonaId, ...],
    overrides: dict[SelfPlayPersonaId, PlayerAgentAdapter] | None,
    *,
    prefer_llm: bool,
    allow_decision_fallback: bool,
) -> dict[SelfPlayPersonaId, PlayerAgentAdapter]:
    base = _default_adapter_factory(
        persona_ids,
        prefer_llm=prefer_llm,
        allow_decision_fallback=allow_decision_fallback,
    )
    if overrides:
        for persona_id, adapter in overrides.items():
            if persona_id in set(persona_ids):
                base[persona_id] = adapter
    return base


def _sample_persona_ids_for_eval_phase(
    persona_ids: list[SelfPlayPersonaId],
    *,
    case_id: str,
    phase: str,
    persona_limit: int | None,
) -> list[SelfPlayPersonaId]:
    ordered = [persona_id for persona_id in persona_ids if persona_id in PERSONA_CONFIGS]
    if not ordered:
        return []
    if persona_limit is None:
        return list(ordered)
    normalized_limit = max(1, int(persona_limit))
    if normalized_limit >= len(ordered):
        return list(ordered)
    rng = random.Random(f"{case_id}:{phase}:persona_eval_sampling:v1")
    sampled = set(rng.sample(ordered, k=normalized_limit))
    return [persona_id for persona_id in ordered if persona_id in sampled]


def _write_worker_state(
    *,
    persona_dir: Path,
    state: UrbanWorldState,
    logs: list[SelfPlayTurnLog],
    summary: SelfPlayRunSummary,
    turn_play_eval_logs: list[play_eval_tools.TurnPlayEvalRecord] | None = None,
) -> None:
    _write_jsonl(persona_dir / "turn_logs.jsonl", logs)
    if turn_play_eval_logs is not None:
        _write_jsonl(persona_dir / "turn_play_eval_logs.jsonl", turn_play_eval_logs)
    _write_json(persona_dir / "latest_state.json", state)
    _write_json(persona_dir / "run_summary.partial.json", summary)


def _turn_play_eval_payload(
    *,
    case_id: str,
    plan: CompiledPlayPlan,
    persona: PersonaConfig,
    log: SelfPlayTurnLog,
    selected_suggestion: UrbanSuggestedAction,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "persona_id": persona.persona_id,
        "story_shell_id": plan.story_shell_id,
        "segment_role": log.segment_role,
        "turn_index": log.turn_index,
        "route_promise": plan.route_promise,
        "bomb_moment": plan.bomb_moment,
        "raw_action_text": log.raw_action_text,
        "selected_suggestion": selected_suggestion.model_dump(mode="json"),
        "narration": log.narration,
        "progress_summary": log.progress_summary,
        "state_before": log.state_before,
        "state_after": log.state_after,
        "feedback": {
            "last_turn_global_deltas": log.state_after.get("last_turn_global_deltas", {}),
            "last_turn_relationship_deltas": log.state_after.get("last_turn_relationship_deltas", {}),
            "last_turn_consequences": log.state_after.get("last_turn_consequences", []),
            "last_turn_reaction_causes": log.state_after.get("last_turn_reaction_causes", {}),
            "consequence_tags": log.consequence_tags,
            "control_resolution": log.state_after.get("last_turn_control_resolution", {}),
        },
        "next_suggested_actions": log.next_suggested_actions,
    }


def _turn_llm_text_audit_payload(
    *,
    case_id: str,
    plan: CompiledPlayPlan,
    persona_id: SelfPlayPersonaId,
    log: SelfPlayTurnLog,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "persona_id": persona_id,
        "turn_index": log.turn_index,
        "story_shell_id": plan.story_shell_id,
        "segment_role": log.segment_role,
        "text": {
            "narration": log.narration,
            "progress_summary": log.progress_summary,
            "last_turn_consequences": list(log.state_after.get("last_turn_consequences") or []),
        },
        "signals": {
            "selected_lane_id": log.selected_lane_id,
            "selected_move_family": log.selected_move_family,
            "selected_target_id": log.selected_target_id,
            "consequence_tags": list(log.consequence_tags),
            "global_deltas": dict(log.state_after.get("last_turn_global_deltas") or {}),
            "relationship_deltas": dict(log.state_after.get("last_turn_relationship_deltas") or {}),
            "reaction_causes": dict(log.state_after.get("last_turn_reaction_causes") or {}),
            "control_resolution": dict(log.state_after.get("last_turn_control_resolution") or {}),
        },
    }


def _compact_turn_log_for_session(
    log: SelfPlayTurnLog,
    turn_play_eval: play_eval_tools.TurnPlayEvalRecord | None,
) -> dict[str, Any]:
    return {
        "turn_index": log.turn_index,
        "segment_role": log.segment_role,
        "raw_action_text": log.raw_action_text,
        "selected_lane_id": log.selected_lane_id,
        "selected_move_family": log.selected_move_family,
        "selected_target_id": log.selected_target_id,
        "narration": log.narration,
        "progress_summary": log.progress_summary,
        "consequence_tags": list(log.consequence_tags),
        "route_target_id": log.state_after.get("current_route_target_id"),
        "state_feedback": {
            "last_turn_global_deltas": log.state_after.get("last_turn_global_deltas", {}),
            "last_turn_relationship_deltas": log.state_after.get("last_turn_relationship_deltas", {}),
            "last_turn_consequences": log.state_after.get("last_turn_consequences", []),
            "last_turn_reaction_causes": log.state_after.get("last_turn_reaction_causes", {}),
            "last_turn_control_resolution": log.state_after.get("last_turn_control_resolution", {}),
        },
        "ending_triggered": log.ending_triggered,
        "turn_play_eval": turn_play_eval.model_dump(mode="json") if turn_play_eval is not None else None,
    }


def _excerpt_turns_for_session(
    logs: list[SelfPlayTurnLog],
    summary: SelfPlayRunSummary,
    turn_play_eval_by_turn: dict[int, play_eval_tools.TurnPlayEvalRecord],
) -> list[dict[str, Any]]:
    if not logs:
        return []
    selected_indices: list[int] = [1]
    if len(logs) >= 2:
        selected_indices.append(2)
    if summary.best_turn_index is not None:
        selected_indices.append(summary.best_turn_index)
    if summary.worst_turn_index is not None:
        selected_indices.append(summary.worst_turn_index)
    selected_indices.append(logs[-1].turn_index)
    seen: set[int] = set()
    excerpts: list[dict[str, Any]] = []
    for turn_index in selected_indices:
        if turn_index in seen:
            continue
        seen.add(turn_index)
        log = next((item for item in logs if item.turn_index == turn_index), None)
        if log is None:
            continue
        excerpts.append(_compact_turn_log_for_session(log, turn_play_eval_by_turn.get(turn_index)))
    return excerpts


def _turn_play_eval_summary(turn_play_eval_logs: list[play_eval_tools.TurnPlayEvalRecord]) -> dict[str, Any]:
    completed = [
        record
        for record in turn_play_eval_logs
        if record.play_eval_status == "completed" and record.scores is not None
    ]
    flag_counter: Counter[str] = Counter()
    for record in completed:
        flag_counter.update(record.flags)
    avg_scores: dict[str, float] = {}
    key_segment_markers = [
        bool(record.key_segment_shell_anchor_hit)
        for record in completed
        if record.key_segment_shell_anchor_hit is not None
    ]
    if completed:
        metrics = (
            "consequence_impact",
            "intent_binding",
            "pressure_exchange",
            "control_effectiveness",
            "trigger_conversion",
            "foreshadow_clarity",
            "shell_signal_fidelity",
            "npc_agency_reversal",
        )
        for metric in metrics:
            avg_scores[metric] = round(
                mean(getattr(record.scores, metric) for record in completed if record.scores is not None),
                4,
            )
    return {
        "completed_turns": len(completed),
        "failed_turns": sum(1 for record in turn_play_eval_logs if record.play_eval_status == "failed"),
        "avg_scores": avg_scores,
        "flag_counts": dict(flag_counter),
        "key_segment_shell_anchor_hit_rate": (
            round(sum(1 for marker in key_segment_markers if marker) / len(key_segment_markers), 4)
            if key_segment_markers
            else 0.0
        ),
        "strongest_signals": [record.strongest_signal for record in completed if record.strongest_signal][:3],
        "main_issues": [record.main_issue for record in completed if record.main_issue][:3],
    }


def _turn_llm_text_audit_summary(turn_llm_logs: list[llm_text_audit_tools.TurnLlmTextAuditRecord]) -> dict[str, Any]:
    completed = [
        record
        for record in turn_llm_logs
        if record.llm_audit_status in {"completed", "partial_success"} and record.scores is not None
    ]
    flag_counter: Counter[str] = Counter()
    for record in completed:
        flag_counter.update(record.flags)
    avg_scores: dict[str, float] = {}
    if completed:
        metrics = (
            "tone_naturalness",
            "character_specificity",
            "dramatic_tension",
            "shell_fidelity",
            "consequence_clarity",
            "anti_template_stiffness",
        )
        for metric in metrics:
            avg_scores[metric] = round(
                mean(getattr(record.scores, metric) for record in completed if record.scores is not None),
                4,
            )
    return {
        "completed_turns": len(completed),
        "partial_turns": sum(1 for record in turn_llm_logs if record.llm_audit_status == "partial_success"),
        "failed_turns": sum(1 for record in turn_llm_logs if record.llm_audit_status == "failed"),
        "avg_scores": avg_scores,
        "flag_counts": dict(flag_counter),
        "strongest_signals": [record.strongest_signal for record in completed if record.strongest_signal][:3],
        "main_issues": [record.main_issue for record in completed if record.main_issue][:3],
    }


def _compact_run_summary_for_llm_session(summary: SelfPlayRunSummary) -> dict[str, Any]:
    return {
        "worker_status": summary.worker_status,
        "turn_count": summary.turn_count,
        "ending_reached": summary.ending_reached,
        "ending_id": summary.ending_id,
        "ending_strength": summary.ending_strength,
        "lane_counts": dict(summary.lane_counts),
        "best_turn_index": summary.best_turn_index,
        "worst_turn_index": summary.worst_turn_index,
        "avg_content_score": summary.avg_content_score,
        "avg_persona_alignment_score": summary.avg_persona_alignment_score,
    }


def _compact_turn_log_for_llm_session(log: SelfPlayTurnLog) -> dict[str, Any]:
    return {
        "turn_index": log.turn_index,
        "segment_role": log.segment_role,
        "raw_action_text": log.raw_action_text,
        "narration": log.narration,
        "progress_summary": log.progress_summary,
        "selected_lane_id": log.selected_lane_id,
        "selected_move_family": log.selected_move_family,
        "selected_target_id": log.selected_target_id,
        "consequence_tags": list(log.consequence_tags),
    }


def _truncate_text(value: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()


def _estimate_payload_tokens(payload: dict[str, Any]) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return max(1, int((len(text) + (LLM_SESSION_AUDIT_CHARS_PER_TOKEN - 1)) / LLM_SESSION_AUDIT_CHARS_PER_TOKEN))


def _select_key_turn_logs_for_llm_session(
    logs: list[SelfPlayTurnLog],
    summary: SelfPlayRunSummary,
) -> list[SelfPlayTurnLog]:
    if not logs:
        return []
    ordered = sorted(logs, key=lambda item: item.turn_index)
    by_turn_index = {log.turn_index: log for log in ordered}
    selected: list[SelfPlayTurnLog] = []
    seen_turns: set[int] = set()

    def _append_turn(turn_index: int | None) -> None:
        if turn_index is None:
            return
        log = by_turn_index.get(turn_index)
        if log is None or turn_index in seen_turns:
            return
        seen_turns.add(turn_index)
        selected.append(log)

    for role in ("opening", "misread", "reveal", "terminal"):
        for log in ordered:
            if str(log.segment_role).strip().casefold() == role:
                _append_turn(log.turn_index)
                break
    _append_turn(summary.best_turn_index)
    _append_turn(summary.worst_turn_index)

    min_turns = min(LLM_SESSION_AUDIT_MIN_KEY_TURNS, len(ordered))
    max_turns = min(LLM_SESSION_AUDIT_MAX_KEY_TURNS, len(ordered))
    for log in ordered:
        if len(selected) >= max_turns:
            break
        if len(selected) < min_turns:
            _append_turn(log.turn_index)
            continue
        if log.turn_index not in seen_turns:
            _append_turn(log.turn_index)

    if len(selected) > max_turns:
        selected = selected[:max_turns]
    return sorted(selected, key=lambda item: item.turn_index)


def _apply_key_turn_text_caps(
    key_turns: list[dict[str, Any]],
    *,
    narration_cap: int,
    action_cap: int,
    progress_cap: int,
) -> None:
    for turn in key_turns:
        narration = str(turn.get("narration") or "")
        raw_action = str(turn.get("raw_action_text") or "")
        progress = str(turn.get("progress_summary") or "")
        turn["narration"] = _truncate_text(narration, max_chars=narration_cap)
        turn["raw_action_text"] = _truncate_text(raw_action, max_chars=action_cap)
        turn["progress_summary"] = _truncate_text(progress, max_chars=progress_cap)


def _trim_session_llm_payload_to_budget(payload: dict[str, Any]) -> dict[str, Any]:
    key_turns = list(payload.get("key_turns") or [])
    min_turns = min(LLM_SESSION_AUDIT_MIN_KEY_TURNS, len(key_turns))
    trimmed = False
    estimated_tokens = _estimate_payload_tokens(payload)

    while estimated_tokens > LLM_SESSION_AUDIT_MAX_ESTIMATED_TOKENS and len(key_turns) > min_turns:
        key_turns.pop()
        payload["key_turns"] = list(key_turns)
        trimmed = True
        estimated_tokens = _estimate_payload_tokens(payload)

    if estimated_tokens > LLM_SESSION_AUDIT_MAX_ESTIMATED_TOKENS:
        for narration_cap, action_cap, progress_cap in LLM_SESSION_AUDIT_TEXT_CAP_STEPS:
            _apply_key_turn_text_caps(
                key_turns,
                narration_cap=narration_cap,
                action_cap=action_cap,
                progress_cap=progress_cap,
            )
            payload["key_turns"] = list(key_turns)
            trimmed = True
            estimated_tokens = _estimate_payload_tokens(payload)
            if estimated_tokens <= LLM_SESSION_AUDIT_MAX_ESTIMATED_TOKENS:
                break

    if estimated_tokens > LLM_SESSION_AUDIT_MAX_ESTIMATED_TOKENS:
        _apply_key_turn_text_caps(
            key_turns,
            narration_cap=96,
            action_cap=48,
            progress_cap=36,
        )
        payload["key_turns"] = list(key_turns)
        trimmed = True
        preview_summary = dict(payload.get("preview_summary") or {})
        for key in ("title_hint", "route_promise", "bomb_moment", "cost_of_truth", "taboo_secret"):
            preview_summary[key] = _truncate_text(str(preview_summary.get(key) or ""), max_chars=64)
        payload["preview_summary"] = preview_summary
        estimated_tokens = _estimate_payload_tokens(payload)

    payload["payload_estimated_tokens"] = estimated_tokens
    payload["payload_trimmed"] = trimmed
    payload["payload_turn_count"] = len(key_turns)
    return payload


def _preview_summary(preview: Any) -> dict[str, Any]:
    return {
        "title_hint": getattr(preview, "title_hint", None),
        "story_shell_id": getattr(preview, "story_shell_id", None),
        "experience_band": getattr(preview, "experience_band", None),
        "social_arena": getattr(preview, "social_arena", None),
        "route_promise": getattr(preview, "route_promise", None),
        "bomb_moment": getattr(preview, "bomb_moment", None),
        "cost_of_truth": getattr(preview, "cost_of_truth", None),
        "taboo_secret": getattr(preview, "taboo_secret", None),
    }


def _session_play_eval_payload(
    *,
    case_id: str,
    preview: Any,
    plan: CompiledPlayPlan,
    persona_pack: PersonaPackResolution,
    persona_id: SelfPlayPersonaId,
    logs: list[SelfPlayTurnLog],
    summary: SelfPlayRunSummary,
    turn_play_eval_logs: list[play_eval_tools.TurnPlayEvalRecord],
) -> dict[str, Any]:
    turn_play_eval_by_turn = {record.turn_index: record for record in turn_play_eval_logs}
    rank_by_persona = {
        entry.persona_id: entry.rank
        for entry in persona_pack.entries
    }
    return {
        "case_id": case_id,
        "persona_id": persona_id,
        "story_shell_id": plan.story_shell_id,
        "title": plan.title,
        "route_promise": plan.route_promise,
        "bomb_moment": plan.bomb_moment,
        "persona_selection": {
            "source": persona_pack.source,
            "source_key": persona_pack.source_key,
            "rank": rank_by_persona.get(persona_id),
            "ordered_persona_ids": list(persona_pack.ordered_persona_ids),
        },
        "preview_summary": _preview_summary(preview),
        "ending_id": summary.ending_id,
        "run_summary": summary.model_dump(mode="json"),
        "turn_play_eval_summary": _turn_play_eval_summary(turn_play_eval_logs),
        "transcript_excerpts": _excerpt_turns_for_session(logs, summary, turn_play_eval_by_turn),
        "turn_logs": [
            _compact_turn_log_for_session(log, turn_play_eval_by_turn.get(log.turn_index))
            for log in logs
        ],
    }


def _session_llm_text_audit_payload(
    *,
    case_id: str,
    preview: Any,
    plan: CompiledPlayPlan,
    persona_pack: PersonaPackResolution,
    persona_id: SelfPlayPersonaId,
    logs: list[SelfPlayTurnLog],
    summary: SelfPlayRunSummary,
    turn_llm_logs: list[llm_text_audit_tools.TurnLlmTextAuditRecord],
) -> dict[str, Any]:
    rank_by_persona = {
        entry.persona_id: entry.rank
        for entry in persona_pack.entries
    }
    selected_logs = _select_key_turn_logs_for_llm_session(logs, summary)
    payload = {
        "case_id": case_id,
        "persona_id": persona_id,
        "story_shell_id": plan.story_shell_id,
        "title": plan.title,
        "route_promise": plan.route_promise,
        "bomb_moment": plan.bomb_moment,
        "persona_selection": {
            "source": persona_pack.source,
            "source_key": persona_pack.source_key,
            "rank": rank_by_persona.get(persona_id),
            "ordered_persona_ids": list(persona_pack.ordered_persona_ids),
        },
        "preview_summary": _preview_summary(preview),
        "ending_id": summary.ending_id,
        "run_summary_compact": _compact_run_summary_for_llm_session(summary),
        "turn_llm_text_audit_summary": _turn_llm_text_audit_summary(turn_llm_logs),
        "key_turns": [_compact_turn_log_for_llm_session(log) for log in selected_logs],
    }
    return _trim_session_llm_payload_to_budget(payload)


def _decide_with_timeout(
    *,
    adapter: PlayerAgentAdapter,
    context: PlayerTurnContext,
    timeout_seconds: float,
) -> PlayerDecision:
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(adapter.decide, context)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"decision timed out after {timeout_seconds:.1f}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _remaining_deadline_seconds(case_deadline_monotonic: float | None) -> float | None:
    if case_deadline_monotonic is None:
        return None
    return max(0.0, case_deadline_monotonic - time.monotonic())


def _compose_deadline_seconds(
    *,
    outer_deadline_monotonic: float | None,
    phase_timeout_seconds: float | None,
) -> float | None:
    local_deadline = (
        time.monotonic() + max(1.0, float(phase_timeout_seconds))
        if phase_timeout_seconds is not None and float(phase_timeout_seconds) > 0
        else None
    )
    if outer_deadline_monotonic is None:
        return local_deadline
    if local_deadline is None:
        return outer_deadline_monotonic
    return min(outer_deadline_monotonic, local_deadline)


def _evaluate_persona_llm_text_audit(
    *,
    case_id: str,
    preview: Any,
    plan: CompiledPlayPlan,
    persona_pack: PersonaPackResolution,
    persona_id: SelfPlayPersonaId,
    logs: list[SelfPlayTurnLog],
    summary: SelfPlayRunSummary,
) -> tuple[list[llm_text_audit_tools.TurnLlmTextAuditRecord], llm_text_audit_tools.SessionLlmTextAuditReport]:
    sampled_logs = _sample_logs_for_llm_turn_audit(
        logs,
        max_turns=DEFAULT_MAX_LLM_TURN_AUDITS_PER_PERSONA,
    )
    turn_records = [
        llm_text_audit_tools.evaluate_turn_text(
            _turn_llm_text_audit_payload(
                case_id=case_id,
                plan=plan,
                persona_id=persona_id,
                log=log,
            )
        )
        for log in sampled_logs
    ]
    session_report = llm_text_audit_tools.evaluate_session_text(
        _session_llm_text_audit_payload(
            case_id=case_id,
            preview=preview,
            plan=plan,
            persona_pack=persona_pack,
            persona_id=persona_id,
            logs=logs,
            summary=summary,
            turn_llm_logs=turn_records,
        )
    )
    return turn_records, session_report


def _sample_logs_for_llm_turn_audit(
    logs: list[SelfPlayTurnLog],
    *,
    max_turns: int,
) -> list[SelfPlayTurnLog]:
    if not logs:
        return []
    cap = max(1, int(max_turns))
    if len(logs) <= cap:
        return list(logs)
    if cap == 1:
        return [logs[-1]]
    if cap == 2:
        return [logs[0], logs[-1]]

    opening_idx = next((idx for idx, log in enumerate(logs) if log.segment_role == "opening"), 0)
    terminal_idx = next(
        (idx for idx in range(len(logs) - 1, -1, -1) if logs[idx].segment_role in {"terminal", "reveal"}),
        len(logs) - 1,
    )
    mid_idx = len(logs) // 2
    chosen_indexes: list[int] = []
    for idx in (opening_idx, mid_idx, terminal_idx):
        if idx not in chosen_indexes:
            chosen_indexes.append(idx)
    for idx in range(len(logs)):
        if len(chosen_indexes) >= cap:
            break
        if idx not in chosen_indexes:
            chosen_indexes.append(idx)
    chosen_indexes.sort()
    return [logs[idx] for idx in chosen_indexes[:cap]]


def _result_from_session_turn(
    *,
    plan: CompiledPlayPlan,
    before_state: UrbanWorldState,
    after_state: UrbanWorldState,
    decision: PlayerDecision,
    selected_suggestion: UrbanSuggestedAction,
    turn_trace: PlayTurnTrace | None = None,
) -> UrbanTurnResult:
    progress_summary = (
        (after_state.last_turn_consequences[0] if after_state.last_turn_consequences else "")
        or (after_state.last_turn_intent_feedback[0] if after_state.last_turn_intent_feedback else "")
        or "局势正在继续发酵。"
    )[:220]
    return UrbanTurnResult(
        plan=plan,
        state=after_state,
        narration=after_state.narration or "场面推进了一步。",
        story_actions=list(after_state.story_actions),
        control_actions=list(after_state.control_actions),
        suggested_actions=list(after_state.suggested_actions),
        triggered_latent_event=after_state.last_turn_escalations[0] if after_state.last_turn_escalations else None,
        latent_radar=list(after_state.latent_radar),
        control_resolution=after_state.last_turn_control_resolution,
        segment_advanced=after_state.segment_index != before_state.segment_index,
        ending_triggered=bool(after_state.ending_id),
        consequence_tags=list(after_state.last_turn_tags),
        progress_summary=progress_summary,
        intent=UrbanTurnIntent(
            input_text=decision.action_text,
            lane_id=turn_trace.lane_id if turn_trace is not None else selected_suggestion.lane_id,
            move_family=turn_trace.move_family if turn_trace is not None and turn_trace.move_family is not None else selected_suggestion.move_family,
            target_id=(
                turn_trace.target_character_ids[0]
                if turn_trace is not None and turn_trace.target_character_ids
                else selected_suggestion.target_id
            ),
            scene_frame=turn_trace.scene_frame if turn_trace is not None and turn_trace.scene_frame is not None else selected_suggestion.scene_frame,
            control_action=turn_trace.resolution.control_action if turn_trace is not None else "none",
            control_source=turn_trace.control_source if turn_trace is not None else "none",
            control_target_kind=turn_trace.resolution.control_target_kind if turn_trace is not None else None,
            control_target_id=turn_trace.resolution.control_target_id if turn_trace is not None else None,
            control_target_mode=(
                turn_trace.resolution.control_resolution.target_mode
                if turn_trace is not None and turn_trace.resolution.control_resolution is not None
                else None
            ),
            confidence=decision.confidence,
            intent_confidence=(
                max(min(float(turn_trace.intent_confidence), 1.0), 0.0)
                if turn_trace is not None and turn_trace.intent_confidence is not None
                else 0.5
            ),
            intent_compile_source=(
                turn_trace.intent_compile_source
                if turn_trace is not None and turn_trace.intent_compile_source is not None
                else "heuristic_fallback"
            ),
            deviation_type=turn_trace.deviation_type if turn_trace is not None else "none",
            deviation_note=(
                turn_trace.resolution.deviation_note
                if turn_trace is not None and turn_trace.resolution.deviation_note
                else None
            ),
            alternatives=(
                list(turn_trace.resolution.alternatives)
                if turn_trace is not None
                else []
            ),
        ),
    )


def _run_persona(
    *,
    case_id: str,
    plan: CompiledPlayPlan,
    play_service: PlaySessionService,
    story_id: str,
    actor_user_id: str,
    adapter: PlayerAgentAdapter,
    persona_dir: Path,
    decision_timeout_seconds: float,
    max_repair_only_turns: int,
    select_id_probability: float,
    typing_rhythm_enabled: bool = DEFAULT_TYPING_RHYTHM_ENABLED,
    draft_intent_probability: float = DEFAULT_DRAFT_INTENT_PROBABILITY,
    draft_call_count_min: int = DEFAULT_DRAFT_CALL_COUNT_MIN,
    draft_call_count_max: int = DEFAULT_DRAFT_CALL_COUNT_MAX,
    draft_debounce_ms: int = DEFAULT_DRAFT_DEBOUNCE_MS,
    strict_no_repair_fallback: bool = False,
    collect_turn_play_eval: bool = False,
    case_deadline_monotonic: float | None = None,
    max_turns_override: int | None = None,
) -> tuple[list[SelfPlayTurnLog], SelfPlayRunSummary, list[play_eval_tools.TurnPlayEvalRecord]]:
    persona = adapter.persona
    session = play_service.create_session(story_id, actor_user_id=actor_user_id)
    record = play_service._get_record(session.session_id)  # noqa: SLF001
    if not isinstance(record.state, UrbanWorldState):
        raise RuntimeError("self-play requires urban_v2 world state")
    state = record.state
    last_result: UrbanTurnResult | None = None
    logs: list[SelfPlayTurnLog] = []
    turn_play_eval_logs: list[play_eval_tools.TurnPlayEvalRecord] = []
    repair_only_turns = 0
    mode_rng = random.Random(f"{case_id}:{persona.persona_id}:input_mode")
    draft_rng = random.Random(f"{case_id}:{persona.persona_id}:draft_rhythm")
    normalized_draft_probability = min(max(float(draft_intent_probability), 0.0), 1.0)
    normalized_draft_call_min = max(1, int(min(draft_call_count_min, draft_call_count_max)))
    normalized_draft_call_max = max(normalized_draft_call_min, int(max(draft_call_count_min, draft_call_count_max)))
    _draft_debounce_ms = int(max(draft_debounce_ms, 0))
    effective_max_turns = min(plan.max_turns, max_turns_override) if max_turns_override is not None else plan.max_turns
    adapter.open()
    try:
        while state.status != "completed" and state.turn_index < effective_max_turns:
            if case_deadline_monotonic is not None and time.monotonic() >= case_deadline_monotonic:
                raise TimeoutError("case_timeout:persona_loop_deadline_exceeded")
            suggestions = build_suggested_actions(plan, state)
            if not suggestions:
                break
            context = _build_turn_context(plan, state, persona=persona, last_result=last_result)
            before_state = state.model_copy(deep=True)
            decision_started = time.perf_counter()
            decision_fallback_note: str | None = None
            try:
                decision = _decide_with_timeout(
                    adapter=adapter,
                    context=context,
                    timeout_seconds=decision_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                if not adapter.allow_decision_fallback():
                    raise
                if strict_no_repair_fallback:
                    raise RuntimeError(f"strict_no_repair_fallback:decision_exception:{str(exc)[:120]}") from exc
                decision_fallback_note = f"player_backend_fallback:{str(exc)[:120]}"
                fallback = _best_suggestion_for_persona(
                    persona.persona_id,
                    suggestions,
                    context.state_snapshot,
                    context.segment_role,
                )
                decision = PlayerDecision(
                    lane_id=fallback.lane_id,
                    action_text=fallback.prompt,
                    reason="玩家决策失败，回退到推荐动作。",
                    confidence="low",
                    target_hint=fallback.target_id,
                )
            decision_latency_ms = (time.perf_counter() - decision_started) * 1000
            repaired, selected_suggestion, repair_notes, diagnostic_confidence = _resolve_repair(
                plan,
                before_state,
                decision,
                persona.persona_id,
            )
            if decision_fallback_note:
                repair_notes = [decision_fallback_note, *repair_notes]
            if strict_no_repair_fallback and repaired:
                joined_notes = ",".join(repair_notes[:6]) or "repair_applied"
                raise RuntimeError(f"strict_no_repair_fallback:repair_applied:{joined_notes}")
            use_selected_ids = mode_rng.random() < select_id_probability
            turn_input_mode: SelfPlayTurnInputMode = "select_id" if use_selected_ids else "free_input"
            draft_call_count = 0
            draft_input_tokens = 0
            draft_output_tokens = 0
            draft_total_tokens = 0
            latest_draft_intent_id: str | None = None
            if (
                turn_input_mode == "free_input"
                and typing_rhythm_enabled
                and draft_rng.random() < normalized_draft_probability
            ):
                target_call_count = draft_rng.randint(normalized_draft_call_min, normalized_draft_call_max)
                draft_fragments = _draft_fragments(decision.action_text, call_count=target_call_count)
                for index, fragment in enumerate(draft_fragments):
                    is_final_draft = index == len(draft_fragments) - 1
                    try:
                        draft_response = play_service.draft_intent(
                            session.session_id,
                            PlayDraftIntentRequest(
                                input_text=fragment,
                                is_final_draft=is_final_draft,
                            ),
                            actor_user_id=actor_user_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        repair_notes = [f"draft_intent_failed:{str(exc)[:120]}", *repair_notes]
                        break
                    draft_call_count += 1
                    draft_usage = dict(draft_response.usage or {})
                    draft_input_tokens += max(int(draft_usage.get("input_tokens", 0) or 0), 0)
                    draft_output_tokens += max(int(draft_usage.get("output_tokens", 0) or 0), 0)
                    draft_total_tokens += max(int(draft_usage.get("total_tokens", 0) or 0), 0)
                    latest_draft_intent_id = draft_response.draft_intent_id
                if draft_total_tokens <= 0:
                    draft_total_tokens = draft_input_tokens + draft_output_tokens
            runtime_started = time.perf_counter()
            if use_selected_ids:
                request_payload = PlayTurnRequest(
                    input_text=decision.action_text,
                    selected_suggestion_id=selected_suggestion.suggestion_id,
                    selected_story_action_id=selected_suggestion.suggestion_id,
                )
            else:
                request_payload = PlayTurnRequest(
                    input_text=decision.action_text,
                    draft_intent_id=latest_draft_intent_id,
                )
            play_service.submit_turn(
                session.session_id,
                request_payload,
                actor_user_id=actor_user_id,
            )
            runtime_latency_ms = (time.perf_counter() - runtime_started) * 1000
            record_after = play_service._get_record(session.session_id)  # noqa: SLF001
            if not isinstance(record_after.state, UrbanWorldState):
                raise RuntimeError("self-play requires urban_v2 world state")
            state = record_after.state
            turn_trace = record_after.turn_traces[-1] if record_after.turn_traces else None
            if strict_no_repair_fallback:
                strict_reason = _strict_runtime_repair_or_fallback_reason(
                    turn_trace=turn_trace,
                    state=state,
                )
                if strict_reason:
                    raise RuntimeError(f"strict_no_repair_fallback:runtime:{strict_reason}")
            result = _result_from_session_turn(
                plan=plan,
                before_state=before_state,
                after_state=state,
                decision=decision,
                selected_suggestion=selected_suggestion,
                turn_trace=turn_trace,
            )
            log = _turn_log_from_result(
                plan=plan,
                persona_id=persona.persona_id,
                decision=decision,
                original_confidence=diagnostic_confidence,
                repaired=repaired,
                repair_notes=repair_notes,
                before_state=before_state,
                result=result,
                suggested_actions=suggestions,
                decision_latency_ms=decision_latency_ms,
                runtime_latency_ms=runtime_latency_ms,
                turn_input_mode=turn_input_mode,
                submitted_with_selected_ids=use_selected_ids,
                draft_call_count=draft_call_count,
                draft_input_tokens=draft_input_tokens,
                draft_output_tokens=draft_output_tokens,
                draft_total_tokens=draft_total_tokens,
                turn_trace=turn_trace,
            )
            logs.append(log)
            if collect_turn_play_eval:
                turn_play_eval_logs.append(
                    play_eval_tools.evaluate_turn(
                        _turn_play_eval_payload(
                            case_id=case_id,
                            plan=plan,
                            persona=persona,
                            log=log,
                            selected_suggestion=selected_suggestion,
                        )
                    )
                )
            repair_only_turns = repair_only_turns + 1 if log.repaired else 0
            last_result = result
            partial_summary = _summarize_persona_run(persona, logs).model_copy(update={"worker_status": "stopped"})
            _write_worker_state(
                persona_dir=persona_dir,
                state=state,
                logs=logs,
                summary=partial_summary,
                turn_play_eval_logs=turn_play_eval_logs if collect_turn_play_eval else None,
            )
            if repair_only_turns >= max_repair_only_turns:
                failure_summary = _summarize_persona_run(persona, logs).model_copy(
                    update={
                        "worker_status": "failed",
                        "failure_reason": f"repair_only_turn_limit:{repair_only_turns}",
                    }
                )
                _write_json(persona_dir / "run_summary.json", failure_summary)
                return logs, failure_summary, turn_play_eval_logs
        final_status: Literal["completed", "stopped"] = "completed" if state.status == "completed" else "stopped"
        final_summary = _summarize_persona_run(persona, logs).model_copy(update={"worker_status": final_status})
        _write_json(persona_dir / "run_summary.json", final_summary)
        if collect_turn_play_eval and not (persona_dir / "turn_play_eval_logs.jsonl").exists():
            _write_jsonl(persona_dir / "turn_play_eval_logs.jsonl", turn_play_eval_logs)
        return logs, final_summary, turn_play_eval_logs
    except Exception as exc:  # noqa: BLE001
        failure_summary = _summarize_persona_run(persona, logs).model_copy(
            update={
                "worker_status": "failed",
                "failure_reason": str(exc)[:240],
            }
        )
        if logs:
            _write_jsonl(persona_dir / "turn_logs.jsonl", logs)
        if collect_turn_play_eval:
            _write_jsonl(persona_dir / "turn_play_eval_logs.jsonl", turn_play_eval_logs)
        _write_json(persona_dir / "latest_state.json", state)
        _write_json(persona_dir / "run_summary.partial.json", failure_summary)
        _write_json(persona_dir / "run_summary.json", failure_summary)
        return logs, failure_summary, turn_play_eval_logs
    finally:
        adapter.close()


def run_self_play_pilot(
    output_dir: Path,
    *,
    case_id: str = PILOT_CASE_ID,
    case_catalog: list[UrbanGoldCase] | None = None,
    live_mode: str = LIVE_AUTHOR_MODE,
    execution_mode: SelfPlayExecutionMode = "parallel",
    max_workers: int | None = None,
    decision_timeout_seconds: float = DEFAULT_DECISION_TIMEOUT_SECONDS,
    max_repair_only_turns: int = DEFAULT_MAX_REPAIR_ONLY_TURNS,
    select_id_probability: float = DEFAULT_SELECT_ID_PROBABILITY,
    typing_rhythm_enabled: bool = DEFAULT_TYPING_RHYTHM_ENABLED,
    draft_intent_probability: float = DEFAULT_DRAFT_INTENT_PROBABILITY,
    draft_call_count_min: int = DEFAULT_DRAFT_CALL_COUNT_MIN,
    draft_call_count_max: int = DEFAULT_DRAFT_CALL_COUNT_MAX,
    draft_debounce_ms: int = DEFAULT_DRAFT_DEBOUNCE_MS,
    play_length_preset: str | None = None,
    adapters: dict[SelfPlayPersonaId, PlayerAgentAdapter] | None = None,
    enable_turn_play_eval: bool = False,
    enable_session_play_eval: bool = False,
    play_eval_max_workers: int | None = None,
    session_play_eval_persona_limit: int | None = None,
    enable_llm_text_audit: bool = False,
    llm_text_audit_max_workers: int | None = None,
    llm_text_audit_persona_limit: int | None = None,
    enable_chaos_persona_shadow: bool = False,
    source_artifacts_dir: Path | None = None,
    max_case_runtime_seconds: float | None = None,
    persona_runtime_timeout_seconds: float | None = None,
    session_play_eval_timeout_seconds: float | None = None,
    llm_text_audit_timeout_seconds: float | None = None,
    max_turns_override: int | None = None,
    strict_no_repair_fallback: bool | None = None,
) -> dict[str, Any]:
    case = _pilot_case(case_id, case_catalog=case_catalog)
    resolved_output_dir = (output_dir / "self_play" / case.case_id / live_mode).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    case_deadline_monotonic = (
        time.monotonic() + max(1.0, float(max_case_runtime_seconds))
        if max_case_runtime_seconds is not None and float(max_case_runtime_seconds) > 0
        else None
    )
    strict_mode = (
        _strict_no_repair_fallback_enabled()
        if strict_no_repair_fallback is None
        else bool(strict_no_repair_fallback)
    )
    normalized_select_id_probability = min(max(float(select_id_probability), 0.0), 1.0)
    normalized_draft_intent_probability = min(max(float(draft_intent_probability), 0.0), 1.0)
    normalized_draft_call_count_min = max(1, int(min(draft_call_count_min, draft_call_count_max)))
    normalized_draft_call_count_max = max(
        normalized_draft_call_count_min,
        int(max(draft_call_count_min, draft_call_count_max)),
    )
    normalized_draft_debounce_ms = max(0, int(draft_debounce_ms))
    normalized_session_eval_persona_limit = (
        max(1, int(session_play_eval_persona_limit))
        if session_play_eval_persona_limit is not None
        else None
    )
    normalized_llm_audit_persona_limit = (
        max(1, int(llm_text_audit_persona_limit))
        if llm_text_audit_persona_limit is not None
        else None
    )
    _write_json(resolved_output_dir / "seed.json", case)
    try:
        package: RelationshipDramaV2Package
        play_plan: CompiledPlayPlan
        preview: UrbanPreviewBlueprint
        accepted: AcceptedBlueprint
        quality_trace: list[dict[str, Any]]
        llm_call_trace: list[dict[str, Any]]
        if source_artifacts_dir is not None:
            package, quality_trace, llm_call_trace = _load_author_artifacts(source_artifacts_dir)
            preview = package.preview_blueprint
            accepted = package.accepted_blueprint
            play_plan = package.compiled_play_plan
            if play_length_preset is not None and accepted.play_length_preset != play_length_preset:
                accepted = apply_blueprint_edits(accepted, {"play_length_preset": play_length_preset})
                pipeline = run_author_play_graph(accepted, live_mode=live_mode)  # type: ignore[arg-type]
                play_plan = pipeline.play_plan
                quality_trace = list(pipeline.state.get("quality_trace", []))
                llm_call_trace = list(pipeline.state.get("llm_call_trace", []))
                package = RelationshipDramaV2Package(
                    preview_blueprint=preview,
                    accepted_blueprint=accepted,
                    urban_bundle=pipeline.bundle,
                    compiled_play_plan=play_plan,
                    quality_trace=quality_trace,
                    llm_call_trace=llm_call_trace,
                )
        else:
            preview, preview_state = run_preview_blueprint_graph(case.seed, live_mode=live_mode)  # type: ignore[arg-type]
            accepted = apply_blueprint_edits(
                preview,
                {"play_length_preset": play_length_preset} if play_length_preset is not None else None,
            )
            pipeline = run_author_play_graph(accepted, live_mode=live_mode)  # type: ignore[arg-type]
            play_plan = pipeline.play_plan
            quality_trace = list(preview_state.get("quality_trace", [])) + list(pipeline.state.get("quality_trace", []))
            llm_call_trace = list(preview_state.get("llm_call_trace", [])) + list(pipeline.state.get("llm_call_trace", []))
            package = RelationshipDramaV2Package(
                preview_blueprint=preview,
                accepted_blueprint=accepted,
                urban_bundle=pipeline.bundle,
                compiled_play_plan=play_plan,
                quality_trace=quality_trace,
                llm_call_trace=llm_call_trace,
            )
        if strict_mode:
            quality_reason = _first_quality_trace_repair_or_fallback(quality_trace)
            if quality_reason:
                raise RuntimeError(
                    f"strict_no_repair_fallback:author_quality:{quality_reason}"
                )
        _write_json(resolved_output_dir / "preview_blueprint.json", preview)
        _write_json(resolved_output_dir / "accepted_blueprint.json", accepted)
        full_quality_trace = list(quality_trace)
        full_llm_call_trace = list(llm_call_trace)
        _write_json(resolved_output_dir / "quality_trace.json", full_quality_trace)
        _write_json(resolved_output_dir / "llm_call_trace.json", full_llm_call_trace)
        _write_json(resolved_output_dir / "urban_bundle.json", package.urban_bundle)
        _write_json(resolved_output_dir / "compiled_play_plan.json", play_plan)
        _write_json(resolved_output_dir / "relationship_drama_v2_package.json", package)
        persona_pack = _resolve_persona_pack_for_plan(play_plan)
        _write_json(resolved_output_dir / "persona_pack.json", persona_pack)
        persona_ids = tuple(persona_pack.ordered_persona_ids)
        config = SelfPlayConfig(
            case_id=case.case_id,
            live_mode=live_mode,
            execution_mode=execution_mode,
            max_workers=max_workers or len(persona_ids),
            decision_timeout_seconds=decision_timeout_seconds,
            max_repair_only_turns=max_repair_only_turns,
            select_id_probability=normalized_select_id_probability,
            typing_rhythm_enabled=bool(typing_rhythm_enabled),
            draft_intent_probability=normalized_draft_intent_probability,
            draft_call_count_min=normalized_draft_call_count_min,
            draft_call_count_max=normalized_draft_call_count_max,
            draft_debounce_ms=normalized_draft_debounce_ms,
            session_play_eval_persona_limit=normalized_session_eval_persona_limit,
            llm_text_audit_persona_limit=normalized_llm_audit_persona_limit,
            latency_bucket_rule="submitted_ids",
            decision_surface="free_text_no_repair" if strict_mode else "free_text_with_repair",
            scoring_mode="rule_based_per_step",
            play_length_preset=play_length_preset,
            personas=[PERSONA_CONFIGS[persona_id] for persona_id in persona_ids],
        )
        _write_json(resolved_output_dir / "self_play_config.json", config)
        source_live_depth_score, source_final_mode_path = _source_live_metrics(full_quality_trace)
        settings = get_settings()
        story_library_service = StoryLibraryService(
            SQLiteStoryLibraryStorage(str((resolved_output_dir / "story_library.sqlite3").resolve()))
        )
        play_service = PlaySessionService(
            story_library_service=story_library_service,
            settings=settings,
            storage=SQLitePlaySessionStorage(str((resolved_output_dir / "play_sessions.sqlite3").resolve())),
        )
        published_story = story_library_service.publish_story(
            owner_user_id=settings.default_actor_id,
            source_job_id=f"self_play_{case.case_id}_{live_mode}_{uuid4().hex[:8]}",
            prompt_seed=case.seed,
            summary=author_story_summary_from_package(package),
            preview=author_preview_from_blueprint(
                package.preview_blueprint,
                bound_cast=package.urban_bundle.bound_cast,
                arc_template_id=package.urban_bundle.arc_template_id,
            ),
            bundle=package,
            visibility="private",
        )
        _write_json(resolved_output_dir / "published_story_card.json", published_story)
        adapter_map = _merge_adapter_map(
            persona_ids,
            adapters,
            prefer_llm=live_mode.startswith("live"),
            allow_decision_fallback=not strict_mode,
        )
        persona_logs: dict[str, list[SelfPlayTurnLog]] = {}
        persona_summaries: dict[str, SelfPlayRunSummary] = {}
        persona_turn_play_eval: dict[str, list[play_eval_tools.TurnPlayEvalRecord]] = {}
        persona_session_play_eval_reports: dict[str, play_eval_tools.SessionPlayEvalReport] = {}
        persona_turn_llm_text_audit: dict[str, list[llm_text_audit_tools.TurnLlmTextAuditRecord]] = {}
        persona_session_llm_text_audit_reports: dict[str, llm_text_audit_tools.SessionLlmTextAuditReport] = {}
        shadow_persona_logs: dict[str, list[SelfPlayTurnLog]] = {}
        shadow_persona_summaries: dict[str, SelfPlayRunSummary] = {}
        shadow_persona_turn_play_eval: dict[str, list[play_eval_tools.TurnPlayEvalRecord]] = {}
        shadow_persona_session_play_eval_reports: dict[str, play_eval_tools.SessionPlayEvalReport] = {}
        shadow_persona_turn_llm_text_audit: dict[str, list[llm_text_audit_tools.TurnLlmTextAuditRecord]] = {}
        shadow_persona_session_llm_text_audit_reports: dict[str, llm_text_audit_tools.SessionLlmTextAuditReport] = {}
        persona_dirs = {
            persona_id: (resolved_output_dir / "personas" / persona_id)
            for persona_id in persona_ids
        }
        for persona_dir in persona_dirs.values():
            persona_dir.mkdir(parents=True, exist_ok=True)
        if execution_mode == "sequential":
            for persona_id in persona_ids:
                logs, summary, turn_play_eval_logs = _run_persona(
                    case_id=case.case_id,
                    plan=play_plan,
                    play_service=play_service,
                    story_id=published_story.story_id,
                    actor_user_id=settings.default_actor_id,
                    adapter=adapter_map[persona_id],
                    persona_dir=persona_dirs[persona_id],
                    decision_timeout_seconds=decision_timeout_seconds,
                    max_repair_only_turns=max_repair_only_turns,
                    select_id_probability=normalized_select_id_probability,
                    typing_rhythm_enabled=bool(typing_rhythm_enabled),
                    draft_intent_probability=normalized_draft_intent_probability,
                    draft_call_count_min=normalized_draft_call_count_min,
                    draft_call_count_max=normalized_draft_call_count_max,
                    draft_debounce_ms=normalized_draft_debounce_ms,
                    strict_no_repair_fallback=strict_mode,
                    collect_turn_play_eval=enable_turn_play_eval,
                    case_deadline_monotonic=_compose_deadline_seconds(
                        outer_deadline_monotonic=case_deadline_monotonic,
                        phase_timeout_seconds=persona_runtime_timeout_seconds,
                    ),
                    max_turns_override=max_turns_override,
                )
                persona_logs[persona_id] = logs
                persona_summaries[persona_id] = summary
                persona_turn_play_eval[persona_id] = turn_play_eval_logs
        else:
            executor = ThreadPoolExecutor(max_workers=max_workers or len(persona_ids))
            pending: set[Any] = set()
            future_map: dict[Any, str] = {}
            try:
                future_map = {
                    executor.submit(
                        _run_persona,
                        case_id=case.case_id,
                        plan=play_plan,
                        play_service=play_service,
                        story_id=published_story.story_id,
                        actor_user_id=settings.default_actor_id,
                        adapter=adapter_map[persona_id],
                        persona_dir=persona_dirs[persona_id],
                        decision_timeout_seconds=decision_timeout_seconds,
                        max_repair_only_turns=max_repair_only_turns,
                        select_id_probability=normalized_select_id_probability,
                        typing_rhythm_enabled=bool(typing_rhythm_enabled),
                        draft_intent_probability=normalized_draft_intent_probability,
                        draft_call_count_min=normalized_draft_call_count_min,
                        draft_call_count_max=normalized_draft_call_count_max,
                        draft_debounce_ms=normalized_draft_debounce_ms,
                        strict_no_repair_fallback=strict_mode,
                        collect_turn_play_eval=enable_turn_play_eval,
                        case_deadline_monotonic=_compose_deadline_seconds(
                            outer_deadline_monotonic=case_deadline_monotonic,
                            phase_timeout_seconds=persona_runtime_timeout_seconds,
                        ),
                        max_turns_override=max_turns_override,
                    ): persona_id
                    for persona_id in persona_ids
                }
                pending = set(future_map.keys())
                while pending:
                    remaining = _remaining_deadline_seconds(case_deadline_monotonic)
                    if remaining is not None and remaining <= 0:
                        for future in list(pending):
                            persona_id = future_map[future]
                            future.cancel()
                            persona_logs.setdefault(persona_id, [])
                            persona_turn_play_eval.setdefault(persona_id, [])
                            persona_summaries[persona_id] = _summarize_persona_run(PERSONA_CONFIGS[persona_id], []).model_copy(
                                update={
                                    "worker_status": "failed",
                                    "failure_reason": "case_timeout:persona_future_deadline_exceeded",
                                }
                            )
                        pending.clear()
                        break
                    wait_timeout = min(1.0, remaining) if remaining is not None else 1.0
                    done, _ = wait(pending, timeout=wait_timeout, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        pending.discard(future)
                        persona_id = future_map[future]
                        try:
                            logs, summary, turn_play_eval_logs = future.result()
                        except Exception as exc:  # noqa: BLE001
                            logs = []
                            turn_play_eval_logs = []
                            summary = _summarize_persona_run(PERSONA_CONFIGS[persona_id], []).model_copy(
                                update={
                                    "worker_status": "failed",
                                    "failure_reason": f"persona_future_failed:{str(exc)[:180]}",
                                }
                            )
                        persona_logs[persona_id] = logs
                        persona_summaries[persona_id] = summary
                        persona_turn_play_eval[persona_id] = turn_play_eval_logs
            finally:
                for future in list(pending):
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
        if enable_session_play_eval:
            play_eval_persona_ids = [
                persona_id
                for persona_id in persona_ids
                if persona_summaries.get(persona_id) is not None
            ]
            play_eval_persona_ids = _sample_persona_ids_for_eval_phase(
                play_eval_persona_ids,
                case_id=case.case_id,
                phase="session_play_eval",
                persona_limit=normalized_session_eval_persona_limit,
            )
            play_eval_persona_id_set = set(play_eval_persona_ids)
            eval_executor = ThreadPoolExecutor(max_workers=play_eval_max_workers or min(6, max(1, len(play_eval_persona_ids))))
            pending_eval: set[Any] = set()
            eval_future_map: dict[Any, str] = {}
            try:
                eval_future_map = {
                    eval_executor.submit(
                        play_eval_tools.evaluate_session,
                        _session_play_eval_payload(
                            case_id=case.case_id,
                            preview=preview,
                            plan=play_plan,
                            persona_pack=persona_pack,
                            persona_id=persona_id,
                            logs=persona_logs.get(persona_id, []),
                            summary=persona_summaries[persona_id],
                            turn_play_eval_logs=persona_turn_play_eval.get(persona_id, []),
                        ),
                    ): persona_id
                    for persona_id in play_eval_persona_ids
                    if persona_summaries[persona_id].worker_status != "failed"
                }
                pending_eval = set(eval_future_map.keys())
                session_eval_deadline_monotonic = _compose_deadline_seconds(
                    outer_deadline_monotonic=case_deadline_monotonic,
                    phase_timeout_seconds=session_play_eval_timeout_seconds,
                )
                while pending_eval:
                    remaining = _remaining_deadline_seconds(session_eval_deadline_monotonic)
                    if remaining is not None and remaining <= 0:
                        for future in list(pending_eval):
                            persona_id = eval_future_map[future]
                            future.cancel()
                            persona_session_play_eval_reports[persona_id] = play_eval_tools.SessionPlayEvalReport(
                                case_id=case.case_id,
                                persona_id=persona_id,
                                play_eval_status="failed",
                                play_eval_error="eval_incomplete:session_play_eval_deadline_exceeded",
                            )
                        pending_eval.clear()
                        break
                    wait_timeout = min(1.0, remaining) if remaining is not None else 1.0
                    done, _ = wait(pending_eval, timeout=wait_timeout, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        pending_eval.discard(future)
                        persona_id = eval_future_map[future]
                        try:
                            persona_session_play_eval_reports[persona_id] = future.result()
                        except Exception as exc:  # noqa: BLE001
                            persona_session_play_eval_reports[persona_id] = play_eval_tools.SessionPlayEvalReport(
                                case_id=case.case_id,
                                persona_id=persona_id,
                                play_eval_status="failed",
                                play_eval_error=f"session_play_eval_failed:{str(exc)[:180]}",
                            )
            finally:
                for future in list(pending_eval):
                    future.cancel()
                eval_executor.shutdown(wait=False, cancel_futures=True)
            for persona_id in persona_ids:
                if persona_id not in persona_session_play_eval_reports:
                    summary = persona_summaries.get(persona_id)
                    if persona_id not in play_eval_persona_id_set:
                        persona_session_play_eval_reports[persona_id] = play_eval_tools.SessionPlayEvalReport(
                            case_id=case.case_id,
                            persona_id=persona_id,
                            play_eval_status="completed",
                            play_eval_error="skipped_by_persona_sampling",
                        )
                        continue
                    persona_session_play_eval_reports[persona_id] = play_eval_tools.SessionPlayEvalReport(
                        case_id=case.case_id,
                        persona_id=persona_id,
                        play_eval_status="failed",
                        play_eval_error=(
                            f"worker_status:{summary.worker_status}"
                            if summary is not None
                            else "missing_summary"
                        )[:240],
                    )
        if enable_session_play_eval:
            for persona_id, report in persona_session_play_eval_reports.items():
                _write_json(persona_dirs[persona_id] / "session_play_eval_report.json", report)
        if enable_llm_text_audit:
            llm_persona_ids = [
                persona_id
                for persona_id in persona_ids
                if persona_summaries.get(persona_id) is not None
            ]
            llm_persona_ids = _sample_persona_ids_for_eval_phase(
                llm_persona_ids,
                case_id=case.case_id,
                phase="llm_text_audit",
                persona_limit=normalized_llm_audit_persona_limit,
            )
            llm_persona_id_set = set(llm_persona_ids)
            llm_executor = ThreadPoolExecutor(max_workers=llm_text_audit_max_workers or min(4, max(1, len(llm_persona_ids))))
            pending_llm: set[Any] = set()
            llm_future_map: dict[Any, str] = {}
            try:
                llm_future_map = {
                    llm_executor.submit(
                        _evaluate_persona_llm_text_audit,
                        case_id=case.case_id,
                        preview=preview,
                        plan=play_plan,
                        persona_pack=persona_pack,
                        persona_id=persona_id,
                        logs=persona_logs.get(persona_id, []),
                        summary=persona_summaries[persona_id],
                    ): persona_id
                    for persona_id in llm_persona_ids
                    if persona_summaries[persona_id].worker_status != "failed"
                }
                pending_llm = set(llm_future_map.keys())
                llm_audit_deadline_monotonic = _compose_deadline_seconds(
                    outer_deadline_monotonic=case_deadline_monotonic,
                    phase_timeout_seconds=llm_text_audit_timeout_seconds,
                )
                while pending_llm:
                    remaining = _remaining_deadline_seconds(llm_audit_deadline_monotonic)
                    if remaining is not None and remaining <= 0:
                        for future in list(pending_llm):
                            persona_id = llm_future_map[future]
                            future.cancel()
                            persona_turn_llm_text_audit.setdefault(persona_id, [])
                            persona_session_llm_text_audit_reports[persona_id] = llm_text_audit_tools.SessionLlmTextAuditReport(
                                case_id=case.case_id,
                                persona_id=persona_id,
                                llm_audit_status="failed",
                                llm_audit_error="case_timeout:llm_text_audit_deadline_exceeded",
                            )
                        pending_llm.clear()
                        break
                    wait_timeout = min(1.0, remaining) if remaining is not None else 1.0
                    done, _ = wait(pending_llm, timeout=wait_timeout, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        pending_llm.discard(future)
                        persona_id = llm_future_map[future]
                        try:
                            turn_records, session_report = future.result()
                        except Exception as exc:  # noqa: BLE001
                            turn_records = []
                            session_report = llm_text_audit_tools.SessionLlmTextAuditReport(
                                case_id=case.case_id,
                                persona_id=persona_id,
                                llm_audit_status="failed",
                                llm_audit_error=f"llm_text_audit_failed:{str(exc)[:180]}",
                            )
                        persona_turn_llm_text_audit[persona_id] = turn_records
                        persona_session_llm_text_audit_reports[persona_id] = session_report
            finally:
                for future in list(pending_llm):
                    future.cancel()
                llm_executor.shutdown(wait=False, cancel_futures=True)
            for persona_id in persona_ids:
                if persona_id not in persona_session_llm_text_audit_reports:
                    summary = persona_summaries.get(persona_id)
                    persona_turn_llm_text_audit.setdefault(persona_id, [])
                    if persona_id not in llm_persona_id_set:
                        persona_session_llm_text_audit_reports[persona_id] = llm_text_audit_tools.SessionLlmTextAuditReport(
                            case_id=case.case_id,
                            persona_id=persona_id,
                            llm_audit_status="completed",
                            llm_audit_error="skipped_by_persona_sampling",
                        )
                        continue
                    persona_session_llm_text_audit_reports[persona_id] = llm_text_audit_tools.SessionLlmTextAuditReport(
                        case_id=case.case_id,
                        persona_id=persona_id,
                        llm_audit_status="failed",
                        llm_audit_error=(
                            f"worker_status:{summary.worker_status}"
                            if summary is not None
                            else "missing_summary"
                        )[:240],
                    )
            for persona_id in persona_ids:
                _write_jsonl(
                    persona_dirs[persona_id] / "turn_llm_text_audit_logs.jsonl",
                    persona_turn_llm_text_audit.get(persona_id, []),
                )
                _write_json(
                    persona_dirs[persona_id] / "session_llm_text_audit_report.json",
                    persona_session_llm_text_audit_reports[persona_id],
                )
        if enable_chaos_persona_shadow:
            chaos_persona_id: SelfPlayPersonaId = "chaos"
            shadow_adapter_map = _merge_adapter_map(
                (chaos_persona_id,),
                adapters,
                prefer_llm=live_mode.startswith("live"),
                allow_decision_fallback=not strict_mode,
            )
            shadow_dir = resolved_output_dir / "personas_shadow" / chaos_persona_id
            shadow_dir.mkdir(parents=True, exist_ok=True)
            logs, summary, turn_play_eval_logs = _run_persona(
                case_id=case.case_id,
                plan=play_plan,
                play_service=play_service,
                story_id=published_story.story_id,
                actor_user_id=settings.default_actor_id,
                adapter=shadow_adapter_map[chaos_persona_id],
                persona_dir=shadow_dir,
                decision_timeout_seconds=decision_timeout_seconds,
                max_repair_only_turns=max_repair_only_turns,
                select_id_probability=normalized_select_id_probability,
                typing_rhythm_enabled=bool(typing_rhythm_enabled),
                draft_intent_probability=normalized_draft_intent_probability,
                draft_call_count_min=normalized_draft_call_count_min,
                draft_call_count_max=normalized_draft_call_count_max,
                draft_debounce_ms=normalized_draft_debounce_ms,
                strict_no_repair_fallback=strict_mode,
                collect_turn_play_eval=enable_turn_play_eval,
                case_deadline_monotonic=_compose_deadline_seconds(
                    outer_deadline_monotonic=case_deadline_monotonic,
                    phase_timeout_seconds=persona_runtime_timeout_seconds,
                ),
            )
            shadow_persona_logs[chaos_persona_id] = logs
            shadow_persona_summaries[chaos_persona_id] = summary
            shadow_persona_turn_play_eval[chaos_persona_id] = turn_play_eval_logs
            if enable_session_play_eval:
                if summary.worker_status != "failed":
                    shadow_persona_session_play_eval_reports[chaos_persona_id] = play_eval_tools.evaluate_session(
                        _session_play_eval_payload(
                            case_id=case.case_id,
                            preview=preview,
                            plan=play_plan,
                            persona_pack=persona_pack,
                            persona_id=chaos_persona_id,
                            logs=logs,
                            summary=summary,
                            turn_play_eval_logs=turn_play_eval_logs,
                        )
                    )
                else:
                    shadow_persona_session_play_eval_reports[chaos_persona_id] = play_eval_tools.SessionPlayEvalReport(
                        case_id=case.case_id,
                        persona_id=chaos_persona_id,
                        play_eval_status="failed",
                        play_eval_error=f"worker_status:{summary.worker_status}"[:240],
                    )
                _write_json(
                    shadow_dir / "session_play_eval_report.json",
                    shadow_persona_session_play_eval_reports[chaos_persona_id],
                )
            if enable_llm_text_audit:
                if summary.worker_status != "failed":
                    turn_records, session_report = _evaluate_persona_llm_text_audit(
                        case_id=case.case_id,
                        preview=preview,
                        plan=play_plan,
                        persona_pack=persona_pack,
                        persona_id=chaos_persona_id,
                        logs=logs,
                        summary=summary,
                    )
                    shadow_persona_turn_llm_text_audit[chaos_persona_id] = turn_records
                    shadow_persona_session_llm_text_audit_reports[chaos_persona_id] = session_report
                else:
                    shadow_persona_turn_llm_text_audit[chaos_persona_id] = []
                    shadow_persona_session_llm_text_audit_reports[chaos_persona_id] = llm_text_audit_tools.SessionLlmTextAuditReport(
                        case_id=case.case_id,
                        persona_id=chaos_persona_id,
                        llm_audit_status="failed",
                        llm_audit_error=f"worker_status:{summary.worker_status}"[:240],
                    )
                _write_jsonl(
                    shadow_dir / "turn_llm_text_audit_logs.jsonl",
                    shadow_persona_turn_llm_text_audit.get(chaos_persona_id, []),
                )
                _write_json(
                    shadow_dir / "session_llm_text_audit_report.json",
                    shadow_persona_session_llm_text_audit_reports[chaos_persona_id],
                )
            _write_json(
                resolved_output_dir / "shadow_persona_summary.json",
                {
                    "enabled": True,
                    "persona_ids": [chaos_persona_id],
                    "run_summaries": {
                        key: value.model_dump(mode="json")
                        for key, value in shadow_persona_summaries.items()
                    },
                    "session_play_eval_reports": {
                        key: value.model_dump(mode="json")
                        for key, value in shadow_persona_session_play_eval_reports.items()
                    },
                    "session_llm_text_audit_reports": {
                        key: value.model_dump(mode="json")
                        for key, value in shadow_persona_session_llm_text_audit_reports.items()
                    },
                },
            )
        comparison = _build_comparison_summary(
            case.case_id,
            persona_summaries,
            persona_logs,
            source_live_depth_score=source_live_depth_score,
            source_final_mode_path=source_final_mode_path,
        )
        _write_json(resolved_output_dir / "comparison_summary.json", comparison)
        (resolved_output_dir / "comparison_analysis.md").write_text(
            _analysis_markdown(plan=play_plan, comparison=comparison, persona_pack=persona_pack)
        )
        return {
            "case_id": case.case_id,
            "live_mode": live_mode,
            "execution_mode": execution_mode,
            "compiled_play_plan": play_plan,
            "persona_pack": persona_pack,
            "persona_summaries": persona_summaries,
            "session_play_eval_reports": persona_session_play_eval_reports,
            "session_llm_text_audit_reports": persona_session_llm_text_audit_reports,
            "comparison_summary": comparison,
            "shadow_persona_summaries": shadow_persona_summaries,
            "shadow_session_play_eval_reports": shadow_persona_session_play_eval_reports,
            "shadow_session_llm_text_audit_reports": shadow_persona_session_llm_text_audit_reports,
            "artifacts_dir": str(resolved_output_dir),
        }
    except Exception as exc:  # noqa: BLE001
        _write_failure_report(resolved_output_dir / "failure_report.md", stage="self_play_pilot", detail=str(exc))
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the internal three-agent self-play pilot.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--case-id", default=PILOT_CASE_ID)
    parser.add_argument("--live-mode", default=LIVE_AUTHOR_MODE)
    parser.add_argument("--execution-mode", choices=("parallel", "sequential"), default="parallel")
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--decision-timeout-seconds", type=float, default=DEFAULT_DECISION_TIMEOUT_SECONDS)
    parser.add_argument("--max-repair-only-turns", type=int, default=DEFAULT_MAX_REPAIR_ONLY_TURNS)
    parser.add_argument("--select-id-probability", type=float, default=DEFAULT_SELECT_ID_PROBABILITY)
    parser.add_argument("--typing-rhythm-enabled", action="store_true")
    parser.add_argument("--typing-rhythm-disabled", action="store_true")
    parser.add_argument("--draft-intent-probability", type=float, default=DEFAULT_DRAFT_INTENT_PROBABILITY)
    parser.add_argument("--draft-call-count-min", type=int, default=DEFAULT_DRAFT_CALL_COUNT_MIN)
    parser.add_argument("--draft-call-count-max", type=int, default=DEFAULT_DRAFT_CALL_COUNT_MAX)
    parser.add_argument("--draft-debounce-ms", type=int, default=DEFAULT_DRAFT_DEBOUNCE_MS)
    parser.add_argument("--play-length-preset", choices=PLAY_LENGTH_PRESETS)
    parser.add_argument("--enable-llm-text-audit", action="store_true")
    parser.add_argument("--llm-text-audit-max-workers", type=int, default=None)
    parser.add_argument("--session-play-eval-persona-limit", type=int, default=None)
    parser.add_argument("--llm-text-audit-persona-limit", type=int, default=None)
    parser.add_argument("--enable-chaos-persona-shadow", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    typing_rhythm_enabled = (
        True
        if bool(args.typing_rhythm_enabled)
        else (False if bool(args.typing_rhythm_disabled) else DEFAULT_TYPING_RHYTHM_ENABLED)
    )
    result = run_self_play_pilot(
        args.output_dir,
        case_id=args.case_id,
        live_mode=args.live_mode,
        execution_mode=args.execution_mode,
        max_workers=args.max_workers,
        decision_timeout_seconds=args.decision_timeout_seconds,
        max_repair_only_turns=args.max_repair_only_turns,
        select_id_probability=min(max(float(args.select_id_probability), 0.0), 1.0),
        typing_rhythm_enabled=typing_rhythm_enabled,
        draft_intent_probability=min(max(float(args.draft_intent_probability), 0.0), 1.0),
        draft_call_count_min=max(1, int(args.draft_call_count_min)),
        draft_call_count_max=max(1, int(args.draft_call_count_max)),
        draft_debounce_ms=max(0, int(args.draft_debounce_ms)),
        play_length_preset=args.play_length_preset,
        enable_llm_text_audit=bool(args.enable_llm_text_audit),
        llm_text_audit_max_workers=args.llm_text_audit_max_workers,
        session_play_eval_persona_limit=(
            max(1, int(args.session_play_eval_persona_limit))
            if args.session_play_eval_persona_limit is not None
            else None
        ),
        llm_text_audit_persona_limit=(
            max(1, int(args.llm_text_audit_persona_limit))
            if args.llm_text_audit_persona_limit is not None
            else None
        ),
        enable_chaos_persona_shadow=bool(args.enable_chaos_persona_shadow),
    )
    print(json.dumps(_to_jsonable(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
