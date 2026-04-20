from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

from rpg_backend.author.contracts import BeatSpec
from rpg_backend.author.normalize import slugify, trim_ellipsis, unique_preserve
from rpg_backend.play.contracts import (
    PlayCostLedger,
    PlayEnding,
    PlayFeedbackSnapshot,
    PlayLedgerSnapshot,
    PlayPlan,
    PlayProtagonist,
    PlayRelationshipStateSnapshot,
    PlayRelationshipTargetState,
    PlayResolutionEffect,
    PlaySessionProgress,
    PlaySessionSnapshot,
    PlayStateBar,
    PlaySuggestedAction,
    PlaySuccessLedger,
    PlayTurnIntentDraft,
)
from rpg_backend.play.runtime import PlaySessionState


RelationshipSource = Literal["heuristic", "skipped"]

_PHASE_DEFAULT_MOVES: dict[str, tuple[str, ...]] = {
    "hook": ("flirt", "probe_secret", "comfort"),
    "misread": ("deflect", "probe_secret", "flirt"),
    "pressure": ("accuse", "ally_with", "jealousy_trigger"),
    "reveal": ("public_reveal", "private_confession", "accuse"),
    "lock": ("ally_with", "betray", "private_confession"),
}

_MOVE_LABELS: dict[str, tuple[str, str]] = {
    "flirt": ("试探暧昧", "你靠近 {target}，试着让这段关系先朝你偏一点。"),
    "probe_secret": ("逼近秘密", "你不动声色地逼问 {target}，想让真正的秘密先松动。"),
    "comfort": ("给出安抚", "你先稳住 {target} 的情绪，试着换取更真实的信任。"),
    "deflect": ("转移锋芒", "你避开正面回应，把场面先从你身上引开。"),
    "accuse": ("正面发难", "你把矛头直接指向 {target}，逼他们当场表态。"),
    "ally_with": ("拉拢结盟", "你把条件摆到桌面上，试着让 {target} 和你站到同一边。"),
    "betray": ("反手背刺", "你在最关键的一步突然转向，让 {target} 失去原本的判断。"),
    "public_reveal": ("当众曝光", "你把秘密丢到所有人面前，逼局势在众目睽睽下失控。"),
    "private_confession": ("私下袒露", "你在无人的地方对 {target} 说出那句最不该说的话。"),
    "jealousy_trigger": ("引爆嫉妒", "你故意让气氛偏向另一个人，看谁先失控。"),
}

_MOVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "flirt": ("暧昧", "靠近", "撩", "试探", "flirt", "tease"),
    "probe_secret": ("秘密", "真相", "逼问", "套话", "secret", "probe"),
    "comfort": ("安慰", "安抚", "抱住", "哄", "comfort", "reassure"),
    "deflect": ("岔开", "转移", "敷衍", "回避", "deflect", "avoid"),
    "accuse": ("质问", "揭穿", "指责", "发难", "accuse", "confront"),
    "ally_with": ("结盟", "合作", "站队", "一起", "ally", "deal"),
    "betray": ("背叛", "出卖", "反手", "betray", "turn on"),
    "public_reveal": ("当众", "公开", "热搜", "曝光", "发布会", "public", "reveal"),
    "private_confession": ("表白", "坦白", "承认", "confession", "confess"),
    "jealousy_trigger": ("吃醋", "嫉妒", "刺激", "jealous", "jealousy"),
}

_PUBLIC_MARKERS = ("当众", "公开", "记者", "发布会", "热搜", "晚宴", "public", "press", "gala")
_PRIVATE_MARKERS = ("私下", "单独", "走廊", "房间", "深夜", "private", "alone")


@dataclass(frozen=True)
class RelationshipInterpretTurnResult:
    intent: PlayTurnIntentDraft
    source: RelationshipSource = "heuristic"
    attempts: int = 1
    failure_reason: str | None = None
    response_id: str | None = None
    usage: dict[str, int | str] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationshipJudgeResult:
    proposed_ending_id: str | None = None
    source: RelationshipSource = "heuristic"
    attempts: int = 1
    failure_reason: str | None = None
    response_id: str | None = None
    usage: dict[str, int | str] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationshipRenderResult:
    narration: str
    suggestions: list[PlaySuggestedAction]
    source: Literal["fallback", "heuristic"] = "heuristic"
    attempts: int = 1
    failure_reason: str | None = None
    response_id: str | None = None
    usage: dict[str, int | str] = field(default_factory=dict)


