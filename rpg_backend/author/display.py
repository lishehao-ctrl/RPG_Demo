from __future__ import annotations

from rpg_backend.author.normalize import trim_ellipsis
from rpg_backend.author.contracts import (
    AuthorCacheMetrics,
    AuthorJobProgress,
    AuthorJobProgressSnapshot,
    AuthorLoadingCard,
    AuthorPreviewFlashcard,
    AuthorPreviewResponse,
    AuthorTokenCostEstimate,
)

THEME_LABELS = {
    "legitimacy_crisis": "Legitimacy crisis",
    "logistics_quarantine_crisis": "Logistics quarantine crisis",
    "truth_record_crisis": "Truth and record crisis",
    "public_order_crisis": "Public order crisis",
    "generic_civic_crisis": "Civic crisis",
}

TOPOLOGY_LABELS = {
    "three_slot": "3-slot pressure triangle",
    "four_slot": "4-slot civic web",
}

STAGE_LABELS = {
    "queued": "Queued for generation",
    "running": "Starting generation",
    "brief_parsed": "Brief parsed",
    "brief_classified": "Theme classified",
    "story_frame_ready": "Story frame drafted",
    "theme_confirmed": "Theme confirmed",
    "cast_planned": "Cast topology planned",
    "cast_ready": "Cast roster drafted",
    "beat_plan_ready": "Beat plan drafted",
    "route_ready": "Route rules compiled",
    "ending_ready": "Ending rules drafted",
    "completed": "Bundle complete",
    "failed": "Generation failed",
}

STAGE_STATUS_MESSAGES = {
    "queued": "Queued. Preparing generation graph.",
    "running": "Starting generation.",
    "brief_parsed": "Brief parsed. Distilling the story kernel.",
    "brief_classified": "Theme classified. Locking the story route.",
    "story_frame_ready": "Story frame drafted. Title, premise, and stakes are set.",
    "theme_confirmed": "Theme confirmed. Strategy is locked.",
    "cast_planned": "Cast topology planned. Defining the pressure web.",
    "cast_ready": "Cast roster drafted. NPC tensions are in place.",
    "beat_plan_ready": "Beat plan drafted. Main progression is mapped.",
    "route_ready": "Route rules compiled. Unlock paths are wired.",
    "ending_ready": "Ending rules drafted. Outcome logic is set.",
    "completed": "Bundle complete. Story package is ready.",
    "failed": "Generation failed. Retry or inspect the error.",
}

_CAST_READY_STAGES = {
    "cast_ready",
    "beat_plan_ready",
    "route_ready",
    "ending_ready",
    "completed",
}

_BEAT_READY_STAGES = {
    "beat_plan_ready",
    "route_ready",
    "ending_ready",
    "completed",
}

_STORY_FRAME_READY_STAGES = {
    "story_frame_ready",
    "theme_confirmed",
    "cast_planned",
    "cast_ready",
    "beat_plan_ready",
    "route_ready",
    "ending_ready",
    "completed",
}


def humanize_identifier(value: str) -> str:
    return value.replace("_", " ").strip().title()


def theme_label(theme: str) -> str:
    return THEME_LABELS.get(theme, humanize_identifier(theme))


def topology_label(topology: str) -> str:
    return TOPOLOGY_LABELS.get(topology, humanize_identifier(topology))


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, humanize_identifier(stage))


def stage_status_message(stage: str) -> str:
    return STAGE_STATUS_MESSAGES.get(stage, stage_label(stage))


def cast_count_value(stage: str, expected_npc_count: int) -> str:
    status = "NPCs drafted" if stage in _CAST_READY_STAGES else "planned NPCs"
    return f"{expected_npc_count} {status}"


def beat_count_value(stage: str, expected_beat_count: int) -> str:
    status = "beats drafted" if stage in _BEAT_READY_STAGES else "planned beats"
    return f"{expected_beat_count} {status}"


def build_preview_flashcards(
    *,
    theme: str,
    tone: str,
    cast_topology: str,
    expected_npc_count: int,
    expected_beat_count: int,
    title: str,
    conflict: str,
    route_fantasy: str | None = None,
    relationship_hook: str | None = None,
    secret_hook: str | None = None,
    surface_signal_summary: str | None = None,
    target_visibility_summary: str | None = None,
) -> list[AuthorPreviewFlashcard]:
    cards = [
        AuthorPreviewFlashcard(card_id="theme", kind="stable", label="故事外壳", value=theme_label(theme)),
        AuthorPreviewFlashcard(card_id="tone", kind="stable", label="整体气质", value=tone),
        AuthorPreviewFlashcard(card_id="npc_count", kind="stable", label="关键对象", value=str(expected_npc_count)),
        AuthorPreviewFlashcard(card_id="beat_count", kind="stable", label="剧情阶段", value=str(expected_beat_count)),
        AuthorPreviewFlashcard(card_id="cast_topology", kind="stable", label="关系结构", value=topology_label(cast_topology)),
        AuthorPreviewFlashcard(card_id="title", kind="draft", label="作品标题", value=title),
    ]
    if route_fantasy:
        cards.append(AuthorPreviewFlashcard(card_id="route_fantasy", kind="draft", label="路线幻想", value=trim_ellipsis(route_fantasy, 220)))
    if relationship_hook:
        cards.append(AuthorPreviewFlashcard(card_id="relationship_hook", kind="draft", label="关系钩子", value=trim_ellipsis(relationship_hook, 220)))
    if secret_hook:
        cards.append(AuthorPreviewFlashcard(card_id="secret_hook", kind="draft", label="秘密钩子", value=trim_ellipsis(secret_hook, 220)))
    if surface_signal_summary:
        cards.append(AuthorPreviewFlashcard(card_id="surface_signal_summary", kind="stable", label="表层压力", value=trim_ellipsis(surface_signal_summary, 220)))
    if target_visibility_summary:
        cards.append(AuthorPreviewFlashcard(card_id="target_visibility_summary", kind="stable", label="目标亮相", value=trim_ellipsis(target_visibility_summary, 220)))
    cards.append(AuthorPreviewFlashcard(card_id="conflict", kind="draft", label="当前局势", value=trim_ellipsis(conflict, 220)))
    return cards[:16]


