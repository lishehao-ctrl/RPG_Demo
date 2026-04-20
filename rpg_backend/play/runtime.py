from __future__ import annotations

from dataclasses import dataclass, field
import re

from rpg_backend.author.contracts import AffordanceTag, AxisDefinition, BeatSpec, ConditionBlock
from rpg_backend.author.normalize import slugify, trim_ellipsis, unique_preserve
from rpg_backend.play.contracts import (
    PlayCostLedger,
    PlayEnding,
    PlayFeedbackSnapshot,
    PlayLedgerSnapshot,
    PlayPlan,
    PlayProtagonist,
    PlayResolutionEffect,
    PlaySessionProgress,
    PlaySuccessLedger,
    PlaySupportSurface,
    PlaySupportSurfaces,
    PlaySessionSnapshot,
    PlayStateBar,
    PlaySuggestedAction,
    PlayTurnIntentDraft,
)


SUGGESTION_TEMPLATES: dict[str, tuple[str, str]] = {
    "reveal_truth": ("Expose the hidden pressure", "You press {npc} until the concealed truth starts to surface."),
    "build_trust": ("Stabilize an alliance", "You work to bring {npc} onto your side before the coalition slips further."),
    "contain_chaos": ("Contain the immediate panic", "You move fast to keep the crisis from spilling into open disorder around {npc}."),
    "shift_public_narrative": ("Take control of the public story", "You reframe events in public and force {npc} to answer to the broader city."),
    "protect_civilians": ("Protect the vulnerable flank", "You prioritize civilian safety and make {npc} react to that moral pressure."),
    "secure_resources": ("Secure what the city needs", "You push {npc} to release resources before scarcity turns political."),
    "unlock_ally": ("Pull a reluctant ally in", "You try to bring {npc} fully into the coalition before the next fracture."),
    "pay_cost": ("Force progress at a cost", "You accept an ugly concession and make {npc} live with the fallout."),
}

SUGGESTION_TEMPLATE_VARIANTS: dict[str, dict[str, tuple[str, str]]] = {
    "contain_chaos": {
        "panic_rising": ("Cool the crowd", "You cut through the surge before panic hardens around {npc}."),
        "panic_eased": ("Hold the calmer line", "You keep the room steady so the panic does not rebound through {npc}."),
    },
    "shift_public_narrative": {
        "leverage_rising": ("Lock the mandate in", "You turn the latest leverage into a public line {npc} cannot easily escape."),
        "public_pressure": ("Reframe the uproar", "You redirect the public pressure so {npc} has to answer on your terms."),
    },
    "build_trust": {
        "coalition_shift": ("Consolidate the alliance", "You make the new trust with {npc} stick before the coalition slips again."),
    },
    "unlock_ally": {
        "coalition_shift": ("Keep the ally inside", "You turn the latest opening with {npc} into a durable commitment."),
    },
    "secure_resources": {
        "resource_rising": ("Reopen the supply line", "You force a practical release from {npc} before the shortage narrative spreads."),
        "resource_eased": ("Protect the new flow", "You keep the reopened supply route from collapsing back under {npc}."),
    },
    "reveal_truth": {
        "institutional_strain": ("Pin the discrepancy down", "You make {npc} answer for the record gap before procedure closes over it."),
        "pressure_rising": ("Force the hidden record out", "You use the rising pressure to drag one more fact from {npc}."),
    },
}

_HEURISTIC_EXECUTION_FRAME_MARKERS: dict[str, tuple[str, ...]] = {
    "coercive": ("force", "threaten", "command", "order", "seize", "ultimatum", "guards", "lock down"),
    "public": ("public", "crowd", "gallery", "hearing", "broadcast", "loudspeaker", "warning bells", "podium", "read aloud", "declare"),
    "coalition": ("joint", "together", "shared", "co-author", "invite", "convene", "unified", "truce", "accord", "compact", "pact"),
    "procedural": ("audit", "verify", "compare", "review", "inspect", "line by line", "records hall", "chain-of-custody"),
}

_HEURISTIC_HARD_COERCIVE_MARKERS = ("threaten", "seize", "ultimatum", "guards", "lock down")

_HEURISTIC_RESOURCE_KEYWORDS = (
    "manifest",
    "manifests",
    "shipment",
    "shipments",
    "inventory",
    "cargo",
    "reserve",
    "reserves",
    "ration",
    "rations",
    "allotment",
    "allotments",
    "checkpoint",
)

_HEURISTIC_CERTIFICATION_KEYWORDS = (
    "certify",
    "certified",
    "ratify",
    "binding order",
    "verified account",
    "emergency protocol",
    "charter",
)

_HEURISTIC_KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "reveal_truth": (
        "reveal",
        "investigate",
        "question",
        "expose",
        "audit",
        "evidence",
        "proof",
        "compare",
        "record",
        "ledger",
        "ledgers",
        "report",
        "reports",
        "count",
        "counts",
        "transcript",
        "witness",
    ),
    "build_trust": ("trust", "convince", "ally", "negotiate", "persuade", "appeal"),
    "contain_chaos": ("contain", "calm", "stabilize", "lockdown", "order", "evacuate"),
    "shift_public_narrative": (
        "announce",
        "speech",
        "public",
        "broadcast",
        "declare",
        "frame",
        "certify",
        "certified",
        "ratify",
        "charter",
        "protocol",
        "binding order",
        "verified account",
        "seal",
    ),
    "protect_civilians": ("protect", "shield", "rescue", "save", "cover"),
    "secure_resources": (
        "resource",
        "supply",
        "food",
        "fuel",
        "cargo",
        "secure",
        "shipment",
        "shipments",
        "manifest",
        "manifests",
        "inventory",
        "allotment",
        "allotments",
        "ration",
        "rations",
        "reserve",
        "reserves",
        "checkpoint",
    ),
    "unlock_ally": ("recruit", "join", "back us", "bring in"),
    "pay_cost": ("threaten", "bribe", "sacrifice", "force", "break", "deal"),
}

_HEURISTIC_STRONG_TAG_COMBOS: dict[str, tuple[tuple[str, ...], ...]] = {
    "reveal_truth": (
        ("compare", "record"),
        ("audit", "ledger"),
        ("verify", "ledger"),
        ("proof", "record"),
    ),
    "shift_public_narrative": (
        ("public", "declare"),
        ("broadcast", "record"),
        ("binding order",),
        ("certify",),
    ),
    "secure_resources": (
        ("manifest", "shipment"),
        ("inventory", "cargo"),
        ("ration", "supply"),
    ),
    "contain_chaos": (
        ("calm", "crowd"),
        ("evacuate", "crowd"),
        ("stabilize", "panic"),
    ),
}

_HEURISTIC_AMBIGUITY_MARKERS = (
    "maybe",
    "perhaps",
    "somehow",
    "someone",
    "something",
    "either",
    "or maybe",
    "i guess",
    "?",
)


@dataclass
class PlaySessionState:
    session_id: str
    story_id: str
    status: str
    turn_index: int
    beat_index: int
    beat_progress: int
    beat_detours_used: int
    axis_values: dict[str, int]
    stance_values: dict[str, int]
    flag_values: dict[str, bool]
    discovered_truth_ids: list[str] = field(default_factory=list)
    discovered_event_ids: list[str] = field(default_factory=list)
    success_ledger: dict[str, int] = field(default_factory=dict)
    cost_ledger: dict[str, int] = field(default_factory=dict)
    last_turn_axis_deltas: dict[str, int] = field(default_factory=dict)
    last_turn_stance_deltas: dict[str, int] = field(default_factory=dict)
    last_turn_tags: list[str] = field(default_factory=list)
    last_turn_consequences: list[str] = field(default_factory=list)
    narration: str = ""
    suggested_actions: list[PlaySuggestedAction] = field(default_factory=list)
    ending: PlayEnding | None = None
    session_response_id: str | None = None
    collapse_pressure_streak: int = 0
    primary_axis_history: list[str] = field(default_factory=list)
    negative_stance_history: list[str] = field(default_factory=list)
    scene_heat: int = 0
    public_image: int = 0
    secret_exposure: int = 0
    route_lock: int = 0
    current_route_target_id: str | None = None
    relationship_values: dict[str, dict[str, int]] = field(default_factory=dict)
    known_secret_ids: list[str] = field(default_factory=list)
    public_event_ids: list[str] = field(default_factory=list)
    private_scene_ids: list[str] = field(default_factory=list)
    promise_ids: list[str] = field(default_factory=list)
    betrayal_ids: list[str] = field(default_factory=list)
    last_turn_global_deltas: dict[str, int] = field(default_factory=dict)
    last_turn_relationship_deltas: dict[str, dict[str, int]] = field(default_factory=dict)
    last_turn_revealed_secret_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TurnEndingGateContext:
    final_beat_completed: bool
    final_beat_handoff: bool
    turn_cap_reached: bool = False