def is_relationship_drama_plan(plan: PlayPlan) -> bool:
    return plan.story_mode == "relationship_drama"


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _current_beat(plan: PlayPlan, state: PlaySessionState) -> BeatSpec:
    index = min(max(state.beat_index, 0), len(plan.beats) - 1)
    return plan.beats[index]


def _relationship_targets(plan: PlayPlan) -> list[str]:
    explicit = [item for item in list(plan.route_target_ids or []) if item and item != plan.protagonist_npc_id]
    if explicit:
        return unique_preserve(explicit)[:5]
    return [member.npc_id for member in plan.cast if member.npc_id != plan.protagonist_npc_id][:5]


def _cast_name(plan: PlayPlan, character_id: str | None) -> str:
    if not character_id:
        return "对方"
    for member in plan.cast:
        if member.npc_id == character_id:
            return member.name
    return character_id


def _relationship_goal(beat: BeatSpec) -> int:
    return int(beat.required_heat or beat.progress_required or 2)


def available_relationship_move_families(plan: PlayPlan, state: PlaySessionState) -> list[str]:
    beat = _current_beat(plan, state)
    if beat.preferred_move_families:
        candidates = [item for item in beat.preferred_move_families if item not in set(beat.blocked_move_families)]
    else:
        candidates = [item for item in _PHASE_DEFAULT_MOVES.get(str(beat.phase or "hook"), _PHASE_DEFAULT_MOVES["hook"])]
    ordered = unique_preserve(candidates)
    if len(ordered) < 3:
        ordered.extend(item for item in _PHASE_DEFAULT_MOVES.get(str(beat.phase or "hook"), _PHASE_DEFAULT_MOVES["hook"]) if item not in ordered)
    return ordered[:3]


def build_relationship_suggested_actions(plan: PlayPlan, state: PlaySessionState) -> list[PlaySuggestedAction]:
    if state.status != "active":
        return []
    target_id = state.current_route_target_id or (_relationship_targets(plan)[0] if _relationship_targets(plan) else None)
    target_name = _cast_name(plan, target_id)
    suggestions: list[PlaySuggestedAction] = []
    for index, move_family in enumerate(available_relationship_move_families(plan, state), start=1):
        label, prompt = _MOVE_LABELS[move_family]
        suggestions.append(
            PlaySuggestedAction(
                suggestion_id=f"{slugify(move_family)}_{index}",
                label=label,
                prompt=trim_ellipsis(prompt.format(target=target_name), 220),
            )
        )
    return suggestions[:3]


def build_initial_relationship_session_state(plan: PlayPlan, *, session_id: str) -> PlaySessionState:
    target_ids = _relationship_targets(plan)
    beat = plan.beats[0]
    current_target_id = (list(beat.focus_character_ids or []) + target_ids[:1])[0] if (list(beat.focus_character_ids or []) + target_ids[:1]) else None
    relationship_values = {
        character_id: {
            "affection": 0,
            "trust": 0,
            "tension": 1,
            "suspicion": 1,
            "dependency": 0,
        }
        for character_id in target_ids
    }
    state = PlaySessionState(
        session_id=session_id,
        story_id=plan.story_id,
        status="active",
        turn_index=0,
        beat_index=0,
        beat_progress=0,
        beat_detours_used=0,
        axis_values={},
        stance_values={},
        flag_values={},
        success_ledger={"proof_progress": 0, "coalition_progress": 0, "order_progress": 0, "settlement_progress": 0},
        cost_ledger={"public_cost": 0, "relationship_cost": 0, "procedural_cost": 0, "coercion_cost": 0},
        narration=plan.opening_narration,
        scene_heat=1,
        public_image=0,
        secret_exposure=0,
        route_lock=0,
        current_route_target_id=current_target_id,
        relationship_values=relationship_values,
    )
    state.suggested_actions = build_relationship_suggested_actions(plan, state)
    return state


