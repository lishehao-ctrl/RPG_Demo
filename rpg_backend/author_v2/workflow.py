from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from typing_extensions import TypedDict

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author.normalize import normalize_whitespace, slugify, trim_text, unique_preserve
from rpg_backend.author_v2.contracts import (
    AcceptedBlueprint,
    AuthorDecisionSnapshot,
    ArcTemplateId,
    BeatDeltaComposePayloadHintBundle,
    BeatDeltaKernel,
    BeatDeltaMicroSimHintBundle,
    BeatDeltaPack,
    BeatDeltaTurnCard,
    BoundIPCastMember,
    CausalContractPolicy,
    CausalContractRule,
    CallbackCommitPolicyV2,
    CallbackPolicy,
    CallbackPolicyRule,
    CastSlotPlan,
    CompiledToneExamplePack,
    CompiledPlayPlan,
    CompiledSegment,
    CostOwnershipPolicy,
    CostPrimaryDriverPolicyV7,
    CostPrimaryDriverSegmentRuleV7,
    CostEscalationLadderPolicyV8,
    CostEscalationLadderSegmentRuleV8,
    CostNarrativeBindingPolicy,
    CostNarrativeBindingSegmentRule,
    CostReturnPolicy,
    CostReturnSegmentRule,
    ControlSignaturePolicyV8,
    ControlSignatureRuleV8,
    CostOwnershipMatrixV2,
    CostOwnershipRule,
    CostIntensityProfile,
    CostVisibilityContract,
    CostVisibilitySegmentRule,
    CostRoutingMatrixPolicy,
    CostRoutingRule,
    EndingMatrix,
    FrozenCandidatePool,
    FrozenSlotCandidate,
    InvariantPolicy,
    PlayLengthPresetId,
    PropagationPriorityBySegment,
    QuestionArcPolicyV2,
    QuestionArcSegmentPolicyV2,
    QuestionProgressPolicy,
    QuestionProgressPolicyV2,
    QuestionProgressSegmentRuleV2,
    QualityTuningProfile,
    PlayQualityTuningProfile,
    ReasonFamilyPriorityPolicy,
    RelationshipSceneFrame,
    RoleDivergenceMatrix,
    RoleDivergenceSegmentRule,
    RoleDivergenceMatrixV2,
    RoleDivergenceSegmentRuleV2,
    RoleFunctionLexiconEntry,
    RoleFunctionLexiconPolicyV8,
    RoleFunctionLexiconSegmentRuleV8,
    RouteEndingSpec,
    SegmentStyleProfile,
    SegmentInterestPolicy,
    SegmentInterestPolicyItem,
    SegmentContract,
    SegmentPlaybook,
    SegmentPlaybookDelta,
    SegmentRoleId,
    SegmentSuggestionLane,
    ShellPropagationEdgePolicy,
    ShellPropagationGraphPolicy,
    ShellSignalGraphV2,
    StakeAxisPriorityPolicy,
    StyleRegister,
    StyleRegisterSegmentRule,
    SupportingDivergencePolicy,
    SupportingReasonPair,
    SuggestionLaneId,
    ToneExampleLine,
    ToneCadence,
    ToneCostFamily,
    ToneReasonFamily,
    ToneSignalFamily,
    ToneSceneExample,
    TurnSemanticStrategyPack,
    AuthorQualityTuningProfile,
    UtilityWeightProfile,
    PropagationPriorityPolicy,
    VoiceAtom,
    VoiceAtomDelta,
    VoiceAtomsDelta,
    UrbanAuthorBundle,
    UrbanPipelineResult,
)
from rpg_backend.author_v2.gateway import (
    AuthorV2LLMGateway,
    AuthorV2RunMode,
    get_author_v2_llm_gateway,
    resolve_author_v2_live_mode_chain,
)
from rpg_backend.author_v2.ip_library import (
    bind_slots_to_ip_cast_with_candidate_pool,
    build_slot_candidate_pool,
)
from rpg_backend.author_v2.template_library import get_template_spec, is_hero_template
from rpg_backend.author_v2.stage_utils import (
    MAX_STAGE_REGEN_ATTEMPTS,
    append_quality_trace,
    extend_llm_trace as extend_stage_llm_trace,
    fallback_reason,
    is_provider_failure,
    retry_exhausted_outcome,
)
from rpg_backend.config import get_settings

_MAINLINE_LIVE_MODES = {"live_priority", "mainline_live"}
_PURE_GPT_SEGMENT_PLAYBOOK_TIMEOUT_SECONDS = 12.0
_SEGMENT_PLAYBOOK_TEXT_MAX_CHARS = 220
_SEGMENT_PLAYBOOK_RENDER_CUE_MAX_ITEMS = 5
_SEGMENT_PLAYBOOK_RENDER_CUE_ITEM_MAX_CHARS = 56
_VOICE_LINE_STUB_SEED_MAX_CHARS = 96
_VOICE_BATCH_SIZE_DEFAULT = 3
_VOICE_BATCH_SIZE_STRICT = 2
_HERO_MAX_OUTPUT_TOKENS = {
    "segment_playbook": 2200,
}

SEGMENT_PLAYBOOK_SYSTEM_PROMPT = """
你在为都市关系戏编译单段 segment playbook。
请只返回一个 JSON 对象，字段必须与 SegmentPlaybookDelta 一致。

规则：
- scene_goal / emotional_goal / move_priorities / segment_id / scene_active_cap 都是锁定字段，不要输出。
- 只允许改写：public_pressure_cue、private_pressure_cue、progression_rule_summary、render_cues。
- public_pressure_cue/private_pressure_cue/progression_rule_summary 每条最多 220 字。
- render_cues 最多 5 项，每项不超过 56 字。
- reveal / terminal 段必须强化公开失控、关系反转和代价感。
- progression_rule_summary 与 render_cues 优先体现“换手合同线索”：谁先让步、代价落在哪、拒绝后怎么升级、旁观者看到了什么。
- 输出必须具体、世俗、可传播，不要空泛。
- 不要输出 markdown，不要解释。
""".strip()

VOICE_ATOM_SYSTEM_PROMPT = """
你在为都市关系戏生成角色 voice atoms。
请只返回 JSON 对象：{"voice_atom_deltas_by_character": {"character_id": [...]}}。
数组元素字段必须与 VoiceAtomDelta 一致。

规则：
- 只处理本次 batch 给出的角色；返回角色集合必须与 batch_character_ids 完全一致。
- 只能改写输入中提供的 atom_id，不得新增 atom_id 或伪造角色 ID。
- line_stub 必须是可直接落地的中文短句，不要模板化，不要英文标签。
- catchphrase_hint 可为空；forbidden_terms 只放需要规避的词；weight 留空时沿用原值。
- 不要输出 markdown，不要解释。
""".strip()

SEGMENT_ROLE_ORDER: dict[ArcTemplateId, list[str]] = {
    "short_3": ["opening", "reveal", "terminal"],
    "compact_4": ["opening", "misread", "reveal", "terminal"],
    "standard_4": ["opening", "misread", "reveal", "terminal"],
    "long_5": ["opening", "misread", "pressure", "reveal", "terminal"],
    "flagship_6": ["opening", "misread", "pressure", "reversal", "reveal", "terminal"],
    "super_flagship_8": ["opening", "misread", "pressure", "reversal", "pressure", "reversal", "reveal", "terminal"],
}

PROGRESS_REQUIRED_BY_TEMPLATE: dict[ArcTemplateId, list[int]] = {
    "short_3": [4, 5, 4],
    "compact_4": [4, 5, 5, 4],
    "standard_4": [4, 5, 6, 4],
    "long_5": [4, 5, 6, 6, 4],
    "flagship_6": [4, 5, 6, 6, 5, 4],
    "super_flagship_8": [4, 5, 6, 6, 6, 6, 5, 4],
}

MOVE_FAMILIES_BY_ROLE: dict[str, list[RelationshipMoveFamily]] = {
    "opening": ["flirt", "comfort", "probe_secret", "accuse"],
    "misread": ["flirt", "jealousy_trigger", "deflect", "ally_with"],
    "pressure": ["accuse", "ally_with", "betray", "probe_secret"],
    "reversal": ["ally_with", "betray", "private_confession", "probe_secret"],
    "reveal": ["probe_secret", "public_reveal", "private_confession", "accuse"],
    "terminal": ["public_reveal", "private_confession", "ally_with", "betray"],
}

_SHELL_SURFACE_SIGNALS: dict[str, tuple[str, str, str]] = {
    "wealth_families": ("主桌顺位", "家宴体面", "继承名分"),
    "office_power": ("牌桌位置", "会议话语权", "背锅名单"),
    "entertainment_scandal": ("镜头风向", "热搜卡位", "商务切割"),
    "campus_romance": ("评审名额", "同圈口碑", "社团站队"),
    "urban_supernatural": ("夜色契约", "命运旧债", "失控异象"),
}

_SHELL_PUBLIC_COST_SIGNALS: dict[str, str] = {
    "wealth_families": "公开失去体面和顺位",
    "office_power": "公开失去位置和话语权",
    "entertainment_scandal": "公开失去镜头和商业价值",
    "campus_romance": "公开失去名额和前途",
    "urban_supernatural": "公开失去体面生活和现实退路",
}

_SHELL_RELATIONSHIP_BACKLASH_SIGNALS: dict[str, str] = {
    "wealth_families": "关系账会反噬成家族翻脸",
    "office_power": "关系账会反噬成职场切割",
    "entertainment_scandal": "关系账会反噬成舆论反扑",
    "campus_romance": "关系账会反噬成圈层孤立",
    "urban_supernatural": "关系账会反噬成旧债追身",
}

_HIGH_RISK_MOVE_FAMILIES: set[RelationshipMoveFamily] = {"public_reveal", "betray", "accuse"}

ROLE_LABEL_BY_SLOT: dict[str, dict[str, str]] = {
    "wealth_families": {
        "lead_interest": "名义联姻对象",
        "rival_interest": "早已进入核心圈的人",
        "hidden_ally": "替你处理脏事的律师或秘书",
        "public_witness": "决定家宴风向的人",
        "secret_keeper": "握着遗嘱秘密的人",
        "supporting_pressure": "负责逼你站队的执行者",
        "wildcard": "最不该在今晚出现的旧爱",
    },
    "entertainment_scandal": {
        "lead_interest": "被镜头宠爱的顶流对象",
        "rival_interest": "最先懂得利用舆论的人",
        "hidden_ally": "会替你收烂摊子的经纪盟友",
        "public_witness": "掌握直播风向的人",
        "secret_keeper": "知道偷拍视频源头的人",
        "supporting_pressure": "盯着你爆红或爆雷的人",
        "wildcard": "突然回流的旧绯闻对象",
    },
    "office_power": {
        "lead_interest": "最强势的上位者",
        "rival_interest": "与你争同一张桌子的对手",
        "hidden_ally": "看似替你兜底的法务或幕僚",
        "public_witness": "会左右会议风向的人",
        "secret_keeper": "知道并购黑账的人",
        "supporting_pressure": "负责催你表态的执行层",
        "wildcard": "不该被卷回局里的旧同盟",
    },
    "campus_romance": {
        "lead_interest": "最容易让你失控的人",
        "rival_interest": "表面无害却最会抢位的人",
        "hidden_ally": "看似善意的学生骨干",
        "public_witness": "决定舆论风向的校园人物",
        "secret_keeper": "握着旧录音或评审资料的人",
        "supporting_pressure": "最会逼你在体面和真心里二选一的人",
        "wildcard": "校庆前突然回来的旧暧昧",
    },
    "urban_supernatural": {
        "lead_interest": "最危险也最让你上头的人",
        "rival_interest": "会逼你相信命运的人",
        "hidden_ally": "看似温柔其实最会算账的知情者",
        "public_witness": "会在异能失控时围观的人",
        "secret_keeper": "握着契约副本的人",
        "supporting_pressure": "负责把你推向失控边缘的人",
        "wildcard": "不该在这一世再出现的旧债对象",
    },
}


class AuthorPlayState(TypedDict, total=False):
    accepted_blueprint: AcceptedBlueprint
    decision_snapshot: AuthorDecisionSnapshot
    arc_template_id: ArcTemplateId
    cast_slots: list[CastSlotPlan]
    bound_cast: list[BoundIPCastMember]
    voice_atoms_by_character: dict[str, list[VoiceAtom]]
    segment_contracts: list[SegmentContract]
    segment_playbooks: list[SegmentPlaybook]
    ending_matrix: EndingMatrix
    urban_bundle: UrbanAuthorBundle
    compiled_play_plan: CompiledPlayPlan
    llm_call_trace: list[dict[str, Any]]
    quality_trace: list[dict[str, Any]]
    live_mode: AuthorV2RunMode
    live_gateway: AuthorV2LLMGateway | None


