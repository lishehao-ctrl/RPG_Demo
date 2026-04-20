from __future__ import annotations

import re
from pathlib import Path

from rpg_backend.author.compiler.cast import derive_cast_overview_draft
from rpg_backend.author.compiler.router import plan_story_theme
from rpg_backend.author.preview import build_author_preview_from_seed, build_author_story_summary
from rpg_backend.author.workflow import build_design_bundle, build_default_ending_rules, focus_brief
from rpg_backend.author.contracts import FocusedBrief, StoryFrameDraft
from rpg_backend.story_profiles import author_theme_from_bundle, play_closeout_profile_from_bundle
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
    assert decision.story_frame_strategy == "harbor_quarantine_story"
    assert decision.cast_strategy == "harbor_quarantine_cast"
    assert decision.beat_plan_strategy == "harbor_quarantine_compile"
    assert "harbor" in decision.modifiers
    harbor_bundle = author_fixture_bundle().design_bundle.model_copy(
        update={
            "focused_brief": fixture,
            "story_bible": author_fixture_bundle().design_bundle.story_bible.model_copy(
                update={
                    "title": "The Harbor Compact",
                    "premise": "In a harbor city under quarantine, an inspector must keep trade moving while panic spreads through the port.",
                    "stakes": "If inspection authority breaks, the city turns scarcity into factional seizure.",
                    "world_rules": ["Trade and legitimacy are linked.", "The main plot advances in fixed beats."],
                }
            ),
        }
    )
    play_decision = play_closeout_profile_from_bundle(
        harbor_bundle
    )
    assert play_decision.play_closeout_profile == "logistics_cost_closeout"


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
    assert decision.story_frame_strategy == "archive_vote_story"
    assert decision.cast_strategy == "archive_vote_cast"
    assert decision.beat_plan_strategy == "archive_vote_compile"
    assert "archive" in decision.modifiers
    play_decision = play_closeout_profile_from_bundle(
        author_fixture_bundle().design_bundle.model_copy(
            update={
                "focused_brief": author_fixture_bundle().focused_brief.model_copy(
                    update={
                        "story_kernel": "An archivist preserving public trust.",
                        "setting_signal": "archive hall during an emergency vote",
                        "core_conflict": "verify altered civic records before the result hardens into public truth",
                        "tone_signal": "Hopeful civic fantasy",
                    }
                ),
            }
        )
    )
    assert play_decision.play_closeout_profile == "record_exposure_closeout"


def test_author_theme_from_bundle_returns_author_only_decision() -> None:
    decision = author_theme_from_bundle(author_fixture_bundle().design_bundle)

    assert decision.primary_theme in {
        "legitimacy_crisis",
        "truth_record_crisis",
        "logistics_quarantine_crisis",
        "public_order_crisis",
        "generic_civic_crisis",
    }
    assert not hasattr(decision, "play_closeout_profile")


def test_preview_uses_brief_theme_when_default_story_frame_would_drift() -> None:
    preview = build_author_preview_from_seed(
        "During a blackout referendum, a city ombudsman must keep neighborhood councils from breaking apart after forged supply reports trigger panic."
    )

    assert preview.theme.primary_theme == "logistics_quarantine_crisis"
    assert preview.strategies.story_frame_strategy == "blackout_referendum_story"
    assert preview.strategies.cast_strategy == "blackout_referendum_cast"
    assert preview.strategies.beat_plan_strategy == "blackout_referendum_compile"


def test_preview_rewrites_seed_echo_into_authored_summary() -> None:
    seed = "A bridge superintendent discovers the ration convoy diversions were staged to justify emergency command powers."

    preview = build_author_preview_from_seed(seed)

    assert preview.story.premise != seed
    assert seed.casefold() not in preview.story.premise.casefold()
    assert preview.story.premise.casefold().startswith("in ")
    assert "must" in preview.story.premise.casefold()
    assert preview.story.tone.casefold() != seed.casefold()
    assert len(preview.story.tone.split()) <= 6