def build_relationship_state_bars(plan: PlayPlan, state: PlaySessionState) -> list[PlayStateBar]:
    bars = [
        PlayStateBar(bar_id="scene_heat", label="场面热度", category="global", current_value=state.scene_heat, min_value=0, max_value=6),
        PlayStateBar(bar_id="public_image", label="公众风评", category="global", current_value=state.public_image, min_value=-3, max_value=3),
        PlayStateBar(bar_id="secret_exposure", label="秘密暴露", category="global", current_value=state.secret_exposure, min_value=0, max_value=6),
        PlayStateBar(bar_id="route_lock", label="路线锁定", category="global", current_value=state.route_lock, min_value=0, max_value=6),
    ]
    if state.current_route_target_id:
        target_name = _cast_name(plan, state.current_route_target_id)
        values = state.relationship_values.get(state.current_route_target_id, {})
        bars.extend(
            [
                PlayStateBar(bar_id=f"{state.current_route_target_id}:affection", label=f"{target_name}·亲密", category="relationship", current_value=int(values.get("affection", 0)), min_value=-3, max_value=6),
                PlayStateBar(bar_id=f"{state.current_route_target_id}:trust", label=f"{target_name}·信任", category="relationship", current_value=int(values.get("trust", 0)), min_value=-3, max_value=6),
                PlayStateBar(bar_id=f"{state.current_route_target_id}:tension", label=f"{target_name}·拉扯", category="relationship", current_value=int(values.get("tension", 0)), min_value=0, max_value=6),
                PlayStateBar(bar_id=f"{state.current_route_target_id}:suspicion", label=f"{target_name}·怀疑", category="relationship", current_value=int(values.get("suspicion", 0)), min_value=0, max_value=6),
            ]
        )
    return bars


def build_relationship_state_snapshot(plan: PlayPlan, state: PlaySessionState) -> PlayRelationshipStateSnapshot:
    targets = [
        PlayRelationshipTargetState(
            character_id=member.npc_id,
            name=member.name,
            affection=int(state.relationship_values.get(member.npc_id, {}).get("affection", 0)),
            trust=int(state.relationship_values.get(member.npc_id, {}).get("trust", 0)),
            tension=int(state.relationship_values.get(member.npc_id, {}).get("tension", 0)),
            suspicion=int(state.relationship_values.get(member.npc_id, {}).get("suspicion", 0)),
            dependency=int(state.relationship_values.get(member.npc_id, {}).get("dependency", 0)),
            is_route_focus=member.npc_id == state.current_route_target_id,
        )
        for member in plan.cast
        if member.npc_id != plan.protagonist_npc_id
    ]
    return PlayRelationshipStateSnapshot(
        scene_heat=state.scene_heat,
        public_image=state.public_image,
        secret_exposure=state.secret_exposure,
        route_lock=state.route_lock,
        current_route_target_id=state.current_route_target_id,
        targets=targets,
    )


def _relationship_feedback_snapshot(state: PlaySessionState) -> PlayFeedbackSnapshot:
    return PlayFeedbackSnapshot(
        ledgers=PlayLedgerSnapshot(
            success=PlaySuccessLedger(proof_progress=0, coalition_progress=0, order_progress=0, settlement_progress=0),
            cost=PlayCostLedger(public_cost=0, relationship_cost=0, procedural_cost=0, coercion_cost=0),
        ),
        last_turn_axis_deltas={},
        last_turn_stance_deltas={},
        last_turn_global_deltas=dict(state.last_turn_global_deltas),
        last_turn_relationship_deltas={key: dict(value) for key, value in state.last_turn_relationship_deltas.items()},
        last_turn_tags=list(state.last_turn_tags),
        last_turn_consequences=list(state.last_turn_consequences),
        last_turn_revealed_secret_ids=list(state.last_turn_revealed_secret_ids),
    )