def _append_quality(
    state: AuthorPlayState,
    *,
    stage: str,
    outcome: str,
    reasons: list[str] | None = None,
    source: str = "deterministic",
    metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return append_quality_trace(
        list(state.get("quality_trace", [])),
        stage=stage,
        outcome=outcome,
        reasons=reasons,
        source=source,
        metrics=metrics,
        strict_enabled=_strict_no_repair_fallback_enabled(),
    )


def _strict_no_repair_fallback_enabled() -> bool:
    return bool(get_settings().internal_test_strict_no_repair_fallback)


def _extend_llm_trace(
    state: AuthorPlayState,
    gateway: AuthorV2LLMGateway,
    *,
    start_index: int,
    stage: str,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    return extend_stage_llm_trace(
        list(state.get("llm_call_trace", [])),
        gateway=gateway,
        start_index=start_index,
        stage=stage,
        duration_seconds=duration_seconds,
        retry_count=0,
    )


def _allow_live_downgrade(live_mode: AuthorV2RunMode) -> bool:
    return live_mode in _MAINLINE_LIVE_MODES


def _segment_playbook_gateway(
    gateway: AuthorV2LLMGateway,
    *,
    live_mode: AuthorV2RunMode,
) -> AuthorV2LLMGateway:
    current_timeout = float(getattr(gateway, "timeout_seconds", 0.0) or 0.0)
    if live_mode != "pure_gpt" or current_timeout <= 0:
        return gateway
    target_timeout = min(current_timeout, _PURE_GPT_SEGMENT_PLAYBOOK_TIMEOUT_SECONDS)
    if target_timeout >= current_timeout:
        return gateway
    if not isinstance(gateway, AuthorV2LLMGateway):
        try:
            gateway.timeout_seconds = target_timeout  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return gateway
        return gateway
    return replace(gateway, timeout_seconds=target_timeout, call_trace=gateway.call_trace)


def _quality_metrics(
    *,
    requested_mode: str,
    actual_mode: str,
    used_live_output: bool,
    live_attempt_count: int,
    live_success_count: int,
    provider_failure_count: int,
    actual_modes: list[str] | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "requested_mode": requested_mode,
        "actual_mode": actual_mode,
        "used_live_output": used_live_output,
        "live_attempt_count": live_attempt_count,
        "live_success_count": live_success_count,
        "provider_failure_count": provider_failure_count,
    }
    if actual_modes:
        metrics["actual_modes"] = actual_modes
    return metrics


def _retry_exhausted_outcome(last_reason: str) -> tuple[str, list[str]]:
    return retry_exhausted_outcome(
        strict_enabled=_strict_no_repair_fallback_enabled(),
        last_reason=last_reason,
    )


def _resolve_live_gateway(
    live_mode: AuthorV2RunMode,
    gateway: AuthorV2LLMGateway | None,
) -> list[tuple[str, AuthorV2LLMGateway]]:
    if live_mode == "deterministic":
        return []
    if gateway is not None:
        return [(gateway.profile_id, gateway)]
    resolved_gateways: list[tuple[str, AuthorV2LLMGateway]] = []
    for candidate_mode in resolve_author_v2_live_mode_chain(live_mode):
        try:
            resolved_gateways.append((candidate_mode, get_author_v2_llm_gateway(candidate_mode)))
        except Exception:  # noqa: BLE001
            continue
    return resolved_gateways


def _hero_budget_gateway(
    gateway: AuthorV2LLMGateway,
    *,
    template_id: str,
    stage: str,
) -> AuthorV2LLMGateway:
    if not is_hero_template(template_id):
        return gateway
    if stage == "segment_playbook" and gateway.max_output_tokens_segment_playbook is not None and gateway.max_output_tokens_segment_playbook < _HERO_MAX_OUTPUT_TOKENS["segment_playbook"]:
        if isinstance(gateway, AuthorV2LLMGateway):
            return replace(gateway, max_output_tokens_segment_playbook=_HERO_MAX_OUTPUT_TOKENS["segment_playbook"], call_trace=gateway.call_trace)
        gateway.max_output_tokens_segment_playbook = _HERO_MAX_OUTPUT_TOKENS["segment_playbook"]  # type: ignore[attr-defined]
        return gateway
    return gateway


def _coerce_playbook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("segment_playbook")
    if isinstance(nested, dict):
        return nested
    return payload


def _raise_payload_validation_error(
    exc: Exception,
    *,
    payload: dict[str, Any],
    required_keys: tuple[str, ...] = (),
) -> None:
    returned_keys = sorted(str(key) for key in payload.keys())
    missing_required = [key for key in required_keys if key not in payload]
    reason = fallback_reason(exc if isinstance(exc, Exception) else RuntimeError("validation_failed"))
    diagnostics: list[str] = []
    if returned_keys:
        diagnostics.append(f"returned_keys={'|'.join(returned_keys[:10])}")
    if missing_required:
        diagnostics.append(f"missing_required_keys={'|'.join(missing_required[:10])}")
    enriched_reason = reason if not diagnostics else f"{reason}:{':'.join(diagnostics)}"
    wrapped = RuntimeError(str(exc))
    setattr(wrapped, "code", enriched_reason)
    raise wrapped from exc


def _sanitize_voice_atoms_delta_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_map = payload.get("voice_atom_deltas_by_character")
    if not isinstance(raw_map, dict):
        return payload
    allowed_atom_keys = {"atom_id", "line_stub", "catchphrase_hint", "forbidden_terms", "weight", "style_tags"}
    sanitized_map: dict[str, list[dict[str, Any]]] = {}
    for character_id, rows in raw_map.items():
        if not isinstance(rows, list):
            continue
        sanitized_rows: list[dict[str, Any]] = []
        seen_atom_ids: set[str] = set()
        for row in rows[:16]:
            if not isinstance(row, dict):
                continue
            sanitized_row = {key: row.get(key) for key in allowed_atom_keys if key in row}
            atom_id_value = str(sanitized_row.get("atom_id") or "").strip()
            if atom_id_value:
                if atom_id_value in seen_atom_ids:
                    continue
                seen_atom_ids.add(atom_id_value)
                sanitized_row["atom_id"] = atom_id_value
            if "line_stub" in sanitized_row:
                sanitized_row["line_stub"] = trim_text(normalize_whitespace(str(sanitized_row.get("line_stub") or "")), 220)
            if "catchphrase_hint" in sanitized_row and sanitized_row.get("catchphrase_hint") is not None:
                sanitized_row["catchphrase_hint"] = trim_text(
                    normalize_whitespace(str(sanitized_row.get("catchphrase_hint") or "")),
                    60,
                )
            if "forbidden_terms" in sanitized_row:
                terms = sanitized_row.get("forbidden_terms")
                if isinstance(terms, list):
                    sanitized_row["forbidden_terms"] = [
                        trim_text(normalize_whitespace(str(term)), 48)
                        for term in terms
                        if normalize_whitespace(str(term)).strip()
                    ][:6]
                else:
                    sanitized_row["forbidden_terms"] = []
            if "style_tags" in sanitized_row:
                tags = sanitized_row.get("style_tags")
                if isinstance(tags, list):
                    sanitized_row["style_tags"] = [
                        trim_text(normalize_whitespace(str(tag)), 32)
                        for tag in tags
                        if normalize_whitespace(str(tag)).strip()
                    ][:8]
                else:
                    sanitized_row["style_tags"] = []
            if "weight" in sanitized_row:
                raw_weight = sanitized_row.get("weight")
                parsed_weight: float | None = None
                if isinstance(raw_weight, (int, float)):
                    parsed_weight = float(raw_weight)
                elif isinstance(raw_weight, str):
                    match = re.search(r"-?\d+(?:\.\d+)?", raw_weight)
                    if match:
                        try:
                            parsed_weight = float(match.group(0))
                        except Exception:  # noqa: BLE001
                            parsed_weight = None
                if parsed_weight is None:
                    sanitized_row.pop("weight", None)
                else:
                    sanitized_row["weight"] = max(0.05, min(1.0, parsed_weight))
            sanitized_rows.append(sanitized_row)
        sanitized_map[str(character_id)] = sanitized_rows
    return {"voice_atom_deltas_by_character": sanitized_map}


def _sanitize_segment_playbook_delta_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "public_pressure_cue",
        "private_pressure_cue",
        "progression_rule_summary",
        "render_cues",
    }
    sanitized: dict[str, Any] = {}
    for key in allowed_keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if key in {"public_pressure_cue", "private_pressure_cue", "progression_rule_summary"}:
            text = trim_text(normalize_whitespace(str(value or "")), _SEGMENT_PLAYBOOK_TEXT_MAX_CHARS)
            if text:
                sanitized[key] = text
            continue
        if key == "render_cues":
            if isinstance(value, list):
                items = [
                    trim_text(normalize_whitespace(str(item)), _SEGMENT_PLAYBOOK_RENDER_CUE_ITEM_MAX_CHARS)
                    for item in value
                    if normalize_whitespace(str(item)).strip()
                ]
                if len(items) >= 2:
                    sanitized[key] = items[:_SEGMENT_PLAYBOOK_RENDER_CUE_MAX_ITEMS]
            continue
        sanitized[key] = value
    return sanitized


def _chunk_list(items: list[str], chunk_size: int) -> list[list[str]]:
    if chunk_size <= 0:
        return [items] if items else []
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def _validate_voice_atoms_payload(
    payload: dict[str, Any],
    *,
    expected_character_ids: set[str],
    allowed_atom_ids_by_character: dict[str, set[str]],
) -> dict[str, list[VoiceAtomDelta]]:
    payload = _sanitize_voice_atoms_delta_payload(payload)
    try:
        parsed = VoiceAtomsDelta.model_validate(payload)
    except ValidationError as exc:
        _raise_payload_validation_error(
            exc,
            payload=payload,
            required_keys=("voice_atom_deltas_by_character",),
        )
    candidate_map = parsed.voice_atom_deltas_by_character
    if set(candidate_map.keys()) != expected_character_ids:
        raise ValueError("voice_character_coverage_mismatch")
    output: dict[str, list[VoiceAtomDelta]] = {}
    for character_id in expected_character_ids:
        rows = list(candidate_map.get(character_id) or [])
        parsed_rows: list[VoiceAtomDelta] = []
        seen_atom_ids: set[str] = set()
        allowed_atom_ids = set(allowed_atom_ids_by_character.get(character_id) or set())
        for atom in rows:
            if atom.atom_id in seen_atom_ids:
                raise ValueError(f"{character_id}:atom_duplicate")
            if atom.atom_id not in allowed_atom_ids:
                raise ValueError(f"{character_id}:atom_id_out_of_range")
            seen_atom_ids.add(atom.atom_id)
            if not atom.line_stub.strip():
                raise ValueError(f"{character_id}:atom_line_stub_empty")
            if any(tag in atom.line_stub for tag in ("old_debt", "loss_position", "public_wave")):
                raise ValueError(f"{character_id}:atom_contains_internal_tag")
            parsed_rows.append(atom)
        if not parsed_rows:
            raise ValueError(f"{character_id}:atoms_empty")
        output[character_id] = parsed_rows[:16]
    return output


def _freeze_slot_candidate_pool(
    slot_candidate_pool: dict[str, list[dict[str, Any]]],
    *,
    snapshot_id: str,
) -> FrozenCandidatePool:
    frozen_by_slot: dict[str, list[FrozenSlotCandidate]] = {}
    for slot_id, rows in slot_candidate_pool.items():
        frozen_rows: list[FrozenSlotCandidate] = []
        for row in list(rows or [])[:8]:
            if not isinstance(row, dict):
                continue
            try:
                frozen_rows.append(
                    FrozenSlotCandidate(
                        candidate_index=int(row.get("candidate_index") or 0),
                        ip_character_id=str(row.get("ip_character_id") or "").strip(),
                        display_name=str(row.get("display_name") or "").strip(),
                        gender=str(row.get("gender") or "female"),  # type: ignore[arg-type]
                        score=float(row.get("score") or 0.0),
                        score_breakdown={
                            str(key): float(value)
                            for key, value in dict(row.get("score_breakdown") or {}).items()
                        },
                        persona_traits=[
                            str(item) for item in list(row.get("persona_traits") or [])[:4]
                        ],
                        voice_register_tags=[
                            str(item) for item in list(row.get("voice_register_tags") or [])[:4]
                        ],
                        secret_affinity_tags=[
                            str(item) for item in list(row.get("secret_affinity_tags") or [])[:4]
                        ],
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        frozen_by_slot[str(slot_id)] = frozen_rows
    return FrozenCandidatePool(
        snapshot_id=snapshot_id,
        by_slot=frozen_by_slot,
    )


def select_arc_template(accepted_blueprint: AcceptedBlueprint) -> ArcTemplateId:
    if accepted_blueprint.play_length_preset == "5_8":
        return "short_3"
    if accepted_blueprint.play_length_preset == "10_12":
        return "compact_4"
    if accepted_blueprint.play_length_preset == "12_15":
        return "standard_4"
    if accepted_blueprint.play_length_preset == "15_20":
        return "long_5"
    if accepted_blueprint.play_length_preset == "20_25":
        return "flagship_6"
    return "super_flagship_8"


def _slot_functions_for_count(cast_count: int, route_target_count: int) -> list[str]:
    base: list[str] = ["lead_interest", "rival_interest", "secret_keeper"]
    if cast_count >= 4:
        base.append("hidden_ally")
    if cast_count >= 5:
        base.append("public_witness")
    if cast_count >= 6:
        base.append("supporting_pressure")
    if cast_count >= 7:
        base.append("wildcard")
    if route_target_count >= 4 and "wildcard" not in base:
        base.append("wildcard")
    return base[:cast_count]


def _route_eligible_for_slot(slot_function: str, route_target_count: int, current_index: int) -> bool:
    priority = {
        "lead_interest": 0,
        "rival_interest": 1,
        "hidden_ally": 2,
        "wildcard": 3,
        "public_witness": 4,
        "secret_keeper": 5,
        "supporting_pressure": 6,
    }
    return priority[slot_function] < route_target_count and current_index < route_target_count


def _normalize_phrase_fragment(value: str, *, fallback: str) -> str:
    text = normalize_whitespace(value).replace("TA", "").strip()
    text = re.sub(r"^[，,。；;:\s]+", "", text)
    text = re.sub(r"[。！!？?；;，,、\s]+$", "", text)
    if not text:
        return fallback
    return trim_text(text, 180)


def _author_public_mask_fragment(raw_mask: str, social_arena: str) -> str:
    text = normalize_whitespace(raw_mask)
    matched = re.search(r"维持(.{1,80}?)体面", text)
    if matched:
        core = matched.group(1).strip("，,。；; ")
        if core:
            return trim_text(f"维持{core}体面的样子", 180)
    normalized = _normalize_phrase_fragment(text, fallback=f"维持{social_arena}体面的样子")
    if any(token in normalized for token in ("在外人眼里", "最懂得", "的人", "是")):
        return trim_text(f"维持{social_arena}体面的样子", 180)
    return normalized


def _build_deterministic_cast_slots(blueprint: AcceptedBlueprint) -> list[CastSlotPlan]:
    template = get_template_spec(blueprint.template_id)
    route_verbs = " / ".join(template.route_promise_verb_set[:3])
    slot_functions = _slot_functions_for_count(blueprint.cast_count_target, blueprint.route_target_count)
    role_map = ROLE_LABEL_BY_SLOT[blueprint.story_shell_id]
    danger_templates = {
        "lead_interest": f"TA最会用亲密感逼主角在{blueprint.social_arena}里立刻做出{route_verbs}的选择。",
        "rival_interest": f"TA一旦丢了体面，就会先拿主角和{blueprint.taboo_secret}一起开刀。",
        "hidden_ally": f"TA看起来像在兜底，实际上最可能替主角决定{blueprint.cost_of_truth}落到谁身上。",
        "public_witness": f"TA只要偏一句，{blueprint.social_arena}的风向就会立刻翻面。",
        "secret_keeper": f"TA掌握着{blueprint.taboo_secret}最关键的那一节证据。",
        "supporting_pressure": f"TA负责把退路一条条封死，让{route_verbs}变成没有回头路的站队。",
        "wildcard": "TA会把旧情和旧账一起拖回来，让主角所有克制当场失效。",
    }
    chemistry_templates = {
        "lead_interest": f"TA会让主角第一次觉得{blueprint.protagonist_hidden_need}可能真的有人接得住。",
        "rival_interest": f"TA越危险，越能逼出主角最想{route_verbs.split(' / ')[0]}的那一面。",
        "hidden_ally": "TA总在最要命的时候替主角兜一下，让依赖感慢慢长出来。",
        "public_witness": f"TA看似旁观，实际上每个眼神都在推动{blueprint.social_arena}里的关系升级。",
        "secret_keeper": f"TA手里的秘密会让亲密和威胁一起发酵。",
        "supporting_pressure": f"TA每次逼问都像在替局面加压，也逼主角更清楚自己要先{route_verbs.split(' / ')[0]}谁。",
        "wildcard": "TA一出现，过去那层没说完的情绪就会重新烧起来。",
    }
    return [
        CastSlotPlan(
            slot_id=f"slot_{index}_{slugify(slot_function)}",
            slot_function=slot_function,
            public_role_hint=role_map[slot_function],
            chemistry_hook=trim_text(chemistry_templates[slot_function], 180),
            danger_hook=trim_text(danger_templates[slot_function], 180),
            secret_pressure=trim_text(
                f"TA和{blueprint.taboo_secret}之间有一层不能被公开说破的联系。",
                180,
            ),
            # Author 只提供语义片段；最终文风与完整句子由 Play 运行时渲染。
            public_mask=trim_text(f"维持{blueprint.social_arena}体面的样子", 180),
            route_eligible=_route_eligible_for_slot(slot_function, blueprint.route_target_count, index - 1),
        )
        for index, slot_function in enumerate(slot_functions, start=1)
    ]


def plan_cast_slots(state: AuthorPlayState) -> AuthorPlayState:
    blueprint = state["accepted_blueprint"]
    deterministic_slots = _build_deterministic_cast_slots(blueprint)
    live_mode = state.get("live_mode", "deterministic")
    metrics = _quality_metrics(
        requested_mode=live_mode,
        actual_mode="deterministic",
        used_live_output=False,
        live_attempt_count=0,
        live_success_count=0,
        provider_failure_count=0,
    )
    metrics.update(
        {
            "decision_source": "deterministic",
            "decision_rule_hits": ["slot_contract_locked"],
            "decision_axis_hits": [],
            "decision_hint_hits": [],
        }
    )
    return {
        "cast_slots": deterministic_slots,
        "quality_trace": _append_quality(
            state,
            stage="plan_cast_slots",
            outcome="accepted",
            source="deterministic",
            metrics=metrics,
        ),
    }


def bind_ip_cast(state: AuthorPlayState) -> AuthorPlayState:
    blueprint = state["accepted_blueprint"]
    cast_slots = state["cast_slots"]
    live_mode: AuthorV2RunMode = state.get("live_mode", "deterministic")
    candidate_pool = build_slot_candidate_pool(cast_slots, blueprint, top_k=8)
    snapshot_id = f"cast_snapshot_{uuid4().hex[:12]}"
    frozen_pool = _freeze_slot_candidate_pool(
        candidate_pool,
        snapshot_id=snapshot_id,
    )
    bound_cast = bind_slots_to_ip_cast_with_candidate_pool(
        cast_slots,
        blueprint,
        slot_candidate_pool=candidate_pool,
    )
    deterministic_reasons: list[str] = []
    if len({member.character_id for member in bound_cast}) != len(bound_cast):
        deterministic_reasons.append("duplicate_ip_character_bound")
    decision_snapshot = AuthorDecisionSnapshot(
        template_id=blueprint.template_id,
        frozen_candidate_pool=frozen_pool,
    )
    metrics = _quality_metrics(
        requested_mode=live_mode,
        actual_mode="deterministic",
        used_live_output=False,
        live_attempt_count=0,
        live_success_count=0,
        provider_failure_count=0,
        actual_modes=[],
    )
    metrics.update(
        {
            "decision_source": "deterministic",
            "decision_rule_hits": ["frozen_candidate_pool_binding"],
            "decision_axis_hits": [],
            "decision_hint_hits": [],
            "frozen_snapshot_id": snapshot_id,
            "frozen_candidate_pool_slots": len(frozen_pool.by_slot),
            "frozen_candidate_pool_size": sum(len(rows) for rows in frozen_pool.by_slot.values()),
        }
    )
    return {
        "bound_cast": bound_cast,
        "decision_snapshot": decision_snapshot,
        "quality_trace": _append_quality(
            state,
            stage="bind_ip_cast",
            outcome="accepted",
            reasons=deterministic_reasons,
            source="deterministic",
            metrics=metrics,
        ),
    }


def _segment_roles(template_id: ArcTemplateId) -> list[str]:
    return SEGMENT_ROLE_ORDER[template_id]


def _voice_intent_tags(segment_role: SegmentRoleId) -> tuple[str, str]:
    return {
        "opening": ("试探", "留钩"),
        "misread": ("错读", "拉扯"),
        "pressure": ("施压", "逼站"),
        "reversal": ("反手", "改写"),
        "reveal": ("说破", "翻牌"),
        "terminal": ("落锁", "定局"),
    }.get(segment_role, ("推进", "定性"))


def _deterministic_voice_atoms_for_member(
    member: BoundIPCastMember,
    *,
    segment_roles: list[SegmentRoleId],
) -> list[VoiceAtom]:
    output: list[VoiceAtom] = []
    for role in segment_roles:
        intent_primary, intent_secondary = _voice_intent_tags(role)
        base_line = trim_text(
            f"{member.display_name}压着语气说：这拍先别急着定性，{intent_primary}才刚开始。",
            220,
        )
        alt_line = trim_text(
            f"{member.display_name}把话扣在桌面：你现在每一句都在{intent_secondary}，别装听不懂。",
            220,
        )
        output.append(
            VoiceAtom(
                atom_id=f"{member.character_id}:{role}:a",
                segment_role=role,
                intent_tag=f"{role}_primary",
                line_stub=base_line,
                catchphrase_hint=None,
                forbidden_terms=list(member.drama_profile.secret_owner_ids[:2]),
                weight=0.72,
                style_tags=[
                    role,
                    "default",
                    "high_secret" if member.slot_function == "secret_keeper" else "normal_secret",
                    "high_heat" if member.slot_function in {"rival_interest", "supporting_pressure"} else "normal_heat",
                ],
            )
        )
        output.append(
            VoiceAtom(
                atom_id=f"{member.character_id}:{role}:b",
                segment_role=role,
                intent_tag=f"{role}_alt",
                line_stub=alt_line,
                catchphrase_hint=(member.shareable_labels[0][:50] if member.shareable_labels else None),
                forbidden_terms=list(member.drama_profile.secret_owner_ids[:2]),
                weight=0.58,
                style_tags=[
                    role,
                    "alt",
                    "guarded" if member.slot_function in {"secret_keeper", "public_witness"} else "aggressive",
                ],
            )
        )
    return output[:16]


def _merge_voice_atoms(
    *,
    deterministic_atoms: list[VoiceAtom],
    live_atom_deltas: list[VoiceAtomDelta],
) -> list[VoiceAtom]:
    updated_by_id: dict[str, VoiceAtom] = {
        atom.atom_id: atom for atom in deterministic_atoms
    }
    for delta in live_atom_deltas:
        base_atom = updated_by_id.get(delta.atom_id)
        if base_atom is None:
            continue
        patch: dict[str, Any] = {
            "line_stub": delta.line_stub,
        }
        if delta.catchphrase_hint is not None:
            patch["catchphrase_hint"] = delta.catchphrase_hint
        if delta.forbidden_terms:
            patch["forbidden_terms"] = list(delta.forbidden_terms[:6])
        if delta.weight is not None:
            patch["weight"] = float(delta.weight)
        if delta.style_tags:
            patch["style_tags"] = list(delta.style_tags[:8])
        updated_by_id[delta.atom_id] = base_atom.model_copy(update=patch)
    return [updated_by_id[atom.atom_id] for atom in deterministic_atoms if atom.atom_id in updated_by_id][:16]


def compile_voice_atoms(state: AuthorPlayState) -> AuthorPlayState:
    blueprint = state["accepted_blueprint"]
    bound_cast = state["bound_cast"]
    segment_roles = [role for role in _segment_roles(state["arc_template_id"])]
    deterministic_map: dict[str, list[VoiceAtom]] = {
        member.character_id: _deterministic_voice_atoms_for_member(member, segment_roles=segment_roles)
        for member in bound_cast
    }
    live_mode: AuthorV2RunMode = state.get("live_mode", "deterministic")
    if live_mode == "deterministic":
        return {
            "voice_atoms_by_character": deterministic_map,
            "quality_trace": _append_quality(
                state,
                stage="compile_voice_atoms",
                outcome="accepted",
                source="deterministic",
                metrics=_quality_metrics(
                    requested_mode=live_mode,
                    actual_mode="deterministic",
                    used_live_output=False,
                    live_attempt_count=0,
                    live_success_count=0,
                    provider_failure_count=0,
                    actual_modes=[],
                ),
            ),
        }

    gateways = _resolve_live_gateway(live_mode, state.get("live_gateway"))
    if not gateways:
        outcome, reasons = _retry_exhausted_outcome("live_gateway_unavailable")
        return {
            "voice_atoms_by_character": deterministic_map,
            "quality_trace": _append_quality(
                state,
                stage="compile_voice_atoms",
                outcome=outcome,
                reasons=reasons,
                source="deterministic",
                metrics=_quality_metrics(
                    requested_mode=live_mode,
                    actual_mode="deterministic",
                    used_live_output=False,
                    live_attempt_count=0,
                    live_success_count=0,
                    provider_failure_count=0,
                    actual_modes=[],
                ),
            ),
        }

    combined_trace = list(state.get("llm_call_trace", []))
    base_trace_len = len(state.get("llm_call_trace", []))
    attempt_failures: list[str] = []
    live_attempt_count = 0
    provider_failure_count = 0
    character_order = [member.character_id for member in bound_cast]
    allowed_atom_ids_by_character = {
        character_id: {atom.atom_id for atom in atoms}
        for character_id, atoms in deterministic_map.items()
    }
    cast_meta = [
        {
            "character_id": member.character_id,
            "display_name": member.display_name,
            "slot_function": member.slot_function,
            "public_role": member.public_role,
            "speech_pattern": member.speech_pattern,
            "shareable_labels": list(member.shareable_labels[:3]),
        }
        for member in bound_cast
    ]
    voice_atom_catalog_by_character = {
        character_id: [
            {
                "atom_id": atom.atom_id,
                "segment_role": atom.segment_role,
                "line_stub_seed": trim_text(atom.line_stub, _VOICE_LINE_STUB_SEED_MAX_CHARS),
                "style_tags": list(atom.style_tags[:4]),
            }
            for atom in atoms
        ]
        for character_id, atoms in deterministic_map.items()
    }
    batch_size = _VOICE_BATCH_SIZE_STRICT if _strict_no_repair_fallback_enabled() else _VOICE_BATCH_SIZE_DEFAULT
    character_batches = _chunk_list(character_order, batch_size)
    allow_live_downgrade = _allow_live_downgrade(live_mode)
    active_gateways = gateways if allow_live_downgrade else gateways[:1]
    gateway_index = 0
    while live_attempt_count < MAX_STAGE_REGEN_ATTEMPTS and active_gateways:
        source_mode, gateway = active_gateways[gateway_index % len(active_gateways)]
        live_attempt_count += 1
        response_payload: dict[str, Any] | None = None
        current_batch_index = 0
        current_batch_ids: list[str] = []
        current_payload_bytes = 0
        current_trace_cursor = len(gateway.call_trace)
        current_trace_recorded = False
        try:
            retry_feedback = attempt_failures[-1] if attempt_failures else None
            live_delta_map: dict[str, list[VoiceAtomDelta]] = {}
            for batch_index, batch_character_ids in enumerate(character_batches, start=1):
                current_batch_index = batch_index
                current_batch_ids = list(batch_character_ids)
                batch_id_set = set(batch_character_ids)
                current_trace_cursor = len(gateway.call_trace)
                current_trace_recorded = False
                started = perf_counter()
                request_payload: dict[str, Any] = {
                    "story_context": {
                        "story_shell_id": blueprint.story_shell_id,
                        "social_arena": blueprint.social_arena,
                        "route_promise": blueprint.route_promise,
                        "taboo_secret": blueprint.taboo_secret,
                        "relationship_setup": blueprint.relationship_setup,
                    },
                    "cast_meta": [
                        row for row in cast_meta if str(row.get("character_id")) in batch_id_set
                    ],
                    "segment_roles": segment_roles,
                    "voice_atom_catalog_by_character": {
                        character_id: list(voice_atom_catalog_by_character.get(character_id) or [])
                        for character_id in batch_character_ids
                    },
                    "batch_character_ids": list(batch_character_ids),
                    "batch_index": batch_index,
                    "batch_count": len(character_batches),
                    "regeneration_index": live_attempt_count,
                    "max_regeneration_attempts": MAX_STAGE_REGEN_ATTEMPTS,
                }
                if retry_feedback:
                    request_payload["validation_feedback"] = retry_feedback
                current_payload_bytes = len(json.dumps(request_payload, ensure_ascii=False))
                response = gateway.invoke_json(
                    system_prompt=VOICE_ATOM_SYSTEM_PROMPT,
                    user_payload=request_payload,
                    max_output_tokens=(
                        getattr(gateway, "max_output_tokens_voice_atoms", None)
                        or getattr(gateway, "max_output_tokens_cast_slots", None)
                        or getattr(gateway, "max_output_tokens_segment_playbook", None)
                    ),
                    operation_name="author_v2.voice_atoms",
                    response_format_type="json_object",
                )
                extended_trace = _extend_llm_trace(
                    state,
                    gateway,
                    start_index=current_trace_cursor,
                    stage="compile_voice_atoms",
                    duration_seconds=perf_counter() - started,
                )
                new_entries = extended_trace[base_trace_len:]
                for entry in new_entries:
                    entry["payload_bytes"] = current_payload_bytes
                    entry["batch_character_count"] = len(batch_character_ids)
                    entry["batch_index"] = batch_index
                    entry["batch_count"] = len(character_batches)
                    entry["batch_character_ids"] = list(batch_character_ids)
                combined_trace.extend(new_entries)
                current_trace_recorded = True
                response_payload = response.payload
                batch_delta_map = _validate_voice_atoms_payload(
                    response_payload,
                    expected_character_ids=batch_id_set,
                    allowed_atom_ids_by_character={
                        character_id: set(allowed_atom_ids_by_character.get(character_id) or set())
                        for character_id in batch_character_ids
                    },
                )
                live_delta_map.update(batch_delta_map)
            merged_map = {
                character_id: _merge_voice_atoms(
                    deterministic_atoms=deterministic_map[character_id],
                    live_atom_deltas=live_delta_map.get(character_id, []),
                )
                for character_id in character_order
                if character_id in deterministic_map
            }
            stage_trace = [entry for entry in combined_trace if entry.get("stage") == "compile_voice_atoms"]
            return {
                "voice_atoms_by_character": merged_map,
                "llm_call_trace": combined_trace,
                "quality_trace": _append_quality(
                    state,
                    stage="compile_voice_atoms",
                    outcome="accepted",
                    reasons=list(attempt_failures),
                    source=source_mode,
                    metrics=_quality_metrics(
                        requested_mode=live_mode,
                        actual_mode=source_mode,
                        used_live_output=True,
                        live_attempt_count=live_attempt_count,
                        live_success_count=1,
                        provider_failure_count=provider_failure_count,
                        actual_modes=[
                            mode
                            for mode in dict.fromkeys(
                                str(entry.get("mode"))
                                for entry in stage_trace
                                if entry.get("response_received")
                            )
                        ],
                    ),
                ),
            }
        except Exception as exc:  # noqa: BLE001
            if not current_trace_recorded:
                extended_trace = _extend_llm_trace(
                    state,
                    gateway,
                    start_index=current_trace_cursor,
                    stage="compile_voice_atoms",
                    duration_seconds=0.0,
                )
                new_entries = extended_trace[base_trace_len:]
                for entry in new_entries:
                    entry["payload_bytes"] = current_payload_bytes
                    entry["batch_character_count"] = len(current_batch_ids)
                    entry["batch_index"] = current_batch_index
                    entry["batch_count"] = len(character_batches)
                    entry["batch_character_ids"] = list(current_batch_ids)
                combined_trace.extend(new_entries)
            if combined_trace and response_payload is not None:
                combined_trace[-1]["validation_failed_reason"] = fallback_reason(exc)
                combined_trace[-1]["returned_keys"] = sorted(str(key) for key in response_payload.keys())[:10]
                combined_trace[-1]["missing_required_keys"] = [
                    key for key in ("voice_atom_deltas_by_character",) if key not in response_payload
                ]
            batch_suffix = f":batch_{current_batch_index}" if current_batch_index > 0 else ""
            attempt_failures.append(f"{source_mode}{batch_suffix}:{fallback_reason(exc)}")
            if is_provider_failure(exc):
                provider_failure_count += 1
        gateway_index += 1

    stage_trace = [entry for entry in combined_trace if entry.get("stage") == "compile_voice_atoms"]
    exhausted_reason = attempt_failures[-1] if attempt_failures else "live_gateway_unavailable"
    outcome, reasons = _retry_exhausted_outcome(exhausted_reason)
    return {
        "voice_atoms_by_character": deterministic_map,
        "llm_call_trace": combined_trace,
        "quality_trace": _append_quality(
            state,
            stage="compile_voice_atoms",
            outcome=outcome,
            reasons=reasons,
            source="deterministic",
            metrics=_quality_metrics(
                requested_mode=live_mode,
                actual_mode="deterministic",
                used_live_output=False,
                live_attempt_count=live_attempt_count,
                live_success_count=0,
                provider_failure_count=provider_failure_count,
                actual_modes=[
                    mode
                    for mode in dict.fromkeys(
                        str(entry.get("mode"))
                        for entry in stage_trace
                        if entry.get("response_received")
                    )
                ],
            ),
        ),
    }


def _progress_budget(template_id: ArcTemplateId) -> list[int]:
    return PROGRESS_REQUIRED_BY_TEMPLATE[template_id]


def _secret_ids_for_blueprint() -> list[str]:
    return ["taboo_secret", "social_exposure", "cost_of_truth", "route_betrayal"]


def _focus_target_ids(bound_cast: list[BoundIPCastMember]) -> list[str]:
    return [member.character_id for member in bound_cast if member.is_route_target]


def _build_deterministic_segment_contracts(
    blueprint: AcceptedBlueprint,
    arc_template_id: ArcTemplateId,
    bound_cast: list[BoundIPCastMember],
) -> list[SegmentContract]:
    template = get_template_spec(blueprint.template_id)
    roles = _segment_roles(arc_template_id)
    progress_budget = _progress_budget(arc_template_id)
    route_targets = _focus_target_ids(bound_cast)
    support_targets = [member.character_id for member in bound_cast if not member.is_route_target]
    secret_ids = _secret_ids_for_blueprint()
    surface_signals = _shell_surface_signals(blueprint.story_shell_id)
    public_cost_signal = _shell_public_cost_signal(blueprint)
    backlash_signal = _shell_relationship_backlash_signal(blueprint)
    contracts: list[SegmentContract] = []
    for index, role in enumerate(roles, start=1):
        focus: list[str]
        rivals: list[str]
        if role == "opening":
            focus = route_targets[:1] or support_targets[:1]
            rivals = route_targets[1:2]
        elif role == "misread":
            focus = route_targets[1:2] or route_targets[:1]
            rivals = route_targets[:1]
        elif role == "pressure":
            focus = support_targets[:1] or route_targets[:1]
            rivals = route_targets[:2]
        elif role == "reversal":
            focus = route_targets[:1] + support_targets[:1]
            rivals = route_targets[1:2] or support_targets[:1]
        elif role == "reveal":
            focus = route_targets[:1] + support_targets[:1]
            rivals = route_targets[1:2]
        else:
            focus = route_targets[:2] or [member.character_id for member in bound_cast[:2]]
            rivals = support_targets[:1]
        allocated_secrets = [secret_ids[min(index - 1, len(secret_ids) - 1)]]
        if role in {"reveal", "terminal"} and "taboo_secret" not in allocated_secrets:
            allocated_secrets.insert(0, "taboo_secret")
        venue_suffix = {
            "opening": "outer_ring",
            "misread": "corridor",
            "pressure": "closed_room",
            "reversal": "private_suite",
            "reveal": "main_stage",
            "terminal": "night_exit",
        }[role]
        opening_surface = surface_signals[(index - 1) % len(surface_signals)]
        carry_surface = surface_signals[index % len(surface_signals)]
        closing_surface = surface_signals[(index + 1) % len(surface_signals)]
        allowed_move_families = _ensure_high_risk_move_family(role, MOVE_FAMILIES_BY_ROLE[role])
        contracts.append(
            SegmentContract(
                segment_id=f"segment_{index}_{role}",
                segment_role=role,
                focus_target_ids=focus[:2],
                rival_target_ids=rivals[:2],
                allocated_secret_ids=allocated_secrets[:3],
                entry_contract=trim_text(
                    f"进入这一段前，{blueprint.social_arena}还维持着脆弱体面，但{opening_surface}和{blueprint.taboo_secret}已经浮到台前；这一段必须把{template.route_promise_verb_set[0]}谁的问题推成可见冲突。",
                    220,
                ),
                exit_contract=trim_text(
                    f"这一段结束时，至少一个核心人物必须在{role}层面失位，并让{public_cost_signal}变成公开代价，同时埋下{backlash_signal}。",
                    220,
                ),
                handoff_contract=trim_text(
                    f"下一段要继承这次失衡，继续放大{carry_surface}和{closing_surface}，把{blueprint.cost_of_truth}推成不可回收的实质损耗。",
                    220,
                ),
                is_terminal=role == "terminal",
                progress_required=progress_budget[index - 1],
                segment_turn_floor=6,
                allowed_move_families=allowed_move_families,
                venue_id=f"{slugify(blueprint.social_arena)}_{venue_suffix}",
            )
        )
    return contracts


def allocate_segment_contracts(state: AuthorPlayState) -> AuthorPlayState:
    blueprint = state["accepted_blueprint"]
    deterministic_contracts = _build_deterministic_segment_contracts(
        blueprint,
        state["arc_template_id"],
        state["bound_cast"],
    )
    live_mode = state.get("live_mode", "deterministic")
    metrics = _quality_metrics(
        requested_mode=live_mode,
        actual_mode="deterministic",
        used_live_output=False,
        live_attempt_count=0,
        live_success_count=0,
        provider_failure_count=0,
    )
    metrics.update(
        {
            "decision_source": "deterministic",
            "decision_rule_hits": ["segment_contract_locked"],
            "decision_axis_hits": [],
            "decision_hint_hits": [],
        }
    )
    return {
        "segment_contracts": deterministic_contracts,
        "quality_trace": _append_quality(
            state,
            stage="allocate_segment_contracts",
            outcome="accepted",
            source="deterministic",
            metrics=metrics,
        ),
    }


def _members_by_id(bound_cast: list[BoundIPCastMember]) -> dict[str, BoundIPCastMember]:
    return {member.character_id: member for member in bound_cast}


def _candidate_lane_moves(
    contract: SegmentContract,
    preferred_moves: tuple[RelationshipMoveFamily, ...],
) -> list[RelationshipMoveFamily]:
    matched = [move_family for move_family in preferred_moves if move_family in contract.allowed_move_families]
    if matched:
        return matched[:4]
    return list(contract.allowed_move_families[:2])


def _lane_target_priority_ids(
    lane_id: SuggestionLaneId,
    *,
    contract: SegmentContract,
    bound_cast: list[BoundIPCastMember],
) -> list[str]:
    route_target_ids = [member.character_id for member in bound_cast if member.is_route_target]
    active_ids = unique_preserve(contract.focus_target_ids + contract.rival_target_ids)[:3]
    secret_keeper_ids = [member.character_id for member in bound_cast if member.slot_function == "secret_keeper"]
    if lane_id == "relationship":
        return unique_preserve(route_target_ids + contract.focus_target_ids + active_ids)[:3]
    if lane_id == "side":
        return unique_preserve(contract.focus_target_ids + contract.rival_target_ids + route_target_ids)[:3]
    return unique_preserve(secret_keeper_ids + contract.rival_target_ids + contract.focus_target_ids + route_target_ids)[:3]


def _secret_core(blueprint: AcceptedBlueprint) -> str:
    text = blueprint.taboo_secret
    for keyword in ("偷拍视频", "旧录音", "遗嘱录音", "黑账", "评审资料", "合同", "证据"):
        if keyword in text:
            return keyword
    return trim_text(text, 32)


def _play_facing_lane_objective(blueprint: AcceptedBlueprint, lane_id: SuggestionLaneId) -> str:
    if lane_id == "relationship":
        return trim_text(f"先把人心拽过来，再逼{blueprint.social_arena}里最会装没事的人露出真正站位。", 220)
    if lane_id == "side":
        return trim_text(f"先让场上有人把边站出来，别再让{blueprint.social_arena}这局继续装糊涂。", 220)
    return trim_text(f"先让最不该见光的那层东西漏一寸，逼{blueprint.social_arena}整场人一起换气。", 220)


def _play_facing_scene_goal(contract: SegmentContract, *, tension_anchor: str, blueprint: AcceptedBlueprint) -> str:
    if contract.segment_role == "opening":
        return trim_text(f"先让{tension_anchor}在最该稳住的时候把偏心、护短和那点不肯说破的拉扯露出来。", 220)
    if contract.segment_role == "misread":
        return trim_text(f"先让{tension_anchor}把话说偏、把站位露半寸，别急着翻牌，先把误读养出来。", 220)
    if contract.segment_role == "pressure":
        return trim_text(f"把{tension_anchor}逼到不表态就更难看的位置，让谁先护自己这件事变得越来越明显。", 220)
    if contract.segment_role == "reversal":
        return trim_text(f"让{tension_anchor}短暂以为还能翻回去，再把新的代价和旧账一起顶到眼前。", 220)
    if contract.segment_role == "reveal":
        return trim_text(f"让{tension_anchor}在所有人都看得见的地方把最该藏的那一下彻底漏出来。", 220)
    return trim_text(f"把{tension_anchor}推到只能认边、翻脸或一起掉下去的最后一拍。", 220)


def _play_facing_progression_summary(contract: SegmentContract, *, tension_anchor: str, blueprint: AcceptedBlueprint) -> str:
    if contract.segment_role in {"opening", "misread"}:
        return trim_text(
            f"这一段别急着摊牌，先让{tension_anchor}把心虚、偏心和试探露出来，并逼出至少一次可观测让步或被迫表态。",
            220,
        )
    if contract.segment_role in {"pressure", "reversal"}:
        return trim_text(
            f"这一段重点不是解释局面，而是把{blueprint.social_arena}里的退路抽掉，逼出一次站位换手（谁从旁观转为认边）。",
            220,
        )
    if contract.segment_role == "reveal":
        return trim_text(
            f"这一段别只把秘密说出来，重点是秘密见光后立刻兑现公开后果：谁先失态、谁先切人、谁先背锅。",
            220,
        )
    return trim_text("这一段要让代价落地并定损，明确谁先失位、谁被迫接盘，不停在口头对峙。", 220)


def _control_render_cue_for_role(segment_role: str) -> str:
    if segment_role in {"opening", "misread"}:
        return "style:control:force_first_concession"
    if segment_role in {"pressure", "reversal"}:
        return "style:control:force_side_switch"
    return "style:control:force_public_settlement"


def _deterministic_move_priorities(contract: SegmentContract) -> list[RelationshipMoveFamily]:
    allowed_moves = list(unique_preserve(contract.allowed_move_families))
    role_order: tuple[RelationshipMoveFamily, ...]
    if contract.segment_role in {"opening", "misread"}:
        role_order = (
            "accuse",
            "ally_with",
            "deflect",
            "probe_secret",
            "comfort",
            "flirt",
            "private_confession",
            "public_reveal",
            "betray",
            "jealousy_trigger",
        )
    elif contract.segment_role in {"pressure", "reversal"}:
        role_order = (
            "accuse",
            "probe_secret",
            "public_reveal",
            "betray",
            "jealousy_trigger",
            "deflect",
            "ally_with",
            "private_confession",
            "comfort",
            "flirt",
        )
    else:
        role_order = (
            "public_reveal",
            "accuse",
            "probe_secret",
            "betray",
            "jealousy_trigger",
            "private_confession",
            "ally_with",
            "deflect",
            "comfort",
            "flirt",
        )
    ordered = [move for move in role_order if move in allowed_moves]
    tail = [move for move in allowed_moves if move not in ordered]
    return [*ordered, *tail][:4]


def _tuned_move_priorities(
    *,
    base_priorities: list[RelationshipMoveFamily],
    allowed_moves: list[RelationshipMoveFamily],
    promote_moves: list[RelationshipMoveFamily],
) -> list[RelationshipMoveFamily]:
    legal_base = [move for move in unique_preserve(base_priorities) if move in set(allowed_moves)]
    legal_allowed = list(unique_preserve(allowed_moves))
    promoted = [move for move in unique_preserve(promote_moves) if move in set(legal_allowed)]
    merged = unique_preserve([*promoted, *legal_base, *legal_allowed])
    return merged[: max(2, min(6, len(merged)))]


def _tuned_progression_summary(
    *,
    summary: str,
    intensity: float,
    control_contract_hint_weight: float = 1.0,
) -> str:
    core = trim_text(summary, 220)
    if control_contract_hint_weight >= 1.2:
        core = trim_text(f"优先交代谁先让步、代价落点和拒绝后的升级路径。{core}", 220)
    elif control_contract_hint_weight >= 1.05:
        core = trim_text(f"优先写清让步与代价交换，不停在解释。{core}", 220)
    if intensity >= 1.2:
        return trim_text(f"这一段必须让代价当场可见，并逼出明确站位换手。{core}", 220)
    if intensity >= 1.1:
        return trim_text(f"这一段优先逼出可观测让步或切边，不停在解释。{core}", 220)
    if intensity >= 1.05:
        return trim_text(f"这一段要把局面继续推紧，避免原地对话。{core}", 220)
    return core


def _tuned_render_cues(
    *,
    cues: list[str],
    boost: list[str],
) -> list[str]:
    merged = [cue for cue in unique_preserve([*boost, *cues]) if isinstance(cue, str) and cue.strip()]
    return [trim_text(cue, 56) for cue in merged[:5]]


def _play_facing_opening_narration(blueprint: AcceptedBlueprint) -> str:
    secret_core = _secret_core(blueprint)
    if blueprint.story_shell_id == "entertainment_scandal":
        return trim_text(f"场景设定：{blueprint.social_arena}。核心风险：{secret_core}一旦被镜头或公屏接住，会直接改变外部风向和切割顺序。", 320)
    if blueprint.story_shell_id == "campus_romance":
        return trim_text(f"场景设定：{blueprint.social_arena}。核心风险：{secret_core}会通过台下、评审和熟人圈扩散，直接影响站队与名额。", 320)
    if blueprint.story_shell_id == "wealth_families":
        return trim_text(f"场景设定：{blueprint.social_arena}。核心风险：{secret_core}会影响顺位与家族站边，公开场和私下交易会同步升温。", 320)
    if blueprint.story_shell_id == "office_power":
        return trim_text(f"场景设定：{blueprint.social_arena}。核心风险：{secret_core}会引发背锅和切割，岗位与话语权会被快速重排。", 320)
    return trim_text(f"场景设定：{blueprint.social_arena}。核心风险：{secret_core}正在持续发酵，后续每一步都会提高公开代价。", 320)


def _compile_suggestion_lanes(
    blueprint: AcceptedBlueprint,
    contract: SegmentContract,
    bound_cast: list[BoundIPCastMember],
) -> list[SegmentSuggestionLane]:
    lane_specs: tuple[tuple[SuggestionLaneId, str, str, tuple[RelationshipMoveFamily, ...], RelationshipSceneFrame], ...] = (
        (
            "relationship",
            "走关系线",
            _play_facing_lane_objective(blueprint, "relationship"),
            ("flirt", "comfort", "private_confession", "ally_with"),
            "private",
        ),
        (
            "side",
            "先选阵营",
            _play_facing_lane_objective(blueprint, "side"),
            ("ally_with", "comfort", "accuse", "deflect"),
            "semi_public" if contract.segment_role == "pressure" else "private",
        ),
        (
            "burst",
            "引爆场面",
            _play_facing_lane_objective(blueprint, "burst"),
            ("probe_secret", "public_reveal", "accuse", "betray", "jealousy_trigger"),
            "public" if contract.segment_role in {"reveal", "terminal"} else "semi_public",
        ),
    )
    return [
        SegmentSuggestionLane(
            lane_id=lane_id,
            label=label,
            objective=objective,
            candidate_move_families=_candidate_lane_moves(contract, preferred_moves),
            target_priority_ids=_lane_target_priority_ids(lane_id, contract=contract, bound_cast=bound_cast),
            scene_frame_hint=scene_frame_hint,
        )
        for lane_id, label, objective, preferred_moves, scene_frame_hint in lane_specs
    ]


def _template_tone_example_lines(template, segment_role: str) -> list[ToneExampleLine]:  # noqa: ANN001
    preferred_by_role = {
        "opening": ("hook", "route_promise", "supporting"),
        "misread": ("hook", "route_promise", "supporting"),
        "pressure": ("route_promise", "cost", "supporting"),
        "reversal": ("route_promise", "supporting", "cost"),
        "reveal": ("bomb", "cost", "supporting"),
        "terminal": ("bomb", "cost", "supporting"),
    }
    preferred = preferred_by_role.get(segment_role, ("hook", "route_promise", "supporting"))
    selected = [
        line
        for slot in preferred
        for line in template.tone_example_pack.lines
        if line.slot == slot
    ]
    return selected[:4]


def _template_tone_scene_examples(template, segment_role: str) -> list[ToneSceneExample]:  # noqa: ANN001
    scenes = list(template.tone_example_pack.scenes)
    public = [scene for scene in scenes if scene.slot == "public_escalation"]
    private = [scene for scene in scenes if scene.slot == "private_aftermath"]
    return ([*public, *private] if segment_role in {"reveal", "terminal"} else [*private, *public])[:2]


def _example_cue_from_line(line: ToneExampleLine) -> str:
    slot_cues = {
        "hook": "style:hook:pressure_first",
        "route_promise": "style:choice:force_alignment",
        "bomb": "style:bomb:short_hard_drop",
        "cost": "style:cost:status_or_face",
        "supporting": "style:supporting:stake_first",
    }
    return slot_cues[line.slot]


def _compile_tone_example_pack(template, segment_role: str) -> tuple[list[ToneExampleLine], list[ToneSceneExample], CompiledToneExamplePack]:  # noqa: ANN001
    lines = _template_tone_example_lines(template, segment_role)
    scenes = _template_tone_scene_examples(template, segment_role)
    supporting_lines = [line for line in template.tone_example_pack.lines if line.slot == "supporting"][:2]
    reaction_lines = [line for line in lines if line.slot in {"route_promise", "bomb", "cost"}] or lines[:2]
    chain_lines = [line for line in template.tone_example_pack.lines if line.slot in {"bomb", "supporting"}][:2]
    debt_lines = [line for line in template.tone_example_pack.lines if line.slot in {"cost", "supporting"}][:2]
    return lines, scenes, CompiledToneExamplePack(
        author_example_lines=lines[:4],
        author_example_scene=scenes[:2],
        play_reaction_example_lines=reaction_lines[:4],
        play_supporting_example_lines=supporting_lines[:4],
        play_chain_example_lines=chain_lines[:4],
        play_debt_example_lines=debt_lines[:4],
    )


def _shell_anchor_tokens(shell_id: str, segment_role: str) -> list[str]:
    if shell_id == "entertainment_scandal":
        return ["镜头", "热搜", "公关", "切割", "版本", "公屏"] if segment_role in {"reveal", "terminal"} else ["镜头", "公关", "风向", "版本"]
    if shell_id == "campus_romance":
        return ["台下", "评审", "名额", "社团", "熟人", "站队"] if segment_role in {"reveal", "terminal"} else ["台下", "熟人", "站队", "评审"]
    if shell_id == "office_power":
        return ["牌桌", "背锅", "站位", "话语权", "会议桌"]
    if shell_id == "wealth_families":
        return ["主桌", "顺位", "家宴", "认边", "体面"]
    return ["风向", "旧账", "站边", "失位"]


def _shell_surface_signals(shell_id: str) -> tuple[str, str, str]:
    return _SHELL_SURFACE_SIGNALS.get(shell_id, ("公开风向", "关系拉扯", "秘密压力"))


def _shell_public_cost_signal(blueprint: AcceptedBlueprint) -> str:
    return _SHELL_PUBLIC_COST_SIGNALS.get(blueprint.story_shell_id, trim_text(blueprint.cost_of_truth, 36))


def _shell_relationship_backlash_signal(blueprint: AcceptedBlueprint) -> str:
    return _SHELL_RELATIONSHIP_BACKLASH_SIGNALS.get(blueprint.story_shell_id, "关系账会在下一段反噬")


def _ensure_high_risk_move_family(
    segment_role: str,
    move_families: list[RelationshipMoveFamily],
) -> list[RelationshipMoveFamily]:
    if any(item in _HIGH_RISK_MOVE_FAMILIES for item in move_families):
        return move_families
    fallback: RelationshipMoveFamily = "accuse" if segment_role in {"opening", "misread", "pressure", "reversal"} else "public_reveal"
    updated = list(move_families)
    if len(updated) >= 4:
        updated[-1] = fallback
    else:
        updated.append(fallback)
    return unique_preserve(updated)[:6]


def _compile_segment_style_profile(
    *,
    blueprint: AcceptedBlueprint,
    contract: SegmentContract,
    tone_lines: list[ToneExampleLine],
    tone_scenes: list[ToneSceneExample],
) -> SegmentStyleProfile:
    reason_families = unique_preserve(
        [
            line.semantic_tag.reason_family
            for line in tone_lines
            if getattr(line, "semantic_tag", None) is not None
        ]
    )[:4]
    signal_families = unique_preserve(
        [
            *[
                line.semantic_tag.signal_family
                for line in tone_lines
                if getattr(line, "semantic_tag", None) is not None
            ],
            *[
                scene.semantic_tag.signal_family
                for scene in tone_scenes
                if getattr(scene, "semantic_tag", None) is not None
            ],
        ]
    )[:4]
    cost_families = unique_preserve(
        [
            *[
                line.semantic_tag.cost_family
                for line in tone_lines
                if getattr(line, "semantic_tag", None) is not None
            ],
            *[
                scene.semantic_tag.cost_family
                for scene in tone_scenes
                if getattr(scene, "semantic_tag", None) is not None
            ],
        ]
    )[:4]
    cadence_order = unique_preserve(
        [
            line.semantic_tag.cadence
            for line in tone_lines
            if getattr(line, "semantic_tag", None) is not None
        ]
    )[:4]
    if not reason_families:
        reason_families = ["mixed"]
    if not signal_families:
        signal_families = ["mixed"]
    if not cost_families:
        cost_families = ["mixed"]
    if not cadence_order:
        cadence_order = ["mixed"]
    return SegmentStyleProfile(
        reason_families=reason_families,  # type: ignore[arg-type]
        signal_families=signal_families,  # type: ignore[arg-type]
        cost_families=cost_families,  # type: ignore[arg-type]
        cadence_order=cadence_order,  # type: ignore[arg-type]
        shell_anchor_tokens=_shell_anchor_tokens(blueprint.story_shell_id, contract.segment_role)[:6],
        explosive_boost=contract.segment_role in {"reveal", "terminal"},
    )


def _compile_single_segment(
    *,
    blueprint: AcceptedBlueprint,
    contract: SegmentContract,
    bound_cast: list[BoundIPCastMember],
) -> SegmentPlaybook:
    template = get_template_spec(blueprint.template_id)
    template_tone_example_lines, template_tone_scene_examples, tone_example_pack = _compile_tone_example_pack(template, contract.segment_role)
    segment_style_profile = _compile_segment_style_profile(
        blueprint=blueprint,
        contract=contract,
        tone_lines=template_tone_example_lines,
        tone_scenes=template_tone_scene_examples,
    )
    members = _members_by_id(bound_cast)
    focus_names = [members[character_id].display_name for character_id in contract.focus_target_ids if character_id in members]
    tension_anchor = "、".join(focus_names) or blueprint.social_arena
    surface_signals = _shell_surface_signals(blueprint.story_shell_id)
    public_cost_signal = _shell_public_cost_signal(blueprint)
    backlash_signal = _shell_relationship_backlash_signal(blueprint)
    public_pressure_cue = trim_text(
        f"{blueprint.social_arena}里的{surface_signals[0]}和{surface_signals[1]}正在升温，只要有人先开口，{tension_anchor}就会立刻失衡，公开代价会直接砸到{public_cost_signal}。",
        220,
    )
    private_pressure_cue = trim_text(
        f"私下里每个人都在围着{surface_signals[2]}和{blueprint.taboo_secret}试探底牌，也在衡量要先{template.route_promise_verb_set[1]}谁；一旦失手就会触发{backlash_signal}。",
        220,
    )
    scene_goal = _play_facing_scene_goal(contract, tension_anchor=tension_anchor, blueprint=blueprint)
    emotional_goal = trim_text(
        f"让主角离{blueprint.protagonist_hidden_need}更近一步，但也更难保住体面，并让{public_cost_signal}与{backlash_signal}同时逼近。",
        220,
    )
    progression_rule_summary = trim_text(
        f"{_play_facing_progression_summary(contract, tension_anchor=tension_anchor, blueprint=blueprint)} 这一段要让{surface_signals[0]}可见，让{public_cost_signal}落地。",
        220,
    )
    move_priorities = _deterministic_move_priorities(contract)
    render_cues = unique_preserve(
        [
            f"style:shell:{blueprint.story_shell_id}",
            f"style:segment:{contract.segment_role}",
            _control_render_cue_for_role(contract.segment_role),
            f"style:reason:{segment_style_profile.reason_families[0]}",
            f"style:signal:{segment_style_profile.signal_families[0]}",
            (
                "style:bomb:public_drop"
                if contract.segment_role in {"reveal", "terminal"}
                else f"style:cadence:{segment_style_profile.cadence_order[0]}"
            ),
            "style:cost:landed" if contract.segment_role in {"reveal", "terminal"} else "style:impact:rising",
        ]
    )
    return SegmentPlaybook(
        segment_id=contract.segment_id,
        scene_goal=scene_goal,
        emotional_goal=emotional_goal,
        move_priorities=move_priorities,
        public_pressure_cue=public_pressure_cue,
        private_pressure_cue=private_pressure_cue,
        progression_rule_summary=progression_rule_summary,
        suggestion_lanes=_compile_suggestion_lanes(blueprint, contract, bound_cast),
        render_cues=render_cues[:5],
        template_tone_example_lines=template_tone_example_lines[:4],
        template_tone_scene_examples=template_tone_scene_examples[:2],
        tone_example_pack=tone_example_pack,
        segment_style_profile=segment_style_profile,
        scene_active_cap=3,
    )


def _segment_control_contract_guidance(
    *,
    blueprint: AcceptedBlueprint,
    contract: SegmentContract,
    bound_cast: list[BoundIPCastMember],
    deterministic_playbook: SegmentPlaybook,
) -> dict[str, str]:
    members = _members_by_id(bound_cast)
    focus_name = next(
        (
            members[character_id].display_name
            for character_id in contract.focus_target_ids
            if character_id in members
        ),
        "对方",
    )
    must_yield_side = f"优先让{focus_name}在台面上先表态，不要只停在解释。"
    yield_cost = trim_text(
        f"让步代价要落到{blueprint.cost_of_truth}，并影响{blueprint.route_promise}的路径选择。",
        220,
    )
    refuse_escalation = {
        "opening": "拒绝后会升级为公开试探与站位拉扯。",
        "misread": "拒绝后会升级为误读放大和当面拆台。",
        "pressure": "拒绝后会升级为切割与追责。",
        "reversal": "拒绝后会升级为反手换边与翻牌。",
        "reveal": "拒绝后会升级为公开翻牌并外溢到旁观席。",
        "terminal": "拒绝后会升级为终局切割且难以回撤。",
    }.get(contract.segment_role, "拒绝后会继续升级并放大后果。")
    settlement_window = (
        "窗口就在本段这一拍，拖延会让局势自动外溢。"
        if contract.segment_role in {"reveal", "terminal", "pressure"}
        else "窗口较短，这段内必须给出可执行让步。"
    )
    observable_evidence = trim_text(
        f"可见证据优先来自 {deterministic_playbook.public_pressure_cue} / {deterministic_playbook.private_pressure_cue}",
        220,
    )
    return {
        "must_yield_side": trim_text(must_yield_side, 220),
        "yield_cost": yield_cost,
        "refuse_escalation": trim_text(refuse_escalation, 220),
        "settlement_window": trim_text(settlement_window, 220),
        "observable_evidence": observable_evidence,
    }


def _validate_live_playbook(
    deterministic_playbook: SegmentPlaybook,
    live_playbook_delta: dict[str, Any],
) -> SegmentPlaybook:
    live_playbook_delta = _sanitize_segment_playbook_delta_payload(live_playbook_delta)
    try:
        parsed = SegmentPlaybookDelta.model_validate(live_playbook_delta)
    except ValidationError as exc:
        _raise_payload_validation_error(
            exc,
            payload=live_playbook_delta,
            required_keys=(),
        )
    update: dict[str, Any] = {}
    if parsed.public_pressure_cue is not None:
        update["public_pressure_cue"] = parsed.public_pressure_cue
    if parsed.private_pressure_cue is not None:
        update["private_pressure_cue"] = parsed.private_pressure_cue
    if parsed.progression_rule_summary is not None:
        update["progression_rule_summary"] = parsed.progression_rule_summary
    if parsed.render_cues is not None:
        update["render_cues"] = parsed.render_cues[:5]
    if not update:
        return deterministic_playbook
    return deterministic_playbook.model_copy(update=update)


def _compile_segment_with_mode(
    *,
    blueprint: AcceptedBlueprint,
    contract: SegmentContract,
    bound_cast: list[BoundIPCastMember],
    live_mode: AuthorV2RunMode,
    control_contract_hint_weight: float = 1.0,
) -> tuple[SegmentPlaybook, list[dict[str, Any]], list[str], bool, dict[str, Any]]:
    deterministic_playbook = _compile_single_segment(
        blueprint=blueprint,
        contract=contract,
        bound_cast=bound_cast,
    )
    if live_mode == "deterministic":
        return deterministic_playbook, [], [], False, {
            "live_attempt_count": 0,
            "live_success_count": 0,
            "provider_failure_count": 0,
            "used_modes": [],
        }
    gateways = _resolve_live_gateway(live_mode, None)
    if not gateways:
        return deterministic_playbook, [], ["retry_exhausted:live_gateway_unavailable"], False, {
            "live_attempt_count": 0,
            "live_success_count": 0,
            "provider_failure_count": 0,
            "used_modes": [],
        }
    combined_trace: list[dict[str, Any]] = []
    attempt_failures: list[str] = []
    live_attempt_count = 0
    provider_failure_count = 0
    used_modes: list[str] = []
    allow_live_downgrade = _allow_live_downgrade(live_mode)
    active_gateways = gateways if allow_live_downgrade else gateways[:1]
    gateway_index = 0
    while live_attempt_count < MAX_STAGE_REGEN_ATTEMPTS and active_gateways:
        source_mode, resolved_gateway = active_gateways[gateway_index % len(active_gateways)]
        gateway = _segment_playbook_gateway(
            _hero_budget_gateway(resolved_gateway, template_id=blueprint.template_id, stage="segment_playbook"),
            live_mode=live_mode,
        )
        trace_cursor = len(gateway.call_trace)
        live_attempt_count += 1
        started = perf_counter()
        response_payload: dict[str, Any] | None = None
        playbook_payload: dict[str, Any] | None = None
        try:
            retry_feedback = attempt_failures[-1] if attempt_failures else None
            request_payload: dict[str, Any] = {
                "accepted_blueprint_summary": {
                    "story_shell_id": blueprint.story_shell_id,
                    "social_arena": blueprint.social_arena,
                    "route_promise": blueprint.route_promise,
                    "bomb_moment": blueprint.bomb_moment,
                    "cost_of_truth": blueprint.cost_of_truth,
                    "protagonist_hidden_need": blueprint.protagonist_hidden_need,
                },
                "segment_contract_summary": {
                    "segment_id": contract.segment_id,
                    "segment_role": contract.segment_role,
                    "focus_target_ids": contract.focus_target_ids,
                    "rival_target_ids": contract.rival_target_ids,
                    "allocated_secret_ids": contract.allocated_secret_ids,
                    "venue_id": contract.venue_id,
                },
                "local_cast_meta": [
                    {
                        "character_id": member.character_id,
                        "display_name": member.display_name,
                        "slot_function": member.slot_function,
                        "public_role": member.public_role,
                        "speech_pattern": member.speech_pattern,
                        "charisma_hook": member.charisma_hook,
                        "danger_hook": member.danger_hook,
                        "relationship_to_protagonist": member.relationship_to_protagonist,
                    }
                    for member in bound_cast
                ],
                "playbook_base": {
                    "scene_goal": deterministic_playbook.scene_goal,
                    "emotional_goal": deterministic_playbook.emotional_goal,
                    "public_pressure_cue": deterministic_playbook.public_pressure_cue,
                    "private_pressure_cue": deterministic_playbook.private_pressure_cue,
                    "progression_rule_summary": deterministic_playbook.progression_rule_summary,
                    "move_priorities": deterministic_playbook.move_priorities,
                    "render_cues": deterministic_playbook.render_cues,
                },
                "allowed_move_families": contract.allowed_move_families,
                "control_contract_hint_weight": round(float(control_contract_hint_weight), 4),
                "control_contract_reference": _segment_control_contract_guidance(
                    blueprint=blueprint,
                    contract=contract,
                    bound_cast=bound_cast,
                    deterministic_playbook=deterministic_playbook,
                ),
                "regeneration_index": live_attempt_count,
                "max_regeneration_attempts": MAX_STAGE_REGEN_ATTEMPTS,
            }
            if retry_feedback:
                request_payload["validation_feedback"] = retry_feedback
            payload_bytes = len(json.dumps(request_payload, ensure_ascii=False))
            response = gateway.invoke_json(
                system_prompt=SEGMENT_PLAYBOOK_SYSTEM_PROMPT,
                user_payload=request_payload,
                max_output_tokens=gateway.max_output_tokens_segment_playbook,
                operation_name="author_v2.segment_playbook",
            )
            combined_trace.extend(
                [
                    {
                        **entry,
                        "stage": "compile_segment_playbooks",
                        "mode": gateway.profile_id,
                        "model": gateway.model,
                        "duration_seconds": round(perf_counter() - started, 4),
                        "retry_count": live_attempt_count - 1,
                        "segment_id": contract.segment_id,
                        "payload_bytes": payload_bytes,
                    }
                    for entry in gateway.call_trace[trace_cursor:]
                ]
            )
            response_payload = response.payload
            playbook_payload = _coerce_playbook_payload(response_payload)
            validated_playbook = _validate_live_playbook(
                deterministic_playbook,
                playbook_payload,
            )
            if source_mode not in used_modes:
                used_modes.append(source_mode)
            return validated_playbook, combined_trace, list(attempt_failures), True, {
                "live_attempt_count": live_attempt_count,
                "live_success_count": sum(1 for entry in combined_trace if entry.get("response_received")),
                "provider_failure_count": provider_failure_count,
                "used_modes": used_modes,
            }
        except Exception as exc:  # noqa: BLE001
            combined_trace.extend(
                [
                    {
                        **entry,
                        "stage": "compile_segment_playbooks",
                        "mode": gateway.profile_id,
                        "model": gateway.model,
                        "duration_seconds": round(perf_counter() - started, 4),
                        "retry_count": live_attempt_count - 1,
                        "segment_id": contract.segment_id,
                        "payload_bytes": len(json.dumps(request_payload, ensure_ascii=False)),
                    }
                    for entry in gateway.call_trace[trace_cursor:]
                ]
            )
            if combined_trace and response_payload is not None:
                diagnostic_payload = playbook_payload if isinstance(playbook_payload, dict) else response_payload
                combined_trace[-1]["validation_failed_reason"] = fallback_reason(exc)
                combined_trace[-1]["returned_keys"] = sorted(str(key) for key in diagnostic_payload.keys())[:10]
                combined_trace[-1]["missing_required_keys"] = []
            attempt_failures.append(f"{source_mode}:{fallback_reason(exc)}")
            if is_provider_failure(exc):
                provider_failure_count += 1
        gateway_index += 1
    exhausted_reason = attempt_failures[-1] if attempt_failures else "live_gateway_unavailable"
    return deterministic_playbook, combined_trace, [f"retry_exhausted:{exhausted_reason}"], False, {
        "live_attempt_count": live_attempt_count,
        "live_success_count": sum(1 for entry in combined_trace if entry.get("response_received")),
        "provider_failure_count": provider_failure_count,
        "used_modes": used_modes,
    }


def compile_segment_playbooks(state: AuthorPlayState) -> AuthorPlayState:
    blueprint = state["accepted_blueprint"]
    contracts = state["segment_contracts"]
    bound_cast = state["bound_cast"]
    live_mode = state.get("live_mode", "deterministic")
    quality_tuning_profile = _apply_quality_tuning_patch(
        profile=_build_quality_tuning_profile(),
        patch_payload=_load_quality_tuning_patch(),
    )
    control_contract_hint_weight = float(quality_tuning_profile.author.control_contract_hint_weight)
    indexed_contracts = list(enumerate(contracts))
    results: dict[int, SegmentPlaybook] = {}
    trace_entries: list[dict[str, Any]] = list(state.get("llm_call_trace", []))
    reasons: list[str] = []
    fallback_count = 0
    aggregate_live_attempt_count = 0
    aggregate_live_success_count = 0
    aggregate_provider_failure_count = 0
    used_modes: list[str] = []
    if live_mode == "deterministic":
        max_workers = min(4, len(indexed_contracts))
    else:
        # strict 评测下优先稳定性：串行编译可显著降低 provider 超时放大。
        max_workers = min(1 if _strict_no_repair_fallback_enabled() else 2, len(indexed_contracts))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                _compile_segment_with_mode,
                blueprint=blueprint,
                contract=contract,
                bound_cast=[
                    member
                    for member in bound_cast
                    if member.character_id in set(contract.focus_target_ids + contract.rival_target_ids) or member.is_route_target
                ][:3]
                or bound_cast[:3],
                live_mode=live_mode,
                control_contract_hint_weight=control_contract_hint_weight,
            ): index
            for index, contract in indexed_contracts
        }
        for future in as_completed(future_map):
            index = future_map[future]
            playbook, new_trace, new_reasons, live_success, metrics = future.result()
            results[index] = playbook
            trace_entries.extend(new_trace)
            reasons.extend(new_reasons)
            aggregate_live_attempt_count += int(metrics.get("live_attempt_count", 0))
            aggregate_live_success_count += int(metrics.get("live_success_count", 0))
            aggregate_provider_failure_count += int(metrics.get("provider_failure_count", 0))
            for mode in metrics.get("used_modes", []):
                if mode not in used_modes:
                    used_modes.append(str(mode))
            if live_mode != "deterministic" and not live_success:
                fallback_count += 1
    ordered_playbooks = [results[index] for index in sorted(results)]
    outcome = "accepted"
    source = "deterministic" if live_mode == "deterministic" else live_mode
    if live_mode != "deterministic" and fallback_count:
        exhausted_reason = next(
            (
                str(reason)
                for reason in reasons
                if isinstance(reason, str) and reason.startswith("retry_exhausted:")
            ),
            "retry_exhausted:segment_compile_failed",
        )
        outcome, outcome_reasons = _retry_exhausted_outcome(exhausted_reason.replace("retry_exhausted:", "", 1))
        reasons = [*outcome_reasons, f"segment_retry_exhausted_count:{fallback_count}"]
    elif live_mode != "deterministic":
        reasons = sorted(set(reasons))
    return {
        "segment_playbooks": ordered_playbooks,
        "llm_call_trace": trace_entries,
        "quality_trace": _append_quality(
            state,
            stage="compile_segment_playbooks",
            outcome=outcome,
            reasons=reasons,
            source=source,
            metrics=_quality_metrics(
                requested_mode=live_mode,
                actual_mode=(
                    "deterministic"
                    if aggregate_live_success_count == 0
                    else used_modes[0] if len(used_modes) == 1 and fallback_count == 0
                    else "mixed"
                ),
                used_live_output=aggregate_live_success_count > 0,
                live_attempt_count=aggregate_live_attempt_count,
                live_success_count=aggregate_live_success_count,
                provider_failure_count=aggregate_provider_failure_count,
                actual_modes=[*used_modes, *(["deterministic"] if fallback_count else [])],
            ),
        ),
    }


def compile_ending_matrix(state: AuthorPlayState) -> AuthorPlayState:
    blueprint = state["accepted_blueprint"]
    route_targets = [member for member in state["bound_cast"] if member.is_route_target]
    terminal_segment_id = next(contract.segment_id for contract in state["segment_contracts"] if contract.is_terminal)
    endings = [
        RouteEndingSpec(
            ending_id="burned_alone",
            label="体面烧穿",
            summary=trim_text(f"主角把{blueprint.taboo_secret}说破了，却没能留下任何人。", 220),
            lane_id=None,
            target_id=None,
            min_lane_count=0,
            min_route_lock=0,
            min_affection=-3,
            min_trust=-3,
            min_dependency=0,
            min_scene_heat=0,
            min_secret_exposure=0,
            min_public_events=0,
            required_secret_ids=[],
            terminal_segment_id=terminal_segment_id,
        )
    ]
    endings.append(
        RouteEndingSpec(
            ending_id="burst_reckoning",
            label="公开翻盘",
            summary=trim_text("你把所有人拖进公开对决，场面炸穿了，但胜负终于被当众定下。", 220),
            lane_id="burst",
            target_id=None,
            min_lane_count=2,
            min_route_lock=0,
            min_affection=-3,
            min_trust=-3,
            min_dependency=0,
            min_scene_heat=4,
            min_secret_exposure=2,
            min_public_events=1,
            required_secret_ids=["taboo_secret"],
            terminal_segment_id=terminal_segment_id,
        )
    )
    for member in route_targets:
        endings.append(
            RouteEndingSpec(
                ending_id=f"relationship_{member.character_id}",
                label=f"{member.display_name}关系线",
                summary=trim_text(
                    f"主角和{member.display_name}在混乱里完成了私下绑定，决定一起扛下{blueprint.cost_of_truth}。",
                    220,
                ),
                lane_id="relationship",
                target_id=member.character_id,
                min_lane_count=2,
                min_route_lock=1,
                min_affection=4,
                min_trust=2,
                min_dependency=1,
                max_scene_heat=2,
                max_secret_exposure=1,
                max_suspicion=3,
                required_secret_ids=[],
                terminal_segment_id=terminal_segment_id,
            )
        )
        endings.append(
            RouteEndingSpec(
                ending_id=f"side_{member.character_id}",
                label=f"{member.display_name}站队线",
                summary=trim_text(
                    f"主角最终公开或半公开站到{member.display_name}一边，把这场局势锁成了无法回头的阵营选择。",
                    220,
                ),
                lane_id="side",
                target_id=member.character_id,
                min_lane_count=2,
                min_route_lock=2,
                min_affection=0,
                min_trust=2,
                min_dependency=0,
                max_scene_heat=4,
                max_suspicion=4,
                required_secret_ids=[],
                terminal_segment_id=terminal_segment_id,
            )
        )
    endings.append(
        RouteEndingSpec(
            ending_id="pyrrhic_control",
            label="赢了局，输了真心",
            summary=trim_text("主角保住了位置，却把所有亲密关系都谈成了交换条件。", 220),
            lane_id=None,
            target_id=None,
            min_lane_count=0,
            min_route_lock=2,
            min_affection=-3,
            min_trust=0,
            min_dependency=0,
            min_scene_heat=2,
            min_secret_exposure=1,
            max_public_image=2,
            required_secret_ids=[],
            terminal_segment_id=terminal_segment_id,
        )
    )
    return {
        "ending_matrix": EndingMatrix(endings=endings[:12]),
        "quality_trace": _append_quality(state, stage="compile_ending_matrix", outcome="accepted"),
    }


def assemble_urban_bundle(state: AuthorPlayState) -> AuthorPlayState:
    blueprint = state["accepted_blueprint"]
    story_id = f"urban_{slugify(blueprint.prompt_seed)[:24]}_{uuid4().hex[:6]}"
    route_names = [member.display_name for member in state["bound_cast"] if member.is_route_target][:2]
    title_tail = " / ".join(route_names) if route_names else normalize_whitespace(blueprint.social_arena)
    title = trim_text(f"{blueprint.protagonist_public_identity}·{title_tail}", 120)
    opening_narration = _play_facing_opening_narration(blueprint)
    bundle = UrbanAuthorBundle(
        story_id=story_id,
        title=title,
        accepted_blueprint=blueprint,
        fit_mode=blueprint.fit_mode,
        template_id=blueprint.template_id,
        seed_fingerprint=blueprint.seed_fingerprint,
        arc_template_id=state["arc_template_id"],
        cast_slots=state["cast_slots"],
        bound_cast=state["bound_cast"],
        voice_atoms_by_character=state.get("voice_atoms_by_character", {}),
        segment_contracts=state["segment_contracts"],
        segment_playbooks=state["segment_playbooks"],
        ending_matrix=state["ending_matrix"],
        opening_narration=opening_narration,
    )
    return {
        "urban_bundle": bundle,
        "quality_trace": _append_quality(state, stage="assemble_urban_bundle", outcome="accepted"),
    }


def _question_progress_policy() -> QuestionProgressPolicy:
    return QuestionProgressPolicy(
        min_status_by_segment_role={
            "opening": "tightening",
            "misread": "tightening",
            "pressure": "flip",
            "reversal": "flip",
            "reveal": "flip",
            "terminal": "resolved",
        },
        key_segment_force_flip_if_no_trigger=True,
        key_segment_force_resolve_secret_exposure=3,
        key_segment_force_resolve_progress_threshold=1,
    )


def _build_question_arc_policy_v2(
    *,
    segment_contracts: list[SegmentContract],
    question_progress_policy: QuestionProgressPolicy,
) -> QuestionArcPolicyV2:
    by_segment_id: dict[str, QuestionArcSegmentPolicyV2] = {}
    key_segment_roles = {"reveal", "terminal"}
    for segment in segment_contracts:
        min_status = question_progress_policy.min_status_by_segment_role.get(segment.segment_role, "open")
        by_segment_id[segment.segment_id] = QuestionArcSegmentPolicyV2(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            scene_question_id=segment.segment_id,
            minimum_status=min_status,  # type: ignore[arg-type]
            key_segment_require_conversion_if_no_trigger=segment.segment_role in key_segment_roles,
            force_resolve_secret_exposure=question_progress_policy.key_segment_force_resolve_secret_exposure,
            force_resolve_progress_threshold=question_progress_policy.key_segment_force_resolve_progress_threshold,
        )
    return QuestionArcPolicyV2(
        by_segment_id=by_segment_id,
        key_segment_roles=["reveal", "terminal"],
    )


def _segment_reason_priority(segment_role: str, shell_id: str) -> list[ToneReasonFamily]:
    base: dict[str, list[ToneReasonFamily]] = {
        "opening": ["opportunity_window", "self_preserve", "loss_position", "mixed"],
        "misread": ["opportunity_window", "self_preserve", "loss_position", "mixed"],
        "pressure": ["self_preserve", "loss_position", "old_debt", "opportunity_window"],
        "reversal": ["loss_position", "old_debt", "self_preserve", "opportunity_window"],
        "reveal": ["loss_position", "old_debt", "self_preserve", "opportunity_window"],
        "terminal": ["old_debt", "loss_position", "self_preserve", "opportunity_window"],
    }
    chosen = list(base.get(segment_role, base["pressure"]))
    if shell_id == "entertainment_scandal" and segment_role in {"reveal", "terminal"}:
        chosen = ["self_preserve", "old_debt", "loss_position", "opportunity_window"]
    elif shell_id == "campus_romance" and segment_role in {"pressure", "reveal", "terminal"}:
        chosen = ["loss_position", "self_preserve", "old_debt", "opportunity_window"]
    elif shell_id == "office_power" and segment_role in {"reversal", "reveal", "terminal"}:
        chosen = ["loss_position", "self_preserve", "opportunity_window", "old_debt"]
    elif shell_id == "wealth_families" and segment_role in {"reversal", "reveal", "terminal"}:
        chosen = ["loss_position", "old_debt", "self_preserve", "opportunity_window"]
    return chosen[:4]


def _default_stake_priority_for_shell(shell_id: str) -> list[str]:
    mapping: dict[str, list[str]] = {
        "campus_romance": ["eligibility", "relationship", "reputation", "position"],
        "entertainment_scandal": ["narrative_control", "reputation", "position", "relationship"],
        "office_power": ["position", "reputation", "relationship", "narrative_control"],
        "wealth_families": ["lineage", "position", "reputation", "relationship"],
    }
    return list(mapping.get(shell_id, ["position", "reputation", "relationship", "narrative_control"]))[:4]


def _segment_stake_priority(
    *,
    segment: SegmentContract,
    cast: list[BoundIPCastMember],
    shell_id: str,
) -> list[str]:
    cast_by_id = {member.character_id: member for member in cast}
    ordered_ids = unique_preserve([*segment.focus_target_ids, *segment.rival_target_ids])
    stakes: list[str] = []
    for character_id in ordered_ids:
        member = cast_by_id.get(character_id)
        if member is None:
            continue
        stake = member.strategic_intent.primary_stake
        if stake and stake not in stakes:
            stakes.append(stake)
    for fallback in _default_stake_priority_for_shell(shell_id):
        if fallback not in stakes:
            stakes.append(fallback)
        if len(stakes) >= 4:
            break
    return stakes[:4]


def _build_segment_interest_policy(
    *,
    shell_id: str,
    segment_contracts: list[SegmentContract],
    cast: list[BoundIPCastMember],
) -> SegmentInterestPolicy:
    by_segment_id: dict[str, SegmentInterestPolicyItem] = {}
    for segment in segment_contracts:
        reason_priority = _segment_reason_priority(segment.segment_role, shell_id)
        dominant_reason = reason_priority[0] if reason_priority else "mixed"
        by_segment_id[segment.segment_id] = SegmentInterestPolicyItem(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            dominant_reason_family=dominant_reason,  # type: ignore[arg-type]
            reason_priority=reason_priority,
            stake_priority=_segment_stake_priority(segment=segment, cast=cast, shell_id=shell_id),
        )
    return SegmentInterestPolicy(
        by_segment_id=by_segment_id,
        default_reason_priority=_segment_reason_priority("pressure", shell_id),
        default_stake_priority=_default_stake_priority_for_shell(shell_id),  # type: ignore[arg-type]
    )


def _build_supporting_divergence_policy(shell_id: str) -> SupportingDivergencePolicy:
    counter_priority: dict[str, list[ToneReasonFamily]] = {
        "opening": ["opportunity_window", "loss_position", "self_preserve"],
        "misread": ["opportunity_window", "loss_position", "self_preserve"],
        "pressure": ["loss_position", "old_debt", "self_preserve"],
        "reversal": ["old_debt", "loss_position", "opportunity_window"],
        "reveal": ["loss_position", "old_debt", "opportunity_window"],
        "terminal": ["old_debt", "loss_position", "opportunity_window"],
    }
    crowd_priority: dict[str, list[ToneReasonFamily]] = {
        "opening": ["self_preserve", "opportunity_window", "mixed"],
        "misread": ["self_preserve", "opportunity_window", "mixed"],
        "pressure": ["self_preserve", "opportunity_window", "loss_position"],
        "reversal": ["self_preserve", "opportunity_window", "old_debt"],
        "reveal": ["self_preserve", "opportunity_window", "loss_position"],
        "terminal": ["self_preserve", "opportunity_window", "old_debt"],
    }
    if shell_id == "entertainment_scandal":
        counter_priority["reveal"] = ["old_debt", "loss_position", "opportunity_window"]
        crowd_priority["reveal"] = ["self_preserve", "opportunity_window", "mixed"]
    elif shell_id == "campus_romance":
        counter_priority["reveal"] = ["loss_position", "old_debt", "self_preserve"]
        crowd_priority["reveal"] = ["self_preserve", "loss_position", "opportunity_window"]
    key_pairs = [
        SupportingReasonPair(counter_reason="loss_position", crowd_reason="self_preserve"),
        SupportingReasonPair(counter_reason="old_debt", crowd_reason="self_preserve"),
        SupportingReasonPair(counter_reason="opportunity_window", crowd_reason="self_preserve"),
    ]
    return SupportingDivergencePolicy(
        require_reason_family_split=True,
        key_segment_roles=["reveal", "terminal"],
        counter_reason_priority_by_segment_role=counter_priority,  # type: ignore[arg-type]
        crowd_reason_priority_by_segment_role=crowd_priority,  # type: ignore[arg-type]
        key_segment_required_pairs=key_pairs,
    )


def _build_role_divergence_matrix(
    *,
    segment_contracts: list[SegmentContract],
    segment_interest_policy: SegmentInterestPolicy,
    divergence_policy: SupportingDivergencePolicy,
) -> RoleDivergenceMatrix:
    by_segment_id: dict[str, RoleDivergenceSegmentRule] = {}
    key_roles = set(divergence_policy.key_segment_roles)
    for segment in segment_contracts:
        segment_interest = segment_interest_policy.by_segment_id.get(segment.segment_id)
        counter_priority = list(divergence_policy.counter_reason_priority_by_segment_role.get(segment.segment_role, []))
        crowd_priority = list(divergence_policy.crowd_reason_priority_by_segment_role.get(segment.segment_role, []))
        if segment_interest is not None:
            counter_priority = unique_preserve([*segment_interest.reason_priority, *counter_priority])[:4]
            crowd_priority = unique_preserve([*crowd_priority, *segment_interest.reason_priority])[:4]
        if not counter_priority:
            counter_priority = list(segment_interest_policy.default_reason_priority[:4])
        if not crowd_priority:
            crowd_priority = list(segment_interest_policy.default_reason_priority[:4])
        by_segment_id[segment.segment_id] = RoleDivergenceSegmentRule(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            min_distinct_functions=2,
            require_counter_crowd_reason_split=divergence_policy.require_reason_family_split,
            counter_reason_priority=counter_priority,
            crowd_reason_priority=crowd_priority,
            key_segment_required_pairs=list(divergence_policy.key_segment_required_pairs[:4]) if segment.segment_role in key_roles else [],
        )
    default_counter = list(divergence_policy.counter_reason_priority_by_segment_role.get("pressure", [])) or list(segment_interest_policy.default_reason_priority)
    default_crowd = list(divergence_policy.crowd_reason_priority_by_segment_role.get("pressure", [])) or list(segment_interest_policy.default_reason_priority)
    return RoleDivergenceMatrix(
        by_segment_id=by_segment_id,
        key_segment_roles=list(divergence_policy.key_segment_roles),
        default_counter_reason_priority=default_counter[:4],
        default_crowd_reason_priority=default_crowd[:4],
    )


def _build_stake_axis_priority_policy(segment_interest_policy: SegmentInterestPolicy) -> StakeAxisPriorityPolicy:
    return StakeAxisPriorityPolicy(
        by_segment_id={
            segment_id: list(item.stake_priority[:4])
            for segment_id, item in segment_interest_policy.by_segment_id.items()
        },
        default_priority=list(segment_interest_policy.default_stake_priority[:4]),
    )


def _build_reason_family_priority_policy(segment_interest_policy: SegmentInterestPolicy) -> ReasonFamilyPriorityPolicy:
    return ReasonFamilyPriorityPolicy(
        by_segment_id={
            segment_id: list(item.reason_priority[:4])
            for segment_id, item in segment_interest_policy.by_segment_id.items()
        },
        default_priority=list(segment_interest_policy.default_reason_priority[:4]),
    )


def _all_move_families() -> list[RelationshipMoveFamily]:
    return [
        "flirt",
        "probe_secret",
        "comfort",
        "deflect",
        "accuse",
        "ally_with",
        "betray",
        "public_reveal",
        "private_confession",
        "jealousy_trigger",
    ]


def _cost_rule_payload(move_family: RelationshipMoveFamily) -> tuple[dict[str, int], dict[str, int], str]:
    global_deltas: dict[str, int] = {}
    rel_deltas: dict[str, int] = {}
    if move_family in {"public_reveal", "betray", "accuse"}:
        global_deltas.update({"public_image": -1, "route_lock": 1})
    elif move_family in {"comfort", "flirt", "ally_with"}:
        global_deltas.update({"scene_heat": 1})
    if move_family in {"accuse", "betray"}:
        rel_deltas.update({"trust": -1, "tension": 1})
    elif move_family in {"comfort", "ally_with", "private_confession"}:
        rel_deltas.update({"trust": 1, "suspicion": -1})
    elif move_family in {"deflect", "probe_secret", "jealousy_trigger", "public_reveal"}:
        rel_deltas.update({"suspicion": 1})
    payoff_family = "mixed"
    if move_family in {"public_reveal", "probe_secret"}:
        payoff_family = "secret_leak"
    elif move_family in {"ally_with", "betray", "accuse"}:
        payoff_family = "status_loss"
    elif move_family in {"flirt", "comfort", "private_confession"}:
        payoff_family = "social_isolation"
    return global_deltas, rel_deltas, payoff_family


def _build_cost_ownership_policy() -> CostOwnershipPolicy:
    rules: list[CostOwnershipRule] = []
    aggressive_moves = {"accuse", "betray", "public_reveal"}
    for move_family in _all_move_families():
        for control_action in ("none", "press", "redirect", "detonate"):
            owner_mode = "target"
            deferred_owner_mode = "target"
            transferred_owner_mode = None
            if control_action == "redirect":
                owner_mode = "control_target"
                deferred_owner_mode = "control_target"
                transferred_owner_mode = "control_target"
            elif move_family in aggressive_moves:
                owner_mode = "rival"
            elif move_family in {"comfort", "ally_with", "private_confession"}:
                owner_mode = "focus"
            rules.append(
                CostOwnershipRule(
                    rule_id=f"owner_{move_family}_{control_action}",
                    move_family=move_family,
                    control_action=control_action,
                    segment_role="any",
                    owner_mode=owner_mode,  # type: ignore[arg-type]
                    deferred_owner_mode=deferred_owner_mode,  # type: ignore[arg-type]
                    transferred_owner_mode=transferred_owner_mode,  # type: ignore[arg-type]
                )
            )
    return CostOwnershipPolicy(
        rules=rules[:80],
        fallback_owner_mode="target",
    )


def _build_cost_routing_matrix() -> CostRoutingMatrixPolicy:
    deferred_kind_map = {
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
    rules: list[CostRoutingRule] = []
    for move_family in _all_move_families():
        global_deltas, rel_deltas, payoff_family = _cost_rule_payload(move_family)
        for control_action, route_kind in (
            ("none", "immediate_cost"),
            ("press", "deferred_cost"),
            ("redirect", "transferred_cost"),
            ("detonate", "immediate_cost"),
        ):
            enable_callback = control_action != "detonate" and move_family in deferred_kind_map
            rules.append(
                CostRoutingRule(
                    rule_id=f"cost_{move_family}_{control_action}",
                    move_family=move_family,
                    control_action=control_action,
                    route_kind=route_kind,
                    global_deltas=global_deltas,
                    target_relationship_deltas=rel_deltas,
                    fallback_payoff_family=payoff_family,
                    deferred_kind=deferred_kind_map.get(move_family),
                    enable_callback=enable_callback,
                )
            )
    return CostRoutingMatrixPolicy(
        rules=rules[:80],
        public_scene_heat_bonus=1,
        key_segment_heat_bonus=1,
        fallback_global_delta_key="scene_heat",
        fallback_global_delta_value=1,
        fallback_target_relationship_delta_key="tension",
        fallback_target_relationship_delta_value=1,
    )


def _build_callback_policy() -> CallbackPolicy:
    rules: list[CallbackPolicyRule] = []
    for move_family in _all_move_families():
        for control_action, due_max in (
            ("none", 3),
            ("press", 2),
            ("redirect", 3),
            ("detonate", 0),
        ):
            enabled = control_action != "detonate"
            rules.append(
                CallbackPolicyRule(
                    rule_id=f"cb_{move_family}_{control_action}",
                    move_family=move_family,
                    control_action=control_action,
                    due_turn_min_offset=1,
                    due_turn_max_offset=due_max if due_max > 0 else 1,
                    base_global_deltas={"scene_heat": 1},
                    base_target_relationship_deltas={"tension": 1, "suspicion": 1},
                    fallback_payoff_kind="public_shame",
                    enabled=enabled,
                )
            )
    return CallbackPolicy(
        max_queue_size=8,
        per_turn_settle_cap=1,
        rules=rules[:80],
    )


def _build_cost_ownership_matrix_v2(policy: CostOwnershipPolicy) -> CostOwnershipMatrixV2:
    return CostOwnershipMatrixV2(
        rules=list(policy.rules[:80]),
        fallback_owner_mode=policy.fallback_owner_mode,
        require_owner_commit=True,
    )


def _build_callback_commit_policy_v2(policy: CallbackPolicy) -> CallbackCommitPolicyV2:
    return CallbackCommitPolicyV2(
        max_queue_size=policy.max_queue_size,
        per_turn_settle_cap=policy.per_turn_settle_cap,
        rules=list(policy.rules[:80]),
        require_deferred_commit=True,
        require_state_commit_on_settle=True,
    )


def _segment_cost_return_focus(*, segment_role: str, shell_id: str) -> str:
    if segment_role in {"reveal", "terminal"}:
        if shell_id == "campus_romance":
            return "who_gets_chased"
        if shell_id == "entertainment_scandal":
            return "who_takes_blame"
        return "who_pays"
    if segment_role in {"pressure", "reversal"}:
        return "who_takes_blame"
    return "who_gets_chased"


def _segment_cost_return_owner_priority(*, segment_role: str, shell_id: str) -> list[str]:
    if segment_role in {"reveal", "terminal"}:
        base = ["target", "rival", "control_target", "focus"]
    elif segment_role in {"pressure", "reversal"}:
        base = ["rival", "target", "focus", "active"]
    else:
        base = ["focus", "target", "rival", "active"]
    if shell_id == "entertainment_scandal":
        base = unique_preserve(["control_target", *base])
    elif shell_id == "campus_romance":
        base = unique_preserve(["rival", *base])
    return list(base[:4])


def _build_cost_return_policy(
    *,
    shell_id: str,
    segment_contracts: list[SegmentContract],
) -> CostReturnPolicy:
    by_segment_id: dict[str, CostReturnSegmentRule] = {}
    for segment in segment_contracts:
        by_segment_id[segment.segment_id] = CostReturnSegmentRule(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            max_return_turns=2 if segment.segment_role in {"reveal", "terminal"} else 3,
            owner_priority_modes=_segment_cost_return_owner_priority(
                segment_role=segment.segment_role,
                shell_id=shell_id,
            ),  # type: ignore[arg-type]
            scene_question_focus=_segment_cost_return_focus(
                segment_role=segment.segment_role,
                shell_id=shell_id,
            ),  # type: ignore[arg-type]
        )
    return CostReturnPolicy(
        by_segment_id=by_segment_id,
        default_max_return_turns=3,
        default_owner_priority_modes=["target", "rival", "focus"],
        default_scene_question_focus="who_pays",
    )


def _segment_cost_narrative_reason_priority(segment_role: str) -> list[ToneReasonFamily]:
    if segment_role in {"reveal", "terminal"}:
        return ["old_debt", "self_preserve", "blame_shift", "loss_position"]
    if segment_role in {"pressure", "reversal"}:
        return ["self_preserve", "old_debt", "blame_shift", "opportunity_window"]
    return ["old_debt", "self_preserve", "blame_shift", "mixed"]


def _build_cost_narrative_binding_policy(
    *,
    segment_contracts: list[SegmentContract],
) -> CostNarrativeBindingPolicy:
    by_segment_id: dict[str, CostNarrativeBindingSegmentRule] = {}
    for segment in segment_contracts:
        segment_role = segment.segment_role
        by_segment_id[segment.segment_id] = CostNarrativeBindingSegmentRule(
            segment_id=segment.segment_id,
            segment_role=segment_role,
            due_cost_driver="primary" if segment_role in {"reveal", "terminal"} else "secondary",
            due_primary_when_due=segment_role in {"pressure", "reversal", "reveal", "terminal"},
            require_main_clause_payer_beneficiary=True,
            reason_family_priority=_segment_cost_narrative_reason_priority(segment_role),
        )
    return CostNarrativeBindingPolicy(
        by_segment_id=by_segment_id,
        due_cost_forces_primary_driver=True,
    )


def _build_cost_primary_driver_policy_v7(
    *,
    segment_contracts: list[SegmentContract],
) -> CostPrimaryDriverPolicyV7:
    eligible_roles: list[SegmentRoleId] = ["pressure", "reversal", "reveal", "terminal"]
    by_segment_id: dict[str, CostPrimaryDriverSegmentRuleV7] = {}
    for segment in segment_contracts:
        by_segment_id[segment.segment_id] = CostPrimaryDriverSegmentRuleV7(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            eligible_segment_roles=eligible_roles,
            due_window_turns=3,
            player_override_mode="player_first",
            deferred_retry_bias=1 if segment.segment_role in {"opening", "misread"} else 2,
        )
    return CostPrimaryDriverPolicyV7(
        by_segment_id=by_segment_id,
        due_cost_forces_primary_driver=True,
    )


def _build_cost_escalation_ladder_policy_v8(
    *,
    segment_contracts: list[SegmentContract],
) -> CostEscalationLadderPolicyV8:
    by_segment_id: dict[str, CostEscalationLadderSegmentRuleV8] = {}
    for segment in segment_contracts:
        by_segment_id[segment.segment_id] = CostEscalationLadderSegmentRuleV8(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            stage1_turn_offset=1,
            stage2_turn_offset=2,
            stage3_turn_offset=3,
            stage1_pressure_bonus=1,
            stage1_maturity_bonus=1,
            stage2_pressure_bonus=2,
            stage2_maturity_bonus=2,
            stage3_force_question_cost_focus=True,
            stage3_force_primary_driver=True,
            allow_player_defer_once=True,
        )
    return CostEscalationLadderPolicyV8(
        by_segment_id=by_segment_id,
        enabled=True,
    )


def _build_control_signature_policy_v8() -> ControlSignaturePolicyV8:
    return ControlSignaturePolicyV8(
        by_action={
            "press": ControlSignatureRuleV8(
                action="press",
                expected_route_kind="deferred_cost",
                require_owner_beneficiary_split=False,
                require_pending_signal=True,
                require_immediate_impact=False,
                require_uncertainty_drop_signal=False,
            ),
            "redirect": ControlSignatureRuleV8(
                action="redirect",
                expected_route_kind="transferred_cost",
                require_owner_beneficiary_split=True,
                require_pending_signal=False,
                require_immediate_impact=False,
                require_uncertainty_drop_signal=False,
            ),
            "detonate": ControlSignatureRuleV8(
                action="detonate",
                expected_route_kind="immediate_cost",
                require_owner_beneficiary_split=False,
                require_pending_signal=False,
                require_immediate_impact=True,
                require_uncertainty_drop_signal=True,
            ),
        },
        require_distinct_signatures=True,
    )


def _role_function_lexicon_rows(shell_id: str) -> tuple[dict[str, tuple[list[str], list[str]]], dict[str, tuple[list[str], list[str]]]]:
    counter_rows: dict[str, tuple[list[str], list[str]]] = {
        "strike": (
            ["先出手", "先压话头", "先卡位", "先点名"],
            ["把矛头压向{primary}", "让{target}先背这一口", "把账直接挂到{primary}身上", "当场把锅位推给{primary}"],
        ),
        "self_preserve": (
            ["先护住自己", "先抽身", "先稳口径", "先留退路"],
            ["给自己留一条可撤的线", "把代价挡在自己外侧", "先保住{target}的体面壳", "把风险先推离自己"],
        ),
        "debt_play": (
            ["翻旧账", "借旧账发力", "按旧账追责", "拿旧账压人"],
            ["把之前那笔账当场抬上桌", "冲着{primary}把旧账连本带息翻回来", "让{target}为旧账先付这一拍", "把历史欠账改成现在的筹码"],
        ),
        "wait_flip": (
            ["等翻车点", "等破绽", "等风向倒向自己", "等你再露半寸"],
            ["盯着{primary}下一次失手", "把节奏压到更有利的窗口", "让{target}先把口风说死", "等局势自己滑到她那边"],
        ),
    }
    crowd_rows: dict[str, tuple[list[str], list[str]]] = {
        "strike": (
            ["起哄加压", "跟着抬高声量", "顺势补刀", "把风向推实"],
            ["把{primary}往失位方向推一步", "把{target}的解释空间压窄", "让这拍直接变成公开问责", "把锅位扩散给整圈人看"],
        ),
        "self_preserve": (
            ["装稳自保", "先避险", "先缩到安全侧", "先对齐大势"],
            ["让自己先离风险源远一点", "把站位往安全边挪半步", "把责任边界先画清", "先避免被卷进连带清算"],
        ),
        "debt_play": (
            ["替旧账加码", "帮着翻账", "顺手追旧责", "把旧账传开"],
            ["让旧账在圈内再滚一圈", "把{primary}的旧账记成当前证词", "把{target}和旧账绑成一组", "把历史欠账写成现在的立场"],
        ),
        "wait_flip": (
            ["围观等变盘", "等站队成形", "等下一拍再下注", "等切割窗口"],
            ["看{primary}下一句会不会彻底失手", "等{target}先把边站死", "等外面风向给出明牌", "等场上有人先掉位再跟进"],
        ),
    }
    if shell_id == "entertainment_scandal":
        counter_rows["strike"] = (
            ["先抢版本", "先切口径", "先占镜头", "先丢说法"],
            ["把{primary}推进镜头问责位", "让{target}先背热搜口径", "把锅先丢给{primary}的版本", "先把切割线画在{primary}那边"],
        )
        crowd_rows["wait_flip"] = (
            ["等热搜发酵", "等公关切割", "等镜头追焦", "等公屏定调"],
            ["看{primary}会不会被热搜先吞掉", "等{target}被公关线切出去", "等镜头把锅位钉死", "等外面风向先判定谁输"],
        )
    elif shell_id == "campus_romance":
        counter_rows["strike"] = (
            ["先站边", "先压台下", "先卡评审口径", "先点名问责"],
            ["把{primary}推到台下视线中心", "让{target}在评审前先接锅", "把名额压力先压给{primary}", "把站队账先记到{target}名下"],
        )
        crowd_rows["wait_flip"] = (
            ["等熟人圈表态", "等社团风向", "等评审态度", "等名额口风"],
            ["看{primary}会不会先在台下失位", "等{target}在熟人圈先被定义", "等评审先给出冷处理信号", "等社团里先有人换边"],
        )
    return counter_rows, crowd_rows


def _build_role_function_lexicon_policy_v8(
    *,
    shell_id: str,
    segment_contracts: list[SegmentContract],
) -> RoleFunctionLexiconPolicyV8:
    counter_rows, crowd_rows = _role_function_lexicon_rows(shell_id)
    by_segment_id: dict[str, RoleFunctionLexiconSegmentRuleV8] = {}
    for segment in segment_contracts:
        counter_entries = [
            RoleFunctionLexiconEntry(function_role=function_role, verbs=list(payload[0][:4]), receiver_templates=list(payload[1][:4]))
            for function_role, payload in counter_rows.items()
        ]
        crowd_entries = [
            RoleFunctionLexiconEntry(function_role=function_role, verbs=list(payload[0][:4]), receiver_templates=list(payload[1][:4]))
            for function_role, payload in crowd_rows.items()
        ]
        by_segment_id[segment.segment_id] = RoleFunctionLexiconSegmentRuleV8(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            counter_entries=counter_entries,
            crowd_entries=crowd_entries,
            enforce_counter_crowd_slot_split=True,
        )
    return RoleFunctionLexiconPolicyV8(by_segment_id=by_segment_id)


def _build_cost_visibility_contract(
    *,
    segment_contracts: list[SegmentContract],
) -> CostVisibilityContract:
    by_segment_id: dict[str, CostVisibilitySegmentRule] = {}
    for segment in segment_contracts:
        payer_floor = 2 if segment.segment_role in {"reveal", "terminal"} else 1
        beneficiary_floor = 1 if segment.segment_role in {"opening", "misread"} else 2 if segment.segment_role in {"reveal", "terminal"} else 1
        by_segment_id[segment.segment_id] = CostVisibilitySegmentRule(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            max_return_turns=3,
            require_visible_owner=True,
            require_main_clause_subject=True,
            require_two_sided_exchange=True,
            min_payer_loss=payer_floor,
            min_beneficiary_gain=beneficiary_floor,
            main_clause_subject_order=["payer", "beneficiary", "blamed_party"],
        )
    return CostVisibilityContract(by_segment_id=by_segment_id)


def _build_question_progress_policy_v2(
    *,
    segment_contracts: list[SegmentContract],
    question_progress_policy: QuestionProgressPolicy,
) -> QuestionProgressPolicyV2:
    by_segment_id: dict[str, QuestionProgressSegmentRuleV2] = {}
    for segment in segment_contracts:
        by_segment_id[segment.segment_id] = QuestionProgressSegmentRuleV2(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            minimum_status=question_progress_policy.min_status_by_segment_role.get(segment.segment_role, "open"),  # type: ignore[arg-type]
            require_cost_focus_when_due=True,
            require_non_stall_advance=True,
            key_segment_force_flip_if_no_trigger=segment.segment_role in {"reveal", "terminal"},
        )
    return QuestionProgressPolicyV2(by_segment_id=by_segment_id)


def _build_role_divergence_matrix_v2(
    *,
    segment_contracts: list[SegmentContract],
    role_divergence_matrix: RoleDivergenceMatrix,
) -> RoleDivergenceMatrixV2:
    by_segment_id: dict[str, RoleDivergenceSegmentRuleV2] = {}
    for segment in segment_contracts:
        current = role_divergence_matrix.by_segment_id.get(segment.segment_id)
        required_functions = ["strike", "self_preserve"]
        if segment.segment_role in {"reveal", "terminal"}:
            required_functions = ["strike", "self_preserve", "debt_play"]
        elif segment.segment_role in {"pressure", "reversal"}:
            required_functions = ["strike", "self_preserve", "wait_flip"]
        by_segment_id[segment.segment_id] = RoleDivergenceSegmentRuleV2(
            segment_id=segment.segment_id,
            segment_role=segment.segment_role,
            min_distinct_functions=max(2, int(current.min_distinct_functions if current is not None else 2)),
            required_functions=required_functions,  # type: ignore[arg-type]
            require_counter_crowd_reason_split=(
                bool(current.require_counter_crowd_reason_split) if current is not None else True
            ),
        )
    return RoleDivergenceMatrixV2(by_segment_id=by_segment_id)


def _build_utility_weight_profile() -> UtilityWeightProfile:
    return UtilityWeightProfile(
        intent_hit_weight=2,
        stake_hit_weight=1,
        latent_pressure_weight=1,
        role_diversity_weight=1,
        utility_delta_weight=1,
        shell_bias_weight=1,
        shell_bias_cap=3,
    )


def _build_cost_intensity_profile(shell_id: str) -> CostIntensityProfile:
    shell_multiplier: dict[str, float] = {
        "wealth_families": 1.0,
        "office_power": 1.05,
        "entertainment_scandal": 1.12,
        "campus_romance": 1.1,
        "urban_supernatural": 1.08,
    }
    return CostIntensityProfile(
        segment_role_multiplier={
            "opening": 0.92,
            "misread": 1.0,
            "pressure": 1.12,
            "reversal": 1.18,
            "reveal": 1.35,
            "terminal": 1.45,
        },
        control_action_multiplier={
            "none": 1.0,
            "press": 0.88,
            "redirect": 1.12,
            "detonate": 1.28,
            "any": 1.0,
        },
        shell_multiplier={
            "wealth_families": shell_multiplier["wealth_families"],
            "office_power": shell_multiplier["office_power"],
            "entertainment_scandal": shell_multiplier["entertainment_scandal"],
            "campus_romance": shell_multiplier["campus_romance"],
            "urban_supernatural": shell_multiplier["urban_supernatural"],
        },  # type: ignore[arg-type]
        payoff_family_multiplier={
            "public_shame": 1.15,
            "status_loss": 1.22,
            "secret_leak": 1.18,
            "social_isolation": 1.1,
        },
        latent_pressure_step_bonus=0.04,
        latent_pressure_bonus_cap=0.24,
        deferred_route_bonus=0.1,
        min_non_zero_delta=1,
        max_abs_delta_per_key=3,
    )


def _build_shell_propagation_graph(shell_id: str) -> ShellPropagationGraphPolicy:
    graph_rows: dict[str, list[ShellPropagationEdgePolicy]] = {
        "campus_romance": [
            ShellPropagationEdgePolicy(edge_id="campus_stage_to_audience", from_node="舞台", to_node="台下", anchor_token="台下", signal_family="peer_spread", note="舞台风波先落到台下眼神。", kind_hints=["public_wave"]),
            ShellPropagationEdgePolicy(edge_id="campus_audience_to_judges", from_node="台下", to_node="评审席", anchor_token="评审", signal_family="institutional_shift", note="台下情绪会把评审温度带偏。", kind_hints=["public_wave", "secret_pressure"]),
            ShellPropagationEdgePolicy(edge_id="campus_judges_to_slots", from_node="评审席", to_node="名额池", anchor_token="名额", signal_family="institutional_shift", note="评审态度会直接改名额预期。", kind_hints=["secret_pressure", "relationship_debt"]),
            ShellPropagationEdgePolicy(edge_id="campus_club_to_peers", from_node="社团核心", to_node="熟人圈", anchor_token="社团", signal_family="peer_spread", note="社团核心会把口风扩散到熟人圈。", kind_hints=["relationship_debt", "npc_action"]),
            ShellPropagationEdgePolicy(edge_id="campus_peers_to_alignment", from_node="熟人圈", to_node="站队层", anchor_token="站队", signal_family="peer_spread", note="熟人传播最终落成公开站队。", kind_hints=["npc_action"]),
        ],
        "entertainment_scandal": [
            ShellPropagationEdgePolicy(edge_id="ent_set_to_camera", from_node="现场", to_node="镜头", anchor_token="镜头", signal_family="public_wave", note="现场动作先被镜头定义。", kind_hints=["public_wave", "npc_action"]),
            ShellPropagationEdgePolicy(edge_id="ent_camera_to_screen", from_node="镜头", to_node="公屏", anchor_token="公屏", signal_family="public_wave", note="镜头叙事会在公屏被放大。", kind_hints=["public_wave"]),
            ShellPropagationEdgePolicy(edge_id="ent_screen_to_hotsearch", from_node="公屏", to_node="热搜", anchor_token="热搜", signal_family="public_wave", note="公屏节奏会被热搜接管。", kind_hints=["public_wave", "secret_pressure"]),
            ShellPropagationEdgePolicy(edge_id="ent_hotsearch_to_pr", from_node="热搜", to_node="公关线", anchor_token="公关", signal_family="institutional_shift", note="热搜变化会迫使公关线切口。", kind_hints=["secret_pressure", "relationship_debt"]),
            ShellPropagationEdgePolicy(edge_id="ent_pr_to_cutoff", from_node="公关线", to_node="切割链", anchor_token="切割", signal_family="institutional_shift", note="公关动作会转为切割执行。", kind_hints=["npc_action", "relationship_debt"]),
        ],
        "office_power": [
            ShellPropagationEdgePolicy(edge_id="office_room_to_line", from_node="会议桌", to_node="汇报线", anchor_token="会议室", signal_family="institutional_shift", note="会议桌风向会改汇报线口径。", kind_hints=["public_wave", "npc_action"]),
            ShellPropagationEdgePolicy(edge_id="office_line_to_review", from_node="汇报线", to_node="考核面", anchor_token="考核", signal_family="institutional_shift", note="汇报线会在考核里沉淀后果。", kind_hints=["secret_pressure", "relationship_debt"]),
            ShellPropagationEdgePolicy(edge_id="office_review_to_rank", from_node="考核面", to_node="职级线", anchor_token="职级", signal_family="institutional_shift", note="考核温度会改职级预期。", kind_hints=["relationship_debt", "npc_action"]),
        ],
        "wealth_families": [
            ShellPropagationEdgePolicy(edge_id="wealth_table_to_family", from_node="主桌", to_node="家族口风", anchor_token="家宴", signal_family="relationship_pressure", note="主桌波动会先改家宴口风。", kind_hints=["relationship_debt", "public_wave"]),
            ShellPropagationEdgePolicy(edge_id="wealth_family_to_order", from_node="家族口风", to_node="顺位线", anchor_token="顺位", signal_family="relationship_pressure", note="家族口风最终落到顺位判断。", kind_hints=["relationship_debt", "npc_action"]),
            ShellPropagationEdgePolicy(edge_id="wealth_order_to_board", from_node="顺位线", to_node="董事会", anchor_token="董事会", signal_family="institutional_shift", note="顺位变动会传导到董事会动作。", kind_hints=["secret_pressure", "npc_action"]),
        ],
    }
    edges = graph_rows.get(shell_id) or graph_rows["office_power"]
    key_segment_preferred = [edge.edge_id for edge in edges[:2]]
    return ShellPropagationGraphPolicy(
        shell_id=shell_id,  # type: ignore[arg-type]
        edges=edges,
        key_segment_preferred_edges=key_segment_preferred,
    )


def _build_propagation_priority_policy(
    *,
    shell_id: str,
    graph: ShellPropagationGraphPolicy,
) -> PropagationPriorityPolicy:
    edge_ids = [edge.edge_id for edge in graph.edges]
    opening_edge = edge_ids[:1] or graph.key_segment_preferred_edges[:1]
    mid_edges = edge_ids[1:3] or edge_ids[:2]
    key_edges = graph.key_segment_preferred_edges or edge_ids[-2:] or edge_ids[:1]
    edge_priority_by_segment_role: dict[str, list[str]] = {
        "opening": opening_edge,
        "misread": mid_edges,
        "pressure": mid_edges,
        "reversal": edge_ids[1:4] or mid_edges,
        "reveal": key_edges,
        "terminal": key_edges,
    }
    signal_bias_by_role: dict[str, ToneSignalFamily] = {
        "opening": "relationship_pressure",
        "misread": "relationship_pressure",
        "pressure": "institutional_shift",
        "reversal": "institutional_shift",
        "reveal": "institutional_shift",
        "terminal": "institutional_shift",
    }
    if shell_id == "entertainment_scandal":
        signal_bias_by_role.update({"pressure": "public_wave", "reveal": "public_wave", "terminal": "public_wave"})
    elif shell_id == "campus_romance":
        signal_bias_by_role.update({"pressure": "peer_spread", "reveal": "peer_spread", "terminal": "peer_spread"})
    elif shell_id == "wealth_families":
        signal_bias_by_role.update({"pressure": "relationship_pressure", "reveal": "relationship_pressure"})
    return PropagationPriorityPolicy(
        shell_id=shell_id,  # type: ignore[arg-type]
        edge_priority_by_segment_role=edge_priority_by_segment_role,  # type: ignore[arg-type]
        signal_family_bias_by_segment_role=signal_bias_by_role,  # type: ignore[arg-type]
        key_segment_require_edge_commit=True,
    )


def _build_shell_signal_graph_v2(graph: ShellPropagationGraphPolicy) -> ShellSignalGraphV2:
    return ShellSignalGraphV2(
        shell_id=graph.shell_id,
        edges=list(graph.edges[:16]),
        key_segment_preferred_edges=list(graph.key_segment_preferred_edges[:8]),
    )


def _build_propagation_priority_by_segment(policy: PropagationPriorityPolicy) -> PropagationPriorityBySegment:
    return PropagationPriorityBySegment(
        shell_id=policy.shell_id,
        edge_priority_by_segment_role={
            segment_role: list(edge_ids[:8])
            for segment_role, edge_ids in policy.edge_priority_by_segment_role.items()
        },
        signal_family_bias_by_segment_role=dict(policy.signal_family_bias_by_segment_role),
        key_segment_require_edge_commit=policy.key_segment_require_edge_commit,
    )


def _build_style_register(
    *,
    shell_id: str,
    segment_contracts: list[SegmentContract],
    propagation_priority_policy: PropagationPriorityPolicy,
) -> StyleRegister:
    anchor_defaults: dict[str, list[str]] = {
        "campus_romance": ["台下", "评审", "名额", "社团", "熟人", "站队"],
        "entertainment_scandal": ["镜头", "公屏", "热搜", "公关", "切割"],
        "office_power": ["会议室", "考核", "职级", "背锅"],
        "wealth_families": ["主桌", "家宴", "顺位", "董事会"],
    }
    default_anchors = anchor_defaults.get(shell_id, ["场上", "风向"])
    by_segment_role: dict[str, StyleRegisterSegmentRule] = {}
    seen_roles = unique_preserve([segment.segment_role for segment in segment_contracts])
    for segment_role in seen_roles:
        reason_priority = _segment_reason_priority(segment_role, shell_id)
        signal = propagation_priority_policy.signal_family_bias_by_segment_role.get(segment_role, "mixed")
        signal_families: list[ToneSignalFamily] = [signal]
        if signal != "mixed":
            signal_families.append("mixed")
        cost_families: list[ToneCostFamily]
        if segment_role in {"reveal", "terminal"}:
            cost_families = ["position", "face", "relationship", "narrative_control"]
            cadence_order = ["contrast", "broken", "staccato", "mixed"]
        else:
            cost_families = ["relationship", "position", "mixed"]
            cadence_order = ["slow_press", "contrast", "staccato", "mixed"]
        by_segment_role[segment_role] = StyleRegisterSegmentRule(
            segment_role=segment_role,  # type: ignore[arg-type]
            reason_families=reason_priority[:4],
            signal_families=unique_preserve(signal_families)[:4],
            cost_families=cost_families[:4],  # type: ignore[arg-type]
            cadence_order=cadence_order[:4],  # type: ignore[arg-type]
            shell_anchor_tokens=list(default_anchors[:6]),
            require_reason_signal_main_clause_on_key_segment=True,
        )
    default_rule = StyleRegisterSegmentRule(
        segment_role="pressure",
        reason_families=_segment_reason_priority("pressure", shell_id),
        signal_families=unique_preserve(
            [
                propagation_priority_policy.signal_family_bias_by_segment_role.get("pressure", "mixed"),
                "mixed",
            ]
        )[:4],
        cost_families=["relationship", "position", "mixed"],
        cadence_order=["slow_press", "contrast", "staccato", "mixed"],
        shell_anchor_tokens=list(default_anchors[:6]),
        require_reason_signal_main_clause_on_key_segment=True,
    )
    return StyleRegister(
        by_segment_role=by_segment_role,  # type: ignore[arg-type]
        default_rule=default_rule,
    )


def _build_invariant_policy() -> InvariantPolicy:
    return InvariantPolicy(
        require_question_progress=True,
        require_observable_cost=True,
        max_main_triggers_per_turn=1,
        require_key_segment_shell_anchor=True,
        require_cost_return_within_window=True,
        require_cost_owner_visible=True,
        require_cost_linked_to_question=True,
        key_segment_roles=["reveal", "terminal"],
        fallback_global_delta_key="scene_heat",
        fallback_global_delta_value=1,
        trace_tag_prefix="invariant",
    )


def _build_causal_contract_policy(shell_id: str) -> CausalContractPolicy:
    if shell_id == "entertainment_scandal":
        wave_hint = "镜头线必须在关键段产生一次可见翻面。"
    elif shell_id == "campus_romance":
        wave_hint = "熟人传播链必须在关键段造成一次站队翻面。"
    elif shell_id == "office_power":
        wave_hint = "汇报线必须在关键段落成一次责任转移。"
    elif shell_id == "wealth_families":
        wave_hint = "家宴口风必须在关键段落成一次顺位改写。"
    else:
        wave_hint = "传播线必须在关键段完成一次立场翻面。"
    stale_delta_key = "scene_heat"
    stale_threshold = 2
    if shell_id == "entertainment_scandal":
        stale_delta_key = "public_wave_pressure"
        stale_threshold = 1
    elif shell_id == "campus_romance":
        stale_delta_key = "relationship_debt_pressure"
        stale_threshold = 1
    elif shell_id == "office_power":
        stale_delta_key = "npc_action_pressure"
    return CausalContractPolicy(
        rules=[
            CausalContractRule(
                rule_id="causal_callback_open",
                source_kind="callback",
                required_kind="relationship_debt",
                open_by_role="misread",
                resolve_by_role="reveal",
                min_resolution_count=1,
                fail_safe_delta_key="route_lock",
                fail_safe_delta_value=1,
                summary_hint="至少一笔延迟旧账应在 reveal 前成熟并产生后果。",
            ),
            CausalContractRule(
                rule_id="causal_wave_conversion",
                source_kind="latent",
                required_kind="public_wave",
                open_by_role="pressure",
                resolve_by_role="terminal",
                min_resolution_count=1,
                fail_safe_delta_key="public_image",
                fail_safe_delta_value=-1,
                summary_hint=wave_hint,
            ),
            CausalContractRule(
                rule_id="causal_payoff_commit",
                source_kind="payoff",
                required_kind="any",
                open_by_role="opening",
                resolve_by_role="terminal",
                min_resolution_count=1,
                fail_safe_delta_key="scene_heat",
                fail_safe_delta_value=1,
                summary_hint="终局前必须有一次明确可观测代价兑现。",
            ),
        ],
        force_resolve_on_terminal=True,
        max_open_rules=6,
        stale_pending_turns_threshold=stale_threshold,
        stale_pending_global_delta_key=stale_delta_key,
        stale_pending_global_delta_value=1,
        stale_pending_max_escalations_per_rule=2,
    )


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, int(value)))


