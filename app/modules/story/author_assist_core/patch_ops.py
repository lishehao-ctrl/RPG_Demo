from __future__ import annotations

from copy import deepcopy

from .deterministic_tasks import (
    _clean_text,
    _patch,
    _patches_with_unique_ids,
    _scene_list_from_context,
    _slugify,
)
from .seed_normalize import _ensure_scene_option_quality
from .types import ASSIST_ACTION_TYPES, TWO_STAGE_ASSIST_TASKS, AuthorAssistTask

_ASSIST_ACTION_TYPES = ASSIST_ACTION_TYPES
def _sanitize_scenes_graph(scenes: list[dict]) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    out = [deepcopy(item) for item in scenes if isinstance(item, dict)]
    if not out:
        return out, warnings

    keys: list[str] = []
    used: set[str] = set()
    for idx, scene in enumerate(out):
        key = _slugify(scene.get("scene_key") or f"scene_{idx + 1}", fallback=f"scene_{idx + 1}")
        if key in used:
            key = f"{key}_{idx + 1}"
        used.add(key)
        scene["scene_key"] = key
        keys.append(key)

    for idx, scene in enumerate(out):
        is_end = bool(scene.get("is_end", False))
        next_key = keys[idx + 1] if idx + 1 < len(keys) else None
        options = scene.get("options") if isinstance(scene.get("options"), list) else []
        cleaned: list[dict] = []
        for option_idx, option in enumerate(options[:4]):
            if not isinstance(option, dict):
                continue
            label = _clean_text(option.get("label"), fallback=f"Option {option_idx + 1}")
            action_type = _clean_text(option.get("action_type"), fallback="rest").lower()
            if action_type not in _ASSIST_ACTION_TYPES:
                action_type = "rest"
                warnings.append(f"Normalized unsupported action_type in scene '{scene['scene_key']}'.")
            go_to = _clean_text(option.get("go_to"), fallback="")
            if is_end:
                go_to = ""
            elif not go_to or go_to not in used:
                go_to = next_key or keys[-1]
            cleaned.append(
                {
                    "option_key": _clean_text(option.get("option_key"), fallback=f"option_{option_idx + 1}"),
                    "label": label,
                    "intent_aliases": [str(item) for item in (option.get("intent_aliases") or []) if _clean_text(item)],
                    "action_type": action_type,
                    "go_to": go_to or None,
                    "effects": option.get("effects") if isinstance(option.get("effects"), dict) else {},
                    "requirements": option.get("requirements") if isinstance(option.get("requirements"), dict) else {},
                    "is_key_decision": bool(option.get("is_key_decision", False)),
                }
            )
        if not is_end:
            while len(cleaned) < 2:
                cleaned.append(
                    {
                        "option_key": f"autofill_{len(cleaned) + 1}",
                        "label": "Take a recovery step",
                        "intent_aliases": ["recover", "rest", "stabilize"],
                        "action_type": "rest",
                        "go_to": next_key,
                        "effects": {"energy": 10},
                        "requirements": {},
                        "is_key_decision": False,
                    }
                )
                warnings.append(f"Added missing options in scene '{scene['scene_key']}' to keep it playable.")
        scene["options"] = _ensure_scene_option_quality(
            scene_key=scene["scene_key"],
            options=cleaned[:4],
            warnings=warnings,
        )
        scene["is_end"] = is_end
    if not any(bool(scene.get("is_end")) for scene in out):
        out[-1]["is_end"] = True
        warnings.append("Marked final scene as end to avoid dangling play loops.")
    return out, warnings


def _enforce_continue_after_decision_gate(*, scenes: list[dict], context: dict) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    if not scenes:
        return scenes, warnings
    draft_scenes = _scene_list_from_context(context)
    draft_keys = {_clean_text(item.get("scene_key"), fallback="") for item in draft_scenes}
    current_keys = [_clean_text(scene.get("scene_key"), fallback="") for scene in scenes]
    if "decision_gate" not in current_keys:
        return scenes, warnings
    new_keys = [key for key in current_keys if key and key not in draft_keys]
    if not new_keys:
        return scenes, warnings
    new_key = new_keys[0]
    decision_idx = current_keys.index("decision_gate")
    new_idx = current_keys.index(new_key)
    out = [deepcopy(item) for item in scenes]
    if new_idx <= decision_idx:
        moved = out.pop(new_idx)
        decision_idx = current_keys.index("decision_gate")
        out.insert(decision_idx + 1, moved)
        warnings.append("Moved appended follow-up scene to sit immediately after decision_gate.")
    keys = [_clean_text(scene.get("scene_key"), fallback="") for scene in out]
    decision_idx = keys.index("decision_gate")
    if decision_idx + 1 < len(out):
        decision_scene = out[decision_idx]
        decision_scene["is_end"] = False
        next_key = keys[decision_idx + 1]
        options = decision_scene.get("options") if isinstance(decision_scene.get("options"), list) else []
        for option in options:
            if isinstance(option, dict):
                option["go_to"] = next_key
        out[-1]["is_end"] = True
    return out, warnings


