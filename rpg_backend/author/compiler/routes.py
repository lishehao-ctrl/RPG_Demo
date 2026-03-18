from __future__ import annotations

from typing import Any

from rpg_backend.author.contracts import (
    AffordanceEffectProfile,
    BeatSpec,
    DesignBundle,
    RouteAffordancePackDraft,
    RouteOpportunityPlanDraft,
    RouteUnlockRule,
)
from rpg_backend.author.normalize import slugify, unique_preserve


def normalize_affordance_tag(value: str) -> str:
    normalized = slugify(value)
    mapping = {
        "reveal": "reveal_truth",
        "investigate": "reveal_truth",
        "build": "build_trust",
        "trust": "build_trust",
        "support": "build_trust",
        "stabilize": "contain_chaos",
        "protect": "protect_civilians",
        "narrative": "shift_public_narrative",
        "public": "shift_public_narrative",
        "resource": "secure_resources",
        "ally": "unlock_ally",
        "cost": "pay_cost",
    }
    return mapping.get(normalized, normalized)


def default_story_function_for_tag(tag: str) -> str:
    normalized = normalize_affordance_tag(tag)
    if normalized == "reveal_truth":
        return "reveal"
    if normalized == "contain_chaos":
        return "stabilize"
    if normalized == "pay_cost":
        return "pay_cost"
    return "advance"


def bundle_affordance_tags(bundle: DesignBundle) -> list[str]:
    affordance_tags = sorted({weight.tag for beat in bundle.beat_spine for weight in beat.affordances})
    if len(affordance_tags) < 2:
        for fallback_tag in ("reveal_truth", "build_trust"):
            if fallback_tag not in affordance_tags:
                affordance_tags.append(fallback_tag)
            if len(affordance_tags) >= 2:
                break
    return affordance_tags


def normalize_route_affordance_pack(
    route_affordance_pack: RouteAffordancePackDraft,
    bundle: DesignBundle,
) -> RouteAffordancePackDraft:
    beat_ids = {beat.beat_id for beat in bundle.beat_spine}
    affordance_tags = set(bundle_affordance_tags(bundle))
    axis_ids = {axis.axis_id for axis in bundle.state_schema.axes}
    stance_ids = {stance.stance_id for stance in bundle.state_schema.stances}
    flag_ids = {flag.flag_id for flag in bundle.state_schema.flags}
    truth_ids = {truth.truth_id for truth in bundle.story_bible.truth_catalog}
    event_ids = {event for beat in bundle.beat_spine for event in beat.required_events}

    normalized_routes = []
    for rule in route_affordance_pack.route_unlock_rules:
        if rule.beat_id not in beat_ids or rule.unlock_affordance_tag not in affordance_tags:
            continue
        if any(key not in axis_ids for key in (*rule.conditions.min_axes.keys(), *rule.conditions.max_axes.keys())):
            continue
        if any(key not in stance_ids for key in rule.conditions.min_stances.keys()):
            continue
        if any(item not in truth_ids for item in rule.conditions.required_truths):
            continue
        if any(item not in event_ids for item in rule.conditions.required_events):
            continue
        if any(item not in flag_ids for item in rule.conditions.required_flags):
            continue
        normalized_routes.append(rule)

    profile_by_tag = {profile.affordance_tag: profile for profile in route_affordance_pack.affordance_effect_profiles}
    normalized_profiles = []
    for tag in sorted(affordance_tags):
        if tag in profile_by_tag:
            normalized_profiles.append(profile_by_tag[tag])
            continue
        default_story_function = default_story_function_for_tag(tag)
        normalized_profiles.append(
            AffordanceEffectProfile(
                affordance_tag=tag,
                default_story_function=default_story_function,  # type: ignore[arg-type]
                axis_deltas={},
                stance_deltas={},
                can_add_truth=default_story_function == "reveal",
                can_add_event=default_story_function in {"advance", "pay_cost"},
            )
        )

    return RouteAffordancePackDraft(
        route_unlock_rules=normalized_routes,
        affordance_effect_profiles=normalized_profiles,
    )