def _clamp_float(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _load_semantic_autotune_patch() -> dict[str, Any] | None:
    settings = get_settings()
    patch_path_raw = (settings.semantic_autotune_patch_path or "").strip()
    if not patch_path_raw:
        return None
    patch_path = Path(patch_path_raw).expanduser()
    if not patch_path.exists() or not patch_path.is_file():
        return None
    try:
        payload = json.loads(patch_path.read_text())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_quality_tuning_patch() -> dict[str, Any] | None:
    settings = get_settings()
    patch_path_raw = (settings.quality_tuning_patch_path or "").strip()
    if not patch_path_raw:
        return None
    patch_path = Path(patch_path_raw).expanduser()
    if not patch_path.exists() or not patch_path.is_file():
        return None
    try:
        payload = json.loads(patch_path.read_text())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _build_quality_tuning_profile() -> QualityTuningProfile:
    return QualityTuningProfile(
        schema_version=1,
        round_label="base",
        note="deterministic_default",
        play=PlayQualityTuningProfile(),
        author=AuthorQualityTuningProfile(
            move_priority_promote_by_segment={
                "opening": ["accuse", "ally_with"],
                "misread": ["accuse", "probe_secret"],
                "pressure": ["accuse", "public_reveal"],
                "reversal": ["public_reveal", "betray"],
            },
            progression_intensity_by_segment={
                "opening": 1.0,
                "misread": 1.05,
                "pressure": 1.1,
                "reversal": 1.15,
                "reveal": 1.2,
                "terminal": 1.25,
            },
            render_cue_boost_by_segment={
                "opening": ["style:control:force_first_concession"],
                "misread": ["style:control:force_first_concession"],
                "pressure": ["style:control:force_side_switch"],
                "reversal": ["style:control:force_side_switch"],
                "reveal": ["style:control:force_public_settlement"],
                "terminal": ["style:control:force_public_settlement"],
            },
        ),
    )


def _apply_quality_tuning_patch(
    *,
    profile: QualityTuningProfile,
    patch_payload: dict[str, Any] | None,
) -> QualityTuningProfile:
    if not patch_payload:
        return profile
    raw_patch = dict(patch_payload.get("quality_tuning_profile") or {})
    if not raw_patch:
        return profile
    merged = _deep_merge_dict(profile.model_dump(mode="json"), raw_patch)
    try:
        return QualityTuningProfile.model_validate(merged)
    except ValidationError:
        return profile


def _sync_semantic_strategy_pack_v2_fields(updated: TurnSemanticStrategyPack) -> TurnSemanticStrategyPack:
    question_arc_items: dict[str, QuestionArcSegmentPolicyV2] = {}
    for segment_id, segment_rule in updated.question_arc_policy_v2.by_segment_id.items():
        minimum_status = updated.question_progress_policy.min_status_by_segment_role.get(
            segment_rule.segment_role,
            segment_rule.minimum_status,
        )
        question_arc_items[segment_id] = segment_rule.model_copy(
            update={
                "minimum_status": minimum_status,
                "key_segment_require_conversion_if_no_trigger": segment_rule.segment_role in {"reveal", "terminal"},
                "force_resolve_secret_exposure": updated.question_progress_policy.key_segment_force_resolve_secret_exposure,
                "force_resolve_progress_threshold": updated.question_progress_policy.key_segment_force_resolve_progress_threshold,
            }
        )
    question_arc = updated.question_arc_policy_v2.model_copy(update={"by_segment_id": question_arc_items})

    role_matrix_items: dict[str, RoleDivergenceSegmentRule] = {}
    for segment_id, segment_rule in updated.role_divergence_matrix.by_segment_id.items():
        interest = updated.segment_interest_policy.by_segment_id.get(segment_id)
        counter_priority = list(updated.supporting_divergence_policy.counter_reason_priority_by_segment_role.get(segment_rule.segment_role, []))
        crowd_priority = list(updated.supporting_divergence_policy.crowd_reason_priority_by_segment_role.get(segment_rule.segment_role, []))
        if interest is not None:
            counter_priority = unique_preserve([*interest.reason_priority, *counter_priority])[:4]
            crowd_priority = unique_preserve([*crowd_priority, *interest.reason_priority])[:4]
        role_matrix_items[segment_id] = segment_rule.model_copy(
            update={
                "require_counter_crowd_reason_split": updated.supporting_divergence_policy.require_reason_family_split,
                "counter_reason_priority": counter_priority or list(updated.role_divergence_matrix.default_counter_reason_priority[:4]),
                "crowd_reason_priority": crowd_priority or list(updated.role_divergence_matrix.default_crowd_reason_priority[:4]),
            }
        )
    role_divergence_matrix = updated.role_divergence_matrix.model_copy(update={"by_segment_id": role_matrix_items})

    stake_axis_priority = updated.stake_axis_priority.model_copy(
        update={
            "by_segment_id": {
                segment_id: list(item.stake_priority[:4])
                for segment_id, item in updated.segment_interest_policy.by_segment_id.items()
            },
            "default_priority": list(updated.segment_interest_policy.default_stake_priority[:4]),
        }
    )
    reason_family_priority = updated.reason_family_priority.model_copy(
        update={
            "by_segment_id": {
                segment_id: list(item.reason_priority[:4])
                for segment_id, item in updated.segment_interest_policy.by_segment_id.items()
            },
            "default_priority": list(updated.segment_interest_policy.default_reason_priority[:4]),
        }
    )

    cost_ownership_matrix_v2 = updated.cost_ownership_matrix_v2.model_copy(
        update={
            "rules": list(updated.cost_ownership_policy.rules[:80]),
            "fallback_owner_mode": updated.cost_ownership_policy.fallback_owner_mode,
        }
    )
    callback_commit_policy_v2 = updated.callback_commit_policy_v2.model_copy(
        update={
            "max_queue_size": updated.callback_policy.max_queue_size,
            "per_turn_settle_cap": updated.callback_policy.per_turn_settle_cap,
            "rules": list(updated.callback_policy.rules[:80]),
        }
    )
    cost_return_by_segment: dict[str, CostReturnSegmentRule] = {}
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.cost_return_policy.by_segment_id.get(segment_id)
        if existing is None:
            existing = CostReturnSegmentRule(
                segment_id=segment_id,
                segment_role=interest.segment_role,
                max_return_turns=updated.cost_return_policy.default_max_return_turns,
                owner_priority_modes=list(updated.cost_return_policy.default_owner_priority_modes[:4]),
                scene_question_focus=updated.cost_return_policy.default_scene_question_focus,
            )
        owner_priority = list(existing.owner_priority_modes) or list(updated.cost_return_policy.default_owner_priority_modes[:4])
        cost_return_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "max_return_turns": max(1, min(3, int(existing.max_return_turns))),
                "owner_priority_modes": owner_priority[:4],
            }
        )
    cost_return_policy = updated.cost_return_policy.model_copy(
        update={
            "by_segment_id": cost_return_by_segment,
            "default_max_return_turns": max(1, min(3, int(updated.cost_return_policy.default_max_return_turns))),
            "default_owner_priority_modes": list(updated.cost_return_policy.default_owner_priority_modes[:4]),
        }
    )
    cost_narrative_by_segment: dict[str, CostNarrativeBindingSegmentRule] = {}
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.cost_narrative_binding_policy.by_segment_id.get(segment_id)
        if existing is None:
            segment_role = interest.segment_role
            existing = CostNarrativeBindingSegmentRule(
                segment_id=segment_id,
                segment_role=segment_role,
                due_cost_driver="primary" if segment_role in {"reveal", "terminal"} else "secondary",
                due_primary_when_due=segment_role in {"pressure", "reversal", "reveal", "terminal"},
                require_main_clause_payer_beneficiary=True,
                reason_family_priority=_segment_cost_narrative_reason_priority(segment_role),
            )
        reason_priority = list(existing.reason_family_priority) or _segment_cost_narrative_reason_priority(existing.segment_role)
        cost_narrative_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "reason_family_priority": list(unique_preserve(reason_priority))[:4],
            }
        )
    cost_narrative_binding_policy = updated.cost_narrative_binding_policy.model_copy(
        update={
            "by_segment_id": cost_narrative_by_segment,
            "due_cost_forces_primary_driver": bool(updated.cost_narrative_binding_policy.due_cost_forces_primary_driver),
        }
    )
    cost_primary_driver_by_segment: dict[str, CostPrimaryDriverSegmentRuleV7] = {}
    default_eligible_roles: list[SegmentRoleId] = ["pressure", "reversal", "reveal", "terminal"]
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.cost_primary_driver_policy_v7.by_segment_id.get(segment_id)
        if existing is None:
            existing = CostPrimaryDriverSegmentRuleV7(
                segment_id=segment_id,
                segment_role=interest.segment_role,
                eligible_segment_roles=default_eligible_roles,
                due_window_turns=3,
                player_override_mode="player_first",
                deferred_retry_bias=1 if interest.segment_role in {"opening", "misread"} else 2,
            )
        eligible_roles = list(unique_preserve(existing.eligible_segment_roles or default_eligible_roles))[:4]
        cost_primary_driver_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "eligible_segment_roles": eligible_roles,
                "due_window_turns": max(1, min(3, int(existing.due_window_turns))),
                "deferred_retry_bias": max(0, min(3, int(existing.deferred_retry_bias))),
            }
        )
    cost_primary_driver_policy_v7 = updated.cost_primary_driver_policy_v7.model_copy(
        update={
            "by_segment_id": cost_primary_driver_by_segment,
            "due_cost_forces_primary_driver": bool(updated.cost_primary_driver_policy_v7.due_cost_forces_primary_driver),
        }
    )
    cost_ladder_by_segment: dict[str, CostEscalationLadderSegmentRuleV8] = {}
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.cost_escalation_ladder_policy_v8.by_segment_id.get(segment_id)
        if existing is None:
            existing = CostEscalationLadderSegmentRuleV8(
                segment_id=segment_id,
                segment_role=interest.segment_role,
                stage1_turn_offset=1,
                stage2_turn_offset=2,
                stage3_turn_offset=3,
                stage1_pressure_bonus=1,
                stage1_maturity_bonus=1,
                stage2_pressure_bonus=2,
                stage2_maturity_bonus=2,
                stage3_force_question_cost_focus=True,
                stage3_force_primary_driver=True,
                allow_player_defer_once=True,
            )
        stage1 = max(1, min(3, int(existing.stage1_turn_offset)))
        stage2 = max(stage1, min(3, int(existing.stage2_turn_offset)))
        stage3 = max(stage2, min(3, int(existing.stage3_turn_offset)))
        cost_ladder_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "stage1_turn_offset": stage1,
                "stage2_turn_offset": stage2,
                "stage3_turn_offset": stage3,
                "stage1_pressure_bonus": max(0, min(3, int(existing.stage1_pressure_bonus))),
                "stage1_maturity_bonus": max(0, min(3, int(existing.stage1_maturity_bonus))),
                "stage2_pressure_bonus": max(0, min(4, int(existing.stage2_pressure_bonus))),
                "stage2_maturity_bonus": max(0, min(4, int(existing.stage2_maturity_bonus))),
                "stage3_force_question_cost_focus": bool(existing.stage3_force_question_cost_focus),
                "stage3_force_primary_driver": bool(existing.stage3_force_primary_driver),
                "allow_player_defer_once": bool(existing.allow_player_defer_once),
            }
        )
    cost_escalation_ladder_policy_v8 = updated.cost_escalation_ladder_policy_v8.model_copy(
        update={
            "by_segment_id": cost_ladder_by_segment,
            "enabled": bool(updated.cost_escalation_ladder_policy_v8.enabled),
        }
    )
    default_signature = _build_control_signature_policy_v8()
    control_signature_by_action: dict[str, ControlSignatureRuleV8] = {}
    for action in ("press", "redirect", "detonate"):
        existing = updated.control_signature_policy_v8.by_action.get(action) or default_signature.by_action.get(action)
        if existing is None:
            continue
        control_signature_by_action[action] = existing.model_copy(update={"action": action})
    control_signature_policy_v8 = updated.control_signature_policy_v8.model_copy(
        update={
            "by_action": control_signature_by_action,
            "require_distinct_signatures": bool(updated.control_signature_policy_v8.require_distinct_signatures),
        }
    )
    role_lexicon_by_segment: dict[str, RoleFunctionLexiconSegmentRuleV8] = {}
    shell_id = str(updated.shell_propagation_graph.shell_id)
    counter_rows, crowd_rows = _role_function_lexicon_rows(shell_id)
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.role_function_lexicon_policy_v8.by_segment_id.get(segment_id)
        if existing is None:
            counter_entries = [
                RoleFunctionLexiconEntry(
                    function_role=function_role,  # type: ignore[arg-type]
                    verbs=list(payload[0][:4]),
                    receiver_templates=list(payload[1][:4]),
                )
                for function_role, payload in counter_rows.items()
            ]
            crowd_entries = [
                RoleFunctionLexiconEntry(
                    function_role=function_role,  # type: ignore[arg-type]
                    verbs=list(payload[0][:4]),
                    receiver_templates=list(payload[1][:4]),
                )
                for function_role, payload in crowd_rows.items()
            ]
            existing = RoleFunctionLexiconSegmentRuleV8(
                segment_id=segment_id,
                segment_role=interest.segment_role,
                counter_entries=counter_entries,
                crowd_entries=crowd_entries,
                enforce_counter_crowd_slot_split=True,
            )
        role_lexicon_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "counter_entries": list(existing.counter_entries[:8]),
                "crowd_entries": list(existing.crowd_entries[:8]),
                "enforce_counter_crowd_slot_split": bool(existing.enforce_counter_crowd_slot_split),
            }
        )
    role_function_lexicon_policy_v8 = updated.role_function_lexicon_policy_v8.model_copy(
        update={"by_segment_id": role_lexicon_by_segment}
    )
    cost_visibility_by_segment: dict[str, CostVisibilitySegmentRule] = {}
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.cost_visibility_contract.by_segment_id.get(segment_id)
        if existing is None:
            existing = CostVisibilitySegmentRule(
                segment_id=segment_id,
                segment_role=interest.segment_role,
                max_return_turns=3,
                require_visible_owner=True,
                require_main_clause_subject=True,
                require_two_sided_exchange=True,
                min_payer_loss=2 if interest.segment_role in {"reveal", "terminal"} else 1,
                min_beneficiary_gain=2 if interest.segment_role in {"reveal", "terminal"} else 1,
                main_clause_subject_order=["payer", "beneficiary", "blamed_party"],
            )
        cost_visibility_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "max_return_turns": max(1, min(3, int(existing.max_return_turns))),
                "require_two_sided_exchange": bool(existing.require_two_sided_exchange),
                "min_payer_loss": max(1, min(3, int(existing.min_payer_loss))),
                "min_beneficiary_gain": max(1, min(3, int(existing.min_beneficiary_gain))),
                "main_clause_subject_order": list(unique_preserve(existing.main_clause_subject_order or ["payer", "beneficiary", "blamed_party"]))[:3],
            }
        )
    cost_visibility_contract = updated.cost_visibility_contract.model_copy(
        update={"by_segment_id": cost_visibility_by_segment}
    )
    question_progress_v2_by_segment: dict[str, QuestionProgressSegmentRuleV2] = {}
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.question_progress_policy_v2.by_segment_id.get(segment_id)
        if existing is None:
            existing = QuestionProgressSegmentRuleV2(
                segment_id=segment_id,
                segment_role=interest.segment_role,
                minimum_status=updated.question_progress_policy.min_status_by_segment_role.get(interest.segment_role, "open"),  # type: ignore[arg-type]
                require_cost_focus_when_due=True,
                require_non_stall_advance=True,
                key_segment_force_flip_if_no_trigger=interest.segment_role in {"reveal", "terminal"},
            )
        question_progress_v2_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "minimum_status": updated.question_progress_policy.min_status_by_segment_role.get(
                    interest.segment_role, existing.minimum_status
                ),
                "key_segment_force_flip_if_no_trigger": bool(
                    existing.key_segment_force_flip_if_no_trigger or interest.segment_role in {"reveal", "terminal"}
                ),
            }
        )
    question_progress_policy_v2 = updated.question_progress_policy_v2.model_copy(
        update={"by_segment_id": question_progress_v2_by_segment}
    )
    role_divergence_v2_by_segment: dict[str, RoleDivergenceSegmentRuleV2] = {}
    for segment_id, interest in updated.segment_interest_policy.by_segment_id.items():
        existing = updated.role_divergence_matrix_v2.by_segment_id.get(segment_id)
        fallback_functions = ["strike", "self_preserve"]
        if interest.segment_role in {"reveal", "terminal"}:
            fallback_functions = ["strike", "self_preserve", "debt_play"]
        if existing is None:
            existing = RoleDivergenceSegmentRuleV2(
                segment_id=segment_id,
                segment_role=interest.segment_role,
                min_distinct_functions=2,
                required_functions=fallback_functions,  # type: ignore[arg-type]
                require_counter_crowd_reason_split=True,
            )
        role_divergence_v2_by_segment[segment_id] = existing.model_copy(
            update={
                "segment_role": interest.segment_role,
                "min_distinct_functions": max(2, int(existing.min_distinct_functions)),
                "required_functions": list(unique_preserve(existing.required_functions or fallback_functions))[:4],
            }
        )
    role_divergence_matrix_v2 = updated.role_divergence_matrix_v2.model_copy(
        update={"by_segment_id": role_divergence_v2_by_segment}
    )

    shell_signal_graph_v2 = updated.shell_signal_graph_v2.model_copy(
        update={
            "shell_id": updated.shell_propagation_graph.shell_id,
            "edges": list(updated.shell_propagation_graph.edges[:16]),
            "key_segment_preferred_edges": list(updated.shell_propagation_graph.key_segment_preferred_edges[:8]),
        }
    )
    propagation_priority_by_segment = updated.propagation_priority_by_segment.model_copy(
        update={
            "shell_id": updated.propagation_priority_policy.shell_id,
            "edge_priority_by_segment_role": {
                segment_role: list(edge_ids[:8])
                for segment_role, edge_ids in updated.propagation_priority_policy.edge_priority_by_segment_role.items()
            },
            "signal_family_bias_by_segment_role": dict(updated.propagation_priority_policy.signal_family_bias_by_segment_role),
            "key_segment_require_edge_commit": updated.propagation_priority_policy.key_segment_require_edge_commit,
        }
    )

    return updated.model_copy(
        update={
            "question_arc_policy_v2": question_arc,
            "role_divergence_matrix": role_divergence_matrix,
            "stake_axis_priority": stake_axis_priority,
            "reason_family_priority": reason_family_priority,
            "cost_ownership_matrix_v2": cost_ownership_matrix_v2,
            "callback_commit_policy_v2": callback_commit_policy_v2,
            "cost_return_policy": cost_return_policy,
            "cost_narrative_binding_policy": cost_narrative_binding_policy,
            "cost_primary_driver_policy_v7": cost_primary_driver_policy_v7,
            "cost_escalation_ladder_policy_v8": cost_escalation_ladder_policy_v8,
            "cost_visibility_contract": cost_visibility_contract,
            "control_signature_policy_v8": control_signature_policy_v8,
            "role_function_lexicon_policy_v8": role_function_lexicon_policy_v8,
            "question_progress_policy_v2": question_progress_policy_v2,
            "role_divergence_matrix_v2": role_divergence_matrix_v2,
            "shell_signal_graph_v2": shell_signal_graph_v2,
            "propagation_priority_by_segment": propagation_priority_by_segment,
        }
    )


