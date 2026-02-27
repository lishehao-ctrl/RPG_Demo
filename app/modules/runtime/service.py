from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable

from sqlalchemy import select, update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ActionLog, Session as GameSession
from app.db.models import SessionStepIdempotency, User
from app.modules.llm_boundary.errors import LLMUnavailableError
from app.modules.llm_boundary.schemas import EndingBundleOutput, SelectionMappingOutputV3
from app.modules.llm_boundary.service import LLMBoundary
from app.modules.runtime.mapping import is_risky_input, normalize_text
from app.modules.runtime.schemas import (
    ChoiceOut,
    CurrentNodeOut,
    SessionCreateResponse,
    SessionStateResponse,
    StepRequest,
    StepResponse,
)
from app.modules.runtime.state import (
    apply_range_effects,
    apply_transition,
    build_npc_state_from_defs,
    default_state,
    relation_tier_from_tiers,
    tier_index,
)
from app.modules.story_domain.schemas import GlobalFallbackV2, StoryPackV2
from app.modules.story_domain.service import get_story_pack, resolve_effective_story_assets
from app.utils.time import utc_now_naive


class RuntimeNotFoundError(ValueError):
    pass


class RuntimeConflictError(ValueError):
    pass


class RuntimeInvalidChoiceError(ValueError):
    pass


class RuntimeChoiceLockedError(RuntimeInvalidChoiceError):
    pass


class IdempotencyInProgressError(RuntimeConflictError):
    pass


class IdempotencyPayloadMismatchError(RuntimeConflictError):
    pass


class RuntimeForbiddenError(RuntimeConflictError):
    pass


class StreamAbortedError(RuntimeConflictError):
    pass


class SessionStepConflictError(RuntimeConflictError):
    def __init__(self, *, stage: str):
        self.stage = stage
        super().__init__(f"session step conflict at {stage}")


_SELECTION_SCHEMA_V3 = "story_selection_mapping_v3"
_FALLBACK_REASON_BY_DECISION_CODE = {
    "FALLBACK_NO_MATCH": "NO_MATCH",
    "FALLBACK_LOW_CONF": "LOW_CONF",
    "FALLBACK_OFF_TOPIC": "OFF_TOPIC",
    "FALLBACK_INPUT_POLICY": "INPUT_POLICY",
}
_FALLBACK_PENALTY_BASE = {
    "NO_MATCH": -1,
    "LOW_CONF": -1,
    "OFF_TOPIC": -1,
    "INPUT_POLICY": -2,
}


class _SelectionResolutionError(ValueError):
    def __init__(self, *, code: str, message: str):
        self.code = code
        super().__init__(message)


StepPhaseHook = Callable[[str, dict | None], None]
NarrativeDeltaHook = Callable[[str], None]


def _emit_phase(hook: StepPhaseHook | None, phase: str, payload: dict | None = None) -> None:
    if hook is None:
        return
    try:
        hook(phase, payload)
    except Exception:
        # Phase hooks are telemetry/UI side channels and must never break runtime.
        return


def _emit_narrative_delta(hook: NarrativeDeltaHook | None, text: str) -> None:
    if hook is None or not text:
        return
    try:
        hook(text)
    except Exception:
        # Streaming callbacks are best-effort and should not affect gameplay state.
        return


def _ensure_runtime_user(db: Session, *, user_id: str | None = None) -> User:
    if user_id:
        row = db.get(User, user_id)
        if row is None:
            raise RuntimeNotFoundError("user not found")
        return row

    row = db.execute(select(User).where(User.external_ref == settings.default_user_external_ref)).scalar_one_or_none()
    if row:
        return row
    row = User(external_ref=settings.default_user_external_ref, display_name=settings.default_user_display_name)
    db.add(row)
    db.flush()
    return row


def _node_index(pack: StoryPackV2) -> dict[str, dict]:
    return {node.node_id: node.model_dump() for node in pack.nodes}


def _npc_defs_by_id(pack: StoryPackV2) -> dict[str, dict]:
    return {item.npc_id: item.model_dump() for item in pack.npc_defs}


def _npc_reaction_policy_by_id(pack: StoryPackV2) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for policy in pack.npc_reaction_policies:
        out[policy.npc_id] = policy.model_dump()
    return out


def _merge_state_delta(base: dict, extra: dict) -> dict:
    merged = copy.deepcopy(base if isinstance(base, dict) else {})
    src = extra if isinstance(extra, dict) else {}
    for key in ("energy", "money", "knowledge", "affection"):
        if key in src:
            merged[key] = int(merged.get(key, 0) or 0) + int(src.get(key, 0) or 0)

    src_npc = src.get("npc")
    if isinstance(src_npc, dict):
        npc_delta = merged.setdefault("npc", {})
        for npc_id, per_npc_src in src_npc.items():
            if not isinstance(per_npc_src, dict):
                continue
            per_npc_dst = npc_delta.setdefault(npc_id, {})
            for axis in ("affection", "trust"):
                if axis in per_npc_src:
                    per_npc_dst[axis] = int(per_npc_dst.get(axis, 0) or 0) + int(per_npc_src.get(axis, 0) or 0)
            for tier_key in ("affection_tier", "trust_tier", "relation_tier"):
                if tier_key in per_npc_src:
                    per_npc_dst[tier_key] = per_npc_src[tier_key]
    return merged


def _resolve_reactive_npc_ids(action_payload: dict, *, pack: StoryPackV2) -> list[str]:
    raw = action_payload.get("reactive_npc_ids") if isinstance(action_payload, dict) else []
    ids = [str(item).strip() for item in (raw or []) if str(item).strip()]
    if ids:
        return ids
    if len(pack.npc_defs) == 1:
        return [pack.npc_defs[0].npc_id]
    return []


def _resolve_npc_relation_tier(npc: dict) -> str:
    relation = str(npc.get("relation_tier") or "").strip()
    if relation:
        return relation
    affection_tier = str(npc.get("affection_tier") or "Hostile")
    trust_tier = str(npc.get("trust_tier") or "Hostile")
    return relation_tier_from_tiers(affection_tier, trust_tier)


def _collect_npc_reaction_effects(
    *,
    state_after: dict,
    reactive_npc_ids: list[str],
    reaction_policy_by_id: dict[str, dict],
    source: str,
) -> tuple[list[dict], list[str]]:
    npc_state = state_after.get("npc_state") if isinstance(state_after, dict) else {}
    npc_state = npc_state if isinstance(npc_state, dict) else {}
    effects: list[dict] = []
    hints: list[str] = []
    for npc_id in reactive_npc_ids:
        npc = npc_state.get(npc_id)
        policy = reaction_policy_by_id.get(npc_id)
        if not isinstance(npc, dict) or not isinstance(policy, dict):
            continue
        relation_tier = _resolve_npc_relation_tier(npc)
        rules = list(policy.get("rules") or [])
        matched = None
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_tier = str(rule.get("tier") or "").strip()
            rule_source = str(rule.get("source") or "any").strip()
            if rule_tier != relation_tier:
                continue
            if rule_source not in {"any", source}:
                continue
            matched = rule
            break
        if matched is None:
            continue
        for effect in list(matched.get("effects") or []):
            if isinstance(effect, dict):
                effects.append(dict(effect))
        hint = str(matched.get("narrative_hint") or "").strip()
        if hint:
            hints.append(hint)
    return effects, hints


