from __future__ import annotations

from typing import Iterable

from rpg_backend.author.contracts import (
    AuthorPreviewBeatSummary,
    AuthorPreviewCastSlotSummary,
    AuthorPreviewResponse,
    AuthorPreviewStory,
    AuthorPreviewStrategies,
    AuthorPreviewStructure,
    AuthorPreviewTheme,
    AuthorStorySummary,
    FocusedBrief,
)
from rpg_backend.author.display import build_preview_flashcards, humanize_identifier
from rpg_backend.author.normalize import trim_ellipsis
from rpg_backend.author_v2.contracts import (
    AcceptedBlueprint,
    ArcTemplateId,
    BoundIPCastMember,
    CompiledPlayPlan,
    SegmentRoleId,
    UrbanPreviewBlueprint,
)
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.play.contracts import PlayEnding, PlayProtagonist

_DEFAULT_TONE = "都市情感悬疑"
_EXPECTED_BEATS_BY_TEMPLATE: dict[ArcTemplateId, int] = {
    "short_3": 3,
    "compact_4": 4,
    "standard_4": 4,
    "long_5": 5,
    "flagship_6": 6,
    "super_flagship_8": 8,
}
_ROLE_TITLES: dict[SegmentRoleId, str] = {
    "opening": "Opening",
    "misread": "Misread",
    "pressure": "Pressure",
    "reversal": "Reversal",
    "reveal": "Reveal",
    "terminal": "Terminal",
}
_PUBLIC_ENDING_FAMILY: dict[str, tuple[str, str, str]] = {
    "route_lock": ("route_lock", "路线锁定", "你和目标之间的关系已经越过了无法退回的界线。"),
    "bittersweet": ("bittersweet", "苦涩成局", "你拿到了想要的结果，但代价已经无法再隐藏。"),
    "breakdown": ("breakdown", "关系翻车", "局面和关系同时失控，谁都没能体面退场。"),
    "open_loop": ("open_loop", "悬而未决", "局势没有真正结束，只是暂时停在了更危险的边缘。"),
}


def _shell_theme(story_shell_id: str) -> str:
    return humanize_identifier(story_shell_id)


def _focused_brief(blueprint: UrbanPreviewBlueprint) -> FocusedBrief:
    return FocusedBrief(
        story_kernel=trim_ellipsis(blueprint.hook, 220),
        setting_signal=trim_ellipsis(blueprint.social_arena, 220),
        core_conflict=trim_ellipsis(blueprint.route_promise, 220),
        tone_signal=_DEFAULT_TONE,
        hard_constraints=[],
        forbidden_tones=["graphic cruelty", "sadistic evil"],
    )


def _cast_topology(cast_count: int) -> str:
    if cast_count <= 3:
        return "triangle"
    if cast_count == 4:
        return "quartet"
    if cast_count == 5:
        return "ensemble_5"
    if cast_count == 6:
        return "ensemble_6"
    return "ensemble_7"


def _preview_story(blueprint: UrbanPreviewBlueprint) -> AuthorPreviewStory:
    return AuthorPreviewStory(
        title=trim_ellipsis(f"{blueprint.social_arena}关系局", 120),
        premise=trim_ellipsis(blueprint.hook, 320),
        tone=_DEFAULT_TONE,
        stakes=trim_ellipsis(blueprint.cost_of_truth, 240),
        route_fantasy=trim_ellipsis(blueprint.route_promise, 240),
    )


def _preview_cast_slots(blueprint: UrbanPreviewBlueprint) -> list[AuthorPreviewCastSlotSummary]:
    route_slots = [
        AuthorPreviewCastSlotSummary(slot_label=f"Route Target {index + 1}", public_role="关键关系对象")
        for index in range(blueprint.route_target_count)
    ]
    support_slots = [
        AuthorPreviewCastSlotSummary(slot_label="Secret Keeper", public_role="秘密持有者"),
        AuthorPreviewCastSlotSummary(slot_label="Pressure Witness", public_role="关系局压力源"),
    ]
    slots = [*route_slots, *support_slots]
    return slots[: blueprint.cast_count_target]


def _preview_beats(blueprint: UrbanPreviewBlueprint) -> list[AuthorPreviewBeatSummary]:
    template = {
        "5_8": ("opening", "reveal", "terminal"),
        "10_12": ("opening", "misread", "reveal", "terminal"),
        "12_15": ("opening", "misread", "reveal", "terminal"),
        "15_20": ("opening", "misread", "pressure", "reveal", "terminal"),
        "20_25": ("opening", "misread", "pressure", "reversal", "reveal", "terminal"),
        "30_45": ("opening", "misread", "pressure", "reversal", "pressure", "reversal", "reveal", "terminal"),
    }[blueprint.play_length_preset]
    goals = {
        "opening": blueprint.hook,
        "misread": blueprint.relationship_setup,
        "pressure": blueprint.route_promise,
        "reversal": blueprint.taboo_secret,
        "reveal": blueprint.bomb_moment,
        "terminal": blueprint.cost_of_truth,
    }
    return [
        AuthorPreviewBeatSummary(
            title=_ROLE_TITLES[role].replace("_", " "),
            goal=trim_ellipsis(goals[role], 220),
            milestone_kind=role,
        )
        for role in template
    ]