def _apply_semantic_autotune_patch(
    *,
    strategy_pack: TurnSemanticStrategyPack,
    shell_id: str,
    patch_payload: dict[str, Any] | None,
) -> TurnSemanticStrategyPack:
    if not patch_payload:
        return strategy_pack
    target_shell_ids = [
        str(item)
        for item in list(patch_payload.get("target_shell_ids") or [])
        if isinstance(item, str) and item.strip()
    ]
    if target_shell_ids and shell_id not in set(target_shell_ids):
        return strategy_pack
    overrides = patch_payload.get("recommended_overrides")
    if not isinstance(overrides, dict):
        return strategy_pack
    updated = strategy_pack.model_copy(deep=True)

    utility_delta = overrides.get("utility_weight_profile")
    if isinstance(utility_delta, dict):
        utility = updated.utility_weight_profile.model_copy(deep=True)
        for field_name in (
            "intent_hit_weight",
            "stake_hit_weight",
            "latent_pressure_weight",
            "role_diversity_weight",
            "utility_delta_weight",
            "shell_bias_weight",
            "shell_bias_cap",
        ):
            delta_key = f"{field_name}_delta"
            if delta_key not in utility_delta:
                continue
            current = int(getattr(utility, field_name))
            delta_value = int(utility_delta.get(delta_key) or 0)
            if field_name in {"shell_bias_weight", "shell_bias_cap"}:
                bounded = _clamp_int(current + delta_value, 0, 6)
            else:
                bounded = _clamp_int(current + delta_value, 1, 6)
            setattr(utility, field_name, bounded)
        updated = updated.model_copy(update={"utility_weight_profile": utility})

    intensity_delta = overrides.get("cost_intensity_profile")
    if isinstance(intensity_delta, dict):
        intensity = updated.cost_intensity_profile.model_copy(deep=True)
        for bucket_key, clamp_lower, clamp_upper in (
            ("segment_role_multiplier_delta", 0.6, 2.4),
            ("control_action_multiplier_delta", 0.6, 2.4),
            ("shell_multiplier_delta", 0.6, 2.4),
            ("payoff_family_multiplier_delta", 0.7, 2.6),
        ):
            delta_map = intensity_delta.get(bucket_key)
            if not isinstance(delta_map, dict):
                continue
            field_name = bucket_key.replace("_delta", "")
            base_map = dict(getattr(intensity, field_name))
            for key, delta_raw in delta_map.items():
                try:
                    delta_value = float(delta_raw)
                except Exception:  # noqa: BLE001
                    continue
                current = float(base_map.get(key, 1.0) or 1.0)
                base_map[str(key)] = _clamp_float(current + delta_value, clamp_lower, clamp_upper)
            setattr(intensity, field_name, base_map)
        latent_step_delta = intensity_delta.get("latent_pressure_step_bonus_delta")
        if latent_step_delta is not None:
            try:
                step_delta = float(latent_step_delta)
                intensity.latent_pressure_step_bonus = _clamp_float(
                    intensity.latent_pressure_step_bonus + step_delta,
                    0.0,
                    0.3,
                )
            except Exception:  # noqa: BLE001
                pass
        latent_cap_delta = intensity_delta.get("latent_pressure_bonus_cap_delta")
        if latent_cap_delta is not None:
            try:
                cap_delta = float(latent_cap_delta)
                intensity.latent_pressure_bonus_cap = _clamp_float(
                    intensity.latent_pressure_bonus_cap + cap_delta,
                    0.0,
                    0.6,
                )
            except Exception:  # noqa: BLE001
                pass
        deferred_bonus_delta = intensity_delta.get("deferred_route_bonus_delta")
        if deferred_bonus_delta is not None:
            try:
                route_delta = float(deferred_bonus_delta)
                intensity.deferred_route_bonus = _clamp_float(
                    intensity.deferred_route_bonus + route_delta,
                    0.0,
                    0.5,
                )
            except Exception:  # noqa: BLE001
                pass
        updated = updated.model_copy(update={"cost_intensity_profile": intensity})

    callback_delta = overrides.get("callback_policy")
    if isinstance(callback_delta, dict):
        min_delta = int(callback_delta.get("due_turn_min_offset_delta", 0) or 0)
        max_delta = int(callback_delta.get("due_turn_max_offset_delta", 0) or 0)
        if min_delta != 0 or max_delta != 0:
            callback = updated.callback_policy.model_copy(deep=True)
            adjusted_rules: list[CallbackPolicyRule] = []
            for rule in callback.rules:
                due_min = _clamp_int(rule.due_turn_min_offset + min_delta, 0, 6)
                due_max = _clamp_int(rule.due_turn_max_offset + max_delta, 0, 10)
                if due_max < due_min:
                    due_max = due_min
                adjusted_rules.append(
                    rule.model_copy(
                        update={
                            "due_turn_min_offset": due_min,
                            "due_turn_max_offset": due_max,
                        }
                    )
                )
            callback = callback.model_copy(update={"rules": adjusted_rules})
            updated = updated.model_copy(update={"callback_policy": callback})

    question_delta = overrides.get("question_progress_policy")
    if isinstance(question_delta, dict):
        question = updated.question_progress_policy.model_copy(deep=True)
        secret_delta = int(question_delta.get("key_segment_force_resolve_secret_exposure_delta", 0) or 0)
        progress_delta = int(question_delta.get("key_segment_force_resolve_progress_threshold_delta", 0) or 0)
        if secret_delta != 0:
            question.key_segment_force_resolve_secret_exposure = _clamp_int(
                question.key_segment_force_resolve_secret_exposure + secret_delta,
                0,
                6,
            )
        if progress_delta != 0:
            question.key_segment_force_resolve_progress_threshold = _clamp_int(
                question.key_segment_force_resolve_progress_threshold + progress_delta,
                0,
                4,
            )
        updated = updated.model_copy(update={"question_progress_policy": question})

    causal_delta = overrides.get("causal_contract_policy")
    if isinstance(causal_delta, dict):
        causal = updated.causal_contract_policy.model_copy(deep=True)
        threshold_delta = int(causal_delta.get("stale_pending_turns_threshold_delta", 0) or 0)
        stale_value_delta = int(causal_delta.get("stale_pending_global_delta_value_delta", 0) or 0)
        escalation_cap_delta = int(causal_delta.get("stale_pending_max_escalations_per_rule_delta", 0) or 0)
        if threshold_delta != 0:
            causal.stale_pending_turns_threshold = _clamp_int(
                causal.stale_pending_turns_threshold + threshold_delta,
                1,
                8,
            )
        if stale_value_delta != 0:
            causal.stale_pending_global_delta_value = _clamp_int(
                causal.stale_pending_global_delta_value + stale_value_delta,
                -6,
                6,
            )
        if escalation_cap_delta != 0:
            causal.stale_pending_max_escalations_per_rule = _clamp_int(
                causal.stale_pending_max_escalations_per_rule + escalation_cap_delta,
                1,
                6,
            )
        updated = updated.model_copy(update={"causal_contract_policy": causal})

    return _sync_semantic_strategy_pack_v2_fields(updated)