def test_theme_router_classifies_bridge_ration_into_bridge_specific_strategy() -> None:
    decision = plan_story_theme(
        author_fixture_bundle().focused_brief.model_copy(
            update={
                "story_kernel": "A bridge engineer must keep the wards connected.",
                "setting_signal": "A flood bridge ration crisis splits the river wards.",
                "core_conflict": "Keep the bridge coalition intact while forged ledgers drive the docks against the upper wards.",
                "tone_signal": "Tense civic fantasy",
            }
        ),
        StoryFrameDraft.model_validate(
            {
                "title": "Ration Bridge",
                "premise": "A bridge engineer must keep the flood coalition together after forged ration ledgers pit the docks against the upper wards.",
                "tone": "Tense civic fantasy",
                "stakes": "If the bridge compact fails, scarcity turns the crossing into a political chokepoint.",
                "style_guard": "Keep it civic and procedural.",
                "world_rules": ["Crossings determine legitimacy.", "The main plot advances in fixed beats."],
                "truths": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.flags],
            }
        ),
    )

    assert decision.primary_theme == "logistics_quarantine_crisis"
    assert decision.story_frame_strategy == "bridge_ration_story"
    assert decision.cast_strategy == "bridge_ration_cast"
    assert decision.beat_plan_strategy == "bridge_ration_compile"


def test_theme_router_classifies_warning_record_into_warning_specific_strategy() -> None:
    decision = plan_story_theme(
        author_fixture_bundle().focused_brief.model_copy(
            update={
                "story_kernel": "A royal archivist proving the warning is real.",
                "setting_signal": "capital observatory record office under storm threat",
                "core_conflict": "prove the storm bulletin is real before courtiers bury it",
                "tone_signal": "Procedural suspense",
            }
        ),
        StoryFrameDraft.model_validate(
            {
                "title": "The Blind Record",
                "premise": "A royal archivist must verify the observatory warning before courtiers suppress it.",
                "tone": "Procedural suspense",
                "stakes": "If the warning is buried, the capital will face the storm unprepared.",
                "style_guard": "Keep it civic and procedural.",
                "world_rules": ["Warnings only matter when entered into the official record.", "The main plot advances in fixed beats."],
                "truths": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.flags],
            }
        ),
    )

    assert decision.primary_theme == "truth_record_crisis"
    assert decision.story_frame_strategy == "warning_record_story"
    assert decision.cast_strategy == "warning_record_cast"
    assert decision.beat_plan_strategy == "warning_record_compile"


def test_author_theme_and_play_closeout_profile_can_diverge_for_logistics_record_bundle() -> None:
    fixture = author_fixture_bundle()
    bundle = fixture.design_bundle.model_copy(
        update={
            "focused_brief": fixture.focused_brief.model_copy(
                update={
                    "story_kernel": "A bridge engineer must keep the wards connected.",
                    "setting_signal": "A flood bridge ration crisis splits the river wards.",
                    "core_conflict": "Keep the bridge coalition intact while forged ledgers drive the docks against the upper wards.",
                }
            ),
            "story_bible": fixture.design_bundle.story_bible.model_copy(
                update={
                    "title": "Ration Bridge",
                    "premise": "A bridge engineer must keep the flood coalition together after forged ration ledgers pit the docks against the upper wards.",
                    "stakes": "If the bridge compact fails, scarcity turns the crossing into a political chokepoint.",
                }
            ),
        }
    )

    author_decision = author_theme_from_bundle(bundle)
    play_decision = play_closeout_profile_from_bundle(bundle)

    assert author_decision.primary_theme == "logistics_quarantine_crisis"
    assert play_decision.play_closeout_profile == "record_exposure_closeout"


def test_default_endings_include_story_specific_conditions() -> None:
    bundle = author_fixture_bundle().design_bundle
    ending_rules = build_default_ending_rules(bundle).ending_rules
    collapse = next(item for item in ending_rules if item.ending_id == "collapse")
    pyrrhic = next(item for item in ending_rules if item.ending_id == "pyrrhic")

    assert collapse.conditions.required_truths or collapse.conditions.required_events or collapse.conditions.required_flags
    assert pyrrhic.conditions.required_truths or pyrrhic.conditions.required_events or pyrrhic.conditions.required_flags
    axis_kind_by_id = {item.axis_id: item.kind for item in bundle.state_schema.axes}
    assert any(axis_kind_by_id.get(axis_id) != "pressure" for axis_id in pyrrhic.conditions.min_axes)

