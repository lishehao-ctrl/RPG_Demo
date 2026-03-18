from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from rpg_backend.author.contracts import (
    BeatDraftSpec,
    BeatPlanDraft,
    BeatPlanSkeletonDraft,
    BeatSkeletonSpec,
    CastDraft,
    CastOverviewDraft,
    CastOverviewSlotDraft,
    DesignBundle,
    FocusedBrief,
    OverviewAxisDraft,
    OverviewCastDraft,
    OverviewFlagDraft,
    OverviewTruthDraft,
    RouteOpportunityPlanDraft,
    StoryFrameDraft,
    StoryFrameScaffoldDraft,
)
from rpg_backend.author.gateway import AuthorGatewayError
from rpg_backend.author.workflow import (
    build_default_route_opportunity_plan,
    build_design_bundle,
)


@dataclass(frozen=True)
class AuthorFixtureBundle:
    focused_brief: FocusedBrief
    story_frame: StoryFrameDraft
    story_frame_scaffold: StoryFrameScaffoldDraft
    cast_overview: CastOverviewDraft
    cast_draft: CastDraft
    beat_plan: BeatPlanDraft
    beat_plan_skeleton: BeatPlanSkeletonDraft
    design_bundle: DesignBundle
    route_opportunity_plan: RouteOpportunityPlanDraft


def focused_brief_fixture() -> FocusedBrief:
    return FocusedBrief(
        story_kernel="Hold the city together.",
        setting_signal="Archive city blackout.",
        core_conflict="Prevent coalition collapse.",
        tone_signal="Hopeful civic fantasy.",
        hard_constraints=[],
        forbidden_tones=[],
    )


def _overview_fixture() -> SimpleNamespace:
    return SimpleNamespace(
        title="The Archive Blackout",
        premise="A young envoy must hold together a city of archives through a blackout and a succession crisis.",
        tone="Hopeful civic fantasy under pressure",
        stakes="If the coalition fractures, the city loses both legitimacy and the systems keeping it alive.",
        style_guard="Keep the story tense, civic, and grounded in public consequence.",
        cast=[
            OverviewCastDraft(
                name="Envoy Iri",
                role="Mediator",
                agenda="Hold the coalition together long enough to expose the real sabotage.",
                red_line="Will not sacrifice civilians to preserve elite legitimacy.",
                pressure_signature="Treats every compromise as something the public will have to live with later.",
            ),
            OverviewCastDraft(
                name="Archivist Sen",
                role="Institutional guardian",
                agenda="Preserve continuity and keep the archive systems stable.",
                red_line="Will not allow the archive vaults to be purged for convenience.",
                pressure_signature="Looks for systemic consequences before approving any drastic move.",
            ),
            OverviewCastDraft(
                name="Broker Tal",
                role="Coalition rival",
                agenda="Exploit the blackout to reshape the balance of power.",
                red_line="Will not accept being shut out of the final order.",
                pressure_signature="Frames every emergency as proof that someone else should lose authority.",
            ),
        ],
        world_rules=[
            "Power restoration and public legitimacy are linked.",
            "The main plot advances through fixed beats even if local tactics vary.",
        ],
        truths=[
            OverviewTruthDraft(text="The blackout was engineered rather than accidental.", importance="core"),
            OverviewTruthDraft(text="The succession vote can still hold if public trust does not collapse.", importance="core"),
        ],
        state_axis_choices=[
            OverviewAxisDraft(template_id="external_pressure", story_label="Civic Pressure", starting_value=1),
            OverviewAxisDraft(template_id="public_panic", story_label="Public Panic", starting_value=0),
            OverviewAxisDraft(template_id="political_leverage", story_label="Political Leverage", starting_value=2),
        ],
        flags=[
            OverviewFlagDraft(label="Public Cover", starting_value=False),
        ],
        beats=[
            BeatDraftSpec(
                title="Opening Pressure",
                goal="Figure out what is breaking and who is pushing the city toward fracture.",
                focus_names=["Envoy Iri", "Archivist Sen"],
                conflict_pair=["Envoy Iri", "Archivist Sen"],
                pressure_axis_id="external_pressure",
                milestone_kind="reveal",
                route_pivot_tag="reveal_truth",
                required_truth_texts=["The blackout was engineered rather than accidental."],
                detour_budget=1,
                progress_required=2,
                return_hooks=["A visible civic failure forces the envoy to act."],
                affordance_tags=["reveal_truth", "contain_chaos", "build_trust"],
                blocked_affordances=[],
            ),
            BeatDraftSpec(
                title="Alliance Stress",
                goal="Keep the coalition intact long enough to expose the real conspiracy.",
                focus_names=["Archivist Sen", "Broker Tal"],
                conflict_pair=["Archivist Sen", "Broker Tal"],
                pressure_axis_id="political_leverage",
                milestone_kind="fracture",
                route_pivot_tag="shift_public_narrative",
                required_truth_texts=["The succession vote can still hold if public trust does not collapse."],
                detour_budget=1,
                progress_required=2,
                return_hooks=["A coalition fracture makes delay impossible."],
                affordance_tags=["build_trust", "shift_public_narrative", "pay_cost"],
                blocked_affordances=[],
            ),
        ],
    )