def author_preview_from_blueprint(
    blueprint: UrbanPreviewBlueprint,
    *,
    bound_cast: Iterable[BoundIPCastMember] | None = None,
    arc_template_id: ArcTemplateId | None = None,
) -> AuthorPreviewResponse:
    cast_members = list(bound_cast or [])
    cast_slots = (
        [
            AuthorPreviewCastSlotSummary(
                slot_label=member.display_name,
                public_role=member.public_role,
            )
            for member in cast_members
        ][:7]
        or _preview_cast_slots(blueprint)
    )
    preview_story = _preview_story(blueprint)
    expected_beat_count = _EXPECTED_BEATS_BY_TEMPLATE.get(
        arc_template_id or {
            "5_8": "short_3",
            "10_12": "compact_4",
            "12_15": "standard_4",
            "15_20": "long_5",
            "20_25": "flagship_6",
            "30_45": "super_flagship_8",
        }[blueprint.play_length_preset],
        4,
    )
    return AuthorPreviewResponse(
        preview_id=blueprint.preview_id,
        prompt_seed=blueprint.prompt_seed,
        play_length_preset=blueprint.play_length_preset,
        normalized_seed=None,
        story_shell_id=blueprint.story_shell_id,
        relationship_hook=trim_ellipsis(blueprint.relationship_setup, 320),
        secret_hook=trim_ellipsis(blueprint.taboo_secret, 320),
        surface_signal_ids=[blueprint.worldly_desire_type, blueprint.play_length_preset],
        surface_signal_summary=trim_ellipsis(blueprint.social_arena, 320),
        target_visibility_summary=trim_ellipsis(blueprint.share_hook, 320),
        focused_brief=_focused_brief(blueprint),
        theme=AuthorPreviewTheme(
            primary_theme=blueprint.story_shell_id,
            modifiers=[blueprint.worldly_desire_type, blueprint.experience_band, blueprint.play_length_preset],
            router_reason="author_v2_blueprint",
        ),
        strategies=AuthorPreviewStrategies(
            story_frame_strategy="author_v2_preview",
            cast_strategy="author_v2_cast_compile",
            beat_plan_strategy="author_v2_segment_compile",
        ),
        structure=AuthorPreviewStructure(
            cast_topology=_cast_topology(blueprint.cast_count_target),
            expected_npc_count=blueprint.cast_count_target,
            expected_beat_count=expected_beat_count,
        ),
        story=preview_story,
        cast_slots=cast_slots,
        beats=_preview_beats(blueprint),
        flashcards=build_preview_flashcards(
            theme=blueprint.story_shell_id,
            tone=_DEFAULT_TONE,
            cast_topology=_cast_topology(blueprint.cast_count_target),
            expected_npc_count=blueprint.cast_count_target,
            expected_beat_count=expected_beat_count,
            title=preview_story.title,
            conflict=blueprint.route_promise,
            route_fantasy=blueprint.route_promise,
            relationship_hook=blueprint.relationship_setup,
            secret_hook=blueprint.taboo_secret,
            surface_signal_summary=blueprint.social_arena,
            target_visibility_summary=blueprint.share_hook,
        ),
        stage="theme_confirmed",
    )


def author_story_summary_from_package(package: RelationshipDramaV2Package) -> AuthorStorySummary:
    plan = package.compiled_play_plan
    return AuthorStorySummary(
        title=plan.title,
        one_liner=trim_ellipsis(package.accepted_blueprint.hook, 220),
        premise=trim_ellipsis(
            f"{package.accepted_blueprint.social_arena}里，{package.accepted_blueprint.route_promise}",
            320,
        ),
        tone=_DEFAULT_TONE,
        theme=_shell_theme(plan.story_shell_id),
        npc_count=len(plan.cast),
        beat_count=len(plan.segments),
    )


def package_from_pipeline(
    *,
    preview_blueprint: UrbanPreviewBlueprint,
    accepted_blueprint: AcceptedBlueprint,
    pipeline,
) -> RelationshipDramaV2Package:  # noqa: ANN001
    return RelationshipDramaV2Package(
        preview_blueprint=preview_blueprint,
        accepted_blueprint=accepted_blueprint,
        urban_bundle=pipeline.bundle,
        compiled_play_plan=pipeline.play_plan,
        quality_trace=list(pipeline.state.get("quality_trace") or []),
        llm_call_trace=list(pipeline.state.get("llm_call_trace") or []),
    )


def play_overview_from_package(package: RelationshipDramaV2Package) -> tuple[PlayProtagonist, str, str, str, int]:
    plan = package.compiled_play_plan
    protagonist = product_protagonist_from_plan(plan)
    return protagonist, plan.opening_narration, "relationship_drama_v2", "Relationship Drama V2", plan.max_turns


def product_protagonist_from_plan(plan: CompiledPlayPlan) -> PlayProtagonist:
    return PlayProtagonist(
        title=plan.protagonist_public_identity,
        mandate=trim_ellipsis(
            f"在{plan.social_arena}里决定你该信谁、护谁、逼谁，并承担{plan.cost_of_truth}",
            220,
        ),
        identity_summary=trim_ellipsis(
            f"你是{plan.protagonist_public_identity}。你真正想要的是{plan.protagonist_hidden_need}。",
            320,
        ),
        core_desire=trim_ellipsis(plan.route_promise, 220),
        hidden_risk=trim_ellipsis(plan.cost_of_truth, 220),
    )


def public_ending_from_v2(ending_id: str | None, summary: str | None) -> PlayEnding | None:
    if not ending_id:
        return None
    if ending_id.startswith("relationship_"):
        public_id = "route_lock"
    elif ending_id.startswith("side_") or ending_id == "pyrrhic_control":
        public_id = "bittersweet"
    elif ending_id == "burst_reckoning" or ending_id == "burned_alone":
        public_id = "breakdown"
    else:
        public_id = "open_loop"
    mapped_id, label, fallback_summary = _PUBLIC_ENDING_FAMILY[public_id]
    return PlayEnding(
        ending_id=mapped_id,
        label=label,
        summary=trim_ellipsis(summary or fallback_summary, 220),
    )
