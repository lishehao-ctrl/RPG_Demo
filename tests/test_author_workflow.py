from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from rpg_backend.author.checkpointer import graph_config
from rpg_backend.author.contracts import (
    AuthorBundleRequest,
    BeatPlanDraft,
    BeatDraftSpec,
    CastDraft,
    CastOverviewDraft,
    CastOverviewSlotDraft,
    EndingRule,
    EndingRulesDraft,
    FocusedBrief,
    RouteOpportunityPlanDraft,
    RouteAffordancePackDraft,
    OverviewAxisDraft,
    OverviewCastDraft,
    OverviewFlagDraft,
    OverviewTruthDraft,
    StoryFrameDraft,
    StoryOverviewDraft,
)
from rpg_backend.author.gateway import AuthorGatewayError, AuthorLLMGateway, GatewayStructuredResponse
from rpg_backend.author.workflow import (
    assemble_story_overview,
    build_author_graph,
    build_design_bundle,
    build_default_ending_rules,
    build_default_route_opportunity_plan,
    build_default_route_affordance_pack,
    focus_brief,
    run_author_bundle,
)
from rpg_backend.main import app


def _overview_draft() -> StoryOverviewDraft:
    return StoryOverviewDraft(
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
                required_truth_texts=["The succession vote can still hold if public trust does not collapse."],
                detour_budget=1,
                progress_required=2,
                return_hooks=["A coalition fracture makes delay impossible."],
                affordance_tags=["build_trust", "shift_public_narrative", "pay_cost"],
                blocked_affordances=[],
            ),
        ],
    )


def _story_frame_draft() -> StoryFrameDraft:
    overview = _overview_draft()
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


def _cast_draft() -> CastDraft:
    return CastDraft(cast=_overview_draft().cast)


def _cast_overview_draft() -> CastOverviewDraft:
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


def _four_slot_cast_overview_draft() -> CastOverviewDraft:
    draft = _cast_overview_draft()
    return CastOverviewDraft(
        cast_slots=[
            *draft.cast_slots,
            CastOverviewSlotDraft(
                slot_label="Civic Witness",
                public_role="Public advocate",
                relationship_to_protagonist="Presses the protagonist to make the process legible to ordinary citizens.",
                agenda_anchor="Force the crisis response to remain publicly accountable.",
                red_line_anchor="Will not let elite procedure erase the public record.",
                pressure_vector="Turns ambiguity into public scrutiny whenever the room starts closing ranks.",
            ),
        ],
        relationship_summary=[
            *draft.relationship_summary,
            "The civic witness amplifies any gap between elite coordination and public legitimacy.",
        ],
    )


def _beat_plan_draft() -> BeatPlanDraft:
    return BeatPlanDraft(beats=_overview_draft().beats)


def _route_affordance_pack_draft() -> RouteAffordancePackDraft:
    overview = _overview_draft()
    bundle = build_design_bundle(
        _story_frame_draft(),
        _cast_draft(),
        _beat_plan_draft(),
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )
    return build_default_route_affordance_pack(bundle)


def _route_opportunity_plan_draft() -> RouteOpportunityPlanDraft:
    bundle = build_design_bundle(
        _story_frame_draft(),
        _cast_draft(),
        _beat_plan_draft(),
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )
    return build_default_route_opportunity_plan(bundle)


def _ending_rules_draft() -> EndingRulesDraft:
    bundle = build_design_bundle(
        _story_frame_draft(),
        _cast_draft(),
        _beat_plan_draft(),
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )
    return build_default_ending_rules(bundle)


