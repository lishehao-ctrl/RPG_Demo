from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from rpg_backend.author.checkpointer import graph_config
from rpg_backend.author.contracts import AuthorBundleRequest
from rpg_backend.author.workflow import build_author_graph, run_author_bundle
from tests.author_fixtures import (
    FakeGateway,
    RecoveringStoryFrameGateway,
    LowQualityStoryFrameGateway,
    fallback_beat_plan_gateway,
    fallback_ending_rules_gateway,
    fallback_overview_gateway,
    fallback_rulepack_gateway,
    generic_cast_gateway,
    narrow_route_diversity_gateway,
    noncanonical_ending_priority_gateway,
    low_quality_route_opportunities_gateway,
    placeholder_cast_gateway,
)


def test_author_graph_can_checkpoint_state_snapshot() -> None:
    graph = build_author_graph(gateway=FakeGateway(), checkpointer=InMemorySaver())
    config = graph_config(run_id="run-1")
    result = graph.invoke(
        {
            "run_id": "run-1",
            "raw_brief": "A hopeful political fantasy about keeping a city together during a crisis.",
        },
        config=config,
    )
    snapshot = graph.get_state(config)

    assert "design_bundle" in result
    assert snapshot.values["story_frame_draft"].title
    assert snapshot.values["cast_overview_draft"].cast_slots
    assert snapshot.values["cast_member_drafts"]
    assert snapshot.values["cast_draft"].cast
    assert snapshot.values["beat_plan_draft"].beats
    assert snapshot.values["primary_theme"]
    assert snapshot.values["beat_plan_strategy"]
    assert snapshot.values["story_frame_source"] == "generated"
    assert snapshot.values["beat_plan_source"] == "generated"
    assert snapshot.values["route_opportunity_plan_draft"].opportunities
    assert snapshot.values["route_opportunity_plan_source"] == "generated"
    assert snapshot.values["route_affordance_pack_draft"].affordance_effect_profiles
    assert snapshot.values["route_affordance_source"] == "compiled"
    assert snapshot.values["ending_intent_draft"].ending_intents
    assert snapshot.values["ending_rules_draft"].ending_rules
    assert snapshot.values["ending_source"] == "generated"
    assert snapshot.values["quality_trace"]
    assert {item["stage"] for item in snapshot.values["quality_trace"]} >= {"story_frame", "beat_plan", "route_affordance", "ending"}
    assert snapshot.values["design_bundle"].story_bible.title
    assert snapshot.values["rule_pack"].ending_rules
    assert snapshot.values["author_session_response_id"]


def test_author_graph_generates_dynamic_number_of_cast_members_from_cast_overview() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=FakeGateway(),
    )

    assert len(result.state["cast_overview_draft"].cast_slots) == 4
    assert len(result.state["cast_member_drafts"]) == 4
    assert len(result.bundle.story_bible.cast) == 4
    assert result.bundle.story_bible.cast[-1].name == "Lio Maren"


def test_author_bundle_falls_back_to_default_rulepack_when_rulepack_payload_is_malformed() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=fallback_rulepack_gateway(),
    )

    assert result.bundle.rule_pack.ending_rules
    assert result.bundle.rule_pack.affordance_effect_profiles
    assert result.state["route_affordance_source"] == "default"
    assert any(
        item["stage"] == "route_affordance"
        and item["source"] == "default"
        and item["outcome"] == "fallback"
        and "llm_invalid_json" in item["reasons"]
        for item in result.state["quality_trace"]
    )


def test_author_bundle_falls_back_to_default_endings_when_ending_payload_is_malformed() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=fallback_ending_rules_gateway(),
    )

    assert result.bundle.rule_pack.ending_rules
    assert {item.ending_id for item in result.bundle.rule_pack.ending_rules} == {"collapse", "pyrrhic", "mixed"}
    assert result.state["ending_source"] == "default"
    assert any(
        item["stage"] == "ending"
        and item["source"] == "default"
        and item["outcome"] == "fallback"
        and "llm_invalid_json" in item["reasons"]
        for item in result.state["quality_trace"]
    )


def test_author_bundle_canonicalizes_noncanonical_ending_priorities() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=noncanonical_ending_priority_gateway(),
    )

    assert [(item.ending_id, item.priority) for item in result.bundle.rule_pack.ending_rules] == [
        ("collapse", 1),
        ("pyrrhic", 2),
        ("mixed", 10),
    ]


def test_author_bundle_replaces_low_quality_route_opportunities_with_default_routes() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=low_quality_route_opportunities_gateway(),
    )

    assert len(result.bundle.rule_pack.route_unlock_rules) >= 2
    assert len({item.beat_id for item in result.bundle.rule_pack.route_unlock_rules}) >= 2


def test_author_bundle_supplements_narrow_route_diversity() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=narrow_route_diversity_gateway(),
    )

    assert len({item.beat_id for item in result.bundle.rule_pack.route_unlock_rules}) >= 2
    assert len({item.unlock_affordance_tag for item in result.bundle.rule_pack.route_unlock_rules}) >= 2


def test_author_bundle_replaces_low_quality_story_frame_with_default_story_frame() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=LowQualityStoryFrameGateway(),
    )

    assert result.bundle.story_bible.premise.startswith("In ")
    assert "player fails" not in result.bundle.story_bible.stakes.casefold()
    assert result.state["story_frame_source"] == "default"
    assert any(
        item["stage"] == "story_frame"
        and item["source"] == "default"
        and item["outcome"] == "fallback"
        and item["reasons"]
        for item in result.state["quality_trace"]
    )


def test_author_bundle_recovers_low_quality_story_frame_via_glean() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=RecoveringStoryFrameGateway(),
    )

    assert result.bundle.story_bible.title == "The Archive Blackout"
    assert result.state["story_frame_source"] == "gleaned"
    assert any(
        item["stage"] == "story_frame"
        and item["source"] == "gleaned"
        and item["outcome"] == "repaired"
        and item["reasons"]
        for item in result.state["quality_trace"]
    )


def test_author_bundle_falls_back_to_default_beats_when_payload_is_malformed() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=fallback_beat_plan_gateway(),
    )

    assert result.state["beat_plan_source"] == "default"
    assert len(result.bundle.beat_spine) >= 2
    assert any(
        item["stage"] == "beat_plan"
        and item["source"] == "default"
        and item["outcome"] == "fallback"
        and "llm_invalid_json" in item["reasons"]
        for item in result.state["quality_trace"]
    )


def test_author_bundle_repairs_generic_cast_fields_without_dropping_named_characters() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=generic_cast_gateway(),
    )

    cast = result.bundle.story_bible.cast
    assert [item.name for item in cast] == ["Mira Vale", "Curator Pell", "Broker Seln", "Lio Maren"]
    assert all("preserve their role in the crisis" not in item.agenda.casefold() for item in cast)
    assert all("pressure threatens public order" not in item.pressure_signature.casefold() for item in cast)


def test_author_bundle_replaces_placeholder_cast_with_default_cast() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=placeholder_cast_gateway(),
    )

    cast_names = [item.name for item in result.bundle.story_bible.cast]
    assert cast_names != ["Mediator Anchor", "Archive Guardian", "Coalition Rival"]
    assert all(not name.startswith("Civic Figure ") for name in cast_names)
    assert all(" " in name for name in cast_names)


def test_author_bundle_falls_back_to_default_overview_when_overview_payload_is_malformed() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=fallback_overview_gateway(),
    )

    assert result.bundle.story_bible.title
    assert result.bundle.beat_spine
