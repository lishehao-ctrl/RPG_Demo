from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from rpg_backend.domain.opening_guidance import build_opening_guidance_for_pack
from rpg_backend.domain.pack_schema import StoryPack


def normalize_story_pack_payload(pack_json: dict[str, Any]) -> dict[str, Any]:
    pack = StoryPack.model_validate(pack_json)
    if pack.opening_guidance is None:
        pack = pack.model_copy(update={"opening_guidance": build_opening_guidance_for_pack(pack)})
    return pack.model_dump(mode="json")


def try_normalize_story_pack_payload(pack_json: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    try:
        return normalize_story_pack_payload(pack_json), []
    except ValidationError as exc:
        return deepcopy(pack_json), [str(exc)]