def _current_beat(plan: PlayPlan, state: PlaySessionState) -> BeatSpec:
    index = min(max(state.beat_index, 0), len(plan.beats) - 1)
    return plan.beats[index]


def _ending_by_id(plan: PlayPlan, ending_id: str) -> PlayEnding:
    item = next((entry for entry in plan.endings if entry.ending_id == ending_id), None)
    if item is None:
        return PlayEnding(ending_id=ending_id, label=ending_id.replace("_", " ").title(), summary="The crisis resolves.")
    return PlayEnding(ending_id=item.ending_id, label=item.label, summary=item.summary)


def _conditions_match(conditions: ConditionBlock, plan: PlayPlan, state: PlaySessionState) -> bool:
    if any(state.axis_values.get(axis_id, 0) < threshold for axis_id, threshold in conditions.min_axes.items()):
        return False
    if any(state.axis_values.get(axis_id, 0) > threshold for axis_id, threshold in conditions.max_axes.items()):
        return False
    if any(state.stance_values.get(stance_id, 0) < threshold for stance_id, threshold in conditions.min_stances.items()):
        return False
    if any(truth_id not in state.discovered_truth_ids for truth_id in conditions.required_truths):
        return False
    if any(event_id not in state.discovered_event_ids for event_id in conditions.required_events):
        return False
    if any(not state.flag_values.get(flag_id, False) for flag_id in conditions.required_flags):
        return False
    return True


def _pressure_axis_id(plan: PlayPlan, beat: BeatSpec) -> str:
    if beat.pressure_axis_id and any(axis.axis_id == beat.pressure_axis_id for axis in plan.axes):
        return beat.pressure_axis_id
    pressure_axis = next((axis.axis_id for axis in plan.axes if axis.kind == "pressure"), None)
    return pressure_axis or plan.axes[0].axis_id


def _route_unlocked_tags(plan: PlayPlan, state: PlaySessionState, beat: BeatSpec) -> list[str]:
    tags = []
    for rule in plan.route_unlock_rules:
        if rule.beat_id != beat.beat_id:
            continue
        if _conditions_match(rule.conditions, plan, state):
            tags.append(rule.unlock_affordance_tag)
    return unique_preserve(tags)


def available_affordance_tags(plan: PlayPlan, state: PlaySessionState) -> list[str]:
    beat = _current_beat(plan, state)
    ordered = [beat.route_pivot_tag] if beat.route_pivot_tag else []
    ordered.extend(weight.tag for weight in beat.affordances)
    ordered.extend(_route_unlocked_tags(plan, state, beat))
    tags = unique_preserve([tag for tag in ordered if tag and tag not in beat.blocked_affordances])
    if not tags:
        tags = list(plan.available_affordance_tags[:3])
    return tags


def _suggestion_target_name(plan: PlayPlan, beat: BeatSpec) -> str:
    protagonist_npc_id = plan.protagonist_npc_id
    focus_candidates = [npc_id for npc_id in (beat.focus_npcs or beat.conflict_npcs) if npc_id != protagonist_npc_id]
    npc_id = next(iter(focus_candidates), None)
    if npc_id is None:
        npc_id = next((item.npc_id for item in plan.cast if item.npc_id != protagonist_npc_id), None)
    npc = next((item for item in plan.cast if item.npc_id == npc_id), None)
    if npc is not None:
        return npc.name
    fallback_npc = next((item for item in plan.cast if item.npc_id != protagonist_npc_id), None)
    return fallback_npc.name if fallback_npc is not None else "the chamber"


def _suggestion_target_names(plan: PlayPlan, state: PlaySessionState, beat: BeatSpec) -> list[str]:
    protagonist_npc_id = plan.protagonist_npc_id
    recent_stance_npc_ids = [
        stance.npc_id
        for stance in plan.stances
        if stance.stance_id in state.last_turn_stance_deltas and stance.npc_id != protagonist_npc_id
    ]
    ordered_ids = unique_preserve(
        [
            *recent_stance_npc_ids,
            *[npc_id for npc_id in beat.conflict_npcs if npc_id != protagonist_npc_id],
            *[npc_id for npc_id in beat.focus_npcs if npc_id != protagonist_npc_id],
            *[npc.npc_id for npc in plan.cast if npc.npc_id != protagonist_npc_id],
        ]
    )
    names: list[str] = []
    for npc_id in ordered_ids:
        npc = next((item for item in plan.cast if item.npc_id == npc_id), None)
        if npc is not None:
            names.append(npc.name)
    if not names:
        names.append("the chamber")
    return names


def _suggestion_context(state: PlaySessionState) -> str | None:
    axis_deltas = state.last_turn_axis_deltas
    if axis_deltas.get("public_panic", 0) > 0:
        return "panic_rising"
    if axis_deltas.get("public_panic", 0) < 0:
        return "panic_eased"
    if axis_deltas.get("political_leverage", 0) > 0:
        return "leverage_rising"
    if axis_deltas.get("resource_strain", 0) > 0:
        return "resource_rising"
    if axis_deltas.get("resource_strain", 0) < 0:
        return "resource_eased"
    if axis_deltas.get("system_integrity", 0) > 0:
        return "institutional_strain"
    if any(value != 0 for value in state.last_turn_stance_deltas.values()):
        return "coalition_shift"
    if any(value > 0 for value in axis_deltas.values()):
        return "pressure_rising"
    return None


def _suggestion_template_for_tag(tag: str, state: PlaySessionState) -> tuple[str, str]:
    context = _suggestion_context(state)
    if context:
        variant = SUGGESTION_TEMPLATE_VARIANTS.get(tag, {}).get(context)
        if variant is not None:
            return variant
        if context in {"panic_rising", "panic_eased"}:
            variant = SUGGESTION_TEMPLATE_VARIANTS.get(tag, {}).get("public_pressure")
            if variant is not None:
                return variant
    return SUGGESTION_TEMPLATES.get(
        tag,
        ("Press the next move", "You push the situation forward and make {npc} react."),
    )


def build_suggested_actions(plan: PlayPlan, state: PlaySessionState) -> list[PlaySuggestedAction]:
    if getattr(plan, "story_mode", "relationship_drama") == "relationship_drama":
        from rpg_backend.play.relationship_runtime import build_relationship_suggested_actions

        return build_relationship_suggested_actions(plan, state)
    if state.status != "active":
        return []
    beat = _current_beat(plan, state)
    target_names = _suggestion_target_names(plan, state, beat)
    suggestions: list[PlaySuggestedAction] = []
    for index, tag in enumerate(available_affordance_tags(plan, state)[:3], start=1):
        label_template, prompt_template = _suggestion_template_for_tag(tag, state)
        target_name = target_names[(index - 1) % len(target_names)]
        suggestions.append(
            PlaySuggestedAction(
                suggestion_id=f"{slugify(tag)}_{index}",
                label=label_template,
                prompt=trim_ellipsis(prompt_template.format(npc=target_name), 220),
            )
        )
    while len(suggestions) < 3:
        index = len(suggestions) + 1
        target_name = target_names[(index - 1) % len(target_names)]
        suggestions.append(
            PlaySuggestedAction(
                suggestion_id=f"advance_{index}",
                label="Push for momentum",
                prompt=trim_ellipsis(f"You force {target_name} to answer the crisis before the stalemate hardens.", 220),
            )
        )
    return suggestions[:3]


def build_initial_session_state(plan: PlayPlan, *, session_id: str) -> PlaySessionState:
    if getattr(plan, "story_mode", "relationship_drama") == "relationship_drama":
        from rpg_backend.play.relationship_runtime import build_initial_relationship_session_state

        return build_initial_relationship_session_state(plan, session_id=session_id)
    state = PlaySessionState(
        session_id=session_id,
        story_id=plan.story_id,
        status="active",
        turn_index=0,
        beat_index=0,
        beat_progress=0,
        beat_detours_used=0,
        axis_values={axis.axis_id: axis.starting_value for axis in plan.axes},
        stance_values={stance.stance_id: stance.starting_value for stance in plan.stances},
        flag_values={flag.flag_id: flag.starting_value for flag in plan.flags},
        success_ledger={
            "proof_progress": 0,
            "coalition_progress": 0,
            "order_progress": 0,
            "settlement_progress": 0,
        },
        cost_ledger={
            "public_cost": 0,
            "relationship_cost": 0,
            "procedural_cost": 0,
            "coercion_cost": 0,
        },
        narration=plan.opening_narration,
    )
    state.suggested_actions = build_suggested_actions(plan, state)
    return state