def build_deterministic_affordance_profiles(bundle: DesignBundle) -> list[AffordanceEffectProfile]:
    affordance_tags = bundle_affordance_tags(bundle)
    axes_by_id = {axis.axis_id: axis for axis in bundle.state_schema.axes}
    pressure_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "pressure"), bundle.state_schema.axes[0].axis_id)
    relationship_axis = next(
        (axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "relationship" and axis.axis_id != pressure_axis),
        pressure_axis,
    )
    resource_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "resource"), relationship_axis)
    exposure_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "exposure"), pressure_axis)
    panic_axis = "public_panic" if "public_panic" in axes_by_id else pressure_axis
    leverage_axis = "political_leverage" if "political_leverage" in axes_by_id else relationship_axis
    ally_axis = "ally_trust" if "ally_trust" in axes_by_id else relationship_axis
    first_stance_id = bundle.state_schema.stances[0].stance_id if bundle.state_schema.stances else None
    profiles = []
    for tag in affordance_tags:
        default_story_function = default_story_function_for_tag(tag)
        axis_deltas: dict[str, int] = {}
        stance_deltas: dict[str, int] = {}
        if tag == "reveal_truth":
            axis_deltas = {exposure_axis: 1}
        elif tag == "build_trust":
            axis_deltas = {ally_axis: 1}
        elif tag == "contain_chaos":
            axis_deltas = {panic_axis: -1}
        elif tag == "shift_public_narrative":
            axis_deltas = {leverage_axis: 1}
            if panic_axis != leverage_axis:
                axis_deltas[panic_axis] = -1
        elif tag == "protect_civilians":
            axis_deltas = {pressure_axis: -1}
        elif tag == "secure_resources":
            axis_deltas = {resource_axis: -1}
        elif tag == "unlock_ally":
            if first_stance_id:
                stance_deltas = {first_stance_id: 1}
            else:
                axis_deltas = {ally_axis: 1}
        elif tag == "pay_cost":
            axis_deltas = {pressure_axis: 1}
        profiles.append(
            AffordanceEffectProfile(
                affordance_tag=tag,
                default_story_function=default_story_function,  # type: ignore[arg-type]
                axis_deltas=axis_deltas,
                stance_deltas=stance_deltas,
                can_add_truth=default_story_function == "reveal",
                can_add_event=default_story_function in {"advance", "pay_cost"},
            )
        )
    return profiles


def _default_route_trigger_payload(bundle: DesignBundle, beat_index: int) -> dict[str, Any]:
    pressure_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "pressure"), bundle.state_schema.axes[0].axis_id)
    beat = bundle.beat_spine[beat_index]
    if beat.required_truths:
        return {"kind": "truth", "target_id": beat.required_truths[0]}
    if beat_index > 0:
        return {"kind": "event", "target_id": bundle.beat_spine[beat_index - 1].required_events[0]}
    if bundle.state_schema.flags:
        return {"kind": "flag", "target_id": bundle.state_schema.flags[0].flag_id}
    if bundle.state_schema.stances:
        return {"kind": "stance", "target_id": bundle.state_schema.stances[0].stance_id, "min_value": 1}
    return {"kind": "axis", "target_id": pressure_axis, "min_value": 2}


def _preferred_route_tags_for_beat(beat: BeatSpec) -> list[str]:
    tags = [beat.route_pivot_tag] if beat.route_pivot_tag else []
    tags.extend(weight.tag for weight in beat.affordances)
    return unique_preserve([normalize_affordance_tag(tag) for tag in tags if tag])


def _route_supplement_candidate_rows(bundle: DesignBundle) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, beat in enumerate(bundle.beat_spine):
        trigger = _default_route_trigger_payload(bundle, index)
        for tag_index, tag in enumerate(_preferred_route_tags_for_beat(beat)[:3], start=1):
            suffix = "route" if tag_index == 1 else f"route_{tag_index}"
            candidates.append(
                {
                    "beat_id": beat.beat_id,
                    "unlock_route_id": f"{beat.beat_id}_{tag}_{suffix}",
                    "unlock_affordance_tag": tag,
                    "triggers": [dict(trigger)],
                }
            )
    return candidates[:8]


def build_default_route_opportunity_plan(bundle: DesignBundle) -> RouteOpportunityPlanDraft:
    primary_rows = []
    for row in _route_supplement_candidate_rows(bundle):
        if any(existing["beat_id"] == row["beat_id"] for existing in primary_rows):
            continue
        primary_rows.append(row)
    return RouteOpportunityPlanDraft.model_validate({"opportunities": primary_rows[:8]})


