from __future__ import annotations

from rpg_backend.author.compiler.beats import (
    compiled_affordance_tags_for_beat,
    event_id_for_beat,
)
from rpg_backend.author.contracts import (
    AffordanceEffectProfile,
    AffordanceWeight,
    AxisTemplateId,
    BeatPlanDraft,
    BeatSpec,
    CastDraft,
    CastMember,
    DesignBundle,
    EndingItem,
    EndingRule,
    FocusedBrief,
    NormalizedSeedPacket,
    OverviewFlagDraft,
    RulePack,
    StateSchema,
    StoryBible,
    StoryFrameDraft,
    TruthItem,
)
from rpg_backend.author.normalize import slugify, trim_ellipsis, unique_preserve
from rpg_backend.author.seed_normalization import relationship_drama_shell_defaults


AXIS_TEMPLATE_CATALOG: dict[str, dict[str, str | int]] = {
    "external_pressure": {"label": "External Pressure", "kind": "pressure", "min_value": 0, "max_value": 5},
    "public_panic": {"label": "Public Panic", "kind": "pressure", "min_value": 0, "max_value": 5},
    "political_leverage": {"label": "Political Leverage", "kind": "relationship", "min_value": 0, "max_value": 5},
    "resource_strain": {"label": "Resource Strain", "kind": "resource", "min_value": 0, "max_value": 5},
    "system_integrity": {"label": "System Integrity", "kind": "pressure", "min_value": 0, "max_value": 5},
    "ally_trust": {"label": "Ally Trust", "kind": "relationship", "min_value": 0, "max_value": 5},
    "exposure_risk": {"label": "Exposure Risk", "kind": "exposure", "min_value": 0, "max_value": 5},
    "time_window": {"label": "Time Window", "kind": "time", "min_value": 0, "max_value": 5},
}

DEFAULT_AXIS_ORDER: tuple[AxisTemplateId, ...] = (
    "external_pressure",
    "public_panic",
    "political_leverage",
)


def _npc_id(name: str) -> str:
    return slugify(name)


