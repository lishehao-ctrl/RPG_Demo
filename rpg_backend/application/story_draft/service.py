from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from rpg_backend.application.story_draft.errors import (
    DraftPatchTargetNotFoundError,
    DraftPatchUnsupportedError,
    DraftValidationError,
)
from rpg_backend.application.story_draft.models import DraftPatchChange, OpeningGuidanceView, StoryDraftView
from rpg_backend.domain.opening_guidance import build_opening_guidance_for_pack
from rpg_backend.domain.pack_schema import StoryPack


def normalize_draft_pack(pack_json: dict[str, Any]) -> dict[str, Any]:
    try:
        pack = StoryPack.model_validate(pack_json)
    except ValidationError:
        return deepcopy(pack_json)

    if pack.opening_guidance is not None:
        return deepcopy(pack_json)

    normalized = deepcopy(pack_json)
    normalized["opening_guidance"] = build_opening_guidance_for_pack(pack).model_dump(mode="json")
    return normalized


def resolve_opening_guidance(pack: StoryPack) -> OpeningGuidanceView:
    guidance = pack.opening_guidance or build_opening_guidance_for_pack(pack)
    prompts = list(guidance.starter_prompts)
    while len(prompts) < 3:
        prompts.append("")
    return OpeningGuidanceView(
        intro_text=guidance.intro_text,
        goal_hint=guidance.goal_hint,
        starter_prompts=(prompts[0], prompts[1], prompts[2]),
    )


def build_story_draft_view(*, story: Any, latest_version: Any | None) -> StoryDraftView:
    draft_pack = normalize_draft_pack(story.draft_pack_json)
    return StoryDraftView(
        story_id=story.id,
        title=story.title,
        created_at=story.created_at,
        draft_pack=draft_pack,
        latest_published_version=latest_version.version if latest_version else None,
        latest_published_at=latest_version.created_at if latest_version else None,
    )


def _find_target_entry(*, entries: list[dict[str, Any]], target_id: str, target_type: str) -> dict[str, Any]:
    for entry in entries:
        if str(entry.get("id") or entry.get("name") or "") == target_id:
            return entry
    raise DraftPatchTargetNotFoundError(target_type=target_type, target_id=target_id)


def _apply_change(*, pack_json: dict[str, Any], story_title: str, change: DraftPatchChange) -> tuple[dict[str, Any], str]:
    updated_pack = deepcopy(pack_json)
    updated_title = story_title

    if change.target_type == "story":
        updated_pack[change.field] = change.value
        if change.field == "title":
            updated_title = change.value
        return updated_pack, updated_title

    if change.target_type == "opening_guidance":
        updated_pack = normalize_draft_pack(updated_pack)
        opening_guidance = updated_pack.setdefault("opening_guidance", {})
        if change.field.startswith("starter_prompt_"):
            prompts = list(opening_guidance.get("starter_prompts") or ["", "", ""])
            while len(prompts) < 3:
                prompts.append("")
            prompt_index = int(change.field.rsplit("_", 1)[1]) - 1
            prompts[prompt_index] = change.value
            opening_guidance["starter_prompts"] = prompts[:3]
        else:
            opening_guidance[change.field] = change.value
        return updated_pack, updated_title

    if change.target_type == "beat":
        beat = _find_target_entry(entries=updated_pack.get("beats") or [], target_id=change.target_id or "", target_type="beat")
        beat[change.field] = change.value
        return updated_pack, updated_title

    if change.target_type == "scene":
        scene = _find_target_entry(entries=updated_pack.get("scenes") or [], target_id=change.target_id or "", target_type="scene")
        scene[change.field] = change.value
        return updated_pack, updated_title

    if change.target_type == "npc":
        npc_profile = _find_target_entry(entries=updated_pack.get("npc_profiles") or [], target_id=change.target_id or "", target_type="npc")
        npc_profile[change.field] = change.value
        return updated_pack, updated_title

    raise DraftPatchUnsupportedError(target_type=change.target_type, field=change.field)


def apply_story_draft_changes(
    *,
    pack_json: dict[str, Any],
    story_title: str,
    changes: list[DraftPatchChange],
) -> tuple[dict[str, Any], str]:
    updated_pack = deepcopy(pack_json)
    updated_title = story_title
    for change in changes:
        updated_pack, updated_title = _apply_change(
            pack_json=updated_pack,
            story_title=updated_title,
            change=change,
        )

    try:
        validated_pack = StoryPack.model_validate(updated_pack)
    except ValidationError as exc:
        raise DraftValidationError(errors=exc.errors()) from exc

    return validated_pack.model_dump(mode="json"), updated_title
