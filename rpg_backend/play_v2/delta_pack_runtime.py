from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from uuid import uuid4

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author.normalize import trim_text, unique_preserve
from rpg_backend.author_v2.contracts import (
    BeatDeltaComposePayloadHintBundle,
    BeatDeltaJournalEntry,
    BeatDeltaMicroSimHintBundle,
    BeatDeltaPack,
    BeatDeltaSource,
    BeatDeltaTurnCard,
    CompiledPlayPlan,
    CompiledSegment,
    SuggestionLaneId,
    VoiceAtom,
)
from rpg_backend.play_v2.contracts import UrbanWorldState

_DELTA_PACK_TIMEOUT_SECONDS = 30.0
_DELTA_PACK_EXECUTOR_MAX_WORKERS = 4
_DELTA_PACK_JOURNAL_LIMIT = 12
_DELTA_PACK_MOVE_BOOST_CAP = 0.6

_HIGH_LEVERAGE_MOVES: set[RelationshipMoveFamily] = {
    "accuse",
    "public_reveal",
    "probe_secret",
    "betray",
    "jealousy_trigger",
}
_SOFT_MOVES: set[RelationshipMoveFamily] = {"comfort", "flirt", "ally_with"}


@dataclass
class _DeltaPackFutureEntry:
    snapshot_id: str
    started_at: float
    segment_index: int
    future: Future[BeatDeltaPack]


_delta_pack_lock = Lock()
_delta_pack_executor: ThreadPoolExecutor | None = None
_delta_pack_futures: dict[str, _DeltaPackFutureEntry] = {}


def _executor() -> ThreadPoolExecutor:
    global _delta_pack_executor
    with _delta_pack_lock:
        if _delta_pack_executor is None:
            _delta_pack_executor = ThreadPoolExecutor(
                max_workers=_DELTA_PACK_EXECUTOR_MAX_WORKERS,
                thread_name_prefix="beat-delta-pack",
            )
        return _delta_pack_executor


def _append_journal(
    state: UrbanWorldState,
    *,
    status: str,
    snapshot_id: str,
    source: BeatDeltaSource,
    elapsed_ms: float | None,
    reason: str,
) -> None:
    entry = BeatDeltaJournalEntry(
        snapshot_id=snapshot_id,
        beat_index=state.segment_index,
        segment_id=state.segment_id,
        source=source,
        status=status,  # type: ignore[arg-type]
        created_turn_index=state.turn_index,
        elapsed_ms=round(float(elapsed_ms), 4) if elapsed_ms is not None else None,
        reason=trim_text(reason, 220),
    )
    state.delta_pack_journal = [*state.delta_pack_journal, entry][-_DELTA_PACK_JOURNAL_LIMIT:]


def _fallback_render_cues(segment: CompiledSegment) -> list[str]:
    role = segment.segment_role
    if role in {"reveal", "terminal"}:
        return ["style:impact:rising", "style:cost:landed", "style:bomb:public_drop"]
    return ["style:impact:rising", f"style:segment:{role}", "style:cadence:slow_press"]


def _target_bias_for_lane(
    *,
    lane_id: SuggestionLaneId,
    segment: CompiledSegment,
    state: UrbanWorldState,
    plan: CompiledPlayPlan,
) -> list[str]:
    current_route = (state.current_route_target_id or "").strip()
    if current_route:
        return [current_route]
    if lane_id == "relationship":
        preferred = [item for item in plan.route_target_ids if item in set(segment.focus_target_ids + segment.rival_target_ids)]
        return preferred[:2]
    if lane_id == "burst":
        return list(unique_preserve(segment.rival_target_ids + segment.focus_target_ids))[:2]
    return list(unique_preserve(segment.focus_target_ids + segment.rival_target_ids))[:2]