def _feedback_snapshot(state: PlaySessionState) -> PlayFeedbackSnapshot:
    return PlayFeedbackSnapshot(
        ledgers=PlayLedgerSnapshot(
            success=PlaySuccessLedger(
                proof_progress=state.success_ledger.get("proof_progress", 0),
                coalition_progress=state.success_ledger.get("coalition_progress", 0),
                order_progress=state.success_ledger.get("order_progress", 0),
                settlement_progress=state.success_ledger.get("settlement_progress", 0),
            ),
            cost=PlayCostLedger(
                public_cost=state.cost_ledger.get("public_cost", 0),
                relationship_cost=state.cost_ledger.get("relationship_cost", 0),
                procedural_cost=state.cost_ledger.get("procedural_cost", 0),
                coercion_cost=state.cost_ledger.get("coercion_cost", 0),
            ),
        ),
        last_turn_axis_deltas=dict(state.last_turn_axis_deltas),
        last_turn_stance_deltas=dict(state.last_turn_stance_deltas),
        last_turn_global_deltas=dict(state.last_turn_global_deltas),
        last_turn_relationship_deltas={key: dict(value) for key, value in state.last_turn_relationship_deltas.items()},
        last_turn_tags=list(state.last_turn_tags),
        last_turn_consequences=list(state.last_turn_consequences),
        last_turn_revealed_secret_ids=list(state.last_turn_revealed_secret_ids),
    )


def _binding_outcome_progress_signal(state: PlaySessionState) -> bool:
    consequence_set = set(state.last_turn_consequences)
    if "The crisis moved closer to a binding outcome." in consequence_set:
        return True
    if "You gained room to maneuver inside the coalition." in consequence_set:
        return True
    if "Proof moved into the open." in consequence_set and state.last_turn_axis_deltas.get("political_leverage", 0) > 0:
        return True
    return False


def _pressure_relief_signal(plan: PlayPlan, state: PlaySessionState) -> bool:
    pressure_axis_ids = {axis.axis_id for axis in plan.axes if axis.kind == "pressure"}
    return any(
        delta < 0
        for axis_id, delta in state.last_turn_axis_deltas.items()
        if axis_id in pressure_axis_ids
    )


def _uncontained_breakdown_signal(plan: PlayPlan, state: PlaySessionState) -> bool:
    pressure_axis_ids = {axis.axis_id for axis in plan.axes if axis.kind == "pressure"}
    positive_pressure_deltas = {
        axis_id: delta
        for axis_id, delta in state.last_turn_axis_deltas.items()
        if axis_id in pressure_axis_ids and delta > 0
    }
    public_delta = state.last_turn_axis_deltas.get("public_panic", 0)
    negative_stance_count = sum(1 for delta in state.last_turn_stance_deltas.values() if delta < 0)
    binding_progress = _binding_outcome_progress_signal(state)
    return (
        len(positive_pressure_deltas) >= 2
        or negative_stance_count >= 2
        or (public_delta >= 2 and negative_stance_count >= 1 and not binding_progress)
    )


def _update_collapse_pressure_streak(
    plan: PlayPlan,
    state: PlaySessionState,
    *,
    pressure_axis_id: str,
    pressure_value: int,
    use_tuned_ending_policy: bool,
) -> None:
    pressure_axis = next(axis for axis in plan.axes if axis.axis_id == pressure_axis_id)
    if not use_tuned_ending_policy:
        state.collapse_pressure_streak = 1 if pressure_value >= pressure_axis.max_value else 0
        return
    at_max_pressure = pressure_value >= pressure_axis.max_value
    pressure_relief = _pressure_relief_signal(plan, state)
    binding_progress = _binding_outcome_progress_signal(state)
    uncontained_breakdown = _uncontained_breakdown_signal(plan, state)
    if at_max_pressure and uncontained_breakdown and not pressure_relief:
        state.collapse_pressure_streak += 1
        return
    if pressure_relief or (binding_progress and not uncontained_breakdown):
        state.collapse_pressure_streak = max(state.collapse_pressure_streak - 1, 0)
        return
    if at_max_pressure:
        state.collapse_pressure_streak = max(state.collapse_pressure_streak, 1)
        return
    state.collapse_pressure_streak = 0


def build_state_bars(plan: PlayPlan, state: PlaySessionState) -> list[PlayStateBar]:
    if getattr(plan, "story_mode", "relationship_drama") == "relationship_drama":
        from rpg_backend.play.relationship_runtime import build_relationship_state_bars

        return build_relationship_state_bars(plan, state)
    bars = [
        PlayStateBar(
            bar_id=axis.axis_id,
            label=axis.label,
            category="axis",
            current_value=state.axis_values.get(axis.axis_id, axis.starting_value),
            min_value=axis.min_value,
            max_value=axis.max_value,
        )
        for axis in plan.axes
    ]
    bars.extend(
        PlayStateBar(
            bar_id=stance.stance_id,
            label=stance.label,
            category="stance",
            current_value=state.stance_values.get(stance.stance_id, stance.starting_value),
            min_value=stance.min_value,
            max_value=stance.max_value,
        )
        for stance in plan.stances
    )
    return bars


def _session_progress(plan: PlayPlan, state: PlaySessionState) -> PlaySessionProgress:
    total_beats = max(len(plan.beats), 1)
    current_beat = _current_beat(plan, state)
    current_beat_goal = max(1, 1 if state.beat_index >= len(plan.beats) - 1 else current_beat.progress_required)
    completed_beats = len(plan.beats) if state.status == "completed" else min(state.beat_index, len(plan.beats))
    current_beat_progress = current_beat_goal if state.status == "completed" else min(state.beat_progress, current_beat_goal)
    completion_ratio = min(
        (completed_beats + (current_beat_progress / current_beat_goal if state.status != "completed" else 0.0))
        / total_beats,
        1.0,
    )
    return PlaySessionProgress(
        completed_beats=completed_beats,
        total_beats=total_beats,
        current_beat_progress=current_beat_progress,
        current_beat_goal=current_beat_goal,
        turn_index=state.turn_index,
        max_turns=plan.max_turns,
        completion_ratio=round(completion_ratio, 3),
        display_percent=min(100, round(completion_ratio * 100)),
    )


def _support_surfaces() -> PlaySupportSurfaces:
    return PlaySupportSurfaces(
        inventory=PlaySupportSurface(
            enabled=False,
            disabled_reason="Inventory is not authored for this runtime yet.",
        ),
        map=PlaySupportSurface(
            enabled=False,
            disabled_reason="Map data is not available for this runtime yet.",
        ),
    )


def build_session_snapshot(plan: PlayPlan, state: PlaySessionState) -> PlaySessionSnapshot:
    if getattr(plan, "story_mode", "relationship_drama") == "relationship_drama":
        from rpg_backend.play.relationship_runtime import build_relationship_session_snapshot

        return build_relationship_session_snapshot(plan, state)
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
        feedback=_feedback_snapshot(state),
        progress=_session_progress(plan, state),
        support_surfaces=_support_surfaces(),
        state_bars=build_state_bars(plan, state),
        suggested_actions=list(state.suggested_actions),
        ending=state.ending,
    )


def _text_contains_keyword(text: str, keyword: str) -> bool:
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _heuristic_keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if _text_contains_keyword(text, keyword))


def _matched_npc_count(plan: PlayPlan, text: str) -> int:
    count = 0
    for npc in plan.cast:
        if npc.npc_id == plan.protagonist_npc_id:
            continue
        parts = npc.name.casefold().split()
        if npc.name.casefold() in text or (parts and parts[0] in text):
            count += 1
    return count