def build_design_bundle(
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
    beat_plan_draft: BeatPlanDraft,
    focused_brief: FocusedBrief,
    *,
    normalized_seed: NormalizedSeedPacket | None = None,
) -> DesignBundle:
    cast = [
        CastMember(
            npc_id=_npc_id(item.name),
            name=trim_ellipsis(item.name, 80),
            role=trim_ellipsis(item.role, 120),
            agenda=trim_ellipsis(item.agenda, 220),
            red_line=trim_ellipsis(item.red_line, 220),
            pressure_signature=trim_ellipsis(item.pressure_signature, 220),
        )
        for item in cast_draft.cast
    ]
    truths = [
        TruthItem(
            truth_id=f"truth_{index}",
            text=trim_ellipsis(item.text, 220),
            importance=item.importance,
        )
        for index, item in enumerate(story_frame.truths, start=1)
    ]
    truth_id_by_text = {
        item.text: truth.truth_id
        for item, truth in zip(story_frame.truths, truths, strict=False)
    }
    axis_rows: list[dict[str, object]] = []
    seen_axis_ids: set[str] = set()
    for axis in story_frame.state_axis_choices:
        template = AXIS_TEMPLATE_CATALOG[axis.template_id]
        if axis.template_id in seen_axis_ids:
            continue
        seen_axis_ids.add(axis.template_id)
        axis_rows.append(
            {
                "axis_id": axis.template_id,
                "label": trim_ellipsis(axis.story_label or str(template["label"]), 80),
                "kind": template["kind"],
                "min_value": int(template["min_value"]),
                "max_value": int(template["max_value"]),
                "starting_value": max(0, min(int(template["max_value"]), axis.starting_value)),
            }
        )
    for axis_id in DEFAULT_AXIS_ORDER:
        if axis_id in seen_axis_ids:
            continue
        template = AXIS_TEMPLATE_CATALOG[axis_id]
        axis_rows.append(
            {
                "axis_id": axis_id,
                "label": str(template["label"]),
                "kind": template["kind"],
                "min_value": int(template["min_value"]),
                "max_value": int(template["max_value"]),
                "starting_value": 0 if axis_id != "external_pressure" else 1,
            }
        )
        seen_axis_ids.add(axis_id)
        if len(axis_rows) >= 3:
            break
    state_schema = StateSchema.model_validate(
        {
            "axes": axis_rows[:6],
            "stances": [
                {
                    "stance_id": f"{_npc_id(item.name)}_stance",
                    "npc_id": _npc_id(item.name),
                    "label": f"{trim_ellipsis(item.name, 60)} Stance",
                    "min_value": -2,
                    "max_value": 3,
                    "starting_value": 0,
                }
                for item in cast_draft.cast
            ],
            "flags": [
                {
                    "flag_id": slugify(flag.label),
                    "label": trim_ellipsis(flag.label, 80),
                    "starting_value": bool(flag.starting_value),
                }
                for flag in story_frame.flags
            ],
        }
    )
    bible = StoryBible(
        title=trim_ellipsis(story_frame.title, 120),
        premise=trim_ellipsis(story_frame.premise, 320),
        tone=trim_ellipsis(story_frame.tone, 120),
        stakes=trim_ellipsis(story_frame.stakes, 240),
        style_guard=trim_ellipsis(story_frame.style_guard, 220),
        cast=cast,
        world_rules=[trim_ellipsis(item, 180) for item in story_frame.world_rules],
        truth_catalog=truths,
        ending_catalog=[
            EndingItem(ending_id="mixed", label="Mixed Outcome", summary="The city survives, but trust and stability remain damaged."),
            EndingItem(ending_id="pyrrhic", label="Pyrrhic Outcome", summary="Success arrives only through a steep civic or personal cost."),
            EndingItem(ending_id="collapse", label="Collapse", summary="The crisis outruns coordination and the city pays the price."),
        ],
    )
    cast_names = {item.name for item in cast_draft.cast}
    cast_id_by_name = {item.name: _npc_id(item.name) for item in cast_draft.cast}
    beat_spine: list[BeatSpec] = []
    for index, beat in enumerate(beat_plan_draft.beats, start=1):
        focus_names = unique_preserve(
            [name for name in (*beat.focus_names, *beat.conflict_pair) if name in cast_names]
        )
        focus_npcs = [cast_id_by_name[name] for name in focus_names][:3]
        conflict_npcs = [cast_id_by_name[name] for name in beat.conflict_pair if name in cast_names][:2]
        affordance_tags = compiled_affordance_tags_for_beat(beat)
        event_id = event_id_for_beat(index, beat)
        beat_spine.append(
            BeatSpec(
                beat_id=f"b{index}",
                title=trim_ellipsis(beat.title, 120),
                goal=trim_ellipsis(beat.goal, 220),
                focus_npcs=focus_npcs,
                conflict_npcs=conflict_npcs,
                pressure_axis_id=beat.pressure_axis_id,
                milestone_kind=beat.milestone_kind,
                route_pivot_tag=beat.route_pivot_tag,
                required_truths=[
                    truth_id_by_text[text]
                    for text in beat.required_truth_texts
                    if text in truth_id_by_text
                ][:4],
                required_events=[event_id],
                detour_budget=beat.detour_budget,
                progress_required=beat.progress_required,
                return_hooks=[trim_ellipsis(item, 180) for item in beat.return_hooks[:3]],
                affordances=[
                    AffordanceWeight(tag=tag, weight=1 + (offset == 0))
                    for offset, tag in enumerate(affordance_tags[:6])
                ],
                blocked_affordances=beat.blocked_affordances[:4],
            )
        )
    return DesignBundle(
        focused_brief=focused_brief,
        normalized_seed=normalized_seed,
        story_shell_id=normalized_seed.accepted_shell if normalized_seed is not None and normalized_seed.fit_mode != "out_of_range" else None,
        relationship_hook=normalized_seed.relationship_hook if normalized_seed is not None and normalized_seed.fit_mode != "out_of_range" else None,
        secret_hook=normalized_seed.secret_hook if normalized_seed is not None and normalized_seed.fit_mode != "out_of_range" else None,
        surface_signal_ids=(
            list(relationship_drama_shell_defaults(normalized_seed.accepted_shell).surface_signal_ids)
            if normalized_seed is not None and normalized_seed.fit_mode != "out_of_range"
            else []
        ),
        surface_signal_summary=normalized_seed.surface_signal_summary if normalized_seed is not None and normalized_seed.fit_mode != "out_of_range" else None,
        target_visibility_summary=(
            relationship_drama_shell_defaults(normalized_seed.accepted_shell).target_visibility_summary
            if normalized_seed is not None and normalized_seed.fit_mode != "out_of_range"
            else None
        ),
        route_target_ids=[member.npc_id for member in cast[:5]] if normalized_seed is not None and normalized_seed.fit_mode != "out_of_range" else [],
        story_bible=bible,
        state_schema=state_schema,
        beat_spine=beat_spine,
        rule_pack=RulePack(
            route_unlock_rules=[],
            ending_rules=[EndingRule(ending_id="mixed", priority=100, conditions={})],
            affordance_effect_profiles=[
                AffordanceEffectProfile(
                    affordance_tag="reveal_truth",
                    default_story_function="reveal",
                    axis_deltas={},
                    stance_deltas={},
                    can_add_truth=True,
                    can_add_event=False,
                ),
                AffordanceEffectProfile(
                    affordance_tag="build_trust",
                    default_story_function="advance",
                    axis_deltas={},
                    stance_deltas={},
                    can_add_truth=False,
                    can_add_event=True,
                ),
            ],
        ),
    )