def _build_semantic_strategy_pack(
    *,
    blueprint: AcceptedBlueprint,
    segment_contracts: list[SegmentContract],
    cast: list[BoundIPCastMember],
) -> TurnSemanticStrategyPack:
    question_progress_policy = _question_progress_policy()
    question_progress_policy_v2 = _build_question_progress_policy_v2(
        segment_contracts=segment_contracts,
        question_progress_policy=question_progress_policy,
    )
    segment_interest_policy = _build_segment_interest_policy(
        shell_id=blueprint.story_shell_id,
        segment_contracts=segment_contracts,
        cast=cast,
    )
    supporting_divergence_policy = _build_supporting_divergence_policy(blueprint.story_shell_id)
    role_divergence_matrix = _build_role_divergence_matrix(
        segment_contracts=segment_contracts,
        segment_interest_policy=segment_interest_policy,
        divergence_policy=supporting_divergence_policy,
    )
    role_divergence_matrix_v2 = _build_role_divergence_matrix_v2(
        segment_contracts=segment_contracts,
        role_divergence_matrix=role_divergence_matrix,
    )
    cost_routing_matrix = _build_cost_routing_matrix()
    cost_ownership_policy = _build_cost_ownership_policy()
    callback_policy = _build_callback_policy()
    cost_return_policy = _build_cost_return_policy(
        shell_id=blueprint.story_shell_id,
        segment_contracts=segment_contracts,
    )
    cost_narrative_binding_policy = _build_cost_narrative_binding_policy(
        segment_contracts=segment_contracts,
    )
    cost_primary_driver_policy_v7 = _build_cost_primary_driver_policy_v7(
        segment_contracts=segment_contracts,
    )
    cost_escalation_ladder_policy_v8 = _build_cost_escalation_ladder_policy_v8(
        segment_contracts=segment_contracts,
    )
    cost_visibility_contract = _build_cost_visibility_contract(
        segment_contracts=segment_contracts,
    )
    control_signature_policy_v8 = _build_control_signature_policy_v8()
    role_function_lexicon_policy_v8 = _build_role_function_lexicon_policy_v8(
        shell_id=blueprint.story_shell_id,
        segment_contracts=segment_contracts,
    )
    utility_weight_profile = _build_utility_weight_profile()
    cost_intensity_profile = _build_cost_intensity_profile(blueprint.story_shell_id)
    shell_graph = _build_shell_propagation_graph(blueprint.story_shell_id)
    propagation_priority_policy = _build_propagation_priority_policy(
        shell_id=blueprint.story_shell_id,
        graph=shell_graph,
    )
    return TurnSemanticStrategyPack(
        question_progress_policy=question_progress_policy,
        question_progress_policy_v2=question_progress_policy_v2,
        question_arc_policy_v2=_build_question_arc_policy_v2(
            segment_contracts=segment_contracts,
            question_progress_policy=question_progress_policy,
        ),
        segment_interest_policy=segment_interest_policy,
        role_divergence_matrix=role_divergence_matrix,
        role_divergence_matrix_v2=role_divergence_matrix_v2,
        stake_axis_priority=_build_stake_axis_priority_policy(segment_interest_policy),
        reason_family_priority=_build_reason_family_priority_policy(segment_interest_policy),
        supporting_divergence_policy=supporting_divergence_policy,
        cost_routing_matrix=cost_routing_matrix,
        cost_ownership_policy=cost_ownership_policy,
        cost_ownership_matrix_v2=_build_cost_ownership_matrix_v2(cost_ownership_policy),
        callback_policy=callback_policy,
        callback_commit_policy_v2=_build_callback_commit_policy_v2(callback_policy),
        cost_return_policy=cost_return_policy,
        cost_narrative_binding_policy=cost_narrative_binding_policy,
        cost_primary_driver_policy_v7=cost_primary_driver_policy_v7,
        cost_escalation_ladder_policy_v8=cost_escalation_ladder_policy_v8,
        cost_visibility_contract=cost_visibility_contract,
        control_signature_policy_v8=control_signature_policy_v8,
        role_function_lexicon_policy_v8=role_function_lexicon_policy_v8,
        utility_weight_profile=utility_weight_profile,
        cost_intensity_profile=cost_intensity_profile,
        shell_propagation_graph=shell_graph,
        shell_signal_graph_v2=_build_shell_signal_graph_v2(shell_graph),
        propagation_priority_policy=propagation_priority_policy,
        propagation_priority_by_segment=_build_propagation_priority_by_segment(propagation_priority_policy),
        style_register=_build_style_register(
            shell_id=blueprint.story_shell_id,
            segment_contracts=segment_contracts,
            propagation_priority_policy=propagation_priority_policy,
        ),
        invariant_policy=_build_invariant_policy(),
        causal_contract_policy=_build_causal_contract_policy(blueprint.story_shell_id),
    )