def _move_priority_boosts(segment: CompiledSegment, state: UrbanWorldState) -> dict[RelationshipMoveFamily, float]:
    move_boosts: dict[RelationshipMoveFamily, float] = {}
    for index, move_family in enumerate(segment.move_priorities):
        boost = max(0.0, 0.22 - 0.05 * float(index))
        if move_family in _HIGH_LEVERAGE_MOVES and (state.scene_heat >= 3 or state.secret_exposure >= 2):
            boost += 0.1
        if move_family in _SOFT_MOVES and state.scene_heat <= 2 and state.secret_exposure <= 1:
            boost += 0.06
        if segment.segment_role in {"reveal", "terminal"} and move_family in {"public_reveal", "betray", "accuse"}:
            boost += 0.08
        move_boosts[move_family] = round(min(boost, _DELTA_PACK_MOVE_BOOST_CAP), 4)
    return move_boosts


def _voice_weight_bias_for_segment(
    *,
    plan: CompiledPlayPlan,
    segment: CompiledSegment,
    state: UrbanWorldState,
) -> dict[str, dict[str, float]]:
    active_ids = set(unique_preserve([*state.active_character_ids, *segment.focus_target_ids, *segment.rival_target_ids]))
    by_character: dict[str, dict[str, float]] = {}
    for character_id in active_ids:
        atoms = list(plan.voice_atoms_by_character.get(character_id) or [])
        if not atoms:
            continue
        per_character: dict[str, float] = {}
        for atom in atoms[:5]:
            boost = 0.05
            if atom.segment_role == segment.segment_role:
                boost += 0.14
            if atom.segment_role in {"reveal", "terminal"} and segment.segment_role in {"pressure", "reversal"}:
                boost += 0.03
            per_character[atom.atom_id] = round(min(boost, 0.32), 4)
        if per_character:
            by_character[character_id] = per_character
    return by_character


def _build_turn_card(*, segment: CompiledSegment, state: UrbanWorldState, card_kind: str) -> BeatDeltaTurnCard:
    lane_focus = [lane.lane_id for lane in segment.suggestion_lanes[:3]]
    move_focus = list(segment.move_priorities[:4])
    voice_focus = list(unique_preserve([*segment.focus_target_ids, *segment.rival_target_ids, *state.active_character_ids]))[:3]
    if card_kind == "burst":
        lane_focus = list(unique_preserve(["burst", *lane_focus]))[:3]
        move_focus = list(
            unique_preserve(
                [
                    *(move for move in segment.move_priorities if move in {"public_reveal", "betray", "accuse", "probe_secret"}),
                    *move_focus,
                ]
            )
        )[:4]
        directive = "关键回合优先放大可见代价与站位变化，动作要能被场内外同时读懂。"
    else:
        if state.scene_heat <= 2 and segment.segment_role in {"opening", "misread", "pressure"}:
            lane_focus = list(unique_preserve(["side", "relationship", *lane_focus]))[:3]
        directive = "普通回合优先可执行推进，保留后手空间，不提前透支爆点。"
    return BeatDeltaTurnCard(
        directive=trim_text(directive, 220),
        lane_focus=lane_focus,
        move_focus=move_focus,
        voice_focus_character_ids=voice_focus,
    )


def _build_micro_sim_hint_bundle(*, plan: CompiledPlayPlan, segment: CompiledSegment, state: UrbanWorldState) -> BeatDeltaMicroSimHintBundle:
    preferred_actor_ids = [
        character_id
        for character_id in state.active_character_ids
        if character_id not in segment.focus_target_ids[:1]
    ][:3]
    reason_family_hints: dict[str, str] = {}
    action_family_hints: dict[str, str] = {}
    members_by_id = {member.character_id: member for member in plan.cast}
    for character_id in preferred_actor_ids:
        member = members_by_id.get(character_id)
        if member is None:
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
            reason_family_hints[character_id] = "old_debt"
            action_family_hints[character_id] = "debt_play"
        elif any(token in strategy_hint for token in ("shield", "contain", "silent", "low_profile")):
            reason_family_hints[character_id] = "self_preserve"
            action_family_hints[character_id] = "self_preserve"
        elif any(token in strategy_hint for token in ("vote", "record", "edge", "counter")):
            reason_family_hints[character_id] = "loss_position"
            action_family_hints[character_id] = "strike"
        else:
            reason_family_hints[character_id] = "mixed"
            action_family_hints[character_id] = "test_water"
    return BeatDeltaMicroSimHintBundle(
        preferred_actor_ids=preferred_actor_ids,
        reason_family_hints=reason_family_hints,
        action_family_hints=action_family_hints,
        summary=trim_text("优先看 supporting 角色是否先手表态，再决定是否升级公开冲突。", 220),
    )