def heuristic_turn_intent(
    *,
    input_text: str,
    plan: PlayPlan,
    state: PlaySessionState,
    selected_prompt: str | None = None,
) -> PlayTurnIntentDraft:
    if getattr(plan, "story_mode", "relationship_drama") == "relationship_drama":
        from rpg_backend.play.relationship_runtime import heuristic_relationship_turn_intent

        return heuristic_relationship_turn_intent(
            input_text=input_text,
            plan=plan,
            state=state,
        ).intent
    text = " ".join([selected_prompt or "", input_text]).casefold()
    tag = available_affordance_tags(plan, state)[0]
    execution_frame = "procedural"
    has_coercive_marker = any(marker in text for marker in _HEURISTIC_EXECUTION_FRAME_MARKERS["coercive"])
    has_public_marker = any(marker in text for marker in _HEURISTIC_EXECUTION_FRAME_MARKERS["public"])
    has_coalition_marker = any(marker in text for marker in _HEURISTIC_EXECUTION_FRAME_MARKERS["coalition"])
    has_procedural_marker = any(marker in text for marker in _HEURISTIC_EXECUTION_FRAME_MARKERS["procedural"])
    has_hard_coercive_marker = any(marker in text for marker in _HEURISTIC_HARD_COERCIVE_MARKERS)
    if has_public_marker and not has_hard_coercive_marker:
        execution_frame = "public"
    elif has_coercive_marker:
        execution_frame = "coercive"
    elif has_coalition_marker:
        execution_frame = "coalition"
    elif has_procedural_marker:
        execution_frame = "procedural"
    if any(keyword in text for keyword in _HEURISTIC_RESOURCE_KEYWORDS):
        tag = "secure_resources"
    certification_semantics = any(keyword in text for keyword in _HEURISTIC_CERTIFICATION_KEYWORDS)
    if certification_semantics:
        tag = "shift_public_narrative"
    if not certification_semantics:
        for candidate, keywords in _HEURISTIC_KEYWORD_MAP.items():
            if any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords):
                tag = candidate
                break
    risk_level = "high" if any(token in text for token in ("threaten", "sacrifice", "force", "burn", "violent")) else "medium"
    if risk_level == "medium" and any(token in text for token in ("carefully", "quietly", "gently", "calmly")):
        risk_level = "low"
    target_npc_ids = [
        npc.npc_id
        for npc in plan.cast
        if npc.npc_id != plan.protagonist_npc_id
        and (npc.name.casefold().split()[0] in text or npc.name.casefold() in text)
    ][:3]
    if not target_npc_ids:
        beat = _current_beat(plan, state)
        target_npc_ids = [
            npc_id
            for npc_id in list(beat.focus_npcs[:2] or beat.conflict_npcs[:1])
            if npc_id != plan.protagonist_npc_id
        ]
    if not target_npc_ids:
        target_npc_ids = [npc.npc_id for npc in plan.cast if npc.npc_id != plan.protagonist_npc_id][:2]
    return PlayTurnIntentDraft(
        affordance_tag=tag,  # type: ignore[arg-type]
        target_npc_ids=target_npc_ids,
        risk_level=risk_level,  # type: ignore[arg-type]
        execution_frame=execution_frame,  # type: ignore[arg-type]
        tactic_summary=trim_ellipsis(input_text, 220),
    )


def heuristic_first_turn_fast_path_intent(
    *,
    input_text: str,
    plan: PlayPlan,
    state: PlaySessionState,
    selected_prompt: str | None = None,
    selected_tag: str | None = None,
) -> PlayTurnIntentDraft | None:
    if state.turn_index != 0:
        return None
    text = " ".join([selected_prompt or "", input_text]).casefold()
    if any(marker in text for marker in _HEURISTIC_AMBIGUITY_MARKERS):
        return None
    intent = heuristic_turn_intent(
        input_text=input_text,
        plan=plan,
        state=state,
        selected_prompt=selected_prompt,
    )
    available_tags = available_affordance_tags(plan, state)
    if intent.affordance_tag not in available_tags:
        return None
    if selected_tag and selected_tag == intent.affordance_tag:
        return intent
    tag_scores = {
        tag: _heuristic_keyword_score(text, _HEURISTIC_KEYWORD_MAP.get(tag, ()))
        for tag in available_tags
    }
    predicted_score = int(tag_scores.get(intent.affordance_tag, 0))
    sorted_scores = sorted(tag_scores.values(), reverse=True)
    top_score = sorted_scores[0] if sorted_scores else 0
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0
    explicit_target = _matched_npc_count(plan, text) > 0
    explicit_frame = intent.execution_frame != "procedural" or any(
        marker in text for marker in _HEURISTIC_EXECUTION_FRAME_MARKERS["procedural"]
    )
    strong_combo = any(
        all(_text_contains_keyword(text, keyword) for keyword in combo)
        for combo in _HEURISTIC_STRONG_TAG_COMBOS.get(intent.affordance_tag, ())
    )
    if strong_combo and predicted_score >= 1:
        return intent
    if predicted_score >= 3 and predicted_score == top_score:
        return intent
    if predicted_score >= 2 and predicted_score == top_score and predicted_score > second_score and (explicit_frame or explicit_target):
        return intent
    return None


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _apply_axis_changes(plan: PlayPlan, state: PlaySessionState, axis_changes: dict[str, int]) -> dict[str, int]:
    applied: dict[str, int] = {}
    for axis in plan.axes:
        delta = axis_changes.get(axis.axis_id, 0)
        if delta == 0:
            continue
        current = state.axis_values.get(axis.axis_id, axis.starting_value)
        updated = _clamp(current + delta, axis.min_value, axis.max_value)
        if updated == current:
            continue
        state.axis_values[axis.axis_id] = updated
        applied[axis.axis_id] = updated - current
    return applied


def _apply_stance_changes(plan: PlayPlan, state: PlaySessionState, stance_changes: dict[str, int]) -> dict[str, int]:
    applied: dict[str, int] = {}
    for stance in plan.stances:
        delta = stance_changes.get(stance.stance_id, 0)
        if delta == 0:
            continue
        current = state.stance_values.get(stance.stance_id, stance.starting_value)
        updated = _clamp(current + delta, stance.min_value, stance.max_value)
        if updated == current:
            continue
        state.stance_values[stance.stance_id] = updated
        applied[stance.stance_id] = updated - current
    return applied


def _next_truth_id(plan: PlayPlan, state: PlaySessionState, beat: BeatSpec) -> str | None:
    for truth_id in beat.required_truths:
        if truth_id not in state.discovered_truth_ids:
            return truth_id
    for truth in plan.truths:
        if truth.truth_id not in state.discovered_truth_ids:
            return truth.truth_id
    return None


def _public_pressure_axis_id(plan: PlayPlan) -> str:
    if any(axis.axis_id == "public_panic" for axis in plan.axes):
        return "public_panic"
    pressure_axis = next((axis.axis_id for axis in plan.axes if axis.kind == "pressure"), None)
    return pressure_axis or plan.axes[0].axis_id


def _support_axis_id(plan: PlayPlan) -> str | None:
    for preferred in ("ally_trust", "political_leverage"):
        if any(axis.axis_id == preferred and axis.kind != "pressure" for axis in plan.axes):
            return preferred
    non_positive_axes = {
        "system_integrity",
        "resource_strain",
        "public_panic",
        "exposure_risk",
        "time_window",
        "external_pressure",
    }
    non_pressure = next(
        (
            axis.axis_id
            for axis in plan.axes
            if axis.kind != "pressure" and axis.axis_id not in non_positive_axes
        ),
        None,
    )
    return non_pressure


def _exposure_axis_id(plan: PlayPlan) -> str | None:
    if any(axis.axis_id == "exposure_risk" for axis in plan.axes):
        return "exposure_risk"
    return next((axis.axis_id for axis in plan.axes if "exposure" in axis.axis_id), None)


def _resource_axis_id(plan: PlayPlan) -> str | None:
    if any(axis.axis_id == "resource_strain" for axis in plan.axes):
        return "resource_strain"
    return next((axis.axis_id for axis in plan.axes if axis.kind == "resource"), None)


def _runtime_policy_is(plan: PlayPlan, *profiles: str) -> bool:
    return plan.runtime_policy_profile in set(profiles)


def _institutional_axis_id(plan: PlayPlan) -> str | None:
    if any(axis.axis_id == "system_integrity" for axis in plan.axes):
        return "system_integrity"
    return next((axis.axis_id for axis in plan.axes if "integrity" in axis.axis_id), None)


