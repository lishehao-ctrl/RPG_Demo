from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from rpg_backend.author.checkpointer import get_author_checkpointer, graph_config
from rpg_backend.author.compiler.beats import build_default_beat_plan_draft
from rpg_backend.author.compiler.brief import focus_brief
from rpg_backend.author.compiler.bundle import (
    assemble_story_overview,
    build_default_overview_draft,
    build_design_bundle,
)
from rpg_backend.author.compiler.cast import (
    build_cast_member_from_slot,
    derive_cast_overview_draft,
    is_legitimacy_broker_slot,
    plan_cast_topology,
)
from rpg_backend.author.compiler.endings import (
    build_default_ending_intent,
    build_default_ending_rules,
    build_ending_skeleton,
    compile_ending_intent_draft,
    merge_ending_anchor_suggestions,
    normalize_ending_intent_draft,
)
from rpg_backend.author.compiler.router import plan_brief_theme, plan_story_theme
from rpg_backend.author.compiler.rules import (
    build_default_route_affordance_pack,
    build_default_route_opportunity_plan,
    build_default_rule_pack,
    compile_route_opportunity_plan,
    merge_rule_pack,
    normalize_ending_rules_draft,
    normalize_route_affordance_pack,
    normalize_rule_pack,
)
from rpg_backend.author.compiler.story import build_default_story_frame_draft
from rpg_backend.author.contracts import (
    AuthorBundleRequest,
    BeatPlanDraft,
    BeatSpec,
    CastDraft,
    CastOverviewDraft,
    DesignBundle,
    EndingIntentDraft,
    EndingRulesDraft,
    FocusedBrief,
    OverviewCastDraft,
    RouteAffordancePackDraft,
    RouteOpportunityPlanDraft,
    RulePack,
    StateSchema,
    StoryBible,
    StoryFrameDraft,
)
from rpg_backend.author.gateway import AuthorGatewayError, AuthorLLMGateway, get_author_llm_gateway
from rpg_backend.author.generation import beats as beat_generation
from rpg_backend.author.generation import cast as cast_generation
from rpg_backend.author.generation import endings as ending_generation
from rpg_backend.author.generation import routes as route_generation
from rpg_backend.author.generation import story_frame as story_generation
from rpg_backend.author.quality.beats import beat_plan_quality_reasons
from rpg_backend.author.quality.cast import (
    cast_member_quality_reasons,
    cast_overview_quality_reasons,
    finalize_cast_member_candidate,
)
from rpg_backend.author.quality.endings import (
    ending_intent_quality_reasons,
    ending_rules_quality_reasons,
)
from rpg_backend.author.quality.routes import route_affordance_pack_quality_reasons
from rpg_backend.author.quality.story import (
    story_frame_quality_reasons,
    story_frame_should_repair,
)
from rpg_backend.author.quality.telemetry import QualityTraceRecord, append_quality_trace


class AuthorState(TypedDict, total=False):
    run_id: str
    raw_brief: str
    focused_brief: FocusedBrief
    author_session_response_id: str
    story_frame_draft: StoryFrameDraft
    cast_overview_draft: CastOverviewDraft
    cast_overview_source: str
    cast_member_drafts: list[OverviewCastDraft]
    cast_draft: CastDraft
    cast_topology: str
    cast_topology_reason: str
    brief_primary_theme: str
    brief_theme_modifiers: list[str]
    brief_theme_router_reason: str
    story_frame_strategy: str
    cast_strategy: str
    primary_theme: str
    theme_modifiers: list[str]
    theme_router_reason: str
    beat_plan_strategy: str
    beat_plan_draft: BeatPlanDraft
    story_frame_source: str
    beat_plan_source: str
    route_opportunity_plan_source: str
    route_affordance_source: str
    ending_source: str
    quality_trace: list[QualityTraceRecord]
    story_bible: StoryBible
    state_schema: StateSchema
    beat_spine: list[BeatSpec]
    route_opportunity_plan_draft: RouteOpportunityPlanDraft
    route_affordance_pack_draft: RouteAffordancePackDraft
    ending_intent_draft: EndingIntentDraft
    ending_rules_draft: EndingRulesDraft
    rule_pack: RulePack
    design_bundle: DesignBundle
    llm_call_trace: list[dict[str, Any]]


def _resolved_session_response_id(
    prior_response_id: str | None,
    next_response_id: str | None,
) -> str | None:
    return next_response_id or prior_response_id