def story_frame_draft() -> StoryFrameDraft:
    overview = _overview_fixture()
    return StoryFrameDraft(
        title=overview.title,
        premise=overview.premise,
        tone=overview.tone,
        stakes=overview.stakes,
        style_guard=overview.style_guard,
        world_rules=overview.world_rules,
        truths=overview.truths,
        state_axis_choices=overview.state_axis_choices,
        flags=overview.flags,
    )


def story_frame_scaffold_draft() -> StoryFrameScaffoldDraft:
    story_frame = story_frame_draft()
    return StoryFrameScaffoldDraft(
        title_seed="Archive Blackout",
        setting_frame="a city of archives trapped in blackout and succession crisis",
        protagonist_mandate="a young envoy must hold the coalition together long enough to expose the sabotage",
        opposition_force="institutional panic and opportunistic rivals keep turning delay into leverage",
        stakes_core="the city loses both legitimacy and the systems keeping it alive",
        tone=story_frame.tone,
        world_rules=story_frame.world_rules,
        truths=story_frame.truths,
        state_axis_choices=story_frame.state_axis_choices,
        flags=story_frame.flags,
    )


def cast_draft() -> CastDraft:
    return CastDraft(cast=_overview_fixture().cast)


def cast_overview_draft() -> CastOverviewDraft:
    return CastOverviewDraft(
        cast_slots=[
            CastOverviewSlotDraft(
                slot_label="Mediator Anchor",
                public_role="Mediator",
                relationship_to_protagonist="This slot is the protagonist and carries public responsibility directly.",
                agenda_anchor="Hold the coalition together long enough to expose the real sabotage.",
                red_line_anchor="Will not sacrifice civilians to preserve elite legitimacy.",
                pressure_vector="Treats every compromise as something the public will have to live with later.",
            ),
            CastOverviewSlotDraft(
                slot_label="Archive Guardian",
                public_role="Institutional guardian",
                relationship_to_protagonist="Needs the protagonist's flexibility but distrusts improvisation under pressure.",
                agenda_anchor="Preserve continuity and keep the archive systems stable.",
                red_line_anchor="Will not allow the archive vaults to be purged for convenience.",
                pressure_vector="Looks for systemic consequences before approving any drastic move.",
            ),
            CastOverviewSlotDraft(
                slot_label="Coalition Rival",
                public_role="Coalition rival",
                relationship_to_protagonist="Tests whether the protagonist can stabilize the crisis without yielding leverage.",
                agenda_anchor="Exploit the blackout to reshape the balance of power.",
                red_line_anchor="Will not accept being shut out of the final order.",
                pressure_vector="Frames every emergency as proof that someone else should lose authority.",
            ),
            CastOverviewSlotDraft(
                slot_label="Civic Witness",
                public_role="Public advocate",
                relationship_to_protagonist="Presses the protagonist to make emergency decisions legible to the public.",
                agenda_anchor="Force the crisis response to remain publicly accountable while pressure keeps rising.",
                red_line_anchor="Will not let elite procedure erase the public record of what happened.",
                pressure_vector="Turns ambiguity, secrecy, or procedural drift into public scrutiny.",
            ),
        ],
        relationship_summary=[
            "The archive guardian and the protagonist need each other but clash over how much improvisation the crisis can tolerate.",
            "The coalition rival gains leverage whenever pressure rises faster than procedure can stabilize it.",
            "The civic witness amplifies any gap between elite coordination and public legitimacy.",
        ],
    )