class _FakeClient:
    def __init__(self, payloads: list[dict[str, object] | str]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

        class _Responses:
            def __init__(self, outer: _FakeClient) -> None:
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


class _FakeGateway:
    def generate_story_frame(
        self,
        focused_brief: FocusedBrief,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        assert focused_brief.story_kernel
        return GatewayStructuredResponse(value=_story_frame_draft(), response_id=previous_response_id or "fake-frame")

    def glean_story_frame(
        self,
        focused_brief: FocusedBrief,
        partial_story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        assert focused_brief.story_kernel
        assert partial_story_frame.title
        return GatewayStructuredResponse(value=_story_frame_draft(), response_id=previous_response_id or "fake-frame-glean")

    def generate_cast_overview(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastOverviewDraft]:
        assert focused_brief.story_kernel
        assert story_frame.title
        return GatewayStructuredResponse(value=_cast_overview_draft(), response_id=previous_response_id or "fake-cast-overview")

    def glean_cast_overview(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        partial_cast_overview: CastOverviewDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastOverviewDraft]:
        assert focused_brief.story_kernel
        assert story_frame.title
        assert partial_cast_overview.cast_slots
        return GatewayStructuredResponse(value=_cast_overview_draft(), response_id=previous_response_id or "fake-cast-overview-glean")

    def generate_story_cast(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_overview: CastOverviewDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastDraft]:
        assert focused_brief.story_kernel
        assert story_frame.title
        assert cast_overview.cast_slots
        return GatewayStructuredResponse(value=_cast_draft(), response_id=previous_response_id or "fake-cast")

    def generate_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, object],
        existing_cast: list[dict[str, object]],
        *,
        previous_response_id: str | None = None,
    ):
        assert focused_brief.story_kernel
        assert story_frame.title
        assert cast_slot["slot_label"]
        pool = [
            *_cast_draft().cast,
            OverviewCastDraft(
                name="Lio Maren",
                role="Public advocate",
                agenda="Force the crisis response to remain publicly accountable while pressure keeps rising.",
                red_line="Will not let elite procedure erase the public record of what happened.",
                pressure_signature="Turns ambiguity, secrecy, or procedural drift into public scrutiny.",
            ),
        ]
        member = pool[len(existing_cast)]
        return GatewayStructuredResponse(value=member, response_id=previous_response_id or f"fake-cast-member-{len(existing_cast)+1}")

    def glean_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, object],
        existing_cast: list[dict[str, object]],
        partial_member: dict[str, object],
        *,
        previous_response_id: str | None = None,
    ):
        assert focused_brief.story_kernel
        assert story_frame.title
        assert cast_slot["slot_label"]
        assert partial_member
        pool = [
            *_cast_draft().cast,
            OverviewCastDraft(
                name="Lio Maren",
                role="Public advocate",
                agenda="Force the crisis response to remain publicly accountable while pressure keeps rising.",
                red_line="Will not let elite procedure erase the public record of what happened.",
                pressure_signature="Turns ambiguity, secrecy, or procedural drift into public scrutiny.",
            ),
        ]
        member = pool[len(existing_cast)]
        return GatewayStructuredResponse(value=member, response_id=previous_response_id or f"fake-cast-member-glean-{len(existing_cast)+1}")

    def glean_story_cast(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_overview: CastOverviewDraft,
        partial_cast: CastDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastDraft]:
        assert focused_brief.story_kernel
        assert story_frame.title
        assert cast_overview.cast_slots
        assert partial_cast.cast
        return GatewayStructuredResponse(value=_cast_draft(), response_id=previous_response_id or "fake-cast-glean")

    def generate_beat_plan(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_draft: CastDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[BeatPlanDraft]:
        assert focused_brief.story_kernel
        assert story_frame.title
        assert cast_draft.cast
        return GatewayStructuredResponse(value=_beat_plan_draft(), response_id=previous_response_id or "fake-beats")

    def generate_story_overview(self, focused_brief: FocusedBrief) -> StoryOverviewDraft:
        return assemble_story_overview(_story_frame_draft(), _cast_draft(), _beat_plan_draft())

    def generate_route_opportunity_plan_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        del design_bundle
        return GatewayStructuredResponse(
            value=_route_opportunity_plan_draft(),
            response_id=previous_response_id or "fake-route-opportunities",
        )

    def generate_route_affordance_pack_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        from rpg_backend.author.contracts import AffordanceEffectProfile, RouteUnlockRule

        del design_bundle
        return GatewayStructuredResponse(
            value=RouteAffordancePackDraft(
                route_unlock_rules=[
                    RouteUnlockRule(
                        rule_id="b2_public_cover",
                        beat_id="b2",
                        conditions={"min_stances": {"archivist_sen_stance": 1}},
                        unlock_route_id="public_cover_route",
                        unlock_affordance_tag="shift_public_narrative",
                    )
                ],
                affordance_effect_profiles=[
                    AffordanceEffectProfile(
                        affordance_tag="reveal_truth",
                        default_story_function="reveal",
                        axis_deltas={"civic_pressure": 1},
                        stance_deltas={},
                        can_add_truth=True,
                        can_add_event=False,
                    ),
                    AffordanceEffectProfile(
                        affordance_tag="build_trust",
                        default_story_function="advance",
                        axis_deltas={"political_leverage": 1},
                        stance_deltas={"archivist_sen_stance": 1},
                        can_add_truth=False,
                        can_add_event=True,
                    ),
                    AffordanceEffectProfile(
                        affordance_tag="contain_chaos",
                        default_story_function="stabilize",
                        axis_deltas={"public_panic": -1},
                        stance_deltas={},
                        can_add_truth=False,
                        can_add_event=False,
                    ),
                    AffordanceEffectProfile(
                        affordance_tag="shift_public_narrative",
                        default_story_function="advance",
                        axis_deltas={"public_panic": -1, "political_leverage": 1},
                        stance_deltas={},
                        can_add_truth=False,
                        can_add_event=True,
                    ),
                    AffordanceEffectProfile(
                        affordance_tag="pay_cost",
                        default_story_function="pay_cost",
                        axis_deltas={"civic_pressure": -1},
                        stance_deltas={},
                        can_add_truth=False,
                        can_add_event=True,
                    ),
                ],
            ),
            response_id=previous_response_id or "fake-rulepack",
        )

    def generate_ending_rules_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        from rpg_backend.author.contracts import EndingRule

        del design_bundle
        return GatewayStructuredResponse(
            value=EndingRulesDraft(
                ending_rules=[
                    EndingRule(ending_id="collapse", priority=1, conditions={"min_axes": {"civic_pressure": 5}}),
                    EndingRule(ending_id="pyrrhic", priority=2, conditions={"min_axes": {"political_leverage": 5}}),
                    EndingRule(ending_id="mixed", priority=10, conditions={}),
                ]
            ),
            response_id=previous_response_id or "fake-endings",
        )

    def glean_ending_rules(self, design_bundle, partial_ending_rules, *, previous_response_id: str | None = None):  # noqa: ANN001
        del design_bundle, partial_ending_rules
        return self.generate_ending_rules_result(design_bundle=None, previous_response_id=previous_response_id)

    def generate_global_rulepack_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        from rpg_backend.author.contracts import RulePack

        route_affordance_pack = self.generate_route_affordance_pack_result(
            design_bundle,
            previous_response_id=previous_response_id,
        )
        ending_rules = self.generate_ending_rules_result(
            design_bundle,
            previous_response_id=route_affordance_pack.response_id,
        )
        return GatewayStructuredResponse(
            value=RulePack(
                route_unlock_rules=route_affordance_pack.value.route_unlock_rules,
                ending_rules=ending_rules.value.ending_rules,
                affordance_effect_profiles=route_affordance_pack.value.affordance_effect_profiles,
            ),
            response_id=ending_rules.response_id,
        )

    def generate_global_rulepack(self, design_bundle):  # noqa: ANN001
        return self.generate_global_rulepack_result(design_bundle).value


class _FallbackRulepackGateway(_FakeGateway):
    def generate_route_opportunity_plan_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        del design_bundle, previous_response_id
        raise AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502)