def _public_semantic_delta(*, applied_tag: str, risk_level: str, tactic_summary: str) -> int | None:
    text = tactic_summary.casefold()
    calm_markers = (
        "calm",
        "reassure",
        "line by line",
        "joint supervision",
        "under oversight",
        "oversight",
        "compact",
        "charter",
        "binding order",
        "emergency protocol",
        "protocol",
        "stand down",
        "form a wall",
        "hold the line",
        "seal the chamber",
        "seal the record",
        "swear compliance",
        "shared pact",
        "seal the book",
    )
    escalate_markers = (
        "warning bells",
        "loudspeaker",
        "broadcast",
        "crowd",
        "evacuation",
        "panic",
        "alarm",
        "force",
        "shout",
        "expose",
    )
    if any(marker in text for marker in calm_markers):
        return -1
    if any(marker in text for marker in escalate_markers):
        return 1
    if applied_tag == "shift_public_narrative":
        if risk_level == "high":
            return 1
        if risk_level == "low":
            return -1
    return None


def _is_public_escalation_tactic(tactic_summary: str) -> bool:
    text = tactic_summary.casefold()
    audience_markers = (
        "public hearing",
        "read aloud",
        "in front of the waiting crowds",
        "waiting crowds",
        "before the council",
        "warning bells",
        "loudspeakers",
        "broadcast",
        "crowd",
        "evacuation order",
    )
    return any(marker in text for marker in audience_markers)


def _is_private_audit_tactic(tactic_summary: str) -> bool:
    text = tactic_summary.casefold()
    private_markers = (
        "compare",
        "audit",
        "line by line",
        "verify",
        "inspect",
        "question",
        "manifest",
        "ledger",
        "records hall",
        "sealed archive",
    )
    return any(marker in text for marker in private_markers) and not _is_public_escalation_tactic(tactic_summary)


def _axis_lookup(plan: PlayPlan) -> dict[str, AxisDefinition]:
    return {axis.axis_id: axis for axis in plan.axes}


def _first_existing_axis(plan: PlayPlan, candidates: list[str | None], *, exclude: set[str] | None = None) -> str | None:
    axes = _axis_lookup(plan)
    blocked = exclude or set()
    for axis_id in candidates:
        if axis_id and axis_id in axes and axis_id not in blocked:
            return axis_id
    return None


def _execution_frame_axis_preferences(
    plan: PlayPlan,
    *,
    applied_tag: str,
    execution_frame: str,
    public_escalation: bool,
    private_audit: bool,
) -> list[str]:
    pressure_axis_id = next((axis.axis_id for axis in plan.axes if axis.kind == "pressure"), plan.axes[0].axis_id)
    public_axis_id = _public_pressure_axis_id(plan)
    support_axis_id = _support_axis_id(plan)
    resource_axis_id = _resource_axis_id(plan)
    exposure_axis_id = _exposure_axis_id(plan)
    institutional_axis_id = _institutional_axis_id(plan)
    leverage_axis_id = "political_leverage" if "political_leverage" in _axis_lookup(plan) else support_axis_id

    if _runtime_policy_is(plan, "warning_record_play"):
        base = {
            "procedural": [exposure_axis_id, institutional_axis_id, leverage_axis_id, pressure_axis_id],
            "coalition": [leverage_axis_id, exposure_axis_id, institutional_axis_id, support_axis_id],
            "public": [public_axis_id, exposure_axis_id, leverage_axis_id, pressure_axis_id],
            "coercive": [public_axis_id, pressure_axis_id, exposure_axis_id, leverage_axis_id],
        }
    elif _runtime_policy_is(plan, "archive_vote_play"):
        base = {
            "procedural": [institutional_axis_id, exposure_axis_id, leverage_axis_id, pressure_axis_id],
            "coalition": [leverage_axis_id, institutional_axis_id, support_axis_id, exposure_axis_id],
            "public": [public_axis_id, leverage_axis_id, institutional_axis_id, pressure_axis_id],
            "coercive": [public_axis_id, pressure_axis_id, institutional_axis_id, leverage_axis_id],
        }
    elif _runtime_policy_is(plan, "bridge_ration_play"):
        base = {
            "procedural": [resource_axis_id, pressure_axis_id, leverage_axis_id, support_axis_id],
            "coalition": [leverage_axis_id, resource_axis_id, support_axis_id, pressure_axis_id],
            "public": [public_axis_id, leverage_axis_id, resource_axis_id, pressure_axis_id],
            "coercive": [public_axis_id, pressure_axis_id, resource_axis_id, leverage_axis_id],
        }
    elif _runtime_policy_is(plan, "harbor_quarantine_play"):
        base = {
            "procedural": [resource_axis_id, leverage_axis_id, pressure_axis_id, support_axis_id],
            "coalition": [leverage_axis_id, resource_axis_id, support_axis_id, pressure_axis_id],
            "public": [public_axis_id, leverage_axis_id, resource_axis_id, pressure_axis_id],
            "coercive": [public_axis_id, pressure_axis_id, resource_axis_id, leverage_axis_id],
        }
    elif _runtime_policy_is(plan, "blackout_council_play", "public_order_play"):
        base = {
            "procedural": [institutional_axis_id, leverage_axis_id, pressure_axis_id, exposure_axis_id],
            "coalition": [leverage_axis_id, support_axis_id, institutional_axis_id, pressure_axis_id],
            "public": [public_axis_id, leverage_axis_id, institutional_axis_id, pressure_axis_id],
            "coercive": [public_axis_id, pressure_axis_id, leverage_axis_id, institutional_axis_id],
        }
    else:
        base = {
            "procedural": [pressure_axis_id, exposure_axis_id, leverage_axis_id, support_axis_id],
            "coalition": [support_axis_id, leverage_axis_id, pressure_axis_id, exposure_axis_id],
            "public": [public_axis_id, leverage_axis_id, pressure_axis_id, support_axis_id],
            "coercive": [public_axis_id, pressure_axis_id, leverage_axis_id, support_axis_id],
        }

    candidates = list(base.get(execution_frame, base["procedural"]))
    if applied_tag in {"contain_chaos", "protect_civilians"}:
        candidates = [public_axis_id, support_axis_id, pressure_axis_id, resource_axis_id]
    elif applied_tag == "secure_resources":
        candidates = [resource_axis_id, leverage_axis_id, support_axis_id, public_axis_id, pressure_axis_id]
    elif applied_tag in {"build_trust", "unlock_ally"}:
        candidates = [support_axis_id, leverage_axis_id, institutional_axis_id, pressure_axis_id]
    elif applied_tag == "shift_public_narrative":
        candidates = [leverage_axis_id, public_axis_id, support_axis_id, institutional_axis_id]
    elif applied_tag == "pay_cost":
        candidates = [pressure_axis_id, public_axis_id, leverage_axis_id]

    if private_audit:
        candidates = [axis_id for axis_id in candidates if axis_id != public_axis_id] + [public_axis_id]
    elif public_escalation and public_axis_id not in candidates[:2]:
        candidates = [public_axis_id, *candidates]

    ordered: list[str] = []
    seen: set[str] = set()
    for axis_id in candidates:
        if not axis_id or axis_id in seen or axis_id not in _axis_lookup(plan):
            continue
        seen.add(axis_id)
        ordered.append(axis_id)
    return ordered


def _dominant_positive_axis(axis_changes: dict[str, int]) -> str | None:
    positive = [(axis_id, delta) for axis_id, delta in axis_changes.items() if delta > 0]
    if not positive:
        return None
    positive.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return positive[0][0]


def _apply_axis_repetition_guard(
    plan: PlayPlan,
    state: PlaySessionState,
    *,
    axis_changes: dict[str, int],
    preferred_axes: list[str],
) -> dict[str, int]:
    dominant_axis = _dominant_positive_axis(axis_changes)
    if dominant_axis is None:
        return axis_changes
    if len(state.primary_axis_history) < 2:
        return axis_changes
    if state.primary_axis_history[-1] != dominant_axis or state.primary_axis_history[-2] != dominant_axis:
        return axis_changes
    alternative_axis = _first_existing_axis(plan, preferred_axes, exclude={dominant_axis})
    if alternative_axis is None:
        return axis_changes
    adjusted = dict(axis_changes)
    adjusted[dominant_axis] = max(adjusted.get(dominant_axis, 0) - 1, 0)
    if adjusted[dominant_axis] == 0:
        adjusted.pop(dominant_axis, None)
    adjusted[alternative_axis] = adjusted.get(alternative_axis, 0) + 1
    return adjusted