def beat_plan_draft() -> BeatPlanDraft:
    return BeatPlanDraft(beats=_overview_fixture().beats)


def beat_plan_skeleton_draft() -> BeatPlanSkeletonDraft:
    overview = _overview_fixture()
    return BeatPlanSkeletonDraft(
        beats=[
            BeatSkeletonSpec(
                title_seed="Opening Pressure",
                goal_seed="Figure out what is breaking and who is pushing the city toward fracture.",
                focus_names=beat.focus_names,
                conflict_pair=beat.conflict_pair,
                pressure_axis_id=beat.pressure_axis_id,
                milestone_kind=beat.milestone_kind,
                route_pivot_tag=beat.route_pivot_tag,
                required_truth_texts=beat.required_truth_texts,
                detour_budget=beat.detour_budget,
                progress_required=beat.progress_required,
                affordance_tags=beat.affordance_tags,
                blocked_affordances=beat.blocked_affordances,
            )
            if index == 0
            else BeatSkeletonSpec(
                title_seed="Alliance Stress",
                goal_seed="Keep the coalition intact long enough to expose the real conspiracy.",
                focus_names=beat.focus_names,
                conflict_pair=beat.conflict_pair,
                pressure_axis_id=beat.pressure_axis_id,
                milestone_kind=beat.milestone_kind,
                route_pivot_tag=beat.route_pivot_tag,
                required_truth_texts=beat.required_truth_texts,
                detour_budget=beat.detour_budget,
                progress_required=beat.progress_required,
                affordance_tags=beat.affordance_tags,
                blocked_affordances=beat.blocked_affordances,
            )
            for index, beat in enumerate(overview.beats)
        ]
    )


def author_fixture_bundle() -> AuthorFixtureBundle:
    focused_brief = focused_brief_fixture()
    story_frame = story_frame_draft()
    cast_overview = cast_overview_draft()
    cast = cast_draft()
    beat_plan = beat_plan_draft()
    design_bundle = build_design_bundle(
        story_frame,
        cast,
        beat_plan,
        focused_brief,
    )
    return AuthorFixtureBundle(
        focused_brief=focused_brief,
        story_frame=story_frame,
        story_frame_scaffold=story_frame_scaffold_draft(),
        cast_overview=cast_overview,
        cast_draft=cast,
        beat_plan=beat_plan,
        beat_plan_skeleton=beat_plan_skeleton_draft(),
        design_bundle=design_bundle,
        route_opportunity_plan=build_default_route_opportunity_plan(design_bundle),
    )


def route_opportunity_plan_draft() -> RouteOpportunityPlanDraft:
    return author_fixture_bundle().route_opportunity_plan