def _relationship_progress(plan: PlayPlan, state: PlaySessionState) -> PlaySessionProgress:
    total_beats = max(len(plan.beats), 1)
    beat = _current_beat(plan, state)
    current_goal = max(1, _relationship_goal(beat))
    completed_beats = len(plan.beats) if state.status == "completed" else min(state.beat_index, len(plan.beats))
    current_progress = current_goal if state.status == "completed" else min(state.beat_progress, current_goal)
    completion_ratio = min((completed_beats + (current_progress / current_goal if state.status != "completed" else 0.0)) / total_beats, 1.0)
    return PlaySessionProgress(
        completed_beats=completed_beats,
        total_beats=total_beats,
        current_beat_progress=current_progress,
        current_beat_goal=current_goal,
        turn_index=state.turn_index,
        max_turns=plan.max_turns,
        completion_ratio=round(completion_ratio, 3),
        display_percent=min(100, round(completion_ratio * 100)),
    )


def build_relationship_session_snapshot(plan: PlayPlan, state: PlaySessionState) -> PlaySessionSnapshot:
    beat = _current_beat(plan, state)
    return PlaySessionSnapshot(
        session_id=state.session_id,
        story_id=state.story_id,
        story_mode=plan.story_mode,
        story_shell_id=plan.story_shell_id,
        status=state.status,  # type: ignore[arg-type]
        turn_index=state.turn_index,
        beat_index=state.beat_index + 1,
        beat_title=beat.title,
        story_title=plan.story_title,
        narration=state.narration,
        protagonist=PlayProtagonist.model_validate(plan.protagonist.model_dump(mode="json")),
        feedback=_relationship_feedback_snapshot(state),
        progress=_relationship_progress(plan, state),
        support_surfaces=None,
        state_bars=build_relationship_state_bars(plan, state),
        current_route_target_id=state.current_route_target_id,
        relationship_state=build_relationship_state_snapshot(plan, state),
        suggested_actions=list(state.suggested_actions),
        ending=state.ending,
    )


def _resolve_target_character_ids(text: str, plan: PlayPlan, state: PlaySessionState) -> list[str]:
    lowered = text.casefold()
    matched: list[str] = []
    for member in plan.cast:
        if member.npc_id == plan.protagonist_npc_id:
            continue
        if member.name.casefold() in lowered:
            matched.append(member.npc_id)
    if matched:
        return matched[:3]
    beat = _current_beat(plan, state)
    fallback = [*list(beat.focus_character_ids or []), *list(beat.rival_character_ids or []), *list(plan.route_target_ids or [])]
    if state.current_route_target_id:
        fallback.insert(0, state.current_route_target_id)
    return unique_preserve([item for item in fallback if item])[:3]


def heuristic_relationship_turn_intent(
    *,
    input_text: str,
    plan: PlayPlan,
    state: PlaySessionState,
    selected_action: PlaySuggestedAction | None = None,
) -> RelationshipInterpretTurnResult:
    text = " ".join([selected_action.prompt if selected_action is not None else "", input_text]).casefold()
    candidates = available_relationship_move_families(plan, state)
    scored = {
        move_family: sum(1 for keyword in _MOVE_KEYWORDS.get(move_family, ()) if keyword.casefold() in text)
        for move_family in candidates
    }
    move_family = max(scored, key=lambda item: (scored[item], -candidates.index(item))) if candidates else "probe_secret"
    if scored.get(move_family, 0) == 0 and candidates:
        move_family = candidates[0]
    if any(marker in text for marker in _PUBLIC_MARKERS):
        scene_frame: Literal["private", "semi_public", "public"] = "public"
    elif any(marker in text for marker in _PRIVATE_MARKERS):
        scene_frame = "private"
    else:
        scene_frame = "semi_public"
    intimacy_risk: Literal["low", "medium", "high"]
    if move_family in {"betray", "public_reveal", "accuse"}:
        intimacy_risk = "high"
    elif move_family in {"comfort", "flirt", "private_confession"}:
        intimacy_risk = "low"
    else:
        intimacy_risk = "medium"
    target_character_ids = _resolve_target_character_ids(text, plan, state)
    return RelationshipInterpretTurnResult(
        intent=PlayTurnIntentDraft(
            move_family=move_family,  # type: ignore[arg-type]
            target_character_ids=target_character_ids,
            intimacy_risk=intimacy_risk,
            scene_frame=scene_frame,
            intent_summary=trim_ellipsis(input_text, 220),
            tactic_summary=trim_ellipsis(input_text, 220),
        )
    )


