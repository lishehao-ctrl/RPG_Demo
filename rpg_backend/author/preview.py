from __future__ import annotations

from uuid import uuid4

from rpg_backend.author.compiler.beats import build_default_beat_plan_draft
from rpg_backend.author.compiler.brief import focus_brief
from rpg_backend.author.compiler.cast import build_cast_draft_from_overview, derive_cast_overview_draft, plan_cast_topology
from rpg_backend.author.compiler.router import plan_brief_theme, plan_story_theme
from rpg_backend.author.compiler.story import build_default_story_frame_draft
from rpg_backend.author.contracts import (
    AuthorBundleRequest,
    AuthorJobCreateRequest,
    AuthorPreviewBeatSummary,
    AuthorPreviewCastSlotSummary,
    AuthorPreviewRequest,
    AuthorPreviewResponse,
    AuthorPreviewStory,
    AuthorPreviewStrategies,
    AuthorPreviewStructure,
    AuthorPreviewTheme,
    AuthorStorySummary,
    DesignBundle,
    FocusedBrief,
)
from rpg_backend.author.display import build_preview_flashcards, theme_label


def build_author_preview_from_seed(prompt_seed: str) -> AuthorPreviewResponse:
    focused_brief = focus_brief(prompt_seed)
    brief_theme = plan_brief_theme(focused_brief)
    preview_story = build_default_story_frame_draft(focused_brief)
    story_theme = plan_story_theme(focused_brief, preview_story)
    topology = plan_cast_topology(focused_brief, preview_story)
    cast_overview = derive_cast_overview_draft(focused_brief, preview_story)
    cast_draft = build_cast_draft_from_overview(cast_overview, focused_brief)
    beat_plan = build_default_beat_plan_draft(
        focused_brief,
        story_frame=preview_story,
        cast_draft=cast_draft,
    )
    expected_npc_count = len(cast_overview.cast_slots)
    expected_beat_count = len(beat_plan.beats)
    return AuthorPreviewResponse(
        preview_id=str(uuid4()),
        prompt_seed=prompt_seed,
        focused_brief=focused_brief,
        theme=AuthorPreviewTheme(
            primary_theme=story_theme.primary_theme,
            modifiers=list(story_theme.modifiers),
            router_reason=story_theme.router_reason,
        ),
        strategies=AuthorPreviewStrategies(
            story_frame_strategy=brief_theme.story_frame_strategy,
            cast_strategy=story_theme.cast_strategy,
            beat_plan_strategy=story_theme.beat_plan_strategy,
        ),
        structure=AuthorPreviewStructure(
            cast_topology=topology.topology,
            expected_npc_count=expected_npc_count,
            expected_beat_count=expected_beat_count,
        ),
        story=AuthorPreviewStory(
            title=preview_story.title,
            premise=preview_story.premise,
            tone=preview_story.tone,
            stakes=preview_story.stakes,
        ),
        cast_slots=[
            AuthorPreviewCastSlotSummary(
                slot_label=item.slot_label,
                public_role=item.public_role,
            )
            for item in cast_overview.cast_slots
        ],
        beats=[
            AuthorPreviewBeatSummary(
                title=item.title,
                goal=item.goal,
                milestone_kind=item.milestone_kind,
            )
            for item in beat_plan.beats
        ],
        flashcards=build_preview_flashcards(
            theme=story_theme.primary_theme,
            tone=preview_story.tone,
            cast_topology=topology.topology,
            expected_npc_count=expected_npc_count,
            expected_beat_count=expected_beat_count,
            title=preview_story.title,
            conflict=focused_brief.core_conflict,
        ),
        stage="brief_parsed",
    )


def build_author_preview_from_request(request: AuthorPreviewRequest | AuthorJobCreateRequest) -> AuthorPreviewResponse:
    return build_author_preview_from_seed(request.prompt_seed)


def build_generation_state_from_preview(preview: AuthorPreviewResponse) -> dict[str, object]:
    return {
        "focused_brief": preview.focused_brief,
        "brief_primary_theme": preview.theme.primary_theme,
        "brief_theme_modifiers": list(preview.theme.modifiers),
        "brief_theme_router_reason": f"preview_locked:{preview.theme.router_reason}",
        "story_frame_strategy": preview.strategies.story_frame_strategy,
        "cast_strategy": preview.strategies.cast_strategy,
        "primary_theme": preview.theme.primary_theme,
        "theme_modifiers": list(preview.theme.modifiers),
        "theme_router_reason": f"preview_locked:{preview.theme.router_reason}",
        "beat_plan_strategy": preview.strategies.beat_plan_strategy,
        "cast_topology": preview.structure.cast_topology,
        "cast_topology_reason": "preview_locked_cast_topology",
    }


def build_author_story_summary(bundle: DesignBundle, *, primary_theme: str) -> AuthorStorySummary:
    one_liner = bundle.story_bible.premise.split(".")[0].strip()
    if not one_liner:
        one_liner = bundle.story_bible.title
    return AuthorStorySummary(
        title=bundle.story_bible.title,
        one_liner=one_liner,
        premise=bundle.story_bible.premise,
        tone=bundle.story_bible.tone,
        theme=theme_label(primary_theme),
        npc_count=len(bundle.story_bible.cast),
        beat_count=len(bundle.beat_spine),
    )


def author_bundle_request_from_seed(prompt_seed: str) -> AuthorBundleRequest:
    return AuthorBundleRequest(raw_brief=prompt_seed)