class FakeClient:
    def __init__(self, payloads: list[dict[str, object] | str]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

        class _Responses:
            def __init__(self, outer: FakeClient) -> None:
                self.outer = outer

            def create(self, **kwargs):  # noqa: ANN003
                self.outer.calls.append(kwargs)
                payload = self.outer.payloads.pop(0)
                if isinstance(payload, str):
                    content = payload
                else:
                    import json

                    content = json.dumps(payload, ensure_ascii=False)
                return SimpleNamespace(output_text=content, id=f"resp-{len(self.outer.calls)}")

        self.responses = _Responses(self)


def cast_member_semantics_payloads() -> list[dict[str, str]]:
    return [
        {
            "name": "Envoy Iri",
            "agenda_detail": "Keeps rival institutions bargaining long enough to expose the sabotage.",
            "red_line_detail": "Will not trade civilian safety for elite stability.",
            "pressure_detail": "Treats every compromise as a public obligation that will outlive the emergency.",
        },
        {
            "name": "Archivist Sen",
            "agenda_detail": "Preserves continuity and keeps the archive systems stable under strain.",
            "red_line_detail": "Will not let the archive vaults be sacrificed for convenience.",
            "pressure_detail": "Pushes everyone to think in system consequences before dramatic gestures.",
        },
        {
            "name": "Broker Tal",
            "agenda_detail": "Uses the blackout to reshape who gets to define the final settlement.",
            "red_line_detail": "Will not accept being excluded from the new order.",
            "pressure_detail": "Frames every delay as proof that authority must change hands.",
        },
        {
            "name": "Lio Maren",
            "agenda_detail": "Forces the crisis response to stay publicly legible while pressure keeps rising.",
            "red_line_detail": "Will not let procedure erase the public record of what happened.",
            "pressure_detail": "Turns secrecy and ambiguity into immediate public scrutiny.",
        },
    ]


def ending_anchor_suggestion_payload() -> dict[str, object]:
    return {
        "ending_anchor_suggestions": [
            {
                "ending_id": "collapse",
                "axis_ids": ["external_pressure"],
                "required_truth_ids": ["truth_1"],
            },
            {
                "ending_id": "pyrrhic",
                "axis_ids": ["political_leverage", "public_panic"],
                "required_event_ids": ["b2.fracture"],
            },
        ]
    }


def default_transport_responses() -> dict[str, list[dict[str, object] | Exception]]:
    fixture_bundle = author_fixture_bundle()
    return {
        "story_frame_semantics": [
            fixture_bundle.story_frame_scaffold.model_dump(mode="json"),
        ],
        "cast_member_semantics": list(cast_member_semantics_payloads()),
        "beat_plan_generate": [
            fixture_bundle.beat_plan_skeleton.model_dump(mode="json"),
        ],
        "route_opportunity_generate": [
            fixture_bundle.route_opportunity_plan.model_dump(mode="json"),
        ],
        "ending_anchor_generate": [
            ending_anchor_suggestion_payload(),
        ],
    }


def low_quality_story_frame_scaffold() -> dict[str, object]:
    fixture_bundle = author_fixture_bundle()
    return {
        "title_seed": "Untitled Crisis",
        "setting_frame": fixture_bundle.focused_brief.setting_signal,
        "protagonist_mandate": "Hold the city together",
        "opposition_force": fixture_bundle.focused_brief.core_conflict,
        "stakes_core": fixture_bundle.focused_brief.core_conflict,
        "tone": fixture_bundle.focused_brief.tone_signal,
        "world_rules": [
            fixture_bundle.focused_brief.setting_signal,
            "The main plot advances in fixed beats even when local tactics vary.",
        ],
        "truths": [
            {"text": fixture_bundle.focused_brief.core_conflict, "importance": "core"},
            {"text": fixture_bundle.focused_brief.setting_signal, "importance": "core"},
        ],
        "state_axis_choices": [item.model_dump(mode="json") for item in fixture_bundle.story_frame.state_axis_choices],
        "flags": [item.model_dump(mode="json") for item in fixture_bundle.story_frame.flags],
    }


class FakeGateway:
    def __init__(self, responses_by_operation: dict[str, list[dict[str, object] | Exception]] | None = None) -> None:
        self.responses_by_operation = responses_by_operation or default_transport_responses()
        self.max_output_tokens_overview = 700
        self.max_output_tokens_beat_plan = 900
        self.max_output_tokens_rulepack = 900
        self.use_session_cache = False
        self.call_trace: list[dict[str, object]] = []
        self._response_index = 0

    def _invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, object],
        max_output_tokens: int | None,
        previous_response_id: str | None = None,
        operation_name: str | None = None,
    ):
        del system_prompt
        operation = operation_name or "unknown"
        queue = self.responses_by_operation.get(operation)
        if not queue:
            raise AssertionError(f"Unexpected operation: {operation}")
        next_item = queue.pop(0)
        self._response_index += 1
        response_id = f"{operation}-{self._response_index}"
        self.call_trace.append(
            {
                "operation": operation,
                "response_id": response_id,
                "used_previous_response_id": bool(previous_response_id),
                "session_cache_enabled": False,
                "max_output_tokens": max_output_tokens,
                "input_characters": len(str(user_payload)),
                "usage": {},
            }
        )
        if isinstance(next_item, Exception):
            raise next_item
        return SimpleNamespace(
            payload=next_item,
            response_id=response_id,
            usage={},
            input_characters=len(str(user_payload)),
        )