def compile_route_opportunity_plan(
    route_opportunity_plan: RouteOpportunityPlanDraft,
    bundle: DesignBundle,
) -> RouteAffordancePackDraft:
    beat_ids = {beat.beat_id for beat in bundle.beat_spine}
    affordance_tags = set(bundle_affordance_tags(bundle))
    axis_ids = {axis.axis_id for axis in bundle.state_schema.axes}
    stance_ids = {stance.stance_id for stance in bundle.state_schema.stances}
    flag_ids = {flag.flag_id for flag in bundle.state_schema.flags}
    truth_ids = {truth.truth_id for truth in bundle.story_bible.truth_catalog}
    event_ids = {event for beat in bundle.beat_spine for event in beat.required_events}
    signatures: set[tuple[str, str, str, tuple[tuple[str, str, int | None], ...]]] = set()
    route_unlock_rules: list[RouteUnlockRule] = []

    def _append_route_rule(opportunity: Any) -> None:
        if opportunity.beat_id not in beat_ids or opportunity.unlock_affordance_tag not in affordance_tags:
            return
        min_axes: dict[str, int] = {}
        min_stances: dict[str, int] = {}
        required_truths: list[str] = []
        required_flags: list[str] = []
        required_events: list[str] = []
        trigger_signature: list[tuple[str, str, int | None]] = []
        for trigger in opportunity.triggers:
            if trigger.kind == "truth" and trigger.target_id in truth_ids:
                required_truths.append(trigger.target_id)
                trigger_signature.append(("truth", trigger.target_id, None))
            elif trigger.kind == "axis" and trigger.target_id in axis_ids:
                threshold = max(1, min(5, trigger.min_value or 2))
                min_axes[trigger.target_id] = threshold
                trigger_signature.append(("axis", trigger.target_id, threshold))
            elif trigger.kind == "stance" and trigger.target_id in stance_ids:
                threshold = max(1, min(3, trigger.min_value or 1))
                min_stances[trigger.target_id] = threshold
                trigger_signature.append(("stance", trigger.target_id, threshold))
            elif trigger.kind == "flag" and trigger.target_id in flag_ids:
                required_flags.append(trigger.target_id)
                trigger_signature.append(("flag", trigger.target_id, None))
            elif trigger.kind == "event" and trigger.target_id in event_ids:
                required_events.append(trigger.target_id)
                trigger_signature.append(("event", trigger.target_id, None))
        if not trigger_signature:
            return
        signature = (
            opportunity.beat_id,
            opportunity.unlock_route_id,
            opportunity.unlock_affordance_tag,
            tuple(sorted(trigger_signature)),
        )
        if signature in signatures:
            return
        signatures.add(signature)
        route_unlock_rules.append(
            RouteUnlockRule(
                rule_id=slugify(f"{opportunity.beat_id}_{opportunity.unlock_route_id}"),
                beat_id=opportunity.beat_id,
                conditions={
                    "min_axes": min_axes,
                    "max_axes": {},
                    "min_stances": min_stances,
                    "required_truths": sorted(set(required_truths)),
                    "required_events": sorted(set(required_events)),
                    "required_flags": sorted(set(required_flags)),
                },
                unlock_route_id=opportunity.unlock_route_id,
                unlock_affordance_tag=opportunity.unlock_affordance_tag,
            )
        )

    for opportunity in route_opportunity_plan.opportunities:
        _append_route_rule(opportunity)
    required_beat_coverage = min(3, len(bundle.beat_spine))
    required_tag_coverage = min(3, len(bundle.beat_spine), len(affordance_tags))
    supplement_candidates = RouteOpportunityPlanDraft.model_validate({"opportunities": _route_supplement_candidate_rows(bundle)}).opportunities
    for candidate in supplement_candidates:
        if len(route_unlock_rules) >= 8:
            break
        covered_beats = {item.beat_id for item in route_unlock_rules}
        covered_tags = {item.unlock_affordance_tag for item in route_unlock_rules}
        needs_beat = len(covered_beats) < required_beat_coverage and candidate.beat_id not in covered_beats
        needs_tag = len(covered_tags) < required_tag_coverage and candidate.unlock_affordance_tag not in covered_tags
        if not needs_beat and not needs_tag:
            continue
        _append_route_rule(candidate)
    return RouteAffordancePackDraft(
        route_unlock_rules=route_unlock_rules,
        affordance_effect_profiles=build_deterministic_affordance_profiles(bundle),
    )


def build_default_route_affordance_pack(bundle: DesignBundle) -> RouteAffordancePackDraft:
    return compile_route_opportunity_plan(build_default_route_opportunity_plan(bundle), bundle)