def _build_compose_payload_hint_bundle(*, segment: CompiledSegment) -> BeatDeltaComposePayloadHintBundle:
    bucket_ids: list[str] = []
    for item in list(segment.template_tone_example_lines) + list(segment.template_tone_scene_examples):
        bucket_id = str(getattr(item, "bucket_id", "") or "").strip()
        if bucket_id:
            bucket_ids.append(bucket_id)
    key_cues = list(
        unique_preserve(
            [
                *segment.render_cues,
                trim_text(segment.public_pressure_cue, 80),
                trim_text(segment.private_pressure_cue, 80),
            ]
        )
    )[:6]
    return BeatDeltaComposePayloadHintBundle(
        style_case_bucket_ids=list(unique_preserve(bucket_ids))[:4],
        key_cues=key_cues,
        cue_summary=trim_text(segment.progression_rule_summary, 220),
    )


def build_next_delta_pack_deterministic(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    segment_index: int,
    snapshot_id: str | None = None,
    source: BeatDeltaSource = "runtime_rollover",
) -> BeatDeltaPack:
    resolved_segment_index = min(max(int(segment_index), 0), len(plan.segments) - 1)
    segment = plan.segments[resolved_segment_index]
    lane_objective_bias_by_lane: dict[SuggestionLaneId, str] = {}
    lane_target_bias_by_lane: dict[SuggestionLaneId, list[str]] = {}
    for lane in segment.suggestion_lanes[:3]:
        lane_objective_bias_by_lane[lane.lane_id] = trim_text(lane.objective, 220)
        lane_target_bias_by_lane[lane.lane_id] = _target_bias_for_lane(
            lane_id=lane.lane_id,
            segment=segment,
            state=state,
            plan=plan,
        )
    render_cues = list(unique_preserve([*segment.render_cues, *_fallback_render_cues(segment)]))[:5]
    return BeatDeltaPack(
        snapshot_id=snapshot_id or f"delta_pack_{uuid4().hex[:12]}",
        source=source,
        beat_index=resolved_segment_index,
        segment_id=segment.segment_id,
        segment_role=segment.segment_role,
        move_priority_boosts=_move_priority_boosts(segment, state),
        progression_bias_summary=trim_text(segment.progression_rule_summary, 220),
        render_cue_bias=render_cues,
        lane_objective_bias_by_lane=lane_objective_bias_by_lane,
        lane_target_bias_by_lane=lane_target_bias_by_lane,
        voice_atom_weight_bias_by_character=_voice_weight_bias_for_segment(
            plan=plan,
            segment=segment,
            state=state,
        ),
        normal_turn_card=_build_turn_card(segment=segment, state=state, card_kind="normal"),
        burst_turn_card=_build_turn_card(segment=segment, state=state, card_kind="burst"),
        micro_sim_hint_bundle=_build_micro_sim_hint_bundle(
            plan=plan,
            segment=segment,
            state=state,
        ),
        compose_payload_hint_bundle=_build_compose_payload_hint_bundle(segment=segment),
    )