class _FallbackEndingRulesGateway(_FakeGateway):
    def generate_ending_rules_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        del design_bundle, previous_response_id
        raise AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502)

    def glean_ending_rules(self, design_bundle, partial_ending_rules, *, previous_response_id: str | None = None):  # noqa: ANN001
        del design_bundle, partial_ending_rules, previous_response_id
        raise AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502)


class _LowQualityEndingRulesGateway(_FakeGateway):
    def generate_ending_rules_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        del design_bundle, previous_response_id
        return GatewayStructuredResponse(
            value=EndingRulesDraft(
                ending_rules=[
                    # Valid schema, but low-signal content that should trip the workflow quality gate.
                    EndingRule(ending_id="mixed", priority=100, conditions={}),
                    EndingRule(ending_id="mixed", priority=100, conditions={}),
                ]
            ),
            response_id="low-quality-endings",
        )

    def glean_ending_rules(self, design_bundle, partial_ending_rules, *, previous_response_id: str | None = None):  # noqa: ANN001
        del partial_ending_rules
        return _FakeGateway().generate_ending_rules_result(design_bundle, previous_response_id=previous_response_id)


class _LowQualityRouteOpportunitiesGateway(_FakeGateway):
    def generate_route_opportunity_plan_result(self, design_bundle, *, previous_response_id: str | None = None):  # noqa: ANN001
        del design_bundle, previous_response_id
        return GatewayStructuredResponse(
            value=RouteOpportunityPlanDraft(
                opportunities=[
                    {
                        "beat_id": "b1",
                        "unlock_route_id": "b1_single_route",
                        "unlock_affordance_tag": "reveal_truth",
                        "triggers": [
                            {"kind": "truth", "target_id": "truth_1"},
                        ],
                    }
                ]
            ),
            response_id="low-quality-routes",
        )