def _evaluate_choice_gate(
    *,
    choice: dict,
    state_json: dict,
    npc_defs: dict[str, dict],
) -> tuple[bool, dict | None, list[dict]]:
    gate_rules = list(choice.get("gate_rules") or [])
    if not gate_rules:
        return True, None, []

    npc_state = state_json.get("npc_state") if isinstance(state_json, dict) else {}
    npc_state = npc_state if isinstance(npc_state, dict) else {}
    failures: list[dict] = []

    for raw in gate_rules:
        rule = raw if isinstance(raw, dict) else {}
        npc_id = str(rule.get("npc_id") or "").strip()
        if not npc_id:
            failures.append({"code": "NPC_GATE_INVALID_RULE", "message": "Invalid npc gate rule.", "npc_id": ""})
            continue

        npc_name = str((npc_defs.get(npc_id) or {}).get("name") or npc_id)
        npc = npc_state.get(npc_id)
        if not isinstance(npc, dict):
            failures.append(
                {
                    "code": "NPC_GATE_NPC_MISSING",
                    "message": f"{npc_name} is not available in current runtime state.",
                    "npc_id": npc_id,
                }
            )
            continue

        min_affection_tier = rule.get("min_affection_tier")
        min_trust_tier = rule.get("min_trust_tier")
        current_affection_tier = str(npc.get("affection_tier") or "Hostile")
        current_trust_tier = str(npc.get("trust_tier") or "Hostile")

        if min_affection_tier is not None and tier_index(current_affection_tier) < tier_index(str(min_affection_tier)):
            failures.append(
                {
                    "code": "NPC_GATE_TIER",
                    "message": f"Need {npc_name} affection tier >= {min_affection_tier}.",
                    "npc_id": npc_id,
                    "axis": "affection",
                    "required": str(min_affection_tier),
                    "current": current_affection_tier,
                }
            )

        if min_trust_tier is not None and tier_index(current_trust_tier) < tier_index(str(min_trust_tier)):
            failures.append(
                {
                    "code": "NPC_GATE_TIER",
                    "message": f"Need {npc_name} trust tier >= {min_trust_tier}.",
                    "npc_id": npc_id,
                    "axis": "trust",
                    "required": str(min_trust_tier),
                    "current": current_trust_tier,
                }
            )

    if not failures:
        return True, None, []
    first = failures[0]
    return False, {"code": str(first.get("code") or "NPC_GATE_TIER"), "message": str(first.get("message") or "")}, failures


def _evaluate_node_choices(
    *,
    node: dict,
    state_json: dict,
    npc_defs: dict[str, dict],
) -> list[dict]:
    evaluated: list[dict] = []
    for choice in list(node.get("choices") or []):
        available, locked_reason, gate_failed_rules = _evaluate_choice_gate(choice=choice, state_json=state_json, npc_defs=npc_defs)
        evaluated.append(
            {
                "choice": choice,
                "available": available,
                "locked_reason": locked_reason,
                "gate_failed_rules": gate_failed_rules,
            }
        )
    return evaluated


def _current_node_out(node: dict, *, state_json: dict, npc_defs: dict[str, dict]) -> CurrentNodeOut:
    evaluated = _evaluate_node_choices(node=node, state_json=state_json, npc_defs=npc_defs)
    return CurrentNodeOut(
        id=str(node.get("node_id")),
        title=str(node.get("title")),
        scene_brief=str(node.get("scene_brief")),
        choices=[
            ChoiceOut(
                id=str(item["choice"].get("choice_id")),
                text=str(item["choice"].get("text")),
                available=bool(item["available"]),
                locked_reason=item["locked_reason"],
            )
            for item in evaluated
        ],
    )


def create_session(db: Session, *, story_id: str, version: int | None, user_id: str | None) -> SessionCreateResponse:
    with db.begin():
        user = _ensure_runtime_user(db, user_id=user_id)
        resolved_version, pack_raw = get_story_pack(db, story_id=story_id, version=version)
        pack = StoryPackV2.model_validate(pack_raw)
        node_map = _node_index(pack)
        start_node = node_map.get(pack.start_node_id)
        if not start_node:
            raise RuntimeNotFoundError("story start node not found")
        state = default_state()
        state["npc_state"] = build_npc_state_from_defs([item.model_dump() for item in pack.npc_defs])
        npc_defs = _npc_defs_by_id(pack)
        session = GameSession(
            user_id=user.id,
            story_id=story_id,
            story_version=resolved_version,
            status="active",
            story_node_id=pack.start_node_id,
            state_json=state,
            version=0,
        )
        db.add(session)
        db.flush()

    return SessionCreateResponse(
        session_id=session.id,
        story_id=story_id,
        story_version=resolved_version,
        story_node_id=pack.start_node_id,
        state_json=copy.deepcopy(session.state_json),
        current_node=_current_node_out(start_node, state_json=session.state_json or {}, npc_defs=npc_defs),
        status=session.status,
    )


def _assert_session_owner(db: Session, *, session_id: str, actor_user_id: str | None) -> GameSession:
    sess = db.get(GameSession, session_id)
    if sess is None:
        raise RuntimeNotFoundError("session not found")
    if actor_user_id and str(sess.user_id) != str(actor_user_id):
        raise RuntimeForbiddenError("session ownership mismatch")
    return sess