def schedule_next_beat_delta_pack(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
) -> dict[str, int | float | str | bool]:
    snapshot_id = f"delta_pack_{state.session_id}_{uuid4().hex[:10]}"
    segment_index = min(state.segment_index, len(plan.segments) - 1)
    scheduled_state = state.model_copy(deep=True)
    future = _executor().submit(
        build_next_delta_pack_deterministic,
        plan=plan,
        state=scheduled_state,
        segment_index=segment_index,
        snapshot_id=snapshot_id,
        source="runtime_rollover",
    )
    with _delta_pack_lock:
        stale = _delta_pack_futures.get(state.session_id)
        if stale is not None:
            stale.future.cancel()
        _delta_pack_futures[state.session_id] = _DeltaPackFutureEntry(
            snapshot_id=snapshot_id,
            started_at=perf_counter(),
            segment_index=segment_index,
            future=future,
        )
    state.delta_pack_snapshot_id = snapshot_id
    state.delta_pack_job_status = "scheduled"
    _append_journal(
        state,
        status="scheduled",
        snapshot_id=snapshot_id,
        source="runtime_rollover",
        elapsed_ms=0.0,
        reason="segment_advanced",
    )
    return {
        "beat_delta_pack_applied": False,
        "beat_delta_pack_source": "",
        "beat_delta_pack_snapshot_id": snapshot_id,
        "beat_delta_pack_job_ms": 0.0,
        "beat_delta_pack_job_status": "scheduled",
    }


def _try_apply_pending_pack(state: UrbanWorldState, *, current_segment_id: str) -> tuple[bool, str, str]:
    pending = state.pending_beat_delta_pack
    if pending is None:
        return False, "none", state.delta_pack_job_status
    if pending.snapshot_id != state.delta_pack_snapshot_id:
        state.pending_beat_delta_pack = None
        state.delta_pack_job_status = "ignored"
        _append_journal(
            state,
            status="ignored",
            snapshot_id=pending.snapshot_id,
            source=pending.source,
            elapsed_ms=None,
            reason="snapshot_mismatch",
        )
        return False, "none", "ignored"
    if pending.segment_id != current_segment_id:
        return False, pending.source, "ready"
    state.active_beat_delta_pack = pending
    state.pending_beat_delta_pack = None
    state.delta_pack_job_status = "applied"
    _append_journal(
        state,
        status="applied",
        snapshot_id=pending.snapshot_id,
        source=pending.source,
        elapsed_ms=None,
        reason="pending_applied",
    )
    return True, pending.source, "applied"


def poll_and_apply_pending_delta_pack(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
) -> dict[str, int | float | str | bool]:
    current_segment_id = plan.segments[min(state.segment_index, len(plan.segments) - 1)].segment_id
    applied, source, status = _try_apply_pending_pack(state, current_segment_id=current_segment_id)
    diagnostics: dict[str, int | float | str | bool] = {
        "beat_delta_pack_applied": bool(applied),
        "beat_delta_pack_source": source if applied else "",
        "beat_delta_pack_snapshot_id": state.delta_pack_snapshot_id,
        "beat_delta_pack_job_ms": 0.0,
        "beat_delta_pack_job_status": status,
    }
    if applied:
        return diagnostics

    entry: _DeltaPackFutureEntry | None = None
    with _delta_pack_lock:
        cached = _delta_pack_futures.get(state.session_id)
        if cached is not None:
            entry = cached
    if entry is None:
        diagnostics["beat_delta_pack_job_status"] = state.delta_pack_job_status
        return diagnostics

    elapsed_ms = round((perf_counter() - entry.started_at) * 1000, 4)
    diagnostics["beat_delta_pack_job_ms"] = elapsed_ms
    if not entry.future.done():
        if elapsed_ms <= _DELTA_PACK_TIMEOUT_SECONDS * 1000:
            diagnostics["beat_delta_pack_job_status"] = "scheduled"
            state.delta_pack_job_status = "scheduled"
            return diagnostics
        entry.future.cancel()
        with _delta_pack_lock:
            _delta_pack_futures.pop(state.session_id, None)
        state.delta_pack_job_status = "timeout"
        _append_journal(
            state,
            status="timeout",
            snapshot_id=entry.snapshot_id,
            source="runtime_rollover",
            elapsed_ms=elapsed_ms,
            reason=f"timeout:{_DELTA_PACK_TIMEOUT_SECONDS:.0f}s",
        )
        diagnostics["beat_delta_pack_job_status"] = "timeout"
        return diagnostics

    with _delta_pack_lock:
        _delta_pack_futures.pop(state.session_id, None)
    try:
        generated_pack = entry.future.result()
    except Exception as exc:  # noqa: BLE001
        state.delta_pack_job_status = "failed"
        _append_journal(
            state,
            status="failed",
            snapshot_id=entry.snapshot_id,
            source="runtime_rollover",
            elapsed_ms=elapsed_ms,
            reason=str(exc)[:220],
        )
        diagnostics["beat_delta_pack_job_status"] = "failed"
        return diagnostics

    if generated_pack.snapshot_id != state.delta_pack_snapshot_id:
        state.delta_pack_job_status = "ignored"
        _append_journal(
            state,
            status="ignored",
            snapshot_id=generated_pack.snapshot_id,
            source=generated_pack.source,
            elapsed_ms=elapsed_ms,
            reason="stale_snapshot",
        )
        diagnostics["beat_delta_pack_job_status"] = "ignored"
        diagnostics["beat_delta_pack_source"] = generated_pack.source
        return diagnostics

    state.pending_beat_delta_pack = generated_pack
    state.delta_pack_job_status = "ready"
    _append_journal(
        state,
        status="ready",
        snapshot_id=generated_pack.snapshot_id,
        source=generated_pack.source,
        elapsed_ms=elapsed_ms,
        reason="ready",
    )
    diagnostics["beat_delta_pack_job_status"] = "ready"
    diagnostics["beat_delta_pack_source"] = generated_pack.source
    applied, source, status = _try_apply_pending_pack(state, current_segment_id=current_segment_id)
    diagnostics["beat_delta_pack_applied"] = bool(applied)
    diagnostics["beat_delta_pack_source"] = source if applied else diagnostics["beat_delta_pack_source"]
    diagnostics["beat_delta_pack_job_status"] = status
    return diagnostics