def _next_secret_id(plan: PlayPlan, state: PlaySessionState, beat: BeatSpec) -> str | None:
    for secret_id in [*list(beat.required_secret_ids or []), *list(beat.reveal_candidates or [])]:
        if secret_id and secret_id not in state.known_secret_ids:
            return secret_id
    for truth in plan.truths:
        if truth.truth_id not in state.known_secret_ids:
            return truth.truth_id
    return None


def _apply_relationship_delta(state: PlaySessionState, character_id: str, field_name: str, delta: int) -> int:
    values = state.relationship_values.setdefault(character_id, {"affection": 0, "trust": 0, "tension": 1, "suspicion": 1, "dependency": 0})
    minimum = -3 if field_name in {"affection", "trust"} else 0
    maximum = 6
    current = int(values.get(field_name, 0))
    updated = max(minimum, min(maximum, current + delta))
    values[field_name] = updated
    return updated - current


def apply_relationship_turn_resolution(
    *,
    plan: PlayPlan,
    state: PlaySessionState,
    intent: PlayTurnIntentDraft,
) -> PlayResolutionEffect:
    move_family = str(intent.move_family or "probe_secret")
    target_ids = list(intent.target_character_ids or [])
    primary_target_id = target_ids[0] if target_ids else state.current_route_target_id
    if primary_target_id:
        state.current_route_target_id = primary_target_id
    global_changes: dict[str, int] = {}
    relationship_changes: dict[str, dict[str, int]] = {}
    revealed_secret_ids: list[str] = []

    def _bump_global(field_name: str, delta: int, *, minimum: int = 0, maximum: int = 6) -> None:
        current = int(getattr(state, field_name))
        updated = max(minimum, min(maximum, current + delta))
        setattr(state, field_name, updated)
        applied = updated - current
        if applied:
            global_changes[field_name] = applied

    if move_family == "flirt" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "affection": _apply_relationship_delta(state, primary_target_id, "affection", 2),
            "tension": _apply_relationship_delta(state, primary_target_id, "tension", 1),
        }
        _bump_global("scene_heat", 1)
        _bump_global("route_lock", 1)
    elif move_family == "probe_secret" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "suspicion": _apply_relationship_delta(state, primary_target_id, "suspicion", 1),
            "tension": _apply_relationship_delta(state, primary_target_id, "tension", 1),
        }
        _bump_global("secret_exposure", 1)
        _bump_global("scene_heat", 1)
    elif move_family == "comfort" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "trust": _apply_relationship_delta(state, primary_target_id, "trust", 2),
            "affection": _apply_relationship_delta(state, primary_target_id, "affection", 1),
            "tension": _apply_relationship_delta(state, primary_target_id, "tension", -1),
        }
        _bump_global("route_lock", 1)
    elif move_family == "deflect" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "suspicion": _apply_relationship_delta(state, primary_target_id, "suspicion", 1),
            "trust": _apply_relationship_delta(state, primary_target_id, "trust", -1),
        }
        _bump_global("public_image", 1, minimum=-3, maximum=3)
    elif move_family == "accuse" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "trust": _apply_relationship_delta(state, primary_target_id, "trust", -2),
            "tension": _apply_relationship_delta(state, primary_target_id, "tension", 2),
            "suspicion": _apply_relationship_delta(state, primary_target_id, "suspicion", 1),
        }
        _bump_global("scene_heat", 2)
    elif move_family == "ally_with" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "trust": _apply_relationship_delta(state, primary_target_id, "trust", 2),
            "dependency": _apply_relationship_delta(state, primary_target_id, "dependency", 1),
        }
        _bump_global("route_lock", 1)
    elif move_family == "betray" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "trust": _apply_relationship_delta(state, primary_target_id, "trust", -3),
            "suspicion": _apply_relationship_delta(state, primary_target_id, "suspicion", 2),
            "tension": _apply_relationship_delta(state, primary_target_id, "tension", 2),
        }
        _bump_global("scene_heat", 2)
        _bump_global("secret_exposure", 1)
        _bump_global("route_lock", -1)
        state.betrayal_ids.append(primary_target_id)
    elif move_family == "public_reveal" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "tension": _apply_relationship_delta(state, primary_target_id, "tension", 1),
            "suspicion": _apply_relationship_delta(state, primary_target_id, "suspicion", 1),
        }
        _bump_global("secret_exposure", 2)
        _bump_global("public_image", 1, minimum=-3, maximum=3)
        _bump_global("scene_heat", 2)
    elif move_family == "private_confession" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "affection": _apply_relationship_delta(state, primary_target_id, "affection", 2),
            "trust": _apply_relationship_delta(state, primary_target_id, "trust", 1),
        }
        _bump_global("scene_heat", 1)
        _bump_global("route_lock", 2)
    elif move_family == "jealousy_trigger" and primary_target_id:
        relationship_changes[primary_target_id] = {
            "tension": _apply_relationship_delta(state, primary_target_id, "tension", 2),
            "affection": _apply_relationship_delta(state, primary_target_id, "affection", 1),
            "suspicion": _apply_relationship_delta(state, primary_target_id, "suspicion", 1),
        }
        _bump_global("scene_heat", 1)

    beat = _current_beat(plan, state)
    if move_family in {"probe_secret", "public_reveal", "betray"}:
        next_secret_id = _next_secret_id(plan, state, beat)
        if next_secret_id:
            state.known_secret_ids.append(next_secret_id)
            revealed_secret_ids.append(next_secret_id)

    progress_gain = 1
    if move_family in set(beat.preferred_move_families or []):
        progress_gain += 1
    if revealed_secret_ids:
        progress_gain += 1
    state.beat_progress += progress_gain

    beat_goal = _relationship_goal(beat)
    beat_completed = state.beat_progress >= beat_goal and all(
        secret_id in state.known_secret_ids for secret_id in list(beat.required_secret_ids or [])
    )
    advanced_to_next_beat = False
    if beat_completed and state.beat_index < len(plan.beats) - 1:
        state.beat_index += 1
        state.beat_progress = 0
        advanced_to_next_beat = True

    state.last_turn_tags = [move_family]
    state.last_turn_consequences = [
        "关系开始失衡，所有人都在重新判断立场。",
        "这一轮选择让局面离真正的摊牌更近了一步。",
    ]
    state.last_turn_global_deltas = dict(global_changes)
    state.last_turn_relationship_deltas = {key: dict(value) for key, value in relationship_changes.items()}
    state.last_turn_revealed_secret_ids = list(revealed_secret_ids)
    state.suggested_actions = build_relationship_suggested_actions(plan, state)

    return PlayResolutionEffect(
        tactic_summary=intent.tactic_summary,
        move_family=move_family,  # type: ignore[arg-type]
        scene_frame=intent.scene_frame,
        target_character_ids=target_ids,
        intimacy_risk=intent.intimacy_risk,
        relationship_state_changes={key: dict(value) for key, value in relationship_changes.items()},
        global_state_changes=dict(global_changes),
        revealed_secret_ids=list(revealed_secret_ids),
        beat_completed=beat_completed,
        advanced_to_next_beat=advanced_to_next_beat,
        route_focus_character_id=primary_target_id,
        pressure_note="The room shifted around your choice.",
    )


