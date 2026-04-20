from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
import re
import time
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author.normalize import normalize_whitespace, trim_text, unique_preserve
from rpg_backend.author_v2.contracts import (
    CompiledPlayPlan,
    CompiledSegment,
    RelationshipSceneFrame,
    SegmentRoleId,
    SegmentSuggestionLane,
    SuggestionLaneId,
    TurnConfidence,
    VoiceAtom,
)
from rpg_backend.config import get_settings
from rpg_backend.play.gateway import PlayGatewayError, PlayLLMGateway, get_play_llm_gateway
from rpg_backend.play_v2.causal_contract import CausalContractEngine
from rpg_backend.play_v2.delta_pack_runtime import (
    clear_delta_pack_future,
    effective_voice_atom_weight,
    poll_and_apply_pending_delta_pack,
    resolve_segment_with_delta,
    schedule_next_beat_delta_pack,
)
from rpg_backend.play_v2.director import EventDirector
from rpg_backend.play_v2.invariants import InvariantValidator
from rpg_backend.play_v2.latent_events import LatentEventEngine
from rpg_backend.play_v2.narration_frames import (
    build_npc_reaction_beat,
    build_render_seed,
    build_supporting_reaction_beats,
    build_tone_example_style_hints,
    NarrationRenderSeed,
    NpcReactionBeat,
    SupportingReactionBeat,
    ToneExampleStyleHints,
)
from rpg_backend.play_v2.narration_surface import render_npc_texture_emergency
from rpg_backend.play_v2.narration_variants import (
    append_narration_history,
    canonicalize_phrase,
)
from rpg_backend.play_v2.storylet_matcher import StoryletMatch, find_matching_storylets
from rpg_backend.play_v2.semantic_resolver import resolve_semantic_effects
from rpg_backend.play_v2.narration_memory import append_narration_event, consolidate_segment_memory, build_narration_memory_context
from rpg_backend.play_v2.semantic_planners import (
    EventPlanner,
    PayoffPlanner,
    QuestionPlanner,
    StakePlanner,
    StylePlanner,
)
from rpg_backend.play_v2.shell_propagation import pick_shell_edge
from rpg_backend.play_v2.turn_reducers import HookLifecycleReducer
from rpg_backend.play_v2.contracts import (
    CallbackQueueItem,
    CallbackTurnStatusRecord,
    CostRouteRecord,
    LatentEvent,
    LatentEventControl,
    NpcMindState,
    NpcUtilityDeltaItem,
    NpcSceneFrame,
    SemanticEffect,
    SceneQuestionStateRecord,
    ShellPropagationEdgeRecord,
    UrbanControlAction,
    UrbanRelationshipTargetState,
    UrbanSuggestedAction,
    UrbanTurnIntent,
    UrbanTurnResult,
    UrbanWorldState,
    TurnSemanticEventPlan,
    TurnSemanticPayoffPlan,
    TurnSemanticPlan,
    TurnSemanticQuestionPlan,
    TurnSemanticStakePlan,
    TurnSemanticStylePlan,
    UnresolvedCostRecord,
)

MOVE_KEYWORDS: dict[RelationshipMoveFamily, tuple[str, ...]] = {
    "flirt": ("暧昧", "撩", "靠近", "试着亲近", "调情"),
    "probe_secret": ("试探", "套话", "追问", "调查", "问真相"),
    "comfort": ("安慰", "护着", "维护", "哄", "站在"),
    "deflect": ("回避", "转移", "敷衍", "压下去"),
    "accuse": ("质问", "指责", "撕", "逼问"),
    "ally_with": ("联手", "合作", "站队", "结盟"),
    "betray": ("背刺", "出卖", "卖掉", "反手"),
    "public_reveal": ("曝光", "公开", "当众", "直播", "说破"),
    "private_confession": ("坦白", "承认", "告白", "私下说"),
    "jealousy_trigger": ("刺激", "吃醋", "挑拨", "让他嫉妒"),
}

MOVE_FAMILY_SURFACE_LABELS: dict[RelationshipMoveFamily, str] = {
    "flirt": "暧昧试探",
    "probe_secret": "追问真相",
    "comfort": "护住她",
    "deflect": "转移火线",
    "accuse": "当面质问",
    "ally_with": "公开认边",
    "betray": "反手切割",
    "public_reveal": "当众翻牌",
    "private_confession": "低声坦白",
    "jealousy_trigger": "故意拱火",
}

PUBLIC_FRAME_KEYWORDS = ("公开", "当众", "直播", "舞台", "镜头", "家宴", "董事会")
SEMI_PUBLIC_FRAME_KEYWORDS = ("走廊", "包厢", "后台", "角落")
OUT_OF_SCOPE_INPUT_KEYWORDS = (
    "召唤",
    "陨石",
    "核弹",
    "瞬移",
    "读档",
    "存档",
    "上帝模式",
    "管理员",
    "控制台",
    "系统指令",
    "黑进",
    "外挂",
)
LOW_INFORMATION_INPUT_EXACT = {
    "嗯",
    "嗯。",
    "啊",
    "啊。",
    "哦",
    "哦。",
    "随便",
    "都行",
    "看着办",
    "...",
    "。。",
    "。",
}

_DEFAULT_CONTROL_BIAS_SEGMENT_LANE: dict[str, SuggestionLaneId] = {
    "opening": "side",
    "misread": "side",
    "pressure": "burst",
    "reversal": "burst",
}
_DEFAULT_CONTROL_BIAS_SOFT_MOVES: set[RelationshipMoveFamily] = {"comfort", "flirt", "ally_with"}
_DEFAULT_CONTROL_BIAS_LEVERAGE_MOVES: set[RelationshipMoveFamily] = {
    "accuse",
    "public_reveal",
    "probe_secret",
    "betray",
    "jealousy_trigger",
    "deflect",
}
_DEFAULT_CONTROL_BIAS_LOW_CONFIDENCE = 0.62
_DEFAULT_CONTROL_BIAS_OPENING_FORCE_UNTIL_TURN_INDEX = 1
_VALID_SEGMENT_ROLES: set[str] = {
    "opening",
    "misread",
    "pressure",
    "reversal",
    "reveal",
    "terminal",
}
_DEFAULT_INTENT_LLM_HIGH_RISK_SEGMENT_ROLES: set[str] = {"reveal", "terminal"}
_DEFAULT_INTENT_LLM_CONFIDENCE_THRESHOLD = 0.5
_DEFAULT_INTENT_LLM_MIN_SEMANTIC_CLAUSE_COUNT = 3
_DEFAULT_INTENT_LLM_SCENE_HEAT_THRESHOLD = 6
_DEFAULT_INTENT_LLM_SECRET_EXPOSURE_THRESHOLD = 5
_DEFAULT_MICRO_SIM_LLM_HIGH_RISK_SEGMENT_ROLES: set[str] = {"reveal", "terminal"}
_DEFAULT_MICRO_SIM_LLM_SCENE_HEAT_THRESHOLD = 6
_DEFAULT_MICRO_SIM_LLM_SECRET_EXPOSURE_THRESHOLD = 6
_DEFAULT_PASS2_HIGH_RISK_SEGMENT_ROLES: set[str] = {"reveal", "terminal"}
_DEFAULT_PASS2_SCENE_HEAT_THRESHOLD = 6
_DEFAULT_PASS2_SECRET_EXPOSURE_THRESHOLD = 6
_DEFAULT_PASS2_ROUTE_LOCK_THRESHOLD = 5
CONTROL_ACTION_KEYWORDS: dict[LatentEventControl, tuple[str, ...]] = {
    "press": ("压住", "先压", "稳住", "降温", "缓一下", "拖一拍"),
    "redirect": ("转移", "转给", "甩锅", "嫁祸", "推给", "让他背", "换人扛"),
    "detonate": ("引爆", "拆雷", "提前炸", "现在爆", "掀桌", "翻牌"),
    "none": (),
}

MOVE_DELTAS: dict[RelationshipMoveFamily, dict[str, int]] = {
    "flirt": {"affection": 2, "trust": 1, "tension": 1, "route": 1},
    "probe_secret": {"trust": -1, "suspicion": 2, "secret_exposure": 1, "heat": 1},
    "comfort": {"affection": 1, "trust": 2, "suspicion": -1, "route": 1},
    "deflect": {"trust": -1, "public_image": 1, "tension": 1},
    "accuse": {"tension": 2, "suspicion": 1, "heat": 1},
    "ally_with": {"trust": 2, "dependency": 1, "route": 2},
    "betray": {"trust": -2, "suspicion": 2, "heat": 1, "route": -1},
    "public_reveal": {"tension": 2, "secret_exposure": 2, "heat": 2, "public_image": -1},
    "private_confession": {"affection": 2, "trust": 1, "dependency": 1, "route_lock": 1, "route": 1},
    "jealousy_trigger": {"affection": 1, "tension": 2, "suspicion": 1, "heat": 1},
}

LANE_MOVE_FAMILIES: dict[SuggestionLaneId, tuple[RelationshipMoveFamily, ...]] = {
    "relationship": ("flirt", "comfort", "private_confession", "ally_with"),
    "side": ("ally_with", "comfort", "accuse", "deflect"),
    "burst": ("probe_secret", "public_reveal", "accuse", "betray", "jealousy_trigger"),
}

MOVE_DEFERRED_KIND: dict[RelationshipMoveFamily, str] = {
    "comfort": "relationship_debt",
    "ally_with": "relationship_debt",
    "private_confession": "secret_pressure",
    "deflect": "public_wave",
    "public_reveal": "public_wave",
    "probe_secret": "secret_pressure",
    "accuse": "npc_action",
    "betray": "relationship_debt",
    "jealousy_trigger": "npc_action",
    "flirt": "relationship_debt",
}


def _play_tuning_profile(plan: CompiledPlayPlan) -> Any:
    profile = getattr(plan, "quality_tuning_profile", None)
    if profile is None:
        return None
    return getattr(profile, "play", None)


