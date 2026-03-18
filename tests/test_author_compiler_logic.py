from __future__ import annotations

import re
from pathlib import Path

from rpg_backend.author.compiler.router import plan_story_theme
from rpg_backend.author.workflow import build_design_bundle, build_default_ending_rules, focus_brief
from rpg_backend.author.contracts import StoryFrameDraft
from tests.author_fixtures import author_fixture_bundle


def test_focus_brief_extracts_kernel_and_conflict() -> None:
    focused = focus_brief(
        "A hopeful political fantasy about a mediator keeping a city together during a blackout and succession crisis."
    )

    assert "mediator" in focused.story_kernel.casefold()
    assert "city" in focused.setting_signal.casefold()
    assert "blackout" in focused.core_conflict.casefold() or "succession crisis" in focused.core_conflict.casefold()
    assert "hopeful political fantasy" in focused.tone_signal.casefold()
    assert focused.story_kernel != focused.setting_signal
    assert focused.story_kernel != focused.core_conflict


def test_focus_brief_splits_setting_and_conflict_from_single_sentence_prompt() -> None:
    focused = focus_brief(
        "A hopeful political fantasy about a young mediator keeping a flood-struck archive city together during a blackout election."
    )

    assert "young mediator" in focused.story_kernel.casefold()
    assert "archive city" in focused.setting_signal.casefold()
    assert "keep a flood-struck archive city together" in focused.core_conflict.casefold()
    assert "while a blackout election strains civic order" in focused.core_conflict.casefold()
    assert "hopeful political fantasy" in focused.tone_signal.casefold()


def test_build_design_bundle_creates_state_schema_and_beat_spine() -> None:
    fixture = author_fixture_bundle()
    bundle = build_design_bundle(
        fixture.story_frame,
        fixture.cast_draft,
        fixture.beat_plan,
        fixture.focused_brief,
    )

    assert bundle.story_bible.cast[0].npc_id
    assert bundle.state_schema.axes[0].axis_id == "external_pressure"
    assert bundle.beat_spine[0].beat_id == "b1"
    assert bundle.beat_spine[0].pressure_axis_id == "external_pressure"
    assert bundle.beat_spine[1].route_pivot_tag == "shift_public_narrative"
    assert bundle.beat_spine[1].required_events == ["b2.fracture"]


def test_theme_router_classifies_harbor_quarantine_into_logistics_strategy() -> None:
    decision = plan_story_theme(
        fixture := author_fixture_bundle().focused_brief.model_copy(
            update={
                "story_kernel": "A harbor inspector preventing collapse.",
                "setting_signal": "port city under quarantine and supply panic",
                "core_conflict": "keep the harbor operating while quarantine politics escalate",
                "tone_signal": "Tense civic fantasy",
            }
        ),
        StoryFrameDraft.model_validate(
            {
                "title": "The Harbor Compact",
                "premise": "In a harbor city under quarantine, an inspector must keep trade moving while panic spreads through the port.",
                "tone": "Tense civic fantasy",
                "stakes": "If inspection authority breaks, the city turns scarcity into factional seizure.",
                "style_guard": "Keep it civic and procedural.",
                "world_rules": ["Trade and legitimacy are linked.", "The main plot advances in fixed beats."],
                "truths": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.flags],
            }
        ),
    )

    assert fixture.story_kernel
    assert decision.primary_theme == "logistics_quarantine_crisis"
    assert decision.beat_plan_strategy == "single_semantic_compile"
    assert "harbor" in decision.modifiers


def test_theme_router_classifies_archive_record_into_single_semantic_strategy() -> None:
    decision = plan_story_theme(
        author_fixture_bundle().focused_brief.model_copy(
            update={
                "story_kernel": "An archivist preserving public trust.",
                "setting_signal": "archive hall during an emergency vote",
                "core_conflict": "verify altered civic records before the result hardens into public truth",
                "tone_signal": "Hopeful civic fantasy",
            }
        ),
        StoryFrameDraft.model_validate(
            {
                "title": "The Unbroken Ledger",
                "premise": "In a city archive under pressure, an archivist must restore altered records before rumor replaces the public record.",
                "tone": "Hopeful civic fantasy",
                "stakes": "If the archive fails, the vote loses legitimacy and the city fractures around competing truths.",
                "style_guard": "Keep it civic and procedural.",
                "world_rules": ["Records and legitimacy move together.", "The main plot advances in fixed beats."],
                "truths": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.flags],
            }
        ),
    )

    assert decision.primary_theme == "truth_record_crisis"
    assert decision.beat_plan_strategy == "single_semantic_compile"
    assert "archive" in decision.modifiers


def test_default_endings_include_story_specific_conditions() -> None:
    bundle = author_fixture_bundle().design_bundle
    ending_rules = build_default_ending_rules(bundle).ending_rules
    collapse = next(item for item in ending_rules if item.ending_id == "collapse")
    pyrrhic = next(item for item in ending_rules if item.ending_id == "pyrrhic")

    assert collapse.conditions.required_truths or collapse.conditions.required_events or collapse.conditions.required_flags
    assert pyrrhic.conditions.required_truths or pyrrhic.conditions.required_events or pyrrhic.conditions.required_flags
    axis_kind_by_id = {item.axis_id: item.kind for item in bundle.state_schema.axes}
    assert any(axis_kind_by_id.get(axis_id) != "pressure" for axis_id in pyrrhic.conditions.min_axes)


def test_only_author_fixtures_defines_fake_gateway_classes() -> None:
    tests_dir = Path(__file__).resolve().parent
    offenders: list[str] = []
    pattern = re.compile(r"^class .*Gateway\b", flags=re.MULTILINE)
    for path in tests_dir.glob("test_*.py"):
        if pattern.search(path.read_text()):
            offenders.append(path.name)
    assert offenders == []