def judge_relationship_drama_ending(
    *,
    plan: PlayPlan,
    state: PlaySessionState,
    resolution: PlayResolutionEffect,
) -> RelationshipJudgeResult:
    beat = _current_beat(plan, state)
    on_final_beat = state.beat_index >= len(plan.beats) - 1
    if not on_final_beat and state.turn_index < plan.max_turns:
        return RelationshipJudgeResult(proposed_ending_id=None, source="skipped", attempts=0)
    target_id = state.current_route_target_id or resolution.route_focus_character_id
    values = state.relationship_values.get(target_id or "", {})
    affection = int(values.get("affection", 0))
    trust = int(values.get("trust", 0))
    tension = int(values.get("tension", 0))
    suspicion = int(values.get("suspicion", 0))
    if state.route_lock >= 4 and affection >= 2 and trust >= 2 and suspicion <= 2:
        return RelationshipJudgeResult(proposed_ending_id="route_lock")
    if affection >= 1 and trust >= 1 and (state.secret_exposure >= 2 or tension >= 3):
        return RelationshipJudgeResult(proposed_ending_id="bittersweet")
    if trust <= -1 or suspicion >= 4 or tension >= 5:
        return RelationshipJudgeResult(proposed_ending_id="breakdown")
    if on_final_beat or state.turn_index >= plan.max_turns or beat.phase == "lock":
        return RelationshipJudgeResult(proposed_ending_id="open_loop")
    return RelationshipJudgeResult(proposed_ending_id=None, source="skipped", attempts=0)