def resolve_segment_with_delta(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
) -> CompiledSegment:
    segment = plan.segments[min(state.segment_index, len(plan.segments) - 1)]
    pack = state.active_beat_delta_pack
    if pack.segment_id != segment.segment_id:
        return segment

    rank_map = {
        move_family: index
        for index, move_family in enumerate(segment.move_priorities)
    }
    move_priorities = sorted(
        segment.move_priorities,
        key=lambda move_family: (
            float(pack.move_priority_boosts.get(move_family, 0.0)),
            -rank_map.get(move_family, 99),
        ),
        reverse=True,
    )
    progression_summary = trim_text(pack.progression_bias_summary or segment.progression_rule_summary, 220)
    render_cues = list(unique_preserve([*pack.render_cue_bias, *segment.render_cues]))[:5]

    suggestion_lanes = []
    for lane in segment.suggestion_lanes:
        objective = trim_text(pack.lane_objective_bias_by_lane.get(lane.lane_id, lane.objective), 220)
        lane_target_bias = list(pack.lane_target_bias_by_lane.get(lane.lane_id, []))
        target_priority_ids = list(unique_preserve([*lane_target_bias, *lane.target_priority_ids]))[:3]
        suggestion_lanes.append(
            lane.model_copy(
                update={
                    "objective": objective,
                    "target_priority_ids": target_priority_ids,
                }
            )
        )
    return segment.model_copy(
        update={
            "move_priorities": move_priorities,
            "progression_rule_summary": progression_summary,
            "render_cues": render_cues,
            "suggestion_lanes": suggestion_lanes or segment.suggestion_lanes,
        }
    )


def effective_voice_atom_weight(*, state: UrbanWorldState, character_id: str, atom: VoiceAtom) -> float:
    pack = state.active_beat_delta_pack
    weight_delta = float(
        pack.voice_atom_weight_bias_by_character.get(character_id, {}).get(atom.atom_id, 0.0)
    )
    return max(0.05, min(1.0, float(atom.weight) + weight_delta))


def clear_delta_pack_future(session_id: str) -> None:
    with _delta_pack_lock:
        entry = _delta_pack_futures.pop(session_id, None)
    if entry is not None:
        entry.future.cancel()