def _apply_stance_repetition_guard(
    state: PlaySessionState,
    *,
    target_npc_ids: list[str],
    plan: PlayPlan,
    stance_changes: dict[str, int],
    execution_frame: str,
) -> dict[str, int]:
    negative_stances = [stance_id for stance_id, delta in stance_changes.items() if delta < 0]
    if len(state.negative_stance_history) < 2 or not negative_stances:
        return stance_changes
    repeated_stance = negative_stances[0]
    if state.negative_stance_history[-1] != repeated_stance or state.negative_stance_history[-2] != repeated_stance:
        return stance_changes
    candidate_stances = [
        stance.stance_id
        for stance in plan.stances
        if stance.npc_id in target_npc_ids and stance.stance_id != repeated_stance
    ]
    adjusted = dict(stance_changes)
    if candidate_stances:
        adjusted.pop(repeated_stance, None)
        adjusted[candidate_stances[0]] = -1
        return adjusted
    if execution_frame in {"procedural", "coalition"}:
        adjusted.pop(repeated_stance, None)
    return adjusted


def _axis_label(plan: PlayPlan, axis_id: str | None) -> str:
    if not axis_id:
        return "Pressure"
    axis = next((item for item in plan.axes if item.axis_id == axis_id), None)
    return axis.label if axis is not None else axis_id.replace("_", " ").title()


def _apply_minimum_feedback_semantics(
    plan: PlayPlan,
    state: PlaySessionState,
    beat: BeatSpec,
    *,
    applied_tag: str,
    risk_level: str,
    execution_frame: str,
    tactic_summary: str,
    off_route: bool,
    target_npc_ids: list[str],
    axis_changes: dict[str, int],
    stance_changes: dict[str, int],
) -> tuple[dict[str, int], dict[str, int]]:
    pressure_axis_id = _pressure_axis_id(plan, beat)
    public_axis_id = _public_pressure_axis_id(plan)
    support_axis_id = _support_axis_id(plan)
    resource_axis_id = _resource_axis_id(plan)
    exposure_axis_id = _exposure_axis_id(plan)
    institutional_axis_id = _institutional_axis_id(plan)
    leverage_axis_id = "political_leverage" if "political_leverage" in _axis_lookup(plan) else support_axis_id
    conflict_npcs = set(beat.conflict_npcs)
    public_escalation = _is_public_escalation_tactic(tactic_summary)
    private_audit = _is_private_audit_tactic(tactic_summary)
    preferred_axes = _execution_frame_axis_preferences(
        plan,
        applied_tag=applied_tag,
        execution_frame=execution_frame,
        public_escalation=public_escalation,
        private_audit=private_audit,
    )
    dominant_preferred_axis = _first_existing_axis(plan, preferred_axes)
    if (
        applied_tag in {"reveal_truth", "build_trust", "unlock_ally", "shift_public_narrative", "secure_resources"}
        and dominant_preferred_axis
        and dominant_preferred_axis != pressure_axis_id
        and axis_changes.get(pressure_axis_id, 0) > 0
    ):
        axis_changes.pop(pressure_axis_id, None)

    if applied_tag == "reveal_truth":
        primary_axis = _first_existing_axis(plan, preferred_axes) or exposure_axis_id or pressure_axis_id
        axis_changes[primary_axis] = axis_changes.get(primary_axis, 0) + 1
        if execution_frame == "coalition" and leverage_axis_id and leverage_axis_id != primary_axis:
            axis_changes[leverage_axis_id] = axis_changes.get(leverage_axis_id, 0) + 1
        if execution_frame in {"public", "coercive"} or public_escalation:
            axis_changes[public_axis_id] = axis_changes.get(public_axis_id, 0) + 1
        if execution_frame == "coercive":
            axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) + 1
        if resource_axis_id and beat.pressure_axis_id == resource_axis_id:
            axis_changes[resource_axis_id] = axis_changes.get(resource_axis_id, 0) + 1
    elif applied_tag in {"contain_chaos", "protect_civilians"}:
        if execution_frame == "public":
            axis_changes[public_axis_id] = axis_changes.get(public_axis_id, 0) - 1
        elif execution_frame == "coercive":
            axis_changes[public_axis_id] = axis_changes.get(public_axis_id, 0) + 1
            axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) + 1
        else:
            axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) - 1
        if support_axis_id:
            axis_changes[support_axis_id] = axis_changes.get(support_axis_id, 0) + 1
        elif leverage_axis_id:
            axis_changes[leverage_axis_id] = axis_changes.get(leverage_axis_id, 0) + 1
    elif applied_tag == "secure_resources":
        if resource_axis_id:
            axis_changes[resource_axis_id] = axis_changes.get(resource_axis_id, 0) - 1
        else:
            axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) - 1
        if execution_frame in {"procedural", "coalition"}:
            if leverage_axis_id:
                axis_changes[leverage_axis_id] = axis_changes.get(leverage_axis_id, 0) + 1
        if execution_frame in {"public", "coercive"} and (public_escalation or risk_level == "high"):
            axis_changes[public_axis_id] = axis_changes.get(public_axis_id, 0) + 1
    elif applied_tag == "shift_public_narrative":
        if leverage_axis_id:
            axis_changes[leverage_axis_id] = axis_changes.get(leverage_axis_id, 0) + 1
        if execution_frame == "coalition" and support_axis_id:
            axis_changes[support_axis_id] = axis_changes.get(support_axis_id, 0) + 1
        axis_changes[public_axis_id] = axis_changes.get(public_axis_id, 0) + (
            1 if execution_frame in {"public", "coercive"} or risk_level == "high" else -1 if risk_level == "low" else 0
        )
    elif applied_tag in {"build_trust", "unlock_ally"}:
        if support_axis_id:
            axis_changes[support_axis_id] = axis_changes.get(support_axis_id, 0) + 1
        if execution_frame == "public" and leverage_axis_id:
            axis_changes[leverage_axis_id] = axis_changes.get(leverage_axis_id, 0) + 1
    elif applied_tag == "pay_cost":
        axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) + 1
        axis_changes[public_axis_id] = axis_changes.get(public_axis_id, 0) + 1
        if leverage_axis_id and execution_frame in {"public", "coercive"}:
            axis_changes[leverage_axis_id] = axis_changes.get(leverage_axis_id, 0) + 1

    semantic_public_delta = _public_semantic_delta(
        applied_tag=applied_tag,
        risk_level=risk_level,
        tactic_summary=tactic_summary,
    )
    if semantic_public_delta is not None:
        current_delta = axis_changes.get(public_axis_id, 0)
        if current_delta == 0 or current_delta * semantic_public_delta < 0:
            axis_changes[public_axis_id] = semantic_public_delta

    if risk_level == "high" and applied_tag in {"shift_public_narrative", "pay_cost"}:
        axis_changes[public_axis_id] = axis_changes.get(public_axis_id, 0) + 1

    if (
        applied_tag in {"reveal_truth", "secure_resources", "build_trust", "unlock_ally"}
        and execution_frame not in {"public", "coercive"}
        and not _is_public_escalation_tactic(tactic_summary)
        and axis_changes.get(public_axis_id, 0) > 0
    ):
        axis_changes[public_axis_id] = 0

    if _runtime_policy_is(plan, "bridge_ration_play", "harbor_quarantine_play") and applied_tag == "secure_resources":
        axis_changes[public_axis_id] = min(axis_changes.get(public_axis_id, 0), 0)

    if _runtime_policy_is(plan, "archive_vote_play") and private_audit:
        axis_changes[public_axis_id] = min(axis_changes.get(public_axis_id, 0), 0)

    if off_route and not axis_changes:
        axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) + 1

    axis_changes = _apply_axis_repetition_guard(
        plan,
        state,
        axis_changes=axis_changes,
        preferred_axes=preferred_axes,
    )

    for stance in plan.stances:
        if stance.npc_id not in target_npc_ids:
            continue
        if stance.stance_id in stance_changes and stance_changes[stance.stance_id] != 0:
            continue
        if applied_tag in {"build_trust", "unlock_ally"}:
            stance_changes[stance.stance_id] = 1
        elif applied_tag in {"contain_chaos", "protect_civilians"}:
            if execution_frame == "coalition":
                stance_changes[stance.stance_id] = 1
        elif applied_tag == "reveal_truth":
            if execution_frame == "coalition" and stance.npc_id not in conflict_npcs:
                stance_changes[stance.stance_id] = 1
            elif execution_frame in {"public", "coercive"} and (stance.npc_id in conflict_npcs or risk_level == "high"):
                stance_changes[stance.stance_id] = -1
        elif applied_tag == "secure_resources":
            if execution_frame == "coalition":
                stance_changes[stance.stance_id] = 1
            elif execution_frame == "procedural":
                if stance.npc_id not in conflict_npcs:
                    stance_changes[stance.stance_id] = 1
            elif stance.npc_id in conflict_npcs:
                stance_changes[stance.stance_id] = -1
        elif applied_tag == "shift_public_narrative":
            if execution_frame == "coalition":
                stance_changes[stance.stance_id] = 1
            elif execution_frame in {"public", "coercive"} and (stance.npc_id in conflict_npcs or risk_level == "high"):
                stance_changes[stance.stance_id] = -1
        elif applied_tag == "pay_cost":
            stance_changes[stance.stance_id] = -1

    stance_changes = _apply_stance_repetition_guard(
        state,
        target_npc_ids=target_npc_ids,
        plan=plan,
        stance_changes=stance_changes,
        execution_frame=execution_frame,
    )

    return {key: value for key, value in axis_changes.items() if value != 0}, {key: value for key, value in stance_changes.items() if value != 0}