def apply_relationship_judged_ending(
    *,
    plan: PlayPlan,
    state: PlaySessionState,
    resolution: PlayResolutionEffect,
    judge_result: RelationshipJudgeResult,
) -> PlayResolutionEffect:
    ending_id = judge_result.proposed_ending_id
    if ending_id is None:
        return resolution
    state.status = "completed"
    state.ending = _build_relationship_ending(plan, state, ending_id=ending_id)
    return resolution.model_copy(
        update={
            "ending_id": ending_id,
            "ending_trigger_reason": f"relationship_judge:{ending_id}",
        }
    )


def _build_relationship_ending(plan: PlayPlan, state: PlaySessionState, *, ending_id: str) -> PlayEnding:
    target_name = _cast_name(plan, state.current_route_target_id)
    mapping = {
        "route_lock": ("路线锁定", f"你和{target_name}之间的关系已经越过了无法退回的界线。"),
        "bittersweet": ("苦涩成局", f"你终于把{target_name}推到了你这边，但代价已经被所有人看见。"),
        "breakdown": ("关系翻车", f"局面在你和{target_name}之间彻底失控，所有暧昧都变成了伤口。"),
        "open_loop": ("悬而未决", f"你和{target_name}都没有退场，但真正的结局还没有发生。"),
    }
    label, summary = mapping.get(ending_id, ("未完待续", "这段关系还没有走到最后。"))
    return PlayEnding(ending_id=ending_id, label=label, summary=summary)


def render_relationship_turn(
    *,
    plan: PlayPlan,
    state: PlaySessionState,
    resolution: PlayResolutionEffect,
    input_text: str,
    selected_action: PlaySuggestedAction | None = None,
) -> RelationshipRenderResult:
    del selected_action
    target_name = _cast_name(plan, resolution.route_focus_character_id or state.current_route_target_id)
    beat = _current_beat(plan, state)
    scene_label = {
        "hook": "局面第一次失衡。",
        "misread": "误会开始发酵。",
        "pressure": "空气里已经全是试探和压迫。",
        "reveal": "真相正在逼近表面。",
        "lock": "所有人都感觉到结局快要落下来了。",
    }.get(str(beat.phase or "hook"), "局面正在失衡。")
    move_line = {
        "flirt": f"你故意向{target_name}靠近半步，让那点若有若无的暧昧终于被所有人看见。",
        "probe_secret": f"你没有顺着表面的台词走，而是逼着{target_name}去碰那件谁都不愿点明的秘密。",
        "comfort": f"你先稳住了{target_name}的情绪，让原本快要碎掉的信任重新有了落点。",
        "deflect": f"你把最危险的问题轻轻拨开，逼得{target_name}开始怀疑你真正想藏的是什么。",
        "accuse": f"你当场把矛头指向{target_name}，让场面不可能再按原来的体面继续。",
        "ally_with": f"你把条件放到{target_name}面前，试着把这段危险关系拉成真正的同盟。",
        "betray": f"你在最关键的一步突然转向，让{target_name}终于意识到你从来没有完全站在他那边。",
        "public_reveal": f"你把本该私下处理的东西直接摊开，逼得{target_name}和所有围观者一起失去退路。",
        "private_confession": f"你终于对{target_name}说出了那句最不该说的话，也把这段关系推向了再也无法装作无事的地步。",
        "jealousy_trigger": f"你故意让第三个人卷进来，让{target_name}再也没办法假装毫不在意。",
    }.get(str(resolution.move_family or ""), trim_ellipsis(input_text, 220))
    reveal_line = ""
    if resolution.revealed_secret_ids:
        reveal_line = " 一个新的秘密已经浮出水面，之后的每一步都会更难收场。"
    narration = f"{scene_label}{move_line}{reveal_line}"
    suggestions = [] if state.status != "active" else build_relationship_suggested_actions(plan, state)
    return RelationshipRenderResult(narration=trim_ellipsis(narration, 4000), suggestions=suggestions)