def repeated_gateway_error(code: str, *, count: int = 3) -> list[AuthorGatewayError]:
    return [
        AuthorGatewayError(code=code, message="provider returned empty content", status_code=502)
        for _ in range(count)
    ]


def gateway_with_overrides(**overrides: list[dict[str, object] | Exception]) -> FakeGateway:
    responses = default_transport_responses()
    responses.update(overrides)
    return FakeGateway(responses)


def fallback_rulepack_gateway() -> FakeGateway:
    return gateway_with_overrides(route_opportunity_generate=repeated_gateway_error("llm_invalid_json"))


def fallback_ending_rules_gateway() -> FakeGateway:
    return gateway_with_overrides(ending_anchor_generate=repeated_gateway_error("llm_invalid_json"))


def noncanonical_ending_priority_gateway() -> FakeGateway:
    return gateway_with_overrides(
        ending_anchor_generate=[
            {
                "ending_anchor_suggestions": [
                    {
                        "ending_id": "pyrrhic",
                        "axis_ids": ["political_leverage", "public_panic"],
                        "required_event_ids": ["b2.fracture"],
                    },
                    {
                        "ending_id": "collapse",
                        "axis_ids": ["external_pressure"],
                        "required_truth_ids": ["truth_1"],
                    },
                ]
            }
        ]
    )


def fallback_beat_plan_gateway() -> FakeGateway:
    return gateway_with_overrides(beat_plan_generate=repeated_gateway_error("llm_invalid_json"))


def low_quality_route_opportunities_gateway() -> FakeGateway:
    return gateway_with_overrides(
        route_opportunity_generate=[
            {
                "opportunities": [
                    {
                        "beat_id": "b1",
                        "unlock_route_id": "b1_single_route",
                        "unlock_affordance_tag": "reveal_truth",
                        "triggers": [{"kind": "truth", "target_id": "truth_1"}],
                    }
                ]
            }
        ]
    )


def narrow_route_diversity_gateway() -> FakeGateway:
    return gateway_with_overrides(
        route_opportunity_generate=[
            {
                "opportunities": [
                    {
                        "beat_id": "b1",
                        "unlock_route_id": "b1_build_trust_route",
                        "unlock_affordance_tag": "build_trust",
                        "triggers": [{"kind": "truth", "target_id": "truth_1"}],
                    },
                    {
                        "beat_id": "b2",
                        "unlock_route_id": "b2_build_trust_route",
                        "unlock_affordance_tag": "build_trust",
                        "triggers": [{"kind": "event", "target_id": "b1.reveal"}],
                    },
                ]
            }
        ]
    )


class LowQualityStoryFrameGateway(FakeGateway):
    def __init__(self) -> None:
        responses = default_transport_responses()
        responses["story_frame_glean"] = [
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502)
        ]
        super().__init__(responses)

    def _invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, object],
        max_output_tokens: int | None,
        previous_response_id: str | None = None,
        operation_name: str | None = None,
    ):
        if operation_name == "story_frame_semantics":
            focused_brief = dict(user_payload.get("focused_brief") or {})
            self.responses_by_operation["story_frame_semantics"] = [
                {
                    **low_quality_story_frame_scaffold(),
                    "setting_frame": focused_brief.get("setting_signal") or "Archive city blackout.",
                    "stakes_core": focused_brief.get("core_conflict") or "Prevent coalition collapse.",
                    "tone": focused_brief.get("tone_signal") or "Hopeful civic fantasy.",
                    "world_rules": [
                        focused_brief.get("setting_signal") or "Archive city blackout.",
                        "The main plot advances in fixed beats even when local tactics vary.",
                    ],
                    "truths": [
                        {"text": focused_brief.get("core_conflict") or "Prevent coalition collapse.", "importance": "core"},
                        {"text": focused_brief.get("setting_signal") or "Archive city blackout.", "importance": "core"},
                    ],
                }
            ]
        return super()._invoke_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_output_tokens=max_output_tokens,
            previous_response_id=previous_response_id,
            operation_name=operation_name,
        )