def _update_feedback_ledgers(
    state: PlaySessionState,
    plan: PlayPlan,
    *,
    applied_tag: str,
    risk_level: str,
    off_route: bool,
    beat_completed: bool,
    revealed_truth_ids: list[str],
    added_event_ids: list[str],
    axis_deltas: dict[str, int],
    stance_deltas: dict[str, int],
) -> tuple[list[str], list[str]]:
    success = state.success_ledger
    cost = state.cost_ledger
    tags: list[str] = []
    consequences: list[str] = []

    pressure_axis_ids = {axis.axis_id for axis in plan.axes if axis.kind == "pressure"}
    public_axis_id = _public_pressure_axis_id(plan)
    support_axis_id = _support_axis_id(plan)
    resource_axis_id = _resource_axis_id(plan)
    public_delta = axis_deltas.get(public_axis_id, 0)
    support_delta = axis_deltas.get(support_axis_id, 0)
    resource_delta = axis_deltas.get(resource_axis_id, 0) if resource_axis_id is not None else 0
    system_delta = axis_deltas.get("system_integrity", 0)
    pressure_rise_cost = sum(
        delta
        for axis_id, delta in axis_deltas.items()
        if axis_id in pressure_axis_ids and delta > 0
    )
    nonpublic_pressure_increase = next(
        (
            axis_id
            for axis_id, delta in axis_deltas.items()
            if delta > 0 and axis_id in pressure_axis_ids and axis_id != public_axis_id
        ),
        None,
    )
    pressure_relief = any(
        delta < 0
        for axis_id, delta in axis_deltas.items()
        if axis_id in pressure_axis_ids and axis_id not in {public_axis_id, support_axis_id}
    )
    relief_axis_id = next(
        (
            axis_id
            for axis_id, delta in axis_deltas.items()
            if delta < 0 and axis_id in pressure_axis_ids and axis_id not in {public_axis_id, support_axis_id}
        ),
        None,
    )
    if applied_tag == "reveal_truth" or revealed_truth_ids:
        success["proof_progress"] = success.get("proof_progress", 0) + 1
        tags.append("truth_exposed")
        consequences.append("Proof moved into the open.")
    if applied_tag in {"build_trust", "unlock_ally"} or any(delta > 0 for delta in stance_deltas.values()):
        success["coalition_progress"] = success.get("coalition_progress", 0) + 1
        tags.append("coalition_strengthened")
        consequences.append("A relationship shifted inside the coalition.")
    if applied_tag in {"contain_chaos", "protect_civilians", "secure_resources"} or public_delta < 0 or resource_delta < 0 or pressure_relief:
        success["order_progress"] = success.get("order_progress", 0) + 1
        if public_delta < 0:
            tags.extend(["order_stabilized", "panic_reduced"])
            consequences.append("Visible public pressure eased.")
        elif resource_delta < 0:
            tags.append("order_stabilized")
            consequences.append("Resource strain eased.")
        elif pressure_relief:
            tags.append("order_stabilized")
            consequences.append(f"{_axis_label(plan, relief_axis_id)} eased.")
        elif support_delta > 0:
            consequences.append("You gained room to maneuver inside the coalition.")
    if applied_tag in {"shift_public_narrative", "pay_cost"} or beat_completed or added_event_ids:
        success["settlement_progress"] = success.get("settlement_progress", 0) + 1
        tags.append("settlement_advanced")
        consequences.append("The crisis moved closer to a binding outcome.")

    if public_delta > 0:
        cost["public_cost"] = cost.get("public_cost", 0) + public_delta
        tags.append("public_pressure_rising")
        consequences.append("Visible public pressure rose.")
    elif system_delta > 0:
        cost["public_cost"] = cost.get("public_cost", 0) + system_delta
        tags.append("institutional_strain_rising")
        consequences.append("Institutional strain rose.")
    elif resource_delta > 0:
        cost["public_cost"] = cost.get("public_cost", 0) + resource_delta
        tags.append("resource_strain_rising")
        consequences.append("Resource strain rose.")
    elif nonpublic_pressure_increase is not None:
        cost["public_cost"] = cost.get("public_cost", 0) + pressure_rise_cost
        tags.append("pressure_shifted")
        consequences.append(f"{_axis_label(plan, nonpublic_pressure_increase)} rose.")
    if any(delta < 0 for delta in stance_deltas.values()):
        cost["relationship_cost"] = cost.get("relationship_cost", 0) + sum(abs(delta) for delta in stance_deltas.values() if delta < 0)
        tags.append("coalition_strained")
        consequences.append("At least one relationship took damage.")
    if off_route:
        cost["procedural_cost"] = cost.get("procedural_cost", 0) + 1
        tags.append("procedural_loss")
        consequences.append("The move came with procedural slippage.")
    if applied_tag == "pay_cost" or (risk_level == "high" and applied_tag in {"shift_public_narrative", "secure_resources"}):
        cost["coercion_cost"] = cost.get("coercion_cost", 0) + 1
        tags.append("coercive_fix")
        consequences.append("Progress came through a coercive or costly push.")

    if not tags:
        success["order_progress"] = success.get("order_progress", 0) + 1
        tags.append("momentum_shifted")
        consequences.append("The balance of the scene moved.")
    return unique_preserve(tags)[:8], unique_preserve(consequences)[:8]


def _highest_pressure_axis_value(plan: PlayPlan, state: PlaySessionState) -> tuple[str, int]:
    pressure_axes = [axis for axis in plan.axes if axis.kind == "pressure"]
    if not pressure_axes:
        axis = plan.axes[0]
        return axis.axis_id, state.axis_values.get(axis.axis_id, axis.starting_value)
    best = max(
        pressure_axes,
        key=lambda axis: state.axis_values.get(axis.axis_id, axis.starting_value),
    )
    return best.axis_id, state.axis_values.get(best.axis_id, best.starting_value)


def _maybe_complete_beat(plan: PlayPlan, state: PlaySessionState) -> tuple[bool, bool, list[str]]:
    beat = _current_beat(plan, state)
    is_final_beat = state.beat_index >= len(plan.beats) - 1
    progress_threshold = 1 if is_final_beat else beat.progress_required
    if state.beat_progress < progress_threshold:
        return False, False, []
    added_events: list[str] = []
    if beat.required_events:
        event_id = beat.required_events[0]
        if event_id not in state.discovered_event_ids:
            state.discovered_event_ids.append(event_id)
            added_events.append(event_id)
    if is_final_beat:
        return True, False, added_events
    state.beat_index += 1
    state.beat_progress = 0
    state.beat_detours_used = 0
    return True, True, added_events