def test_author_story_summary_sanitizes_malformed_premise() -> None:
    bundle = author_fixture_bundle().design_bundle.model_copy(deep=True)
    malformed = (
        "In a city of archives under blackout., As the youngest envoy you must restore the record to. "
        "while rival ministries and."
    )
    bundle.story_bible = bundle.story_bible.model_copy(update={"premise": malformed})

    summary = build_author_story_summary(bundle, primary_theme="truth_record_crisis")

    assert summary.premise != malformed
    assert ".," not in summary.premise
    assert ". while" not in summary.premise.casefold()
    assert summary.one_liner


def test_author_story_summary_clamps_one_liner_length() -> None:
    bundle = author_fixture_bundle().design_bundle.model_copy(deep=True)
    bundle.story_bible = bundle.story_bible.model_copy(
        update={
            "premise": (
                "In a flood-swollen river city, a relief commissioner must hold the bridges, the ration depots, "
                "the district captains, and the terrified neighborhoods together before missing ledgers turn emergency logistics "
                "into a public collapse with no trusted path back to order"
            )
        }
    )

    summary = build_author_story_summary(bundle, primary_theme="public_order_crisis")

    assert len(summary.one_liner) <= 220


def test_author_story_summary_falls_back_from_repeated_clause_premise() -> None:
    bundle = author_fixture_bundle().design_bundle.model_copy(deep=True)
    noisy_premise = (
        "In city during a succession settlement, When sealed chain-of-custody records are altered "
        "while When sealed chain-of-custody records are altered while a succession settlement strains civic order."
    )
    bundle.story_bible = bundle.story_bible.model_copy(update={"premise": noisy_premise})
    bundle.focused_brief = bundle.focused_brief.model_copy(
        update={
            "story_kernel": "When sealed chain-of-custody records are altered",
            "setting_signal": "city during a succession settlement",
            "core_conflict": "When sealed chain-of-custody records are altered while a succession settlement strains civic order",
        }
    )

    summary = build_author_story_summary(bundle, primary_theme="truth_record_crisis")

    assert summary.premise != noisy_premise
    assert summary.premise.casefold().count("when sealed chain-of-custody records are altered") <= 1
    assert "a city of archives" in summary.premise.casefold()


def test_cast_overview_handles_forced_four_slot_when_recomputed_plan_is_three_slot() -> None:
    focused_brief = FocusedBrief(
        story_kernel="A civic engineer must keep district councils talking.",
        setting_signal="A river city under flood stress.",
        core_conflict="Keep the council process legitimate before shortages split the wards.",
        tone_signal="Tense civic drama.",
        hard_constraints=[],
        forbidden_tones=[],
    )
    story_frame = StoryFrameDraft.model_validate(
        {
            "title": "The Rationed Arch",
            "premise": "In a river city under flood stress, an engineer must hold the councils together while forged ledgers drive the wards apart.",
            "tone": "Tense civic drama",
            "stakes": "If the coalition breaks, the bridges become private choke points and the city loses any common emergency process.",
            "style_guard": "Keep it grounded in civic pressure.",
            "world_rules": ["Emergency legitimacy depends on visible fairness.", "The main plot advances in fixed beats."],
            "truths": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.truths],
            "state_axis_choices": [item.model_dump(mode="json") for item in author_fixture_bundle().story_frame.state_axis_choices],
            "flags": [],
        }
    )

    overview = derive_cast_overview_draft(
        focused_brief,
        story_frame,
        topology_override="four_slot",
    )

    assert len(overview.cast_slots) == 4
    assert overview.cast_slots[-1].archetype_id in {"public_witness", "dock_delegate"}


def test_only_author_fixtures_defines_fake_gateway_classes() -> None:
    tests_dir = Path(__file__).resolve().parent
    offenders: list[str] = []
    allowed = {"test_author_v2_pipeline.py"}
    pattern = re.compile(r"^class .*Gateway\b", flags=re.MULTILINE)
    for path in tests_dir.glob("test_*.py"):
        if path.name in allowed:
            continue
        if pattern.search(path.read_text()):
            offenders.append(path.name)
    assert offenders == []
