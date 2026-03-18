from __future__ import annotations

import json

from rpg_backend.author.contracts import FocusedBrief
from rpg_backend.author.gateway import AuthorGatewayError, AuthorLLMGateway
from rpg_backend.author.generation import beats as beat_generation
from rpg_backend.author.generation import cast as cast_generation
from rpg_backend.author.generation import endings as ending_generation
from rpg_backend.author.generation import routes as route_generation
from rpg_backend.author.generation import story_frame as story_generation
from tests.author_fixtures import (
    FakeClient,
    author_fixture_bundle,
    cast_draft,
    cast_overview_draft,
    ending_anchor_suggestion_payload,
    route_opportunity_plan_draft,
    story_frame_draft,
    story_frame_scaffold_draft,
    beat_plan_skeleton_draft,
)


def _gateway(client: FakeClient) -> AuthorLLMGateway:
    return AuthorLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        max_output_tokens_overview=700,
        max_output_tokens_beat_plan=900,
        max_output_tokens_rulepack=900,
        use_session_cache=True,
    )


def test_gateway_formats_requests_and_parses_models() -> None:
    client = FakeClient(
        [
            story_frame_scaffold_draft().model_dump(mode="json"),
            cast_overview_draft().model_dump(mode="json"),
            cast_draft().model_dump(mode="json"),
            beat_plan_skeleton_draft().model_dump(mode="json"),
        ]
    )
    gateway = _gateway(client)
    focused_brief = author_fixture_bundle().focused_brief

    story_frame = story_generation.generate_story_frame(gateway, focused_brief)
    cast_overview = cast_generation.generate_cast_overview(
        gateway,
        focused_brief,
        story_frame.value,
        previous_response_id=story_frame.response_id,
    )
    cast = cast_generation.generate_story_cast(
        gateway,
        focused_brief,
        story_frame.value,
        cast_overview.value,
        previous_response_id=cast_overview.response_id or story_frame.response_id,
    )
    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        focused_brief,
        story_frame.value,
        cast.value,
        previous_response_id=cast.response_id or story_frame.response_id,
    )

    assert story_frame.value.title == "Archive Blackout"
    assert cast.value.cast[0].name == "Envoy Iri"
    assert beat_plan.value.beats[0].title == "The First Nightfall"
    assert client.calls[0]["model"] == "demo-model"
    assert client.calls[0]["max_output_tokens"] == 800
    assert "Return one strict JSON object matching StoryFrameScaffoldDraft" in client.calls[0]["instructions"]
    assert "Return one strict JSON object matching CastOverviewDraft" in client.calls[1]["instructions"]
    assert "Return one strict JSON object matching CastDraft" in client.calls[2]["instructions"]
    assert "Return one strict JSON object matching BeatPlanSkeletonDraft" in client.calls[3]["instructions"]
    assert client.calls[1]["previous_response_id"] == "resp-1"
    assert client.calls[2]["previous_response_id"] == "resp-2"
    assert client.calls[3]["previous_response_id"] == "resp-3"
    beat_skeleton_payload = json.loads(client.calls[3]["input"])
    assert "author_context" in beat_skeleton_payload
    assert "story_frame" not in beat_skeleton_payload
    assert "cast" not in beat_skeleton_payload


def test_gateway_compiles_story_frame_from_semantics_without_second_llm_call() -> None:
    client = FakeClient([story_frame_scaffold_draft().model_dump(mode="json")])
    gateway = _gateway(client)

    story_frame = story_generation.generate_story_frame(
        gateway,
        author_fixture_bundle().focused_brief,
    )

    assert story_frame.value.title == "Archive Blackout"
    assert story_frame.response_id == "resp-1"
    assert story_frame.value.premise.startswith("In ")
    assert len(client.calls) == 1


