from __future__ import annotations

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
) -> list[AuthorPreviewFlashcard]:
    return [
        AuthorPreviewFlashcard(card_id="theme", kind="stable", label="Theme", value=theme_label(theme)),
        AuthorPreviewFlashcard(card_id="tone", kind="stable", label="Tone", value=tone),
        AuthorPreviewFlashcard(card_id="npc_count", kind="stable", label="NPC Count", value=str(expected_npc_count)),
        AuthorPreviewFlashcard(card_id="beat_count", kind="stable", label="Beat Count", value=str(expected_beat_count)),
        AuthorPreviewFlashcard(card_id="cast_topology", kind="stable", label="Cast Structure", value=topology_label(cast_topology)),
        AuthorPreviewFlashcard(card_id="title", kind="draft", label="Working Title", value=title),
        AuthorPreviewFlashcard(card_id="conflict", kind="draft", label="Core Conflict", value=conflict),
    ]


def build_loading_cards(
    *,
    preview: AuthorPreviewResponse,
    progress: AuthorJobProgress,
    token_usage: AuthorCacheMetrics,
    token_cost_estimate: AuthorTokenCostEstimate | None,
) -> list[AuthorLoadingCard]:
    if token_usage.total_tokens is None:
        budget_value = "Waiting for first model call"
    else:
        budget_value = f"{token_usage.total_tokens} total tokens"
        if token_cost_estimate is not None:
            budget_value += f" · RMB {token_cost_estimate.estimated_total_cost_rmb:.6f} est."
    return [
        AuthorLoadingCard(card_id="theme", emphasis="stable", label="Theme", value=theme_label(preview.theme.primary_theme)),
        AuthorLoadingCard(card_id="tone", emphasis="stable", label="Tone", value=preview.story.tone),
        AuthorLoadingCard(
            card_id="structure",
            emphasis="stable",
            label="Story Shape",
            value=topology_label(preview.structure.cast_topology),
        ),
        AuthorLoadingCard(
            card_id="cast_count",
            emphasis="stable",
            label="NPC Count",
            value=cast_count_value(progress.stage, preview.structure.expected_npc_count),
        ),
        AuthorLoadingCard(
            card_id="beat_count",
            emphasis="stable",
            label="Beat Count",
            value=beat_count_value(progress.stage, preview.structure.expected_beat_count),
        ),
        AuthorLoadingCard(
            card_id="working_title",
            emphasis="draft",
            label="Working Title",
            value=preview.story.title,
        ),
        AuthorLoadingCard(
            card_id="core_conflict",
            emphasis="draft",
            label="Core Conflict",
            value=preview.focused_brief.core_conflict,
        ),
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
