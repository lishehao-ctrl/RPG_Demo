from __future__ import annotations

from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver

from rpg_backend.author.checkpointer import graph_config
from rpg_backend.author.contracts import (
    AuthorBundleRequest,
    BeatPlanProseDraft,
    BeatPlanSkeletonDraft,
    BeatPlanDraft,
    BeatDraftSpec,
    BeatProseSpec,
    BeatSkeletonSpec,
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
    StoryFrameProseDraft,
    StoryFrameScaffoldDraft,
    StoryOverviewDraft,
)
from rpg_backend.author.gateway import AuthorGatewayError, AuthorLLMGateway
from rpg_backend.author.compiler.router import plan_story_theme
from rpg_backend.author.generation import beats as beat_generation
from rpg_backend.author.generation import cast as cast_generation
from rpg_backend.author.generation import endings as ending_generation
from rpg_backend.author.generation import routes as route_generation
from rpg_backend.author.generation import story_frame as story_generation
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


def _story_frame_scaffold_draft() -> StoryFrameScaffoldDraft:
    story_frame = _story_frame_draft()
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


def _story_frame_prose_draft() -> StoryFrameProseDraft:
    story_frame = _story_frame_draft()
    return StoryFrameProseDraft(
        title=story_frame.title,
        premise=story_frame.premise,
        stakes=story_frame.stakes,
        style_guard=story_frame.style_guard,
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


def _beat_plan_draft() -> BeatPlanDraft:
    return BeatPlanDraft(beats=_overview_draft().beats)


def _beat_plan_skeleton_draft() -> BeatPlanSkeletonDraft:
    overview = _overview_draft()
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


def _beat_plan_prose_draft() -> BeatPlanProseDraft:
    overview = _overview_draft()
    return BeatPlanProseDraft(
        beats=[
            BeatProseSpec(
                title=beat.title,
                goal=beat.goal,
                return_hooks=beat.return_hooks,
            )
            for beat in overview.beats
        ]
    )


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


def _cast_member_semantics_payloads() -> list[dict[str, str]]:
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


def _ending_anchor_suggestion_payload() -> dict[str, object]:
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


def _default_transport_responses() -> dict[str, list[dict[str, object] | Exception]]:
    return {
        "story_frame_semantics": [
            _story_frame_scaffold_draft().model_dump(mode="json"),
        ],
        "cast_member_semantics": list(_cast_member_semantics_payloads()),
        "beat_plan_generate": [
            _beat_plan_skeleton_draft().model_dump(mode="json"),
        ],
        "route_opportunity_generate": [
            _route_opportunity_plan_draft().model_dump(mode="json"),
        ],
        "ending_anchor_generate": [
            _ending_anchor_suggestion_payload(),
        ],
    }


def _low_quality_story_frame_scaffold() -> dict[str, object]:
    return {
        "title_seed": "Untitled Crisis",
        "setting_frame": "Archive city blackout.",
        "protagonist_mandate": "Hold the city together",
        "opposition_force": "Prevent coalition collapse.",
        "stakes_core": "Prevent coalition collapse.",
        "tone": "Hopeful civic fantasy.",
        "world_rules": ["Archive city blackout.", "The main plot advances in fixed beats even when local tactics vary."],
        "truths": [
            {"text": "Prevent coalition collapse.", "importance": "core"},
            {"text": "Archive city blackout.", "importance": "core"},
        ],
        "state_axis_choices": [item.model_dump(mode="json") for item in _story_frame_draft().state_axis_choices],
        "flags": [item.model_dump(mode="json") for item in _story_frame_draft().flags],
    }


class _FakeGateway:
    def __init__(self, responses_by_operation: dict[str, list[dict[str, object] | Exception]] | None = None) -> None:
        self.responses_by_operation = responses_by_operation or _default_transport_responses()
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


class _FallbackRulepackGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["route_opportunity_generate"] = [
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
        ]
        super().__init__(responses)


class _FallbackEndingRulesGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["ending_anchor_generate"] = [
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
        ]
        super().__init__(responses)


class _NonCanonicalEndingPriorityGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["ending_anchor_generate"] = [
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
        super().__init__(responses)


class _FallbackBeatPlanGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["beat_plan_generate"] = [
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
        ]
        super().__init__(responses)


class _LowQualityRouteOpportunitiesGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["route_opportunity_generate"] = [
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
        super().__init__(responses)


class _NarrowRouteDiversityGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["route_opportunity_generate"] = [
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
        super().__init__(responses)


class _LowQualityStoryFrameGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
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
                    **_low_quality_story_frame_scaffold(),
                    "setting_frame": focused_brief.get("setting_signal") or "Archive city blackout.",
                    "protagonist_mandate": "a mediator keeping a city together",
                    "opposition_force": "institutional pressure closing in",
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


class _RecoveringStoryFrameGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["story_frame_glean"] = [_story_frame_draft().model_dump(mode="json")]
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
                    **_low_quality_story_frame_scaffold(),
                    "setting_frame": focused_brief.get("setting_signal") or "Archive city blackout.",
                    "protagonist_mandate": "a mediator keeping a city together",
                    "opposition_force": "institutional pressure closing in",
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


class _GenericCastGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["cast_member_semantics"] = [
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
        super().__init__(responses)


class _FallbackOverviewGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
        responses["story_frame_semantics"] = [
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
            AuthorGatewayError(code="llm_invalid_json", message="provider returned empty content", status_code=502),
        ]
        super().__init__(responses)


class _PlaceholderCastGateway(_FakeGateway):
    def __init__(self) -> None:
        responses = _default_transport_responses()
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
        responses["cast_member_semantics"] = placeholder
        super().__init__(responses)


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
    assert bundle.beat_spine[0].pressure_axis_id == "external_pressure"
    assert bundle.beat_spine[1].route_pivot_tag == "shift_public_narrative"
    assert bundle.beat_spine[1].required_events == ["b2.fracture"]


def test_gateway_formats_requests_and_parses_models() -> None:
    client = _FakeClient(
        [
            _story_frame_scaffold_draft().model_dump(mode="json"),
            _cast_overview_draft().model_dump(mode="json"),
            _cast_draft().model_dump(mode="json"),
            _beat_plan_skeleton_draft().model_dump(mode="json"),
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

    focused_brief = FocusedBrief(
        story_kernel="Hold the city together.",
        setting_signal="Archive city blackout.",
        core_conflict="Prevent coalition collapse.",
        tone_signal="Hopeful civic fantasy.",
        hard_constraints=[],
        forbidden_tones=[],
    )
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
    overview = assemble_story_overview(story_frame.value, cast.value, beat_plan.value)

    assert overview.title == "Archive Blackout"
    assert client.calls[0]["model"] == "demo-model"
    assert client.calls[0]["max_output_tokens"] == 800
    assert "Return one strict JSON object matching StoryFrameScaffoldDraft" in client.calls[0]["instructions"]
    assert "Return one strict JSON object matching CastOverviewDraft" in client.calls[1]["instructions"]
    assert "Return one strict JSON object matching CastDraft" in client.calls[2]["instructions"]
    assert "Return one strict JSON object matching BeatPlanSkeletonDraft" in client.calls[3]["instructions"]
    assert client.calls[1]["previous_response_id"] == "resp-1"
    assert client.calls[2]["previous_response_id"] == "resp-2"
    assert client.calls[3]["previous_response_id"] == "resp-3"
    import json
    beat_skeleton_payload = json.loads(client.calls[3]["input"])
    assert "author_context" in beat_skeleton_payload
    assert "story_frame" not in beat_skeleton_payload
    assert "cast" not in beat_skeleton_payload


def test_gateway_compiles_story_frame_from_semantics_without_second_llm_call() -> None:
    client = _FakeClient(
        [
            _story_frame_scaffold_draft().model_dump(mode="json"),
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

    story_frame = story_generation.generate_story_frame(
        gateway,
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        )
    )

    assert story_frame.value.title == "Archive Blackout"
    assert story_frame.response_id == "resp-1"
    assert story_frame.value.premise.startswith("In ")
    assert len(client.calls) == 1


def test_gateway_retries_story_frame_semantics_after_invalid_json() -> None:
    client = _FakeClient(
        [
            "not json at all",
            _story_frame_scaffold_draft().model_dump(mode="json"),
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

    story_frame = story_generation.generate_story_frame(
        gateway,
        FocusedBrief(
            story_kernel="A mediator keeping a city together",
            setting_signal="city during a blackout and succession crisis",
            core_conflict="keep a city together while a blackout and succession crisis strains civic order",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        )
    )

    assert len(client.calls) == 2
    assert story_frame.value.title == "Archive Blackout"


def test_gateway_stabilizes_generic_story_frame_scaffold_before_compile() -> None:
    client = _FakeClient(
        [
            {
                "title_seed": "A Mediator Keeping A City Together",
                "setting_frame": "city during a blackout and succession crisis",
                "protagonist_mandate": "a mediator keeping a city together",
                "opposition_force": "keep a city together while a blackout and succession crisis strains civic order",
                "stakes_core": "Prevent coalition collapse.",
                "tone": "hopeful political fantasy",
                "world_rules": _story_frame_draft().world_rules,
                "truths": [item.model_dump(mode="json") for item in _story_frame_draft().truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in _story_frame_draft().state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in _story_frame_draft().flags],
            },
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

    story_frame = story_generation.generate_story_frame(
        gateway,
        FocusedBrief(
            story_kernel="A mediator keeping a city together",
            setting_signal="city during a blackout and succession crisis",
            core_conflict="keep a city together while a blackout and succession crisis strains civic order",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        )
    )

    assert story_frame.value.title == "The Dimmed Accord"
    assert "A Mediator Keeping A City Together" not in story_frame.value.premise


def test_gateway_compiles_beat_plan_from_single_semantics_call() -> None:
    client = _FakeClient(
        [
            _beat_plan_skeleton_draft().model_dump(mode="json"),
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

    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
        _story_frame_draft(),
        _cast_draft(),
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
    client = _FakeClient(
        [
            "not json at all",
            _beat_plan_skeleton_draft().model_dump(mode="json"),
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

    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
        _story_frame_draft(),
        _cast_draft(),
    )

    assert len(client.calls) == 2
    assert [beat.title for beat in beat_plan.value.beats] == [
        "The First Nightfall",
        "The Public Ledger",
        "The Dawn Bargain",
    ]


def test_gateway_compiles_cast_member_semantics_and_replaces_role_label_name() -> None:
    client = _FakeClient(
        [
            {
                "name": "Leverage Broker",
                "agenda_detail": "Uses a private shipping ledger to squeeze concessions out of every public delay.",
                "red_line_detail": "Will burn the room down politically before accepting exclusion from the settlement.",
                "pressure_detail": "Starts framing every compromise as proof that the balance of power must change immediately.",
            }
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

    slot = _cast_overview_draft().cast_slots[2].model_dump(mode="json")
    member = cast_generation.generate_story_cast_member(
        gateway,
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
        _story_frame_draft(),
        slot,
        existing_cast=[
            _cast_draft().cast[0].model_dump(mode="json"),
            _cast_draft().cast[1].model_dump(mode="json"),
        ],
    )

    assert member.value.name != "Leverage Broker"
    assert member.value.role == "Coalition rival"
    assert "Exploit the blackout to reshape the balance of power." in member.value.agenda
    assert "Will not accept being shut out of the final order." in member.value.red_line
    assert "Frames every emergency as proof that someone else should lose authority." in member.value.pressure_signature


def test_gateway_retries_cast_member_semantics_after_invalid_json() -> None:
    client = _FakeClient(
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
    gateway = AuthorLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        max_output_tokens_overview=700,
        max_output_tokens_beat_plan=900,
        max_output_tokens_rulepack=900,
        use_session_cache=True,
    )

    slot = _cast_overview_draft().cast_slots[2].model_dump(mode="json")
    member = cast_generation.generate_story_cast_member(
        gateway,
        FocusedBrief(
            story_kernel="Hold the city together.",
            setting_signal="Archive city blackout.",
            core_conflict="Prevent coalition collapse.",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
        _story_frame_draft(),
        slot,
        existing_cast=[
            _cast_draft().cast[0].model_dump(mode="json"),
            _cast_draft().cast[1].model_dump(mode="json"),
        ],
    )

    assert len(client.calls) == 2
    assert member.value.name == "Mara Kestrel"
    assert "Exploit the blackout to reshape the balance of power." in member.value.agenda


def test_gateway_raises_stable_error_for_invalid_json() -> None:
    client = _FakeClient(["not json at all", "not json at all", "not json at all"])
    gateway = AuthorLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        max_output_tokens_overview=700,
        max_output_tokens_beat_plan=900,
        max_output_tokens_rulepack=900,
    )

    try:
        story_generation.generate_story_frame(
            gateway,
            FocusedBrief(
                story_kernel="Hold the city together.",
                setting_signal="Archive city blackout.",
                core_conflict="Prevent coalition collapse.",
                tone_signal="Hopeful civic fantasy.",
                hard_constraints=[],
                forbidden_tones=[],
            ),
        )
    except AuthorGatewayError as exc:
        assert exc.code == "llm_invalid_json"
    else:  # pragma: no cover
        raise AssertionError("Expected AuthorGatewayError")


def test_rule_generation_uses_author_context_packets() -> None:
    client = _FakeClient(
        [
            _route_opportunity_plan_draft().model_dump(mode="json"),
            _ending_anchor_suggestion_payload(),
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

    route_generation.generate_route_opportunity_plan_result(gateway, bundle, previous_response_id="resp-a")
    ending_generation.generate_ending_anchor_suggestions(gateway, bundle, previous_response_id="resp-b")

    import json
    route_payload = json.loads(client.calls[0]["input"])
    ending_payload = json.loads(client.calls[1]["input"])
    assert "author_context" in route_payload
    assert "story_bible" not in route_payload
    assert "state_schema" not in route_payload
    assert "beat_spine" not in route_payload
    assert "author_context" in ending_payload
    assert "story_bible" not in ending_payload


def test_theme_router_classifies_harbor_quarantine_into_logistics_strategy() -> None:
    decision = plan_story_theme(
        FocusedBrief(
            story_kernel="A harbor inspector preventing collapse.",
            setting_signal="port city under quarantine and supply panic",
            core_conflict="keep the harbor operating while quarantine politics escalate",
            tone_signal="Tense civic fantasy",
            hard_constraints=[],
            forbidden_tones=[],
        ),
        StoryFrameDraft.model_validate(
            {
                "title": "The Harbor Compact",
                "premise": "In a harbor city under quarantine, an inspector must keep trade moving while panic spreads through the port.",
                "tone": "Tense civic fantasy",
                "stakes": "If inspection authority breaks, the city turns scarcity into factional seizure.",
                "style_guard": "Keep it civic and procedural.",
                "world_rules": ["Trade and legitimacy are linked.", "The main plot advances in fixed beats."],
                "truths": [item.model_dump(mode="json") for item in _story_frame_draft().truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in _story_frame_draft().state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in _story_frame_draft().flags],
            }
        ),
    )

    assert decision.primary_theme == "logistics_quarantine_crisis"
    assert decision.beat_plan_strategy == "single_semantic_compile"
    assert "harbor" in decision.modifiers


def test_theme_router_classifies_archive_record_into_single_semantic_strategy() -> None:
    decision = plan_story_theme(
        FocusedBrief(
            story_kernel="An archivist preserving public trust.",
            setting_signal="archive hall during an emergency vote",
            core_conflict="verify altered civic records before the result hardens into public truth",
            tone_signal="Hopeful civic fantasy",
            hard_constraints=[],
            forbidden_tones=[],
        ),
        StoryFrameDraft.model_validate(
            {
                "title": "The Unbroken Ledger",
                "premise": "In a city archive under pressure, an archivist must restore altered records before rumor replaces the public record.",
                "tone": "Hopeful civic fantasy",
                "stakes": "If the archive fails, the vote loses legitimacy and the city fractures around competing truths.",
                "style_guard": "Keep it civic and procedural.",
                "world_rules": ["Records and legitimacy move together.", "The main plot advances in fixed beats."],
                "truths": [item.model_dump(mode='json') for item in _story_frame_draft().truths],
                "state_axis_choices": [item.model_dump(mode='json') for item in _story_frame_draft().state_axis_choices],
                "flags": [item.model_dump(mode='json') for item in _story_frame_draft().flags],
            }
        ),
    )

    assert decision.primary_theme == "truth_record_crisis"
    assert decision.beat_plan_strategy == "single_semantic_compile"
    assert "archive" in decision.modifiers


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
        gateway=_FakeGateway(),
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
        gateway=_FallbackRulepackGateway(),
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
        gateway=_FallbackEndingRulesGateway(),
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
        gateway=_NonCanonicalEndingPriorityGateway(),
    )

    assert [(item.ending_id, item.priority) for item in result.bundle.rule_pack.ending_rules] == [
        ("collapse", 1),
        ("pyrrhic", 2),
        ("mixed", 10),
    ]


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
    axis_kind_by_id = {item.axis_id: item.kind for item in bundle.state_schema.axes}
    assert any(axis_kind_by_id.get(axis_id) != "pressure" for axis_id in pyrrhic.conditions.min_axes)


def test_author_bundle_replaces_low_quality_route_opportunities_with_default_routes() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_LowQualityRouteOpportunitiesGateway(),
    )

    assert len(result.bundle.rule_pack.route_unlock_rules) >= 2
    assert len({item.beat_id for item in result.bundle.rule_pack.route_unlock_rules}) >= 2


def test_author_bundle_supplements_narrow_route_diversity() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_NarrowRouteDiversityGateway(),
    )

    assert len({item.beat_id for item in result.bundle.rule_pack.route_unlock_rules}) >= 2
    assert len({item.unlock_affordance_tag for item in result.bundle.rule_pack.route_unlock_rules}) >= 2


def test_author_bundle_replaces_low_quality_story_frame_with_default_story_frame() -> None:
    result = run_author_bundle(
        AuthorBundleRequest(
            raw_brief="A civic fantasy about preserving trust during a blackout election."
        ),
        gateway=_LowQualityStoryFrameGateway(),
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
        gateway=_RecoveringStoryFrameGateway(),
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
        gateway=_FallbackBeatPlanGateway(),
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
