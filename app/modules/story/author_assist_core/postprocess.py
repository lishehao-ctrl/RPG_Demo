from __future__ import annotations

from copy import deepcopy

from .deterministic_tasks import _patches_with_unique_ids
from .errors import AuthorAssistInvalidOutputError
from .patch_ops import (
    _enforce_continue_after_decision_gate,
    _sanitize_patch_preview,
    _sanitize_scenes_graph,
    _sync_ending_rules_with_flow,
    _upsert_patch,
)
from .seed_normalize import _normalize_seed_expand_suggestions
from .types import ASSIST_MAX_SCENES, ENDING_SYNC_ASSIST_TASKS, TWO_STAGE_ASSIST_TASKS, AuthorAssistTask

_ASSIST_MAX_SCENES = ASSIST_MAX_SCENES
_NPC_MIN_COUNT = 3
_NPC_MAX_COUNT = 6


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_npc_list(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        role = _clean_text(item.get("role"))
        traits_raw = item.get("traits") if isinstance(item.get("traits"), list) else []
        traits = [_clean_text(value) for value in traits_raw if _clean_text(value)]
        out.append(
            {
                "name": name,
                "role": role or None,
                "traits": traits[:4],
            }
        )
        if len(out) >= _NPC_MAX_COUNT:
            break
    return out


def _default_npc_templates(locale: str) -> list[dict]:
    if str(locale or "").strip().lower().startswith("zh"):
        return [
            {"name": "林然", "role": "support friend", "traits": ["细心", "可靠"]},
            {"name": "周峻", "role": "rival competitor", "traits": ["好胜", "锋利"]},
            {"name": "陈导师", "role": "gatekeeper advisor", "traits": ["严谨", "克制"]},
        ]
    return [
        {"name": "Mina", "role": "support friend", "traits": ["steady", "empathetic"]},
        {"name": "Reed", "role": "rival competitor", "traits": ["driven", "incisive"]},
        {"name": "Professor Lin", "role": "gatekeeper advisor", "traits": ["strict", "fair"]},
    ]


def _supplement_npcs(*, locale: str, existing: list[dict]) -> list[dict]:
    merged = [deepcopy(item) for item in existing]
    seen = {_clean_text(item.get("name")).lower() for item in merged if _clean_text(item.get("name"))}
    for template in _default_npc_templates(locale):
        name = _clean_text(template.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        merged.append(deepcopy(template))
        seen.add(key)
        if len(merged) >= _NPC_MIN_COUNT:
            break
    return merged[:_NPC_MAX_COUNT]


def _context_existing_npcs(context: dict) -> list[dict]:
    draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
    characters = draft.get("characters") if isinstance(draft.get("characters"), dict) else {}
    return _normalize_npc_list(characters.get("npcs"))


def _enforce_two_stage_cast_merge(
    *,
    locale: str,
    context: dict,
    suggestions: dict,
    patch_preview: list[dict],
    warnings: list[str],
) -> None:
    existing_npcs = _context_existing_npcs(context)
    generated_characters = suggestions.get("characters") if isinstance(suggestions.get("characters"), dict) else {}
    generated_npcs = _normalize_npc_list(generated_characters.get("npcs"))

    merged: list[dict] = []
    seen: set[str] = set()
    for source in (existing_npcs, generated_npcs):
        for item in source:
            name = _clean_text(item.get("name"))
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(
                {
                    "name": name,
                    "role": _clean_text(item.get("role")) or None,
                    "traits": item.get("traits") if isinstance(item.get("traits"), list) else [],
                }
            )
            if len(merged) >= _NPC_MAX_COUNT:
                break
        if len(merged) >= _NPC_MAX_COUNT:
            break

    if len(merged) < _NPC_MIN_COUNT:
        merged = _supplement_npcs(locale=locale, existing=merged)
        warnings.append("Supplemented NPC roster to keep at least three named NPCs for two-stage authoring.")

    merged = merged[:_NPC_MAX_COUNT]
    normalized_current = _normalize_npc_list(generated_characters.get("npcs"))
    changed = merged != normalized_current
    if not merged:
        return

    generated_characters["npcs"] = merged
    suggestions["characters"] = generated_characters
    if changed:
        _upsert_patch(
            patch_preview,
            path="characters.npcs",
            label="Sync NPC roster with preserved existing cast and supplemental roles",
            value=merged,
        )


def _postprocess_assist_payload(*, task: AuthorAssistTask, locale: str, context: dict, payload: dict) -> dict:
    parsed = deepcopy(payload if isinstance(payload, dict) else {})
    warnings = [str(item) for item in (parsed.get("warnings") or [])]
    suggestions = parsed.get("suggestions") if isinstance(parsed.get("suggestions"), dict) else {}
    patch_preview, patch_warnings = _sanitize_patch_preview(parsed.get("patch_preview"))
    warnings.extend(patch_warnings)

    if task == "seed_expand":
        suggestions, seed_warnings = _normalize_seed_expand_suggestions(
            locale=locale,
            context=context,
            suggestions=suggestions,
        )
        warnings.extend(seed_warnings)
        flow = suggestions.get("flow") if isinstance(suggestions.get("flow"), dict) else {}
        plot = suggestions.get("plot") if isinstance(suggestions.get("plot"), dict) else {}
        _upsert_patch(patch_preview, path="format_version", label="Lock author format to ASF v4", value=4)
        _upsert_patch(patch_preview, path="entry_mode", label="Set entry mode to spark", value="spark")
        _upsert_patch(patch_preview, path="flow", label="Set 4-node tension-loop flow scaffold", value=flow)
        if isinstance(plot.get("mainline_acts"), list):
            _upsert_patch(
                patch_preview,
                path="plot.mainline_acts",
                label="Align acts with tension-loop scene sequence",
                value=plot.get("mainline_acts"),
            )
        if isinstance(suggestions.get("writer_journal"), list):
            _upsert_patch(
                patch_preview,
                path="writer_journal",
                label="Seed explainable writer journal turn",
                value=suggestions.get("writer_journal"),
            )
        if isinstance(suggestions.get("playability_policy"), dict):
            _upsert_patch(
                patch_preview,
                path="playability_policy",
                label="Apply default playability policy for 8-12 minute runs",
                value=suggestions.get("playability_policy"),
            )
    elif task in {"continue_write", "trim_content", "spice_branch", "tension_rebalance"}:
        flow_patch = next(
            (item for item in patch_preview if str(item.get("path") or "").strip() == "flow.scenes" and isinstance(item.get("value"), list)),
            None,
        )
        if flow_patch:
            scenes, graph_warnings = _sanitize_scenes_graph(flow_patch.get("value"))
            if task == "continue_write":
                scenes, continue_warnings = _enforce_continue_after_decision_gate(scenes=scenes, context=context)
                graph_warnings.extend(continue_warnings)
            flow_patch["value"] = scenes
            warnings.extend(graph_warnings)
        else:
            warnings.append("Assist response did not include flow.scenes patch; no graph repair was applied.")

    if task == "seed_expand":
        flow = suggestions.get("flow") if isinstance(suggestions.get("flow"), dict) else {}
        scenes = flow.get("scenes") if isinstance(flow.get("scenes"), list) else []
        if len(scenes) != _ASSIST_MAX_SCENES:
            raise AuthorAssistInvalidOutputError(
                hint="Model output did not meet 4-scene tension loop requirements.",
                detail=f"expected 4 scenes, got {len(scenes)}",
            )
        if not flow.get("start_scene_key"):
            raise AuthorAssistInvalidOutputError(
                hint="Model output missed flow.start_scene_key.",
                detail="missing start_scene_key",
            )

    if task in ENDING_SYNC_ASSIST_TASKS:
        _sync_ending_rules_with_flow(
            task=task,
            context=context,
            suggestions=suggestions,
            patch_preview=patch_preview,
            warnings=warnings,
        )

    if task in TWO_STAGE_ASSIST_TASKS:
        _enforce_two_stage_cast_merge(
            locale=locale,
            context=context,
            suggestions=suggestions,
            patch_preview=patch_preview,
            warnings=warnings,
        )
        warnings.append(f"pipeline_trace: two_stage/{task} expand->build")

    return {
        "suggestions": suggestions,
        "patch_preview": _patches_with_unique_ids(patch_preview),
        "warnings": warnings,
    }