def _build_delta_kernel(bundle: UrbanAuthorBundle) -> BeatDeltaKernel:
    anchor_tokens = _shell_anchor_tokens(bundle.accepted_blueprint.story_shell_id, "opening")
    voice_axes = {
        member.character_id: trim_text(
            f"{member.speech_pattern}；底层驱动是{member.drama_profile.status_need}",
            220,
        )
        for member in bundle.bound_cast
    }
    return BeatDeltaKernel(
        kernel_id=f"delta_kernel_{uuid4().hex[:12]}",
        story_shell_id=bundle.accepted_blueprint.story_shell_id,
        template_id=bundle.template_id,
        route_promise_anchor=trim_text(bundle.accepted_blueprint.route_promise, 220),
        bomb_moment_anchor=trim_text(bundle.accepted_blueprint.bomb_moment, 220),
        cost_of_truth_anchor=trim_text(bundle.accepted_blueprint.cost_of_truth, 220),
        protagonist_need_anchor=trim_text(bundle.accepted_blueprint.protagonist_hidden_need, 180),
        route_target_ids=[member.character_id for member in bundle.bound_cast if member.is_route_target][:4],
        semantic_anchor_tokens=list(unique_preserve(anchor_tokens))[:8],
        character_voice_axes=voice_axes,
    )