class _LowQualityStoryFrameGateway(_FakeGateway):
    def generate_story_frame(
        self,
        focused_brief: FocusedBrief,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        del previous_response_id
        return GatewayStructuredResponse(
            value=StoryFrameDraft(
                title=focused_brief.story_kernel,
                premise=focused_brief.story_kernel,
                tone=focused_brief.tone_signal,
                stakes=f"If the player fails, {focused_brief.core_conflict}",
                style_guard="Keep it readable.",
                world_rules=[focused_brief.setting_signal, "The main plot advances in fixed beats even when local tactics vary."],
                truths=[
                    OverviewTruthDraft(text=focused_brief.core_conflict, importance="core"),
                    OverviewTruthDraft(text=focused_brief.setting_signal, importance="core"),
                ],
                state_axis_choices=_story_frame_draft().state_axis_choices,
                flags=_story_frame_draft().flags,
            ),
            response_id="low-quality-frame",
        )

    def glean_story_frame(
        self,
        focused_brief: FocusedBrief,
        partial_story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        del focused_brief, partial_story_frame, previous_response_id
        raise AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502)


class _RecoveringStoryFrameGateway(_FakeGateway):
    def generate_story_frame(
        self,
        focused_brief: FocusedBrief,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        del previous_response_id
        return GatewayStructuredResponse(
            value=StoryFrameDraft(
                title=focused_brief.story_kernel,
                premise=focused_brief.story_kernel,
                tone=focused_brief.tone_signal,
                stakes=f"If the player fails, {focused_brief.core_conflict}",
                style_guard="Keep it readable.",
                world_rules=[focused_brief.setting_signal, "The main plot advances in fixed beats even when local tactics vary."],
                truths=[
                    OverviewTruthDraft(text=focused_brief.core_conflict, importance="core"),
                    OverviewTruthDraft(text=focused_brief.setting_signal, importance="core"),
                ],
                state_axis_choices=_story_frame_draft().state_axis_choices,
                flags=_story_frame_draft().flags,
            ),
            response_id="recovering-low-quality-frame",
        )

    def glean_story_frame(
        self,
        focused_brief: FocusedBrief,
        partial_story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        del focused_brief, partial_story_frame, previous_response_id
        return GatewayStructuredResponse(value=_story_frame_draft(), response_id="recovered-frame")


class _LowQualityCastOverviewGateway(_FakeGateway):
    def generate_cast_overview(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastOverviewDraft]:
        del focused_brief, story_frame, previous_response_id
        return GatewayStructuredResponse(
            value=CastOverviewDraft(
                cast_slots=[
                    CastOverviewSlotDraft(
                        slot_label="Civic Role 1",
                        public_role="Stakeholder",
                        relationship_to_protagonist="Complicates or supports the protagonist under pressure.",
                        agenda_anchor="Protect their institutional stake while the crisis unfolds.",
                        red_line_anchor="Will not accept being cut out of the settlement.",
                        pressure_vector="Pushes harder for leverage as public pressure rises.",
                    ),
                    CastOverviewSlotDraft(
                        slot_label="Civic Role 2",
                        public_role="Stakeholder",
                        relationship_to_protagonist="Complicates or supports the protagonist under pressure.",
                        agenda_anchor="Protect their institutional stake while the crisis unfolds.",
                        red_line_anchor="Will not accept being cut out of the settlement.",
                        pressure_vector="Pushes harder for leverage as public pressure rises.",
                    ),
                    CastOverviewSlotDraft(
                        slot_label="Civic Role 3",
                        public_role="Stakeholder",
                        relationship_to_protagonist="Complicates or supports the protagonist under pressure.",
                        agenda_anchor="Protect their institutional stake while the crisis unfolds.",
                        red_line_anchor="Will not accept being cut out of the settlement.",
                        pressure_vector="Pushes harder for leverage as public pressure rises.",
                    ),
                ],
                relationship_summary=[
                    "Generic relation one.",
                    "Generic relation two.",
                ],
            ),
            response_id="low-quality-cast-overview",
        )


class _GenericCastGateway(_FakeGateway):
    def generate_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, object],
        existing_cast: list[dict[str, object]],
        *,
        previous_response_id: str | None = None,
    ):
        del focused_brief, story_frame, cast_slot, previous_response_id
        members = [
            OverviewCastDraft(
                name="Mira Vale",
                role="Mediator",
                agenda="Mira Vale tries to preserve their role in the crisis.",
                red_line="Mira Vale will not lose public legitimacy without resistance.",
                pressure_signature="Mira Vale reacts sharply when pressure threatens public order.",
            ),
            OverviewCastDraft(
                name="Curator Pell",
                role="Institutional guardian",
                agenda="Curator Pell tries to preserve their role in the crisis.",
                red_line="Curator Pell will not lose public legitimacy without resistance.",
                pressure_signature="Curator Pell reacts sharply when pressure threatens public order.",
            ),
            OverviewCastDraft(
                name="Broker Seln",
                role="Coalition rival",
                agenda="Broker Seln tries to preserve their role in the crisis.",
                red_line="Broker Seln will not lose public legitimacy without resistance.",
                pressure_signature="Broker Seln reacts sharply when pressure threatens public order.",
            ),
            OverviewCastDraft(
                name="Lio Maren",
                role="Public advocate",
                agenda="Lio Maren tries to preserve their role in the crisis.",
                red_line="Lio Maren will not lose public legitimacy without resistance.",
                pressure_signature="Lio Maren reacts sharply when pressure threatens public order.",
            ),
        ]
        return GatewayStructuredResponse(
            value=members[len(existing_cast)],
            response_id="generic-cast",
        )


class _FallbackOverviewGateway(_FakeGateway):
    def generate_story_frame(
        self,
        focused_brief: FocusedBrief,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        del focused_brief, previous_response_id
        raise AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502)


class _PlaceholderCastGateway(_FakeGateway):
    def generate_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, object],
        existing_cast: list[dict[str, object]],
        *,
        previous_response_id: str | None = None,
    ):
        del focused_brief, story_frame, cast_slot, previous_response_id
        member = OverviewCastDraft(
            name=f"Civic Figure {len(existing_cast) + 1}",
            role="Stakeholder",
            agenda="Placeholder agenda.",
            red_line="Placeholder red line.",
            pressure_signature="Placeholder pressure signature.",
        )
        return GatewayStructuredResponse(
            value=member,
            response_id="placeholder-cast",
        )

    def glean_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, object],
        existing_cast: list[dict[str, object]],
        partial_member: dict[str, object],
        *,
        previous_response_id: str | None = None,
    ):
        return self.generate_story_cast_member(
            focused_brief,
            story_frame,
            cast_slot,
            existing_cast,
            previous_response_id=previous_response_id,
        )


