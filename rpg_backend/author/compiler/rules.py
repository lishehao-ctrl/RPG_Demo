from __future__ import annotations

from rpg_backend.author.compiler.endings import (
    ENDING_PRIORITY_BY_ID,
    _canonical_ending_priority,
    build_default_ending_intent,
    build_default_ending_rules,
    build_ending_skeleton,
    compile_ending_intent_draft,
    merge_ending_anchor_suggestions,
    normalize_ending_anchor_suggestions,
    normalize_ending_intent_draft,
    normalize_ending_rules_draft,
)
from rpg_backend.author.compiler.routes import (
    bundle_affordance_tags,
    default_story_function_for_tag,
    build_default_route_affordance_pack,
    build_default_route_opportunity_plan,
    build_deterministic_affordance_profiles,
    compile_route_opportunity_plan,
    normalize_route_affordance_pack,
)
from rpg_backend.author.contracts import EndingRulesDraft, RouteAffordancePackDraft, RulePack, DesignBundle


def merge_rule_pack(
    route_affordance_pack: RouteAffordancePackDraft,
    ending_rules_draft: EndingRulesDraft,
) -> RulePack:
    return RulePack(
        route_unlock_rules=route_affordance_pack.route_unlock_rules,
        ending_rules=ending_rules_draft.ending_rules,
        affordance_effect_profiles=route_affordance_pack.affordance_effect_profiles,
    )


def normalize_rule_pack(rule_pack: RulePack, bundle: DesignBundle) -> RulePack:
    normalized_route_affordance_pack = normalize_route_affordance_pack(
        RouteAffordancePackDraft(
            route_unlock_rules=rule_pack.route_unlock_rules,
            affordance_effect_profiles=rule_pack.affordance_effect_profiles,
        ),
        bundle,
    )
    normalized_ending_rules = normalize_ending_rules_draft(
        EndingRulesDraft(ending_rules=rule_pack.ending_rules),
        bundle,
    )
    return merge_rule_pack(normalized_route_affordance_pack, normalized_ending_rules)


def build_default_rule_pack(bundle: DesignBundle) -> RulePack:
    return merge_rule_pack(
        build_default_route_affordance_pack(bundle),
        build_default_ending_rules(bundle),
    )


__all__ = [
    "ENDING_PRIORITY_BY_ID",
    "_canonical_ending_priority",
    "bundle_affordance_tags",
    "build_default_ending_intent",
    "build_default_ending_rules",
    "build_default_route_affordance_pack",
    "build_default_route_opportunity_plan",
    "build_default_rule_pack",
    "default_story_function_for_tag",
    "build_deterministic_affordance_profiles",
    "build_ending_skeleton",
    "compile_ending_intent_draft",
    "compile_route_opportunity_plan",
    "merge_ending_anchor_suggestions",
    "merge_rule_pack",
    "normalize_ending_anchor_suggestions",
    "normalize_ending_intent_draft",
    "normalize_ending_rules_draft",
    "normalize_route_affordance_pack",
    "normalize_rule_pack",
]