def _build_initial_beat_delta_pack(
    *,
    bundle: UrbanAuthorBundle,
    first_segment: CompiledSegment,
) -> BeatDeltaPack:
    def _build_turn_card(card_kind: str) -> BeatDeltaTurnCard:
        lane_focus = [lane.lane_id for lane in first_segment.suggestion_lanes[:3]]
        move_focus = list(first_segment.move_priorities[:4])
        voice_focus = list(unique_preserve(first_segment.focus_target_ids + first_segment.rival_target_ids))[:3]
        if card_kind == "burst":
            prioritized_lanes = list(unique_preserve(["burst", *lane_focus]))[:3]
            prioritized_moves = list(
                unique_preserve(
                    [
                        *(move for move in first_segment.move_priorities if move in {"public_reveal", "betray", "accuse", "probe_secret"}),
                        *move_focus,
                    ]
                )
            )[:4]
            return BeatDeltaTurnCard(
                directive=trim_text(
                    "关键拍要把可见代价落地：优先推进会改变站位和解释权的动作，再放大后果外溢。",
                    220,
                ),
                lane_focus=prioritized_lanes,
                move_focus=prioritized_moves,
                voice_focus_character_ids=voice_focus,
            )
        return BeatDeltaTurnCard(
            directive=trim_text(
                "普通拍先落可执行动作，保持关系推进与场面压强同步，不抢跑终局爆点。",
                220,
            ),
            lane_focus=lane_focus,
            move_focus=move_focus,
            voice_focus_character_ids=voice_focus,
        )

    def _build_micro_sim_hint_bundle() -> BeatDeltaMicroSimHintBundle:
        preferred_actor_ids = [
            member.character_id
            for member in bundle.bound_cast
            if member.character_id not in first_segment.focus_target_ids[:1]
        ][:3]
        reason_family_hints: dict[str, str] = {}
        action_family_hints: dict[str, str] = {}
        for member in bundle.bound_cast:
            if member.character_id not in preferred_actor_ids:
                continue
            strategic = member.strategic_intent
            strategy_hint = " ".join(
                [
                    str(strategic.loss_trigger),
                    str(strategic.public_survival_mode),
                    str(strategic.debt_memory_bias),
                ]
            ).lower()
            if any(token in strategy_hint for token in ("debt", "history", "old")):
                reason_family_hints[member.character_id] = "old_debt"
                action_family_hints[member.character_id] = "debt_play"
            elif any(token in strategy_hint for token in ("shield", "contain", "silent", "low_profile")):
                reason_family_hints[member.character_id] = "self_preserve"
                action_family_hints[member.character_id] = "self_preserve"
            elif any(token in strategy_hint for token in ("vote", "record", "edge", "counter")):
                reason_family_hints[member.character_id] = "loss_position"
                action_family_hints[member.character_id] = "strike"
            else:
                reason_family_hints[member.character_id] = "mixed"
                action_family_hints[member.character_id] = "test_water"
        return BeatDeltaMicroSimHintBundle(
            preferred_actor_ids=preferred_actor_ids,
            reason_family_hints=reason_family_hints,
            action_family_hints=action_family_hints,
            summary=trim_text("优先观察这批 supporting 角色的先手反应，再决定是否放大到公开层。", 220),
        )

    def _build_compose_payload_hint_bundle() -> BeatDeltaComposePayloadHintBundle:
        bucket_ids: list[str] = []
        for item in list(first_segment.template_tone_example_lines) + list(first_segment.template_tone_scene_examples):
            bucket = str(getattr(item, "bucket_id", "") or "").strip()
            if bucket:
                bucket_ids.append(bucket)
        key_cues = list(
            unique_preserve(
                [
                    *first_segment.render_cues,
                    trim_text(first_segment.public_pressure_cue, 80),
                    trim_text(first_segment.private_pressure_cue, 80),
                ]
            )
        )[:6]
        return BeatDeltaComposePayloadHintBundle(
            style_case_bucket_ids=list(unique_preserve(bucket_ids))[:4],
            key_cues=key_cues,
            cue_summary=trim_text(first_segment.progression_rule_summary, 220),
        )

    move_boosts: dict[RelationshipMoveFamily, float] = {}
    for index, move_family in enumerate(first_segment.move_priorities):
        base = max(0.0, 0.24 - 0.06 * float(index))
        if first_segment.segment_role in {"opening", "misread"} and move_family in {"accuse", "probe_secret", "deflect"}:
            base += 0.08
        if first_segment.segment_role in {"reveal", "terminal"} and move_family in {"public_reveal", "betray", "accuse"}:
            base += 0.1
        move_boosts[move_family] = round(min(base, 0.45), 4)

    lane_objective_bias_by_lane: dict[SuggestionLaneId, str] = {}
    lane_target_bias_by_lane: dict[SuggestionLaneId, list[str]] = {}
    for lane in first_segment.suggestion_lanes[:3]:
        lane_objective_bias_by_lane[lane.lane_id] = trim_text(lane.objective, 220)
        lane_target_bias_by_lane[lane.lane_id] = list(unique_preserve(lane.target_priority_ids))[:3]

    voice_atom_weight_bias_by_character: dict[str, dict[str, float]] = {}
    active_ids = set(first_segment.focus_target_ids + first_segment.rival_target_ids)
    for member in bundle.bound_cast:
        if member.character_id not in active_ids:
            continue
        atoms = list(bundle.voice_atoms_by_character.get(member.character_id) or [])
        if not atoms:
            continue
        per_character: dict[str, float] = {}
        for atom in atoms[:5]:
            boost = 0.08
            if atom.segment_role == first_segment.segment_role:
                boost += 0.16
            if atom.segment_role in {"reveal", "terminal"} and first_segment.segment_role in {"pressure", "reversal"}:
                boost += 0.04
            per_character[atom.atom_id] = round(min(boost, 0.35), 4)
        if per_character:
            voice_atom_weight_bias_by_character[member.character_id] = per_character

    return BeatDeltaPack(
        snapshot_id=f"delta_pack_{uuid4().hex[:12]}",
        source="author_initial",
        beat_index=0,
        segment_id=first_segment.segment_id,
        segment_role=first_segment.segment_role,
        move_priority_boosts=move_boosts,
        progression_bias_summary=trim_text(first_segment.progression_rule_summary, 220),
        render_cue_bias=list(unique_preserve(first_segment.render_cues))[:5],
        lane_objective_bias_by_lane=lane_objective_bias_by_lane,
        lane_target_bias_by_lane=lane_target_bias_by_lane,
        voice_atom_weight_bias_by_character=voice_atom_weight_bias_by_character,
        normal_turn_card=_build_turn_card("normal"),
        burst_turn_card=_build_turn_card("burst"),
        micro_sim_hint_bundle=_build_micro_sim_hint_bundle(),
        compose_payload_hint_bundle=_build_compose_payload_hint_bundle(),
    )