def build_author_graph(*, gateway: AuthorLLMGateway | None = None, checkpointer=None):
    resolved_gateway = gateway or get_author_llm_gateway()

    def focus_brief_node(state: AuthorState) -> dict[str, Any]:
        if state.get("focused_brief") is not None:
            return {"focused_brief": state["focused_brief"]}
        return {"focused_brief": focus_brief(state["raw_brief"])}

    def generate_story_frame_node(state: AuthorState) -> dict[str, Any]:
        prior_response_id = state.get("author_session_response_id")
        latest_response_id = prior_response_id
        trace = state.get("quality_trace")
        try:
            generated = story_generation.generate_story_frame(
                resolved_gateway,
                state["focused_brief"],
                previous_response_id=prior_response_id,
                story_frame_strategy=state.get("story_frame_strategy"),
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            story_frame_draft = build_default_story_frame_draft(state["focused_brief"])
            trace = append_quality_trace(
                trace,
                stage="story_frame",
                source="default",
                outcome="fallback",
                reasons=[exc.code],
            )
            return {
                "story_frame_draft": story_frame_draft,
                "story_frame_source": "default",
                "author_session_response_id": latest_response_id,
                "quality_trace": trace,
            }
        story_frame_draft = generated.value
        latest_response_id = _resolved_session_response_id(prior_response_id, generated.response_id)
        story_frame_source = "generated"
        story_frame_outcome = "accepted"
        story_frame_reasons = story_frame_quality_reasons(story_frame_draft, state["focused_brief"])
        if story_frame_should_repair(story_frame_reasons):
            try:
                gleaned = story_generation.glean_story_frame(
                    resolved_gateway,
                    state["focused_brief"],
                    story_frame_draft,
                    previous_response_id=latest_response_id,
                )
                latest_response_id = _resolved_session_response_id(latest_response_id, gleaned.response_id)
                glean_reasons = story_frame_quality_reasons(gleaned.value, state["focused_brief"])
                if not story_frame_should_repair(glean_reasons):
                    story_frame_draft = gleaned.value
                    story_frame_source = "gleaned"
                    story_frame_outcome = "repaired"
                else:
                    story_frame_draft = build_default_story_frame_draft(state["focused_brief"])
                    story_frame_source = "default"
                    story_frame_outcome = "fallback"
                    story_frame_reasons.extend(glean_reasons)
            except AuthorGatewayError as exc:
                if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                    raise
                story_frame_draft = build_default_story_frame_draft(state["focused_brief"])
                story_frame_source = "default"
                story_frame_outcome = "fallback"
                story_frame_reasons.append(exc.code)
        trace = append_quality_trace(
            trace,
            stage="story_frame",
            source=story_frame_source,  # type: ignore[arg-type]
            outcome=story_frame_outcome,  # type: ignore[arg-type]
            reasons=story_frame_reasons if story_frame_outcome != "accepted" else [],
        )
        return {
            "story_frame_draft": story_frame_draft,
            "story_frame_source": story_frame_source,
            "author_session_response_id": latest_response_id,
            "quality_trace": trace,
        }

    def derive_cast_overview_node(state: AuthorState) -> dict[str, Any]:
        topology_plan = plan_cast_topology(state["focused_brief"], state["story_frame_draft"])
        topology_reason = state.get("cast_topology_reason") or topology_plan.planner_reason
        cast_overview = derive_cast_overview_draft(
            state["focused_brief"],
            state["story_frame_draft"],
            topology_override=state.get("cast_topology"),
        )
        trace = append_quality_trace(
            state.get("quality_trace"),
            stage="cast_overview",
            source="default",
            outcome="accepted",
            reasons=[],
            subject=topology_plan.topology,
        )
        return {
            "cast_overview_draft": cast_overview,
            "cast_overview_source": "default",
            "cast_topology": state.get("cast_topology") or topology_plan.topology,
            "cast_topology_reason": topology_reason,
            "quality_trace": trace,
        }

    def plan_story_theme_node(state: AuthorState) -> dict[str, Any]:
        if state.get("primary_theme") and state.get("cast_strategy") and state.get("beat_plan_strategy"):
            return {
                "primary_theme": state["primary_theme"],
                "theme_modifiers": list(state.get("theme_modifiers") or []),
                "theme_router_reason": state.get("theme_router_reason") or "preview_locked_theme",
                "cast_strategy": state["cast_strategy"],
                "beat_plan_strategy": state["beat_plan_strategy"],
            }
        decision = plan_story_theme(
            state["focused_brief"],
            state["story_frame_draft"],
        )
        return {
            "primary_theme": decision.primary_theme,
            "theme_modifiers": list(decision.modifiers),
            "theme_router_reason": decision.router_reason,
            "cast_strategy": decision.cast_strategy,
            "beat_plan_strategy": decision.beat_plan_strategy,
        }

    def plan_brief_theme_node(state: AuthorState) -> dict[str, Any]:
        if state.get("story_frame_strategy") and state.get("cast_strategy") and state.get("brief_primary_theme"):
            return {
                "brief_primary_theme": state["brief_primary_theme"],
                "brief_theme_modifiers": list(state.get("brief_theme_modifiers") or []),
                "brief_theme_router_reason": state.get("brief_theme_router_reason") or "preview_locked_theme",
                "story_frame_strategy": state["story_frame_strategy"],
                "cast_strategy": state["cast_strategy"],
            }
        decision = plan_brief_theme(state["focused_brief"])
        return {
            "brief_primary_theme": decision.primary_theme,
            "brief_theme_modifiers": list(decision.modifiers),
            "brief_theme_router_reason": decision.router_reason,
            "story_frame_strategy": decision.story_frame_strategy,
            "cast_strategy": decision.cast_strategy,
        }

    def generate_cast_members_node(state: AuthorState) -> dict[str, Any]:
        prior_response_id = state.get("author_session_response_id")
        latest_response_id = prior_response_id
        existing_members = list(state.get("cast_member_drafts") or [])
        slots = list(state["cast_overview_draft"].cast_slots)
        trace = list(state.get("quality_trace") or [])
        for slot_index in range(len(existing_members), len(slots)):
            slot = slots[slot_index]
            existing_names = {member.name for member in existing_members}
            slot_payload = slot.model_dump(mode="json")
            existing_payload = [member.model_dump(mode="json") for member in existing_members]
            fallback_member = build_cast_member_from_slot(
                slot,
                state["focused_brief"],
                slot_index,
                set(existing_names),
            )
            member_source = "generated"
            member_outcome = "accepted"
            member_reasons: list[str] = []
            cast_strategy = state.get("cast_strategy") or "generic_civic_cast"
            if is_legitimacy_broker_slot(cast_strategy, slot):
                trace = append_quality_trace(
                    trace,
                    stage="cast_member",
                    source="default",
                    outcome="accepted",
                    reasons=["router_forced_deterministic_slot"],
                    slot_index=slot_index,
                    subject=slot.slot_label,
                )
                existing_members.append(fallback_member)
                continue
            try:
                generated = cast_generation.generate_story_cast_member(
                    resolved_gateway,
                    state["focused_brief"],
                    state["story_frame_draft"],
                    slot_payload,
                    existing_payload,
                    previous_response_id=latest_response_id,
                )
                latest_response_id = _resolved_session_response_id(latest_response_id, generated.response_id)
                member_seed = generated.value
                member_reasons = cast_member_quality_reasons(member_seed, existing_names, slot)
            except AuthorGatewayError as exc:
                if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                    raise
                member_seed = fallback_member
                member_source = "default"
                member_outcome = "fallback"
                member_reasons = [exc.code]

            finalized_member = finalize_cast_member_candidate(
                member_seed,
                state["focused_brief"],
                slot,
                existing_names,
            )
            if finalized_member is None and member_source != "default":
                try:
                    gleaned = cast_generation.glean_story_cast_member(
                        resolved_gateway,
                        state["focused_brief"],
                        state["story_frame_draft"],
                        slot_payload,
                        existing_payload,
                        member_seed.model_dump(mode="json"),
                        previous_response_id=latest_response_id,
                    )
                    latest_response_id = _resolved_session_response_id(latest_response_id, gleaned.response_id)
                    glean_reasons = cast_member_quality_reasons(gleaned.value, existing_names, slot)
                    finalized_member = finalize_cast_member_candidate(
                        gleaned.value,
                        state["focused_brief"],
                        slot,
                        existing_names,
                    )
                    if finalized_member is not None:
                        member_source = "gleaned"
                        member_outcome = "repaired"
                        member_reasons = member_reasons or glean_reasons
                    else:
                        member_reasons.extend(glean_reasons)
                except AuthorGatewayError as exc:
                    if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                        raise
                    member_reasons.append(exc.code)
            if finalized_member is None:
                finalized_member = fallback_member
                member_source = "default"
                member_outcome = "fallback"
                if not member_reasons:
                    member_reasons = cast_member_quality_reasons(member_seed, existing_names, slot)
            trace = append_quality_trace(
                trace,
                stage="cast_member",
                source=member_source,  # type: ignore[arg-type]
                outcome=member_outcome,  # type: ignore[arg-type]
                reasons=member_reasons if member_outcome != "accepted" else [],
                slot_index=slot_index,
                subject=slot.slot_label,
            )
            existing_members.append(finalized_member)
        return {
            "cast_member_drafts": existing_members,
            "author_session_response_id": latest_response_id,
            "quality_trace": trace,
        }

    def assemble_cast_node(state: AuthorState) -> dict[str, Any]:
        return {
            "cast_draft": CastDraft(cast=list(state.get("cast_member_drafts") or [])),
        }

    def generate_beat_plan_node(state: AuthorState) -> dict[str, Any]:
        prior_response_id = state.get("author_session_response_id")
        latest_response_id = prior_response_id
        trace = state.get("quality_trace")
        beat_strategy = state.get("beat_plan_strategy") or "conservative_direct_draft"
        if beat_strategy == "single_semantic_compile":
            beat_plan_generate = beat_generation.generate_beat_plan
        else:
            beat_plan_generate = beat_generation.generate_beat_plan_conservative
        try:
            generated = beat_plan_generate(
                resolved_gateway,
                state["focused_brief"],
                state["story_frame_draft"],
                state["cast_draft"],
                previous_response_id=prior_response_id,
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            return {
                "beat_plan_draft": build_default_beat_plan_draft(
                    state["focused_brief"],
                    story_frame=state["story_frame_draft"],
                    cast_draft=state["cast_draft"],
                ),
                "beat_plan_source": "default",
                "quality_trace": append_quality_trace(
                    trace,
                    stage="beat_plan",
                    source="default",
                    outcome="fallback",
                    reasons=[exc.code],
                ),
            }
        latest_response_id = _resolved_session_response_id(prior_response_id, generated.response_id)
        beat_plan_draft = generated.value
        beat_plan_source = "generated"
        beat_plan_outcome = "accepted"
        beat_plan_reasons = beat_plan_quality_reasons(
            beat_plan_draft,
            state["story_frame_draft"],
            state["cast_draft"],
        )
        if beat_plan_reasons:
            try:
                gleaned = beat_generation.glean_beat_plan(
                    resolved_gateway,
                    state["focused_brief"],
                    state["story_frame_draft"],
                    state["cast_draft"],
                    beat_plan_draft,
                    previous_response_id=latest_response_id,
                )
                latest_response_id = _resolved_session_response_id(latest_response_id, gleaned.response_id)
                glean_reasons = beat_plan_quality_reasons(
                    gleaned.value,
                    state["story_frame_draft"],
                    state["cast_draft"],
                )
                if not glean_reasons:
                    beat_plan_draft = gleaned.value
                    beat_plan_source = "gleaned"
                    beat_plan_outcome = "repaired"
                else:
                    beat_plan_draft = build_default_beat_plan_draft(
                        state["focused_brief"],
                        story_frame=state["story_frame_draft"],
                        cast_draft=state["cast_draft"],
                    )
                    beat_plan_source = "default"
                    beat_plan_outcome = "fallback"
                    beat_plan_reasons.extend(glean_reasons)
            except AuthorGatewayError as exc:
                if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                    raise
                beat_plan_draft = build_default_beat_plan_draft(
                    state["focused_brief"],
                    story_frame=state["story_frame_draft"],
                    cast_draft=state["cast_draft"],
                )
                beat_plan_source = "default"
                beat_plan_outcome = "fallback"
                beat_plan_reasons.append(exc.code)
        trace = append_quality_trace(
            trace,
            stage="beat_plan",
            source=beat_plan_source,  # type: ignore[arg-type]
            outcome=beat_plan_outcome,  # type: ignore[arg-type]
            reasons=beat_plan_reasons if beat_plan_outcome != "accepted" else [],
        )
        return {
            "beat_plan_draft": beat_plan_draft,
            "beat_plan_source": beat_plan_source,
            "author_session_response_id": latest_response_id,
            "quality_trace": trace,
        }

    def build_design_bundle_node(state: AuthorState) -> dict[str, Any]:
        bundle = build_design_bundle(
            state["story_frame_draft"],
            state["cast_draft"],
            state["beat_plan_draft"],
            state["focused_brief"],
        )
        return {
            "story_bible": bundle.story_bible,
            "state_schema": bundle.state_schema,
            "beat_spine": bundle.beat_spine,
            "design_bundle": bundle,
        }

    def generate_route_opportunity_plan_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        prior_response_id = state.get("author_session_response_id")
        try:
            generated = route_generation.generate_route_opportunity_plan_result(
                resolved_gateway,
                design_bundle,
                previous_response_id=prior_response_id,
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            return {
                "route_opportunity_plan_draft": build_default_route_opportunity_plan(design_bundle),
                "route_opportunity_plan_source": "default",
                "quality_trace": append_quality_trace(
                    state.get("quality_trace"),
                    stage="route_affordance",
                    source="default",
                    outcome="fallback",
                    reasons=[exc.code],
                ),
            }
        return {
            "route_opportunity_plan_draft": generated.value,
            "route_opportunity_plan_source": "generated",
            "author_session_response_id": _resolved_session_response_id(prior_response_id, generated.response_id),
        }

    def compile_route_affordance_pack_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        route_affordance_pack = compile_route_opportunity_plan(
            state["route_opportunity_plan_draft"],
            design_bundle,
        )
        route_affordance_source = "compiled" if state.get("route_opportunity_plan_source") == "generated" else "default"
        trace = state.get("quality_trace")
        route_quality_reasons = route_affordance_pack_quality_reasons(route_affordance_pack, design_bundle)
        if route_quality_reasons:
            route_affordance_pack = build_default_route_affordance_pack(design_bundle)
            route_affordance_source = "default"
            trace = append_quality_trace(
                trace,
                stage="route_affordance",
                source=route_affordance_source,
                outcome="fallback",
                reasons=route_quality_reasons,
            )
        elif state.get("route_opportunity_plan_source") == "generated":
            trace = append_quality_trace(
                trace,
                stage="route_affordance",
                source=route_affordance_source,
                outcome="accepted",
                reasons=[],
            )
        return {
            "route_affordance_pack_draft": route_affordance_pack,
            "route_affordance_source": route_affordance_source,
            "quality_trace": trace,
        }

    def generate_ending_rules_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        prior_response_id = state.get("author_session_response_id")
        latest_response_id = prior_response_id
        trace = state.get("quality_trace")
        skeleton = build_ending_skeleton(design_bundle)
        try:
            generated = ending_generation.generate_ending_anchor_suggestions(
                resolved_gateway,
                design_bundle,
                previous_response_id=prior_response_id,
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            ending_intent = normalize_ending_intent_draft(
                build_default_ending_intent(design_bundle),
                design_bundle,
            )
            normalized = build_default_ending_rules(design_bundle)
            trace = append_quality_trace(
                trace,
                stage="ending",
                source="default",
                outcome="fallback",
                reasons=[exc.code],
            )
            return {
                "ending_intent_draft": ending_intent,
                "ending_rules_draft": normalized,
                "ending_source": "default",
                "quality_trace": trace,
            }
        latest_response_id = _resolved_session_response_id(prior_response_id, generated.response_id)
        ending_intent = merge_ending_anchor_suggestions(
            skeleton,
            generated.value,
            design_bundle,
        )
        ending_source = "generated"
        ending_outcome = "accepted"
        ending_reasons = ending_intent_quality_reasons(ending_intent, design_bundle)
        if ending_reasons:
            try:
                gleaned = ending_generation.glean_ending_anchor_suggestions(
                    resolved_gateway,
                    design_bundle,
                    generated.value,
                    previous_response_id=latest_response_id,
                )
                latest_response_id = _resolved_session_response_id(latest_response_id, gleaned.response_id)
                ending_intent = merge_ending_anchor_suggestions(
                    skeleton,
                    gleaned.value,
                    design_bundle,
                )
                glean_reasons = ending_intent_quality_reasons(ending_intent, design_bundle)
                if not glean_reasons:
                    ending_source = "gleaned"
                    ending_outcome = "repaired"
                else:
                    ending_reasons.extend(glean_reasons)
            except AuthorGatewayError as exc:
                if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                    raise
                ending_reasons.append(exc.code)
            if ending_intent_quality_reasons(ending_intent, design_bundle):
                ending_intent = normalize_ending_intent_draft(
                    build_default_ending_intent(design_bundle),
                    design_bundle,
                )
                ending_source = "default"
                ending_outcome = "fallback"
        normalized = compile_ending_intent_draft(ending_intent, design_bundle)
        ending_rule_reasons = ending_rules_quality_reasons(normalized, design_bundle)
        if ending_rule_reasons:
            ending_intent = normalize_ending_intent_draft(
                build_default_ending_intent(design_bundle),
                design_bundle,
            )
            normalized = build_default_ending_rules(design_bundle)
            ending_source = "default"
            ending_outcome = "fallback"
            ending_reasons.extend(ending_rule_reasons)
        trace = append_quality_trace(
            trace,
            stage="ending",
            source=ending_source,  # type: ignore[arg-type]
            outcome=ending_outcome,  # type: ignore[arg-type]
            reasons=ending_reasons,
        )
        return {
            "ending_intent_draft": ending_intent,
            "ending_rules_draft": normalized,
            "ending_source": ending_source,
            "author_session_response_id": latest_response_id,
            "quality_trace": trace,
        }

    def merge_rule_pack_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        rule_pack = merge_rule_pack(
            state["route_affordance_pack_draft"],
            state["ending_rules_draft"],
        )
        return {
            "rule_pack": rule_pack,
            "design_bundle": design_bundle.model_copy(update={"rule_pack": rule_pack}),
        }

    graph = StateGraph(AuthorState)
    graph.add_node("focus_brief", focus_brief_node)
    graph.add_node("plan_brief_theme", plan_brief_theme_node)
    graph.add_node("generate_story_frame", generate_story_frame_node)
    graph.add_node("plan_story_theme", plan_story_theme_node)
    graph.add_node("derive_cast_overview", derive_cast_overview_node)
    graph.add_node("generate_cast_members", generate_cast_members_node)
    graph.add_node("assemble_cast", assemble_cast_node)
    graph.add_node("generate_beat_plan", generate_beat_plan_node)
    graph.add_node("build_design_bundle", build_design_bundle_node)
    graph.add_node("generate_route_opportunity_plan", generate_route_opportunity_plan_node)
    graph.add_node("compile_route_affordance_pack", compile_route_affordance_pack_node)
    graph.add_node("generate_ending_rules", generate_ending_rules_node)
    graph.add_node("merge_rule_pack", merge_rule_pack_node)
    graph.add_edge(START, "focus_brief")
    graph.add_edge("focus_brief", "plan_brief_theme")
    graph.add_edge("plan_brief_theme", "generate_story_frame")
    graph.add_edge("generate_story_frame", "plan_story_theme")
    graph.add_edge("plan_story_theme", "derive_cast_overview")
    graph.add_edge("derive_cast_overview", "generate_cast_members")
    graph.add_edge("generate_cast_members", "assemble_cast")
    graph.add_edge("assemble_cast", "generate_beat_plan")
    graph.add_edge("generate_beat_plan", "build_design_bundle")
    graph.add_edge("build_design_bundle", "generate_route_opportunity_plan")
    graph.add_edge("generate_route_opportunity_plan", "compile_route_affordance_pack")
    graph.add_edge("compile_route_affordance_pack", "generate_ending_rules")
    graph.add_edge("generate_ending_rules", "merge_rule_pack")
    graph.add_edge("merge_rule_pack", END)
    return graph.compile(checkpointer=checkpointer or get_author_checkpointer())


def run_author_bundle(request: AuthorBundleRequest, *, gateway: AuthorLLMGateway | None = None) -> "AuthorBundle":
    resolved_gateway = gateway or get_author_llm_gateway()
    if hasattr(resolved_gateway, "call_trace"):
        resolved_gateway.call_trace.clear()
    graph = build_author_graph(gateway=resolved_gateway)
    run_id = str(uuid4())
    state = graph.invoke(
        {
            "run_id": run_id,
            "raw_brief": request.raw_brief,
        },
        config=graph_config(run_id=run_id),
    )
    if hasattr(resolved_gateway, "call_trace"):
        state["llm_call_trace"] = list(resolved_gateway.call_trace)
    return AuthorBundle(
        run_id=run_id,
        bundle=state["design_bundle"],
        state=state,
    )

class AuthorBundle(BaseModel):
    run_id: str
    bundle: DesignBundle
    state: AuthorState