def build_loading_cards(
    *,
    preview: AuthorPreviewResponse,
    progress: AuthorJobProgress,
    token_usage: AuthorCacheMetrics,
    token_cost_estimate: AuthorTokenCostEstimate | None,
) -> list[AuthorLoadingCard]:
    cards: list[AuthorLoadingCard] = [
        AuthorLoadingCard(card_id="theme", emphasis="stable", label="Theme", value=theme_label(preview.theme.primary_theme)),
        AuthorLoadingCard(
            card_id="structure",
            emphasis="stable",
            label="Story Shape",
            value=topology_label(preview.structure.cast_topology),
        ),
    ]
    if token_usage.total_tokens is None:
        budget_value = "Waiting for first model call"
    else:
        budget_value = f"{token_usage.total_tokens} total tokens"
        if token_cost_estimate is not None:
            from rpg_backend.config import get_settings

            usd_cost = token_cost_estimate.estimated_total_cost_rmb * get_settings().responses_usd_per_rmb
            budget_value += f" · USD {usd_cost:.6f} est."
    if progress.stage in _STORY_FRAME_READY_STAGES:
        cards.extend(
            [
                AuthorLoadingCard(
                    card_id="working_title",
                    emphasis="draft",
                    label="Working Title",
                    value=preview.story.title,
                ),
                AuthorLoadingCard(
                    card_id="tone",
                    emphasis="stable",
                    label="Tone",
                    value=preview.story.tone,
                ),
                AuthorLoadingCard(
                    card_id="story_premise",
                    emphasis="draft",
                    label="Story Premise",
                    value=trim_ellipsis(preview.story.premise, 220),
                ),
                AuthorLoadingCard(
                    card_id="story_stakes",
                    emphasis="draft",
                    label="Story Stakes",
                    value=trim_ellipsis(preview.story.stakes, 220),
                ),
            ]
        )
    if progress.stage in _CAST_READY_STAGES:
        anchor = preview.cast_slots[0] if preview.cast_slots else None
        cards.extend(
            [
                AuthorLoadingCard(
                    card_id="cast_count",
                    emphasis="stable",
                    label="NPC Count",
                    value=cast_count_value(progress.stage, preview.structure.expected_npc_count),
                ),
                AuthorLoadingCard(
                    card_id="cast_anchor",
                    emphasis="draft",
                    label="Cast Anchor",
                    value=trim_ellipsis(
                        (
                            f"{anchor.slot_label} · {anchor.public_role}"
                            if anchor is not None
                            else "Awaiting cast release"
                        ),
                        220,
                    ),
                ),
            ]
        )
    if progress.stage in _BEAT_READY_STAGES:
        opening_beat = preview.beats[0] if preview.beats else None
        final_beat = preview.beats[-1] if preview.beats else None
        cards.extend(
            [
                AuthorLoadingCard(
                    card_id="beat_count",
                    emphasis="stable",
                    label="Beat Count",
                    value=beat_count_value(progress.stage, preview.structure.expected_beat_count),
                ),
                AuthorLoadingCard(
                    card_id="opening_beat",
                    emphasis="draft",
                    label="Opening Beat",
                    value=trim_ellipsis(
                        (
                            f"{opening_beat.title}: {opening_beat.goal}"
                            if opening_beat is not None
                            else "Awaiting beat release"
                        ),
                        220,
                    ),
                ),
                AuthorLoadingCard(
                    card_id="final_beat",
                    emphasis="draft",
                    label="Final Beat",
                    value=trim_ellipsis(
                        (
                            f"{final_beat.title}: {final_beat.goal}"
                            if final_beat is not None
                            else "Awaiting beat release"
                        ),
                        220,
                    ),
                ),
            ]
        )
    cards.extend(
        [
            AuthorLoadingCard(
                card_id="generation_status",
                emphasis="live",
                label="Generation Status",
                value=stage_status_message(progress.stage),
            ),
            AuthorLoadingCard(
                card_id="token_budget",
                emphasis="live",
                label="Token Budget",
                value=budget_value,
            ),
        ]
    )
    return cards


def build_progress_snapshot(
    *,
    preview: AuthorPreviewResponse,
    progress: AuthorJobProgress,
    token_usage: AuthorCacheMetrics,
    token_cost_estimate: AuthorTokenCostEstimate | None,
) -> AuthorJobProgressSnapshot:
    completion_ratio = 0.0
    if progress.stage_total > 0:
        completion_ratio = min(progress.stage_index / progress.stage_total, 1.0)
    return AuthorJobProgressSnapshot(
        stage=progress.stage,
        stage_label=stage_label(progress.stage),
        stage_index=progress.stage_index,
        stage_total=progress.stage_total,
        completion_ratio=round(completion_ratio, 3),
        primary_theme=preview.theme.primary_theme,
        cast_topology=preview.structure.cast_topology,
        expected_npc_count=preview.structure.expected_npc_count,
        expected_beat_count=preview.structure.expected_beat_count,
        preview_title=preview.story.title,
        preview_premise=preview.story.premise,
        flashcards=list(preview.flashcards),
        loading_cards=build_loading_cards(
            preview=preview,
            progress=progress,
            token_usage=token_usage,
            token_cost_estimate=token_cost_estimate,
        ),
    )