def apply_turn_resolution(
    *,
    plan: PlayPlan,
    state: PlaySessionState,
    intent: PlayTurnIntentDraft,
    use_tuned_ending_policy: bool = True,
) -> tuple[PlayResolutionEffect, TurnEndingGateContext]:
    if getattr(plan, "story_mode", "relationship_drama") == "relationship_drama":
        from rpg_backend.play.relationship_runtime import apply_relationship_turn_resolution

        resolution = apply_relationship_turn_resolution(plan=plan, state=state, intent=intent)
        ending_context = TurnEndingGateContext(
            final_beat_completed=bool(resolution.beat_completed and state.beat_index >= len(plan.beats) - 1),
            final_beat_handoff=bool(resolution.advanced_to_next_beat and state.beat_index >= len(plan.beats) - 1),
            turn_cap_reached=state.turn_index >= plan.max_turns,
        )
        return resolution, ending_context
    beat = _current_beat(plan, state)
    execution_frame = getattr(intent, "execution_frame", "procedural")
    target_npc_ids = [
        npc_id
        for npc_id in intent.target_npc_ids
        if npc_id and npc_id != plan.protagonist_npc_id
    ]
    available_tags = available_affordance_tags(plan, state)
    off_route = intent.affordance_tag not in available_tags or intent.affordance_tag in beat.blocked_affordances
    applied_tag = intent.affordance_tag if intent.affordance_tag in plan.available_affordance_tags else available_tags[0]
    profile = next((item for item in plan.affordance_effect_profiles if item.affordance_tag == applied_tag), None)
    if profile is None:
        profile = next(item for item in plan.affordance_effect_profiles if item.affordance_tag == available_tags[0])
        applied_tag = profile.affordance_tag
    pressure_axis_id = _pressure_axis_id(plan, beat)
    axis_changes = dict(profile.axis_deltas)
    stance_changes = dict(profile.stance_deltas)
    flag_changes: dict[str, bool] = {}
    if off_route:
        axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) + 1
        state.beat_detours_used += 1
    if intent.risk_level == "high":
        axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) + 1
    if intent.risk_level == "low" and applied_tag == beat.route_pivot_tag:
        axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) - 1
    axis_changes, stance_changes = _apply_minimum_feedback_semantics(
        plan,
        state,
        beat,
        applied_tag=applied_tag,
        risk_level=intent.risk_level,
        execution_frame=execution_frame,
        tactic_summary=intent.tactic_summary,
        off_route=off_route,
        target_npc_ids=target_npc_ids,
        axis_changes=axis_changes,
        stance_changes=stance_changes,
    )
    if state.beat_detours_used > beat.detour_budget:
        axis_changes[pressure_axis_id] = axis_changes.get(pressure_axis_id, 0) + 1
    applied_axis_changes = _apply_axis_changes(plan, state, axis_changes)
    applied_stance_changes = _apply_stance_changes(plan, state, stance_changes)
    revealed_truth_ids: list[str] = []
    if profile.can_add_truth:
        truth_id = _next_truth_id(plan, state, beat)
        if truth_id is not None and truth_id not in state.discovered_truth_ids:
            state.discovered_truth_ids.append(truth_id)
            revealed_truth_ids.append(truth_id)
    if plan.flags:
        flag_id = plan.flags[0].flag_id
        if applied_tag == "shift_public_narrative":
            state.flag_values[flag_id] = True
            flag_changes[flag_id] = True
        elif applied_tag == "pay_cost" and state.flag_values.get(flag_id):
            state.flag_values[flag_id] = False
            flag_changes[flag_id] = False
    state.beat_progress += 1
    beat_completed, advanced_to_next_beat, added_event_ids = _maybe_complete_beat(plan, state)
    pressure_axis_id, pressure_value = _highest_pressure_axis_value(plan, state)
    pressure_axis = next(axis for axis in plan.axes if axis.axis_id == pressure_axis_id)
    final_beat_completed = beat_completed and not advanced_to_next_beat and state.beat_index >= len(plan.beats) - 1
    final_beat_handoff = advanced_to_next_beat and state.beat_index >= len(plan.beats) - 1 and state.turn_index >= 4 if use_tuned_ending_policy else False
    pressure_note = "The situation bends, but it does not stall."
    if off_route:
        pressure_note = "You make progress, but the move comes with extra pressure."
    elif intent.risk_level == "high":
        pressure_note = "You force the issue and raise the temperature across the scene."
    last_turn_tags, last_turn_consequences = _update_feedback_ledgers(
        state,
        plan,
        applied_tag=applied_tag,
        risk_level=intent.risk_level,
        off_route=off_route,
        beat_completed=beat_completed,
        revealed_truth_ids=revealed_truth_ids,
        added_event_ids=added_event_ids,
        axis_deltas=applied_axis_changes,
        stance_deltas=applied_stance_changes,
    )
    state.last_turn_axis_deltas = dict(applied_axis_changes)
    state.last_turn_stance_deltas = dict(applied_stance_changes)
    state.last_turn_tags = list(last_turn_tags)
    state.last_turn_consequences = list(last_turn_consequences)
    _update_collapse_pressure_streak(
        plan,
        state,
        pressure_axis_id=pressure_axis_id,
        pressure_value=pressure_value,
        use_tuned_ending_policy=use_tuned_ending_policy,
    )
    primary_axis = _dominant_positive_axis(applied_axis_changes)
    if primary_axis is not None:
        state.primary_axis_history.append(primary_axis)
        state.primary_axis_history = state.primary_axis_history[-4:]
    negative_stances = [stance_id for stance_id, delta in applied_stance_changes.items() if delta < 0]
    if negative_stances:
        state.negative_stance_history.append(negative_stances[0])
        state.negative_stance_history = state.negative_stance_history[-4:]
    return (
        PlayResolutionEffect(
        affordance_tag=applied_tag,
        risk_level=intent.risk_level,
        execution_frame=execution_frame,
        target_npc_ids=target_npc_ids,
        tactic_summary=intent.tactic_summary,
        off_route=off_route,
        axis_changes=applied_axis_changes,
        stance_changes=applied_stance_changes,
        flag_changes=flag_changes,
        revealed_truth_ids=revealed_truth_ids,
        added_event_ids=added_event_ids,
        beat_completed=beat_completed,
        advanced_to_next_beat=advanced_to_next_beat,
        ending_id=None,
        ending_trigger_reason=None,
        pressure_note=pressure_note,
        ),
        TurnEndingGateContext(
            final_beat_completed=bool(final_beat_completed or final_beat_handoff),
            final_beat_handoff=final_beat_handoff,
            turn_cap_reached=state.turn_index >= plan.max_turns,
        ),
    )
def resolve_turn(
    *,
    plan: PlayPlan,
    state: PlaySessionState,
    intent: PlayTurnIntentDraft,
    use_tuned_ending_policy: bool = True,
    proposed_ending_id: str | None = None,
    enable_pyrrhic_judge_relaxation: bool = True,
) -> PlayResolutionEffect:
    from rpg_backend.play.closeout import finalize_turn_ending

    resolution, ending_context = apply_turn_resolution(
        plan=plan,
        state=state,
        intent=intent,
        use_tuned_ending_policy=use_tuned_ending_policy,
    )
    return finalize_turn_ending(
        plan=plan,
        state=state,
        resolution=resolution,
        ending_context=ending_context,
        proposed_ending_id=proposed_ending_id,
        use_tuned_ending_policy=use_tuned_ending_policy,
        enable_pyrrhic_judge_relaxation=enable_pyrrhic_judge_relaxation,
    )


def deterministic_narration(
    *,
    plan: PlayPlan,
    state: PlaySessionState,
    resolution: PlayResolutionEffect,
) -> str:
    intro_templates = {
        "build_trust": "You tighten a fragile alliance",
        "contain_chaos": "You move before the room can tip into disorder",
        "pay_cost": "You force the issue through visible cost",
        "protect_civilians": "You put yourself between the crowd and the break",
        "reveal_truth": "You drag the hidden record into the open",
        "secure_resources": "You force scarce resources back into public view",
        "shift_public_narrative": "You turn the public story before it hardens against you",
        "unlock_ally": "You pull a wavering ally back into the coalition",
    }
    beat = _current_beat(plan, state)
    target_names = [
        npc.name
        for npc in plan.cast
        if npc.npc_id != plan.protagonist_npc_id and npc.npc_id in resolution.target_npc_ids
    ]
    target_clause = f" with {', '.join(target_names)}" if target_names else ""
    lines = [
        f"{intro_templates.get(resolution.affordance_tag, 'You force the scene to move')}{target_clause}.",
        resolution.pressure_note,
    ]
    if resolution.revealed_truth_ids:
        truth = next((item.text for item in plan.truths if item.truth_id == resolution.revealed_truth_ids[0]), None)
        if truth:
            lines.append(f"A buried truth breaks into the open: {truth}")
    if state.last_turn_consequences:
        consequence_line = state.last_turn_consequences[0].rstrip(".")
        if consequence_line and consequence_line.casefold() not in " ".join(lines).casefold():
            lines.append(f"The consequence lands immediately: {consequence_line}.")
    if resolution.beat_completed and state.status != "completed":
        lines.append(f"The story shifts into {beat.title.lower()}, and the next pressure point comes into focus.")
    if state.ending is not None:
        lines.append(f"The ending locks into {state.ending.label.lower()}. {state.ending.summary}")
    return trim_ellipsis(" ".join(lines), 4000)