def get_session_state(
    db: Session,
    *,
    session_id: str,
    actor_user_id: str | None = None,
) -> SessionStateResponse:
    row = _assert_session_owner(db, session_id=session_id, actor_user_id=actor_user_id)
    resolved_version, pack_raw = get_story_pack(db, story_id=row.story_id, version=row.story_version)
    pack = StoryPackV2.model_validate(pack_raw)
    npc_defs = _npc_defs_by_id(pack)
    node_map = _node_index(pack)
    node = node_map.get(row.story_node_id)
    if not node:
        raise RuntimeNotFoundError("session current node not found in story pack")

    return SessionStateResponse(
        session_id=row.id,
        story_id=row.story_id,
        story_version=resolved_version,
        story_node_id=row.story_node_id,
        status=row.status,
        state_json=copy.deepcopy(row.state_json),
        current_node=_current_node_out(node, state_json=row.state_json or {}, npc_defs=npc_defs),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prepare_idempotency(
    db: Session,
    *,
    session_id: str,
    idempotency_key: str,
    request_hash: str,
    actor_user_id: str | None = None,
) -> dict | None:
    with db.begin():
        if actor_user_id:
            owner = db.execute(select(GameSession.user_id).where(GameSession.id == session_id)).scalar_one_or_none()
            if owner is None:
                raise RuntimeNotFoundError("session not found")
            if str(owner) != str(actor_user_id):
                raise RuntimeForbiddenError("session ownership mismatch")

        row = db.execute(
            select(SessionStepIdempotency).where(
                SessionStepIdempotency.session_id == session_id,
                SessionStepIdempotency.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

        if row is None:
            row = SessionStepIdempotency(
                session_id=session_id,
                idempotency_key=idempotency_key,
                status="in_progress",
                request_hash=request_hash,
            )
            db.add(row)
            db.flush()
            return None

        if row.request_hash != request_hash:
            raise IdempotencyPayloadMismatchError("idempotency key reused with different payload")

        if row.status == "succeeded" and isinstance(row.response_json, dict):
            return copy.deepcopy(row.response_json)

        if row.status == "in_progress":
            raise IdempotencyInProgressError("request already in progress")

        row.status = "in_progress"
        row.error_code = None
        row.response_json = None
        row.updated_at = utc_now_naive()
        db.flush()
        return None


def _mark_idempotency_success(
    db: Session,
    *,
    session_id: str,
    idempotency_key: str,
    request_hash: str,
    response_json: dict,
) -> None:
    with db.begin():
        row = db.execute(
            select(SessionStepIdempotency).where(
                SessionStepIdempotency.session_id == session_id,
                SessionStepIdempotency.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if row is None:
            row = SessionStepIdempotency(
                session_id=session_id,
                idempotency_key=idempotency_key,
                status="succeeded",
                request_hash=request_hash,
                response_json=response_json,
                error_code=None,
            )
            db.add(row)
            db.flush()
            return
        row.status = "succeeded"
        row.error_code = None
        row.response_json = response_json
        row.updated_at = utc_now_naive()
        db.flush()


def _mark_idempotency_failed(
    db: Session,
    *,
    session_id: str,
    idempotency_key: str,
    request_hash: str,
    error_code: str,
) -> None:
    with db.begin():
        row = db.execute(
            select(SessionStepIdempotency).where(
                SessionStepIdempotency.session_id == session_id,
                SessionStepIdempotency.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if row is None:
            row = SessionStepIdempotency(
                session_id=session_id,
                idempotency_key=idempotency_key,
                status="failed",
                request_hash=request_hash,
                error_code=error_code,
            )
            db.add(row)
            db.flush()
            return
        row.status = "failed"
        row.error_code = error_code
        row.updated_at = utc_now_naive()
        db.flush()


def _normalize_player_input(raw: str | None) -> str:
    text = normalize_text(raw or "")
    max_chars = int(settings.story_input_max_chars)
    return text[:max_chars] if len(text) > max_chars else text


def _default_hub_node_id(pack: StoryPackV2, node_map: dict[str, dict]) -> str:
    if "n_hub" in node_map:
        return "n_hub"
    return pack.start_node_id


def _resolve_fallback_target_node(
    fallback: GlobalFallbackV2,
    *,
    current_node: dict,
    fallback_by_id: dict[str, GlobalFallbackV2],
    default_hub_node_id: str,
) -> str:
    if fallback.target_node_id:
        return fallback.target_node_id

    node_fallback_id = str(current_node.get("node_fallback_id") or "").strip()
    if node_fallback_id and node_fallback_id in fallback_by_id:
        linked = fallback_by_id[node_fallback_id]
        if linked.target_node_id:
            return linked.target_node_id

    return default_hub_node_id


def _pick_fallback_by_reason(
    *,
    reason_code: str,
    effective_fallbacks: list[GlobalFallbackV2],
    current_node: dict,
    fallback_by_id: dict[str, GlobalFallbackV2],
    default_hub_node_id: str,
    player_input: str,
    step_index: int,
) -> tuple[GlobalFallbackV2, str]:
    # 1) reason-specific fallback
    reason_matches = [item for item in effective_fallbacks if item.reason_code == reason_code]
    if reason_matches:
        picked = reason_matches[0]
        target = _resolve_fallback_target_node(
            picked,
            current_node=current_node,
            fallback_by_id=fallback_by_id,
            default_hub_node_id=default_hub_node_id,
        )
        return picked, target

    # 2) node fallback
    node_fallback_id = str(current_node.get("node_fallback_id") or "").strip()
    if node_fallback_id and node_fallback_id in fallback_by_id:
        picked = fallback_by_id[node_fallback_id]
        target = _resolve_fallback_target_node(
            picked,
            current_node=current_node,
            fallback_by_id=fallback_by_id,
            default_hub_node_id=default_hub_node_id,
        )
        return picked, target

    # 3) deterministic hash pick from all effective fallbacks
    if not effective_fallbacks:
        raise RuntimeNotFoundError("no effective fallback candidates")
    seed = f"{current_node.get('node_id')}|{player_input}|{step_index}|{reason_code}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    idx = int.from_bytes(digest[:4], byteorder="big") % len(effective_fallbacks)
    picked = effective_fallbacks[idx]
    target = _resolve_fallback_target_node(
        picked,
        current_node=current_node,
        fallback_by_id=fallback_by_id,
        default_hub_node_id=default_hub_node_id,
    )
    return picked, target


def _auto_mainline_nudge(*, next_node: dict) -> str:
    choices = list(next_node.get("choices") or [])
    if choices:
        top_choice = str(choices[0].get("text") or "").strip()
        if top_choice:
            return f"To get back on track, focus on: {top_choice}."
    scene = str(next_node.get("title") or next_node.get("node_id") or "the next scene").strip()
    return f"To get back on track, act on the clearest objective in {scene}."


def _resolve_nudge_tier(*, fallback_reason: str | None, consecutive_fallback_count: int) -> str:
    reason = str(fallback_reason or "").strip().upper()
    if reason == "INPUT_POLICY" or consecutive_fallback_count >= 3:
        return "firm"
    if reason == "LOW_CONF" or consecutive_fallback_count == 2:
        return "neutral"
    return "soft"


def _resolve_ending_tone(*, ending_outcome: str | None) -> str:
    outcome = str(ending_outcome or "").strip().lower()
    if outcome == "success":
        return "triumphant"
    if outcome == "neutral":
        return "reflective"
    return "somber"


def _to_float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_confidence_thresholds() -> tuple[float, float]:
    high = min(1.0, max(0.0, float(settings.story_mapping_confidence_high)))
    low = min(1.0, max(0.0, float(settings.story_mapping_confidence_low)))
    if low > high:
        low, high = high, low
    return high, low


def _clamp_intensity_tier(value: object) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = 0
    return max(-2, min(2, parsed))


def _decision_matches_target_type(*, decision_code: str, target_type: str) -> bool:
    if decision_code == "SELECT_CHOICE":
        return target_type == "choice"
    if decision_code in _FALLBACK_REASON_BY_DECISION_CODE:
        return target_type == "fallback"
    return False


def _resolve_selection_decision_v3(
    *,
    llm_mapping: SelectionMappingOutputV3,
    choice_by_id: dict[str, dict],
    fallback_by_id: dict[str, GlobalFallbackV2],
    input_policy_flag: bool,
    confidence_high: float,
    confidence_low: float,
) -> dict:
    decision_code = str(llm_mapping.decision_code or "").strip().upper()
    target_type = str(llm_mapping.target_type or "").strip()
    target_id = str(llm_mapping.target_id or "").strip()
    mapping_confidence = float(llm_mapping.confidence)
    raw_intensity_tier = _clamp_intensity_tier(llm_mapping.intensity_tier)
    top_candidates = [item.model_dump() for item in llm_mapping.top_candidates]
    mapped_reason = str(llm_mapping.fallback_reason_code or "").strip().upper() or None
    decision_reason = _FALLBACK_REASON_BY_DECISION_CODE.get(decision_code)

    if input_policy_flag:
        preferred = target_id if target_type == "fallback" and target_id in fallback_by_id else None
        return {
            "selection_source": "fallback",
            "executed_choice": None,
            "attempted_choice_id": target_id if target_type == "choice" else None,
            "preferred_fallback_id": preferred,
            "fallback_reason": "INPUT_POLICY",
            "mapping_confidence": mapping_confidence,
            "top_candidates": top_candidates,
            "raw_intensity_tier": raw_intensity_tier,
            "selection_decision_code": "FALLBACK_INPUT_POLICY",
            "fallback_reason_code": "INPUT_POLICY",
            "decision_overridden_by_runtime": True,
            "runtime_override_reason": "INPUT_POLICY_FLAG",
        }

    if not _decision_matches_target_type(decision_code=decision_code, target_type=target_type):
        raise _SelectionResolutionError(code="SCHEMA_INCONSISTENT", message="decision_code does not match target_type")

    if target_type == "choice":
        selected = choice_by_id.get(target_id)
        if selected is None:
            raise _SelectionResolutionError(code="TARGET_NOT_ALLOWED", message="llm selection target choice is not available")

        if mapping_confidence >= confidence_high:
            return {
                "selection_source": "llm",
                "executed_choice": selected,
                "attempted_choice_id": target_id,
                "preferred_fallback_id": None,
                "fallback_reason": None,
                "mapping_confidence": mapping_confidence,
                "top_candidates": top_candidates,
                "raw_intensity_tier": raw_intensity_tier,
                "selection_decision_code": decision_code,
                "fallback_reason_code": None,
                "decision_overridden_by_runtime": False,
                "runtime_override_reason": None,
            }

        downgraded_reason = "LOW_CONF" if mapping_confidence >= confidence_low else "NO_MATCH"
        return {
            "selection_source": "fallback",
            "executed_choice": None,
            "attempted_choice_id": target_id,
            "preferred_fallback_id": None,
            "fallback_reason": downgraded_reason,
            "mapping_confidence": mapping_confidence,
            "top_candidates": top_candidates,
            "raw_intensity_tier": raw_intensity_tier,
            "selection_decision_code": (
                "FALLBACK_LOW_CONF" if downgraded_reason == "LOW_CONF" else "FALLBACK_NO_MATCH"
            ),
            "fallback_reason_code": downgraded_reason,
            "decision_overridden_by_runtime": True,
            "runtime_override_reason": (
                "CONFIDENCE_GATE_LOW_CONF" if downgraded_reason == "LOW_CONF" else "CONFIDENCE_GATE_NO_MATCH"
            ),
        }

    fallback = fallback_by_id.get(target_id)
    if fallback is None:
        raise _SelectionResolutionError(code="TARGET_NOT_ALLOWED", message="llm selection target fallback is not valid")

    if decision_reason and mapped_reason and mapped_reason != decision_reason:
        raise _SelectionResolutionError(code="FALLBACK_REASON_INVALID", message="fallback reason_code conflicts with decision_code")

    if decision_code == "SELECT_CHOICE":
        raise _SelectionResolutionError(code="SCHEMA_INCONSISTENT", message="fallback target cannot use SELECT_CHOICE decision")

    resolved_reason = decision_reason or mapped_reason or str(fallback.reason_code or "").strip().upper() or None
    if resolved_reason is None:
        raise _SelectionResolutionError(code="FALLBACK_REASON_INVALID", message="fallback_reason_code missing")

    fallback_reason_code = str(fallback.reason_code or "").strip().upper() or None
    if fallback_reason_code and fallback_reason_code != resolved_reason:
        raise _SelectionResolutionError(code="FALLBACK_REASON_INVALID", message="target fallback reason_code mismatch")

    return {
        "selection_source": "fallback",
        "executed_choice": None,
        "attempted_choice_id": None,
        "preferred_fallback_id": target_id,
        "fallback_reason": resolved_reason,
        "mapping_confidence": mapping_confidence,
        "top_candidates": top_candidates,
        "raw_intensity_tier": raw_intensity_tier,
        "selection_decision_code": decision_code,
        "fallback_reason_code": resolved_reason,
        "decision_overridden_by_runtime": False,
        "runtime_override_reason": None,
    }


def _compute_effective_tier(*, raw_llm_tier: int, fallback_used: bool, fallback_reason: str | None) -> tuple[int, int]:
    raw = _clamp_intensity_tier(raw_llm_tier)
    if not fallback_used:
        return raw, 0

    reason = str(fallback_reason or "").strip().upper()
    base_penalty = int(_FALLBACK_PENALTY_BASE.get(reason, -1))
    effective = _clamp_intensity_tier(raw + base_penalty)
    return effective, base_penalty


def _compact_state_delta(delta: dict | None) -> dict:
    raw = delta if isinstance(delta, dict) else {}
    return {
        "energy": _to_float(raw.get("energy"), default=0.0),
        "money": _to_float(raw.get("money"), default=0.0),
        "knowledge": _to_float(raw.get("knowledge"), default=0.0),
        "affection": _to_float(raw.get("affection"), default=0.0),
    }


def _build_ending_report_brief(
    db: Session,
    *,
    session_id: str,
    state_after: dict,
    current_step_index: int,
    current_executed_choice_id: str,
    current_fallback_reason: str | None,
    current_selection_source: str,
    current_state_delta: dict,
    recent_window: int = 12,
) -> dict:
    logs = (
        db.execute(
            select(ActionLog).where(ActionLog.session_id == session_id).order_by(ActionLog.step_index.asc())
        )
        .scalars()
        .all()
    )

    source_counts = {"explicit": 0, "rule": 0, "llm": 0, "fallback": 0}
    for row in logs:
        selection_result = row.selection_result_json or {}
        source = str(selection_result.get("selection_source") or "fallback")
        if source in source_counts:
            source_counts[source] += 1
        else:
            source_counts["fallback"] += 1
    if current_selection_source in source_counts:
        source_counts[current_selection_source] += 1
    else:
        source_counts["fallback"] += 1

    baseline = default_state()
    total_steps = int(((state_after.get("run_state") or {}).get("step_index", 0) or 0))
    fallback_count = int(((state_after.get("run_state") or {}).get("fallback_count", 0) or 0))
    fallback_rate = 0.0 if total_steps <= 0 else min(1.0, max(0.0, fallback_count / float(total_steps)))
    session_stats = {
        "total_steps": total_steps,
        "fallback_count": fallback_count,
        "fallback_rate": round(fallback_rate, 4),
        "explicit_count": int(source_counts["explicit"]),
        "rule_count": int(source_counts["rule"]),
        "llm_count": int(source_counts["llm"]),
        "fallback_source_count": int(source_counts["fallback"]),
        "energy_delta": round(_to_float(state_after.get("energy")) - _to_float(baseline.get("energy")), 3),
        "money_delta": round(_to_float(state_after.get("money")) - _to_float(baseline.get("money")), 3),
        "knowledge_delta": round(_to_float(state_after.get("knowledge")) - _to_float(baseline.get("knowledge")), 3),
        "affection_delta": round(_to_float(state_after.get("affection")) - _to_float(baseline.get("affection")), 3),
    }

    recent_beats: list[dict] = []
    prior_rows = logs[-max(0, recent_window - 1) :]
    for row in prior_rows:
        selection_result = row.selection_result_json or {}
        recent_beats.append(
            {
                "step_index": int(row.step_index),
                "executed_choice_id": str(selection_result.get("executed_choice_id") or ""),
                "fallback_reason": selection_result.get("fallback_reason"),
                "selection_source": str(selection_result.get("selection_source") or "fallback"),
                "state_delta": _compact_state_delta(row.state_delta),
            }
        )

    recent_beats.append(
        {
            "step_index": int(current_step_index),
            "executed_choice_id": current_executed_choice_id,
            "fallback_reason": current_fallback_reason,
            "selection_source": current_selection_source,
            "state_delta": _compact_state_delta(current_state_delta),
        }
    )
    if len(recent_beats) > recent_window:
        recent_beats = recent_beats[-recent_window:]

    return {
        "session_stats": session_stats,
        "recent_action_beats": recent_beats,
    }


def _select_via_free_input(
    *,
    player_input: str,
    current_node: dict,
    state_before: dict,
    npc_defs: dict[str, dict],
    effective_fallbacks: list[GlobalFallbackV2],
    llm_boundary: LLMBoundary,
) -> dict:
    evaluated = _evaluate_node_choices(node=current_node, state_json=state_before, npc_defs=npc_defs)
    available_choices = [item["choice"] for item in evaluated if item["available"]]
    choice_by_id = {str(item.get("choice_id") or ""): item for item in available_choices}
    fallback_by_id = {item.fallback_id: item for item in effective_fallbacks}
    input_policy_flag = is_risky_input(player_input)
    allowed_target_ids = list(choice_by_id.keys()) + list(fallback_by_id.keys())
    confidence_high, confidence_low = _normalize_confidence_thresholds()
    retry_errors: list[str] = []
    max_attempts = 3
    last_error_message = "selection mapping unavailable"

    for attempt in range(1, max_attempts + 1):
        retry_context = None
        if attempt > 1:
            retry_context = {
                "last_error_code": retry_errors[-1] if retry_errors else "UNKNOWN",
                "allowed_target_ids": allowed_target_ids,
            }
        try:
            llm_mapping: SelectionMappingOutputV3 = llm_boundary.map_free_input_v3(
                player_input=player_input,
                scene_brief=str(current_node.get("scene_brief") or ""),
                visible_choices=available_choices,
                available_fallbacks=[item.model_dump() for item in effective_fallbacks],
                input_policy_flag=input_policy_flag,
                retry_context=retry_context,
            )
        except LLMUnavailableError as exc:
            retry_errors.append("LLM_CALL_OR_SCHEMA_ERROR")
            last_error_message = str(exc)
            if attempt >= max_attempts:
                break
            continue

        try:
            resolved = _resolve_selection_decision_v3(
                llm_mapping=llm_mapping,
                choice_by_id=choice_by_id,
                fallback_by_id=fallback_by_id,
                input_policy_flag=input_policy_flag,
                confidence_high=confidence_high,
                confidence_low=confidence_low,
            )
        except _SelectionResolutionError as exc:
            retry_errors.append(exc.code)
            last_error_message = str(exc)
            if attempt >= max_attempts:
                break
            continue

        resolved["mapping_schema"] = _SELECTION_SCHEMA_V3
        resolved["input_policy_flag"] = bool(input_policy_flag)
        resolved["selection_retry_count"] = attempt
        resolved["selection_retry_errors"] = list(retry_errors)
        resolved["selection_final_attempt"] = attempt
        return resolved

    raise LLMUnavailableError(
        "selection mapping failed after 3 attempts: "
        + ";".join(retry_errors[-3:] or ["UNKNOWN"])
        + f" ({last_error_message})"
    )


def _execute_step(
    db: Session,
    *,
    session_id: str,
    payload: StepRequest,
    llm_boundary: LLMBoundary,
    actor_user_id: str | None = None,
    on_phase: StepPhaseHook | None = None,
    on_narrative_delta: NarrativeDeltaHook | None = None,
    abort_check: Callable[[], bool] | None = None,
) -> StepResponse:
    def _raise_if_stream_aborted() -> None:
        if abort_check is not None and bool(abort_check()):
            raise StreamAbortedError("stream closed by client")

    with db.begin():
        sess = _assert_session_owner(db, session_id=session_id, actor_user_id=actor_user_id)
        if sess.status != "active":
            raise RuntimeConflictError("session is not active")

        _, pack_raw = get_story_pack(db, story_id=sess.story_id, version=sess.story_version)
        pack = StoryPackV2.model_validate(pack_raw)
        effective_fallbacks, effective_endings = resolve_effective_story_assets(pack)
        node_map = _node_index(pack)
        npc_defs = _npc_defs_by_id(pack)
        reaction_policy_by_id = _npc_reaction_policy_by_id(pack)
        fallback_by_id = {item.fallback_id: item for item in effective_fallbacks}
        ending_by_id = {item.ending_id: item for item in effective_endings}

        current_node = node_map.get(sess.story_node_id)
        if current_node is None:
            raise RuntimeNotFoundError("current node missing from pack")
        state_before = copy.deepcopy(sess.state_json or default_state())
        state_before.setdefault("npc_state", build_npc_state_from_defs([item.model_dump() for item in pack.npc_defs]))
        expected_session_version = int(sess.version or 0)
        session_db_id = str(sess.id)
        story_id = str(sess.story_id)

        attempted_choice_id: str | None = None
        executed_choice_id: str
        fallback_used = False
        fallback_reason: str | None = None
        selection_mode: str
        selection_source: str
        mapping_confidence: float | None = None
        top_candidates: list[dict] = []
        raw_intensity_tier = 0
        effective_intensity_tier = 0
        fallback_base_penalty = 0
        selection_decision_code: str | None = None
        fallback_reason_code: str | None = None
        mapping_schema = _SELECTION_SCHEMA_V3
        decision_overridden_by_runtime = False
        runtime_override_reason: str | None = None
        range_effects: list[dict] = []
        reactive_npc_ids: list[str] = []
        transition_ending_id: str | None = None
        gate_blocked = False
        gate_failed_rules: list[dict] = []
        input_policy_flag = False
        selection_retry_count = 0
        selection_retry_errors: list[str] = []
        selection_final_attempt = 0
        next_node_id: str
        mainline_nudge: str | None = None
        nudge_tier: str | None = None
        preferred_fallback_id: str | None = None

        current_node_eval = _evaluate_node_choices(node=current_node, state_json=state_before, npc_defs=npc_defs)
        current_eval_by_id = {
            str(item["choice"].get("choice_id") or ""): item
            for item in current_node_eval
        }
        _raise_if_stream_aborted()
        _emit_phase(
            on_phase,
            "selection_start",
            {
                "selection_mode": "explicit_choice" if payload.choice_id else "free_input",
            },
        )

        if payload.choice_id:
            selection_mode = "explicit_choice"
            attempted_choice_id = str(payload.choice_id).strip()
            selected_entry = current_eval_by_id.get(attempted_choice_id)
            if selected_entry is None:
                raise RuntimeInvalidChoiceError("choice_id is not valid for current node")
            if not bool(selected_entry["available"]):
                gate_blocked = True
                gate_failed_rules = list(selected_entry["gate_failed_rules"] or [])
                reason = selected_entry.get("locked_reason") or {}
                raise RuntimeChoiceLockedError(str(reason.get("message") or "choice is locked by npc gate"))

            selected_choice = selected_entry["choice"]
            selection_source = "explicit"
            executed_choice_id = selected_choice["choice_id"]
            next_node_id = selected_choice["next_node_id"]
            range_effects = [dict(item) for item in list(selected_choice.get("range_effects") or []) if isinstance(item, dict)]
            reactive_npc_ids = _resolve_reactive_npc_ids(selected_choice, pack=pack)
            transition_ending_id = str(selected_choice.get("ending_id") or "").strip() or None
            raw_intensity_tier = 0
            effective_intensity_tier = 0
            fallback_base_penalty = 0
            selection_decision_code = "SELECT_CHOICE"
            fallback_reason_code = None
            mapping_schema = "explicit_choice"
            decision_overridden_by_runtime = False
            runtime_override_reason = None
            selection_retry_count = 0
            selection_retry_errors = []
            selection_final_attempt = 0
        else:
            selection_mode = "free_input"
            free_input = _normalize_player_input(payload.player_input)
            resolved = _select_via_free_input(
                player_input=free_input,
                current_node=current_node,
                state_before=state_before,
                npc_defs=npc_defs,
                effective_fallbacks=effective_fallbacks,
                llm_boundary=llm_boundary,
            )
            selection_source = str(resolved.get("selection_source") or "llm")
            attempted_choice_id = resolved.get("attempted_choice_id")
            mapping_confidence = resolved.get("mapping_confidence")
            top_candidates = list(resolved.get("top_candidates") or [])
            preferred_fallback_id = resolved.get("preferred_fallback_id")
            raw_intensity_tier = int(resolved.get("raw_intensity_tier", 0) or 0)
            input_policy_flag = bool(resolved.get("input_policy_flag"))
            selection_decision_code = str(resolved.get("selection_decision_code") or "").strip() or None
            fallback_reason_code = (
                str(resolved.get("fallback_reason_code") or "").strip().upper() or None
            )
            mapping_schema = str(resolved.get("mapping_schema") or _SELECTION_SCHEMA_V3)
            decision_overridden_by_runtime = bool(resolved.get("decision_overridden_by_runtime"))
            runtime_override_reason = (
                str(resolved.get("runtime_override_reason") or "").strip() or None
            )
            selection_retry_count = int(resolved.get("selection_retry_count", 1) or 1)
            selection_retry_errors = [str(item) for item in list(resolved.get("selection_retry_errors") or [])]
            selection_final_attempt = int(resolved.get("selection_final_attempt", selection_retry_count) or selection_retry_count)

            selected_choice = resolved.get("executed_choice")
            if isinstance(selected_choice, dict):
                executed_choice_id = str(selected_choice["choice_id"])
                next_node_id = str(selected_choice["next_node_id"])
                range_effects = [dict(item) for item in list(selected_choice.get("range_effects") or []) if isinstance(item, dict)]
                reactive_npc_ids = _resolve_reactive_npc_ids(selected_choice, pack=pack)
                transition_ending_id = str(selected_choice.get("ending_id") or "").strip() or None
            else:
                fallback_used = True
                fallback_reason = str(resolved.get("fallback_reason") or "NO_MATCH")

        if fallback_used:
            step_index = int(((state_before or {}).get("run_state") or {}).get("step_index", 0) or 0)
            player_input_for_seed = _normalize_player_input(payload.player_input)
            default_hub = _default_hub_node_id(pack, node_map)

            chosen_fallback: GlobalFallbackV2 | None = None
            target_node = ""
            if preferred_fallback_id and preferred_fallback_id in fallback_by_id:
                chosen_fallback = fallback_by_id[preferred_fallback_id]
                target_node = _resolve_fallback_target_node(
                    chosen_fallback,
                    current_node=current_node,
                    fallback_by_id=fallback_by_id,
                    default_hub_node_id=default_hub,
                )
            if chosen_fallback is None:
                chosen_fallback, target_node = _pick_fallback_by_reason(
                    reason_code=fallback_reason or "NO_MATCH",
                    effective_fallbacks=effective_fallbacks,
                    current_node=current_node,
                    fallback_by_id=fallback_by_id,
                    default_hub_node_id=default_hub,
                    player_input=player_input_for_seed,
                    step_index=step_index,
                )

            executed_choice_id = f"fallback:{chosen_fallback.fallback_id}"
            next_node_id = target_node
            range_effects = [item.model_dump() for item in chosen_fallback.range_effects]
            fallback_reason = str(chosen_fallback.reason_code or fallback_reason or "NO_MATCH")
            fallback_reason_code = str(fallback_reason or "").strip().upper() or None
            reactive_npc_ids = _resolve_reactive_npc_ids(chosen_fallback.model_dump(), pack=pack)
            transition_ending_id = str(chosen_fallback.ending_id or "").strip() or None

        _raise_if_stream_aborted()
        _emit_phase(
            on_phase,
            "selection_done",
            {
                "selection_mode": selection_mode,
                "selection_source": selection_source,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "attempted_choice_id": attempted_choice_id,
                "executed_choice_id": executed_choice_id,
            },
        )

        effective_intensity_tier, fallback_base_penalty = _compute_effective_tier(
            raw_llm_tier=int(raw_intensity_tier),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
        state_after, state_delta, range_effects_applied = apply_transition(
            state_before,
            range_effects=range_effects,
            intensity_tier=int(effective_intensity_tier),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
        reaction_effects, reaction_hints = _collect_npc_reaction_effects(
            state_after=state_after,
            reactive_npc_ids=reactive_npc_ids,
            reaction_policy_by_id=reaction_policy_by_id,
            source="fallback" if fallback_used else "choice",
        )
        reaction_hint = reaction_hints[0] if reaction_hints else None
        if reaction_effects:
            state_after, reaction_delta, reaction_applied = apply_range_effects(
                state_after,
                range_effects=reaction_effects,
                intensity_tier=0,
            )
            state_delta = _merge_state_delta(state_delta, reaction_delta)
            range_effects_applied.extend(reaction_applied)

        next_node = node_map.get(next_node_id)
        if next_node is None:
            raise RuntimeNotFoundError("next node missing from pack")

        run_state = state_after.setdefault("run_state", {})
        run_state["selection_retry_count"] = int(selection_retry_count)
        run_state["selection_retry_errors"] = list(selection_retry_errors)
        run_ended = False
        ending_id: str | None = None
        ending_outcome: str | None = None
        ending_camp: str | None = None
        ending_report: dict | None = None

        if fallback_used:
            consecutive_fallback_count = int(run_state.get("consecutive_fallback_count", 0) or 0)
            nudge_tier = _resolve_nudge_tier(
                fallback_reason=fallback_reason,
                consecutive_fallback_count=consecutive_fallback_count,
            )
            run_state["nudge_tier"] = nudge_tier
        else:
            run_state["nudge_tier"] = None
            nudge_tier = None

        if transition_ending_id and transition_ending_id in ending_by_id:
            transition_ending = ending_by_id[transition_ending_id]
            run_ended = True
            ending_id = transition_ending.ending_id
            ending_outcome = transition_ending.outcome
            ending_camp = transition_ending.camp
            run_state["run_ended"] = True
            run_state["ending_id"] = ending_id
            run_state["ending_outcome"] = ending_outcome
            run_state["ending_camp"] = ending_camp
        else:
            run_state["ending_camp"] = None

        threshold = int(pack.fallback_policy.forced_fallback_threshold or settings.story_fallback_guard_default_max_consecutive)
        forced_ending_id = pack.fallback_policy.forced_fallback_ending_id
        forced_ending_triggered = False
        if not run_ended and fallback_used and forced_ending_id:
            consecutive = int(run_state.get("consecutive_fallback_count", 0) or 0)
            if consecutive >= threshold and forced_ending_id in ending_by_id:
                forced = ending_by_id[forced_ending_id]
                run_ended = True
                forced_ending_triggered = True
                ending_id = forced.ending_id
                ending_outcome = forced.outcome
                ending_camp = forced.camp
                run_state["run_ended"] = True
                run_state["ending_id"] = ending_id
                run_state["ending_outcome"] = ending_outcome
                run_state["ending_camp"] = ending_camp

        run_state_delta = state_delta.setdefault("run_state", {})
        if isinstance(run_state_delta, dict):
            run_state_delta["selection_retry_count"] = int(run_state.get("selection_retry_count", 0) or 0)
            run_state_delta["selection_retry_errors"] = list(run_state.get("selection_retry_errors") or [])
            run_state_delta["ending_camp"] = run_state.get("ending_camp")
            run_state_delta["run_ended"] = bool(run_state.get("run_ended", False))
            run_state_delta["ending_id"] = run_state.get("ending_id")
            run_state_delta["ending_outcome"] = run_state.get("ending_outcome")

        if fallback_used:
            reason_fallback = None
            for item in effective_fallbacks:
                if executed_choice_id == f"fallback:{item.fallback_id}":
                    reason_fallback = item
                    break
            if reason_fallback and reason_fallback.mainline_nudge:
                mainline_nudge = reason_fallback.mainline_nudge
            else:
                mainline_nudge = _auto_mainline_nudge(next_node=next_node)

    _raise_if_stream_aborted()
    if run_ended and ending_id and ending_id in ending_by_id:
        _emit_phase(on_phase, "narration_start", {"run_ended": True, "mode": "ending_bundle"})
        ending = ending_by_id[ending_id]
        profile_id = str(ending.prompt_profile_id or "ending_default_v2")
        if profile_id == "ending_default_v1":
            profile_id = "ending_default_v2"
        with db.begin():
            brief = _build_ending_report_brief(
                db,
                session_id=session_db_id,
                state_after=state_after,
                current_step_index=int(run_state.get("step_index", 0) or 0),
                current_executed_choice_id=executed_choice_id,
                current_fallback_reason=fallback_reason,
                current_selection_source=selection_source,
                current_state_delta=state_delta,
            )
        _raise_if_stream_aborted()
        bundle: EndingBundleOutput = llm_boundary.ending_bundle(
            prompt_profile_id=profile_id,
            slots={
                "ending_id": ending.ending_id,
                "ending_outcome": ending.outcome,
                "tone": _resolve_ending_tone(ending_outcome=ending.outcome),
                "epilogue": ending.epilogue,
                "language": settings.story_narration_language,
                "session_stats_json": json.dumps(brief["session_stats"], ensure_ascii=False, separators=(",", ":")),
                "recent_action_beats_json": json.dumps(
                    brief["recent_action_beats"], ensure_ascii=False, separators=(",", ":")
                ),
                "session_stats": brief["session_stats"],
                "recent_action_beats": brief["recent_action_beats"],
            },
        )
        narrative = bundle
        ending_report = bundle.ending_report.model_dump()
        run_state["ending_report"] = ending_report
        _emit_phase(
            on_phase,
            "narration_done",
            {
                "run_ended": True,
                "mode": "ending_bundle",
                "char_count": len(str(narrative.narrative_text or "")),
            },
        )
    elif fallback_used:
        _emit_phase(on_phase, "narration_start", {"run_ended": False, "mode": "fallback_narration"})
        profile_id = "fallback_default_v1"
        for item in effective_fallbacks:
            if executed_choice_id == f"fallback:{item.fallback_id}" and item.prompt_profile_id:
                profile_id = item.prompt_profile_id
                break
        fallback_slots = {
            "scene_from": current_node.get("scene_brief"),
            "scene_to": next_node.get("scene_brief"),
            "fallback_reason": fallback_reason,
            "mainline_nudge": mainline_nudge,
            "nudge_tier": nudge_tier,
            "state_delta_brief": json.dumps(state_delta, ensure_ascii=False),
            "player_input_excerpt": _normalize_player_input(payload.player_input),
            "reaction_hint": reaction_hint,
            "tone": "firm" if nudge_tier == "firm" else "calm",
            "language": settings.story_narration_language,
        }
        narrative_kwargs: dict[str, object] = {
            "prompt_profile_id": profile_id,
            "slots": fallback_slots,
        }
        if on_narrative_delta is not None:
            def _stream_delta(text: str) -> None:
                _raise_if_stream_aborted()
                _emit_narrative_delta(on_narrative_delta, text)

            narrative_kwargs["on_delta"] = _stream_delta
        narrative = llm_boundary.narrative(**narrative_kwargs)
        _raise_if_stream_aborted()
        run_state["ending_report"] = None
        _emit_phase(
            on_phase,
            "narration_done",
            {
                "run_ended": False,
                "mode": "fallback_narration",
                "char_count": len(str(narrative.narrative_text or "")),
            },
        )
    else:
        _emit_phase(on_phase, "narration_start", {"run_ended": False, "mode": "normal_narration"})
        language = str(settings.story_narration_language or "English").strip() or "English"
        system_prompt = (
            f"You are an RPG narration assistant. Write concise second-person {language} narrative text only. "
            "No JSON, no markdown."
        )
        prompt_payload = {
            "story_id": story_id,
            "from_node": current_node["node_id"],
            "to_node": next_node_id,
            "fallback_used": fallback_used,
            "attempted_choice_id": attempted_choice_id,
            "executed_choice_id": executed_choice_id,
            "state_delta": state_delta,
            "reaction_hint": reaction_hint,
            "scene_from": current_node.get("scene_brief"),
            "scene_to": next_node.get("scene_brief"),
            "language": language,
        }
        user_prompt = (
            f"Story narration task. Use concise second-person {language} narration with clear cause->effect. "
            "Return plain text only. Context:"
            + json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))
        )
        narrative_kwargs = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
        if on_narrative_delta is not None:
            def _stream_delta(text: str) -> None:
                _raise_if_stream_aborted()
                _emit_narrative_delta(on_narrative_delta, text)

            narrative_kwargs["on_delta"] = _stream_delta
        narrative = llm_boundary.narrative(**narrative_kwargs)
        _raise_if_stream_aborted()
        run_state["ending_report"] = None
        _emit_phase(
            on_phase,
            "narration_done",
            {
                "run_ended": False,
                "mode": "normal_narration",
                "char_count": len(str(narrative.narrative_text or "")),
            },
        )

    _raise_if_stream_aborted()
    _emit_phase(on_phase, "finalizing", None)
    session_status_after = "ended" if run_ended else "active"
    committed_session_version = expected_session_version + 1
    session_updated_at = utc_now_naive()

    next_node_eval = _evaluate_node_choices(node=next_node, state_json=state_after, npc_defs=npc_defs)
    state_excerpt = {
        "energy": state_after.get("energy"),
        "money": state_after.get("money"),
        "knowledge": state_after.get("knowledge"),
        "affection": state_after.get("affection"),
        "day": state_after.get("day"),
        "slot": state_after.get("slot"),
        "run_state": state_after.get("run_state", {}),
    }
    choices_payload = [
        {
            "id": str(item["choice"].get("choice_id")),
            "text": str(item["choice"].get("text")),
            "available": bool(item["available"]),
            "locked_reason": item["locked_reason"],
        }
        for item in next_node_eval
    ]
    response_payload = {
        "session_status": session_status_after,
        "story_node_id": next_node_id,
        "attempted_choice_id": attempted_choice_id,
        "executed_choice_id": executed_choice_id,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "selection_mode": selection_mode,
        "selection_source": selection_source,
        "mapping_confidence": mapping_confidence,
        "intensity_tier": int(effective_intensity_tier),
        "mainline_nudge": mainline_nudge,
        "nudge_tier": nudge_tier,
        "narrative_text": narrative.narrative_text,
        "choices": choices_payload,
        "range_effects_applied": range_effects_applied,
        "state_excerpt": state_excerpt,
        "run_ended": run_ended,
        "ending_id": ending_id,
        "ending_outcome": ending_outcome,
        "ending_camp": ending_camp,
        "ending_report": ending_report,
        "current_node": {
            "id": str(next_node.get("node_id")),
            "title": str(next_node.get("title")),
            "scene_brief": str(next_node.get("scene_brief")),
            "choices": choices_payload,
        },
    }

    llm_schemas = [_SELECTION_SCHEMA_V3]
    llm_schemas.append("story_ending_bundle_v1" if run_ended else "story_narrative_v1")
    confidence_high, confidence_low = _normalize_confidence_thresholds()

    step_index = int(((state_after.get("run_state") or {}).get("step_index", 0) or 0))
    with db.begin():
        _raise_if_stream_aborted()
        session_update = db.execute(
            sql_update(GameSession)
            .where(
                GameSession.id == session_db_id,
                GameSession.status == "active",
                GameSession.version == expected_session_version,
            )
            .values(
                status=session_status_after,
                story_node_id=next_node_id,
                state_json=state_after,
                updated_at=session_updated_at,
                version=committed_session_version,
            )
        )
        if int(session_update.rowcount or 0) != 1:
            raise SessionStepConflictError(stage="session_update")

        action_log = ActionLog(
            session_id=session_db_id,
            step_index=step_index,
            request_payload_json=payload.model_dump(exclude_none=True),
            selection_result_json={
                "attempted_choice_id": attempted_choice_id,
                "executed_choice_id": executed_choice_id,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "selection_mode": selection_mode,
                "selection_source": selection_source,
                "mapping_confidence": mapping_confidence,
                "intensity_tier": int(effective_intensity_tier),
                "raw_intensity_tier": int(raw_intensity_tier),
                "effective_intensity_tier": int(effective_intensity_tier),
                "fallback_base_penalty": int(fallback_base_penalty),
                "mapping_schema": mapping_schema,
                "selection_decision_code": selection_decision_code,
                "fallback_reason_code": fallback_reason_code,
                "decision_overridden_by_runtime": bool(decision_overridden_by_runtime),
                "runtime_override_reason": runtime_override_reason,
                "gate_blocked": bool(gate_blocked),
                "gate_failed_rules": gate_failed_rules,
                "selection_retry_count": int(selection_retry_count),
                "selection_retry_errors": list(selection_retry_errors),
                "selection_final_attempt": int(selection_final_attempt),
                "run_ended": run_ended,
                "ending_id": ending_id,
                "ending_outcome": ending_outcome,
                "step_index": step_index,
            },
            state_before=state_before,
            state_delta=state_delta,
            state_after=state_after,
            llm_trace_json={
                "provider": "real_auto" if bool(str(settings.llm_api_key or "").strip()) else "fake_auto",
                "schemas": llm_schemas,
                "selection_call_mode": "non_stream_schema",
                "narration_call_mode": "stream_text",
                "ending_call_mode": "non_stream_schema",
            },
            classification_json={
                "fallback_reason": fallback_reason,
                "selection_source": selection_source,
                "mapping_confidence": mapping_confidence,
                "consecutive_fallback_count": int((state_after.get("run_state") or {}).get("consecutive_fallback_count", 0) or 0),
                "forced_ending_triggered": forced_ending_triggered,
                "mainline_nudge_applied": bool(mainline_nudge),
                "nudge_tier": nudge_tier,
                "ending_report_generated": ending_report is not None,
                "ending_report_highlight_count": len((ending_report or {}).get("highlights") or []),
                "ending_report_input_window": "global_stats_plus_recent_12",
                "top_candidates": top_candidates,
                "range_formula": "center + tier * intensity",
                "range_targets_count": len(range_effects_applied),
                "input_policy_flag": bool(input_policy_flag),
                "free_input_llm_required": selection_mode == "free_input",
                "llm_selection_schema": _SELECTION_SCHEMA_V3,
                "confidence_high": confidence_high,
                "confidence_low": confidence_low,
                "selection_decision_code": selection_decision_code,
                "fallback_reason_code": fallback_reason_code,
                "raw_intensity_tier": int(raw_intensity_tier),
                "effective_intensity_tier": int(effective_intensity_tier),
                "fallback_base_penalty": int(fallback_base_penalty),
                "decision_overridden_by_runtime": bool(decision_overridden_by_runtime),
                "runtime_override_reason": runtime_override_reason,
                "mapping_schema": mapping_schema,
                "selection_retry_count": int(selection_retry_count),
                "selection_retry_errors": list(selection_retry_errors),
                "selection_final_attempt": int(selection_final_attempt),
                "reaction_npc_ids": list(reactive_npc_ids),
                "reaction_hint_applied": bool(reaction_hint),
                "session_version_expected": int(expected_session_version),
                "session_version_committed": int(committed_session_version),
                "cas_conflict": False,
                "conflict_stage": None,
                "state_json_size_bytes": len(json.dumps(state_after, ensure_ascii=False)),
            },
        )
        db.add(action_log)
        try:
            db.flush()
        except IntegrityError as exc:
            msg = str(getattr(exc, "orig", exc)).lower()
            is_step_unique_conflict = "uq_action_log_session_step" in msg or (
                "action_logs.session_id, action_logs.step_index" in msg
            )
            if is_step_unique_conflict:
                raise SessionStepConflictError(stage="action_log_unique") from exc
            raise
        _raise_if_stream_aborted()

    return StepResponse.model_validate(response_payload)


def run_step_with_replay_flag(
    db: Session,
    *,
    session_id: str,
    payload: StepRequest,
    idempotency_key: str,
    llm_boundary: LLMBoundary,
    actor_user_id: str | None = None,
    on_phase: StepPhaseHook | None = None,
    on_narrative_delta: NarrativeDeltaHook | None = None,
    abort_check: Callable[[], bool] | None = None,
) -> tuple[StepResponse, bool]:
    request_payload = payload.model_dump(exclude_none=True)
    req_hash = _request_hash(request_payload)

    replay = _prepare_idempotency(
        db,
        session_id=session_id,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        actor_user_id=actor_user_id,
    )
    if isinstance(replay, dict):
        return StepResponse.model_validate(replay), True

    try:
        result = _execute_step(
            db,
            session_id=session_id,
            payload=payload,
            llm_boundary=llm_boundary,
            actor_user_id=actor_user_id,
            on_phase=on_phase,
            on_narrative_delta=on_narrative_delta,
            abort_check=abort_check,
        )
    except SessionStepConflictError:
        _mark_idempotency_failed(
            db,
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            error_code="SESSION_STEP_CONFLICT",
        )
        raise
    except StreamAbortedError:
        _mark_idempotency_failed(
            db,
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            error_code="STREAM_ABORTED",
        )
        raise
    except LLMUnavailableError:
        _mark_idempotency_failed(
            db,
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            error_code="LLM_UNAVAILABLE",
        )
        raise
    except Exception:
        _mark_idempotency_failed(
            db,
            session_id=session_id,
            idempotency_key=idempotency_key,
            request_hash=req_hash,
            error_code="STEP_FAILED",
        )
        raise

    _mark_idempotency_success(
        db,
        session_id=session_id,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        response_json=result.model_dump(),
    )

    return result, False


def run_step(
    db: Session,
    *,
    session_id: str,
    payload: StepRequest,
    idempotency_key: str,
    llm_boundary: LLMBoundary,
    actor_user_id: str | None = None,
    on_phase: StepPhaseHook | None = None,
    on_narrative_delta: NarrativeDeltaHook | None = None,
    abort_check: Callable[[], bool] | None = None,
) -> StepResponse:
    result, _ = run_step_with_replay_flag(
        db,
        session_id=session_id,
        payload=payload,
        idempotency_key=idempotency_key,
        llm_boundary=llm_boundary,
        actor_user_id=actor_user_id,
        on_phase=on_phase,
        on_narrative_delta=on_narrative_delta,
        abort_check=abort_check,
    )
    return result