class _FourSlotCastGateway(_FakeGateway):
    def generate_cast_overview(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastOverviewDraft]:
        assert focused_brief.story_kernel
        assert story_frame.title
        return GatewayStructuredResponse(
            value=_four_slot_cast_overview_draft(),
            response_id=previous_response_id or "fake-four-slot-overview",
        )

    def generate_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, object],
        existing_cast: list[dict[str, object]],
        *,
        previous_response_id: str | None = None,
    ):
        assert focused_brief.story_kernel
        assert story_frame.title
        pool = [
            _cast_draft().cast[0],
            _cast_draft().cast[1],
            _cast_draft().cast[2],
            OverviewCastDraft(
                name="Lio Maren",
                role="Public advocate",
                agenda="Force the crisis response to remain publicly accountable.",
                red_line="Will not let elite procedure erase the public record.",
                pressure_signature="Turns ambiguity into public scrutiny whenever the room starts closing ranks.",
            ),
        ]
        return GatewayStructuredResponse(
            value=pool[len(existing_cast)],
            response_id=previous_response_id or f"fake-four-slot-member-{len(existing_cast)+1}",
        )


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
    bundle = build_design_bundle(
        _story_frame_draft(),
        _cast_draft(),
        _beat_plan_draft(),
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )

    assert bundle.story_bible.cast[0].npc_id
    assert bundle.state_schema.axes[0].axis_id == "external_pressure"
    assert bundle.beat_spine[0].beat_id == "b1"
    assert bundle.beat_spine[1].required_events == ["b2.milestone"]