def _control_bias_segment_lane(plan: CompiledPlayPlan) -> dict[str, SuggestionLaneId]:
    profile = _play_tuning_profile(plan)
    raw = dict(getattr(profile, "control_bias_segment_lane", {}) or {})
    output = {
        str(key): value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    return output or dict(_DEFAULT_CONTROL_BIAS_SEGMENT_LANE)


def _control_bias_soft_moves(plan: CompiledPlayPlan) -> set[RelationshipMoveFamily]:
    profile = _play_tuning_profile(plan)
    raw = list(getattr(profile, "control_bias_soft_moves", []) or [])
    output = {
        move
        for move in raw
        if move in MOVE_KEYWORDS
    }
    return output or set(_DEFAULT_CONTROL_BIAS_SOFT_MOVES)


def _control_bias_low_confidence(plan: CompiledPlayPlan) -> float:
    profile = _play_tuning_profile(plan)
    if profile is None:
        return _DEFAULT_CONTROL_BIAS_LOW_CONFIDENCE
    try:
        value = float(getattr(profile, "control_bias_low_confidence"))
    except Exception:  # noqa: BLE001
        return _DEFAULT_CONTROL_BIAS_LOW_CONFIDENCE
    return max(0.0, min(value, 1.0))


def _control_bias_opening_force_until_turn_index(plan: CompiledPlayPlan) -> int:
    profile = _play_tuning_profile(plan)
    if profile is None:
        return _DEFAULT_CONTROL_BIAS_OPENING_FORCE_UNTIL_TURN_INDEX
    try:
        value = int(getattr(profile, "control_bias_opening_force_until_turn_index"))
    except Exception:  # noqa: BLE001
        return _DEFAULT_CONTROL_BIAS_OPENING_FORCE_UNTIL_TURN_INDEX
    return max(0, min(value, 4))


def _segment_roles_from_profile(
    profile: Any | None,
    *,
    attr: str,
    default: set[str],
) -> set[str]:
    raw = list(getattr(profile, attr, list(default)) or list(default)) if profile is not None else list(default)
    output = {
        str(item).strip()
        for item in raw
        if str(item).strip() in _VALID_SEGMENT_ROLES
    }
    return output or set(default)


def _intent_llm_high_risk_segment_roles(plan: CompiledPlayPlan) -> set[str]:
    profile = _play_tuning_profile(plan)
    return _segment_roles_from_profile(
        profile,
        attr="intent_llm_high_risk_segment_roles",
        default=_DEFAULT_INTENT_LLM_HIGH_RISK_SEGMENT_ROLES,
    )


def _micro_sim_llm_high_risk_segment_roles(plan: CompiledPlayPlan) -> set[str]:
    profile = _play_tuning_profile(plan)
    return _segment_roles_from_profile(
        profile,
        attr="micro_sim_llm_high_risk_segment_roles",
        default=_DEFAULT_MICRO_SIM_LLM_HIGH_RISK_SEGMENT_ROLES,
    )


def _pass2_high_risk_segment_roles(plan: CompiledPlayPlan) -> set[str]:
    profile = _play_tuning_profile(plan)
    return _segment_roles_from_profile(
        profile,
        attr="key_burst_pass2_high_risk_segment_roles",
        default=_DEFAULT_PASS2_HIGH_RISK_SEGMENT_ROLES,
    )


def _profile_float(
    profile: Any | None,
    *,
    attr: str,
    default: float,
    lower: float,
    upper: float,
) -> float:
    if profile is None:
        return default
    try:
        value = float(getattr(profile, attr))
    except Exception:  # noqa: BLE001
        return default
    return max(lower, min(value, upper))


def _profile_int(
    profile: Any | None,
    *,
    attr: str,
    default: int,
    lower: int,
    upper: int,
) -> int:
    if profile is None:
        return default
    try:
        value = int(getattr(profile, attr))
    except Exception:  # noqa: BLE001
        return default
    return max(lower, min(value, upper))


def _has_key_escalation(state: UrbanWorldState) -> bool:
    for escalation in list(state.last_turn_escalations or []):
        if escalation.control == "detonate":
            return True
        if escalation.kind in {"public_wave", "secret_pressure", "npc_action"}:
            return True
    return False


def _should_invoke_intent_llm(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    input_text: str,
    clause_intents: list[_ClauseIntent],
    heuristic_candidate: _IntentCandidate,
    selected_control_action_id: str | None,
    control_action: LatentEventControl | None,
) -> tuple[bool, str]:
    if selected_control_action_id or (control_action and control_action != "none"):
        return False, "explicit_control"
    if _is_low_information_input(input_text):
        return False, "low_information"
    return True, "llm_first_default"


def _should_invoke_micro_sim_llm(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    segment_role: str,
) -> tuple[bool, str]:
    if segment_role == 'opening' and state.turn_index <= 1:
        return False, 'opening_warmup'
    return True, 'llm_first_default'


def _should_run_compose_pass2(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    segment_role: str,
    turn_complexity: Literal["normal", "key_burst"],
) -> tuple[bool, str]:
    if turn_complexity != "key_burst":
        return False, "normal_turn"
    high_risk_roles = _pass2_high_risk_segment_roles(plan)
    if segment_role not in high_risk_roles:
        return False, "segment_not_pass2_high_risk"
    profile = _play_tuning_profile(plan)
    scene_heat_threshold = _profile_int(
        profile,
        attr="key_burst_pass2_scene_heat_threshold",
        default=_DEFAULT_PASS2_SCENE_HEAT_THRESHOLD,
        lower=0,
        upper=6,
    )
    secret_exposure_threshold = _profile_int(
        profile,
        attr="key_burst_pass2_secret_exposure_threshold",
        default=_DEFAULT_PASS2_SECRET_EXPOSURE_THRESHOLD,
        lower=0,
        upper=6,
    )
    route_lock_threshold = _profile_int(
        profile,
        attr="key_burst_pass2_route_lock_threshold",
        default=_DEFAULT_PASS2_ROUTE_LOCK_THRESHOLD,
        lower=0,
        upper=6,
    )
    if (
        state.secret_exposure >= secret_exposure_threshold
        or (_has_key_escalation(state) and state.secret_exposure >= 2)
    ):
        return True, "segment_high_risk"
    if (
        state.scene_heat >= scene_heat_threshold
        and state.secret_exposure >= secret_exposure_threshold
        and state.route_lock >= route_lock_threshold
    ):
        return True, "pressure_locked"
    return False, "pass2_gated"


def _control_bias_leverage_bonus(plan: CompiledPlayPlan) -> float:
    profile = _play_tuning_profile(plan)
    if profile is None:
        return 3.0
    try:
        return max(0.0, float(getattr(profile, "control_bias_leverage_bonus")))
    except Exception:  # noqa: BLE001
        return 3.0


def _turn_compose_limits(
    *,
    plan: CompiledPlayPlan,
    turn_complexity: Literal["normal", "key_burst"],
) -> tuple[int, int, int, int]:
    profile = _play_tuning_profile(plan)
    if profile is None:
        if turn_complexity == "normal":
            return 2, 1, 3, 5
        return 3, 2, 6, 8
    if turn_complexity == "normal":
        return (
            int(getattr(profile, "normal_style_case_max", 2) or 2),
            int(getattr(profile, "normal_supporting_payload_limit", 1) or 1),
            int(getattr(profile, "normal_consequence_tag_limit", 3) or 3),
            int(getattr(profile, "normal_shell_token_limit", 5) or 5),
        )
    return (
        int(getattr(profile, "key_burst_style_case_max", 3) or 3),
        int(getattr(profile, "key_burst_supporting_payload_limit", 2) or 2),
        int(getattr(profile, "key_burst_consequence_tag_limit", 6) or 6),
        int(getattr(profile, "key_burst_shell_token_limit", 8) or 8),
    )


def _key_burst_pass2_config(plan: CompiledPlayPlan) -> tuple[bool, int, int, float]:
    profile = _play_tuning_profile(plan)
    if profile is None:
        return True, 1, 280, 8000.0
    return (
        bool(getattr(profile, "key_burst_pass2_enabled", True)),
        max(0, int(getattr(profile, "key_burst_pass2_max_retry", 1) or 1)),
        max(120, int(getattr(profile, "key_burst_pass2_max_output_tokens", 280) or 280)),
        max(1000.0, float(getattr(profile, "key_burst_pass2_latency_budget_ms", 8000.0) or 8000.0)),
    )


def _sanitize_compose_payload(
    payload: dict[str, Any] | None,
) -> tuple[str, dict[str, int | float | str | bool]]:
    if not isinstance(payload, dict):
        return "", {}
    narration = normalize_whitespace(str(payload.get("narration") or "")).strip()
    diagnostics_raw = payload.get("diagnostics")
    diagnostics: dict[str, int | float | str | bool] = {}
    if isinstance(diagnostics_raw, dict):
        for key, value in diagnostics_raw.items():
            if isinstance(value, bool):
                diagnostics[str(key)] = value
            elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
                diagnostics[str(key)] = value
    prewarm_source = str(payload.get("compose_prewarm_source") or payload.get("source") or "").strip()
    if prewarm_source:
        diagnostics["compose_prewarm_source"] = prewarm_source
    compose_tokens = payload.get("compose_total_tokens")
    if isinstance(compose_tokens, (int, float)) and not isinstance(compose_tokens, bool):
        diagnostics["compose_total_tokens"] = max(int(round(float(compose_tokens))), 0)
    compose_input_tokens = payload.get("compose_input_tokens")
    if isinstance(compose_input_tokens, (int, float)) and not isinstance(compose_input_tokens, bool):
        diagnostics["compose_input_tokens"] = max(int(round(float(compose_input_tokens))), 0)
    compose_output_tokens = payload.get("compose_output_tokens")
    if isinstance(compose_output_tokens, (int, float)) and not isinstance(compose_output_tokens, bool):
        diagnostics["compose_output_tokens"] = max(int(round(float(compose_output_tokens))), 0)
    return narration, diagnostics


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _move_family_surface_label(move_family: RelationshipMoveFamily) -> str:
    return MOVE_FAMILY_SURFACE_LABELS.get(move_family, "出手")


def _segment_threshold(segment: CompiledSegment) -> int:
    if isinstance(getattr(segment, "progress_required", None), int):
        return max(int(segment.progress_required), 1)
    return 1 if segment.is_terminal else 2


def _segment_turn_floor(segment: CompiledSegment) -> int:
    if isinstance(getattr(segment, "segment_turn_floor", None), int):
        return max(int(segment.segment_turn_floor), 1)
    return 1


def _current_segment_turns(state: UrbanWorldState) -> int:
    return max(int(state.turn_index) - int(state.segment_enter_turn_index), 0)


def _segment_progress_cap(segment: CompiledSegment) -> int:
    return max(6, _segment_threshold(segment) + 2)


_QUESTION_STATUS_ORDER: tuple[str, ...] = ("open", "tightening", "flip", "resolved")


def _question_status_rank(status: str) -> int:
    try:
        return _QUESTION_STATUS_ORDER.index(status)
    except ValueError:
        return 0


def _next_question_status(status: str) -> str:
    rank = _question_status_rank(status)
    if rank >= len(_QUESTION_STATUS_ORDER) - 1:
        return "resolved"
    return _QUESTION_STATUS_ORDER[rank + 1]


def _build_initial_scene_questions(plan: CompiledPlayPlan) -> dict[str, SceneQuestionStateRecord]:
    output: dict[str, SceneQuestionStateRecord] = {}
    for segment in plan.segments:
        question = trim_text(segment.scene_goal, 220)
        output[segment.segment_id] = SceneQuestionStateRecord(
            segment_id=segment.segment_id,
            question=question,
            status="open",
            previous_status=None,
            resolved_by=None,
            updated_turn_index=0,
            summary=f"问题已立起：{question}",
        )
    return output


def _scene_question_transition(
    *,
    segment: CompiledSegment,
    state: UrbanWorldState,
    triggered_kind: str | None,
    key_segment_conversion: bool,
) -> tuple[SceneQuestionStateRecord, bool, str | None]:
    record = state.scene_question_states.get(segment.segment_id)
    if record is None:
        record = SceneQuestionStateRecord(
            segment_id=segment.segment_id,
            question=trim_text(segment.scene_goal, 220),
            status="open",
            previous_status=None,
            resolved_by=None,
            updated_turn_index=state.turn_index,
            summary="问题已立起。",
        )
    previous = record.status
    next_status = previous
    forced_advance = False
    advance_reason: str | None = None
    resolved_by: str | None = None
    threshold = _segment_threshold(segment)
    if previous == "open" and (state.segment_progress >= 1 or state.scene_heat >= 3):
        next_status = "tightening"
    if next_status in {"open", "tightening"} and (
        triggered_kind is not None or state.scene_heat >= 4 or state.segment_progress >= max(threshold - 1, 1)
    ):
        next_status = "flip"
    if segment.segment_role in {"reveal", "terminal"} and (
        triggered_kind is not None
        or key_segment_conversion
        or state.segment_progress >= threshold
        or state.secret_exposure >= 3
    ):
        next_status = "resolved"
        resolved_by = (
            f"latent:{triggered_kind}"
            if triggered_kind is not None
            else "key_segment_conversion"
            if key_segment_conversion
            else "progress_threshold"
        )
    if next_status == previous:
        if segment.segment_role in {"reveal", "terminal"} and next_status in {"open", "tightening"}:
            next_status = "flip"
            forced_advance = True
            advance_reason = "key_segment_minimum_progress"
        else:
            next_status = _next_question_status(previous)
            if next_status != previous:
                forced_advance = True
                advance_reason = "same_state_blocked"
    if segment.segment_role in {"reveal", "terminal"} and triggered_kind is None and next_status != "resolved":
        if _question_status_rank(next_status) < _question_status_rank("flip"):
            next_status = "flip"
            forced_advance = True
            advance_reason = "key_segment_conversion_pass"
        if state.segment_progress >= threshold or state.secret_exposure >= 3:
            next_status = "resolved"
            forced_advance = True
            advance_reason = "key_segment_forced_resolve"
            resolved_by = resolved_by or "forced_progress_threshold"
    summary = {
        "open": f"问题已立起：{record.question}",
        "tightening": f"问题收紧：{record.question}",
        "flip": f"问题翻面：{record.question}",
        "resolved": f"问题落锤：{record.question}",
    }[next_status]
    updated = record.model_copy(
        update={
            "previous_status": previous,
            "status": next_status,
            "resolved_by": resolved_by or record.resolved_by,
            "updated_turn_index": state.turn_index,
            "summary": trim_text(summary, 220),
        }
    )
    state.scene_question_states[segment.segment_id] = updated
    return updated, forced_advance, advance_reason


def _expected_question_status(*, segment: CompiledSegment, state: UrbanWorldState) -> str:
    record = state.scene_question_states.get(segment.segment_id)
    current = record.status if record is not None else "open"
    threshold = _segment_threshold(segment)
    if current == "open" and (state.segment_progress >= 1 or state.scene_heat >= 3):
        return "tightening"
    if current in {"open", "tightening"} and (
        state.scene_heat >= 4 or state.segment_progress >= max(threshold - 1, 1)
    ):
        return "flip"
    if segment.segment_role in {"reveal", "terminal"} and (
        state.segment_progress >= threshold or state.secret_exposure >= 3
    ):
        return "resolved"
    return current


def _cost_return_primary_applies(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    prioritized_cost: UnresolvedCostRecord | None,
) -> tuple[bool, bool, bool, int]:
    if prioritized_cost is None or prioritized_cost.status != "pending":
        return False, False, False, 0
    policy_v7 = plan.semantic_strategy_pack.cost_primary_driver_policy_v7
    policy_v8 = plan.semantic_strategy_pack.cost_escalation_ladder_policy_v8
    if not policy_v7.due_cost_forces_primary_driver:
        return False, False, False, 0
    rule_v7 = policy_v7.by_segment_id.get(segment.segment_id)
    if rule_v7 is None:
        return False, False, False, 0
    eligible_roles = set(rule_v7.eligible_segment_roles or [])
    if segment.segment_role not in eligible_roles:
        return False, False, False, int(rule_v7.deferred_retry_bias)
    ladder_rule = _cost_ladder_rule_for_cost(plan=plan, segment=segment, cost=prioritized_cost)
    if ladder_rule is not None and policy_v8.enabled:
        ladder_stage = _compute_cost_ladder_stage(
            turn_index=state.turn_index,
            cost=prioritized_cost,
            ladder_rule=ladder_rule,
        )
    else:
        ladder_stage = _clamp(int(prioritized_cost.ladder_stage or 1), 1, 3)
    prioritized_cost.ladder_stage = ladder_stage
    due_gap = int(prioritized_cost.due_turn) - int(state.turn_index)
    eligible_by_due_window = due_gap <= int(rule_v7.due_window_turns)
    eligible_by_ladder = ladder_stage >= 2
    if not (eligible_by_due_window or eligible_by_ladder):
        return False, False, False, int(rule_v7.deferred_retry_bias)
    settings = get_settings()
    if settings.play_v2_policy_question_progress_v2_enabled:
        question_rule = plan.semantic_strategy_pack.question_progress_policy_v2.by_segment_id.get(segment.segment_id)
        if question_rule is not None and not question_rule.require_cost_focus_when_due:
            return False, False, False, int(rule_v7.deferred_retry_bias)
    if settings.play_v2_policy_cost_visibility_enabled:
        visibility_rule = plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id.get(segment.segment_id)
        if visibility_rule is not None and visibility_rule.require_visible_owner:
            has_owner = bool(prioritized_cost.owner_character_ids or prioritized_cost.payer_character_id)
            if not has_owner:
                return False, False, False, int(rule_v7.deferred_retry_bias)
    due_cost_primary_eligible = True
    player_override_applied = (
        intent.control_source == "explicit"
        and intent.control_action != "none"
        and rule_v7.player_override_mode == "player_first"
    )
    allow_defer_once = bool(ladder_rule.allow_player_defer_once) if ladder_rule is not None else True
    stage3_force_primary = bool(ladder_rule.stage3_force_primary_driver) if ladder_rule is not None else True
    defer_once_available = allow_defer_once and not prioritized_cost.ladder_defer_once_used
    defer_once_applied = bool(player_override_applied and defer_once_available)
    if defer_once_applied:
        prioritized_cost.ladder_defer_once_used = True
        prioritized_cost.ladder_retry_bias_steps = _clamp(
            int(prioritized_cost.ladder_retry_bias_steps or 0) + int(rule_v7.deferred_retry_bias),
            0,
            6,
        )
    forced_even_with_override = bool(player_override_applied and not defer_once_available and ladder_stage >= 3 and stage3_force_primary)
    due_cost_forces_primary_driver_applied = due_cost_primary_eligible and (not player_override_applied or forced_even_with_override)
    secondary_due_cost_pressure = due_cost_primary_eligible and player_override_applied and not forced_even_with_override
    retry_steps = int(rule_v7.deferred_retry_bias) + int(prioritized_cost.ladder_retry_bias_steps or 0)
    prioritized_cost.ladder_summary = trim_text(
        f"代价挂账(stage-{ladder_stage})：{prioritized_cost.scene_question_focus}，最晚第{prioritized_cost.due_turn}回合回钩。",
        220,
    )
    prioritized_cost.summary = prioritized_cost.ladder_summary
    return (
        due_cost_primary_eligible,
        due_cost_forces_primary_driver_applied,
        secondary_due_cost_pressure,
        _clamp(retry_steps, 0, 6),
    )


def _choose_semantic_family(
    *,
    values: list[str],
    turn_index: int,
    slot_name: str,
    recent_values: set[str],
) -> str:
    cleaned = [item for item in values if isinstance(item, str) and item.strip()]
    if not cleaned:
        return "mixed"
    slot_seed = sum(ord(char) for char in f"semantic:{slot_name}:{len(cleaned)}")
    start = (turn_index + slot_seed) % len(cleaned)
    for offset in range(len(cleaned)):
        value = cleaned[(start + offset) % len(cleaned)]
        if value in recent_values:
            continue
        return value
    return cleaned[start]


def _build_turn_semantic_plan_seed(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    state: UrbanWorldState,
) -> TurnSemanticPlan:
    question_plan = QuestionPlanner.seed(plan=plan, segment=segment, state=state)
    style_plan = StylePlanner.seed(plan=plan, segment=segment, state=state)
    return TurnSemanticPlan(
        turn_index=state.turn_index + 1,
        segment_id=segment.segment_id,
        segment_role=segment.segment_role,
        question_plan=question_plan,
        style_plan=style_plan,
        summary="语义总线已建立。",
    )


def _top_stake_summary(top: list[NpcUtilityDeltaItem]) -> str:
    if not top:
        return "利益面本回合变化较弱。"
    head = top[0]
    return trim_text(f"{head.display_name}的利益变化最大（{head.utility_delta:+d}），反应理由={head.reason_family}。", 220)


def _event_plan_summary(*, transition: str, triggered_kind: str | None, key_segment_conversion: bool) -> str:
    if triggered_kind:
        summary = f"事件推进已落锤：{triggered_kind}触发，transition={transition}。"
    elif transition in {"rising", "cooling"}:
        summary = f"事件推进保持流动：top latent transition={transition}。"
    else:
        summary = "事件推进未形成明确流动。"
    if key_segment_conversion:
        summary = f"{summary}关键段启用了conversion补锤。"
    return trim_text(summary, 220)


def _payoff_plan_summary(*, committed: bool, route_kind: str | None, fallback_applied: bool) -> str:
    if not committed:
        return "后果兑现未命中可观测变化。"
    fallback_text = "（触发了最小痛感兜底）" if fallback_applied else ""
    if route_kind:
        return trim_text(f"后果兑现已提交：route={route_kind}{fallback_text}。", 220)
    return trim_text(f"后果兑现已提交{fallback_text}。", 220)


def _finalize_turn_semantic_plan(
    *,
    semantic_plan: TurnSemanticPlan,
    scene_question_state: SceneQuestionStateRecord,
    question_forced_advance: bool,
    question_advance_reason: str | None,
    utility_top: list[NpcUtilityDeltaItem],
    latent_outcome,
    triggered_record,
    cost_route: CostRouteRecord,
    fallback_applied: bool,
    global_delta_keys: list[str],
    relationship_delta_ids: list[str],
) -> TurnSemanticPlan:
    event_transition = str(getattr(latent_outcome, "top_event_transition", "none") or "none")
    triggered_kind = triggered_record.kind if triggered_record is not None else None
    key_segment_conversion = bool(getattr(latent_outcome, "key_segment_conversion", False))
    updated = semantic_plan.model_copy(
        update={
            "question_plan": semantic_plan.question_plan.model_copy(
                update={
                    "final_status": scene_question_state.status,
                    "forced_advance": question_forced_advance,
                    "advance_reason": question_advance_reason,
                    "resolved_by": scene_question_state.resolved_by,
                    "summary": trim_text(
                        (
                            f"问题推进：{semantic_plan.question_plan.before_status} -> {scene_question_state.status}。"
                            if not question_forced_advance
                            else f"问题推进：{semantic_plan.question_plan.before_status} -> {scene_question_state.status}（强制推进:{question_advance_reason or 'fallback'}）。"
                        ),
                        220,
                    ),
                }
            ),
            "stake_plan": TurnSemanticStakePlan(
                top_shifts=list(utility_top[:3]),
                summary=_top_stake_summary(list(utility_top[:3])),
            ),
            "event_plan": TurnSemanticEventPlan(
                top_event_id=getattr(latent_outcome, "top_event_id", None),
                top_event_kind=getattr(latent_outcome, "top_event_kind", None),
                top_event_transition=event_transition,
                triggered_event_id=triggered_record.event_id if triggered_record is not None else None,
                triggered_kind=triggered_kind,
                key_segment_conversion=key_segment_conversion,
                summary=_event_plan_summary(
                    transition=event_transition,
                    triggered_kind=triggered_kind,
                    key_segment_conversion=key_segment_conversion,
                ),
            ),
            "payoff_plan": TurnSemanticPayoffPlan(
                committed=bool(global_delta_keys or relationship_delta_ids),
                route_kind=cost_route.route_kind,
                global_delta_keys=global_delta_keys[:8],
                relationship_delta_ids=relationship_delta_ids[:8],
                fallback_applied=fallback_applied,
                summary=_payoff_plan_summary(
                    committed=bool(global_delta_keys or relationship_delta_ids),
                    route_kind=cost_route.route_kind,
                    fallback_applied=fallback_applied,
                ),
            ),
        }
    )
    updated.summary = trim_text(
        " ".join(
            [
                updated.question_plan.summary,
                updated.stake_plan.summary,
                updated.event_plan.summary,
                updated.payoff_plan.summary,
                updated.style_plan.summary,
            ]
        ),
        220,
    )
    return updated


def _semantic_style_anchor_hit(*, narration: str, style_plan: TurnSemanticStylePlan) -> bool:
    if not style_plan.key_segment:
        return False
    if not style_plan.shell_anchor_tokens:
        return False
    return any(token in narration for token in style_plan.shell_anchor_tokens)


@dataclass(frozen=True)
class _SemanticRenderContract:
    key_segment: bool
    primary_reason_family: str
    counter_reason_family: str
    crowd_reason_family: str
    fallout_reason_family: str
    signal_family: str
    cost_family: str
    cadence: str
    force_main_clause_cost_subject: bool
    cost_subject_payer_name: str | None
    cost_subject_beneficiary_name: str | None
    cost_subject_focus: str | None
    counter_function_role: str = "wait_flip"
    crowd_function_role: str = "wait_flip"
    counter_action_verb: str | None = None
    crowd_action_verb: str | None = None
    counter_receiver_template: str | None = None
    crowd_receiver_template: str | None = None
    role_lexicon_hit: bool = False
    shell_anchor_tokens: tuple[str, ...] = ()


def _semantic_render_contract_from_plan(
    plan: CompiledPlayPlan,
    semantic_plan: TurnSemanticPlan | None,
) -> _SemanticRenderContract | None:
    if semantic_plan is None:
        return None
    style = semantic_plan.style_plan
    payer_name = _target_name(plan, style.payer_character_id) if style.payer_character_id else None
    beneficiary_name = _target_name(plan, style.beneficiary_character_id) if style.beneficiary_character_id else None
    return _SemanticRenderContract(
        key_segment=style.key_segment,
        primary_reason_family=style.reason_family,
        counter_reason_family=style.counter_reason_family or style.reason_family,
        crowd_reason_family=style.crowd_reason_family or style.reason_family,
        fallout_reason_family=style.reason_family,
        signal_family=style.signal_family,
        cost_family=style.cost_family,
        cadence=style.cadence,
        force_main_clause_cost_subject=style.force_main_clause_cost_subject,
        cost_subject_payer_name=payer_name,
        cost_subject_beneficiary_name=beneficiary_name,
        cost_subject_focus=style.cost_subject_focus,
        counter_function_role=style.counter_function_role,
        crowd_function_role=style.crowd_function_role,
        counter_action_verb=style.counter_action_verb,
        crowd_action_verb=style.crowd_action_verb,
        counter_receiver_template=style.counter_receiver_template,
        crowd_receiver_template=style.crowd_receiver_template,
        role_lexicon_hit=style.role_lexicon_hit,
        shell_anchor_tokens=tuple(style.shell_anchor_tokens),
    )


def _apply_semantic_render_contract(
    *,
    style_hints: ToneExampleStyleHints,
    contract: _SemanticRenderContract | None,
) -> tuple[ToneExampleStyleHints, bool]:
    if contract is None:
        return style_hints, False
    anchors = tuple(unique_preserve([*list(style_hints.anchor_tokens), *list(contract.shell_anchor_tokens)]))
    clause_ids = tuple(
        unique_preserve(
            [
                f"reason:primary:{contract.primary_reason_family}",
                f"reason:counter:{contract.counter_reason_family}",
                f"reason:crowd:{contract.crowd_reason_family}",
                f"reason:fallout:{contract.fallout_reason_family}",
                f"signal:{contract.signal_family}",
                f"cost:{contract.cost_family}",
                f"cadence:{contract.cadence}",
            ]
        )
    )
    styled = replace(
        style_hints,
        primary_reason_family=contract.primary_reason_family,
        counter_reason_family=contract.counter_reason_family,
        crowd_reason_family=contract.crowd_reason_family,
        fallout_reason_family=contract.fallout_reason_family,
        signal_family=contract.signal_family,
        cost_family=contract.cost_family,
        cadence=contract.cadence,
        force_main_clause_cost_subject=contract.force_main_clause_cost_subject,
        cost_subject_payer_name=contract.cost_subject_payer_name,
        cost_subject_beneficiary_name=contract.cost_subject_beneficiary_name,
        cost_subject_focus=contract.cost_subject_focus,
        counter_function_role=contract.counter_function_role,
        crowd_function_role=contract.crowd_function_role,
        counter_action_verb=contract.counter_action_verb,
        crowd_action_verb=contract.crowd_action_verb,
        counter_receiver_template=contract.counter_receiver_template,
        crowd_receiver_template=contract.crowd_receiver_template,
        role_lexicon_hit=contract.role_lexicon_hit,
        primary_anchor_tokens=anchors or style_hints.primary_anchor_tokens,
        supporting_anchor_tokens=anchors or style_hints.supporting_anchor_tokens,
        fallout_anchor_tokens=anchors or style_hints.fallout_anchor_tokens,
        anchor_tokens=anchors or style_hints.anchor_tokens,
        primary_clause_family_id=f"reason:primary:{contract.primary_reason_family}",
        counter_clause_family_id=f"reason:counter:{contract.counter_reason_family}",
        crowd_clause_family_id=f"reason:crowd:{contract.crowd_reason_family}",
        fallout_clause_family_id=f"reason:fallout:{contract.fallout_reason_family}",
        used_clause_family_ids=clause_ids,
    )
    return styled, True


def _required_shell_anchor_tokens(shell_id: str) -> tuple[str, ...]:
    if shell_id == "entertainment_scandal":
        return ("镜头", "热搜", "公关", "切割")
    if shell_id == "campus_romance":
        return ("台下", "评审", "名额", "社团", "熟人", "站队")
    if shell_id == "office_power":
        return ("会议室", "口风", "背锅", "站位")
    if shell_id == "wealth_families":
        return ("主桌", "顺位", "认边", "家宴")
    return ()


def _forced_shell_anchor_tail(shell_id: str, anchor: str) -> str:
    picker = (sum(ord(ch) for ch in f"{shell_id}:{anchor}") % 3)
    if shell_id == "entertainment_scandal":
        options = (
            f"{anchor}和外面风向已经把这一下记成公开切割，后面只会更快滚成版本战。",
            f"{anchor}那边已经开始替这一下分版本，接下来只会越传越硬。",
            f"{anchor}已经先把这一步定成公开代价，后面想说轻都来不及。",
        )
        return options[picker]
    if shell_id == "campus_romance":
        options = (
            f"{anchor}已经把这一下记成公开站队，名额和熟人圈的账会立刻跟着动。",
            f"{anchor}那边已经把你们这一步当成认边信号，后续名单会先变脸。",
            f"{anchor}已经先记下这次站位，熟人圈和名额压力会一起压上来。",
        )
        return options[picker]
    if shell_id == "office_power":
        options = (
            f"{anchor}那边已经把这一下记进背锅顺序，后续发言权会先掉一截。",
            f"{anchor}那边已经把责任排位改了一轮，后面谁先开口都要先付账。",
            f"{anchor}已经把这一步记成锅位变化，后续口风会更快偏过去。",
        )
        return options[picker]
    if shell_id == "wealth_families":
        options = (
            f"{anchor}那边已经把这一下记成顺位信号，后续认边会更难回撤。",
            f"{anchor}已经先把这一步写进家族账本，谁想装中立都会更难看。",
            f"{anchor}那边已经按新站位开始记账，后续认边只会更硬。",
        )
        return options[picker]
    fallback = (
        f"{anchor}那边已经把这一下记进后续账本。",
        f"{anchor}那边已经先记下这一步，后续代价会顺着这条线追上来。",
        f"{anchor}那边已经把这次动作挂到账上，后面不会轻轻过去。",
    )
    return fallback[picker]


def _commit_semantic_style_after_render(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    narration: str,
) -> str:
    semantic_plan = state.last_turn_semantic_plan
    if semantic_plan is None:
        return narration
    style_plan = semantic_plan.style_plan
    if not style_plan.key_segment:
        updated_style = style_plan.model_copy(
            update={
                "shell_anchor_hit": False,
                "summary": trim_text(
                    f"文风提交完成：非关键段，沿用reason={style_plan.reason_family}/signal={style_plan.signal_family}。",
                    220,
                ),
            }
        )
    else:
        shell_tokens = list(
            unique_preserve(
                [
                    *list(style_plan.shell_anchor_tokens),
                    *_required_shell_anchor_tokens(plan.story_shell_id),
                ]
            )
        )[:6]
        anchor_hit = any(token in narration for token in shell_tokens)
        forced_anchor: str | None = None
        if not anchor_hit and shell_tokens:
            forced_anchor = shell_tokens[0]
            narration = trim_text(f"{narration}{_forced_shell_anchor_tail(plan.story_shell_id, forced_anchor)}", 4000)
            anchor_hit = forced_anchor in narration
        style_summary = (
            "文风提交完成：关键段已命中reason->signal主句位与壳子锚点。"
            if anchor_hit
            else "文风提交完成：关键段未命中壳子锚点。"
        )
        if forced_anchor is not None and anchor_hit:
            style_summary = f"{style_summary}（补写锚点：{forced_anchor}）"
        updated_style = style_plan.model_copy(
            update={
                "shell_anchor_tokens": shell_tokens,
                "shell_anchor_hit": bool(anchor_hit),
                "summary": trim_text(style_summary, 220),
            }
        )
    updated_semantic = semantic_plan.model_copy(update={"style_plan": updated_style})
    updated_semantic.summary = trim_text(
        " ".join(
            [
                updated_semantic.question_plan.summary,
                updated_semantic.stake_plan.summary,
                updated_semantic.event_plan.summary,
                updated_semantic.payoff_plan.summary,
                updated_semantic.style_plan.summary,
            ]
        ),
        220,
    )
    state.last_turn_semantic_plan = updated_semantic
    return narration


def _finalize_last_turn_tags(
    *,
    latent_ops: list[str],
    consequence_tags: list[str],
    required_tags: list[str],
) -> list[str]:
    tags = unique_preserve([*latent_ops, *consequence_tags])
    for tag in reversed(required_tags):
        if tag in tags:
            tags.remove(tag)
        tags.insert(0, tag)
    return tags[:8]


def _utility_reason_family(
    *,
    intent_frame,
    delta: int,
    cause_tags: tuple[str, ...],
) -> str:
    if any(tag in cause_tags for tag in ("sacrifice_window", "forced_alignment", "blame_shift")):
        return "blame_shift"
    if any(tag in cause_tags for tag in ("debt_due", "kept_score", "owes_debt")):
        return "old_debt"
    if delta <= -2:
        if intent_frame.public_survival_mode in {"self_preserve", "cut_off", "claim_narrative"}:
            return "self_preserve"
        return "loss_position"
    if delta >= 2:
        return "opportunity_window"
    return "mixed"


def _compute_utility_delta_map(
    *,
    plan: CompiledPlayPlan,
    before_state: UrbanWorldState,
    state: UrbanWorldState,
) -> tuple[dict[str, int], list[NpcUtilityDeltaItem]]:
    members_by_id = {member.character_id: member for member in plan.cast}
    output: dict[str, int] = {}
    rows: list[NpcUtilityDeltaItem] = []
    for character_id in unique_preserve([*state.active_character_ids, *plan.route_target_ids]):
        member = members_by_id.get(character_id)
        before_rel = before_state.relationships.get(character_id)
        after_rel = state.relationships.get(character_id)
        if member is None or before_rel is None or after_rel is None:
            continue
        rel_shift = (
            (after_rel.trust - before_rel.trust) * 2
            + (after_rel.affection - before_rel.affection)
            - (after_rel.suspicion - before_rel.suspicion) * 2
            - (after_rel.tension - before_rel.tension)
        )
        global_shift = 0
        if member.strategic_intent.primary_stake in {"reputation", "narrative_control"}:
            global_shift += (state.public_image - before_state.public_image) * 2
        if member.strategic_intent.primary_stake in {"position", "lineage", "eligibility"}:
            global_shift += (state.route_lock - before_state.route_lock) * 2
        if member.strategic_intent.primary_stake in {"relationship", "normal_life"}:
            global_shift += (state.scene_heat - before_state.scene_heat) * -1
        latent_touch = 0
        for event in state.latent_events:
            if character_id == event.actor_character_id:
                latent_touch += 1
            if character_id in set(event.target_character_ids):
                latent_touch -= 1
            if character_id in set(event.stake_character_ids):
                latent_touch += 1
        delta = _clamp(rel_shift + global_shift + latent_touch, -12, 12)
        output[character_id] = delta
        cause_tags = tuple(state.last_turn_reaction_causes.get(character_id, []))
        family = _utility_reason_family(
            intent_frame=member.strategic_intent,
            delta=delta,
            cause_tags=cause_tags,
        )
        reason_text = {
            "loss_position": f"{member.display_name}这回合在失位。",
            "self_preserve": f"{member.display_name}这回合在优先自保。",
            "old_debt": f"{member.display_name}这回合在借旧账动手。",
            "blame_shift": f"{member.display_name}这回合在重排锅位，想把账甩给别人扛。",
            "opportunity_window": f"{member.display_name}这回合在等机会反扑。",
            "mixed": f"{member.display_name}这回合的效用变化较弱。",
        }[family]
        rows.append(
            NpcUtilityDeltaItem(
                character_id=character_id,
                display_name=member.display_name,
                utility_delta=delta,
                reason_family=family,  # type: ignore[arg-type]
                reason_text=reason_text,
            )
        )
    rows = sorted(rows, key=lambda item: (abs(item.utility_delta), item.utility_delta, item.character_id), reverse=True)
    return output, rows[:3]


def _cost_route_source(
    *,
    plan: CompiledPlayPlan,
    intent: UrbanTurnIntent,
    segment: CompiledSegment,
    state: UrbanWorldState,
) -> tuple[str, dict[str, int], dict[str, dict[str, int]], str]:
    route_kind = "immediate_cost"
    global_deltas: dict[str, int] = {}
    rel_deltas: dict[str, dict[str, int]] = {}
    if intent.scene_frame != "private":
        global_deltas["scene_heat"] = global_deltas.get("scene_heat", 0) + 1
    if intent.move_family in {"public_reveal", "betray", "accuse"}:
        global_deltas["public_image"] = global_deltas.get("public_image", 0) - 1
        global_deltas["route_lock"] = global_deltas.get("route_lock", 0) + 1
    elif intent.move_family in {"comfort", "flirt", "ally_with"}:
        global_deltas["scene_heat"] = global_deltas.get("scene_heat", 0) + 1
    if segment.segment_role in {"reveal", "terminal"}:
        global_deltas["scene_heat"] = global_deltas.get("scene_heat", 0) + 1
    if intent.target_id:
        payload: dict[str, int] = {}
        if intent.move_family in {"accuse", "betray"}:
            payload = {"trust": -1, "tension": 1}
        elif intent.move_family in {"comfort", "ally_with", "private_confession"}:
            payload = {"trust": 1, "suspicion": -1}
        elif intent.move_family in {"deflect", "probe_secret", "jealousy_trigger", "public_reveal"}:
            payload = {"suspicion": 1}
        if payload:
            rel_deltas[intent.target_id] = payload
    if intent.control_action == "redirect":
        route_kind = "transferred_cost"
    elif intent.control_action == "press":
        route_kind = "deferred_cost"
    elif intent.control_action == "detonate":
        route_kind = "immediate_cost"
    payoff_family = "mixed"
    target_member = next((member for member in plan.cast if member.character_id == intent.target_id), None)
    if target_member is not None:
        payoff_family = target_member.strategic_intent.regression_payoff
    return route_kind, global_deltas, rel_deltas, payoff_family


def _create_deferred_callback(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    segment: CompiledSegment,
    route: CostRouteRecord,
) -> CallbackQueueItem | None:
    deferred_kind = MOVE_DEFERRED_KIND.get(intent.move_family)
    if deferred_kind is None:
        return None
    if intent.control_action == "detonate":
        return None
    target_id = intent.control_target_id if intent.control_action == "redirect" and intent.control_target_id else intent.target_id
    target_member = next((member for member in plan.cast if member.character_id == target_id), None)
    payoff_kind = target_member.strategic_intent.regression_payoff if target_member is not None else "public_shame"
    linked_edge = pick_shell_edge(
        shell_id=plan.story_shell_id,
        latent_kind=deferred_kind,
        turn_index=state.turn_index,
        segment_role=segment.segment_role,
        graph_policy=plan.semantic_strategy_pack.shell_propagation_graph,
        priority_policy=plan.semantic_strategy_pack.propagation_priority_policy,
    )
    due_min = state.turn_index + 1
    due_max = state.turn_index + (2 if intent.control_action == "press" else 3)
    callback_id = f"cb_{state.turn_index}_{segment.segment_id}_{len(state.callback_queue)}"
    cue = trim_text(f"这步动作留下了后账：{_target_name(plan, target_id)}这边还没结清。", 220)
    detonation = trim_text(
        f"你之前这步留下的后账到期了，{_target_name(plan, target_id)}这边开始回咬，{route.payoff_family}成本被迫兑现。",
        220,
    )
    global_deltas: dict[str, int] = {"scene_heat": 1}
    if payoff_kind in {"public_shame", "secret_leak"}:
        global_deltas["public_image"] = -1
    if payoff_kind in {"status_loss", "social_isolation"}:
        global_deltas["route_lock"] = 1
    rel_deltas: dict[str, dict[str, int]] = {}
    if target_id:
        rel_deltas[target_id] = {"tension": 1, "suspicion": 1}
    return CallbackQueueItem(
        callback_id=callback_id,
        status="pending",
        source_turn_index=state.turn_index,
        source_segment_id=segment.segment_id,
        source_move_family=intent.move_family,
        linked_shell_edge_id=linked_edge.edge_id if linked_edge is not None else None,
        linked_scene_question_id=segment.segment_id,
        due_turn_min=due_min,
        due_turn_max=max(due_max, due_min),
        kind=deferred_kind,  # type: ignore[arg-type]
        payoff_kind=payoff_kind,
        stake_character_ids=[item for item in [target_id] if item][:3],
        target_character_ids=[item for item in [target_id] if item][:3],
        actor_character_id=target_id,
        cue_text=cue,
        detonation_text=detonation,
        global_deltas=global_deltas,
        relationship_deltas=rel_deltas,
    )


def _apply_cost_routing_matrix(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    segment: CompiledSegment,
) -> tuple[CostRouteRecord, CallbackQueueItem | None, bool]:
    route_kind, global_deltas, rel_deltas, payoff_family = _cost_route_source(
        plan=plan,
        intent=intent,
        segment=segment,
        state=state,
    )
    fallback_applied = False
    if not global_deltas and not rel_deltas:
        fallback_applied = True
        if intent.target_id:
            rel_deltas[intent.target_id] = {"tension": 1}
        else:
            global_deltas["scene_heat"] = 1
    transferred_target = intent.control_target_id if intent.control_action == "redirect" else None
    route = CostRouteRecord(
        route_id=f"cost_{state.turn_index}_{segment.segment_id}",
        route_kind=route_kind,  # type: ignore[arg-type]
        source_move_family=intent.move_family,
        source_control_action=intent.control_action,
        source_scene_frame=intent.scene_frame,
        source_segment_role=segment.segment_role,
        target_character_ids=[item for item in [intent.target_id] if item][:3],
        payoff_family=payoff_family,
        immediate_global_deltas=dict(global_deltas),
        immediate_relationship_deltas={key: dict(value) for key, value in rel_deltas.items()},
        deferred_kind=MOVE_DEFERRED_KIND.get(intent.move_family),  # type: ignore[arg-type]
        deferred_callback_id=None,
        transferred_to_character_id=transferred_target,
    )
    for key, delta in global_deltas.items():
        _apply_global_delta(state, key, int(delta))
    for relationship_id, deltas in rel_deltas.items():
        _apply_relationship_deltas(state, relationship_id, deltas)
    callback_item = _create_deferred_callback(
        plan=plan,
        state=state,
        intent=intent,
        segment=segment,
        route=route,
    )
    if callback_item is not None:
        route.deferred_callback_id = callback_item.callback_id
    return route, callback_item, fallback_applied


def _story_debug_summary(state: UrbanWorldState) -> str:
    parts: list[str] = []
    if state.last_turn_semantic_plan is not None and state.last_turn_semantic_plan.summary:
        parts.append(state.last_turn_semantic_plan.summary)
    if state.last_turn_scene_question_state is not None:
        parts.append(state.last_turn_scene_question_state.summary)
    if state.last_turn_cost_route is not None:
        parts.append(f"成本路由={state.last_turn_cost_route.route_kind}")
    if state.last_turn_propagation_edge is not None:
        parts.append(f"传播边={state.last_turn_propagation_edge.from_node}->{state.last_turn_propagation_edge.to_node}")
    if state.last_turn_callback_status is not None and state.last_turn_callback_status.triggered_callback_id:
        parts.append("回调已到期并触发。")
    elif state.last_turn_callback_status is not None and state.last_turn_callback_status.pending_count > 0:
        parts.append("仍有后账在队列里发酵。")
    if state.last_turn_causal_receipts:
        parts.append(trim_text(state.last_turn_causal_receipts[0], 120))
    top_shifts = (
        list(state.last_turn_semantic_plan.stake_plan.top_shifts)
        if state.last_turn_semantic_plan is not None
        else []
    )
    if top_shifts:
        top = top_shifts[0]
        parts.append(f"效用变化最大={top.display_name}:{top.utility_delta:+d}")
    return trim_text(" ".join(parts) or "本回合故事调度已完成。", 220)


def _find_unresolved_cost_by_id(
    state: UrbanWorldState,
    cost_id: str | None,
) -> UnresolvedCostRecord | None:
    if not cost_id:
        return None
    return next(
        (item for item in state.unresolved_costs if item.cost_id == cost_id and item.status == "pending"),
        None,
    )


def _cost_focus_kind_candidates(cost: UnresolvedCostRecord) -> tuple[str, ...]:
    if cost.scene_question_focus == "who_takes_blame":
        return ("public_wave", "npc_action")
    if cost.scene_question_focus == "who_gets_chased":
        return ("npc_action", "relationship_debt")
    return ("relationship_debt", "public_wave")


def _is_trigger_related_to_cost(
    *,
    cost: UnresolvedCostRecord,
    triggered_record,
) -> bool:
    if triggered_record is None or triggered_record.kind is None:
        return False
    if triggered_record.kind not in set(_cost_focus_kind_candidates(cost)):
        return False
    cost_ids = {
        *list(cost.owner_character_ids),
        *([cost.payer_character_id] if cost.payer_character_id else []),
        *([cost.beneficiary_character_id] if cost.beneficiary_character_id else []),
    }
    trigger_ids = {
        *list(triggered_record.stake_character_ids),
        *list(triggered_record.target_character_ids),
        *([triggered_record.actor_character_id] if triggered_record.actor_character_id else []),
    }
    return bool(cost_ids & trigger_ids)


def _cost_ladder_rule_for_cost(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    cost: UnresolvedCostRecord,
):
    policy = plan.semantic_strategy_pack.cost_escalation_ladder_policy_v8
    if not policy.enabled:
        return None
    direct = policy.by_segment_id.get(cost.source_segment_id)
    if direct is not None:
        return direct
    source_segment = next((item for item in plan.segments if item.segment_id == cost.source_segment_id), None)
    if source_segment is not None:
        by_role = next(
            (item for item in policy.by_segment_id.values() if item.segment_role == source_segment.segment_role),
            None,
        )
        if by_role is not None:
            return by_role
    return policy.by_segment_id.get(segment.segment_id)


def _compute_cost_ladder_stage(
    *,
    turn_index: int,
    cost: UnresolvedCostRecord,
    ladder_rule,
) -> int:  # noqa: ANN001
    if ladder_rule is None:
        base = int(cost.ladder_stage or 1)
        return _clamp(base, 1, 3)
    age = max(0, int(turn_index) - int(cost.source_turn_index))
    stage = 1
    if age >= int(ladder_rule.stage3_turn_offset):
        stage = 3
    elif age >= int(ladder_rule.stage2_turn_offset):
        stage = 2
    elif age >= int(ladder_rule.stage1_turn_offset):
        stage = 1
    retry_bonus = min(1, max(0, int(cost.ladder_retry_bias_steps) // 2))
    stage = min(3, stage + retry_bonus)
    if cost.ladder_defer_once_used and stage < 3 and age >= int(ladder_rule.stage2_turn_offset):
        stage = min(3, stage + 1)
    return _clamp(max(stage, int(cost.ladder_stage or 1)), 1, 3)


def _refresh_unresolved_cost_ladder(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    state: UrbanWorldState,
) -> None:
    updated: list[UnresolvedCostRecord] = []
    for item in state.unresolved_costs:
        record = item.model_copy(deep=True)
        if record.status == "pending":
            ladder_rule = _cost_ladder_rule_for_cost(plan=plan, segment=segment, cost=record)
            stage = _compute_cost_ladder_stage(
                turn_index=state.turn_index,
                cost=record,
                ladder_rule=ladder_rule,
            )
            summary = trim_text(
                f"代价挂账(stage-{stage})：{record.scene_question_focus}，最晚第{record.due_turn}回合回钩。",
                220,
            )
            record = record.model_copy(
                update={
                    "ladder_stage": stage,
                    "ladder_summary": summary,
                    "summary": summary,
                }
            )
        updated.append(record)
    state.unresolved_costs = sorted(
        updated,
        key=lambda item: (
            item.status != "pending",
            -int(item.ladder_stage or 1),
            int(item.due_turn),
            int(item.source_turn_index),
        ),
    )[:12]


def _upsert_unresolved_cost(
    *,
    state: UrbanWorldState,
    unresolved_cost: UnresolvedCostRecord,
) -> None:
    records = [item.model_copy(deep=True) for item in state.unresolved_costs]
    match_index = next(
        (
            index
            for index, item in enumerate(records)
            if (
                item.cost_id == unresolved_cost.cost_id
                or (
                    item.linked_callback_id
                    and unresolved_cost.linked_callback_id
                    and item.linked_callback_id == unresolved_cost.linked_callback_id
                )
                or (
                    item.source_turn_index == unresolved_cost.source_turn_index
                    and item.source_segment_id == unresolved_cost.source_segment_id
                    and item.route_kind == unresolved_cost.route_kind
                    and item.payer_character_id == unresolved_cost.payer_character_id
                )
            )
        ),
        None,
    )
    if match_index is None:
        records.append(unresolved_cost.model_copy(deep=True))
    else:
        retry_bias_steps = max(
            int(records[match_index].ladder_retry_bias_steps or 0),
            int(unresolved_cost.ladder_retry_bias_steps or 0),
        )
        records[match_index] = records[match_index].model_copy(
            update={
                "owner_character_ids": list(unresolved_cost.owner_character_ids[:3]),
                "payer_character_id": unresolved_cost.payer_character_id,
                "beneficiary_character_id": unresolved_cost.beneficiary_character_id,
                "linked_scene_question_id": unresolved_cost.linked_scene_question_id,
                "scene_question_focus": unresolved_cost.scene_question_focus,
                "due_turn": unresolved_cost.due_turn,
                "status": "pending",
                "linked_callback_id": unresolved_cost.linked_callback_id or records[match_index].linked_callback_id,
                "ladder_stage": max(1, int(unresolved_cost.ladder_stage or records[match_index].ladder_stage or 1)),
                "ladder_retry_bias_steps": _clamp(retry_bias_steps, 0, 6),
                "ladder_defer_once_used": bool(
                    unresolved_cost.ladder_defer_once_used or records[match_index].ladder_defer_once_used
                ),
                "ladder_summary": unresolved_cost.ladder_summary or records[match_index].ladder_summary,
                "summary": unresolved_cost.summary,
            }
        )
    records = sorted(
        records,
        key=lambda item: (
            item.status != "pending",
            -int(item.ladder_stage or 1),
            item.due_turn,
            item.source_turn_index,
        ),
    )
    state.unresolved_costs = [item for item in records if item.status != "expired"][:12]


def _reconcile_unresolved_costs(
    *,
    state: UrbanWorldState,
    scene_question_state: SceneQuestionStateRecord | None,
    callback_status: CallbackTurnStatusRecord | None,
    triggered_record,
) -> None:
    updated: list[UnresolvedCostRecord] = []
    for item in state.unresolved_costs:
        record = item.model_copy(deep=True)
        if record.status == "pending":
            if (
                callback_status is not None
                and callback_status.triggered_callback_id
                and record.linked_callback_id == callback_status.triggered_callback_id
            ):
                record.status = "returned"
                record.resolved_turn_index = state.turn_index
            elif _is_trigger_related_to_cost(cost=record, triggered_record=triggered_record):
                record.status = "returned"
                record.resolved_turn_index = state.turn_index
            elif state.turn_index > record.due_turn + 3:
                record.status = "expired"
                record.resolved_turn_index = state.turn_index
        if (
            record.status == "returned"
            and scene_question_state is not None
            and record.linked_scene_question_id == scene_question_state.segment_id
            and scene_question_state.status == "resolved"
        ):
            record.status = "resolved"
            record.resolved_turn_index = state.turn_index
        if record.status != "expired":
            updated.append(record)
    state.unresolved_costs = sorted(
        updated,
        key=lambda item: (
            item.status != "pending",
            -int(item.ladder_stage or 1),
            item.due_turn,
            item.source_turn_index,
        ),
    )[:12]


def _scene_frame_for_segment(segment: CompiledSegment) -> RelationshipSceneFrame:
    if segment.segment_role in {"reveal", "terminal"}:
        return "public"
    if segment.segment_role == "pressure":
        return "semi_public"
    return "private"


def _current_segment(plan: CompiledPlayPlan, state: UrbanWorldState) -> CompiledSegment:
    return plan.segments[min(state.segment_index, len(plan.segments) - 1)]


def _resolved_segment(plan: CompiledPlayPlan, state: UrbanWorldState) -> CompiledSegment:
    return resolve_segment_with_delta(plan=plan, state=state)


def _route_focus_ids(plan: CompiledPlayPlan) -> set[str]:
    return set(plan.route_target_ids)


def _target_name(plan: CompiledPlayPlan, target_id: str | None) -> str:
    return next((member.display_name for member in plan.cast if member.character_id == target_id), "对方")


def _fallback_lane_id(move_family: RelationshipMoveFamily) -> SuggestionLaneId:
    for lane_id, move_families in LANE_MOVE_FAMILIES.items():
        if move_family in move_families:
            return lane_id
    return "side"


def _normalize_user_text(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _text_terms(value: str) -> set[str]:
    normalized = _normalize_user_text(value)
    latin_terms = set(re.findall(r"[a-z0-9_]{2,}", normalized))
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    cjk_bigrams = {
        f"{cjk_chars[index]}{cjk_chars[index + 1]}"
        for index in range(len(cjk_chars) - 1)
    }
    return latin_terms | cjk_bigrams


def _suggestion_match_score(
    plan: CompiledPlayPlan,
    suggestion: UrbanSuggestedAction,
    input_text: str,
    input_terms: set[str],
) -> int:
    score = 0
    normalized_input = _normalize_user_text(input_text)
    target_name = _target_name(plan, suggestion.target_id)
    if target_name and _normalize_user_text(target_name) in normalized_input:
        score += 3
    move_keywords = MOVE_KEYWORDS.get(suggestion.move_family, ())
    if any(keyword.casefold() in normalized_input for keyword in move_keywords):
        score += 3
    scene_keywords = PUBLIC_FRAME_KEYWORDS if suggestion.scene_frame == "public" else SEMI_PUBLIC_FRAME_KEYWORDS
    if any(keyword.casefold() in normalized_input for keyword in scene_keywords):
        score += 1
    suggestion_terms = _text_terms(f"{suggestion.label} {suggestion.prompt}")
    overlap = input_terms & suggestion_terms
    score += min(len(overlap), 4)
    return score


def _nearest_legal_suggestion(
    plan: CompiledPlayPlan,
    suggestions: list[UrbanSuggestedAction],
    input_text: str,
) -> UrbanSuggestedAction | None:
    if not suggestions:
        return None
    input_terms = _text_terms(input_text)
    ranked = sorted(
        suggestions,
        key=lambda item: (
            _suggestion_match_score(plan, item, input_text, input_terms),
            item.lane_id,
            item.suggestion_id,
        ),
        reverse=True,
    )
    return ranked[0]


def _soft_repair_note(plan: CompiledPlayPlan, suggestion: UrbanSuggestedAction) -> str:
    target_name = _target_name(plan, suggestion.target_id)
    lane_hint = {
        "relationship": "把目标和你愿意付的关系代价说清楚",
        "side": "把你要站谁、准备放弃谁说清楚",
        "burst": "把你要引爆的点和承受成本说清楚",
    }.get(suggestion.lane_id, "把目标和代价再说得具体一点")
    return trim_text(
        f"你这句动作超出当前场景可执行范围，系统先按「{suggestion.label}」落到{target_name}身上推进一拍；下一句如果{lane_hint}，局势会更按你的节奏走。",
        220,
    )


def _is_out_of_scope_input(value: str) -> bool:
    normalized = _normalize_user_text(value)
    return any(keyword.casefold() in normalized for keyword in OUT_OF_SCOPE_INPUT_KEYWORDS)


def _is_low_information_input(value: str) -> bool:
    normalized = _normalize_user_text(value)
    if not normalized:
        return True
    if normalized in LOW_INFORMATION_INPUT_EXACT:
        return True
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    if len(cjk_chars) <= 1 and not re.search(r"[a-z0-9]{2,}", normalized):
        return True
    return False


def _build_default_suggestion_lanes(segment: CompiledSegment, plan: CompiledPlayPlan) -> list[SegmentSuggestionLane]:
    route_target_ids = [target_id for target_id in segment.focus_target_ids if target_id in _route_focus_ids(plan)] or [
        target_id for target_id in plan.route_target_ids if target_id in set(segment.focus_target_ids + segment.rival_target_ids)
    ]
    conflict_target_ids = unique_preserve(segment.focus_target_ids + segment.rival_target_ids)[:3]
    secret_target_ids = unique_preserve(segment.rival_target_ids + segment.focus_target_ids)[:3]

    def _candidate_moves(preferred: tuple[RelationshipMoveFamily, ...]) -> list[RelationshipMoveFamily]:
        matched = [move_family for move_family in preferred if move_family in segment.allowed_move_families]
        if matched:
            return matched[:4]
        return list(segment.allowed_move_families[:2])

    return [
        SegmentSuggestionLane(
            lane_id="relationship",
            label="走关系线",
            objective=trim_text(f"优先把关系拉近，让目标角色更愿意在{plan.social_arena}里接住你。", 220),
            candidate_move_families=_candidate_moves(LANE_MOVE_FAMILIES["relationship"]),
            target_priority_ids=(route_target_ids or conflict_target_ids)[:3],
            scene_frame_hint="private",
        ),
        SegmentSuggestionLane(
            lane_id="side",
            label="先选阵营",
            objective=trim_text(f"优先明确站边，把{plan.social_arena}里的立场关系先钉死。", 220),
            candidate_move_families=_candidate_moves(LANE_MOVE_FAMILIES["side"]),
            target_priority_ids=conflict_target_ids[:3],
            scene_frame_hint=_scene_frame_for_segment(segment),
        ),
        SegmentSuggestionLane(
            lane_id="burst",
            label="引爆场面",
            objective=trim_text(f"优先撬动秘密和公开压力，把{plan.bomb_moment}往前推。", 220),
            candidate_move_families=_candidate_moves(LANE_MOVE_FAMILIES["burst"]),
            target_priority_ids=(secret_target_ids or conflict_target_ids)[:3],
            scene_frame_hint="public" if segment.segment_role in {"reveal", "terminal"} else "semi_public",
        ),
    ]


def _segment_suggestion_lanes(segment: CompiledSegment, plan: CompiledPlayPlan) -> list[SegmentSuggestionLane]:
    return segment.suggestion_lanes or _build_default_suggestion_lanes(segment, plan)


def _resolve_lane_target_id(plan: CompiledPlayPlan, state: UrbanWorldState, lane: SegmentSuggestionLane) -> str | None:
    current_route_target_id = state.current_route_target_id
    if current_route_target_id and current_route_target_id in lane.target_priority_ids:
        return current_route_target_id
    active_ids = set(state.active_character_ids)
    for target_id in lane.target_priority_ids:
        if target_id in active_ids:
            return target_id
    return lane.target_priority_ids[0] if lane.target_priority_ids else (state.active_character_ids[0] if state.active_character_ids else None)


def _resolve_lane_move_family(segment: CompiledSegment, lane: SegmentSuggestionLane) -> RelationshipMoveFamily:
    for move_family in lane.candidate_move_families:
        if move_family in segment.allowed_move_families:
            return move_family
    return segment.move_priorities[0]


def _lane_prompt(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    segment: CompiledSegment,
    lane: SegmentSuggestionLane,
    target_name: str,
    move_family: RelationshipMoveFamily,
) -> str:
    if lane.lane_id == "relationship":
        return trim_text(f"现在先护住{target_name}，让她欠你这一手，也让场上所有人看清你更偏向谁。代价是你会先把自己和这条关系绑得更深，另一边马上就会记账。", 220)
    if lane.lane_id == "side":
        return trim_text(f"现在逼{target_name}把立场摆到台面上，让场子当场分阵营。代价是另一边会立刻把你记成已经认边，几乎不会再给你回头路。", 220)
    if segment.segment_role in {"reveal", "terminal"} or state.secret_exposure >= 2 or state.scene_heat >= 4:
        return trim_text(f"现在就对{target_name}翻牌，把最不该见光的东西直接摔到所有人眼前。代价不是丢脸而已，是退路、体面和名额会一起烧掉。", 220)
    if move_family == "accuse":
        return trim_text(f"现在就当场逼问{target_name}，把最疼的口子直接撕开。代价是这一下会把所有人的敌意一起抬起来。", 220)
    return trim_text(f"从{target_name}身上先硬撕出一个缺口，让秘密和站边开始见血。代价是你自己也会跟着一起失去退路。", 220)


def _lane_target_score(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    *,
    target_id: str,
    lane_id: SuggestionLaneId,
    reserved_targets: set[str],
) -> tuple[int, int, str]:
    relationship = state.relationships.get(target_id)
    mind = state.npc_mind_states.get(target_id)
    is_route_target = target_id in _route_focus_ids(plan)
    active_bonus = 1 if target_id in set(state.active_character_ids) else 0
    reserved_penalty = -4 if target_id in reserved_targets else 0
    order_bias = -list(unique_preserve(state.active_character_ids + plan.route_target_ids + [target_id])).index(target_id)
    if lane_id == "relationship":
        trust = relationship.trust if relationship is not None else 0
        affection = relationship.affection if relationship is not None else 0
        protectiveness = mind.protectiveness if mind is not None else 0
        score = (5 if is_route_target else 0) + trust + affection + protectiveness + active_bonus + reserved_penalty
        return score, trust + affection, order_bias
    if lane_id == "side":
        suspicion = relationship.suspicion if relationship is not None else 0
        tension = relationship.tension if relationship is not None else 0
        control = mind.control_need if mind is not None else 0
        betrayal = mind.betrayal_readiness if mind is not None else 0
        score = (3 if not is_route_target else 1) + suspicion + tension + control + betrayal + active_bonus + reserved_penalty
        return score, suspicion + tension, order_bias
    humiliation = mind.humiliation_risk if mind is not None else 0
    pressure = mind.pressure_load if mind is not None else 0
    jealousy = mind.jealousy if mind is not None else 0
    score = humiliation + pressure + jealousy + active_bonus + reserved_penalty + (2 if not is_route_target else 0)
    return score, humiliation + pressure, order_bias


def _choose_lane_target_id(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    lane: SegmentSuggestionLane,
    *,
    reserved_targets: set[str],
) -> str | None:
    candidates = unique_preserve(list(lane.target_priority_ids) + list(state.active_character_ids))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda target_id: _lane_target_score(
            plan,
            state,
            target_id=target_id,
            lane_id=lane.lane_id,
            reserved_targets=reserved_targets,
        ),
    )


def _lane_move_score(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    *,
    lane_id: SuggestionLaneId,
    move_family: RelationshipMoveFamily,
    target_id: str | None,
    reserved_moves: set[RelationshipMoveFamily],
) -> tuple[int, int, int, str]:
    relationship = state.relationships.get(target_id or "")
    mind = state.npc_mind_states.get(target_id or "")
    reserved_penalty = -2 if move_family in reserved_moves else 0
    public_bonus = 1 if state.scene_frame == "public" else 0
    if lane_id == "relationship":
        score = reserved_penalty
        if move_family == "private_confession":
            score += 4 + (relationship.trust if relationship is not None else 0)
        elif move_family == "comfort":
            score += 3 + (relationship.suspicion if relationship is not None else 0)
        elif move_family == "flirt":
            score += 2 + (relationship.affection if relationship is not None else 0)
        elif move_family == "ally_with":
            score += 2 + state.route_lock
        return score, relationship.trust if relationship is not None else 0, public_bonus, move_family
    if lane_id == "side":
        score = reserved_penalty
        if move_family == "ally_with":
            score += 4 + max(0, 3 - state.route_lock)
        elif move_family == "accuse":
            score += 3 + (relationship.suspicion if relationship is not None else 0) + (mind.control_need if mind is not None else 0)
        elif move_family == "comfort":
            score += 2 + (mind.protectiveness if mind is not None else 0)
        elif move_family == "deflect":
            score += 2 + state.scene_heat + public_bonus
        return score, relationship.tension if relationship is not None else 0, public_bonus, move_family
    score = reserved_penalty
    if move_family == "public_reveal":
        score += 4 + state.secret_exposure + public_bonus + (2 if state.segment_index >= len(plan.segments) - 2 else 0)
    elif move_family == "probe_secret":
        score += 3 + max(0, 2 - state.secret_exposure) + (mind.pressure_load if mind is not None else 0)
    elif move_family == "betray":
        score += 3 + (mind.betrayal_readiness if mind is not None else 0)
    elif move_family == "accuse":
        score += 2 + (mind.humiliation_risk if mind is not None else 0)
    elif move_family == "jealousy_trigger":
        score += 2 + (mind.jealousy if mind is not None else 0)
    return score, state.secret_exposure, public_bonus, move_family


def _choose_lane_move_family(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    lane: SegmentSuggestionLane,
    *,
    segment: CompiledSegment,
    target_id: str | None,
    reserved_moves: set[RelationshipMoveFamily],
) -> RelationshipMoveFamily:
    candidates = [move_family for move_family in lane.candidate_move_families if move_family in LANE_MOVE_FAMILIES[lane.lane_id]]
    if not candidates:
        candidates = list(lane.candidate_move_families)
    if lane.lane_id == "burst":
        directed = EventDirector.preferred_burst_move(
            plan=plan,
            segment=segment,
            state=state,
            target_id=target_id,
            candidates=candidates,
        )
        if directed is not None and directed in candidates:
            return directed
    return max(
        candidates,
        key=lambda move_family: _lane_move_score(
            plan,
            state,
            lane_id=lane.lane_id,
            move_family=move_family,
            target_id=target_id,
            reserved_moves=reserved_moves,
        ),
    )


def _lane_label(lane: SegmentSuggestionLane, move_family: RelationshipMoveFamily, target_name: str) -> str:
    if lane.lane_id == "relationship":
        return {
            "private_confession": "把心口话掀开",
            "comfort": f"先护住{target_name}",
            "flirt": f"笑着靠近{target_name}",
            "ally_with": f"跟{target_name}绑死",
        }.get(move_family, "走关系线")
    if lane.lane_id == "side":
        return {
            "ally_with": "现在认边",
            "accuse": f"逼{target_name}认栽",
            "deflect": f"替{target_name}压场",
            "comfort": f"护{target_name}站边",
        }.get(move_family, "先选阵营")
    return {
        "public_reveal": "把证据摔桌",
        "probe_secret": "先撕开口子",
        "betray": f"拿{target_name}挡刀",
        "accuse": "当场点名",
        "jealousy_trigger": "故意拱火",
    }.get(move_family, "引爆场面")


def _render_opening_from_plan(plan: CompiledPlayPlan, segment: CompiledSegment) -> str:
    if plan.story_shell_id == "entertainment_scandal":
        opening = (
            f"{plan.social_arena}的流程还在走，但镜头和外面风向已经盯住了{segment.scene_goal[:40]}。"
            f"你每一句都可能被接成版本，代价是{plan.cost_of_truth}。"
        )
    elif plan.story_shell_id == "campus_romance":
        opening = (
            f"{plan.social_arena}还没散，台下和熟人圈已经在交换眼色。"
            f"你现在的站位会直接碰到{plan.cost_of_truth}，而{plan.route_promise}已经被所有人盯着。"
        )
    elif plan.story_shell_id == "wealth_families":
        opening = (
            f"{plan.social_arena}看着体面，顺位和关系账却在桌下同时发酵。"
            f"你每一步都在靠近{plan.bomb_moment}，代价会落到{plan.cost_of_truth}。"
        )
    elif plan.story_shell_id == "office_power":
        opening = (
            f"{plan.social_arena}表面稳定，站边和背锅名单却已经开始重排。"
            f"你这局真正要赌的是{plan.route_promise}，以及它会带来的{plan.cost_of_truth}。"
        )
    else:
        opening = (
            f"{plan.social_arena}已经进入高压段，关系、风向和秘密都在同一拍上累积。"
            f"你现在的选择会决定谁先吃到{plan.cost_of_truth}。"
        )
    return _finalize_narration_style(trim_text(opening, 4000))


def build_initial_world_state(plan: CompiledPlayPlan, *, session_id: str | None = None) -> UrbanWorldState:
    first_segment = plan.segments[0]
    initial_delta_pack = plan.initial_beat_delta_pack.model_copy(deep=True)
    relationships = {
        member.character_id: UrbanRelationshipTargetState(
            character_id=member.character_id,
            name=member.display_name,
            is_route_focus=member.is_route_target,
        )
        for member in plan.cast
    }
    npc_mind_states = {
        member.character_id: NpcMindState(
            stance="testing" if member.is_route_target else "guarded",
            current_goal=member.drama_profile.status_need,
            control_need=3 if "控制" in member.danger_hook or "掌权" in member.shareable_labels else 2,
            trust=0,
            affection=0,
            tension=1,
            suspicion=1,
            dependency=0,
        )
        for member in plan.cast
    }
    active_ids = unique_preserve((first_segment.focus_target_ids + first_segment.rival_target_ids)[:3])[:3]
    route_scores = {target_id: 0 for target_id in plan.route_target_ids}
    state = UrbanWorldState(
        session_id=session_id or f"urban_session_{uuid4().hex[:12]}",
        story_id=plan.story_id,
        relationships=relationships,
        route_scores_by_target=route_scores,
        active_beat_delta_pack=initial_delta_pack,
        pending_beat_delta_pack=None,
        delta_pack_snapshot_id=initial_delta_pack.snapshot_id,
        delta_pack_job_status="idle",
        delta_pack_journal=[],
        segment_id=first_segment.segment_id,
        segment_enter_turn_index=0,
        scene_frame=_scene_frame_for_segment(first_segment),
        venue_id=first_segment.venue_id,
        active_character_ids=active_ids,
        npc_mind_states=npc_mind_states,
        witness_pressure=2 if _scene_frame_for_segment(first_segment) != "private" else 1,
        lane_counts={lane_id: 0 for lane_id in LANE_MOVE_FAMILIES},
        lane_counts_by_target={},
        scene_question_states=_build_initial_scene_questions(plan),
        narration=_render_opening_from_plan(plan, first_segment),
    )
    from rpg_backend.play_v2.hook_engine import build_initial_hook_states

    state.hook_states = build_initial_hook_states(plan)
    story_actions = build_suggested_actions(plan, state)
    state.story_actions = story_actions
    state.suggested_actions = story_actions
    state.control_actions = build_control_actions(plan, state)
    return state


def build_suggested_actions(plan: CompiledPlayPlan, state: UrbanWorldState) -> list[UrbanSuggestedAction]:
    segment = _resolved_segment(plan, state)
    suggestions: list[UrbanSuggestedAction] = []
    reserved_targets: set[str] = set()
    reserved_moves: set[RelationshipMoveFamily] = set()
    for lane in _segment_suggestion_lanes(segment, plan):
        target_id = _choose_lane_target_id(plan, state, lane, reserved_targets=reserved_targets)
        move_family = _choose_lane_move_family(
            plan,
            state,
            lane,
            segment=segment,
            target_id=target_id,
            reserved_moves=reserved_moves,
        )
        target_name = _target_name(plan, target_id)
        scene_frame: RelationshipSceneFrame = "public" if move_family == "public_reveal" else lane.scene_frame_hint
        suggestions.append(
            UrbanSuggestedAction(
                suggestion_id=f"{segment.segment_id}_{lane.lane_id}",
                lane_id=lane.lane_id,
                label=_lane_label(lane, move_family, target_name),
                prompt=_lane_prompt(plan, state, segment, lane, target_name, move_family),
                move_family=move_family,
                target_id=target_id,
                scene_frame=scene_frame,
            )
        )
        if target_id is not None:
            reserved_targets.add(target_id)
        reserved_moves.add(move_family)
    if suggestions:
        return suggestions[:3]
    return []


def _latent_kind_label(kind: str) -> str:
    return {
        "relationship_debt": "关系旧账",
        "public_wave": "公开风向",
        "secret_pressure": "秘密压力",
        "npc_action": "人物动作",
    }.get(kind, "潜在风险")


def _ranked_latent_kinds(state: UrbanWorldState) -> list[str]:
    weighted = [
        ("relationship_debt", state.relationship_debt_pressure),
        ("public_wave", state.public_wave_pressure),
        ("secret_pressure", state.secret_pressure),
        ("npc_action", state.npc_action_pressure),
    ]
    return [kind for kind, _ in sorted(weighted, key=lambda item: (item[1], item[0]), reverse=True)]


def build_control_actions(plan: CompiledPlayPlan, state: UrbanWorldState) -> list[UrbanControlAction]:
    ranked_kinds = _ranked_latent_kinds(state)
    press_kind = ranked_kinds[0] if ranked_kinds else "relationship_debt"
    redirect_kind = ranked_kinds[1] if len(ranked_kinds) > 1 else ranked_kinds[0] if ranked_kinds else "public_wave"
    detonate_kind = ranked_kinds[2] if len(ranked_kinds) > 2 else ranked_kinds[0] if ranked_kinds else "secret_pressure"
    target_character = state.current_route_target_id or (state.active_character_ids[0] if state.active_character_ids else None)
    return [
        UrbanControlAction(
            action_id=f"{state.segment_id}_control_press",
            action_type="press",
            target_mode="kind",
            target_kind=press_kind,  # type: ignore[arg-type]
            target_id=None,
            label=f"先压住{_latent_kind_label(press_kind)}",
            prompt=f"先把{_latent_kind_label(press_kind)}往下压一拍，换短暂可控窗口。",
        ),
        UrbanControlAction(
            action_id=f"{state.segment_id}_control_redirect",
            action_type="redirect",
            target_mode="character",
            target_kind=redirect_kind,  # type: ignore[arg-type]
            target_id=target_character,
            label=f"转移{_latent_kind_label(redirect_kind)}",
            prompt=f"把{_latent_kind_label(redirect_kind)}先转移到更可承受的对象，代价是后续关系账会变重。",
        ),
        UrbanControlAction(
            action_id=f"{state.segment_id}_control_detonate",
            action_type="detonate",
            target_mode="kind",
            target_kind=detonate_kind,  # type: ignore[arg-type]
            target_id=None,
            label=f"提前拆{_latent_kind_label(detonate_kind)}",
            prompt=f"现在主动提前引爆{_latent_kind_label(detonate_kind)}，换更少不确定性但更高当回合成本。",
        ),
    ]


@dataclass(frozen=True)
class _IntentCandidate:
    move_family: RelationshipMoveFamily
    target_id: str | None
    scene_frame: RelationshipSceneFrame
    lane_id: SuggestionLaneId | None
    mapped_suggestion_id: str | None
    intent_confidence: float
    compile_source: str
    deviation_type: str = "none"
    deviation_note: str | None = None
    alternatives: tuple[str, ...] = ()
    control_action: LatentEventControl = "none"
    control_target_id: str | None = None
    control_target_mode: str | None = None
    tradeoff_markers: tuple[str, ...] = ()
    semantic_effects: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class _ClauseIntent:
    clause_index: int
    clause_text: str
    move_family: RelationshipMoveFamily | None
    target_id: str | None
    move_hit_count: int
    target_hit_count: int
    control_action: LatentEventControl = "none"


@dataclass(frozen=True)
class _NpcMicroSimChoice:
    character_id: str
    action_family: str
    reason_family: str
    signal_family: str
    cost_family: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class _NpcMicroSimResult:
    source: Literal["llm", "heuristic"]
    shortlist: tuple[str, ...]
    recommended_actor_id: str | None
    choices: tuple[_NpcMicroSimChoice, ...]
    summary: str


def _confidence_bucket(score: float) -> TurnConfidence:
    if score >= 0.78:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _safe_confidence(score: float) -> float:
    return max(0.0, min(1.0, float(score)))


def _usage_token_count(usage: dict[str, Any] | None, key: str) -> int:
    if not isinstance(usage, dict):
        return 0
    value = usage.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return 0


def _live_llm_calls_enabled(*, settings, flag_attr: str) -> bool:
    if not bool(getattr(settings, flag_attr, False)):
        return False
    if os.getenv("PYTEST_CURRENT_TEST"):
        allow_in_tests = str(os.getenv("APP_PLAY_V2_ALLOW_LIVE_LLM_IN_TESTS", "")).strip().lower()
        return allow_in_tests in {"1", "true", "yes", "on"}
    return True


def _slot_alternatives(
    suggestions: list[UrbanSuggestedAction],
    *,
    preferred_suggestion_id: str | None = None,
) -> tuple[str, ...]:
    labels: list[str] = []
    if preferred_suggestion_id:
        preferred = next((item for item in suggestions if item.suggestion_id == preferred_suggestion_id), None)
        if preferred is not None:
            labels.append(preferred.label)
    for item in suggestions:
        if item.label in labels:
            continue
        labels.append(item.label)
    return tuple(labels[:3])


def _normalize_deviation_type(value: str | None) -> str:
    token = str(value or "").strip()
    if token in {"scope_shift", "target_shift", "move_downgrade", "none"}:
        return token
    return "none"


def _normalize_optional_control_action(value: Any) -> LatentEventControl:
    token = str(value or "").strip()
    if token in {"press", "redirect", "detonate"}:
        return token  # type: ignore[return-value]
    return "none"


def _normalize_optional_control_target_mode(value: Any) -> str | None:
    token = str(value or "").strip()
    if token in {"kind", "event", "character"}:
        return token
    return None


def _normalize_tradeoff_markers(value: Any) -> tuple[str, ...]:
    raw_items: list[str] = []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = [str(item) for item in value if isinstance(item, str) and str(item).strip()]
    return tuple(
        trim_text(item, 72)
        for item in unique_preserve(raw_items)
        if trim_text(item, 72)
    )[:5]


def _split_input_clauses(input_text: str) -> list[str]:
    normalized = trim_text(normalize_whitespace(input_text), 500)
    if not normalized:
        return []
    parts = re.split(r"(?:然后|再|接着|并且|同时|之后|;|；|。|！|!|？|\?|,|，)", normalized)
    output = [trim_text(part, 140) for part in parts if trim_text(part, 140)]
    return output[:4]


def _extract_clause_intents(plan: CompiledPlayPlan, input_text: str) -> list[_ClauseIntent]:
    clauses = _split_input_clauses(input_text)
    if not clauses:
        return []
    cast_targets = [(member.character_id, _normalize_user_text(member.display_name)) for member in plan.cast]
    rows: list[_ClauseIntent] = []
    for clause_index, clause in enumerate(clauses):
        lowered = _normalize_user_text(clause)
        move_counts = {
            move_family: sum(1 for keyword in keywords if keyword and keyword.casefold() in lowered)
            for move_family, keywords in MOVE_KEYWORDS.items()
        }
        ranked_moves = sorted(move_counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
        best_move = ranked_moves[0][0] if ranked_moves and ranked_moves[0][1] > 0 else None
        best_hits = ranked_moves[0][1] if ranked_moves else 0
        target_id = None
        target_hits = 0
        for character_id, name_token in cast_targets:
            if not name_token:
                continue
            if name_token in lowered:
                target_id = character_id
                target_hits += 1
                break
        rows.append(
            _ClauseIntent(
                clause_index=clause_index,
                clause_text=clause,
                move_family=best_move,
                target_id=target_id,
                control_action=_free_text_control_action(clause),
                move_hit_count=int(best_hits),
                target_hit_count=int(target_hits),
            )
        )
    return rows


def _secondary_alternatives_from_clauses(
    *,
    suggestions: list[UrbanSuggestedAction],
    clause_intents: list[_ClauseIntent],
    primary_move: RelationshipMoveFamily,
) -> tuple[str, ...]:
    labels: list[str] = []
    for clause_intent in clause_intents:
        move = clause_intent.move_family
        if move is None or move == primary_move:
            continue
        matched = next((item for item in suggestions if item.move_family == move), None)
        if matched is None:
            continue
        labels.append(matched.label)
    return tuple(unique_preserve(labels)[:2])


def _control_alternatives_from_clauses(
    *,
    control_actions: list[UrbanControlAction],
    clause_intents: list[_ClauseIntent],
) -> tuple[str, ...]:
    labels: list[str] = []
    for clause_intent in clause_intents:
        if clause_intent.control_action in {"none", "press", "redirect", "detonate"}:
            matched = next(
                (item for item in control_actions if item.action_type == clause_intent.control_action),
                None,
            )
            if matched is None:
                continue
            labels.append(matched.label)
    return tuple(unique_preserve(labels)[:2])


def _primary_clause_score(clause: _ClauseIntent, *, allowed_moves: set[RelationshipMoveFamily]) -> int:
    move_bonus = clause.move_hit_count * 4
    target_bonus = clause.target_hit_count * 3
    order_bonus = max(0, 2 - clause.clause_index)
    legal_bonus = 2 if clause.move_family in allowed_moves else 0
    control_bonus = 1 if clause.control_action != "none" else 0
    return move_bonus + target_bonus + order_bonus + legal_bonus + control_bonus


def _infer_control_target_from_text(
    plan: CompiledPlayPlan,
    input_text: str,
    clause_intents: list[_ClauseIntent],
) -> str | None:
    mentioned_ids = [clause.target_id for clause in clause_intents if clause.target_id]
    if len(set(mentioned_ids)) == 1 and mentioned_ids:
        return mentioned_ids[0]
    normalized = _normalize_user_text(input_text)
    if not normalized:
        return None
    directional = ("转给", "甩给", "推给", "丢给", "给", "向")
    for member in plan.cast:
        name_token = _normalize_user_text(member.display_name)
        if not name_token:
            continue
        if name_token in normalized and any(f"{prefix}{name_token}" in normalized for prefix in directional):
            return member.character_id
    for member in plan.cast:
        name_token = _normalize_user_text(member.display_name)
        if name_token and name_token in normalized:
            return member.character_id
    return None


def _free_text_control_action(input_text: str) -> LatentEventControl:
    normalized = _normalize_user_text(input_text)
    if not normalized:
        return "none"
    scores: dict[str, int] = {}
    for action, keywords in CONTROL_ACTION_KEYWORDS.items():
        if action == "none":
            continue
        score = 0
        for keyword in keywords:
            token = keyword.casefold()
            for match in re.finditer(re.escape(token), normalized):
                prefix = normalized[max(0, match.start() - 3) : match.start()]
                if any(neg in prefix for neg in ("别", "不要", "不许", "先不")):
                    continue
                score += 1
        scores[action] = score
    ranked = sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return "none"
    return ranked[0][0]  # type: ignore[return-value]


def _micro_sim_signal_family(shell_id: str) -> str:
    if shell_id == "entertainment_scandal":
        return "public_wave"
    if shell_id == "campus_romance":
        return "peer_spread"
    if shell_id == "office_power":
        return "institution_pressure"
    if shell_id == "wealth_families":
        return "lineage_pressure"
    return "mixed"


def _micro_sim_action_family(public_survival_mode: str) -> str:
    return {
        "self_preserve": "self_clarify",
        "cut_off": "cut_side",
        "hold_face": "hold_position",
        "claim_narrative": "claim_version",
        "align_early": "align_side",
    }.get(public_survival_mode, "test_water")


def _micro_sim_reason_family(intent_frame, intent: UrbanTurnIntent) -> str:
    if intent.target_id in set(intent_frame.opportunism_target_ids):
        return "opportunity_window"
    if intent.target_id in set(intent_frame.protect_target_ids):
        return "self_preserve"
    if intent.target_id in set(intent_frame.sacrifice_target_ids):
        return "blame_shift"
    if intent.move_family in {"accuse", "betray"} and intent.control_action in {"redirect", "none"}:
        return "blame_shift"
    return {
        "public_humiliation": "loss_position",
        "seat_shift": "loss_position",
        "version_loss": "self_preserve",
        "peer_rejection": "self_preserve",
        "route_rejection": "opportunity_window",
        "debt_reopened": "old_debt",
    }.get(intent_frame.loss_trigger, "mixed")


def _micro_sim_candidate_score(
    *,
    intent: UrbanTurnIntent,
    character_id: str,
    intent_frame,
    mind: NpcMindState | None,
    state: UrbanWorldState,
    segment_role: str,
) -> int:
    score = 0
    if character_id == intent.target_id:
        score -= 4
    if character_id in set(state.active_character_ids):
        score += 2
    if intent.target_id in set(intent_frame.opportunism_target_ids):
        score += 4
    if intent.target_id in set(intent_frame.protect_target_ids):
        score += 2
    if intent.target_id in set(intent_frame.sacrifice_target_ids):
        score += 2
    if intent.scene_frame != "private" and intent_frame.loss_trigger in {"public_humiliation", "version_loss", "peer_rejection"}:
        score += 2
    if intent.move_family in {"public_reveal", "accuse", "betray", "deflect"} and intent_frame.public_survival_mode in {"self_preserve", "cut_off", "claim_narrative"}:
        score += 2
    if segment_role in {"reveal", "terminal"}:
        score += 1
    previous_utility = int(state.last_turn_utility_delta_by_character.get(character_id, 0))
    score += min(3, abs(previous_utility))
    if mind is not None:
        score += min(2, int(mind.control_need) // 2)
        score += min(2, int(mind.betrayal_readiness) // 2)
        score += min(2, int(mind.jealousy) // 2)
    return score


def _heuristic_micro_sim_result(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    shortlist: tuple[str, ...],
    segment_role: str,
) -> _NpcMicroSimResult:
    members_by_id = {member.character_id: member for member in plan.cast}
    signal_family = _micro_sim_signal_family(plan.story_shell_id)
    ranked_choices: list[_NpcMicroSimChoice] = []
    for idx, character_id in enumerate(shortlist):
        member = members_by_id.get(character_id)
        if member is None:
            continue
        intent_frame = member.strategic_intent
        reason_family = _micro_sim_reason_family(intent_frame, intent)
        action_family = _micro_sim_action_family(intent_frame.public_survival_mode)
        confidence = _safe_confidence(0.78 - idx * 0.12)
        rationale = trim_text(
            f"{member.display_name}在{segment_role}段的利益变化最敏感，当前更可能先手{action_family}。",
            120,
        )
        ranked_choices.append(
            _NpcMicroSimChoice(
                character_id=character_id,
                action_family=action_family,
                reason_family=reason_family,
                signal_family=signal_family,
                cost_family=member.strategic_intent.regression_payoff,
                confidence=confidence,
                rationale=rationale,
            )
        )
    recommended_actor_id = ranked_choices[0].character_id if ranked_choices else None
    summary = trim_text(
        "micro-sim 预测了本回合最可能主动出手的 supporting 角色，并给出原因族。",
        220,
    )
    return _NpcMicroSimResult(
        source="heuristic",
        shortlist=shortlist,
        recommended_actor_id=recommended_actor_id,
        choices=tuple(ranked_choices[:3]),
        summary=summary,
    )


def _run_npc_micro_sim(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    gateway: PlayLLMGateway | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> _NpcMicroSimResult | None:
    segment = _resolved_segment(plan, state)
    if segment.segment_role not in {"misread", "pressure", "reveal", "terminal"}:
        if diagnostics is not None:
            diagnostics.setdefault("micro_sim_status", "segment_skipped")
        return None
    members_by_id = {member.character_id: member for member in plan.cast}
    max_candidates = max(1, int(getattr(get_settings(), "play_v2_micro_sim_max_candidates", 3) or 3))
    ranked_ids: list[tuple[str, int]] = []
    for character_id in state.active_character_ids:
        if character_id == intent.target_id:
            continue
        member = members_by_id.get(character_id)
        if member is None:
            continue
        mind = state.npc_mind_states.get(character_id)
        score = _micro_sim_candidate_score(
            intent=intent,
            character_id=character_id,
            intent_frame=member.strategic_intent,
            mind=mind,
            state=state,
            segment_role=segment.segment_role,
        )
        ranked_ids.append((character_id, score))
    ranked_ids = sorted(ranked_ids, key=lambda item: (item[1], item[0]), reverse=True)
    shortlist = tuple(item[0] for item in ranked_ids[:max_candidates] if item[1] > 0)
    if not shortlist:
        if diagnostics is not None:
            diagnostics.setdefault("micro_sim_status", "no_candidates")
        return None
    pack = state.active_beat_delta_pack
    micro_hints = pack.micro_sim_hint_bundle if pack.segment_id == segment.segment_id else None
    if micro_hints is not None and micro_hints.preferred_actor_ids:
        preferred_ids = set(micro_hints.preferred_actor_ids)
        shortlist = tuple(
            unique_preserve(
                [
                    *(character_id for character_id in shortlist if character_id in preferred_ids),
                    *shortlist,
                ]
            )[:max_candidates]
        )
    heuristic_result = _heuristic_micro_sim_result(
        plan=plan,
        state=state,
        intent=intent,
        shortlist=shortlist,
        segment_role=segment.segment_role,
    )
    should_invoke_llm_micro_sim, micro_sim_gate_reason = _should_invoke_micro_sim_llm(
        plan=plan,
        state=state,
        segment_role=segment.segment_role,
    )
    if diagnostics is not None:
        diagnostics["micro_sim_llm_gate_reason"] = micro_sim_gate_reason
    if not should_invoke_llm_micro_sim:
        if diagnostics is not None:
            diagnostics["micro_sim_status"] = "heuristic_only"
        return heuristic_result
    settings = get_settings()
    if not _live_llm_calls_enabled(settings=settings, flag_attr="play_v2_micro_sim_use_llm"):
        if diagnostics is not None:
            diagnostics["micro_sim_status"] = "disabled_pytest" if os.getenv("PYTEST_CURRENT_TEST") else "disabled"
        return heuristic_result
    if gateway is None:
        if diagnostics is not None:
            diagnostics["micro_sim_status"] = "gateway_unavailable"
        return heuristic_result
    shortlist_payload = []
    for choice in heuristic_result.choices:
        member = members_by_id.get(choice.character_id)
        if member is None:
            continue
        shortlist_payload.append(
            {
                "character_id": choice.character_id,
                "display_name": member.display_name,
                "public_survival_mode": member.strategic_intent.public_survival_mode,
                "loss_trigger": member.strategic_intent.loss_trigger,
                "heuristic_reason_family": choice.reason_family,
                "heuristic_action_family": choice.action_family,
                "heuristic_confidence": choice.confidence,
            }
        )
    if not shortlist_payload:
        return heuristic_result
    started = time.perf_counter()
    try:
        response = gateway._invoke_json(
            system_prompt=(
                "你是 RPG play_v2 的 NPC micro-sim 角色动机预测器。"
                "只输出 JSON。字段: recommended_actor_id,summary,candidates。"
                "candidates 是数组，每项包含 character_id,action_family,reason_family,signal_family,cost_family,confidence,rationale。"
                "只允许使用 shortlist 里的 character_id。reason_family 必须是 loss_position/self_preserve/old_debt/opportunity_window/blame_shift/mixed。"
                "confidence 输出 0-1 浮点，保留两位即可。"
            ),
            user_payload={
                "segment_role": segment.segment_role,
                "shell_id": plan.story_shell_id,
                "intent": {
                    "move_family": intent.move_family,
                    "target_id": intent.target_id,
                    "scene_frame": intent.scene_frame,
                    "control_action": intent.control_action,
                },
                "shortlist": shortlist_payload,
                "micro_sim_hint_bundle": (
                    micro_hints.model_dump(mode="json")
                    if micro_hints is not None
                    else {}
                ),
            },
            max_output_tokens=int(getattr(settings, "play_v2_micro_sim_max_output_tokens", 260) or 260),
            operation_name="play_v2.npc_micro_sim",
            plaintext_fallback_key=None,
        )
    except PlayGatewayError:
        if diagnostics is not None:
            diagnostics["micro_sim_status"] = "failed"
            diagnostics["micro_sim_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
        return heuristic_result
    if diagnostics is not None:
        diagnostics["micro_sim_status"] = "completed"
        diagnostics["micro_sim_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
        diagnostics["micro_sim_input_tokens"] = _usage_token_count(response.usage, "input_tokens")
        diagnostics["micro_sim_output_tokens"] = _usage_token_count(response.usage, "output_tokens")
        diagnostics["micro_sim_total_tokens"] = _usage_token_count(response.usage, "total_tokens")
    payload = response.payload if isinstance(response.payload, dict) else {}
    allowed_ids = set(shortlist)
    allowed_reason = {"loss_position", "self_preserve", "old_debt", "opportunity_window", "blame_shift", "mixed"}
    raw_candidates = payload.get("candidates")
    parsed_choices: list[_NpcMicroSimChoice] = []
    for raw in list(raw_candidates or []):
        if not isinstance(raw, dict):
            continue
        character_id = str(raw.get("character_id") or "").strip()
        if character_id not in allowed_ids:
            continue
        reason_family = str(raw.get("reason_family") or "mixed").strip()
        if reason_family not in allowed_reason:
            reason_family = "mixed"
        confidence = _safe_confidence(float(raw.get("confidence") or 0.0))
        parsed_choices.append(
            _NpcMicroSimChoice(
                character_id=character_id,
                action_family=trim_text(str(raw.get("action_family") or "test_water"), 40),
                reason_family=reason_family,
                signal_family=trim_text(str(raw.get("signal_family") or _micro_sim_signal_family(plan.story_shell_id)), 40),
                cost_family=trim_text(str(raw.get("cost_family") or "mixed"), 40),
                confidence=max(confidence, 0.2),
                rationale=trim_text(str(raw.get("rationale") or ""), 120),
            )
        )
    if not parsed_choices:
        return heuristic_result
    parsed_choices = sorted(parsed_choices, key=lambda item: (item.confidence, item.character_id), reverse=True)[:max_candidates]
    recommended_actor_id = str(payload.get("recommended_actor_id") or "").strip()
    if recommended_actor_id not in {item.character_id for item in parsed_choices}:
        recommended_actor_id = parsed_choices[0].character_id
    summary = trim_text(str(payload.get("summary") or heuristic_result.summary), 220)
    return _NpcMicroSimResult(
        source="llm",
        shortlist=shortlist,
        recommended_actor_id=recommended_actor_id,
        choices=tuple(parsed_choices),
        summary=summary,
    )


def _try_compile_with_llm(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    input_text: str,
    suggestions: list[UrbanSuggestedAction],
    gateway: PlayLLMGateway | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> _IntentCandidate | None:
    settings = get_settings()
    if not _live_llm_calls_enabled(settings=settings, flag_attr="play_v2_intent_compiler_use_llm"):
        if diagnostics is not None:
            diagnostics.setdefault("intent_llm_status", "disabled_pytest" if os.getenv("PYTEST_CURRENT_TEST") else "disabled")
        return None
    if gateway is None:
        if diagnostics is not None:
            diagnostics["intent_llm_status"] = "gateway_unavailable"
        return None
    segment = _resolved_segment(plan, state)
    play_tuning = _play_tuning_profile(plan)
    intent_control_contract_hint_weight = (
        float(getattr(play_tuning, "intent_control_contract_hint_weight", 1.0))
        if play_tuning is not None
        else 1.0
    )
    allowed_moves = list(dict.fromkeys(segment.allowed_move_families or list(MOVE_KEYWORDS.keys())))
    cast_payload = [
        {
            "character_id": member.character_id,
            "display_name": member.display_name,
        }
        for member in plan.cast
    ]
    suggestion_payload = [
        {
            "suggestion_id": item.suggestion_id,
            "lane_id": item.lane_id,
            "move_family": item.move_family,
            "target_id": item.target_id,
            "scene_frame": item.scene_frame,
            "label": item.label,
        }
        for item in suggestions
    ]
    control_actions = [
        {
            "action_type": item.action_type,
            "target_mode": item.target_mode,
            "target_kind": item.target_kind,
            "target_id": item.target_id,
            "label": item.label,
        }
        for item in build_control_actions(plan, state)
    ]
    started = time.perf_counter()
    try:
        response = gateway._invoke_json(
            system_prompt=(
                "你是 play_v2 的自由输入意图编译器。只输出 JSON 对象。"
                "字段: move_family,target_id,target_name,scene_frame,lane_id,intent_confidence,deviation_type,deviation_note,alternatives,semantic_effects。"
                "可选字段: control_action,control_target_id,control_target_mode,tradeoff_markers。"
                "move_family 必须来自 allowed_move_families。scene_frame 只能是 private/semi_public/public。"
                "intent_confidence 输出 0 到 1 浮点。若输入含多步动作或多目标，优先给第一可执行步，并在 deviation_note 解释偏移和 alternatives。"
                "当输入带有让步、代价、拒绝升级、台面证据等信号时，优先在 tradeoff_markers 提炼短语，并尽量给出可执行 control_action。"
                "可参考 intent_control_contract_hint_weight 调整 tradeoff_markers 和 control_action 的提取强度。"
                "semantic_effects 是一个数组，每个元素 {effect_type, target_id, detail}。"
                "effect_type 可选值: secret_reveal, trust_action, betrayal, public_exposure, emotional_shift, alliance_change, confession, confrontation, protection, jealousy_provocation。"
                "用 semantic_effects 描述玩家行为的语义后果，不要只依赖 move_family。例如玩家说'把秘密告诉大家'，move_family 是 public_reveal，同时 semantic_effects 应包含 {effect_type:'secret_reveal', detail:'向众人揭露秘密'}。"
            ),
            user_payload={
                "input_text": input_text,
                "segment_role": segment.segment_role,
                "allowed_move_families": allowed_moves,
                "default_scene_frame": _scene_frame_for_segment(segment),
                "cast": cast_payload,
                "suggestions": suggestion_payload,
                "control_actions": control_actions,
                "intent_control_contract_hint_weight": round(intent_control_contract_hint_weight, 4),
                "known_secrets": [sid for sid in (state.known_secret_ids or [])],
                "allocated_secrets_this_segment": [sid for sid in (segment.allocated_secret_ids or [])],
            },
            max_output_tokens=int(getattr(settings, "play_v2_intent_compiler_max_output_tokens", 220) or 220),
            operation_name="play_v2.intent_compile",
            plaintext_fallback_key=None,
        )
    except PlayGatewayError:
        if diagnostics is not None:
            diagnostics["intent_llm_status"] = "failed"
            diagnostics["intent_llm_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
        return None
    if diagnostics is not None:
        diagnostics["intent_llm_status"] = "completed"
        diagnostics["intent_llm_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
        diagnostics["intent_llm_input_tokens"] = _usage_token_count(response.usage, "input_tokens")
        diagnostics["intent_llm_output_tokens"] = _usage_token_count(response.usage, "output_tokens")
        diagnostics["intent_llm_total_tokens"] = _usage_token_count(response.usage, "total_tokens")
    payload = response.payload if isinstance(response.payload, dict) else {}
    move_family = str(payload.get("move_family") or "")
    if move_family not in set(allowed_moves):
        return None
    target_id = str(payload.get("target_id") or "").strip() or None
    target_name = str(payload.get("target_name") or "").strip()
    if target_id is None and target_name:
        target_id = next(
            (
                member.character_id
                for member in plan.cast
                if _normalize_user_text(member.display_name) == _normalize_user_text(target_name)
            ),
            None,
        )
    if target_id is not None and target_id not in {member.character_id for member in plan.cast}:
        target_id = None
    scene_frame = str(payload.get("scene_frame") or "").strip() or _scene_frame_for_segment(segment)
    if scene_frame not in {"private", "semi_public", "public"}:
        scene_frame = _scene_frame_for_segment(segment)
    lane_id = str(payload.get("lane_id") or "").strip() or None
    if lane_id not in {"relationship", "side", "burst"}:
        lane_id = None
    raw_alternatives = payload.get("alternatives")
    alternatives: tuple[str, ...] = tuple(
        trim_text(str(item), 80)
        for item in list(raw_alternatives or [])
        if isinstance(item, str) and str(item).strip()
    )[:3]
    deviation_type = _normalize_deviation_type(str(payload.get("deviation_type") or ""))
    deviation_note = str(payload.get("deviation_note") or "").strip() or None
    confidence = _safe_confidence(float(payload.get("intent_confidence") or 0.0))
    control_action = _normalize_optional_control_action(payload.get("control_action"))
    control_target_mode = _normalize_optional_control_target_mode(payload.get("control_target_mode"))
    control_target_id = str(payload.get("control_target_id") or "").strip() or None
    if control_target_id and control_target_id not in {member.character_id for member in plan.cast}:
        control_target_id = None
    tradeoff_markers = _normalize_tradeoff_markers(payload.get("tradeoff_markers"))
    raw_semantic_effects = payload.get("semantic_effects")
    semantic_effects: tuple[dict[str, str], ...] = ()
    if isinstance(raw_semantic_effects, list):
        parsed_effects = []
        for raw_effect in raw_semantic_effects[:6]:
            if isinstance(raw_effect, dict) and raw_effect.get("effect_type"):
                parsed_effects.append({
                    "effect_type": str(raw_effect.get("effect_type", ""))[:60],
                    "target_id": str(raw_effect.get("target_id", ""))[:120] if raw_effect.get("target_id") else "",
                    "detail": str(raw_effect.get("detail", ""))[:220],
                })
        semantic_effects = tuple(parsed_effects)
    if diagnostics is not None:
        diagnostics["intent_llm_control_action"] = control_action
        diagnostics["intent_llm_control_target_id"] = control_target_id or ""
        diagnostics["intent_llm_control_target_mode"] = control_target_mode or ""
        diagnostics["intent_tradeoff_markers"] = ",".join(tradeoff_markers)
    return _IntentCandidate(
        move_family=move_family,  # type: ignore[arg-type]
        target_id=target_id,
        scene_frame=scene_frame,  # type: ignore[arg-type]
        lane_id=lane_id,  # type: ignore[arg-type]
        mapped_suggestion_id=None,
        intent_confidence=max(confidence, 0.35),
        compile_source="llm",
        deviation_type=deviation_type,
        deviation_note=trim_text(deviation_note, 220) if deviation_note else None,
        alternatives=alternatives,
        control_action=control_action,
        control_target_id=control_target_id,
        control_target_mode=control_target_mode,
        tradeoff_markers=tradeoff_markers,
        semantic_effects=semantic_effects,
    )


def _heuristic_intent_candidate(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    input_text: str,
    suggestions: list[UrbanSuggestedAction],
    nearest_suggestion: UrbanSuggestedAction | None,
    clause_intents: list[_ClauseIntent] | None = None,
) -> _IntentCandidate:
    lowered = input_text.casefold()
    low_information = _is_low_information_input(input_text)
    default_move = nearest_suggestion.move_family if nearest_suggestion is not None else (suggestions[0].move_family if suggestions else "probe_secret")
    clause_intents = clause_intents if clause_intents is not None else _extract_clause_intents(plan, input_text)
    segment = _resolved_segment(plan, state)
    allowed_moves = set(segment.allowed_move_families or list(MOVE_KEYWORDS.keys()))
    primary_clause: _ClauseIntent | None = None
    if clause_intents:
        primary_clause = max(
            clause_intents,
            key=lambda item: (_primary_clause_score(item, allowed_moves=allowed_moves), -item.clause_index, len(item.clause_text)),
        )
    move_family = default_move
    confidence = 0.38
    if primary_clause is not None and primary_clause.move_family in allowed_moves:
        move_family = primary_clause.move_family
        confidence = max(0.66, min(0.88, 0.64 + 0.08 * float(primary_clause.move_hit_count)))
    elif primary_clause is not None and primary_clause.move_family is not None and primary_clause.move_family not in allowed_moves:
        confidence = min(confidence, 0.56)
    else:
        for candidate, keywords in MOVE_KEYWORDS.items():
            if candidate in allowed_moves and any(keyword.casefold() in lowered for keyword in keywords):
                move_family = candidate
                confidence = 0.72
                break
    explicit_target_hit = False
    target_id = primary_clause.target_id if primary_clause is not None else None
    if target_id is None:
        target_id = next(
            (
                member.character_id
                for member in plan.cast
                if member.display_name.casefold() in lowered
            ),
            None,
        )
    if target_id is not None:
        explicit_target_hit = True
    auto_target_fallback = False
    if target_id is None and nearest_suggestion is not None:
        target_id = nearest_suggestion.target_id
        auto_target_fallback = target_id is not None
    if target_id is not None and not low_information:
        confidence = max(confidence, 0.64)
    scene_frame: RelationshipSceneFrame = _scene_frame_for_segment(_resolved_segment(plan, state))
    if any(keyword.casefold() in lowered for keyword in PUBLIC_FRAME_KEYWORDS):
        scene_frame = "public"
        confidence = max(confidence, 0.72)
    elif any(keyword.casefold() in lowered for keyword in SEMI_PUBLIC_FRAME_KEYWORDS):
        scene_frame = "semi_public"
        confidence = max(confidence, 0.58)
    elif move_family == "public_reveal":
        scene_frame = "public"
    elif move_family == "private_confession":
        scene_frame = "private"
    mapped = None
    deviation_type = "none"
    deviation_note = None
    alternatives = _slot_alternatives(suggestions, preferred_suggestion_id=mapped)
    secondary_alternatives = _secondary_alternatives_from_clauses(
        suggestions=suggestions,
        clause_intents=clause_intents,
        primary_move=move_family,
    )
    control_alternatives = _control_alternatives_from_clauses(
        control_actions=build_control_actions(plan, state),
        clause_intents=clause_intents,
    )
    if secondary_alternatives:
        alternatives = tuple(unique_preserve([*secondary_alternatives, *alternatives])[:3])
        deviation_type = "scope_shift"
        deviation_note = trim_text(
            "你这句包含多步动作，系统先执行最贴近当前段落的一步，后续动作保留在候选里。",
            220,
        )
    has_story_clause = any(clause.move_family is not None for clause in clause_intents)
    has_control_clause = any(clause.control_action != "none" for clause in clause_intents)
    has_split_scope = (
        any(clause.move_family is not None and clause.control_action == "none" for clause in clause_intents)
        and has_control_clause
    )
    if control_alternatives and has_split_scope:
        alternatives = tuple(unique_preserve([*alternatives, *control_alternatives])[:3])
        if deviation_type == "none":
            deviation_type = "scope_shift"
            deviation_note = trim_text(
                "你这句同时在推进剧情和控雷，系统先落一条可执行主动作，其余作为下一步候选。",
                220,
            )
    distinct_targets = {
        clause.target_id
        for clause in clause_intents
        if clause.target_id is not None
    }
    if len(distinct_targets) > 1 and deviation_type == "none":
        deviation_type = "target_shift"
        deviation_note = trim_text(
            "你这句同时点了多个对象，系统先落到当前风险最高的一位，避免回合失焦。",
            220,
        )
    if nearest_suggestion is not None and move_family == nearest_suggestion.move_family and target_id == nearest_suggestion.target_id:
        mapped = nearest_suggestion.suggestion_id
    if _is_out_of_scope_input(input_text) and nearest_suggestion is not None:
        move_family = nearest_suggestion.move_family
        target_id = nearest_suggestion.target_id
        scene_frame = nearest_suggestion.scene_frame
        mapped = nearest_suggestion.suggestion_id
        # Keep soft-repaired out-of-scope inputs in the low-confidence bucket
        # so downstream diagnostics and repair analytics remain explainable.
        confidence = 0.39
        deviation_note = _soft_repair_note(plan, nearest_suggestion)
        deviation_type = "scope_shift"
    elif auto_target_fallback and not explicit_target_hit and deviation_type == "none":
        deviation_type = "target_shift"
    elif low_information:
        confidence = min(confidence, 0.34)
    heuristic_semantic_effects: tuple[dict[str, str], ...] = ()
    _MOVE_TO_EFFECT_TYPE = {
        "probe_secret": "secret_reveal",
        "public_reveal": "public_exposure",
        "private_confession": "confession",
        "comfort": "trust_action",
        "accuse": "confrontation",
        "ally_with": "alliance_change",
        "betray": "betrayal",
        "flirt": "emotional_shift",
        "jealousy_trigger": "jealousy_provocation",
        "deflect": "protection",
    }
    effect_type = _MOVE_TO_EFFECT_TYPE.get(move_family, "")
    if effect_type:
        heuristic_semantic_effects = ({"effect_type": effect_type, "target_id": target_id or "", "detail": ""},)
    return _IntentCandidate(
        move_family=move_family,
        target_id=target_id,
        scene_frame=scene_frame,
        lane_id=None,
        mapped_suggestion_id=mapped,
        intent_confidence=confidence,
        compile_source="heuristic_fallback",
        deviation_type=deviation_type,
        deviation_note=deviation_note,
        alternatives=alternatives,
        semantic_effects=heuristic_semantic_effects,
    )


def _control_bias_triggered(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    segment_role: SegmentRoleId,
    intent_compile_source: str,
    intent_confidence: float,
) -> bool:
    if (
        segment_role == "opening"
        and int(state.turn_index) <= _control_bias_opening_force_until_turn_index(plan)
    ):
        return True
    if intent_compile_source == "heuristic_fallback":
        return True
    if intent_compile_source == "llm" and float(intent_confidence) < _control_bias_low_confidence(plan):
        return True
    return False


def _select_control_bias_suggestion(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    suggestions: list[UrbanSuggestedAction],
) -> UrbanSuggestedAction | None:
    preferred_lane = _control_bias_segment_lane(plan).get(segment.segment_role)
    if preferred_lane is None:
        return None
    soft_moves = _control_bias_soft_moves(plan)
    candidates = [
        item
        for item in suggestions
        if item.lane_id == preferred_lane
        and item.move_family in set(segment.allowed_move_families)
        and item.move_family not in soft_moves
    ]
    if not candidates:
        candidates = [
            item
            for item in suggestions
            if item.move_family in set(segment.allowed_move_families)
            and item.move_family not in soft_moves
        ]
    if not candidates:
        return None
    move_priority_rank = {
        move_family: index
        for index, move_family in enumerate(segment.move_priorities)
    }

    def _score(item: UrbanSuggestedAction) -> tuple[int, int, str]:
        leverage = _control_bias_leverage_bonus(plan) if item.move_family in _DEFAULT_CONTROL_BIAS_LEVERAGE_MOVES else 0.0
        priority = 6 - min(move_priority_rank.get(item.move_family, 6), 6)
        return int(round(leverage + priority)), -move_priority_rank.get(item.move_family, 99), item.suggestion_id

    return max(candidates, key=_score)


def _apply_control_bias_if_needed(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    suggestions: list[UrbanSuggestedAction],
    submitted_with_selected_ids: bool,
    move_family: RelationshipMoveFamily,
    target_id: str | None,
    scene_frame: RelationshipSceneFrame,
    lane_id: SuggestionLaneId,
    mapped_suggestion_id: str | None,
    intent_confidence: float,
    intent_compile_source: str,
    control_source: str,
    deviation_type: str,
    deviation_note: str | None,
    diagnostics: dict[str, Any] | None,
) -> tuple[RelationshipMoveFamily, str | None, RelationshipSceneFrame, SuggestionLaneId, str | None, float, str, str | None]:
    if diagnostics is not None:
        diagnostics.setdefault("control_bias_applied", False)
        diagnostics.setdefault("control_bias_reason", "not_evaluated")
        diagnostics.setdefault("control_bias_from_move", "")
        diagnostics.setdefault("control_bias_to_move", "")
    if submitted_with_selected_ids:
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "submitted_selected_ids"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    if state.latent_events:
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "latent_context_keep_soft"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    segment = _resolved_segment(plan, state)
    segment_lane_map = _control_bias_segment_lane(plan)
    if segment.segment_role not in segment_lane_map:
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "segment_not_supported"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    if move_family not in _control_bias_soft_moves(plan):
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "non_soft_move"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    if control_source == "explicit":
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "explicit_control"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    if not _control_bias_triggered(
        plan=plan,
        state=state,
        segment_role=segment.segment_role,
        intent_compile_source=intent_compile_source,
        intent_confidence=intent_confidence,
    ):
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "confidence_not_low"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    biased = _select_control_bias_suggestion(plan=plan, segment=segment, suggestions=suggestions)
    if biased is None:
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "no_bias_candidate"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    if biased.move_family == move_family and biased.target_id == target_id:
        if diagnostics is not None:
            diagnostics["control_bias_reason"] = "already_aligned"
        return (
            move_family,
            target_id,
            scene_frame,
            lane_id,
            mapped_suggestion_id,
            intent_confidence,
            deviation_type,
            deviation_note,
        )
    from_label = MOVE_FAMILY_SURFACE_LABELS.get(move_family, move_family)
    to_label = MOVE_FAMILY_SURFACE_LABELS.get(biased.move_family, biased.move_family)
    target_name = _target_name(plan, biased.target_id)
    bias_note = trim_text(
        f"你这句先落在「{from_label}」，系统先升级成「{to_label}」并指向{target_name}，优先逼出可观测代价和站位换手。",
        220,
    )
    if deviation_note:
        bias_note = trim_text(f"{deviation_note} {bias_note}", 220)
    if diagnostics is not None:
        diagnostics["control_bias_applied"] = True
        diagnostics["control_bias_reason"] = "applied"
        diagnostics["control_bias_from_move"] = move_family
        diagnostics["control_bias_to_move"] = biased.move_family
    return (
        biased.move_family,
        biased.target_id,
        biased.scene_frame,
        biased.lane_id,
        biased.suggestion_id,
        max(float(intent_confidence), _control_bias_low_confidence(plan)),
        ("scope_shift" if deviation_type == "none" else deviation_type),
        bias_note,
    )


def _legalize_candidate(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    candidate: _IntentCandidate,
    nearest_suggestion: UrbanSuggestedAction | None,
    suggestions: list[UrbanSuggestedAction],
) -> _IntentCandidate:
    segment = _resolved_segment(plan, state)
    allowed = set(segment.allowed_move_families or list(MOVE_KEYWORDS.keys()))
    move_family = candidate.move_family
    target_id = candidate.target_id
    scene_frame = candidate.scene_frame
    lane_id = candidate.lane_id
    mapped_suggestion_id = candidate.mapped_suggestion_id
    deviation_type = candidate.deviation_type
    deviation_note = candidate.deviation_note
    confidence = candidate.intent_confidence
    if move_family not in allowed and nearest_suggestion is not None:
        move_family = nearest_suggestion.move_family
        target_id = nearest_suggestion.target_id
        scene_frame = nearest_suggestion.scene_frame
        lane_id = nearest_suggestion.lane_id
        mapped_suggestion_id = nearest_suggestion.suggestion_id
        confidence = min(confidence, 0.58)
        if deviation_type == "none":
            deviation_type = "move_downgrade"
        deviation_note = deviation_note or _soft_repair_note(plan, nearest_suggestion)
    if target_id is None and nearest_suggestion is not None:
        target_id = nearest_suggestion.target_id
        mapped_suggestion_id = mapped_suggestion_id or nearest_suggestion.suggestion_id
        confidence = min(confidence, 0.64)
        if deviation_type == "none":
            deviation_type = "target_shift"
        if deviation_note is None:
            deviation_note = trim_text(
                f"你这句没有点名对象，系统先把动作落到{_target_name(plan, target_id)}身上，确保回合可执行。",
                220,
            )
    if move_family == "public_reveal":
        scene_frame = "public"
    elif move_family == "private_confession":
        scene_frame = "private"
    if lane_id is None:
        if mapped_suggestion_id:
            matched = next((item for item in suggestions if item.suggestion_id == mapped_suggestion_id), None)
            lane_id = matched.lane_id if matched is not None else _fallback_lane_id(move_family)
        else:
            lane_id = _fallback_lane_id(move_family)
    alternatives = candidate.alternatives or _slot_alternatives(suggestions, preferred_suggestion_id=mapped_suggestion_id)
    return _IntentCandidate(
        move_family=move_family,
        target_id=target_id,
        scene_frame=scene_frame,
        lane_id=lane_id,
        mapped_suggestion_id=mapped_suggestion_id,
        intent_confidence=_safe_confidence(confidence),
        compile_source=candidate.compile_source,
        deviation_type=deviation_type,
        deviation_note=deviation_note,
        alternatives=alternatives,
        semantic_effects=candidate.semantic_effects,
    )


def parse_turn_intent(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    input_text: str,
    *,
    gateway: PlayLLMGateway | None = None,
    selected_suggestion_id: str | None = None,
    selected_story_action_id: str | None = None,
    selected_control_action_id: str | None = None,
    control_action: LatentEventControl | None = None,
    control_target_kind: str | None = None,
    control_target_id: str | None = None,
    control_target_mode: str | None = None,
    prefetched_suggestions: tuple[UrbanSuggestedAction, ...] | None = None,
    prefetched_control_actions: tuple[UrbanControlAction, ...] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> UrbanTurnIntent:
    submitted_with_selected_ids = bool((selected_story_action_id or "").strip() or (selected_suggestion_id or "").strip())
    if diagnostics is not None:
        diagnostics.setdefault("control_bias_applied", False)
        diagnostics.setdefault("control_bias_reason", "not_evaluated")
        diagnostics.setdefault("control_bias_from_move", "")
        diagnostics.setdefault("control_bias_to_move", "")
        diagnostics.setdefault("intent_llm_control_used", False)
        diagnostics.setdefault("intent_tradeoff_markers", "")
    clause_intents = _extract_clause_intents(plan, input_text)
    suggestions = list(prefetched_suggestions) if prefetched_suggestions is not None else build_suggested_actions(plan, state)
    nearest_suggestion = _nearest_legal_suggestion(plan, suggestions, input_text)
    selected_story_id = selected_story_action_id or selected_suggestion_id
    normalized_input = _normalize_user_text(input_text)
    if selected_story_id is None and normalized_input:
        prompt_matched = next((item for item in suggestions if _normalize_user_text(item.prompt) == normalized_input), None)
        if prompt_matched is not None:
            selected_story_id = prompt_matched.suggestion_id
    control_actions = (
        list(prefetched_control_actions)
        if prefetched_control_actions is not None
        else build_control_actions(plan, state)
    )
    selected_control = next((item for item in control_actions if item.action_id == selected_control_action_id), None)
    selected_story = next((item for item in suggestions if item.suggestion_id == selected_story_id), None)
    llm_candidate: _IntentCandidate | None = None
    if selected_story is not None:
        if diagnostics is not None:
            diagnostics.setdefault("intent_llm_status", "bypassed:selected_story")
            diagnostics.setdefault("intent_llm_gate_reason", "selected_story")
        candidate = _IntentCandidate(
            move_family=selected_story.move_family,
            target_id=selected_story.target_id,
            scene_frame=selected_story.scene_frame,
            lane_id=selected_story.lane_id,
            mapped_suggestion_id=selected_story.suggestion_id,
            intent_confidence=0.95,
            compile_source="heuristic_fallback",
            alternatives=_slot_alternatives(suggestions, preferred_suggestion_id=selected_story.suggestion_id),
        )
    else:
        heuristic_candidate = _heuristic_intent_candidate(
            plan,
            state,
            input_text,
            suggestions,
            nearest_suggestion,
            clause_intents=clause_intents,
        )
        should_invoke_intent_llm, intent_llm_gate_reason = _should_invoke_intent_llm(
            plan=plan,
            state=state,
            input_text=input_text,
            clause_intents=clause_intents,
            heuristic_candidate=heuristic_candidate,
            selected_control_action_id=selected_control_action_id,
            control_action=control_action,
        )
        if diagnostics is not None:
            diagnostics["intent_llm_gate_reason"] = intent_llm_gate_reason
        if should_invoke_intent_llm:
            llm_candidate = _try_compile_with_llm(
                plan,
                state,
                input_text,
                suggestions,
                gateway=gateway,
                diagnostics=diagnostics,
            )
            candidate = llm_candidate or heuristic_candidate
            if llm_candidate is None and diagnostics is not None and "intent_llm_status" not in diagnostics:
                diagnostics["intent_llm_status"] = "heuristic_after_llm"
        else:
            if diagnostics is not None and "intent_llm_status" not in diagnostics:
                diagnostics["intent_llm_status"] = "bypassed:heuristic_gate"
            candidate = heuristic_candidate
    legalized = _legalize_candidate(
        plan=plan,
        state=state,
        candidate=candidate,
        nearest_suggestion=nearest_suggestion,
        suggestions=suggestions,
    )
    move_family = legalized.move_family
    target_id = legalized.target_id
    scene_frame = legalized.scene_frame
    lane_id = legalized.lane_id
    mapped_suggestion_id = legalized.mapped_suggestion_id
    intent_confidence = legalized.intent_confidence
    intent_compile_source = legalized.compile_source
    deviation_type = legalized.deviation_type
    deviation_note = legalized.deviation_note
    out_of_scope_input = _is_out_of_scope_input(input_text)
    if out_of_scope_input and nearest_suggestion is not None:
        mapped_suggestion_id = mapped_suggestion_id or nearest_suggestion.suggestion_id
        deviation_type = "scope_shift"
        deviation_note = _soft_repair_note(plan, nearest_suggestion)
    if mapped_suggestion_id is None and nearest_suggestion is not None:
        if move_family == nearest_suggestion.move_family or target_id is None or deviation_type != "none":
            mapped_suggestion_id = nearest_suggestion.suggestion_id

    resolved_control_action = control_action or "none"
    control_source: str = "none"
    if selected_control is not None:
        resolved_control_action = selected_control.action_type
        control_source = "explicit"
    if control_action and control_action != "none":
        resolved_control_action = control_action
        control_source = "explicit"
    if resolved_control_action == "none":
        llm_control_action = llm_candidate.control_action if llm_candidate is not None else "none"
        if llm_control_action != "none":
            resolved_control_action = llm_control_action
            control_source = "free_text"
            if diagnostics is not None:
                diagnostics["intent_llm_control_used"] = True
            if llm_candidate.control_target_mode and not control_target_mode:
                control_target_mode = llm_candidate.control_target_mode
            if llm_candidate.control_target_id and not control_target_id:
                control_target_id = llm_candidate.control_target_id
        inferred = next((item.control_action for item in clause_intents if item.control_action != "none"), "none")
        if resolved_control_action == "none" and inferred == "none":
            inferred = _free_text_control_action(input_text)
        if resolved_control_action == "none" and inferred != "none":
            resolved_control_action = inferred
            control_source = "free_text"
    resolved_control_target_kind = control_target_kind or (selected_control.target_kind if selected_control is not None else None)
    resolved_control_target_id = control_target_id if control_target_id is not None else (selected_control.target_id if selected_control is not None else None)
    resolved_control_target_mode = control_target_mode or (selected_control.target_mode if selected_control is not None else None)
    tradeoff_markers = llm_candidate.tradeoff_markers if llm_candidate is not None else ()
    if diagnostics is not None and tradeoff_markers:
        diagnostics["intent_tradeoff_markers"] = ",".join(tradeoff_markers)
    semantic_clause_count = sum(
        1
        for clause in clause_intents
        if clause.move_family is not None or clause.control_action != "none"
    )
    sequence_markers_present = any(token in input_text for token in ("然后", "再", "接着", "最后", "之后"))
    has_story_clause = any(clause.move_family is not None for clause in clause_intents)
    has_control_clause = any(clause.control_action != "none" for clause in clause_intents)
    has_story_only_clause = any(
        clause.move_family is not None and clause.control_action == "none"
        for clause in clause_intents
    )
    if (
        selected_story is None
        and (
            semantic_clause_count >= 2
            or (sequence_markers_present and len(clause_intents) >= 2)
        )
    ):
        deviation_type = "scope_shift"
        if deviation_note is None:
            deviation_note = trim_text(
                "你这句里有多步动作，系统先执行最接近当前段落的一步，其余动作保留为下一步候选。",
                220,
            )
    if has_story_only_clause and has_control_clause and deviation_note is None:
        deviation_type = "scope_shift"
        deviation_note = trim_text(
            "你这句同时在推进剧情和控雷，系统先落可执行主动作，其余控雷意图会保留在后续候选里。",
            220,
        )
    if (
        resolved_control_action == "redirect"
        and control_source == "free_text"
        and not resolved_control_target_id
    ):
        inferred_target_id = _infer_control_target_from_text(
            plan=plan,
            input_text=input_text,
            clause_intents=clause_intents,
        )
        if inferred_target_id is not None:
            resolved_control_target_id = inferred_target_id
            resolved_control_target_mode = "character"
        elif deviation_type == "none":
            deviation_type = "target_shift"
            deviation_note = trim_text(
                "你这句明确要转移风险，但没有指定谁来接，系统会先按主动作推进并保留转移意图。",
                220,
            )
    if deviation_note and deviation_type == "none":
        deviation_type = "scope_shift"
    if resolved_control_action == "redirect" and not (resolved_control_target_id or legalized.target_id):
        if control_source == "explicit":
            raise ValueError("redirect control requires a valid target cluster or character")
        resolved_control_action = "none"
        control_source = "none"
        deviation_note = trim_text("你这句更像是在转移风险，但没指定可落地对象，系统先按场内动作推进。", 220)
        deviation_type = "target_shift"
    (
        move_family,
        target_id,
        scene_frame,
        lane_id,
        mapped_suggestion_id,
        intent_confidence,
        deviation_type,
        deviation_note,
    ) = _apply_control_bias_if_needed(
        plan=plan,
        state=state,
        suggestions=suggestions,
        submitted_with_selected_ids=submitted_with_selected_ids,
        move_family=move_family,
        target_id=target_id,
        scene_frame=scene_frame,
        lane_id=lane_id,
        mapped_suggestion_id=mapped_suggestion_id,
        intent_confidence=intent_confidence,
        intent_compile_source=intent_compile_source,
        control_source=control_source,
        deviation_type=deviation_type,
        deviation_note=deviation_note,
        diagnostics=diagnostics,
    )
    if control_source == "free_text" and resolved_control_target_mode is None:
        resolved_control_target_mode = "kind"
    return UrbanTurnIntent(
        input_text=input_text,
        lane_id=lane_id,
        move_family=move_family,
        target_id=target_id,
        scene_frame=scene_frame,
        control_action=resolved_control_action,
        control_source=control_source,  # type: ignore[arg-type]
        control_target_kind=resolved_control_target_kind,  # type: ignore[arg-type]
        control_target_id=resolved_control_target_id,
        control_target_mode=resolved_control_target_mode,  # type: ignore[arg-type]
        confidence=_confidence_bucket(intent_confidence),
        intent_confidence=_safe_confidence(intent_confidence),
        intent_compile_source=intent_compile_source,  # type: ignore[arg-type]
        deviation_type=deviation_type,  # type: ignore[arg-type]
        deviation_note=deviation_note,
        alternatives=list(legalized.alternatives[:3]),
        mapped_suggestion_id=mapped_suggestion_id,
        semantic_effects=[
            SemanticEffect(
                effect_type=e.get("effect_type", ""),
                target_id=e.get("target_id") or None,
                detail=e.get("detail", ""),
            )
            for e in legalized.semantic_effects
        ],
    )


def run_intent_stage(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    input_text: str,
    *,
    gateway: PlayLLMGateway | None = None,
    selected_suggestion_id: str | None = None,
    selected_story_action_id: str | None = None,
    selected_control_action_id: str | None = None,
    control_action: LatentEventControl | None = None,
    control_target_kind: str | None = None,
    control_target_id: str | None = None,
    control_target_mode: str | None = None,
    precomputed_intent: UrbanTurnIntent | None = None,
    precomputed_micro_sim: Any | None = None,
    precomputed_diagnostics: dict[str, Any] | None = None,
    prefetched_suggestions: tuple[UrbanSuggestedAction, ...] | None = None,
    prefetched_control_actions: tuple[UrbanControlAction, ...] | None = None,
) -> tuple[UrbanTurnIntent, _NpcMicroSimResult | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = dict(precomputed_diagnostics or {})
    stage_started = time.perf_counter()
    if precomputed_intent is not None:
        intent = precomputed_intent.model_copy(deep=True)
        # When submit reuses a precomputed draft, submit-phase call accounting must
        # treat intent/micro as reused (not completed live calls).
        diagnostics["intent_llm_status"] = "reused_draft"
        diagnostics["intent_llm_gate_reason"] = "draft_reuse"
        diagnostics["micro_sim_status"] = "reused_draft"
        diagnostics["intent_parse_latency_ms"] = 0.0
        diagnostics["intent_micro_sim_stage_latency_ms"] = 0.0
        diagnostics["intent_stage_latency_ms"] = round((time.perf_counter() - stage_started) * 1000, 4)
        diagnostics["intent_compile_source"] = intent.intent_compile_source
        diagnostics["control_source"] = intent.control_source
        diagnostics["intent_stage_input_tokens"] = 0
        diagnostics["intent_stage_output_tokens"] = 0
        diagnostics["intent_stage_total_tokens"] = 0
        diagnostics["intent_llm_input_tokens"] = 0
        diagnostics["intent_llm_output_tokens"] = 0
        diagnostics["intent_llm_total_tokens"] = 0
        diagnostics["micro_sim_input_tokens"] = 0
        diagnostics["micro_sim_output_tokens"] = 0
        diagnostics["micro_sim_total_tokens"] = 0
        return intent, precomputed_micro_sim, diagnostics
    parse_started = time.perf_counter()
    intent = parse_turn_intent(
        plan,
        state,
        input_text,
        gateway=gateway,
        selected_suggestion_id=selected_suggestion_id,
        selected_story_action_id=selected_story_action_id,
        selected_control_action_id=selected_control_action_id,
        control_action=control_action,
        control_target_kind=control_target_kind,
        control_target_id=control_target_id,
        control_target_mode=control_target_mode,
        prefetched_suggestions=prefetched_suggestions,
        prefetched_control_actions=prefetched_control_actions,
        diagnostics=diagnostics,
    )
    parse_latency_ms = (time.perf_counter() - parse_started) * 1000
    diagnostics["intent_parse_latency_ms"] = round(parse_latency_ms, 4)
    diagnostics["intent_compile_source"] = intent.intent_compile_source
    diagnostics["control_source"] = intent.control_source
    micro_started = time.perf_counter()
    micro_sim = _run_npc_micro_sim(
        plan=plan,
        state=state,
        intent=intent,
        gateway=gateway,
        diagnostics=diagnostics,
    )
    diagnostics["intent_micro_sim_stage_latency_ms"] = round((time.perf_counter() - micro_started) * 1000, 4)
    diagnostics["intent_stage_latency_ms"] = round((time.perf_counter() - stage_started) * 1000, 4)
    intent_input_tokens = int(diagnostics.get("intent_llm_input_tokens", 0) or 0)
    intent_output_tokens = int(diagnostics.get("intent_llm_output_tokens", 0) or 0)
    micro_input_tokens = int(diagnostics.get("micro_sim_input_tokens", 0) or 0)
    micro_output_tokens = int(diagnostics.get("micro_sim_output_tokens", 0) or 0)
    diagnostics["intent_stage_input_tokens"] = max(intent_input_tokens + micro_input_tokens, 0)
    diagnostics["intent_stage_output_tokens"] = max(intent_output_tokens + micro_output_tokens, 0)
    diagnostics["intent_stage_total_tokens"] = int(diagnostics.get("intent_llm_total_tokens", 0)) + int(
        diagnostics.get("micro_sim_total_tokens", 0)
    )
    return intent, micro_sim, diagnostics


def run_speculative_compose_prewarm(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    input_text: str,
    *,
    gateway: PlayLLMGateway | None = None,
    selected_suggestion_id: str | None = None,
    selected_story_action_id: str | None = None,
    selected_control_action_id: str | None = None,
    control_action: LatentEventControl | None = None,
    control_target_kind: str | None = None,
    control_target_id: str | None = None,
    control_target_mode: str | None = None,
    precomputed_intent: UrbanTurnIntent | None = None,
    precomputed_micro_sim: Any | None = None,
    precomputed_intent_diagnostics: dict[str, Any] | None = None,
    prefetched_suggestions: tuple[UrbanSuggestedAction, ...] | None = None,
    prefetched_control_actions: tuple[UrbanControlAction, ...] | None = None,
) -> dict[str, Any]:
    submitted_with_selected_ids = bool(
        (selected_story_action_id or "").strip() or (selected_suggestion_id or "").strip()
    )
    working_state = state.model_copy(deep=True)
    intent, micro_sim, intent_diagnostics = run_intent_stage(
        plan,
        working_state,
        input_text,
        gateway=gateway,
        selected_suggestion_id=selected_suggestion_id,
        selected_story_action_id=selected_story_action_id,
        selected_control_action_id=selected_control_action_id,
        control_action=control_action,
        control_target_kind=control_target_kind,
        control_target_id=control_target_id,
        control_target_mode=control_target_mode,
        precomputed_intent=precomputed_intent,
        precomputed_micro_sim=precomputed_micro_sim,
        precomputed_diagnostics=precomputed_intent_diagnostics,
        prefetched_suggestions=prefetched_suggestions,
        prefetched_control_actions=prefetched_control_actions,
    )
    working_state, _ = apply_turn_resolution(
        plan,
        working_state,
        intent,
        micro_sim=micro_sim,
    )
    render_state = working_state.model_copy(deep=True)
    narration, compose_diagnostics = _render_narration(
        plan,
        render_state,
        intent,
        intent_diagnostics=intent_diagnostics,
        submitted_with_selected_ids=submitted_with_selected_ids,
        gateway=gateway,
    )
    diagnostics: dict[str, int | float | str | bool] = {}
    for key, value in dict(compose_diagnostics or {}).items():
        if isinstance(value, bool):
            diagnostics[str(key)] = value
        elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
            diagnostics[str(key)] = value
    compose_input_tokens = int(diagnostics.get("compose_input_tokens") or 0)
    compose_output_tokens = int(diagnostics.get("compose_output_tokens") or 0)
    compose_total_tokens = int(diagnostics.get("compose_total_tokens") or 0)
    if compose_total_tokens <= 0:
        compose_total_tokens = max(compose_input_tokens + compose_output_tokens, 0)
    return {
        "narration": narration,
        "diagnostics": diagnostics,
        "compose_input_tokens": compose_input_tokens,
        "compose_output_tokens": compose_output_tokens,
        "compose_total_tokens": compose_total_tokens,
        "source": str(diagnostics.get("narration_compose_source") or "prewarm_compose"),
    }


def _apply_relationship_delta(state: UrbanWorldState, target_id: str | None, move_family: RelationshipMoveFamily) -> None:
    if target_id is None or target_id not in state.relationships:
        return
    target = state.relationships[target_id]
    deltas = MOVE_DELTAS[move_family]
    target.affection = _clamp(target.affection + deltas.get("affection", 0), -3, 6)
    target.trust = _clamp(target.trust + deltas.get("trust", 0), -3, 6)
    target.tension = _clamp(target.tension + deltas.get("tension", 0), 0, 6)
    target.suspicion = _clamp(target.suspicion + deltas.get("suspicion", 0), 0, 6)
    target.dependency = _clamp(target.dependency + deltas.get("dependency", 0), 0, 6)


def _update_commitment_target(mind: NpcMindState, target_id: str | None) -> None:
    if target_id is None:
        return
    if mind.commitment_target_id == target_id:
        mind.commitment_streak = _clamp(mind.commitment_streak + 1, 0, 12)
    else:
        mind.commitment_target_id = target_id
        mind.commitment_streak = 1


def _apply_npc_mind_delta(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    target_id: str | None,
    move_family: RelationshipMoveFamily,
    scene_frame: RelationshipSceneFrame,
) -> None:
    if target_id is None or target_id not in state.npc_mind_states:
        return
    mind = state.npc_mind_states[target_id]
    relationship = state.relationships.get(target_id)
    if move_family == "comfort":
        mind.trust = _clamp(mind.trust + 2, -3, 6)
        mind.protectiveness = _clamp(mind.protectiveness + 1, 0, 6)
        mind.pressure_load = _clamp(mind.pressure_load - 1, 0, 6)
        mind.humiliation_risk = _clamp(mind.humiliation_risk - 1, 0, 6)
        if mind.trust >= 2:
            mind.stance = "ally"
            _update_commitment_target(mind, plan.route_target_ids[0] if plan.route_target_ids else target_id)
    elif move_family == "flirt":
        mind.affection = _clamp(mind.affection + 2, -3, 6)
        if scene_frame == "public":
            mind.mask_integrity = _clamp(mind.mask_integrity - 1, 0, 6)
            mind.humiliation_risk = _clamp(mind.humiliation_risk + 1, 0, 6)
        mind.jealousy = _clamp(mind.jealousy + (1 if relationship and relationship.is_route_focus else 0), 0, 6)
    elif move_family == "probe_secret":
        mind.suspicion = _clamp(mind.suspicion + 1, 0, 6)
        mind.pressure_load = _clamp(mind.pressure_load + 1, 0, 6)
        if mind.trust >= 0:
            mind.confession_readiness = _clamp(mind.confession_readiness + 1, 0, 6)
    elif move_family == "accuse":
        mind.humiliation_risk = _clamp(mind.humiliation_risk + 2, 0, 6)
        mind.mask_integrity = _clamp(mind.mask_integrity - 1, 0, 6)
        mind.betrayal_readiness = _clamp(mind.betrayal_readiness + 1, 0, 6)
        mind.last_wound = "public_accusation"
    elif move_family == "ally_with":
        _update_commitment_target(mind, plan.route_target_ids[0] if plan.route_target_ids else target_id)
        mind.stance = "ally" if mind.trust >= 2 else "testing"
        if mind.trust >= 2:
            mind.control_need = _clamp(mind.control_need - 1, 0, 6)
    elif move_family == "betray":
        mind.trust = _clamp(mind.trust - 2, -3, 6)
        mind.betrayal_readiness = 0
        mind.stance = "hostile"
        mind.last_wound = "betrayed"
    elif move_family == "public_reveal":
        mind.mask_integrity = _clamp(mind.mask_integrity - 2, 0, 6)
        mind.humiliation_risk = _clamp(mind.humiliation_risk + 2, 0, 6)
        mind.pressure_load = _clamp(mind.pressure_load + 2, 0, 6)
        if any(trigger in " ".join(state.known_secret_ids + plan.route_target_ids) for trigger in ("taboo_secret", "旧案", "黑账", "录像")):
            mind.last_wound = "shame_triggered"
    elif move_family == "private_confession":
        mind.confession_readiness = 0
        mind.trust = _clamp(mind.trust + 1, -3, 6)
        mind.dependency = _clamp(mind.dependency + 1, 0, 6)
        mind.stance = "dependent" if mind.dependency >= 2 else "ally"
        _update_commitment_target(mind, plan.route_target_ids[0] if plan.route_target_ids else target_id)
    elif move_family == "jealousy_trigger":
        mind.jealousy = _clamp(mind.jealousy + 2, 0, 6)
        mind.tension = _clamp(mind.tension + 1, 0, 6)
    if relationship is not None:
        relationship.trust = mind.trust
        relationship.affection = mind.affection
        relationship.tension = mind.tension
        relationship.suspicion = mind.suspicion
        relationship.dependency = mind.dependency


def _derive_npc_scene_frame(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    character_id: str,
) -> NpcSceneFrame:
    member = next((item for item in plan.cast if item.character_id == character_id), None)
    mind = state.npc_mind_states[character_id]
    target_focus_id = mind.commitment_target_id or state.current_route_target_id
    if mind.betrayal_readiness >= 4 and mind.suspicion >= 3:
        scene_intent: str = "betray"
    elif mind.confession_readiness >= 4 and mind.trust >= 2:
        scene_intent = "confess"
    elif mind.protectiveness >= 3:
        scene_intent = "protect"
    elif mind.jealousy >= 4:
        scene_intent = "retaliate"
    elif mind.suspicion >= 3:
        scene_intent = "test"
    else:
        scene_intent = "deflect" if mind.pressure_load >= 4 else "seduce"
    if mind.mask_integrity <= 1:
        public_posture = "brittle"
    elif mind.humiliation_risk >= 4:
        public_posture = "cornered"
    elif mind.jealousy >= 4 or state.scene_frame == "public":
        public_posture = "performative"
    else:
        public_posture = "composed"
    most_feared_exposure = member.drama_profile.shame_trigger if member is not None else "被公开说破真正立场"
    reaction_priority = unique_preserve(
        [
            "save_face" if mind.humiliation_risk >= 3 else "",
            "keep_target_close" if target_focus_id else "",
            "bury_secret" if state.secret_exposure >= 2 else "",
            "punish_threat" if mind.betrayal_readiness >= 4 else "",
        ]
    )
    return NpcSceneFrame(
        character_id=character_id,
        scene_intent=scene_intent,  # type: ignore[arg-type]
        public_posture=public_posture,  # type: ignore[arg-type]
        target_focus_id=target_focus_id,
        most_feared_exposure=most_feared_exposure,
        line_about_to_break=(mind.mask_integrity <= 1 or mind.confession_readiness >= 4 or mind.betrayal_readiness >= 4),
        reaction_priority=[item for item in reaction_priority if item][:5],
    )


def _update_route(state: UrbanWorldState, target_id: str | None, move_family: RelationshipMoveFamily) -> None:
    if target_id is None or target_id not in state.route_scores_by_target:
        return
    route_delta = MOVE_DELTAS[move_family].get("route", 0)
    new_score = _clamp(state.route_scores_by_target.get(target_id, 0) + route_delta, -3, 6)
    state.route_scores_by_target[target_id] = new_score
    best_target_id = max(
        state.route_scores_by_target,
        key=lambda candidate: (state.route_scores_by_target[candidate], candidate),
    )
    state.current_route_target_id = best_target_id
    if move_family in {"ally_with", "private_confession"}:
        state.route_lock = _clamp(state.route_lock + 1, 0, 6)


def _resolve_lane_id_for_intent(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    suggestions: list[UrbanSuggestedAction],
) -> SuggestionLaneId:
    for suggestion in suggestions:
        if suggestion.move_family == intent.move_family and suggestion.target_id == intent.target_id:
            return suggestion.lane_id
    for suggestion in suggestions:
        if suggestion.move_family == intent.move_family:
            return suggestion.lane_id
    return _fallback_lane_id(intent.move_family)


def _lane_progress_gain(
    plan: CompiledPlayPlan,
    before_state: UrbanWorldState,
    after_state: UrbanWorldState,
    intent: UrbanTurnIntent,
) -> tuple[int, list[str]]:
    lane_id = intent.lane_id or _fallback_lane_id(intent.move_family)
    route_target_ids = _route_focus_ids(plan)
    tags = [f"{lane_id}_lane"]
    gain = 0
    target_id = intent.target_id
    if lane_id == "relationship" and target_id in route_target_ids and target_id in before_state.relationships and target_id in after_state.relationships:
        before_rel = before_state.relationships[target_id]
        after_rel = after_state.relationships[target_id]
        if (
            after_rel.affection > before_rel.affection
            or after_rel.trust > before_rel.trust
            or after_rel.dependency > before_rel.dependency
        ):
            gain = 1
            tags.append("relationship_progress")
    elif lane_id == "side" and target_id is not None:
        if (
            after_state.route_lock > before_state.route_lock
            or after_state.route_scores_by_target.get(target_id, 0) > before_state.route_scores_by_target.get(target_id, 0)
        ):
            gain = 1
            tags.append("side_progress")
    elif lane_id == "burst":
        if (
            after_state.scene_heat > before_state.scene_heat
            or after_state.secret_exposure > before_state.secret_exposure
            or len(after_state.public_event_ids) > len(before_state.public_event_ids)
        ):
            gain = 1
            tags.append("burst_progress")
    return gain, tags


def _increment_lane_counts(state: UrbanWorldState, lane_id: SuggestionLaneId, target_id: str | None) -> None:
    state.lane_counts[lane_id] = state.lane_counts.get(lane_id, 0) + 1
    if target_id is None:
        return
    target_counts = dict(state.lane_counts_by_target.get(target_id, {}))
    target_counts[lane_id] = target_counts.get(lane_id, 0) + 1
    state.lane_counts_by_target[target_id] = target_counts


def _apply_relationship_deltas(
    state: UrbanWorldState,
    relationship_id: str,
    deltas: dict[str, int],
) -> bool:
    relationship = state.relationships.get(relationship_id)
    if relationship is None:
        return False
    relationship.affection = _clamp(relationship.affection + int(deltas.get("affection", 0)), -3, 6)
    relationship.trust = _clamp(relationship.trust + int(deltas.get("trust", 0)), -3, 6)
    relationship.tension = _clamp(relationship.tension + int(deltas.get("tension", 0)), 0, 6)
    relationship.suspicion = _clamp(relationship.suspicion + int(deltas.get("suspicion", 0)), 0, 6)
    relationship.dependency = _clamp(relationship.dependency + int(deltas.get("dependency", 0)), 0, 6)
    return True


def _apply_global_delta(state: UrbanWorldState, key: str, delta: int) -> None:
    current = int(getattr(state, key))
    if key in {
        "scene_heat",
        "public_image",
        "relationship_debt_pressure",
        "public_wave_pressure",
        "secret_pressure",
        "npc_action_pressure",
        "secret_exposure",
        "route_lock",
    }:
        setattr(state, key, _clamp(current + int(delta), 0, 6))
    else:
        setattr(state, key, current + int(delta))


def _ensure_two_sided_cost_exchange(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    before_state: UrbanWorldState,
    state: UrbanWorldState,
    route: CostRouteRecord,
    min_payer_loss: int,
    min_beneficiary_gain: int,
) -> tuple[bool, bool]:
    payer_id = route.payer_character_id or (route.owner_character_ids[0] if route.owner_character_ids else None)
    beneficiary_id = route.beneficiary_character_id
    if beneficiary_id is None or beneficiary_id == payer_id:
        beneficiary_id = next(
            (
                item
                for item in unique_preserve(
                    [
                        *segment.rival_target_ids,
                        *segment.focus_target_ids,
                        *state.active_character_ids,
                        *plan.route_target_ids,
                    ]
                )
                if item and item != payer_id
            ),
            beneficiary_id,
        )
    route.payer_character_id = payer_id
    route.beneficiary_character_id = beneficiary_id
    if payer_id:
        route.owner_character_ids = unique_preserve([payer_id, *route.owner_character_ids])[:3]
    if beneficiary_id:
        route.target_character_ids = unique_preserve([beneficiary_id, *route.target_character_ids])[:3]

    payer_loss_committed = False
    if payer_id and payer_id in state.relationships and payer_id in before_state.relationships:
        before_rel = before_state.relationships[payer_id]
        after_rel = state.relationships[payer_id]
        existing_loss = max(
            0,
            int(after_rel.tension - before_rel.tension),
            int(after_rel.suspicion - before_rel.suspicion),
            int(before_rel.trust - after_rel.trust),
            int(before_rel.affection - after_rel.affection),
        )
        required_loss = max(0, int(min_payer_loss) - existing_loss)
        if required_loss > 0:
            after_rel.tension = _clamp(after_rel.tension + required_loss, 0, 6)
            payer_loss_committed = True
        else:
            payer_loss_committed = existing_loss > 0

    beneficiary_gain_committed = False
    if beneficiary_id and beneficiary_id in state.relationships and beneficiary_id in before_state.relationships:
        before_rel = before_state.relationships[beneficiary_id]
        after_rel = state.relationships[beneficiary_id]
        existing_gain = max(
            0,
            int(after_rel.trust - before_rel.trust),
            int(after_rel.affection - before_rel.affection),
            int(before_rel.tension - after_rel.tension),
            int(before_rel.suspicion - after_rel.suspicion),
            int(after_rel.dependency - before_rel.dependency),
        )
        required_gain = max(0, int(min_beneficiary_gain) - existing_gain)
        if required_gain > 0:
            after_rel.trust = _clamp(after_rel.trust + required_gain, -3, 6)
            beneficiary_gain_committed = True
        else:
            beneficiary_gain_committed = existing_gain > 0
    elif beneficiary_id and beneficiary_id != payer_id:
        state.route_lock = _clamp(state.route_lock + max(1, int(min_beneficiary_gain)), 0, 6)
        beneficiary_gain_committed = True

    return payer_loss_committed, beneficiary_gain_committed


def _stake_label(stake: str) -> str:
    return {
        "position": "位置",
        "reputation": "名声",
        "eligibility": "名额",
        "lineage": "顺位",
        "relationship": "关系",
        "narrative_control": "版本",
        "normal_life": "正常生活",
    }.get(stake, "退路")


def _derive_intent_feedback(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
) -> list[str]:
    feedback: list[str] = []
    members_by_id = {member.character_id: member for member in plan.cast}
    target_name = next((member.display_name for member in plan.cast if member.character_id == intent.target_id), "对方")
    for character_id in unique_preserve(list(state.active_character_ids) + list(state.last_turn_reaction_causes)):
        member = members_by_id.get(character_id)
        if member is None:
            continue
        tags = tuple(state.last_turn_reaction_causes.get(character_id, []))
        if not tags:
            continue
        intent_frame = member.strategic_intent
        name = member.display_name
        if "debt_due" in tags and intent_frame.debt_memory_bias in {"scorekeeping", "late_payback"}:
            feedback.append(f"{name}这回合明显是在借旧账动手。")
            continue
        if "covering_self" in tags or intent_frame.public_survival_mode == "self_preserve" and any(tag in tags for tag in ("public_hit", "interrupt_touched", "camera_pressure", "campus_spread")):
            feedback.append(f"{name}现在先护的是自己的{_stake_label(intent_frame.primary_stake)}。")
            continue
        if "cutting_others" in tags or intent.target_id in set(intent_frame.opportunism_target_ids) and any(tag in tags for tag in ("at_center_of_event", "public_hit", "was_cut_out")):
            feedback.append(f"{name}已经在等{target_name}继续失位，好顺手把局势变成自己的机会。")
            continue
        if "forced_alignment" in tags or "saw_player_side" in tags:
            feedback.append(f"{name}这回合已经把你记成站边的人。")
            continue
        if "kept_score" in tags:
            feedback.append(f"{name}没有当场发作，但这笔账她已经记下了。")
            continue
    return unique_preserve(feedback)[:4]


def _derive_reaction_causes(
    plan: CompiledPlayPlan,
    before_state: UrbanWorldState,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    segment: CompiledSegment,
) -> dict[str, list[str]]:
    causes: dict[str, list[str]] = {}
    members_by_id = {member.character_id: member for member in plan.cast}
    active_ids = unique_preserve(list(before_state.active_character_ids) + list(state.active_character_ids))
    triggered = state.last_turn_escalations[0] if state.last_turn_escalations else None

    def _latent_tags_for_shell() -> str:
        if plan.story_shell_id == "entertainment_scandal":
            return "camera_pressure"
        if plan.story_shell_id == "campus_romance":
            return "campus_spread"
        return "crowd_pressure"

    for character_id in active_ids:
        tags: list[str] = []
        member = members_by_id.get(character_id)
        intent_frame = member.strategic_intent if member is not None else None
        rel_delta = dict(state.last_turn_relationship_deltas.get(character_id) or {})
        if character_id == intent.target_id:
            if rel_delta.get("trust", 0) < 0 or rel_delta.get("tension", 0) > 0:
                tags.append("public_hit")
            if intent.move_family in {"comfort", "ally_with", "private_confession"} and (rel_delta.get("trust", 0) > 0 or rel_delta.get("affection", 0) > 0):
                tags.append("protected_by_player")
            if state.last_turn_public_event_text or (triggered is not None and triggered.kind in {"public_wave", "secret_pressure"}):
                tags.append("at_center_of_event")
        else:
            if rel_delta.get("suspicion", 0) > 0 or rel_delta.get("tension", 0) > 0:
                tags.append("saw_player_side")
            if rel_delta.get("trust", 0) < 0:
                tags.append("was_cut_out")
        if triggered is not None:
            if triggered.kind == "public_wave":
                tags.append(_latent_tags_for_shell())
                if character_id in set(triggered.target_character_ids) or character_id in triggered.relationship_deltas:
                    tags.append("chain_touched")
            elif triggered.kind == "relationship_debt":
                if character_id in set(triggered.stake_character_ids):
                    tags.extend(["debt_due", "kept_score"])
                if character_id in set(triggered.target_character_ids):
                    tags.extend(["debt_due", "owes_debt"])
            elif triggered.kind == "secret_pressure":
                if character_id in set(triggered.target_character_ids):
                    tags.extend(["public_hit", "at_center_of_event"])
            elif triggered.kind == "npc_action":
                if triggered.actor_character_id == character_id:
                    if intent_frame is not None and intent_frame.public_survival_mode in {"self_preserve", "claim_narrative", "hold_face"}:
                        tags.append("covering_self")
                    if intent_frame is not None and intent_frame.public_survival_mode == "cut_off":
                        tags.append("cutting_others")
                    if intent_frame is not None and intent_frame.public_survival_mode == "align_early":
                        tags.append("forced_alignment")
                if character_id in triggered.relationship_deltas:
                    tags.append("interrupt_touched")
                if character_id in set(triggered.target_character_ids):
                    tags.append("was_cut_out")
        for event in state.latent_events:
            if event.kind == "relationship_debt":
                if character_id in set(event.stake_character_ids):
                    tags.append("kept_score")
                if character_id in set(event.target_character_ids):
                    tags.append("owes_debt")
            elif event.kind == "public_wave":
                if character_id in set(event.stake_character_ids) or character_id in set(event.target_character_ids):
                    tags.append(_latent_tags_for_shell())
            elif event.kind == "secret_pressure":
                if character_id in set(event.target_character_ids):
                    tags.append("at_center_of_event")
            elif event.kind == "npc_action":
                if event.actor_character_id == character_id and event.status == "primed":
                    if intent_frame is not None and intent_frame.public_survival_mode == "cut_off":
                        tags.append("cutting_others")
                    else:
                        tags.append("covering_self")
                if character_id in set(event.target_character_ids):
                    tags.append("was_cut_out")
        if state.route_lock > before_state.route_lock and character_id != intent.target_id and character_id in set(segment.rival_target_ids):
            tags.append("forced_alignment")
        if intent_frame is not None:
            if intent_frame.loss_trigger == "public_humiliation" and any(tag in tags for tag in ("public_hit", "camera_pressure", "campus_spread")):
                tags.append("intent_loss_triggered")
            if intent_frame.loss_trigger == "seat_shift" and any(tag in tags for tag in ("was_cut_out", "forced_alignment")):
                tags.append("intent_loss_triggered")
            if intent_frame.loss_trigger == "version_loss" and any(tag in tags for tag in ("camera_pressure", "covering_self", "interrupt_touched", "chain_touched")):
                tags.append("intent_loss_triggered")
            if intent_frame.loss_trigger == "peer_rejection" and any(tag in tags for tag in ("campus_spread", "forced_alignment")):
                tags.append("intent_loss_triggered")
            if intent_frame.loss_trigger == "route_rejection" and any(tag in tags for tag in ("saw_player_side", "was_cut_out", "protected_by_player")):
                tags.append("intent_loss_triggered")
            if intent_frame.loss_trigger == "debt_reopened" and any(tag in tags for tag in ("debt_due", "kept_score", "owes_debt")):
                tags.append("intent_loss_triggered")
            if intent.target_id in set(intent_frame.opportunism_target_ids) and any(tag in tags for tag in ("public_hit", "at_center_of_event", "was_cut_out")):
                tags.append("opportunity_window")
            if intent.target_id in set(intent_frame.protect_target_ids) and "protected_by_player" in tags:
                tags.append("protective_stake")
            if intent.target_id in set(intent_frame.sacrifice_target_ids) and any(tag in tags for tag in ("forced_alignment", "was_cut_out", "public_hit")):
                tags.append("sacrifice_window")
        if tags:
            causes[character_id] = unique_preserve(tags)[:6]
    return causes


def apply_turn_resolution(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    *,
    micro_sim: _NpcMicroSimResult | None = None,
) -> tuple[UrbanWorldState, list[str]]:
    suggestions = build_suggested_actions(plan, state)
    if intent.lane_id is None:
        intent.lane_id = _resolve_lane_id_for_intent(plan, state, intent, suggestions)
    before_state = state.model_copy(deep=True)
    state.last_turn_revealed_secret_ids = []
    segment = _resolved_segment(plan, state)
    semantic_plan = TurnSemanticPlan(
        turn_index=state.turn_index + 1,
        segment_id=segment.segment_id,
        segment_role=segment.segment_role,
        question_plan=QuestionPlanner.seed(plan=plan, segment=segment, state=state),
        style_plan=StylePlanner.seed(plan=plan, segment=segment, state=state),
        summary="语义总线已建立。",
    )
    prioritized_unresolved_cost = _find_unresolved_cost_by_id(
        state,
        semantic_plan.question_plan.prioritized_cost_id,
    )
    deltas = MOVE_DELTAS[intent.move_family]
    state.turn_index += 1
    state.scene_heat = _clamp(state.scene_heat + deltas.get("heat", 0) + (1 if intent.scene_frame == "public" else 0), 0, 6)
    state.public_image = _clamp(state.public_image + deltas.get("public_image", 0), 0, 6)
    state.secret_exposure = _clamp(state.secret_exposure + deltas.get("secret_exposure", 0), 0, 6)
    state.route_lock = _clamp(state.route_lock + deltas.get("route_lock", 0), 0, 6)
    _apply_relationship_delta(state, intent.target_id, intent.move_family)
    _update_route(state, intent.target_id, intent.move_family)
    _apply_npc_mind_delta(plan, state, intent.target_id, intent.move_family, intent.scene_frame)
    # --- Semantic effect resolution (additive on top of MOVE_DELTAS) ---
    from rpg_backend.play_v2.hook_engine import build_hook_context, build_hook_callback_question, get_hook_callback_hook_id, is_hook_callback_item

    hook_context = build_hook_context(
        state,
        actor_id=str(getattr(state, "protagonist_id", None) or "player"),
        target_id=intent.target_id,
    )
    semantic_result = resolve_semantic_effects(
        plan,
        state,
        getattr(intent, "semantic_effects", []),
        hook_context=hook_context,
        move_family=intent.move_family,
    )
    for key, delta in semantic_result["global_deltas"].items():
        _apply_global_delta(state, key, int(delta))
    for rel_id, rel_deltas in semantic_result["relationship_deltas"].items():
        _apply_relationship_deltas(state, rel_id, rel_deltas)
    reducer_result = HookLifecycleReducer.apply(
        plan=plan,
        segment=segment,
        state=state,
        intent=intent,
        semantic_result=semantic_result,
    )
    if reducer_result.changed_hook_ids:
        hook_tags = [f"hook_transition:{hook_id}" for hook_id in reducer_result.changed_hook_ids]
        state.last_turn_tags = unique_preserve([*state.last_turn_tags, *hook_tags])
    consequence_semantic_tags = list(semantic_result.get("tags", []))
    directed_outcome = EventDirector.direct_turn_outcome(
        plan=plan,
        segment=segment,
        intent=intent,
        state=state,
    )
    for key, delta in directed_outcome.collateral_global_deltas.items():
        _apply_global_delta(state, key, int(delta))
    affected_relationship_ids = []
    for relationship_id, deltas in directed_outcome.collateral_relationship_deltas.items():
        if _apply_relationship_deltas(state, relationship_id, deltas):
            affected_relationship_ids.append(relationship_id)
    cost_route = PayoffPlanner.plan_cost_route(
        plan=plan,
        state=state,
        intent=intent,
        segment=segment,
    )
    cost_fallback_applied = False
    if not cost_route.immediate_global_deltas and not cost_route.immediate_relationship_deltas:
        policy = plan.semantic_strategy_pack.cost_routing_matrix
        cost_fallback_applied = True
        if intent.target_id:
            cost_route.immediate_relationship_deltas[intent.target_id] = {
                policy.fallback_target_relationship_delta_key: policy.fallback_target_relationship_delta_value,
            }
        else:
            cost_route.immediate_global_deltas[policy.fallback_global_delta_key] = policy.fallback_global_delta_value
    for key, delta in cost_route.immediate_global_deltas.items():
        _apply_global_delta(state, key, int(delta))
    for relationship_id, deltas in cost_route.immediate_relationship_deltas.items():
        if _apply_relationship_deltas(state, relationship_id, deltas):
            affected_relationship_ids.append(relationship_id)
    callback_item = PayoffPlanner.build_callback(
        plan=plan,
        state=state,
        intent=intent,
        segment=segment,
        route=cost_route,
    )
    if callback_item is not None:
        cost_route.deferred_callback_id = callback_item.callback_id
    unresolved_cost = PayoffPlanner.build_unresolved_cost(
        state=state,
        segment=segment,
        route=cost_route,
        callback_item=callback_item,
    )
    if unresolved_cost is not None:
        _upsert_unresolved_cost(state=state, unresolved_cost=unresolved_cost)
    _refresh_unresolved_cost_ladder(
        plan=plan,
        segment=segment,
        state=state,
    )
    if semantic_plan.question_plan.prioritized_cost_id is not None:
        refreshed_cost = _find_unresolved_cost_by_id(state, semantic_plan.question_plan.prioritized_cost_id)
        if refreshed_cost is not None:
            prioritized_unresolved_cost = refreshed_cost
    state.last_turn_cost_route = cost_route
    affected_relationship_ids.extend(list(cost_route.immediate_relationship_deltas.keys()))
    if callback_item is not None:
        state.callback_queue = [*state.callback_queue, callback_item][-8:]
    callback_queue_before_resolution = [item.model_copy(deep=True) for item in state.callback_queue]
    (
        due_cost_primary_eligible,
        cost_return_primary_applies,
        secondary_due_cost_pressure,
        due_cost_retry_bias,
    ) = _cost_return_primary_applies(
        plan=plan,
        segment=segment,
        state=state,
        intent=intent,
        prioritized_cost=prioritized_unresolved_cost,
    )
    latent_outcome = LatentEventEngine.resolve_turn_latent_events(
        plan=plan,
        segment=segment,
        intent=intent,
        before_state=before_state,
        state=state,
        prioritized_cost=prioritized_unresolved_cost,
        prefer_cost_return_primary_driver=cost_return_primary_applies,
        suppress_cost_return_primary_driver=secondary_due_cost_pressure,
        cost_return_retry_bias=secondary_due_cost_pressure,
        cost_return_retry_bias_steps=due_cost_retry_bias,
        secondary_due_cost_pressure=secondary_due_cost_pressure,
    )
    triggered_record = latent_outcome.triggered_record
    if triggered_record is not None:
        for key, delta in triggered_record.global_deltas.items():
            _apply_global_delta(state, key, int(delta))
        for relationship_id, deltas in triggered_record.relationship_deltas.items():
            if _apply_relationship_deltas(state, relationship_id, deltas):
                affected_relationship_ids.append(relationship_id)
    scene_question_state, question_forced_advance, question_advance_reason = QuestionPlanner.advance(
        plan=plan,
        segment=segment,
        state=state,
        triggered_kind=triggered_record.kind if triggered_record is not None else None,
        key_segment_conversion=bool(getattr(latent_outcome, "key_segment_conversion", False)),
    )
    state.last_turn_scene_question_state = scene_question_state
    propagation_edge = pick_shell_edge(
        shell_id=plan.story_shell_id,
        latent_kind=triggered_record.kind if triggered_record is not None else None,
        turn_index=state.turn_index,
        segment_role=segment.segment_role,
        graph_policy=plan.semantic_strategy_pack.shell_propagation_graph,
        priority_policy=plan.semantic_strategy_pack.propagation_priority_policy,
    )
    state.last_turn_propagation_edge = propagation_edge
    _increment_lane_counts(state, intent.lane_id, intent.target_id)
    consequence_tags = [
        intent.move_family,
        intent.scene_frame,
        f"intent_compile:{intent.intent_compile_source}",
        f"control_source:{intent.control_source}",
    ]
    if intent.deviation_type != "none":
        consequence_tags.append(f"deviation_type:{intent.deviation_type}")
    lane_progress_gain, lane_tags = _lane_progress_gain(plan, before_state, state, intent)
    consequence_tags.extend(lane_tags)
    consequence_tags.extend(consequence_semantic_tags)
    consequence_tags.extend(directed_outcome.event_tags)
    if triggered_record is not None and triggered_record.kind is not None:
        consequence_tags.append(f"latent:{triggered_record.kind}:triggered")
    consequence_tags.extend(latent_outcome.latent_ops)
    if getattr(latent_outcome, "top_event_kind", None) is not None and not any(
        tag.startswith(f"latent:{getattr(latent_outcome, 'top_event_kind')}:")
        for tag in latent_outcome.latent_ops
    ):
        transition = str(getattr(latent_outcome, "top_event_transition", "none") or "none")
        transition_tag = {
            "rising": f"latent:{getattr(latent_outcome, 'top_event_kind')}:rising",
            "cooling": f"latent:{getattr(latent_outcome, 'top_event_kind')}:cooled",
            "triggered": f"latent:{getattr(latent_outcome, 'top_event_kind')}:triggered",
        }.get(transition)
        if transition_tag is not None:
            consequence_tags.append(transition_tag)
    consequence_tags.extend(latent_outcome.control_resolution.tags)
    if propagation_edge is not None:
        consequence_tags.append(f"propagation:{propagation_edge.edge_id}")
    if scene_question_state.status == "resolved":
        consequence_tags.append("scene_question:resolved")
    elif scene_question_state.status == "flip":
        consequence_tags.append("scene_question:flip")
    if question_forced_advance:
        consequence_tags.append("scene_question:forced_advance")
    secondary_signal = False
    if intent.target_id in set(segment.focus_target_ids + segment.rival_target_ids):
        secondary_signal = True
        consequence_tags.append("focus_hit")
    if intent.move_family in set(segment.move_priorities[:2]):
        secondary_signal = True
        consequence_tags.append("priority_move")
    state.segment_progress = _clamp(
        state.segment_progress + lane_progress_gain + (1 if secondary_signal else 0),
        0,
        _segment_progress_cap(segment),
    )
    if intent.move_family == "betray":
        state.betrayal_ids = unique_preserve(state.betrayal_ids + [segment.segment_id])[:8]
    if intent.move_family == "ally_with":
        state.promise_ids = unique_preserve(state.promise_ids + [segment.segment_id])[:8]
    if intent.scene_frame == "public" or directed_outcome.forced_public_event:
        state.public_event_ids = unique_preserve(state.public_event_ids + [segment.segment_id])[:8]
    if directed_outcome.forced_public_event:
        state.irreversible_flags = unique_preserve(state.irreversible_flags + [f"public_event:{segment.segment_id}"])[:8]
    if directed_outcome.no_return_text:
        state.irreversible_flags = unique_preserve(state.irreversible_flags + [f"no_return:{segment.segment_id}"])[:8]
    if triggered_record is not None and triggered_record.kind is not None:
        state.irreversible_flags = unique_preserve(state.irreversible_flags + [f"latent:{triggered_record.kind}:{segment.segment_id}"])[:8]
    state.last_turn_latent_ops = list(latent_outcome.latent_ops[:6])
    state.last_turn_latent_feedback = list(latent_outcome.latent_feedback[:4])
    if secondary_due_cost_pressure and semantic_plan.question_plan.prioritized_cost_id is not None:
        due_cost_line = trim_text(
            "你这回合先按了显式控雷，这笔到期账暂时退到次驱动，但下一拍会更抢主线。",
            220,
        )
        state.last_turn_latent_feedback = unique_preserve([due_cost_line, *state.last_turn_latent_feedback])[:4]
        consequence_tags.append("cost_return:secondary_due_pressure")
    state.last_turn_escalations = [triggered_record] if triggered_record is not None else []
    state.last_turn_control_resolution = latent_outcome.control_resolution
    callback_status = latent_outcome.callback_status.model_copy(deep=True)
    if callback_item is not None:
        callback_status.created_count = _clamp(callback_status.created_count + 1, 0, 8)
    callback_status.pending_count = len([item for item in state.callback_queue if item.status == "pending"])
    fired_hook_callback_tag: str | None = None
    fired_hook_scene_question: str | None = None
    if callback_status.triggered_callback_id:
        fired_callback_item = next(
            (item for item in callback_queue_before_resolution if item.callback_id == callback_status.triggered_callback_id),
            None,
        )
        if is_hook_callback_item(fired_callback_item):
            hook_callback_kind = str(getattr(fired_callback_item, "payoff_kind", "") or "")
            hook_id = get_hook_callback_hook_id(fired_callback_item)
            if hook_id:
                fired_hook_callback_tag = f"callback_fired:{hook_callback_kind}:{hook_id}"
            fired_hook_scene_question = build_hook_callback_question(fired_callback_item)
    if not callback_status.summary:
        if callback_status.triggered_callback_id:
            callback_status.summary = "有一笔延迟回调在本回合到期并触发。"
        elif callback_status.pending_count > 0:
            callback_status.summary = "仍有回调在后台排队发酵。"
        else:
            callback_status.summary = "本回合没有回调触发。"
    state.last_turn_callback_status = callback_status
    _reconcile_unresolved_costs(
        state=state,
        scene_question_state=scene_question_state,
        callback_status=callback_status,
        triggered_record=triggered_record,
    )
    _refresh_unresolved_cost_ladder(
        plan=plan,
        segment=segment,
        state=state,
    )
    causal_outcome = CausalContractEngine.enforce(
        plan=plan,
        segment=segment,
        state=state,
        triggered_record=triggered_record,
        callback_status=callback_status,
        payoff_plan=None,
    )
    consequence_tags.extend(list(causal_outcome.tags))
    required_turn_tags: list[str] = []
    causal_required_tags = [tag for tag in consequence_tags if isinstance(tag, str) and tag.startswith("causal:")][:3]
    required_turn_tags.extend(causal_required_tags)
    hook_transition_tags = [
        tag
        for tag in list(state.last_turn_tags)
        if isinstance(tag, str) and tag.startswith("hook_transition:")
    ][:4]
    required_turn_tags.extend(hook_transition_tags)
    if fired_hook_callback_tag:
        required_turn_tags.append(fired_hook_callback_tag)
    state.last_turn_tags = _finalize_last_turn_tags(
        latent_ops=list(latent_outcome.latent_ops),
        consequence_tags=consequence_tags,
        required_tags=required_turn_tags,
    )
    state.latent_radar = list(latent_outcome.latent_radar[:4])
    state.last_turn_public_event_text = directed_outcome.public_event_text or (
        triggered_record.text if triggered_record is not None and triggered_record.kind in {"public_wave", "secret_pressure"} else None
    )
    state.last_turn_pain_text = directed_outcome.pain_text
    state.last_turn_no_return_text = (
        triggered_record.text if triggered_record is not None and triggered_record.kind in {"relationship_debt", "npc_action"} else directed_outcome.no_return_text
    )
    state.last_turn_consequences = unique_preserve(
        [
            item
            for item in [
                directed_outcome.public_event_text,
                triggered_record.text if triggered_record is not None else None,
                directed_outcome.pain_text,
                directed_outcome.no_return_text,
                latent_outcome.control_resolution.summary,
                *state.last_turn_causal_receipts,
                *state.last_turn_latent_feedback,
            ]
            if item
        ]
    )[:8]
    if fired_hook_scene_question:
        state.last_turn_consequences = unique_preserve([fired_hook_scene_question, *state.last_turn_consequences])[:8]
    cost_visibility_rule = plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id.get(segment.segment_id)
    enforce_two_sided_exchange = bool(
        cost_visibility_rule is not None
        and cost_visibility_rule.require_two_sided_exchange
        and (
            cost_return_primary_applies
            or semantic_plan.question_plan.prioritized_cost_id is not None
        )
    )
    if enforce_two_sided_exchange and state.last_turn_cost_route is not None:
        payer_loss_committed, beneficiary_gain_committed = _ensure_two_sided_cost_exchange(
            plan=plan,
            segment=segment,
            before_state=before_state,
            state=state,
            route=state.last_turn_cost_route,
            min_payer_loss=int(cost_visibility_rule.min_payer_loss),
            min_beneficiary_gain=int(cost_visibility_rule.min_beneficiary_gain),
        )
        if payer_loss_committed and beneficiary_gain_committed:
            consequence_tags.append("cost_return:two_sided_exchange")
            state.last_turn_consequences = unique_preserve(
                [
                    "这笔到期账已经在主线里兑现成双侧交换：有人先受损，也有人先拿到缓冲。",
                    *state.last_turn_consequences,
                ]
            )[:8]
    state.last_turn_global_deltas = {
        key: after - before
        for key, before, after in (
            ("scene_heat", before_state.scene_heat, state.scene_heat),
            ("public_image", before_state.public_image, state.public_image),
            ("relationship_debt_pressure", before_state.relationship_debt_pressure, state.relationship_debt_pressure),
            ("public_wave_pressure", before_state.public_wave_pressure, state.public_wave_pressure),
            ("secret_pressure", before_state.secret_pressure, state.secret_pressure),
            ("npc_action_pressure", before_state.npc_action_pressure, state.npc_action_pressure),
            ("secret_exposure", before_state.secret_exposure, state.secret_exposure),
            ("route_lock", before_state.route_lock, state.route_lock),
        )
        if after != before
    }
    changed_relationship_ids = unique_preserve(
        [item for item in [intent.target_id, *affected_relationship_ids] if item]
    )
    state.last_turn_relationship_deltas = {
        relationship_id: {
            key: after - before
            for key, before, after in (
                ("affection", before_state.relationships.get(relationship_id).affection if relationship_id in before_state.relationships else 0, state.relationships.get(relationship_id).affection if relationship_id in state.relationships else 0),
                ("trust", before_state.relationships.get(relationship_id).trust if relationship_id in before_state.relationships else 0, state.relationships.get(relationship_id).trust if relationship_id in state.relationships else 0),
                ("tension", before_state.relationships.get(relationship_id).tension if relationship_id in before_state.relationships else 0, state.relationships.get(relationship_id).tension if relationship_id in state.relationships else 0),
                ("suspicion", before_state.relationships.get(relationship_id).suspicion if relationship_id in before_state.relationships else 0, state.relationships.get(relationship_id).suspicion if relationship_id in state.relationships else 0),
                ("dependency", before_state.relationships.get(relationship_id).dependency if relationship_id in before_state.relationships else 0, state.relationships.get(relationship_id).dependency if relationship_id in state.relationships else 0),
            )
            if after != before
        }
        for relationship_id in changed_relationship_ids
        if relationship_id in state.relationships and relationship_id in before_state.relationships
    }
    state.last_turn_reaction_causes = _derive_reaction_causes(
        plan=plan,
        before_state=before_state,
        state=state,
        intent=intent,
        segment=segment,
    )
    micro_bias_by_character: dict[str, int] = {}
    micro_reason_by_character: dict[str, str] = {}
    if micro_sim is not None:
        for rank, choice in enumerate(micro_sim.choices):
            bonus = 2 if choice.character_id == micro_sim.recommended_actor_id else 1
            if rank >= 2:
                bonus = max(1, bonus - 1)
            micro_bias_by_character[choice.character_id] = max(int(micro_bias_by_character.get(choice.character_id, 0)), int(bonus))
            if choice.reason_family in {"loss_position", "self_preserve", "old_debt", "opportunity_window", "blame_shift", "mixed"}:
                micro_reason_by_character[choice.character_id] = choice.reason_family
            tags = list(state.last_turn_reaction_causes.get(choice.character_id, []))
            tags.append("micro_sim_candidate")
            if choice.character_id == micro_sim.recommended_actor_id:
                tags.append("micro_sim_actor")
            if choice.reason_family == "opportunity_window":
                tags.append("opportunity_window")
            elif choice.reason_family == "old_debt":
                tags.extend(["kept_score", "debt_due"])
            elif choice.reason_family == "blame_shift":
                tags.extend(["sacrifice_window", "forced_alignment", "blame_shift"])
            elif choice.reason_family in {"self_preserve", "loss_position"}:
                tags.append("intent_loss_triggered")
            state.last_turn_reaction_causes[choice.character_id] = unique_preserve(tags)[:8]
        consequence_tags.append(f"micro_sim:{micro_sim.source}")
        if micro_sim.recommended_actor_id:
            consequence_tags.append(f"micro_sim_actor:{micro_sim.recommended_actor_id}")
    if propagation_edge is not None:
        for character_id in state.active_character_ids:
            tags = list(state.last_turn_reaction_causes.get(character_id, []))
            tags = unique_preserve([*tags, f"prop_edge:{propagation_edge.edge_id}", f"prop_signal:{propagation_edge.signal_family}"])[:8]
            if tags:
                state.last_turn_reaction_causes[character_id] = tags
    utility_map, utility_top, stake_plan = StakePlanner.compute_utility(
        plan=plan,
        segment=segment,
        before_state=before_state,
        state=state,
        micro_bias_by_character=micro_bias_by_character,
        micro_reason_by_character=micro_reason_by_character,
    )
    state.last_turn_utility_delta_by_character = utility_map
    state.last_turn_intent_feedback = _derive_intent_feedback(plan, state, intent)
    state.last_turn_consequences = unique_preserve(
        [
            item
            for item in [
                *state.last_turn_consequences,
                unresolved_cost.summary if unresolved_cost is not None else None,
                micro_sim.summary if micro_sim is not None else None,
                *state.last_turn_latent_feedback,
                *state.last_turn_intent_feedback,
                state.last_turn_scene_question_state.summary if state.last_turn_scene_question_state is not None else None,
                state.last_turn_callback_status.summary if state.last_turn_callback_status is not None else None,
            ]
            if item
        ]
    )[:8]
    prioritized_cost_for_event = _find_unresolved_cost_by_id(
        state,
        semantic_plan.question_plan.prioritized_cost_id,
    ) or prioritized_unresolved_cost
    event_plan = EventPlanner.finalize(
        latent_outcome=latent_outcome,
        triggered_record=triggered_record,
        causal_pending_count=causal_outcome.pending_count,
        causal_resolved_this_turn=causal_outcome.resolved_this_turn,
        causal_fail_safe_applied=causal_outcome.fail_safe_applied,
        stale_escalations_this_turn=causal_outcome.stale_escalations_this_turn,
        prioritized_cost=prioritized_cost_for_event,
        due_cost_primary_eligible=due_cost_primary_eligible,
        due_cost_forces_primary_driver_applied=cost_return_primary_applies,
        cost_ladder_stage=int(prioritized_cost_for_event.ladder_stage) if prioritized_cost_for_event is not None else 0,
        player_override_applied=(
            due_cost_primary_eligible and secondary_due_cost_pressure
        ),
        secondary_due_cost_pressure=secondary_due_cost_pressure,
    )
    payoff_plan = PayoffPlanner.finalize(
        route=cost_route,
        callback_item=callback_item,
        global_delta_keys=list(state.last_turn_global_deltas.keys()),
        relationship_delta_ids=list(state.last_turn_relationship_deltas.keys()),
        fallback_applied=cost_fallback_applied or causal_outcome.fail_safe_applied,
        unresolved_cost=unresolved_cost,
        control_signature_action=(
            state.last_turn_control_resolution.action_type
            if state.last_turn_control_resolution is not None
            else "none"
        ),
    )
    cost_binding_rule = plan.semantic_strategy_pack.cost_narrative_binding_policy.by_segment_id.get(segment.segment_id)
    cost_visibility_rule = plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id.get(segment.segment_id)
    style_force_cost_subject = bool(
        (
            event_plan.primary_driver == "cost_return"
            or semantic_plan.question_plan.prioritized_cost_id is not None
        )
        and (
            (cost_binding_rule is not None and cost_binding_rule.require_main_clause_payer_beneficiary)
            or (
                get_settings().play_v2_policy_cost_visibility_enabled
                and cost_visibility_rule is not None
                and cost_visibility_rule.require_main_clause_subject
            )
            or (
                get_settings().play_v2_policy_question_progress_v2_enabled
                and semantic_plan.question_plan.prioritized_cost_id is not None
            )
        )
    )
    style_summary = semantic_plan.style_plan.summary
    if style_force_cost_subject:
        style_summary = trim_text("文风落地目标：主句第一分句先回答谁付账/谁接锅/谁被追责。", 220)
    style_plan = semantic_plan.style_plan.model_copy(
        update={
            "force_main_clause_cost_subject": style_force_cost_subject,
            "payer_character_id": payoff_plan.payer_character_id,
            "beneficiary_character_id": payoff_plan.beneficiary_character_id,
            "cost_subject_focus": (
                semantic_plan.question_plan.prioritized_cost_focus
                or cost_route.scene_question_focus
            ),
            "summary": style_summary,
        }
    )
    semantic_plan = semantic_plan.model_copy(
        update={
            "question_plan": semantic_plan.question_plan.model_copy(
                update={
                    "final_status": scene_question_state.status,
                    "forced_advance": question_forced_advance,
                    "advance_reason": question_advance_reason,
                    "resolved_by": scene_question_state.resolved_by,
                    "summary": trim_text(
                        (
                            f"问题推进：{semantic_plan.question_plan.before_status} -> {scene_question_state.status}。"
                            if not question_forced_advance
                            else f"问题推进：{semantic_plan.question_plan.before_status} -> {scene_question_state.status}（强制推进:{question_advance_reason or 'fallback'}）。"
                        ),
                        220,
                    ),
                }
            ),
            "stake_plan": stake_plan,
            "event_plan": event_plan,
            "payoff_plan": payoff_plan,
            "style_plan": style_plan,
        }
    )
    semantic_plan.summary = trim_text(
        " ".join(
            [
                semantic_plan.question_plan.summary,
                semantic_plan.stake_plan.summary,
                semantic_plan.event_plan.summary,
                semantic_plan.payoff_plan.summary,
                semantic_plan.style_plan.summary,
            ]
        ),
        220,
    )
    state.last_turn_semantic_plan = semantic_plan
    state.last_turn_story_debug_summary = _story_debug_summary(state)
    return state, consequence_tags


def _load_segment_scene(state: UrbanWorldState, segment: CompiledSegment) -> None:
    state.segment_id = segment.segment_id
    state.segment_enter_turn_index = int(state.turn_index)
    state.scene_frame = _scene_frame_for_segment(segment)
    state.venue_id = segment.venue_id
    state.active_character_ids = unique_preserve((segment.focus_target_ids + segment.rival_target_ids)[:3])[:3]
    state.witness_pressure = 2 if state.scene_frame != "private" else 1


def _ending_lane_count(state: UrbanWorldState, lane_id: SuggestionLaneId | None, target_id: str | None) -> int:
    if lane_id is None:
        return 0
    if target_id is None:
        return int(state.lane_counts.get(lane_id, 0))
    return int(state.lane_counts_by_target.get(target_id, {}).get(lane_id, 0))


def _ending_target_id(state: UrbanWorldState, ending_target_id: str | None) -> str | None:
    return ending_target_id or state.current_route_target_id


def _ending_target_state(state: UrbanWorldState, ending_target_id: str | None) -> UrbanRelationshipTargetState | None:
    resolved_target_id = _ending_target_id(state, ending_target_id)
    if not resolved_target_id:
        return None
    return state.relationships.get(resolved_target_id)


def _ending_is_eligible(
    plan: CompiledPlayPlan, state: UrbanWorldState, ending, *, late_game_factor: float = 1.0
) -> bool:
    if ending.terminal_segment_id != state.segment_id:
        return False
    segment = _current_segment(plan, state)
    if _current_segment_turns(state) < _segment_turn_floor(segment):
        return False
    if ending.target_id and ending.target_id != state.current_route_target_id:
        return False

    factor = max(0.0, min(1.0, late_game_factor))

    def _scaled_min(original_min: int) -> int:
        return max(0, int(original_min * factor))

    if ending.lane_id is not None and _ending_lane_count(state, ending.lane_id, ending.target_id) < _scaled_min(ending.min_lane_count):
        return False
    if state.route_lock < _scaled_min(ending.min_route_lock):
        return False
    if state.scene_heat < _scaled_min(ending.min_scene_heat):
        return False
    if ending.max_scene_heat is not None and state.scene_heat > ending.max_scene_heat:
        return False
    if state.secret_exposure < _scaled_min(ending.min_secret_exposure):
        return False
    if ending.max_secret_exposure is not None and state.secret_exposure > ending.max_secret_exposure:
        return False
    if len(state.public_event_ids) < _scaled_min(ending.min_public_events):
        return False
    if ending.max_public_image is not None and state.public_image > ending.max_public_image:
        return False
    target_state = _ending_target_state(state, ending.target_id)
    if target_state is not None:
        if target_state.affection < _scaled_min(ending.min_affection) or target_state.trust < _scaled_min(ending.min_trust):
            return False
        if target_state.dependency < _scaled_min(ending.min_dependency):
            return False
        if ending.max_suspicion is not None and target_state.suspicion > ending.max_suspicion:
            return False
    if ending.required_secret_ids and factor > 0.5:
        if any(secret_id not in set(state.known_secret_ids) for secret_id in ending.required_secret_ids):
            return False
    return True


def _ending_candidate_score(state: UrbanWorldState, ending) -> int:  # noqa: ANN001
    target_state = _ending_target_state(state, ending.target_id)
    lane_score = _ending_lane_count(state, ending.lane_id, ending.target_id) * 3 if ending.lane_id else 0
    if ending.lane_id == "relationship" and target_state is not None:
        return lane_score + target_state.affection * 2 + target_state.trust * 2 + target_state.dependency - target_state.suspicion
    if ending.lane_id == "side" and target_state is not None:
        target_id = _ending_target_id(state, ending.target_id) or ""
        return lane_score + state.route_lock * 2 + state.route_scores_by_target.get(target_id, 0) * 2 + target_state.trust
    if ending.lane_id == "burst":
        return lane_score + state.scene_heat * 2 + state.secret_exposure * 2 + len(state.public_event_ids)
    if ending.ending_id == "pyrrhic_control" and target_state is not None:
        return state.route_lock * 2 + state.scene_heat + state.secret_exposure + max(0, 3 - state.public_image) + target_state.trust
    return state.scene_heat + state.secret_exposure


def judge_ending(plan: CompiledPlayPlan, state: UrbanWorldState) -> tuple[bool, str | None, str | None]:
    if state.status == "completed":
        return True, state.ending_id, state.ending_summary

    progress_ratio = state.turn_index / max(plan.max_turns, 1)
    if progress_ratio >= 0.8:
        late_game_factor = max(0.0, 1.0 - (progress_ratio - 0.8) / 0.2)
    else:
        late_game_factor = 1.0

    candidates = []
    for ending in plan.ending_matrix.endings:
        if ending.ending_id == "burned_alone":
            continue
        if not _ending_is_eligible(plan, state, ending, late_game_factor=late_game_factor):
            continue
        candidates.append((_ending_candidate_score(state, ending), ending))
    if candidates:
        _, ending = max(candidates, key=lambda item: (item[0], item[1].ending_id))
        state.status = "completed"
        state.ending_id = ending.ending_id
        state.ending_summary = ending.summary
        return True, ending.ending_id, ending.summary
    segment = _current_segment(plan, state)
    if (
        segment.is_terminal
        and state.segment_progress >= 1
        and _current_segment_turns(state) >= _segment_turn_floor(segment)
    ):
        fallback = next(item for item in plan.ending_matrix.endings if item.ending_id == "burned_alone")
        state.status = "completed"
        state.ending_id = fallback.ending_id
        state.ending_summary = fallback.summary
        return True, fallback.ending_id, fallback.summary
    return False, None, None


def advance_segment_if_ready(plan: CompiledPlayPlan, state: UrbanWorldState) -> bool:
    segment = _current_segment(plan, state)
    if state.segment_progress < _segment_threshold(segment):
        return False
    if _current_segment_turns(state) < _segment_turn_floor(segment):
        return False
    if segment.is_terminal:
        return False
    consolidate_segment_memory(
        state,
        segment_id=segment.segment_id,
        segment_role=segment.segment_role,
    )
    state.segment_index = min(state.segment_index + 1, len(plan.segments) - 1)
    state.segment_progress = 0
    _load_segment_scene(state, _current_segment(plan, state))
    return True


_NARRATION_HISTORY_WINDOW = 4
_KEY_BURST_SEGMENT_ROLES: set[SegmentRoleId] = {"reveal", "terminal"}


def _extract_embedded_narration_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if raw.startswith("{") and "\"narration\"" in raw:
        try:
            decoded, _ = json.JSONDecoder().raw_decode(raw)
            if isinstance(decoded, dict):
                narration = decoded.get("narration")
                if isinstance(narration, str) and narration.strip():
                    return narration
        except Exception:  # noqa: BLE001
            pass
    if "\"narration\"" in raw:
        match = re.search(r'"narration"\s*:\s*"(?P<value>(?:[^"\\]|\\.)*)"', raw, flags=re.DOTALL)
        if match is not None:
            try:
                return str(json.loads(f"\"{match.group('value')}\""))
            except Exception:  # noqa: BLE001
                return match.group("value").replace('\\"', '"').replace("\\n", "\n")
    return raw


def _finalize_narration_style(text: str) -> str:
    normalized = normalize_whitespace(_extract_embedded_narration_text(text))
    normalized = normalized.replace("TA", "对方")
    normalized = re.sub(r"。{2,}", "。", normalized)
    normalized = re.sub(r"([。！？])([，,])", r"\1", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return trim_text(normalized, 4000)


class NarrationComposeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_pack: dict[str, Any]
    style_cases: list[dict[str, str]] = Field(default_factory=list, min_length=1, max_length=3)
    style_card: dict[str, Any]
    storylet_hints: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    memory_context: dict | None = None


class NarrationComposeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narration: str = Field(min_length=8, max_length=4000)
    coverage_marks: dict[str, bool] = Field(default_factory=dict)
    length_profile: Literal["short", "normal", "burst"] = "normal"


def _selected_dramatic_example_texts(segment: CompiledSegment, style_hints: ToneExampleStyleHints) -> dict[str, str]:
    explicit_cases = {
        case_id: trim_text(text, 260)
        for case_id, text in style_hints.style_case_text_items
        if case_id and text
    }
    if explicit_cases:
        return explicit_cases
    bucket_ids = tuple(style_hints.used_bucket_ids)
    if not bucket_ids:
        return {}
    all_items = [
        *segment.template_tone_example_lines,
        *segment.template_tone_scene_examples,
        *segment.tone_example_pack.author_example_lines,
        *segment.tone_example_pack.author_example_scene,
        *segment.tone_example_pack.play_reaction_example_lines,
        *segment.tone_example_pack.play_supporting_example_lines,
        *segment.tone_example_pack.play_chain_example_lines,
        *segment.tone_example_pack.play_debt_example_lines,
    ]
    by_bucket: dict[str, str] = {}
    wanted = set(bucket_ids)
    for item in all_items:
        if item.bucket_id in wanted and item.bucket_id not in by_bucket:
            by_bucket[item.bucket_id] = trim_text(item.text, 260)
    return by_bucket


def _sentence_count(text: str) -> int:
    chunks = [item for item in re.split(r"[。！？!?]+", text) if item.strip()]
    return len(chunks)


def _length_profile_from_verbosity(verbosity_hint: Literal["short", "medium", "long"]) -> Literal["short", "normal", "burst"]:
    if verbosity_hint == "short":
        return "short"
    if verbosity_hint == "long":
        return "burst"
    return "normal"


def _length_bounds_for_policy(length_policy: str) -> tuple[int, int]:
    if length_policy == "short":
        return 2, 3
    if length_policy == "burst":
        return 4, 6
    return 2, 3


def _selected_style_cases_for_compose(
    segment: CompiledSegment,
    style_hints: ToneExampleStyleHints,
    *,
    preferred_bucket_ids: tuple[str, ...] = (),
    max_cases: int = 3,
) -> tuple[tuple[str, str], ...]:
    layer_order = {"primary": 0, "supporting": 1, "fallout": 2}
    explicit: list[tuple[str, str]] = []
    preferred = {item.strip() for item in preferred_bucket_ids if item.strip()}
    for case_id, text in style_hints.style_case_text_items:
        if not case_id or not text:
            continue
        explicit.append((case_id, trim_text(text, 260)))
    if preferred:
        explicit = sorted(
            explicit,
            key=lambda item: (
                0 if any(bucket in item[0] for bucket in preferred) else 1,
                layer_order.get(str(item[0]).split(":", 1)[0], 9),
            ),
        )
    else:
        explicit.sort(key=lambda item: layer_order.get(str(item[0]).split(":", 1)[0], 9))
    selected: list[tuple[str, str]] = explicit[: max(1, max_cases)]
    seen_ids = {item[0] for item in selected}
    if len(selected) < 2:
        for case_id, text in _selected_dramatic_example_texts(segment, style_hints).items():
            if not case_id or not text or case_id in seen_ids:
                continue
            selected.append((case_id, trim_text(text, 260)))
            seen_ids.add(case_id)
            if len(selected) >= max(2, max_cases):
                break
    if not selected:
        selected = [
            ("primary:fallback", "你这句话把关系账先推到了台面，场内外都开始重算站位。"),
            ("fallout:fallback", "代价先落在解释权和信任上，后续每句都会被放大。"),
        ]
    if len(selected) == 1:
        selected.append(("supporting:fallback", "旁边的人不会再按旧默契配合，风向会继续外扩。"))
    return tuple(selected[: max(1, max_cases)])


_SOFT_DEWEIGHT_BASE_STEMS: tuple[str, ...] = (
    "等于",
    "当场",
    "话音一落",
    "像是",
    "台面",
    "站边",
    "背锅",
    "没给",
    "没有给",
)

_NARRATIVE_TECHNIQUE_CARDS: tuple[dict[str, str], ...] = (
    {
        "technique_id": "dialogue_crosscut",
        "camera_focus": "用两段短对话交叉推进，不先下结论。",
        "rhythm_hint": "先抛一句试探，再用对方的停顿或改口回击。",
        "detail_hint": "优先写到说话时的手势、停顿、呼吸或目光偏移。",
        "avoid_style": "避免连用抽象判词和总结句。",
    },
    {
        "technique_id": "object_trace",
        "camera_focus": "从可见物证或现场物件入手，再落到关系后果。",
        "rhythm_hint": "先写物件动作，再写人物反应，不要反过来。",
        "detail_hint": "用一处细节（纸角、话筒、屏幕、杯沿）承接冲突。",
        "avoid_style": "避免每句都以“等于/当场”做结算。",
    },
    {
        "technique_id": "witness_reaction",
        "camera_focus": "借旁观者反应折射主冲突，而不是直接宣判。",
        "rhythm_hint": "先写围观席变化，再切回主角动作。",
        "detail_hint": "写一条能被旁人直接看见或听见的信号。",
        "avoid_style": "避免口号化的“站边/背锅”堆叠。",
    },
    {
        "technique_id": "inner_micro_pause",
        "camera_focus": "用半拍停顿和自我克制制造张力反差。",
        "rhythm_hint": "短句+短句+长句，形成节奏起伏。",
        "detail_hint": "写清“本想说什么、最后改成了什么”。",
        "avoid_style": "避免全程同一音高的审计口吻。",
    },
)

_MOVE_EXPRESSION_HINTS: dict[str, tuple[str, ...]] = {
    "accuse": (
        "把“指责”写成证据链追问，不要直接贴标签。",
        "先复述对方上一句关键话，再指出矛盾点。",
        "尽量用具体行为词（签字、删档、改口）代替抽象定性。",
    ),
    "public_reveal": (
        "先给可见证据，再给结论，不要先下判词。",
        "把爆点写成可听见/可看见的瞬时变化。",
        "借旁观反应放大冲击，不要只写系统总结。",
    ),
    "ally_with": (
        "把“联手”写成互相让步的交换动作，而非口头宣誓。",
        "写清谁先让步、对方怎么接刀，避免空泛表忠。",
    ),
    "comfort": (
        "把“安慰”写成护住现场位置的动作，不止情绪安抚。",
        "避免千篇一律的温柔句，给出角色专属口吻。",
    ),
}


def _stable_rotation_index(seed: str, size: int) -> int:
    if size <= 1:
        return 0
    return sum(ord(char) for char in seed) % size


def _soft_avoid_stems_from_recent(
    *,
    state: UrbanWorldState,
    style_hints: ToneExampleStyleHints,
) -> tuple[str, ...]:
    candidates = []
    event_phrases = [e.phrase for e in getattr(state, "narration_event_log", []) if e.phrase]
    source_phrases = event_phrases if event_phrases else list(state.recent_narration_phrases)[-_NARRATION_HISTORY_WINDOW:]
    for phrase in source_phrases:
        canonical = canonicalize_phrase(phrase)
        if len(canonical) >= 6:
            candidates.append(canonical[:8])
    blocked = list(getattr(style_hints, "blocked_stems", None) or [])
    candidates.extend(blocked)
    return tuple(unique_preserve(candidates)[:20])


def _soft_deweight_stems(
    *,
    state: UrbanWorldState,
    style_hints: ToneExampleStyleHints,
    soft_avoid_stems: tuple[str, ...],
) -> tuple[dict[str, str | float], ...]:
    recent_candidates: list[str] = []
    for phrase in list(state.recent_narration_phrases)[-_NARRATION_HISTORY_WINDOW:]:
        canonical = canonicalize_phrase(phrase)
        if len(canonical) >= 4:
            recent_candidates.append(canonical[:10])
    ordered_stems = unique_preserve(
        [*recent_candidates, *list(soft_avoid_stems), *_SOFT_DEWEIGHT_BASE_STEMS]
    )[:10]
    weighted: list[dict[str, str | float]] = []
    for stem in ordered_stems:
        if stem in recent_candidates:
            weight = 0.3
        elif stem in _SOFT_DEWEIGHT_BASE_STEMS:
            weight = 0.6
        else:
            weight = 0.5
        weighted.append(
            {
                "stem": trim_text(stem, 24),
                "deweight": round(weight, 2),
            }
        )
    return tuple(weighted)


def _move_expression_hints(
    *,
    move_family: RelationshipMoveFamily,
    segment_role: SegmentRoleId,
    turn_input_mode: Literal["free_input", "select_id"],
    turn_index: int,
    target_id: str,
) -> tuple[str, ...]:
    hints = list(_MOVE_EXPRESSION_HINTS.get(move_family, ()))
    if (
        turn_input_mode == "free_input"
        and segment_role in {"opening", "reveal"}
        and move_family in {"accuse", "public_reveal"}
    ):
        hints.extend(
            (
                "本回合优先减少“谁对谁错”的结算语，多写现场换手动作。",
                "可以把冲突落到一件小动作上，再引出后果，不要整段概括。",
            )
        )
    if not hints:
        return ()
    start = _stable_rotation_index(
        f"{move_family}:{segment_role}:{turn_input_mode}:{turn_index}:{target_id}",
        len(hints),
    )
    rotated = hints[start:] + hints[:start]
    limit = 3 if turn_input_mode == "free_input" else 2
    return tuple(trim_text(item, 90) for item in rotated[:limit])


def _narrative_technique_card(
    *,
    move_family: RelationshipMoveFamily,
    segment_role: SegmentRoleId,
    turn_input_mode: Literal["free_input", "select_id"],
    turn_index: int,
    target_id: str,
) -> dict[str, str]:
    preferred_cards = _NARRATIVE_TECHNIQUE_CARDS
    if (
        turn_input_mode == "free_input"
        and segment_role in {"opening", "reveal"}
        and move_family in {"accuse", "public_reveal"}
    ):
        preferred_cards = tuple(
            card
            for card in _NARRATIVE_TECHNIQUE_CARDS
            if card["technique_id"] in {"dialogue_crosscut", "object_trace", "witness_reaction"}
        ) or _NARRATIVE_TECHNIQUE_CARDS
    index = _stable_rotation_index(
        f"{segment_role}:{move_family}:{turn_input_mode}:{turn_index}:{target_id}",
        len(preferred_cards),
    )
    return dict(preferred_cards[index])


def _voice_phrase_hints(
    selected_voice_atoms: tuple[VoiceAtom, ...],
) -> tuple[dict[str, str], ...]:
    hints: list[dict[str, str]] = []
    for atom in selected_voice_atoms[:2]:
        voice_sample = trim_text(atom.line_stub, 120)
        catchphrase = trim_text(atom.catchphrase_hint or "", 40)
        avoid_reuse = "、".join(trim_text(term, 20) for term in atom.forbidden_terms[:2] if term.strip())
        hints.append(
            {
                "atom_id": atom.atom_id,
                "voice_sample": voice_sample,
                "catchphrase": catchphrase,
                "avoid_reuse": avoid_reuse,
            }
        )
    return tuple(hints)


def _tradeoff_markers_from_diagnostics(intent_diagnostics: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(intent_diagnostics, dict):
        return ()
    raw = str(intent_diagnostics.get("intent_tradeoff_markers") or "").strip()
    if not raw:
        return ()
    return tuple(
        trim_text(item, 72)
        for item in raw.split(",")
        if trim_text(item, 72)
    )[:5]


def _default_control_contract(
    *,
    segment_role: SegmentRoleId,
    move_family: RelationshipMoveFamily,
    turn_index: int,
    target_name: str,
    scene_pressure: ScenePressureBeat,
    shell_tokens: tuple[str, ...],
) -> dict[str, str]:
    must_yield_side = f"{target_name}先给出可见让步，不能继续口头拖延。"
    yield_cost = "让步代价要落在关系账或场面顺位上。"
    refuse_escalation = {
        "opening": "若拒绝让步，下一拍会升级为公开站位试探。",
        "misread": "若拒绝让步，误读会升级成当面拆台。",
        "pressure": "若拒绝让步，冲突会升级为公开切割和追责。",
        "reversal": "若拒绝让步，局势会升级为换边和反手翻牌。",
        "reveal": "若拒绝让步，后果会升级到公开翻牌并外溢到旁观者。",
        "terminal": "若拒绝让步，后果会升级为终局切割且难以回撤。",
    }.get(segment_role, "若拒绝让步，局势会继续升级并扩大成本。")
    settlement_window = {
        "private": "窗口在这回合内，拖过这一拍就会失控。",
        "semi_public": "窗口只剩这一拍，旁人已经开始对号入座。",
        "public": "窗口极短，台面已经在记录谁先失手。",
    }.get(scene_pressure.visibility_level, "窗口很短，这回合就要给出可执行态度。")
    shell_hint = "、".join(shell_tokens[:2]) if shell_tokens else "场面"
    observable_evidence = f"要给出可见证据：谁先表态、谁付代价、{shell_hint}如何当场反应。"
    if (
        segment_role == "opening"
        and move_family in _DEFAULT_CONTROL_BIAS_SOFT_MOVES
        and int(turn_index) <= _DEFAULT_CONTROL_BIAS_OPENING_FORCE_UNTIL_TURN_INDEX
    ):
        must_yield_side = f"{target_name}必须在台面上先认一件具体事，不能只给情绪安抚。"
        yield_cost = "让步代价要落在可计数资产：名额、站位、信誉或盟友支持。"
        refuse_escalation = "若拒绝让步，下一拍立刻升级为公开点名或换边试探。"
        observable_evidence = f"必须出现可见证据：谁先认账、谁被追问、{shell_hint}如何转向。"
    return {
        "must_yield_side": must_yield_side,
        "yield_cost": yield_cost,
        "refuse_escalation": refuse_escalation,
        "settlement_window": settlement_window,
        "observable_evidence": observable_evidence,
    }


def _control_contract_with_markers(
    *,
    base_contract: dict[str, str],
    tradeoff_markers: tuple[str, ...],
) -> dict[str, str]:
    if not tradeoff_markers:
        return base_contract
    contract = dict(base_contract)
    marker_slots: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("must_yield_side", ("让步", "站边", "先认", "先表态")),
        ("yield_cost", ("代价", "背锅", "失去", "付出")),
        ("refuse_escalation", ("升级", "翻牌", "切割", "外溢")),
        ("settlement_window", ("窗口", "今晚", "这回合", "这一拍")),
        ("observable_evidence", ("证据", "看见", "台面", "镜头", "旁观")),
    )
    remaining = list(tradeoff_markers)
    for slot_key, keywords in marker_slots:
        matched = next(
            (item for item in remaining if any(token in item for token in keywords)),
            None,
        )
        if matched:
            contract[slot_key] = trim_text(matched, 90)
            remaining.remove(matched)
    for slot_key, _keywords in marker_slots:
        if not remaining:
            break
        if slot_key in contract and contract[slot_key] == base_contract.get(slot_key):
            contract[slot_key] = trim_text(remaining.pop(0), 90)
    return contract


def _turn_complexity_for_compose(
    *,
    state: UrbanWorldState,
    segment: CompiledSegment,
) -> Literal["normal", "key_burst"]:
    if (
        segment.segment_role in _KEY_BURST_SEGMENT_ROLES
        or bool(state.last_turn_escalations)
        or state.scene_heat >= 5
        or state.secret_exposure >= 4
        or state.route_lock >= 4
    ):
        return "key_burst"
    return "normal"


def _storylet_hints_for_compose(matches: list[StoryletMatch]) -> list[dict[str, Any]]:
    return [
        {
            "storylet_id": str(match.storylet_id or "").strip(),
            "function": str(match.narrative_function or "").strip(),
            "scene_text": str(match.scene_text or "").strip()[:180],
            "venue_hint": str(match.venue_hint or "").strip()[:60],
            "match_score": round(float(match.match_score), 2),
            "dramatic_weight": round(float(getattr(match, "dramatic_weight", 0.0) or 0.0), 2),
            "cooldown_turns": int(getattr(match, "cooldown_turns", 0) or 0),
            "matched_conditions": [
                str(item).strip()
                for item in list(getattr(match, "matched_conditions", []) or [])
                if str(item).strip()
            ][:4],
            "preconditions": {
                "required_secrets_known": [
                    str(item).strip()
                    for item in list(dict(getattr(match, "preconditions", {}) or {}).get("required_secrets_known") or [])
                    if str(item).strip()
                ][:3],
                "required_relationships": [
                    str(item).strip()
                    for item in list(dict(getattr(match, "preconditions", {}) or {}).get("required_relationships") or [])
                    if str(item).strip()
                ][:3],
                "required_segment_roles": [
                    str(item).strip()
                    for item in list(dict(getattr(match, "preconditions", {}) or {}).get("required_segment_roles") or [])
                    if str(item).strip()
                ][:3],
                "min_tension_score": round(
                    float(dict(getattr(match, "preconditions", {}) or {}).get("min_tension_score") or 0.0),
                    2,
                ),
            },
            "effects": {
                "secrets_revealed": [
                    str(item).strip()
                    for item in list(dict(getattr(match, "effects", {}) or {}).get("secrets_revealed") or [])
                    if str(item).strip()
                ][:3],
                "relationship_shifts": {
                    str(character_id).strip(): round(float(raw_shift), 2)
                    for character_id, raw_shift in dict(
                        dict(getattr(match, "effects", {}) or {}).get("relationship_shifts") or {}
                    ).items()
                    if str(character_id).strip()
                },
                "tension_delta": round(float(dict(getattr(match, "effects", {}) or {}).get("tension_delta") or 0.0), 2),
                "triggers_chain": (
                    str(dict(getattr(match, "effects", {}) or {}).get("triggers_chain") or "").strip() or None
                ),
            },
        }
        for match in matches[:3]
    ]


def _storylet_hint_prompt_section(storylet_hints: list[dict[str, Any]] | None) -> str:
    ranked_hints = sorted(
        [
            item
            for item in list(storylet_hints or [])
            if isinstance(item, dict) and str(item.get("scene_text") or "").strip()
        ],
        key=lambda item: (
            -float(item.get("match_score") or 0.0),
            str(item.get("function") or ""),
            str(item.get("scene_text") or ""),
        ),
    )
    if not ranked_hints:
        return ""
    selected_hint = dict(ranked_hints[0])
    selected_payload = {
        "storylet_id": str(selected_hint.get("storylet_id") or "").strip(),
        "narrative_function": str(selected_hint.get("function") or "").strip() or "scene",
        "match_score": round(float(selected_hint.get("match_score") or 0.0), 2),
        "dramatic_weight": round(float(selected_hint.get("dramatic_weight") or 0.0), 2),
        "cooldown_turns": int(selected_hint.get("cooldown_turns") or 0),
        "matched_conditions": [
            str(item).strip()
            for item in list(selected_hint.get("matched_conditions") or [])
            if str(item).strip()
        ][:4],
        "scene_anchor": trim_text(str(selected_hint.get("scene_text") or "").strip(), 180),
        "venue_hint": trim_text(str(selected_hint.get("venue_hint") or "").strip(), 60),
        "preconditions": {
            "required_secrets_known": [
                str(item).strip()
                for item in list(dict(selected_hint.get("preconditions") or {}).get("required_secrets_known") or [])
                if str(item).strip()
            ][:3],
            "required_relationships": [
                str(item).strip()
                for item in list(dict(selected_hint.get("preconditions") or {}).get("required_relationships") or [])
                if str(item).strip()
            ][:3],
            "required_segment_roles": [
                str(item).strip()
                for item in list(dict(selected_hint.get("preconditions") or {}).get("required_segment_roles") or [])
                if str(item).strip()
            ][:3],
            "min_tension_score": round(
                float(dict(selected_hint.get("preconditions") or {}).get("min_tension_score") or 0.0),
                2,
            ),
        },
        "effects": {
            "secrets_revealed": [
                str(item).strip()
                for item in list(dict(selected_hint.get("effects") or {}).get("secrets_revealed") or [])
                if str(item).strip()
            ][:3],
            "relationship_shifts": {
                str(character_id).strip(): round(float(raw_shift), 2)
                for character_id, raw_shift in dict(dict(selected_hint.get("effects") or {}).get("relationship_shifts") or {}).items()
                if str(character_id).strip()
            },
            "tension_delta": round(float(dict(selected_hint.get("effects") or {}).get("tension_delta") or 0.0), 2),
            "triggers_chain": (
                str(dict(selected_hint.get("effects") or {}).get("triggers_chain") or "").strip() or None
            ),
        },
    }
    payload_text = json.dumps(selected_payload, ensure_ascii=False, separators=(",", ":"))
    while payload_text:
        if len(payload_text) <= 700:
            return (
                "\n\n## 已选情境素材（storylet）\n"
                "以下 JSON 已根据当前世界状态匹配完成，不是可选灵感：\n"
                f"{payload_text}\n"
                "最终叙述必须把 scene_anchor 或 effects 里的至少一个具体物件、证据、地点、动作或后果写成场上正在发生的细节，不得原样抄写 JSON。\n\n"
            )
        selected_payload["scene_anchor"] = trim_text(selected_payload["scene_anchor"], max(len(selected_payload["scene_anchor"]) - 24, 72))
        payload_text = json.dumps(selected_payload, ensure_ascii=False, separators=(",", ":"))
    return ""


_MEMORY_CONTEXT_PROMPT_CHAR_LIMIT = 900
_MEMORY_CONTEXT_RELATION_DIMENSIONS = ("affection", "trust", "tension", "suspicion", "dependency")
_MEMORY_CONTEXT_RELATION_LABELS = {
    "affection": "亲密",
    "trust": "信任",
    "tension": "张力",
    "suspicion": "怀疑",
    "dependency": "依赖",
}
_MEMORY_CONTEXT_TREND_LABELS = {
    "rising": "上升",
    "falling": "下降",
    "stable": "持平",
}


def _memory_context_counts(memory_context: dict | None) -> dict[str, int]:
    if not isinstance(memory_context, dict):
        return {
            "memory_context_active_hooks": 0,
            "memory_context_revealed_secrets": 0,
            "memory_context_npc_pressure_count": 0,
        }
    active_hooks = memory_context.get("active_hook_summary")
    revealed_secrets = memory_context.get("revealed_secret_summary")
    npc_pressure = memory_context.get("npc_pressure_snapshot")
    return {
        "memory_context_active_hooks": len(active_hooks) if isinstance(active_hooks, list) else 0,
        "memory_context_revealed_secrets": len(revealed_secrets) if isinstance(revealed_secrets, list) else 0,
        "memory_context_npc_pressure_count": len(npc_pressure) if isinstance(npc_pressure, dict) else 0,
    }


def _memory_context_has_content(memory_context: dict | None) -> bool:
    if not isinstance(memory_context, dict):
        return False
    for key in (
        "active_hook_summary",
        "relationship_trajectory",
        "revealed_secret_summary",
        "npc_pressure_snapshot",
        "summary_texts",
    ):
        value = memory_context.get(key)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, list) and value:
            return True
    return False


def _memory_context_prompt_section(compose_input: NarrationComposeInput) -> tuple[str, int]:
    memory_context = compose_input.memory_context
    if not _memory_context_has_content(memory_context):
        return "", 0
    if not isinstance(memory_context, dict):
        return "", 0

    def _format_number(raw_value: object) -> str:
        try:
            return f"{float(raw_value):g}"
        except Exception:
            return str(raw_value).strip()

    def _recent_items(items: list[str], *, limit: int) -> list[str]:
        if limit <= 0:
            return []
        return list(items[-limit:])

    active_hook_items: list[str] = []
    for hook in list(memory_context.get("active_hook_summary") or []):
        if not isinstance(hook, dict):
            continue
        holder_id = str(hook.get("holder_id") or "").strip() or "unknown_holder"
        target_id = str(hook.get("target_id") or "").strip() or "unknown_target"
        leverage_type = str(hook.get("leverage_type") or "").strip() or "mixed"
        status = str(hook.get("status") or "").strip() or "unknown"
        leverage_value = _format_number(hook.get("leverage_value", "0"))
        active_hook_items.append(
            trim_text(
                f"{holder_id}→{target_id}（{leverage_type}，{status}，筹码强度 {leverage_value}）",
                84,
            )
        )
    active_hook_items = _recent_items(active_hook_items, limit=2)

    prompt_target_ids: set[str] = set()
    prompt_target_id = str(dict(compose_input.fact_pack or {}).get("target_id") or "").strip()
    if prompt_target_id and prompt_target_id != "unknown":
        prompt_target_ids.add(prompt_target_id)

    npc_pressure_snapshot = memory_context.get("npc_pressure_snapshot") or {}
    if isinstance(npc_pressure_snapshot, dict):
        prompt_target_ids.update(str(character_id).strip() for character_id in npc_pressure_snapshot.keys() if str(character_id).strip())
    else:
        npc_pressure_snapshot = {}

    relationship_items: list[str] = []
    relationship_trajectory = memory_context.get("relationship_trajectory") or {}
    if isinstance(relationship_trajectory, dict) and prompt_target_ids:
        filtered_trajectory = (
            {
                str(character_id): raw_dimensions
                for character_id, raw_dimensions in relationship_trajectory.items()
                if str(character_id) in prompt_target_ids
            }
        )
        for character_id, raw_dimensions in filtered_trajectory.items():
            if not isinstance(raw_dimensions, dict):
                continue
            rendered_dimensions = [
                f"{label}{_MEMORY_CONTEXT_TREND_LABELS.get(str(raw_dimensions.get(key) or '').strip(), '持平')}"
                for key, label in _MEMORY_CONTEXT_RELATION_LABELS.items()
                if key in {"affection", "trust", "tension", "suspicion"}
            ]
            relationship_items.append(
                trim_text(f"{character_id}: {' / '.join(rendered_dimensions)}", 92)
            )
    relationship_items = _recent_items(relationship_items, limit=2)

    revealed_secret_items: list[str] = []
    for secret in list(memory_context.get("revealed_secret_summary") or []):
        if not isinstance(secret, dict):
            continue
        title = str(secret.get("title") or secret.get("secret_id") or "").strip() or "unknown_secret"
        excerpt = str(secret.get("description_excerpt") or "").strip()
        if excerpt:
            revealed_secret_items.append(trim_text(f"{title}（{excerpt}）", 88))
        else:
            revealed_secret_items.append(trim_text(title, 72))
    revealed_secret_items = _recent_items(revealed_secret_items, limit=3)

    pressure_items: list[str] = []
    if isinstance(npc_pressure_snapshot, dict):
        for character_id, metrics in npc_pressure_snapshot.items():
            if not isinstance(metrics, dict):
                continue
            pressure_items.append(
                trim_text(
                    (
                        f"{character_id}: "
                        f"压力{_format_number(metrics.get('pressure_load', 0))} / "
                        f"受辱风险{_format_number(metrics.get('humiliation_risk', 0))} / "
                        f"背叛倾向{_format_number(metrics.get('betrayal_readiness', 0))}"
                    ),
                    90,
                )
            )
    pressure_items = _recent_items(pressure_items, limit=2)

    summary_items = [
        trim_text(str(item).strip(), 90)
        for item in list(memory_context.get("summary_texts") or [])[-3:]
        if str(item).strip()
    ]

    blocks = [
        {
            "key": "active_hook_summary",
            "header": "- 已知并活跃的钩子（持钩者→目标，筹码类型，状态）：",
            "items": active_hook_items,
        },
        {
            "key": "relationship_trajectory",
            "header": "- 关系走向（仅本 turn 涉及的 NPC）：",
            "items": relationship_items,
        },
        {
            "key": "revealed_secret_summary",
            "header": "- 已暴露秘密（最近 N 条）：",
            "items": revealed_secret_items,
        },
        {
            "key": "npc_pressure_snapshot",
            "header": "- NPC 心理压力（本 turn 涉及）：",
            "items": pressure_items,
        },
        {
            "key": "summary_texts",
            "header": "- 近期场景摘要：",
            "items": summary_items,
        },
    ]

    def _render_section() -> str:
        if not any(block["items"] for block in blocks):
            return ""
        lines = ["\n\n## 当前局势（memory context）"]
        for block in blocks:
            body = "；".join(str(item) for item in block["items"] if str(item).strip()) or "无"
            lines.append(f"{block['header']}\n  {body}")
        lines.append("叙述必须与上述状态保持一致，不得自相矛盾。")
        return "\n".join(lines)

    section = _render_section()
    if not section:
        return "", 0
    trim_order = (
        "summary_texts",
        "npc_pressure_snapshot",
        "revealed_secret_summary",
        "relationship_trajectory",
        "active_hook_summary",
    )
    while len(section) > _MEMORY_CONTEXT_PROMPT_CHAR_LIMIT and any(block["items"] for block in blocks):
        trimmed = False
        for key in trim_order:
            block = next(item for item in blocks if item["key"] == key)
            if not block["items"]:
                continue
            if key in {"summary_texts", "revealed_secret_summary", "active_hook_summary"}:
                block["items"].pop(0)
            else:
                block["items"].pop()
            trimmed = True
            break
        if not trimmed:
            break
        section = _render_section()
        if not section:
            return "", 0
    if not any(block["items"] for block in blocks):
        return "", 0
    return section, len(section)


def _build_narration_compose_input(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    beat: NpcReactionBeat,
    style_hints: ToneExampleStyleHints,
    supporting_reactions: tuple[SupportingReactionBeat, ...],
    selected_voice_atoms: tuple[VoiceAtom, ...],
    verbosity_hint: Literal["short", "medium", "long"],
    turn_complexity: Literal["normal", "key_burst"],
    turn_input_mode: Literal["free_input", "select_id"],
    intent_diagnostics: dict[str, Any] | None = None,
    storylet_hints: list[dict[str, Any]] | None = None,
) -> NarrationComposeInput:
    pack = state.active_beat_delta_pack
    delta_pack_hit = pack.segment_id == segment.segment_id
    compose_hint_bundle = pack.compose_payload_hint_bundle if delta_pack_hit else None
    preferred_bucket_ids = (
        tuple(compose_hint_bundle.style_case_bucket_ids)
        if compose_hint_bundle is not None
        else ()
    )
    max_cases, supporting_payload_limit, consequence_tag_limit, shell_token_limit = _turn_compose_limits(
        plan=plan,
        turn_complexity=turn_complexity,
    )
    style_cases = _selected_style_cases_for_compose(
        segment,
        style_hints,
        preferred_bucket_ids=preferred_bucket_ids,
        max_cases=max_cases,
    )
    soft_avoid_stems = _soft_avoid_stems_from_recent(state=state, style_hints=style_hints)
    soft_deweight_stems = _soft_deweight_stems(
        state=state,
        style_hints=style_hints,
        soft_avoid_stems=soft_avoid_stems,
    )
    shell_tokens = tuple(unique_preserve([*style_hints.anchor_tokens, beat.arena_name]))[:8]
    required_names = tuple(
        unique_preserve(
            [
                beat.target_name,
                style_hints.cost_subject_payer_name if style_hints.force_main_clause_cost_subject else "",
                style_hints.cost_subject_beneficiary_name if style_hints.force_main_clause_cost_subject else "",
            ]
        )
    )
    length_policy = _length_profile_from_verbosity(verbosity_hint)
    min_sentences, max_sentences = _length_bounds_for_policy(length_policy)
    turn_card = pack.burst_turn_card if turn_complexity == "key_burst" else pack.normal_turn_card
    play_tuning = _play_tuning_profile(plan)
    compose_style_guidance_weight = (
        float(getattr(play_tuning, "compose_style_guidance_weight", 1.0))
        if play_tuning is not None
        else 1.0
    )
    compose_voice_hint_weight = (
        float(getattr(play_tuning, "compose_voice_hint_weight", 1.0))
        if play_tuning is not None
        else 1.0
    )
    compose_control_contract_hint_weight = (
        float(getattr(play_tuning, "compose_control_contract_hint_weight", 1.0))
        if play_tuning is not None
        else 1.0
    )
    compose_evidence_hint_weight = (
        float(getattr(play_tuning, "compose_evidence_hint_weight", 1.0))
        if play_tuning is not None
        else 1.0
    )
    tradeoff_markers = _tradeoff_markers_from_diagnostics(intent_diagnostics)
    base_control_contract = _default_control_contract(
        segment_role=segment.segment_role,
        move_family=intent.move_family,
        turn_index=state.turn_index,
        target_name=beat.target_name,
        scene_pressure=beat.scene_pressure,
        shell_tokens=shell_tokens,
    )
    control_contract = _control_contract_with_markers(
        base_contract=base_control_contract,
        tradeoff_markers=tradeoff_markers,
    )
    narrative_technique_card = _narrative_technique_card(
        move_family=intent.move_family,
        segment_role=segment.segment_role,
        turn_input_mode=turn_input_mode,
        turn_index=state.turn_index,
        target_id=beat.target_id,
    )
    move_expression_hints = _move_expression_hints(
        move_family=intent.move_family,
        segment_role=segment.segment_role,
        turn_input_mode=turn_input_mode,
        turn_index=state.turn_index,
        target_id=beat.target_id,
    )
    voice_phrase_hints = _voice_phrase_hints(selected_voice_atoms)
    fact_pack = {
        "story_shell_id": plan.story_shell_id,
        "template_id": plan.template_id,
        "segment_role": segment.segment_role,
        "turn_complexity": turn_complexity,
        "target_id": beat.target_id,
        "target_name": beat.target_name,
        "move_family": intent.move_family,
        "move_label": MOVE_FAMILY_SURFACE_LABELS.get(intent.move_family, intent.move_family),
        "scene_pressure": {
            "visibility_level": beat.scene_pressure.visibility_level,
            "pressure_level": beat.scene_pressure.pressure_level,
            "scene_heat": beat.scene_pressure.scene_heat,
            "secret_exposure": beat.scene_pressure.secret_exposure,
            "route_lock": beat.scene_pressure.route_lock,
            "witness_focus": beat.scene_pressure.witness_focus,
        },
        "relationship_anchor": {
            "relation_shift": beat.relation_shift,
            "dominant_impulse": beat.dominant_impulse,
            "fallout_vector": beat.fallout_vector,
        },
        "supporting_reactions": [
            {
                "role": reaction.role,
                "name": reaction.beat.target_name,
                "reason_family": reaction.reason_family or "mixed",
                "cause_tags": list(reaction.cause_tags[:3]),
            }
            for reaction in supporting_reactions[:supporting_payload_limit]
        ],
        "consequence_tags": list(state.last_turn_tags[:consequence_tag_limit]),
        "must_keep_names": [item for item in required_names if item],
        "delta_turn_directive": trim_text(turn_card.directive, 220),
    }
    style_card = {
        "dramatic_mode": style_hints.dramatic_mode,
        "cadence": style_hints.cadence,
        "primary_reason_family": style_hints.primary_reason_family,
        "counter_reason_family": style_hints.counter_reason_family,
        "crowd_reason_family": style_hints.crowd_reason_family,
        "fallout_reason_family": style_hints.fallout_reason_family,
        "signal_family": style_hints.signal_family,
        "cost_family": style_hints.cost_family,
        "shell_tokens": list(shell_tokens[:shell_token_limit]),
        "style_keywords": list(style_hints.style_case_keywords[:8]),
        "previous_scene_summaries": [
            {"segment_role": s.segment_role, "summary": s.summary_text}
            for s in getattr(state, "narration_segment_summaries", [])
            if s.summary_text
        ][-3:],
        "progression_bias_summary": trim_text(
            (compose_hint_bundle.cue_summary if compose_hint_bundle is not None else segment.progression_rule_summary),
            220,
        ),
        "render_cues": list(
            unique_preserve(
                [
                    *(compose_hint_bundle.key_cues if compose_hint_bundle is not None else []),
                    *segment.render_cues,
                ]
            )[:5]
        ),
        "soft_avoid_stems": list(soft_avoid_stems),
        "soft_deweight_stems": [dict(item) for item in soft_deweight_stems],
        "length_policy": length_policy,
        "sentence_bounds": {"min_sentences": min_sentences, "max_sentences": max_sentences},
        "turn_complexity": turn_complexity,
        "turn_input_mode": turn_input_mode,
        "narrative_technique_card": narrative_technique_card,
        "move_expression_hints": list(move_expression_hints),
        "delta_turn_card": {
            "directive": trim_text(turn_card.directive, 220),
            "lane_focus": list(turn_card.lane_focus[:3]),
            "move_focus": list(turn_card.move_focus[:4]),
            "voice_focus_character_ids": list(turn_card.voice_focus_character_ids[:3]),
        },
        "voice_hints": [
            {
                "atom_id": atom.atom_id,
                "intent_tag": atom.intent_tag,
                "line_stub": trim_text(atom.line_stub, 120),
                "catchphrase_hint": trim_text(atom.catchphrase_hint or "", 40),
                "forbidden_terms": [trim_text(term, 20) for term in atom.forbidden_terms[:3] if term.strip()],
            }
            for atom in selected_voice_atoms[:2]
        ],
        "voice_phrase_hints": [dict(item) for item in voice_phrase_hints],
        "compose_style_guidance_weight": round(compose_style_guidance_weight, 4),
        "compose_voice_hint_weight": round(compose_voice_hint_weight, 4),
        "compose_control_contract_hint_weight": round(compose_control_contract_hint_weight, 4),
        "compose_evidence_hint_weight": round(compose_evidence_hint_weight, 4),
        "control_contract": {
            "must_yield_side": trim_text(control_contract.get("must_yield_side", ""), 120),
            "yield_cost": trim_text(control_contract.get("yield_cost", ""), 120),
            "refuse_escalation": trim_text(control_contract.get("refuse_escalation", ""), 120),
            "settlement_window": trim_text(control_contract.get("settlement_window", ""), 120),
            "observable_evidence": trim_text(control_contract.get("observable_evidence", ""), 120),
        },
        "tradeoff_markers": list(tradeoff_markers),
    }
    current_turn_npc_ids = [
        item
        for item in unique_preserve(
            [
                str(intent.target_id or "").strip(),
                str(intent.control_target_id or "").strip(),
                *[
                    str(effect.target_id or "").strip()
                    for effect in getattr(intent, "semantic_effects", [])
                    if str(getattr(effect, "target_id", "") or "").strip()
                ],
                *[
                    str(reaction.beat.target_id or "").strip()
                    for reaction in supporting_reactions
                    if str(getattr(reaction.beat, "target_id", "") or "").strip()
                ],
                *[
                    str(character_id).strip()
                    for character_id in list(getattr(state, "last_turn_relationship_deltas", {}).keys())
                    if str(character_id).strip()
                ],
            ]
        )
        if item and item != "unknown"
    ]
    memory_context = build_narration_memory_context(
        state,
        plan=plan,
        current_turn_npc_ids=current_turn_npc_ids,
    )
    return NarrationComposeInput(
        fact_pack=fact_pack,
        style_cases=[
            {"case_id": case_id, "text": trim_text(text, 260)}
            for case_id, text in style_cases
        ],
        style_card=style_card,
        storylet_hints=[dict(item) for item in list(storylet_hints or [])[:3]],
        memory_context=memory_context,
    )


def _deterministic_compose_output(compose_input: NarrationComposeInput) -> NarrationComposeOutput:
    fact_pack = dict(compose_input.fact_pack or {})
    style_card = dict(compose_input.style_card or {})
    relationship_anchor = dict(fact_pack.get("relationship_anchor") or {})
    scene_pressure = dict(fact_pack.get("scene_pressure") or {})
    target_name = str(fact_pack.get("target_name") or "对方").strip() or "对方"
    move_label = str(fact_pack.get("move_label") or fact_pack.get("move_family") or "动作").strip() or "动作"
    relation_shift = str(relationship_anchor.get("relation_shift") or "拉扯").strip() or "拉扯"
    fallout_vector = str(relationship_anchor.get("fallout_vector") or "pressure_wave").strip() or "pressure_wave"
    shell_tokens = [
        str(item).strip()
        for item in list(style_card.get("shell_tokens") or [])
        if str(item).strip()
    ]
    shell_token = shell_tokens[0] if shell_tokens else "场面"
    shell_signature = "、".join(shell_tokens[:3]) if shell_tokens else shell_token
    consequence_tags = [
        str(item).strip()
        for item in list(fact_pack.get("consequence_tags") or [])
        if str(item).strip()
    ]
    consequence_phrase = consequence_tags[0] if consequence_tags else "后果外溢"
    heat = str(scene_pressure.get("scene_heat") or "mid").strip() or "mid"
    pressure_level = str(scene_pressure.get("pressure_level") or "medium").strip() or "medium"
    voice_hints = list(style_card.get("voice_hints") or [])
    voice_hint = ""
    if voice_hints and isinstance(voice_hints[0], dict):
        voice_hint = str(voice_hints[0].get("line_stub") or "").strip()
    supporting_reactions = [
        item
        for item in list(fact_pack.get("supporting_reactions") or [])
        if isinstance(item, dict)
    ]
    primary_reason_family = str(style_card.get("primary_reason_family") or "").strip()
    supporting_name = ""
    supporting_reason = ""
    if supporting_reactions:
        supporting_name = str(supporting_reactions[0].get("name") or "").strip()
        supporting_reason = str(supporting_reactions[0].get("reason_family") or "").strip()
    line_two_prefix = "这一下把旧账和关系一起往" if primary_reason_family == "old_debt" else "这一下把关系往"
    lines: list[str] = [
        f"{shell_token}里，{target_name}先把{move_label}摆到台面。",
        f"{line_two_prefix}{relation_shift}推，{shell_signature}已经按“{consequence_phrase}”开始记账。",
        f"眼下压强是{pressure_level}，热度在{heat}档，{fallout_vector}正在外扩。",
    ]
    if shell_tokens:
        lines.append(f"{'、'.join(shell_tokens[:3])}这几条线已经被拉进同一张账。")
    if primary_reason_family == "old_debt":
        lines.append("旧账被重新翻到台面，没人还能假装没看见。")
    if supporting_name:
        reason_phrase = supporting_reason or "mixed"
        lines.insert(2, f"{supporting_name}已经按{reason_phrase}的路数表态，旁线不会再沉默。")
    if voice_hint:
        lines.append(trim_text(f"她说话的口吻仍贴着这条线：{voice_hint}。", 120))
    required_names = [
        str(item).strip()
        for item in list(fact_pack.get("must_keep_names") or [])
        if str(item).strip()
    ]
    missing_names = [name for name in required_names if all(name not in line for line in lines)]
    if missing_names:
        lines.append(f"{'、'.join(missing_names)}都被卷进这拍的代价里。")
    length_policy = str(style_card.get("length_policy") or "normal")
    if length_policy == "short":
        selected_lines = lines[:2]
        length_profile = "short"
    elif length_policy == "burst":
        selected_lines = lines[:4]
        if len(selected_lines) < 4:
            selected_lines.append(f"{target_name}知道这不是收口，而是下一轮追责的起点。")
        length_profile = "burst"
    else:
        selected_lines = lines[:3]
        length_profile = "normal"
    narration = trim_text("".join(line if line.endswith("。") else f"{line}。" for line in selected_lines), 4000)
    return NarrationComposeOutput(
        narration=narration,
        coverage_marks={
            "target": True,
            "move": True,
            "consequence": True,
            "relationship": True,
        },
        length_profile=length_profile,  # type: ignore[arg-type]
    )


def _compose_invalid_reasons(
    *,
    output: NarrationComposeOutput,
    shell_tokens: tuple[str, ...] = (),
) -> tuple[list[str], str]:
    rendered = _finalize_narration_style(output.narration)
    if not rendered:
        return ["empty_narration"], ""
    reasons: list[str] = []
    if shell_tokens and not any(token in rendered for token in shell_tokens):
        reasons.append("shell_miss")
    return reasons, rendered


def _compose_narration_once_with_regen(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    beat: NpcReactionBeat,
    seed: NarrationRenderSeed,
    style_hints: ToneExampleStyleHints,
    supporting_reactions: tuple[SupportingReactionBeat, ...],
    selected_voice_atoms: tuple[VoiceAtom, ...],
    voice_fallback_reason: str,
    verbosity_hint: Literal["short", "medium", "long"],
    turn_complexity: Literal["normal", "key_burst"],
    turn_input_mode: Literal["free_input", "select_id"],
    intent_diagnostics: dict[str, Any] | None = None,
    storylet_hints: list[dict[str, Any]] | None = None,
    shell_tokens: tuple[str, ...] = (),
    gateway: PlayLLMGateway | None = None,
) -> tuple[str, str, dict[str, int | float | str | bool]]:
    settings = get_settings()
    compose_started = time.perf_counter()
    compose_input = _build_narration_compose_input(
        plan=plan,
        segment=segment,
        state=state,
        intent=intent,
        beat=beat,
        style_hints=style_hints,
        supporting_reactions=supporting_reactions,
        selected_voice_atoms=selected_voice_atoms,
        verbosity_hint=verbosity_hint,
        turn_complexity=turn_complexity,
        turn_input_mode=turn_input_mode,
        intent_diagnostics=intent_diagnostics,
        storylet_hints=storylet_hints,
    )
    memory_context_counts = _memory_context_counts(compose_input.memory_context)
    memory_context_prompt_section, memory_context_chars = _memory_context_prompt_section(compose_input)
    diagnostics: dict[str, int | float | str | bool] = {
        "selected_style_case_ids": ",".join(case["case_id"] for case in compose_input.style_cases),
        "soft_avoid_stems": ",".join(str(item).strip() for item in list(compose_input.style_card.get("soft_avoid_stems") or []) if str(item).strip()),
        "diversity_guard_hits": 0,
        "pattern_guard_hits": 0,
        "compose_retry_count": 0,
        "shell_miss_on_first": False,
        "compose_invalid_reason": "",
        "blocked_stems": "",
        "blocked_stems_hit": False,
        "length_profile": "",
        "selected_voice_atom_ids": ",".join(atom.atom_id for atom in selected_voice_atoms[:2]),
        "voice_fallback_reason": voice_fallback_reason,
        "fallback_reason": "none",
        "narration_compose_source": "llm",
        "compose_latency_ms": 0.0,
        "compose_input_tokens": 0,
        "compose_output_tokens": 0,
        "compose_total_tokens": 0,
        "turn_complexity": turn_complexity,
        "turn_input_mode": turn_input_mode,
        "tradeoff_markers": ",".join(
            str(item).strip()
            for item in list(compose_input.style_card.get("tradeoff_markers") or [])
            if str(item).strip()
        ),
        "narrative_technique_id": str(
            dict(compose_input.style_card.get("narrative_technique_card") or {}).get("technique_id") or ""
        ),
        "soft_deweight_stems": ",".join(
            str(item.get("stem", "")).strip()
            for item in list(compose_input.style_card.get("soft_deweight_stems") or [])
            if isinstance(item, dict) and str(item.get("stem", "")).strip()
        ),
        "control_contract_slots": ",".join(
            str(key)
            for key, value in dict(compose_input.style_card.get("control_contract") or {}).items()
            if str(value).strip()
        ),
        "memory_context_active_hooks": int(memory_context_counts["memory_context_active_hooks"]),
        "memory_context_revealed_secrets": int(memory_context_counts["memory_context_revealed_secrets"]),
        "memory_context_npc_pressure_count": int(memory_context_counts["memory_context_npc_pressure_count"]),
        "memory_context_total_chars_sent": 0,
    }
    if not _live_llm_calls_enabled(settings=settings, flag_attr="play_v2_dramatic_rewrite_use_llm"):
        deterministic_output = _deterministic_compose_output(compose_input)
        invalid_reasons, rendered = _compose_invalid_reasons(
            output=deterministic_output,
            shell_tokens=shell_tokens,
        )
        if not invalid_reasons and rendered:
            diagnostics["compose_retry_count"] = 0
            diagnostics["compose_invalid_reason"] = ""
            diagnostics["narration_compose_source"] = "deterministic"
            diagnostics["length_profile"] = f"{deterministic_output.length_profile}:{_sentence_count(rendered)}"
            diagnostics["compose_latency_ms"] = round((time.perf_counter() - compose_started) * 1000, 4)
            return rendered, "deterministic", diagnostics
        invalid_label = ",".join(invalid_reasons[:4]) or "deterministic_invalid"
        if bool(getattr(settings, "internal_test_strict_no_repair_fallback", False)):
            raise RuntimeError(f"narration_compose:retry_exhausted:{invalid_label}")
        diagnostics["compose_invalid_reason"] = invalid_label
        diagnostics["fallback_reason"] = f"deterministic_invalid:{invalid_label}"
        diagnostics["narration_compose_source"] = "fallback"
        fallback_text = render_npc_texture_emergency(beat, seed, reason=invalid_label)
        diagnostics["length_profile"] = f"short:{_sentence_count(fallback_text)}"
        diagnostics["compose_latency_ms"] = round((time.perf_counter() - compose_started) * 1000, 4)
        return fallback_text, "fallback", diagnostics
    if gateway is None:
        if bool(getattr(settings, "internal_test_strict_no_repair_fallback", False)):
            raise RuntimeError("narration_compose:gateway_unavailable")
        diagnostics["fallback_reason"] = "gateway_unavailable"
        diagnostics["narration_compose_source"] = "fallback"
        fallback_text = render_npc_texture_emergency(beat, seed, reason="gateway_unavailable")
        diagnostics["compose_latency_ms"] = round((time.perf_counter() - compose_started) * 1000, 4)
        return fallback_text, "fallback", diagnostics
    max_output_tokens = int(getattr(settings, "play_v2_dramatic_rewrite_max_output_tokens", 360) or 360)
    diagnostics["memory_context_total_chars_sent"] = memory_context_chars if memory_context_prompt_section else 0
    last_invalid_label = ""
    for attempt in range(3):
        try:
            storylet_prompt_section = _storylet_hint_prompt_section(compose_input.storylet_hints)
            response = gateway._invoke_json(
                system_prompt=(
                    "你是中文都市关系戏文案作者。请基于给定事实包、style_cases 和 style_card 写一段自然叙事。"
                    "重点是口吻自然、节奏有变化、角色感清晰、现场动作细节可感。"
                    "请优先体现角色差异化表达，尽量避免重复沿用 soft_avoid_stems 里的句干。"
                    "soft_deweight_stems 是近期高频判词降权清单，请尽量换成具体动作和对话。"
                    "可参考 style_card.narrative_technique_card 选择叙述手法，避免每句都写成结论。"
                    "可参考 style_card.move_expression_hints 为同一动作切换表达路径。"
                    "可参考 style_card.voice_phrase_hints 与 voice_hints 写出口吻差异，不要原样复读 line_stub。"
                    "可参考 style_card.control_contract 体现换手感：谁先让步、代价如何落地、拒绝后如何升级、旁观者看到了什么。"
                    "即便是 comfort/flirt/ally_with 这类软动作，也要写出可观测换手，不要只停留在安抚语气。"
                    "可参考 style_card.compose_control_contract_hint_weight 与 compose_evidence_hint_weight 调整强调强度。"
                    f"{storylet_prompt_section}"
                    "不得新增角色、事件或改写既定状态结果。"
                    f"{memory_context_prompt_section}"
                    "叙事中必须自然融入 style_card.shell_tokens 中的至少一个场域关键词，场域特征要渗透到动作和对白里，不能只是装饰。"
                    "输出 JSON: {\"narration\":\"...\",\"coverage_marks\":{\"target\":true,\"move\":true,\"consequence\":true,\"relationship\":true},\"length_profile\":\"short|normal|burst\"}。"
                ),
                user_payload={
                    "compose_input": compose_input.model_dump(mode="json"),
                    "retry_mode": attempt > 0,
                    "turn_complexity": turn_complexity,
                },
                max_output_tokens=max_output_tokens,
                operation_name="play_v2.narration_compose",
                plaintext_fallback_key="narration",
            )
            payload = response.payload if isinstance(response.payload, dict) else {}
            if "narration" not in payload and payload.get("rewritten_narration"):
                payload = {
                    "narration": payload.get("rewritten_narration"),
                    "coverage_marks": payload.get("coverage_marks") or {},
                    "length_profile": payload.get("length_profile") or "normal",
                }
            output = NarrationComposeOutput.model_validate(payload)
            invalid_reasons, rendered = _compose_invalid_reasons(
                output=output,
                shell_tokens=shell_tokens if attempt < 1 else (),
            )
            if "shell_miss" in invalid_reasons:
                diagnostics["shell_miss_on_first"] = True
        except ValidationError:
            invalid_reasons = ["schema_invalid"]
            rendered = ""
        except Exception:
            invalid_reasons = ["llm_provider_failed"]
            rendered = ""
        if not invalid_reasons and rendered:
            diagnostics["compose_retry_count"] = attempt
            diagnostics["blocked_stems_hit"] = False
            diagnostics["compose_invalid_reason"] = ""
            diagnostics["fallback_reason"] = "none"
            diagnostics["length_profile"] = f"{output.length_profile}:{_sentence_count(rendered)}"
            diagnostics["compose_input_tokens"] = _usage_token_count(response.usage, "input_tokens")
            diagnostics["compose_output_tokens"] = _usage_token_count(response.usage, "output_tokens")
            diagnostics["compose_total_tokens"] = _usage_token_count(response.usage, "total_tokens")
            diagnostics["compose_latency_ms"] = round((time.perf_counter() - compose_started) * 1000, 4)
            diagnostics["narration_compose_source"] = "llm_retry" if attempt > 0 else "llm"
            return rendered, str(diagnostics["narration_compose_source"]), diagnostics
        last_invalid_label = ",".join(invalid_reasons[:4])
    diagnostics["compose_retry_count"] = 2
    diagnostics["diversity_guard_hits"] = 0
    diagnostics["compose_invalid_reason"] = last_invalid_label
    if bool(getattr(settings, "internal_test_strict_no_repair_fallback", False)):
        raise RuntimeError(f"narration_compose:retry_exhausted:{last_invalid_label or 'unknown'}")
    diagnostics["fallback_reason"] = f"retry_exhausted:{last_invalid_label or 'unknown'}"
    diagnostics["narration_compose_source"] = "fallback"
    fallback_text = render_npc_texture_emergency(beat, seed, reason=last_invalid_label)
    diagnostics["length_profile"] = f"short:{_sentence_count(fallback_text)}"
    diagnostics["compose_latency_ms"] = round((time.perf_counter() - compose_started) * 1000, 4)
    return fallback_text, "fallback", diagnostics


def _compose_burst_enhance_with_regen(
    *,
    plan: CompiledPlayPlan,
    compose_input: NarrationComposeInput,
    base_narration: str,
    gateway: PlayLLMGateway | None,
) -> tuple[str | None, dict[str, int | float | str | bool]]:
    started = time.perf_counter()
    diagnostics: dict[str, int | float | str | bool] = {
        "compose_pass2_retry_count": 0,
        "compose_pass2_invalid_reason": "",
        "compose_pass2_latency_ms": 0.0,
        "compose_pass2_input_tokens": 0,
        "compose_pass2_output_tokens": 0,
        "compose_pass2_total_tokens": 0,
        "compose_pass2_applied": False,
    }
    if gateway is None:
        diagnostics["compose_pass2_invalid_reason"] = "gateway_unavailable"
        diagnostics["compose_pass2_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
        return None, diagnostics
    if not base_narration.strip():
        diagnostics["compose_pass2_invalid_reason"] = "empty_base_narration"
        diagnostics["compose_pass2_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
        return None, diagnostics
    _, pass2_max_retry, pass2_max_output_tokens, _ = _key_burst_pass2_config(plan)
    max_attempts = 1 + max(pass2_max_retry, 0)
    last_reason = ""
    for attempt in range(max_attempts):
        try:
            response = gateway._invoke_json(
                system_prompt=(
                    "你是中文都市关系戏文案作者。"
                    "给定 pass1 文案与事实包后，请在不改事实结果的前提下，增强冲突爆点与后果外溢。"
                    "不要新增角色、不要改变动作归属，只提升临场冲击与可见代价。"
                    "输出 JSON: {\"narration\":\"...\"}。"
                ),
                user_payload={
                    "base_narration": base_narration,
                    "compose_input": compose_input.model_dump(mode="json"),
                    "retry_mode": attempt > 0,
                },
                max_output_tokens=pass2_max_output_tokens,
                operation_name="play_v2.narration_compose_pass2",
                plaintext_fallback_key="narration",
            )
            payload = response.payload if isinstance(response.payload, dict) else {}
            raw_text = str(payload.get("narration") or "")
            enhanced = _finalize_narration_style(raw_text)
            if enhanced:
                diagnostics["compose_pass2_retry_count"] = attempt
                diagnostics["compose_pass2_invalid_reason"] = ""
                diagnostics["compose_pass2_input_tokens"] = _usage_token_count(response.usage, "input_tokens")
                diagnostics["compose_pass2_output_tokens"] = _usage_token_count(response.usage, "output_tokens")
                diagnostics["compose_pass2_total_tokens"] = _usage_token_count(response.usage, "total_tokens")
                diagnostics["compose_pass2_applied"] = enhanced != base_narration
                diagnostics["compose_pass2_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
                return enhanced, diagnostics
            last_reason = "empty_narration"
        except ValidationError:
            last_reason = "schema_invalid"
        except Exception:
            last_reason = "llm_provider_failed"
    diagnostics["compose_pass2_retry_count"] = max_attempts - 1
    diagnostics["compose_pass2_invalid_reason"] = last_reason or "unknown"
    diagnostics["compose_pass2_latency_ms"] = round((time.perf_counter() - started) * 1000, 4)
    return None, diagnostics


def _reason_to_function_role(reason_family: str) -> str:
    if reason_family in {"loss_position", "blame_shift"}:
        return "strike"
    if reason_family == "self_preserve":
        return "self_preserve"
    if reason_family == "old_debt":
        return "debt_play"
    if reason_family == "opportunity_window":
        return "wait_flip"
    return "wait_flip"


def _fill_receiver_template(
    template: str | None,
    *,
    primary_name: str,
    target_name: str,
) -> str | None:
    if not template:
        return None
    return trim_text(template.replace("{primary}", primary_name).replace("{target}", target_name), 160)


def _pick_role_function_lexicon(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    supporting_reactions: tuple[SupportingReactionBeat, ...],
    primary_name: str,
    turn_index: int,
) -> dict[str, str | bool | None]:
    policy = plan.semantic_strategy_pack.role_function_lexicon_policy_v8
    segment_rule = policy.by_segment_id.get(segment.segment_id)
    if segment_rule is None:
        segment_rule = next(
            (
                item
                for item in policy.by_segment_id.values()
                if item.segment_role == segment.segment_role
            ),
            None,
        )
    if segment_rule is None:
        return {
            "counter_function_role": "wait_flip",
            "crowd_function_role": "wait_flip",
            "counter_action_verb": None,
            "crowd_action_verb": None,
            "counter_receiver_template": None,
            "crowd_receiver_template": None,
            "role_lexicon_hit": False,
        }
    reaction_by_role = {item.role: item for item in supporting_reactions}
    counter = reaction_by_role.get("counter")
    crowd = reaction_by_role.get("crowd")
    counter_role = _reason_to_function_role(counter.reason_family if counter is not None else "mixed")
    crowd_role = _reason_to_function_role(crowd.reason_family if crowd is not None else "mixed")
    if segment_rule.enforce_counter_crowd_slot_split and counter_role == crowd_role and counter_role in {"strike", "self_preserve", "debt_play", "wait_flip"}:
        fallback = next((role for role in ("self_preserve", "wait_flip", "debt_play", "strike") if role != counter_role), "wait_flip")
        crowd_role = fallback

    def _pick_entry(role_name: str, *, role: str) -> tuple[str | None, str | None]:
        entries = segment_rule.counter_entries if role == "counter" else segment_rule.crowd_entries
        entry = next((item for item in entries if item.function_role == role_name), None)
        if entry is None and entries:
            entry = entries[0]
        if entry is None:
            return None, None
        seed = sum(ord(char) for char in f"{segment.segment_id}:{role}:{turn_index}:{role_name}")
        verb = entry.verbs[seed % len(entry.verbs)] if entry.verbs else None
        tpl = entry.receiver_templates[(seed // 3) % len(entry.receiver_templates)] if entry.receiver_templates else None
        return verb, tpl

    counter_verb, counter_tpl = _pick_entry(counter_role, role="counter")
    crowd_verb, crowd_tpl = _pick_entry(crowd_role, role="crowd")
    counter_receiver = _fill_receiver_template(
        counter_tpl,
        primary_name=primary_name,
        target_name=counter.beat.target_name if counter is not None else primary_name,
    )
    crowd_receiver = _fill_receiver_template(
        crowd_tpl,
        primary_name=primary_name,
        target_name=crowd.beat.target_name if crowd is not None else primary_name,
    )
    role_hit = bool(counter_verb or counter_receiver or crowd_verb or crowd_receiver)
    return {
        "counter_function_role": counter_role,
        "crowd_function_role": crowd_role,
        "counter_action_verb": counter_verb,
        "crowd_action_verb": crowd_verb,
        "counter_receiver_template": counter_receiver,
        "crowd_receiver_template": crowd_receiver,
        "role_lexicon_hit": role_hit,
    }


def _narration_verbosity_hint(state: UrbanWorldState, segment_role: str) -> Literal["short", "medium", "long"]:
    if (
        segment_role in {"reveal", "terminal"}
        or state.last_turn_escalations
        or state.secret_exposure >= 4
        or state.scene_heat >= 5
        or state.route_lock >= 4
    ):
        return "long"
    if (
        segment_role in {"opening", "misread", "pressure"}
        and state.scene_heat <= 2
        and state.route_lock <= 2
        and state.secret_exposure <= 1
        and not state.last_turn_escalations
    ):
        return "short"
    return "medium"


def _relation_state_tag(state: UrbanWorldState, target_id: str | None) -> str:
    if not target_id:
        return "guarded"
    relation = state.relationships.get(target_id)
    if relation is None:
        return "guarded"
    if relation.trust >= 3 and relation.affection >= 2:
        return "ally"
    if relation.suspicion >= 3 or relation.tension >= 4:
        return "hostile"
    if relation.dependency >= 3:
        return "dependent"
    if relation.trust <= 0 and relation.suspicion >= 2:
        return "guarded"
    return "testing"


def _select_voice_atoms_for_turn(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    segment_role: SegmentRoleId,
) -> tuple[tuple[VoiceAtom, ...], str]:
    target_id = intent.target_id or ""
    atoms = list(plan.voice_atoms_by_character.get(target_id) or [])
    if not atoms:
        return (), "voice_atoms_missing"
    relation_tag = _relation_state_tag(state, target_id)
    secret_hot = state.secret_exposure >= 3
    heat_hot = state.scene_heat >= 4
    ranked: list[tuple[float, VoiceAtom]] = []
    for atom in atoms:
        score = effective_voice_atom_weight(
            state=state,
            character_id=target_id,
            atom=atom,
        )
        if atom.segment_role == segment_role:
            score += 0.9
        elif atom.segment_role == "terminal" and segment_role == "reveal":
            score += 0.25
        tags = set(atom.style_tags)
        if relation_tag in tags:
            score += 0.3
        if secret_hot and "high_secret" in tags:
            score += 0.25
        if heat_hot and "high_heat" in tags:
            score += 0.25
        ranked.append((score, atom))
    ranked.sort(key=lambda item: (-item[0], item[1].atom_id))
    selected = tuple(atom for _, atom in ranked[:2])
    if not selected:
        return (), "voice_atoms_rank_empty"
    return selected, "none"


def _render_narration_npc_texture_v2(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    intent_diagnostics: dict[str, Any] | None = None,
    submitted_with_selected_ids: bool = False,
    precomputed_compose: dict[str, Any] | None = None,
    gateway: PlayLLMGateway | None = None,
) -> tuple[str, dict[str, int | float | str | bool]]:
    current_segment = _resolved_segment(plan, state)
    target_member = next(
        (member for member in plan.cast if member.character_id == intent.target_id),
        None,
    )
    scene_frame = _derive_npc_scene_frame(plan, state, intent.target_id) if intent.target_id in state.npc_mind_states else None
    active_scene_frames = {
        character_id: _derive_npc_scene_frame(plan, state, character_id)
        for character_id in state.active_character_ids
        if character_id in state.npc_mind_states
    }
    beat = build_npc_reaction_beat(
        plan=plan,
        state=state,
        intent=intent,
        scene_frame=scene_frame,
    )
    seed = build_render_seed(
        member=target_member,
        state=state,
        intent=intent,
        segment_role=current_segment.segment_role,
    )
    supporting_reactions = tuple(
        build_supporting_reaction_beats(
            plan=plan,
            state=state,
            intent=intent,
            segment_id=current_segment.segment_id,
            segment_role=current_segment.segment_role,
            scene_frames_by_id=active_scene_frames,
        )
    )
    role_lexicon = _pick_role_function_lexicon(
        plan=plan,
        segment=current_segment,
        supporting_reactions=supporting_reactions,
        primary_name=beat.target_name,
        turn_index=state.turn_index,
    )
    style_hints = build_tone_example_style_hints(current_segment, state)
    style_hints = replace(
        style_hints,
        counter_function_role=str(role_lexicon.get("counter_function_role") or "wait_flip"),
        crowd_function_role=str(role_lexicon.get("crowd_function_role") or "wait_flip"),
        counter_action_verb=(
            str(role_lexicon.get("counter_action_verb"))
            if role_lexicon.get("counter_action_verb")
            else None
        ),
        crowd_action_verb=(
            str(role_lexicon.get("crowd_action_verb"))
            if role_lexicon.get("crowd_action_verb")
            else None
        ),
        counter_receiver_template=(
            str(role_lexicon.get("counter_receiver_template"))
            if role_lexicon.get("counter_receiver_template")
            else None
        ),
        crowd_receiver_template=(
            str(role_lexicon.get("crowd_receiver_template"))
            if role_lexicon.get("crowd_receiver_template")
            else None
        ),
        role_lexicon_hit=bool(role_lexicon.get("role_lexicon_hit", False)),
    )
    if state.last_turn_semantic_plan is not None:
        state.last_turn_semantic_plan = state.last_turn_semantic_plan.model_copy(
            update={
                "style_plan": state.last_turn_semantic_plan.style_plan.model_copy(
                    update={
                        "counter_function_role": style_hints.counter_function_role,
                        "crowd_function_role": style_hints.crowd_function_role,
                        "counter_action_verb": style_hints.counter_action_verb,
                        "crowd_action_verb": style_hints.crowd_action_verb,
                        "counter_receiver_template": style_hints.counter_receiver_template,
                        "crowd_receiver_template": style_hints.crowd_receiver_template,
                        "role_lexicon_hit": style_hints.role_lexicon_hit,
                    }
                )
            }
        )
    semantic_contract = _semantic_render_contract_from_plan(plan, state.last_turn_semantic_plan)
    style_hints, contract_applied = _apply_semantic_render_contract(
        style_hints=style_hints,
        contract=semantic_contract,
    )
    turn_complexity = _turn_complexity_for_compose(state=state, segment=current_segment)
    turn_input_mode: Literal["free_input", "select_id"] = (
        "select_id" if submitted_with_selected_ids else "free_input"
    )
    delta_pack_hit = state.active_beat_delta_pack.segment_id == current_segment.segment_id
    verbosity_hint = _narration_verbosity_hint(state, current_segment.segment_role)
    selected_voice_atoms, voice_fallback_reason = _select_voice_atoms_for_turn(
        plan=plan,
        state=state,
        intent=intent,
        segment_role=current_segment.segment_role,
    )
    storylet_matches = find_matching_storylets(state, plan, max_count=1, min_score=0.4)
    storylet_hints = _storylet_hints_for_compose(storylet_matches)
    storylet_match_ids = [match.storylet_id for match in storylet_matches[:3]]
    shell_tokens = tuple(unique_preserve([*style_hints.anchor_tokens, beat.arena_name]))[:8]
    if state.last_turn_semantic_plan is not None:
        state.last_turn_semantic_plan = state.last_turn_semantic_plan.model_copy(
            update={
                "style_plan": state.last_turn_semantic_plan.style_plan.model_copy(
                    update={
                        "reason_family": style_hints.primary_reason_family,
                        "counter_reason_family": style_hints.counter_reason_family,
                        "crowd_reason_family": style_hints.crowd_reason_family,
                        "signal_family": style_hints.signal_family,
                        "cost_family": style_hints.cost_family,
                        "cadence": style_hints.cadence,
                        "shell_anchor_tokens": list(style_hints.anchor_tokens[:6]),
                        "counter_function_role": style_hints.counter_function_role,
                        "crowd_function_role": style_hints.crowd_function_role,
                        "counter_action_verb": style_hints.counter_action_verb,
                        "crowd_action_verb": style_hints.crowd_action_verb,
                        "counter_receiver_template": style_hints.counter_receiver_template,
                        "crowd_receiver_template": style_hints.crowd_receiver_template,
                        "role_lexicon_hit": style_hints.role_lexicon_hit,
                    }
                )
            }
    )
    state.recent_example_bucket_ids = unique_preserve([*style_hints.used_bucket_ids, *state.recent_example_bucket_ids])[:6]
    state.recent_clause_family_ids = unique_preserve([*style_hints.used_clause_family_ids, *state.recent_clause_family_ids])[:6]
    precomputed_compose_narration, precomputed_compose_diagnostics = _sanitize_compose_payload(precomputed_compose)
    compose_prewarm_applied = bool(precomputed_compose_narration)
    if compose_prewarm_applied:
        composed_text = precomputed_compose_narration
        compose_source = "prewarm_cache"
        compose_diagnostics = dict(precomputed_compose_diagnostics)
        compose_diagnostics["narration_compose_source"] = "prewarm_cache"
    else:
        composed_text, compose_source, compose_diagnostics = _compose_narration_once_with_regen(
            plan=plan,
            segment=current_segment,
            state=state,
            intent=intent,
            beat=beat,
            seed=seed,
            style_hints=style_hints,
            supporting_reactions=supporting_reactions,
            selected_voice_atoms=selected_voice_atoms,
            voice_fallback_reason=voice_fallback_reason,
            verbosity_hint=verbosity_hint,
            turn_complexity=turn_complexity,
            turn_input_mode=turn_input_mode,
            intent_diagnostics=intent_diagnostics,
            storylet_hints=storylet_hints,
            shell_tokens=shell_tokens,
            gateway=gateway,
        )
    compose_pass_count = 1
    compose_pass2_retry_count = 0
    compose_pass2_latency_ms = 0.0
    compose_pass2_invalid_reason = ""
    compose_pass2_tokens = 0
    compose_pass2_applied = False
    compose_pass2_gate_reason = ""
    compose_budget_hit = False
    compose_pass1_latency_ms = float(compose_diagnostics.get("compose_latency_ms") or 0.0)
    settings = get_settings()
    pass2_enabled, _pass2_max_retry, _pass2_max_output_tokens, _pass2_latency_budget_ms = _key_burst_pass2_config(plan)
    pass2_gated, compose_pass2_gate_reason = _should_run_compose_pass2(
        plan=plan,
        state=state,
        segment_role=current_segment.segment_role,
        turn_complexity=turn_complexity,
    )
    pass2_allowed = (
        (not compose_prewarm_applied)
        and pass2_gated
        and pass2_enabled
        and gateway is not None
        and _live_llm_calls_enabled(settings=settings, flag_attr="play_v2_dramatic_rewrite_use_llm")
    )
    if pass2_allowed:
        pass2_compose_input = _build_narration_compose_input(
            plan=plan,
            segment=current_segment,
            state=state,
            intent=intent,
            beat=beat,
            style_hints=style_hints,
            supporting_reactions=supporting_reactions,
            selected_voice_atoms=selected_voice_atoms,
            verbosity_hint=verbosity_hint,
            turn_complexity="key_burst",
            turn_input_mode=turn_input_mode,
            intent_diagnostics=intent_diagnostics,
            storylet_hints=storylet_hints,
        )
        enhanced_text, pass2_diagnostics = _compose_burst_enhance_with_regen(
            plan=plan,
            compose_input=pass2_compose_input,
            base_narration=composed_text,
            gateway=gateway,
        )
        compose_pass_count = 2
        compose_pass2_retry_count = int(pass2_diagnostics.get("compose_pass2_retry_count") or 0)
        compose_pass2_invalid_reason = str(pass2_diagnostics.get("compose_pass2_invalid_reason") or "")
        compose_pass2_latency_ms = float(pass2_diagnostics.get("compose_pass2_latency_ms") or 0.0)
        compose_pass2_tokens = int(pass2_diagnostics.get("compose_pass2_total_tokens") or 0)
        compose_pass2_applied = bool(pass2_diagnostics.get("compose_pass2_applied") or False)
        if enhanced_text:
            composed_text = enhanced_text
            if compose_pass2_applied:
                compose_source = "llm_pass2"
    if compose_prewarm_applied:
        compose_pass_count = int(compose_diagnostics.get("compose_pass_count") or 1)
        compose_pass2_retry_count = int(compose_diagnostics.get("compose_pass2_retry_count") or 0)
        compose_pass2_latency_ms = float(compose_diagnostics.get("compose_pass2_latency_ms") or 0.0)
        compose_pass2_invalid_reason = str(compose_diagnostics.get("compose_pass2_invalid_reason") or "")
        compose_pass2_gate_reason = str(compose_diagnostics.get("compose_pass2_gate_reason") or compose_pass2_gate_reason)
        compose_pass2_applied = bool(
            compose_diagnostics.get("compose_pass2_applied")
            or compose_pass_count > 1
        )
        compose_pass1_latency_ms = float(compose_diagnostics.get("compose_pass1_latency_ms") or 0.0)
    render_tag = "render:semantic_contract" if contract_applied else "render:semantic_fallback"
    tags = unique_preserve(
        [
            *state.last_turn_tags,
            f"dramatic_mode:{style_hints.dramatic_mode}",
            f"narration_compose:{compose_source}",
            render_tag,
            *(f"clause_family:{item}" for item in style_hints.used_clause_family_ids[:2]),
        ]
    )
    causal_priority_tags = [tag for tag in state.last_turn_tags if tag.startswith("causal:")][:2]
    if render_tag in tags:
        tags.remove(render_tag)
    tags.insert(0, render_tag)
    insert_at = 1
    for causal_tag in causal_priority_tags:
        if causal_tag in tags:
            tags.remove(causal_tag)
        tags.insert(insert_at, causal_tag)
        insert_at += 1
    state.last_turn_tags = tags[:8]
    compose_input_tokens_submit = 0 if compose_prewarm_applied else int(compose_diagnostics.get("compose_input_tokens") or 0)
    compose_output_tokens_submit = 0 if compose_prewarm_applied else int(compose_diagnostics.get("compose_output_tokens") or 0)
    compose_total_tokens_submit = (
        0
        if compose_prewarm_applied
        else int(compose_diagnostics.get("compose_total_tokens") or 0) + compose_pass2_tokens
    )
    compose_latency_submit_ms = (
        0.0
        if compose_prewarm_applied
        else round(compose_pass1_latency_ms + compose_pass2_latency_ms, 4)
    )
    merged_diagnostics: dict[str, int | float | str | bool] = {
        "selected_style_case_ids": str(
            compose_diagnostics.get("selected_style_case_ids")
            or ",".join(style_hints.style_case_ids)
        ),
        "soft_avoid_stems": str(compose_diagnostics.get("soft_avoid_stems") or ""),
        "soft_deweight_stems": str(compose_diagnostics.get("soft_deweight_stems") or ""),
        "narrative_technique_id": str(compose_diagnostics.get("narrative_technique_id") or ""),
        "diversity_guard_hits": int(compose_diagnostics.get("diversity_guard_hits") or 0),
        "pattern_guard_hits": int(compose_diagnostics.get("pattern_guard_hits") or 0),
        "compose_retry_count": int(compose_diagnostics.get("compose_retry_count") or 0),
        "blocked_stems": str(compose_diagnostics.get("blocked_stems") or ""),
        "blocked_stems_hit": bool(compose_diagnostics.get("blocked_stems_hit") or False),
        "compose_invalid_reason": str(compose_diagnostics.get("compose_invalid_reason") or ""),
        "length_profile": str(compose_diagnostics.get("length_profile") or ""),
        "selected_voice_atom_ids": str(
            compose_diagnostics.get("selected_voice_atom_ids")
            or ",".join(atom.atom_id for atom in selected_voice_atoms[:2])
        ),
        "voice_fallback_reason": str(compose_diagnostics.get("voice_fallback_reason") or voice_fallback_reason),
        "fallback_reason": str(
            compose_diagnostics.get("fallback_reason")
            or "none"
        ),
        "narration_compose_source": str(compose_diagnostics.get("narration_compose_source") or compose_source),
        "compose_latency_ms": compose_latency_submit_ms,
        "compose_input_tokens": compose_input_tokens_submit,
        "compose_output_tokens": compose_output_tokens_submit,
        "compose_total_tokens": compose_total_tokens_submit,
        "turn_complexity": turn_complexity,
        "turn_input_mode": turn_input_mode,
        "compose_pass_count": compose_pass_count,
        "compose_pass2_retry_count": compose_pass2_retry_count,
        "compose_pass1_latency_ms": round(compose_pass1_latency_ms, 4),
        "compose_pass2_latency_ms": round(compose_pass2_latency_ms, 4),
        "compose_pass2_invalid_reason": compose_pass2_invalid_reason,
        "compose_pass2_gate_reason": compose_pass2_gate_reason,
        "compose_budget_hit": compose_budget_hit,
        "delta_pack_hit": delta_pack_hit,
        "compose_pass2_applied": compose_pass2_applied,
        "compose_prewarm_applied": compose_prewarm_applied,
        "compose_prewarm_source": str(compose_diagnostics.get("compose_prewarm_source") or ""),
        "compose_prewarm_total_tokens": int(compose_diagnostics.get("compose_total_tokens") or 0),
        "storylet_matches_count": len(storylet_match_ids),
        "memory_context_active_hooks": int(compose_diagnostics.get("memory_context_active_hooks") or 0),
        "memory_context_revealed_secrets": int(compose_diagnostics.get("memory_context_revealed_secrets") or 0),
        "memory_context_npc_pressure_count": int(compose_diagnostics.get("memory_context_npc_pressure_count") or 0),
        "memory_context_total_chars_sent": int(compose_diagnostics.get("memory_context_total_chars_sent") or 0),
    }
    merged_diagnostics["storylet_matches_ids"] = list(storylet_match_ids)
    return composed_text, merged_diagnostics


def _render_narration(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    intent_diagnostics: dict[str, Any] | None = None,
    submitted_with_selected_ids: bool = False,
    precomputed_compose: dict[str, Any] | None = None,
    gateway: PlayLLMGateway | None = None,
) -> tuple[str, dict[str, int | float | str | bool]]:
    rendered, diagnostics = _render_narration_npc_texture_v2(
        plan,
        state,
        intent,
        intent_diagnostics=intent_diagnostics,
        submitted_with_selected_ids=submitted_with_selected_ids,
        precomputed_compose=precomputed_compose,
        gateway=gateway,
    )
    return _finalize_narration_style(rendered), diagnostics


def _build_progress_summary(plan: CompiledPlayPlan, state: UrbanWorldState) -> str:
    segment = _resolved_segment(plan, state)
    threshold = _segment_threshold(segment)
    triggered = state.last_turn_escalations[0] if state.last_turn_escalations else None
    question_suffix = ""
    if state.last_turn_scene_question_state is not None:
        question_state = state.last_turn_scene_question_state
        if question_state.status == "resolved":
            question_suffix = f" {question_state.summary}后续后果会沿着既定站位继续回咬。"
        elif question_state.status == "flip":
            question_suffix = f" {question_state.summary}下一句基本会逼出更明确的站边或翻脸。"
        elif question_state.status == "tightening":
            question_suffix = f" {question_state.summary}场面正在收紧，留给双方回撤的空间在变窄。"
    intent_prefix = f"{state.last_turn_intent_feedback[0]} " if state.last_turn_intent_feedback else ""
    if triggered is not None:
        if triggered.kind == "relationship_debt":
            return trim_text(f"{intent_prefix}你之前压下去的那笔旧账已经开始回头咬人了，后面不是还能不能稳，而是谁先被这笔账拖下去。{question_suffix}", 220)
        if triggered.kind == "public_wave":
            return trim_text(f"{intent_prefix}场外的风向已经自己炸开了，后面每一句都不只是在对人说，也是在喂给整个场面。{question_suffix}", 220)
        if triggered.kind == "secret_pressure":
            return trim_text(f"{intent_prefix}最不该见光的东西已经自己拱开口子了，后面不是压不压得住，而是谁先被它拖下水。{question_suffix}", 220)
        if triggered.kind == "npc_action":
            return trim_text(f"{intent_prefix}你这一手刚落地，别人就顺着发酵的局势先动了，后面不会再只按你的节奏走。{question_suffix}", 220)
    if state.last_turn_latent_feedback:
        latent_text = " ".join(state.last_turn_latent_feedback[:1])
        if not any(token in latent_text for token in ("发酵", "记账", "没过去", "变重", "轮到")):
            latent_text = trim_text(f"{latent_text} 这条线还在发酵变重，账没过去。", 220)
        return trim_text(f"{latent_text}{question_suffix}", 220)
    if state.last_turn_intent_feedback:
        return trim_text(f"{' '.join(state.last_turn_intent_feedback[:2])}{question_suffix}", 220)
    if question_suffix:
        return trim_text(question_suffix.strip(), 220)
    if state.public_event_ids and state.secret_exposure >= 3:
        return trim_text("这一手已经把最不该见光的东西拖成公开事件了，后面不是还能不能压住，而是谁先被这场面吞掉。", 220)
    if state.scene_heat >= 5 and state.route_lock >= 3:
        return trim_text("场面已经烧穿到谁都没法装中立的位置，站边和翻脸都只剩最后那一下。", 220)
    if max(state.relationship_debt_pressure, state.public_wave_pressure, state.secret_pressure, state.npc_action_pressure) >= 4:
        return trim_text("有一类后果已经快养熟了，接下来你不是在选说什么，而是在选先让哪颗雷咬回来。", 220)
    if state.route_lock >= 3:
        return trim_text("站边已经被你钉得很死，后面再开口，不是表忠就是翻脸。", 220)
    if state.scene_heat >= 4:
        return trim_text("场面已经被你推到再多一句就会当场翻车的位置，谁都不可能全身而退。", 220)
    if state.segment_progress >= max(threshold - 1, 1):
        return trim_text("这一段已经被你推到临门一脚，接下来不是摊牌，就是有人先失态。", 220)
    return trim_text("这一下已经把关系、站边和风向都往疼处拧了一格，下一句只会更重。", 220)


def _post_submit_llm_call_count(diagnostics: dict[str, int | float | str | bool]) -> int:
    count = 0
    intent_status = str(diagnostics.get("intent_llm_status") or "").strip()
    micro_status = str(diagnostics.get("micro_sim_status") or "").strip()
    compose_source = str(diagnostics.get("narration_compose_source") or "").strip()
    compose_pass_count = int(diagnostics.get("compose_pass_count") or 1)
    compose_prewarm_hit = bool(diagnostics.get("compose_prewarm_hit") or False)
    if intent_status == "completed":
        count += 1
    if micro_status == "completed":
        count += 1
    if compose_source.startswith("llm") and not compose_prewarm_hit:
        count += 1
    if compose_pass_count > 1 and not compose_prewarm_hit:
        count += 1
    return count


def run_turn(
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    input_text: str,
    *,
    selected_suggestion_id: str | None = None,
    selected_story_action_id: str | None = None,
    selected_control_action_id: str | None = None,
    control_action: LatentEventControl | None = None,
    control_target_kind: str | None = None,
    control_target_id: str | None = None,
    control_target_mode: str | None = None,
    precomputed_intent: UrbanTurnIntent | None = None,
    precomputed_micro_sim: Any | None = None,
    precomputed_intent_diagnostics: dict[str, Any] | None = None,
    precomputed_compose: dict[str, Any] | None = None,
    prefetched_suggestions: tuple[UrbanSuggestedAction, ...] | None = None,
    prefetched_control_actions: tuple[UrbanControlAction, ...] | None = None,
    draft_usage: dict[str, int] | None = None,
    draft_call_count: int = 0,
    draft_intent_status: str = "not_requested",
    compose_prewarm_status: str = "not_requested",
    compose_prewarm_wait_ms: float = 0.0,
    compose_prewarm_source: str = "",
    compose_prewarm_total_tokens: int = 0,
    typing_phase_prewarm_tokens: int = 0,
    read_phase_prewarm_tokens: int = 0,
    typing_final_draft_seen: bool = False,
    typing_scope_cleared_count: int = 0,
    compose_prewarm_stale_fragment_count: int = 0,
) -> UrbanTurnResult:
    settings = get_settings()
    submitted_with_selected_ids = bool(
        (selected_story_action_id or "").strip() or (selected_suggestion_id or "").strip()
    )
    delta_pack_diagnostics = poll_and_apply_pending_delta_pack(plan=plan, state=state)
    gateway: PlayLLMGateway | None = None
    gateway_acquire_wait_ms = 0.0
    needs_live_gateway = (
        _live_llm_calls_enabled(settings=settings, flag_attr="play_v2_intent_compiler_use_llm")
        or _live_llm_calls_enabled(settings=settings, flag_attr="play_v2_micro_sim_use_llm")
        or _live_llm_calls_enabled(settings=settings, flag_attr="play_v2_dramatic_rewrite_use_llm")
    )
    if needs_live_gateway:
        gateway_started = time.perf_counter()
        try:
            gateway = get_play_llm_gateway(settings)
        except PlayGatewayError:
            gateway = None
        gateway_acquire_wait_ms = round((time.perf_counter() - gateway_started) * 1000, 4)
    intent, micro_sim, _intent_diagnostics = run_intent_stage(
        plan,
        state,
        input_text,
        gateway=gateway,
        selected_suggestion_id=selected_suggestion_id,
        selected_story_action_id=selected_story_action_id,
        selected_control_action_id=selected_control_action_id,
        control_action=control_action,
        control_target_kind=control_target_kind,
        control_target_id=control_target_id,
        control_target_mode=control_target_mode,
        precomputed_intent=precomputed_intent,
        precomputed_micro_sim=precomputed_micro_sim,
        precomputed_diagnostics=precomputed_intent_diagnostics,
        prefetched_suggestions=prefetched_suggestions,
        prefetched_control_actions=prefetched_control_actions,
    )
    _intent_diagnostics["gateway_acquire_wait_ms"] = gateway_acquire_wait_ms
    state, consequence_tags = apply_turn_resolution(
        plan,
        state,
        intent,
        micro_sim=micro_sim,
    )
    resolved_segment = _resolved_segment(plan, state)
    render_state = state.model_copy(deep=True)
    narration, narration_diagnostics = _render_narration(
        plan,
        render_state,
        intent,
        intent_diagnostics=_intent_diagnostics,
        submitted_with_selected_ids=submitted_with_selected_ids,
        precomputed_compose=precomputed_compose,
        gateway=gateway,
    )
    if state.last_turn_semantic_plan is not None and render_state.last_turn_semantic_plan is not None:
        state.last_turn_semantic_plan = state.last_turn_semantic_plan.model_copy(
            update={
                "style_plan": render_state.last_turn_semantic_plan.style_plan.model_copy(deep=True),
            }
        )
    state.recent_example_bucket_ids = list(render_state.recent_example_bucket_ids[:6])
    state.recent_clause_family_ids = list(render_state.recent_clause_family_ids[:6])
    render_semantic_tag = next((tag for tag in render_state.last_turn_tags if isinstance(tag, str) and tag.startswith("render:")), None)
    if render_semantic_tag:
        state.last_turn_tags = _finalize_last_turn_tags(
            latent_ops=[],
            consequence_tags=list(state.last_turn_tags),
            required_tags=[render_semantic_tag],
        )
    narration = _commit_semantic_style_after_render(
        plan=plan,
        state=state,
        narration=narration,
    )
    narration, invariant_tags = InvariantValidator.validate_and_patch(
        plan=plan,
        segment=resolved_segment,
        state=state,
        narration=narration,
    )
    if invariant_tags:
        state.last_turn_tags = unique_preserve([*state.last_turn_tags, *invariant_tags])[:8]
    if state.last_turn_public_event_text:
        state.last_turn_consequences = unique_preserve(
            [state.last_turn_public_event_text, *state.last_turn_consequences]
        )[:8]
    if state.last_turn_semantic_plan is not None and state.last_turn_semantic_plan.style_plan.key_segment:
        style_tag = (
            "style:key_segment_shell_anchor_hit"
            if state.last_turn_semantic_plan.style_plan.shell_anchor_hit
            else "style:key_segment_shell_anchor_miss"
        )
        state.last_turn_tags = unique_preserve([*state.last_turn_tags, style_tag])[:8]
    state.last_turn_story_debug_summary = _story_debug_summary(state)
    segment_advanced = advance_segment_if_ready(plan, state)
    ending_triggered, _, _ = judge_ending(plan, state)
    if ending_triggered:
        clear_delta_pack_future(state.session_id)
    if segment_advanced and not ending_triggered:
        scheduled_delta_diagnostics = schedule_next_beat_delta_pack(plan=plan, state=state)
        for key, value in scheduled_delta_diagnostics.items():
            delta_pack_diagnostics[key] = value
    story_actions = [] if ending_triggered else build_suggested_actions(plan, state)
    control_actions = [] if ending_triggered else build_control_actions(plan, state)
    suggested_actions = story_actions
    pattern_redact_terms = tuple(
        unique_preserve(
            [
                *(member.display_name for member in plan.cast),
                plan.social_arena,
                "镜头",
                "热搜",
                "公屏",
                "台下",
                "评审",
                "名额",
                "主桌",
                "会议室",
            ]
        )
    )
    next_fingerprints, next_phrases, next_pattern_fingerprints = append_narration_history(
        recent_fingerprints=tuple(state.recent_narration_fingerprints),
        recent_phrases=tuple(state.recent_narration_phrases),
        recent_pattern_fingerprints=tuple(state.recent_narration_pattern_fingerprints),
        narration=narration,
        max_recent=_NARRATION_HISTORY_WINDOW,
        pattern_redact_terms=pattern_redact_terms,
    )
    state.narration = narration
    state.story_actions = story_actions
    state.control_actions = control_actions
    state.suggested_actions = suggested_actions
    state.recent_narration_fingerprints = next_fingerprints
    state.recent_narration_phrases = next_phrases
    state.recent_narration_pattern_fingerprints = next_pattern_fingerprints
    expected_event_phrase = canonicalize_phrase(narration)[:320]
    append_narration_event(
        state,
        turn_index=state.turn_index,
        narration=narration,
        move_family=intent.move_family,
        target_id=intent.target_id or "",
    )
    relationship_deltas_payload: dict[str, dict[str, float]] = {}
    raw_relationship_deltas = getattr(state, "last_turn_relationship_deltas", {}) or {}
    if isinstance(raw_relationship_deltas, dict):
        for character_id, raw_deltas in raw_relationship_deltas.items():
            if not isinstance(raw_deltas, dict):
                continue
            normalized_deltas: dict[str, float] = {}
            for dimension, raw_value in raw_deltas.items():
                if dimension not in _MEMORY_CONTEXT_RELATION_DIMENSIONS:
                    continue
                try:
                    normalized_deltas[str(dimension)] = float(raw_value)
                except Exception:
                    continue
            if normalized_deltas:
                relationship_deltas_payload[str(character_id)] = normalized_deltas
    if state.narration_event_log:
        last_event = state.narration_event_log[-1]
        if last_event.turn_index == state.turn_index and last_event.phrase == expected_event_phrase:
            state.narration_event_log[-1] = last_event.model_copy(
                update={"relationship_deltas": relationship_deltas_payload}
            )
    progress_summary = _build_progress_summary(plan, state)
    intent_stage_diagnostics: dict[str, int | float | str | bool] = {}
    for key, value in dict(_intent_diagnostics or {}).items():
        if isinstance(value, bool):
            intent_stage_diagnostics[key] = value
        elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
            intent_stage_diagnostics[key] = value
    for key, value in dict(narration_diagnostics or {}).items():
        if isinstance(value, bool):
            intent_stage_diagnostics[key] = value
        elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
            intent_stage_diagnostics[key] = value
    for key, value in dict(delta_pack_diagnostics or {}).items():
        if isinstance(value, bool):
            intent_stage_diagnostics[key] = value
        elif isinstance(value, (int, float, str)) and not isinstance(value, bool):
            intent_stage_diagnostics[key] = value
    storylet_matches_ids = narration_diagnostics.get("storylet_matches_ids")
    if isinstance(storylet_matches_ids, list):
        intent_stage_diagnostics["storylet_matches_ids"] = [
            str(item).strip()
            for item in storylet_matches_ids
            if str(item).strip()
        ][:3]
    intent_stage_diagnostics["storylet_matches_count"] = int(
        narration_diagnostics.get("storylet_matches_count") or 0
    )
    hook_callback_tags = [
        tag
        for tag in state.last_turn_tags
        if isinstance(tag, str) and tag.startswith("callback_fired:hook_")
    ]
    if hook_callback_tags:
        intent_stage_diagnostics["hook_callbacks_fired"] = json.dumps(hook_callback_tags, ensure_ascii=False)
        intent_stage_diagnostics["hook_callbacks_fired_count"] = len(hook_callback_tags)
    draft_payload = dict(draft_usage or {})
    draft_input_tokens = int(draft_payload.get("input_tokens", 0) or 0)
    draft_output_tokens = int(draft_payload.get("output_tokens", 0) or 0)
    draft_total_tokens = int(draft_payload.get("total_tokens", 0) or 0)
    if draft_total_tokens <= 0:
        draft_total_tokens = max(draft_input_tokens + draft_output_tokens, 0)
    resolved_compose_prewarm_total_tokens = max(int(compose_prewarm_total_tokens or 0), 0)
    resolved_typing_phase_prewarm_tokens = max(int(typing_phase_prewarm_tokens or 0), 0)
    resolved_read_phase_prewarm_tokens = max(int(read_phase_prewarm_tokens or 0), 0)
    intent_stage_diagnostics["draft_intent_status"] = str(draft_intent_status or "not_requested")
    intent_stage_diagnostics["draft_call_count"] = max(int(draft_call_count or 0), 0)
    intent_stage_diagnostics["draft_input_tokens"] = max(draft_input_tokens, 0)
    intent_stage_diagnostics["draft_output_tokens"] = max(draft_output_tokens, 0)
    intent_stage_diagnostics["draft_total_tokens"] = max(draft_total_tokens, 0)
    intent_stage_diagnostics["compose_prewarm_status"] = str(compose_prewarm_status or "not_requested")
    intent_stage_diagnostics["compose_prewarm_hit"] = str(compose_prewarm_status or "").strip().lower() == "ready"
    intent_stage_diagnostics["compose_prewarm_wait_ms"] = round(max(float(compose_prewarm_wait_ms or 0.0), 0.0), 4)
    intent_stage_diagnostics["compose_prewarm_source"] = str(compose_prewarm_source or "")
    intent_stage_diagnostics["compose_prewarm_total_tokens"] = resolved_compose_prewarm_total_tokens
    intent_stage_diagnostics["typing_final_draft_seen"] = bool(typing_final_draft_seen)
    intent_stage_diagnostics["typing_scope_cleared_count"] = max(int(typing_scope_cleared_count or 0), 0)
    intent_stage_diagnostics["compose_prewarm_stale_fragment_count"] = max(
        int(compose_prewarm_stale_fragment_count or 0), 0
    )
    intent_stage_total_tokens = int(intent_stage_diagnostics.get("intent_stage_total_tokens") or 0)
    compose_total_tokens = int(intent_stage_diagnostics.get("compose_total_tokens") or 0)
    pre_submit_total_tokens = max(
        draft_total_tokens + resolved_typing_phase_prewarm_tokens + resolved_read_phase_prewarm_tokens,
        0,
    )
    post_submit_total_tokens = max(intent_stage_total_tokens + compose_total_tokens, 0)
    intent_stage_diagnostics["read_phase_prewarm_tokens"] = resolved_read_phase_prewarm_tokens
    intent_stage_diagnostics["typing_phase_prewarm_tokens"] = resolved_typing_phase_prewarm_tokens
    intent_stage_diagnostics["submit_phase_tokens"] = post_submit_total_tokens
    intent_stage_diagnostics["pre_submit_total_tokens"] = pre_submit_total_tokens
    intent_stage_diagnostics["post_submit_total_tokens"] = post_submit_total_tokens
    intent_stage_diagnostics["play_turn_total_tokens"] = pre_submit_total_tokens + post_submit_total_tokens
    post_submit_llm_calls = _post_submit_llm_call_count(intent_stage_diagnostics)
    intent_stage_diagnostics["post_submit_llm_calls"] = post_submit_llm_calls
    intent_stage_diagnostics["single_llm_call_after_submit"] = post_submit_llm_calls <= 1
    return UrbanTurnResult(
        plan=plan,
        state=state,
        narration=narration,
        story_actions=story_actions,
        control_actions=control_actions,
        suggested_actions=suggested_actions,
        triggered_latent_event=(state.last_turn_escalations[0] if state.last_turn_escalations else None),
        latent_radar=list(state.latent_radar[:4]),
        control_resolution=state.last_turn_control_resolution,
        segment_advanced=segment_advanced,
        ending_triggered=ending_triggered,
        consequence_tags=consequence_tags[:8],
        progress_summary=progress_summary,
        intent=intent,
        intent_stage_diagnostics=intent_stage_diagnostics,
    )


def run_smoke_playthrough(
    plan: CompiledPlayPlan,
    *,
    scripted_turns: list[str] | None = None,
) -> list[UrbanTurnResult]:
    state = build_initial_world_state(plan)
    scripted = scripted_turns or [
        "先试探最危险的人手里到底握着什么秘密",
        "我选择和他站队，但先不公开表态",
        "把真正的录音当众说破",
        "对他私下坦白我真正的目的",
        "如果还没结束，就逼所有人现在给答案",
    ]
    results: list[UrbanTurnResult] = []
    for turn_text in scripted:
        if state.status == "completed" or state.turn_index >= plan.max_turns:
            break
        result = run_turn(plan, state, turn_text)
        results.append(result)
        state = result.state
    while state.status != "completed" and state.turn_index < plan.max_turns:
        suggestions = build_suggested_actions(plan, state)
        if not suggestions:
            break
        result = run_turn(plan, state, suggestions[0].prompt, selected_suggestion_id=suggestions[0].suggestion_id)
        results.append(result)
        state = result.state
    return results
