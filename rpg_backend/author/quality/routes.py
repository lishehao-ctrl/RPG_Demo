from __future__ import annotations

from rpg_backend.author.compiler.rules import bundle_affordance_tags
from rpg_backend.author.contracts import DesignBundle, RouteAffordancePackDraft


def _has_condition_content(conditions) -> bool:  # noqa: ANN001
    return any(
        getattr(conditions, key)
        for key in (
            "min_axes",
            "max_axes",
            "min_stances",
            "required_truths",
            "required_events",
            "required_flags",
        )
    )


def route_affordance_pack_quality_reasons(
    route_affordance_pack: RouteAffordancePackDraft,
    bundle: DesignBundle,
) -> list[str]:
    reasons: list[str] = []
    if not route_affordance_pack.route_unlock_rules:
        reasons.append("missing_route_unlock_rules")
        return reasons
    if not any(_has_condition_content(item.conditions) for item in route_affordance_pack.route_unlock_rules):
        reasons.append("route_conditions_empty")
    unique_beats = {item.beat_id for item in route_affordance_pack.route_unlock_rules}
    required_beat_coverage = min(3, len(bundle.beat_spine))
    if len(bundle.beat_spine) > 1 and len(unique_beats) < required_beat_coverage:
        reasons.append("route_beat_coverage_too_narrow")
    unique_tags = {item.unlock_affordance_tag for item in route_affordance_pack.route_unlock_rules}
    required_tag_coverage = min(3, len(bundle.beat_spine), len(bundle_affordance_tags(bundle)))
    if len(unique_tags) < required_tag_coverage:
        reasons.append("route_tag_diversity_too_narrow")
    return reasons
