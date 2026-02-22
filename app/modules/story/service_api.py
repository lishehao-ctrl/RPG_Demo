from __future__ import annotations

from pydantic import ValidationError

from app.modules.story.authoring import compile_author_story_payload
from app.modules.story.playability import analyze_story_playability
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


def _friendly_story_error(error_text: str) -> dict[str, str | None]:
    text = str(error_text or "").strip()
    if text.startswith("SCHEMA:"):
        _, location, *rest = text.split(":")
        message = ":".join(rest).strip() if rest else "Schema validation failed."
        return {
            "code": "RUNTIME_SCHEMA_ERROR",
            "path": location or None,
            "message": message,
            "suggestion": "Check this field in the author form or compiled preview.",
        }
    if text.startswith("DANGLING_NEXT_NODE:"):
        return {
            "code": "RUNTIME_DANGLING_NEXT_NODE",
            "path": None,
            "message": text,
            "suggestion": "Ensure every option go_to references an existing scene.",
        }
    if text.startswith("MISSING_START_NODE:"):
        return {
            "code": "RUNTIME_MISSING_START_NODE",
            "path": "flow.start_scene_key",
            "message": text,
            "suggestion": "Set flow.start_scene_key to an existing scene.",
        }
    if text.startswith("DUPLICATE_CHOICE_ID:"):
        return {
            "code": "RUNTIME_DUPLICATE_CHOICE_ID",
            "path": None,
            "message": text,
            "suggestion": "Use unique option keys per scene and avoid duplicate generated ids.",
        }
    if text.startswith("INVALID_VISIBLE_CHOICE_COUNT:"):
        return {
            "code": "RUNTIME_INVALID_VISIBLE_CHOICE_COUNT",
            "path": "flow.scenes.options",
            "message": text,
            "suggestion": "Non-end scenes must have 2-4 options.",
        }
    if text.startswith("DANGLING_QUEST_TRIGGER_EXECUTED_CHOICE:"):
        return {
            "code": "RUNTIME_DANGLING_QUEST_TRIGGER_OPTION",
            "path": "progress",
            "message": text,
            "suggestion": "Use valid option_key references in milestone triggers.",
        }
    if text.startswith("DANGLING_QUEST_TRIGGER_NODE:") or text.startswith("DANGLING_QUEST_TRIGGER_NEXT_NODE:"):
        return {
            "code": "RUNTIME_DANGLING_QUEST_TRIGGER_SCENE",
            "path": "progress",
            "message": text,
            "suggestion": "Use valid scene_key references in milestone triggers.",
        }
    return {
        "code": "RUNTIME_STRUCTURAL_ERROR",
        "path": None,
        "message": text,
        "suggestion": "Review the compiled preview and fix the referenced section.",
    }


def _dedupe_author_diagnostics(items: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for item in items:
        code = str(item.get("code") or "")
        path = str(item.get("path") or "")
        message = str(item.get("message") or "")
        key = f"{code}|{path}|{message}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _playability_policy_from_payload(payload: dict) -> dict | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("playability_policy")
    return raw if isinstance(raw, dict) else None


def compile_author_payload_with_runtime_checks(
    payload: dict,
) -> tuple[dict | None, list[dict], list[dict], dict, dict]:
    result = compile_author_story_payload(payload)
    errors = list(result.errors or [])
    warnings = list(result.warnings or [])
    compiled_pack = result.pack if isinstance(result.pack, dict) else None
    playability = {
        "pass": False,
        "blocking_errors": [],
        "warnings": [],
        "metrics": {
            "ending_reach_rate": 0.0,
            "stuck_turn_rate": 0.0,
            "no_progress_rate": 0.0,
            "branch_coverage": 0.0,
        },
    }
    if compiled_pack is not None:
        runtime_errors = story_pack_errors(compiled_pack)
        errors.extend(_friendly_story_error(item) for item in runtime_errors)
        playability = analyze_story_playability(
            pack=compiled_pack,
            playability_policy=_playability_policy_from_payload(payload),
        )
        errors.extend(playability.get("blocking_errors") or [])
        warnings.extend(playability.get("warnings") or [])
    return (
        compiled_pack,
        _dedupe_author_diagnostics(errors),
        _dedupe_author_diagnostics(warnings),
        dict(result.mappings or {}),
        playability,
    )