def _upsert_patch(patches: list[dict], *, path: str, label: str, value: object) -> None:
    for idx, patch in enumerate(patches):
        if not isinstance(patch, dict):
            continue
        if str(patch.get("path") or "").strip() == path:
            patches[idx] = {
                "id": str(patch.get("id") or _slugify(path, fallback="patch")),
                "path": path,
                "label": label,
                "value": value,
            }
            return
    patches.append(_patch(path, label, value))


def _resolve_scene_keys_from_payload(
    *,
    suggestions: dict,
    patch_preview: list[dict],
    context: dict,
) -> list[str]:
    flow = suggestions.get("flow") if isinstance(suggestions.get("flow"), dict) else {}
    scenes = flow.get("scenes") if isinstance(flow.get("scenes"), list) else []
    if not scenes:
        flow_patch = next(
            (
                item
                for item in patch_preview
                if isinstance(item, dict)
                and str(item.get("path") or "").strip() in {"flow", "flow.scenes"}
            ),
            None,
        )
        if isinstance(flow_patch, dict):
            value = flow_patch.get("value")
            if isinstance(value, dict):
                scenes = value.get("scenes") if isinstance(value.get("scenes"), list) else []
            elif isinstance(value, list):
                scenes = value
    if not scenes:
        draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
        draft_flow = draft.get("flow") if isinstance(draft.get("flow"), dict) else {}
        scenes = draft_flow.get("scenes") if isinstance(draft_flow.get("scenes"), list) else []
    keys: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        key = _clean_text(scene.get("scene_key"), fallback="")
        if key:
            keys.append(key)
    return keys


def _sync_ending_rules_with_flow(
    *,
    task: AuthorAssistTask,
    context: dict,
    suggestions: dict,
    patch_preview: list[dict],
    warnings: list[str],
) -> None:
    scene_keys = _resolve_scene_keys_from_payload(suggestions=suggestions, patch_preview=patch_preview, context=context)
    if not scene_keys:
        return
    target_scene_key = scene_keys[-1]
    ending = suggestions.get("ending") if isinstance(suggestions.get("ending"), dict) else {}
    ending_rules = ending.get("ending_rules") if isinstance(ending.get("ending_rules"), list) else []
    if not ending_rules:
        draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
        draft_ending = draft.get("ending") if isinstance(draft.get("ending"), dict) else {}
        ending_rules = draft_ending.get("ending_rules") if isinstance(draft_ending.get("ending_rules"), list) else []

    normalized_rules: list[dict] = []
    rewired = 0
    for idx, rule in enumerate(ending_rules):
        if not isinstance(rule, dict):
            continue
        normalized = deepcopy(rule)
        trigger = normalized.get("trigger") if isinstance(normalized.get("trigger"), dict) else {}
        scene_ref = _clean_text(trigger.get("scene_key_is"), fallback="")
        if not scene_ref or scene_ref not in scene_keys:
            trigger["scene_key_is"] = target_scene_key
            rewired += 1
        normalized["trigger"] = trigger
        normalized_rules.append(normalized)

    if not normalized_rules:
        normalized_rules = [
            {
                "ending_key": "auto_synced_ending",
                "title": "Auto Synced Ending",
                "priority": 100,
                "outcome": "mixed",
                "trigger": {"scene_key_is": target_scene_key},
                "epilogue": "The run closes on your final committed stance.",
            }
        ]
        warnings.append("Added default ending rule after flow rewrite to keep compile-safe scene references.")
    elif rewired > 0:
        warnings.append(f"Synced {rewired} ending trigger reference(s) to existing flow scene keys.")

    if task in TWO_STAGE_ASSIST_TASKS or rewired > 0:
        _upsert_patch(
            patch_preview,
            path="ending.ending_rules",
            label="Sync ending triggers to valid flow scene keys",
            value=normalized_rules,
        )


def _sanitize_patch_preview(raw_patches: object) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    patches: list[dict] = []
    if not isinstance(raw_patches, list):
        return patches, warnings
    for idx, patch in enumerate(raw_patches):
        if not isinstance(patch, dict):
            warnings.append(f"Skipped non-object patch at index {idx}.")
            continue
        path = _clean_text(patch.get("path"), fallback="")
        label = _clean_text(patch.get("label"), fallback="Patch")
        if not path:
            warnings.append(f"Skipped patch at index {idx} because path is empty.")
            continue
        if "value" not in patch:
            warnings.append(f"Skipped patch '{path}' because value is missing.")
            continue
        patches.append(
            {
                "id": _clean_text(patch.get("id"), fallback=_slugify(path, fallback=f"patch_{idx + 1}")),
                "path": path,
                "label": label,
                "value": patch.get("value"),
            }
        )
    return _patches_with_unique_ids(patches), warnings

