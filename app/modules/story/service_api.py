from __future__ import annotations

from pydantic import ValidationError

from app.modules.story.schemas import StoryPack
from app.modules.story.validation import validate_story_pack_structural


def validate_story_pack_model(pack: StoryPack) -> list[str]:
    return validate_story_pack_structural(pack)


def story_pack_errors(raw_pack: dict | None) -> list[str]:
    payload = raw_pack if isinstance(raw_pack, dict) else {}
    try:
        pack = StoryPack.model_validate(payload)
    except ValidationError as exc:
        rendered: list[str] = []
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", ()))
            message = str(item.get("msg") or "validation error")
            rendered.append(f"SCHEMA:{location}:{message}")
        return sorted(set(rendered))
    return validate_story_pack_model(pack)