class RecoveringStoryFrameGateway(FakeGateway):
    def __init__(self) -> None:
        responses = default_transport_responses()
        responses["story_frame_glean"] = [story_frame_draft().model_dump(mode="json")]
        super().__init__(responses)

    def _invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, object],
        max_output_tokens: int | None,
        previous_response_id: str | None = None,
        operation_name: str | None = None,
    ):
        if operation_name == "story_frame_semantics":
            focused_brief = dict(user_payload.get("focused_brief") or {})
            self.responses_by_operation["story_frame_semantics"] = [
                {
                    **low_quality_story_frame_scaffold(),
                    "setting_frame": focused_brief.get("setting_signal") or "Archive city blackout.",
                    "stakes_core": focused_brief.get("core_conflict") or "Prevent coalition collapse.",
                    "tone": focused_brief.get("tone_signal") or "Hopeful civic fantasy.",
                    "world_rules": [
                        focused_brief.get("setting_signal") or "Archive city blackout.",
                        "The main plot advances in fixed beats even when local tactics vary.",
                    ],
                    "truths": [
                        {"text": focused_brief.get("core_conflict") or "Prevent coalition collapse.", "importance": "core"},
                        {"text": focused_brief.get("setting_signal") or "Archive city blackout.", "importance": "core"},
                    ],
                }
            ]
        return super()._invoke_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_output_tokens=max_output_tokens,
            previous_response_id=previous_response_id,
            operation_name=operation_name,
        )


def generic_cast_gateway() -> FakeGateway:
    return gateway_with_overrides(
        cast_member_semantics=[
            {
                "name": "Mira Vale",
                "agenda_detail": "Tries to preserve their role in the crisis.",
                "red_line_detail": "Will not lose public legitimacy without resistance.",
                "pressure_detail": "Reacts sharply when pressure threatens public order.",
            },
            {
                "name": "Curator Pell",
                "agenda_detail": "Tries to preserve their role in the crisis.",
                "red_line_detail": "Will not lose public legitimacy without resistance.",
                "pressure_detail": "Reacts sharply when pressure threatens public order.",
            },
            {
                "name": "Broker Seln",
                "agenda_detail": "Tries to preserve their role in the crisis.",
                "red_line_detail": "Will not lose public legitimacy without resistance.",
                "pressure_detail": "Reacts sharply when pressure threatens public order.",
            },
            {
                "name": "Lio Maren",
                "agenda_detail": "Tries to preserve their role in the crisis.",
                "red_line_detail": "Will not lose public legitimacy without resistance.",
                "pressure_detail": "Reacts sharply when pressure threatens public order.",
            },
        ]
    )


def fallback_overview_gateway() -> FakeGateway:
    return gateway_with_overrides(story_frame_semantics=repeated_gateway_error("llm_invalid_json"))


def placeholder_cast_gateway() -> FakeGateway:
    placeholder = [
        {
            "name": "Civic Figure 1",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
        {
            "name": "Civic Figure 2",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
        {
            "name": "Civic Figure 3",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
        {
            "name": "Civic Figure 4",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
        {
            "name": "Civic Figure 1",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
        {
            "name": "Civic Figure 2",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
        {
            "name": "Civic Figure 3",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
        {
            "name": "Civic Figure 4",
            "agenda_detail": "Placeholder agenda.",
            "red_line_detail": "Placeholder red line.",
            "pressure_detail": "Placeholder pressure signature.",
        },
    ]
    return gateway_with_overrides(cast_member_semantics=placeholder)