def test_gateway_retries_story_frame_semantics_after_invalid_json() -> None:
    client = FakeClient(["not json at all", story_frame_scaffold_draft().model_dump(mode="json")])
    gateway = _gateway(client)

    story_frame = story_generation.generate_story_frame(
        gateway,
        FocusedBrief(
            story_kernel="A mediator keeping a city together",
            setting_signal="city during a blackout and succession crisis",
            core_conflict="keep a city together while a blackout and succession crisis strains civic order",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )

    assert len(client.calls) == 2
    assert story_frame.value.title == "Archive Blackout"


def test_gateway_stabilizes_generic_story_frame_scaffold_before_compile() -> None:
    fixture = author_fixture_bundle()
    client = FakeClient(
        [
            {
                "title_seed": "A Mediator Keeping A City Together",
                "setting_frame": "city during a blackout and succession crisis",
                "protagonist_mandate": "a mediator keeping a city together",
                "opposition_force": "keep a city together while a blackout and succession crisis strains civic order",
                "stakes_core": "Prevent coalition collapse.",
                "tone": "hopeful political fantasy",
                "world_rules": fixture.story_frame.world_rules,
                "truths": [item.model_dump(mode="json") for item in fixture.story_frame.truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in fixture.story_frame.state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in fixture.story_frame.flags],
            }
        ]
    )
    gateway = _gateway(client)

    story_frame = story_generation.generate_story_frame(
        gateway,
        FocusedBrief(
            story_kernel="A mediator keeping a city together",
            setting_signal="city during a blackout and succession crisis",
            core_conflict="keep a city together while a blackout and succession crisis strains civic order",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )

    assert story_frame.value.title == "The Dimmed Accord"
    assert "A Mediator Keeping A City Together" not in story_frame.value.premise


def test_gateway_compiles_beat_plan_from_single_semantics_call() -> None:
    client = FakeClient([beat_plan_skeleton_draft().model_dump(mode="json")])
    gateway = _gateway(client)
    fixture = author_fixture_bundle()

    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        fixture.cast_draft,
    )

    assert beat_plan.response_id == "resp-1"
    assert len(client.calls) == 1
    assert [beat.title for beat in beat_plan.value.beats] == [
        "The First Nightfall",
        "The Public Ledger",
        "The Dawn Bargain",
    ]
    assert [beat.milestone_kind for beat in beat_plan.value.beats] == [
        "reveal",
        "containment",
        "commitment",
    ]
    assert all(beat.return_hooks for beat in beat_plan.value.beats)


def test_gateway_retries_beat_plan_skeleton_after_invalid_json() -> None:
    client = FakeClient(["not json at all", beat_plan_skeleton_draft().model_dump(mode="json")])
    gateway = _gateway(client)
    fixture = author_fixture_bundle()

    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        fixture.cast_draft,
    )

    assert len(client.calls) == 2
    assert [beat.title for beat in beat_plan.value.beats] == [
        "The First Nightfall",
        "The Public Ledger",
        "The Dawn Bargain",
    ]


def test_gateway_compiles_cast_member_semantics_and_replaces_role_label_name() -> None:
    client = FakeClient(
        [
            {
                "name": "Leverage Broker",
                "agenda_detail": "Uses a private shipping ledger to squeeze concessions out of every public delay.",
                "red_line_detail": "Will burn the room down politically before accepting exclusion from the settlement.",
                "pressure_detail": "Starts framing every compromise as proof that the balance of power must change immediately.",
            }
        ]
    )
    gateway = _gateway(client)
    fixture = author_fixture_bundle()
    slot = fixture.cast_overview.cast_slots[2].model_dump(mode="json")

    member = cast_generation.generate_story_cast_member(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        slot,
        existing_cast=[
            fixture.cast_draft.cast[0].model_dump(mode="json"),
            fixture.cast_draft.cast[1].model_dump(mode="json"),
        ],
    )

    assert member.value.name != "Leverage Broker"
    assert member.value.role == "Coalition rival"
    assert "Exploit the blackout to reshape the balance of power." in member.value.agenda
    assert "Will not accept being shut out of the final order." in member.value.red_line
    assert "Frames every emergency as proof that someone else should lose authority." in member.value.pressure_signature


def test_gateway_retries_cast_member_semantics_after_invalid_json() -> None:
    client = FakeClient(
        [
            "not json at all",
            {
                "name": "Mara Kestrel",
                "agenda_detail": "Uses a private relief ledger to force concessions whenever the room stalls.",
                "red_line_detail": "Will take public blame over quiet exclusion from the settlement.",
                "pressure_detail": "Sharpens into open leverage the moment delay starts protecting someone else.",
            },
        ]
    )
    gateway = _gateway(client)
    fixture = author_fixture_bundle()
    slot = fixture.cast_overview.cast_slots[2].model_dump(mode="json")

    member = cast_generation.generate_story_cast_member(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        slot,
        existing_cast=[
            fixture.cast_draft.cast[0].model_dump(mode="json"),
            fixture.cast_draft.cast[1].model_dump(mode="json"),
        ],
    )

    assert len(client.calls) == 2
    assert member.value.name == "Mara Kestrel"
    assert "Exploit the blackout to reshape the balance of power." in member.value.agenda


def test_gateway_raises_stable_error_for_invalid_json() -> None:
    client = FakeClient(["not json at all", "not json at all", "not json at all"])
    gateway = _gateway(client)

    try:
        story_generation.generate_story_frame(
            gateway,
            author_fixture_bundle().focused_brief,
        )
    except AuthorGatewayError as exc:
        assert exc.code == "llm_invalid_json"
    else:  # pragma: no cover
        raise AssertionError("Expected AuthorGatewayError")


def test_rule_generation_uses_author_context_packets() -> None:
    client = FakeClient(
        [
            route_opportunity_plan_draft().model_dump(mode="json"),
            ending_anchor_suggestion_payload(),
        ]
    )
    gateway = _gateway(client)
    fixture = author_fixture_bundle()

    route_generation.generate_route_opportunity_plan_result(gateway, fixture.design_bundle, previous_response_id="resp-a")
    ending_generation.generate_ending_anchor_suggestions(gateway, fixture.design_bundle, previous_response_id="resp-b")

    route_payload = json.loads(client.calls[0]["input"])
    ending_payload = json.loads(client.calls[1]["input"])
    assert "author_context" in route_payload
    assert "story_bible" not in route_payload
    assert "state_schema" not in route_payload
    assert "beat_spine" not in route_payload
    assert "author_context" in ending_payload
    assert "story_bible" not in ending_payload
