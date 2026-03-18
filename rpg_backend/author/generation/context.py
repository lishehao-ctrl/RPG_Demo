from __future__ import annotations

from typing import Any

from rpg_backend.author.contracts import CastDraft, DesignBundle, StoryFrameDraft


def build_author_context_from_story(
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
) -> dict[str, Any]:
    return {
        "title": story_frame.title,
        "premise": story_frame.premise,
        "tone": story_frame.tone,
        "stakes": story_frame.stakes,
        "style_guard": story_frame.style_guard,
        "world_rules": list(story_frame.world_rules),
        "truths": [{"text": item.text} for item in story_frame.truths],
        "cast": [
            {
                "name": item.name,
                "role": item.role,
                "agenda": item.agenda,
                "pressure_signature": item.pressure_signature,
            }
            for item in cast_draft.cast
        ],
        "axes": [
            {
                "axis_id": item.template_id,
                "label": item.story_label,
                "kind": None,
                "starting_value": item.starting_value,
            }
            for item in story_frame.state_axis_choices
        ],
        "flags": [item.label for item in story_frame.flags],
        "beats": [],
    }


def build_author_context_from_bundle(design_bundle: DesignBundle) -> dict[str, Any]:
    return {
        "title": design_bundle.story_bible.title,
        "premise": design_bundle.story_bible.premise,
        "tone": design_bundle.story_bible.tone,
        "stakes": design_bundle.story_bible.stakes,
        "style_guard": design_bundle.story_bible.style_guard,
        "world_rules": list(design_bundle.story_bible.world_rules),
        "truths": [
            {
                "truth_id": item.truth_id,
                "text": item.text,
            }
            for item in design_bundle.story_bible.truth_catalog
        ],
        "cast": [
            {
                "name": item.name,
                "role": item.role,
                "agenda": item.agenda,
                "pressure_signature": item.pressure_signature,
            }
            for item in design_bundle.story_bible.cast
        ],
        "axes": [
            {
                "axis_id": item.axis_id,
                "label": item.label,
                "kind": item.kind,
                "starting_value": item.starting_value,
            }
            for item in design_bundle.state_schema.axes
        ],
        "flags": [item.flag_id for item in design_bundle.state_schema.flags],
        "beats": [
            {
                "beat_id": item.beat_id,
                "title": item.title,
                "goal": item.goal,
                "focus_names": item.focus_npcs,
                "conflict_names": item.conflict_npcs,
                "pressure_axis_id": item.pressure_axis_id,
                "milestone_kind": item.milestone_kind,
                "route_pivot_tag": item.route_pivot_tag,
                "required_truths": item.required_truths,
                "required_events": item.required_events,
                "affordance_tags": [weight.tag for weight in item.affordances],
            }
            for item in design_bundle.beat_spine
        ],
    }