def test_gateway_formats_requests_and_parses_models() -> None:
    client = _FakeClient(
        [
            _story_frame_draft().model_dump(mode="json"),
            _cast_overview_draft().model_dump(mode="json"),
            _cast_draft().model_dump(mode="json"),
            _beat_plan_draft().model_dump(mode="json"),
        ]
    )
    gateway = AuthorLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        max_output_tokens_overview=700,
        max_output_tokens_beat_plan=900,
        max_output_tokens_rulepack=900,
        use_session_cache=True,
    )

    overview = gateway.generate_story_overview(
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        )
    )

    assert overview.title == "The Archive Blackout"
    assert client.calls[0]["model"] == "demo-model"
    assert client.calls[0]["max_output_tokens"] == 700
    assert "Return one strict JSON object matching StoryFrameDraft" in client.calls[0]["instructions"]
    assert "Return one strict JSON object matching CastOverviewDraft" in client.calls[1]["instructions"]
    assert "Return one strict JSON object matching CastDraft" in client.calls[2]["instructions"]
    assert "Return one strict JSON object matching BeatPlanDraft" in client.calls[3]["instructions"]
    assert client.calls[1]["previous_response_id"] == "resp-1"
    assert client.calls[2]["previous_response_id"] == "resp-2"
    assert client.calls[3]["previous_response_id"] == "resp-3"
    import json
    beat_payload = json.loads(client.calls[3]["input"])
    assert "author_context" in beat_payload
    assert "story_frame" not in beat_payload
    assert "cast" not in beat_payload


def test_gateway_raises_stable_error_for_invalid_json() -> None:
    client = _FakeClient(["not json at all"])
    gateway = AuthorLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        max_output_tokens_overview=700,
        max_output_tokens_beat_plan=900,
        max_output_tokens_rulepack=900,
    )

    try:
        gateway.generate_story_overview(
            FocusedBrief(
                story_kernel="Hold the city together.",
                setting_signal="Archive city blackout.",
                core_conflict="Prevent coalition collapse.",
                tone_signal="Hopeful civic fantasy.",
                hard_constraints=[],
                forbidden_tones=[],
            )
        )
    except AuthorGatewayError as exc:
        assert exc.code == "llm_invalid_json"
    else:  # pragma: no cover
        raise AssertionError("Expected AuthorGatewayError")


def test_rule_generation_uses_author_context_packets() -> None:
    client = _FakeClient(
        [
            _route_opportunity_plan_draft().model_dump(mode="json"),
            _ending_rules_draft().model_dump(mode="json"),
        ]
    )
    gateway = AuthorLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        max_output_tokens_overview=700,
        max_output_tokens_beat_plan=900,
        max_output_tokens_rulepack=900,
        use_session_cache=True,
    )
    bundle = build_design_bundle(
        _story_frame_draft(),
        _cast_draft(),
        _beat_plan_draft(),
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )

    gateway.generate_route_opportunity_plan_result(bundle, previous_response_id="resp-a")
    gateway.generate_ending_rules_result(bundle, previous_response_id="resp-b")

    import json
    route_payload = json.loads(client.calls[0]["input"])
    ending_payload = json.loads(client.calls[1]["input"])
    assert "author_context" in route_payload
    assert "story_bible" not in route_payload
    assert "state_schema" not in route_payload
    assert "beat_spine" not in route_payload
    assert "author_context" in ending_payload
    assert "story_bible" not in ending_payload


def test_author_graph_can_checkpoint_state_snapshot() -> None:
    graph = build_author_graph(gateway=_FakeGateway(), checkpointer=InMemorySaver())
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
    assert snapshot.values["route_opportunity_plan_draft"].opportunities
    assert snapshot.values["route_affordance_pack_draft"].affordance_effect_profiles
    assert snapshot.values["ending_rules_draft"].ending_rules
    assert snapshot.values["design_bundle"].story_bible.title
    assert snapshot.values["rule_pack"].ending_rules
    assert snapshot.values["author_session_response_id"]


def test_author_graph_generates_dynamic_number_of_cast_members_from_cast_overview() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_FakeGateway(),
    )

    assert len(result.state["cast_overview_draft"].cast_slots) == 4
    assert len(result.state["cast_member_drafts"]) == 4
    assert len(result.bundle.story_bible.cast) == 4
    assert result.bundle.story_bible.cast[-1].name == "Lio Maren"