def compile_play_plan(state: AuthorPlayState) -> AuthorPlayState:
    bundle = state["urban_bundle"]
    quality_tuning_profile = _apply_quality_tuning_patch(
        profile=_build_quality_tuning_profile(),
        patch_payload=_load_quality_tuning_patch(),
    )
    strategy_pack = _build_semantic_strategy_pack(
        blueprint=bundle.accepted_blueprint,
        segment_contracts=bundle.segment_contracts,
        cast=bundle.bound_cast,
    )
    strategy_pack = _apply_semantic_autotune_patch(
        strategy_pack=strategy_pack,
        shell_id=bundle.accepted_blueprint.story_shell_id,
        patch_payload=_load_semantic_autotune_patch(),
    )
    compiled_segments: list[CompiledSegment] = []
    playbooks_by_id = {playbook.segment_id: playbook for playbook in bundle.segment_playbooks}
    for contract in bundle.segment_contracts:
        playbook = playbooks_by_id[contract.segment_id]
        author_tuning = quality_tuning_profile.author
        promote_moves = list(author_tuning.move_priority_promote_by_segment.get(contract.segment_role, []))
        tuned_move_priorities = _tuned_move_priorities(
            base_priorities=list(playbook.move_priorities),
            allowed_moves=list(contract.allowed_move_families),
            promote_moves=promote_moves,
        )
        progression_intensity = float(author_tuning.progression_intensity_by_segment.get(contract.segment_role, 1.0))
        tuned_progression = _tuned_progression_summary(
            summary=playbook.progression_rule_summary,
            intensity=progression_intensity,
            control_contract_hint_weight=float(author_tuning.control_contract_hint_weight),
        )
        tuned_render_cues = _tuned_render_cues(
            cues=list(playbook.render_cues),
            boost=list(author_tuning.render_cue_boost_by_segment.get(contract.segment_role, [])),
        )
        compiled_segments.append(
            CompiledSegment(
                segment_id=contract.segment_id,
                segment_role=contract.segment_role,
                focus_target_ids=contract.focus_target_ids,
                rival_target_ids=contract.rival_target_ids,
                allocated_secret_ids=contract.allocated_secret_ids,
                is_terminal=contract.is_terminal,
                progress_required=contract.progress_required,
                segment_turn_floor=contract.segment_turn_floor,
                allowed_move_families=contract.allowed_move_families,
                venue_id=contract.venue_id,
                scene_goal=playbook.scene_goal,
                emotional_goal=playbook.emotional_goal,
                move_priorities=tuned_move_priorities,
                public_pressure_cue=playbook.public_pressure_cue,
                private_pressure_cue=playbook.private_pressure_cue,
                progression_rule_summary=tuned_progression,
                suggestion_lanes=playbook.suggestion_lanes,
                render_cues=tuned_render_cues,
                template_tone_example_lines=playbook.template_tone_example_lines,
                template_tone_scene_examples=playbook.template_tone_scene_examples,
                tone_example_pack=playbook.tone_example_pack,
                segment_style_profile=playbook.segment_style_profile,
                scene_active_cap=playbook.scene_active_cap,
            )
        )
    play_plan = CompiledPlayPlan(
        story_id=bundle.story_id,
        title=bundle.title,
        story_shell_id=bundle.accepted_blueprint.story_shell_id,
        fit_mode=bundle.fit_mode,
        template_id=bundle.template_id,
        seed_fingerprint=bundle.seed_fingerprint,
        arc_template_id=bundle.arc_template_id,
        protagonist_public_identity=bundle.accepted_blueprint.protagonist_public_identity,
        protagonist_hidden_need=bundle.accepted_blueprint.protagonist_hidden_need,
        social_arena=bundle.accepted_blueprint.social_arena,
        play_length_preset=bundle.accepted_blueprint.play_length_preset,
        route_promise=bundle.accepted_blueprint.route_promise,
        bomb_moment=bundle.accepted_blueprint.bomb_moment,
        cost_of_truth=bundle.accepted_blueprint.cost_of_truth,
        cast=bundle.bound_cast,
        voice_atoms_by_character=bundle.voice_atoms_by_character,
        route_target_ids=[member.character_id for member in bundle.bound_cast if member.is_route_target][:4],
        delta_pack_contract_version=4,
        delta_kernel=_build_delta_kernel(bundle),
        initial_beat_delta_pack=_build_initial_beat_delta_pack(
            bundle=bundle,
            first_segment=compiled_segments[0],
        ),
        segments=compiled_segments,
        ending_matrix=bundle.ending_matrix,
        opening_narration=bundle.opening_narration,
        max_turns={
            "short_3": 24,
            "compact_4": 28,
            "standard_4": 32,
            "long_5": 36,
            "flagship_6": 40,
            "super_flagship_8": 56,
        }[bundle.arc_template_id],
        semantic_strategy_version=8,
        semantic_strategy_pack=strategy_pack,
        quality_tuning_profile=quality_tuning_profile,
    )
    return {
        "compiled_play_plan": play_plan,
        "quality_trace": _append_quality(state, stage="compile_play_plan", outcome="accepted"),
    }


def _set_arc_template(state: AuthorPlayState) -> AuthorPlayState:
    arc_template_id = select_arc_template(state["accepted_blueprint"])
    return {
        "arc_template_id": arc_template_id,
        "quality_trace": _append_quality(state, stage="select_arc_template", outcome="accepted"),
    }


def build_author_play_graph() -> Any:
    graph = StateGraph(AuthorPlayState)
    graph.add_node("select_arc_template", _set_arc_template)
    graph.add_node("plan_cast_slots", plan_cast_slots)
    graph.add_node("bind_ip_cast", bind_ip_cast)
    graph.add_node("compile_voice_atoms", compile_voice_atoms)
    graph.add_node("allocate_segment_contracts", allocate_segment_contracts)
    graph.add_node("compile_segment_playbooks", compile_segment_playbooks)
    graph.add_node("compile_ending_matrix", compile_ending_matrix)
    graph.add_node("assemble_urban_bundle", assemble_urban_bundle)
    graph.add_node("compile_play_plan", compile_play_plan)
    graph.add_edge(START, "select_arc_template")
    graph.add_edge("select_arc_template", "plan_cast_slots")
    graph.add_edge("plan_cast_slots", "bind_ip_cast")
    graph.add_edge("bind_ip_cast", "compile_voice_atoms")
    graph.add_edge("compile_voice_atoms", "allocate_segment_contracts")
    graph.add_edge("allocate_segment_contracts", "compile_segment_playbooks")
    graph.add_edge("compile_segment_playbooks", "compile_ending_matrix")
    graph.add_edge("compile_ending_matrix", "assemble_urban_bundle")
    graph.add_edge("assemble_urban_bundle", "compile_play_plan")
    graph.add_edge("compile_play_plan", END)
    return graph.compile()


def run_author_play_graph(
    accepted_blueprint: AcceptedBlueprint,
    *,
    live_mode: AuthorV2RunMode = "deterministic",
    gateway: AuthorV2LLMGateway | None = None,
) -> UrbanPipelineResult:
    compiled = build_author_play_graph()
    initial_state: AuthorPlayState = {
        "accepted_blueprint": accepted_blueprint,
        "llm_call_trace": [],
        "quality_trace": [],
        "live_mode": live_mode,
        "live_gateway": gateway,
    }
    state = compiled.invoke(initial_state)
    return UrbanPipelineResult(
        bundle=state["urban_bundle"],
        play_plan=state["compiled_play_plan"],
        state=state,
    )
