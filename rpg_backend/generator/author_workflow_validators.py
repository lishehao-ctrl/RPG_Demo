from __future__ import annotations

from rpg_backend.domain.constants import (
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
)
from rpg_backend.generator.author_workflow_models import (
    AuthorMemory,
    AuthorMemoryBeatSummary,
    BeatBlueprint,
    BeatDraft,
    BeatLintReport,
    BeatOverviewContext,
    BeatOverviewNPCContext,
    BeatPrefixBeatSummary,
    BeatPrefixSummary,
    StoryOverview,
)


_FIXED_GLOBAL_MOVES = [
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
]

def check_story_overview(overview: StoryOverview) -> list[str]:
    errors: list[str] = []
    if overview.npc_count != len(overview.npc_roster):
        errors.append("overview npc_count must equal npc_roster length")
    names = [npc.name.strip().casefold() for npc in overview.npc_roster]
    if len(set(names)) != len(names):
        errors.append("overview npc_roster names must be unique")
    if len(set(overview.move_bias)) != len(overview.move_bias):
        errors.append("overview move_bias values must be unique")
    if any(not item.strip() for item in overview.scene_constraints):
        errors.append("overview scene_constraints entries must be non-empty")
    return errors


def _trim_sentence(value: str, *, max_length: int) -> str:
    text = " ".join((value or "").strip().split())
    if len(text) <= max_length:
        return text
    clipped = text[: max_length + 1]
    for separator in (". ", "; ", ", "):
        idx = clipped.rfind(separator)
        if idx >= 40:
            return clipped[: idx + 1].strip()
    return text[:max_length].rstrip(" ,;")


def project_overview_for_beat_generation(overview: StoryOverview) -> BeatOverviewContext:
    return BeatOverviewContext(
        title=overview.title,
        premise=overview.premise,
        tone=overview.tone,
        stakes=overview.stakes,
        ending_shape=overview.ending_shape,
        move_bias=list(overview.move_bias),
        npc_roster=[
            BeatOverviewNPCContext(
                name=npc.name,
                role=npc.role,
                red_line=npc.red_line,
                conflict_tags=list(npc.conflict_tags),
            )
            for npc in overview.npc_roster
        ],
        scene_constraints=[_trim_sentence(item, max_length=120) for item in overview.scene_constraints if item.strip()],
    )


def build_structured_prefix_summary(prior_beats: list[BeatDraft]) -> BeatPrefixSummary:
    completed_beats = [BeatPrefixBeatSummary(beat_id=beat.beat_id, title=beat.title) for beat in prior_beats]
    return BeatPrefixSummary(completed_beats=completed_beats)


def build_author_memory(prior_beats: list[BeatDraft]) -> AuthorMemory:
    active_npcs: list[str] = []
    unresolved_threads: list[str] = []
    for beat in prior_beats:
        for npc in beat.present_npcs:
            if npc not in active_npcs:
                active_npcs.append(npc)
        for event in beat.events_produced or [beat.required_event]:
            if event not in unresolved_threads:
                unresolved_threads.append(event)
        if beat.scenes:
            final_scene_seed = _trim_sentence(beat.scenes[-1].scene_seed, max_length=120)
            if final_scene_seed and final_scene_seed not in unresolved_threads:
                unresolved_threads.append(final_scene_seed)

    recent_beats = [
        AuthorMemoryBeatSummary(
            beat_id=beat.beat_id,
            title=beat.title,
            objective=_trim_sentence(beat.objective, max_length=140),
            present_npcs=list(beat.present_npcs),
            events_produced=list(beat.events_produced or [beat.required_event])[:3],
            closing_hook=_trim_sentence(beat.scenes[-1].scene_seed, max_length=120) if beat.scenes else None,
        )
        for beat in prior_beats[-2:]
    ]
    return AuthorMemory(
        beat_count=len(prior_beats),
        active_npcs=active_npcs,
        unresolved_threads=unresolved_threads[:8],
        recent_beats=recent_beats,
    )


def lint_beat_draft(
    *,
    overview: StoryOverview,
    blueprint: BeatBlueprint,
    draft: BeatDraft,
    prior_beats: list[BeatDraft],
) -> BeatLintReport:
    errors: list[str] = []
    if draft.beat_id != blueprint.beat_id:
        errors.append("beat_id does not match blueprint")
    if draft.title.strip() != blueprint.title.strip():
        errors.append("beat title does not match blueprint")
    if draft.objective.strip() != blueprint.objective.strip():
        errors.append("beat objective does not match blueprint")
    if draft.conflict.strip() != blueprint.conflict.strip():
        errors.append("beat conflict does not match blueprint")
    if draft.required_event.strip() != blueprint.required_event.strip():
        errors.append("beat required_event does not match blueprint")
    if draft.entry_scene_id != blueprint.entry_scene_id:
        errors.append("beat entry_scene_id does not match blueprint")

    allowed_npcs = {npc.name for npc in overview.npc_roster}
    if not set(draft.present_npcs).issubset(allowed_npcs):
        errors.append("beat uses NPCs outside overview npc_roster")

    prior_scene_ids = {scene.id for beat in prior_beats for scene in beat.scenes}
    prior_move_ids = {move.id for beat in prior_beats for move in beat.moves}
    if any(scene.id in prior_scene_ids for scene in draft.scenes):
        errors.append("beat scene ids collide with prior beats")
    if any(move.id in prior_move_ids for move in draft.moves):
        errors.append("beat move ids collide with prior beats")
    prior_events = {event for beat in prior_beats for event in (beat.events_produced or [beat.required_event])}
    if draft.required_event in prior_events:
        errors.append("beat required_event collides with prior beats")

    scene_ids = {scene.id for scene in draft.scenes}
    move_ids = {move.id for move in draft.moves}
    if draft.entry_scene_id not in scene_ids:
        errors.append("entry_scene_id not present in beat scenes")

    for scene in draft.scenes:
        if len(scene.enabled_moves) < 3 or len(scene.enabled_moves) > 5:
            errors.append(f"scene '{scene.id}' enabled_moves must contain 3-5 moves")
        if any(move_id not in move_ids for move_id in scene.enabled_moves):
            errors.append(f"scene '{scene.id}' references missing local move ids")
        if list(scene.always_available_moves) != _FIXED_GLOBAL_MOVES:
            errors.append(f"scene '{scene.id}' must use the fixed global always_available_moves")
        if any(npc not in allowed_npcs for npc in scene.present_npcs):
            errors.append(f"scene '{scene.id}' references unknown npc")
        for cond in scene.exit_conditions:
            if cond.next_scene_id and cond.next_scene_id not in scene_ids:
                errors.append(f"scene '{scene.id}' exit points outside current beat")

    for move in draft.moves:
        results = {outcome.result for outcome in move.outcomes}
        if "success" not in results or "fail_forward" not in results:
            errors.append(f"move '{move.id}' must include success and fail_forward outcomes")
        seen_outcomes = [outcome.id for outcome in move.outcomes]
        if len(seen_outcomes) != len(set(seen_outcomes)):
            errors.append(f"move '{move.id}' has duplicate outcome ids")
        for outcome in move.outcomes:
            if outcome.next_scene_id and outcome.next_scene_id not in scene_ids:
                errors.append(f"move '{move.id}' outcome '{outcome.id}' points outside current beat")

    return BeatLintReport(ok=not errors, errors=errors, warnings=[])