def test_author_design_bundle_api_returns_bundle() -> None:
    import rpg_backend.main as main_module

    client = TestClient(app)
    original = main_module.get_author_llm_gateway
    main_module.get_author_llm_gateway = lambda: _FakeGateway()
    try:
        response = client.post(
            "/author/design-bundles",
            json=AuthorBundleRequest(
                raw_brief="A civic fantasy about preserving trust during a blackout election."
            ).model_dump(mode="json"),
        )
    finally:
        main_module.get_author_llm_gateway = original

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert body["bundle"]["focused_brief"]["story_kernel"]
    assert body["bundle"]["story_bible"]["cast"]
    assert body["bundle"]["rule_pack"]["ending_rules"]


def test_author_design_bundle_api_maps_gateway_errors() -> None:
    import rpg_backend.main as main_module

    def _bad_gateway():
        raise AuthorGatewayError(code="llm_config_missing", message="missing config", status_code=500)

    client = TestClient(app)
    original = main_module.get_author_llm_gateway
    main_module.get_author_llm_gateway = _bad_gateway
    try:
        response = client.post(
            "/author/design-bundles",
            json={"raw_brief": "A civic fantasy about preserving trust during a blackout election."},
        )
    finally:
        main_module.get_author_llm_gateway = original

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "llm_config_missing"


def test_author_bundle_falls_back_to_default_rulepack_when_rulepack_payload_is_malformed() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_FallbackRulepackGateway(),
    )

    assert result.bundle.rule_pack.ending_rules
    assert result.bundle.rule_pack.affordance_effect_profiles


def test_author_bundle_falls_back_to_default_endings_when_ending_payload_is_malformed() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_FallbackEndingRulesGateway(),
    )

    assert result.bundle.rule_pack.ending_rules
    assert {item.ending_id for item in result.bundle.rule_pack.ending_rules} == {"collapse", "pyrrhic", "mixed"}


def test_author_bundle_replaces_low_quality_endings_with_default_endings() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_LowQualityEndingRulesGateway(),
    )

    assert {item.ending_id for item in result.bundle.rule_pack.ending_rules} == {"collapse", "pyrrhic", "mixed"}
    assert any(item.conditions.min_axes for item in result.bundle.rule_pack.ending_rules if item.ending_id != "mixed")


def test_default_endings_include_story_specific_conditions() -> None:
    bundle = build_design_bundle(
        _story_frame_draft(),
        _cast_draft(),
        _beat_plan_draft(),
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )

    ending_rules = build_default_ending_rules(bundle).ending_rules
    collapse = next(item for item in ending_rules if item.ending_id == "collapse")
    pyrrhic = next(item for item in ending_rules if item.ending_id == "pyrrhic")

    assert collapse.conditions.required_truths or collapse.conditions.required_events or collapse.conditions.required_flags
    assert pyrrhic.conditions.required_truths or pyrrhic.conditions.required_events or pyrrhic.conditions.required_flags


def test_author_bundle_replaces_low_quality_route_opportunities_with_default_routes() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_LowQualityRouteOpportunitiesGateway(),
    )

    assert len(result.bundle.rule_pack.route_unlock_rules) >= 2
    assert len({item.beat_id for item in result.bundle.rule_pack.route_unlock_rules}) >= 2


def test_author_bundle_replaces_low_quality_story_frame_with_default_story_frame() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_LowQualityStoryFrameGateway(),
    )

    assert result.bundle.story_bible.premise.startswith("In ")
    assert "player fails" not in result.bundle.story_bible.stakes.casefold()


def test_author_bundle_recovers_low_quality_story_frame_via_glean() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_RecoveringStoryFrameGateway(),
    )

    assert result.bundle.story_bible.title == "The Archive Blackout"
    assert result.bundle.story_bible.premise == _story_frame_draft().premise


def test_author_bundle_replaces_low_quality_cast_overview_with_default_cast_overview() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_LowQualityCastOverviewGateway(),
    )

    slot_labels = [item.slot_label for item in result.state["cast_overview_draft"].cast_slots]
    assert slot_labels == ["Mediator Anchor", "Institutional Guardian", "Leverage Broker", "Civic Witness"]


def test_author_bundle_repairs_generic_cast_fields_without_dropping_named_characters() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_GenericCastGateway(),
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
        gateway=_PlaceholderCastGateway(),
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
        gateway=_FallbackOverviewGateway(),
    )

    assert result.bundle.story_bible.title
    assert result.bundle.beat_spine
