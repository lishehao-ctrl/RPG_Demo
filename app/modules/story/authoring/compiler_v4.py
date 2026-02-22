from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.modules.story.authoring.diagnostics import diag
from app.modules.story.authoring.schema_v4 import (
    ACTION_TYPES,
    TIME_SLOTS,
    AuthorStoryV4,
    Effects,
    FallbackStyle,
    FallbackTextVariants,
)

_DENY_FALLBACK_TERMS_RE = re.compile(r"\b(fuzzy|unclear|invalid|wrong input|cannot understand)\b", re.IGNORECASE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class AuthorCompileResult:
    pack: dict | None
    errors: list[dict[str, str | None]]
    warnings: list[dict[str, str | None]]
    mappings: dict[str, dict[str, str]]


def _slugify(value: str, *, default: str) -> str:
    text = str(value or "").strip().lower()
    text = _SLUG_RE.sub("_", text)
    text = text.strip("_")
    return text or default


def _dedupe_slug(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _clean_patterns(values: list[str] | None, *, max_items: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _sanitize_fallback_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    cleaned = _DENY_FALLBACK_TERMS_RE.sub("off-beat", cleaned)
    return cleaned.strip()


def _fallback_tone_templates(tone: str) -> dict[str, str]:
    normalized = str(tone or "supportive").strip().lower()
    if normalized == "calm":
        return {
            "NO_INPUT": "You slow down for a moment and settle your breathing.",
            "BLOCKED": "That route does not open right now, so you reset and stay composed.",
            "FALLBACK": "You adjust smoothly and keep your footing in the day.",
            "DEFAULT": "You take a small pause and choose your next move.",
        }
    if normalized == "neutral":
        return {
            "NO_INPUT": "You miss a beat and regroup.",
            "BLOCKED": "That option is not available right now, so you pivot.",
            "FALLBACK": "You redirect and keep moving through the moment.",
            "DEFAULT": "You pause and reassess.",
        }
    return {
        "NO_INPUT": "You lose a beat and take a breath before moving.",
        "BLOCKED": "That approach does not work right now, so you reset your pace.",
        "FALLBACK": "You make a quick adjustment and keep your momentum.",
        "DEFAULT": "You pause and rethink your next move.",
    }


def _default_action_params(action_type: str) -> dict[str, str]:
    if action_type == "date":
        return {"target": "alice"}
    if action_type == "gift":
        return {"target": "alice", "gift_type": "small gift"}
    return {}


def _compact_effects(value: Effects | dict | None) -> dict[str, int | float]:
    if value is None:
        source: dict[str, Any] = {}
    elif isinstance(value, dict):
        source = value
    else:
        source = value.model_dump(mode="json", exclude_none=True)
    out: dict[str, int | float] = {}
    for key in ("energy", "money", "knowledge", "affection"):
        raw = source.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            out[key] = raw
    return out


def _compact_thresholds(value: dict | None) -> dict[str, int | float]:
    source = value if isinstance(value, dict) else {}
    out: dict[str, int | float] = {}
    for raw_key, raw_value in source.items():
        key = str(raw_key or "").strip()
        if not key or raw_value is None or isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, (int, float)):
            out[key] = raw_value
    return out


def _normalize_action(
    *,
    action_type: str,
    action_params: dict,
    path: str,
    warnings: list[dict[str, str | None]],
) -> dict:
    normalized = dict(action_params or {})
    if action_type not in ACTION_TYPES:
        normalized = {}
    if action_type in {"study", "work", "rest"}:
        if normalized:
            warnings.append(
                diag(
                    code="AUTHOR_ACTION_PARAMS_CLEARED",
                    path=path,
                    message=f"'{action_type}' does not accept params; params were ignored.",
                    suggestion="Remove action_params for simple action types.",
                )
            )
        return {"action_id": action_type, "params": {}}

    defaults = _default_action_params(action_type)
    out = {**defaults, **{k: v for k, v in normalized.items() if v is not None}}
    if action_type == "date" and not str(out.get("target") or "").strip():
        out["target"] = "alice"
    if action_type == "gift":
        if not str(out.get("target") or "").strip():
            out["target"] = "alice"
        if not str(out.get("gift_type") or "").strip():
            out["gift_type"] = "small gift"
    return {"action_id": action_type, "params": out}


def _merge_fallback_variants(
    *,
    tone: str,
    overrides: FallbackTextVariants | None,
) -> dict[str, str]:
    out = _fallback_tone_templates(tone)
    raw = overrides.model_dump(mode="json", exclude_none=True) if overrides else {}
    for key in ("NO_INPUT", "BLOCKED", "FALLBACK", "DEFAULT"):
        if key in raw:
            out[key] = str(raw[key])
    return {key: _sanitize_fallback_text(value) for key, value in out.items()}


def _scene_brief(scene) -> str:
    title = " ".join(str(scene.title or "").split())
    setup = " ".join(str(scene.setup or "").split())
    dramatic_question = " ".join(str(scene.dramatic_question or "").split())
    if dramatic_question:
        return f"{title}: {setup} Question: {dramatic_question}".strip()
    return f"{title}: {setup}".strip()


def _project_initial_state(world) -> dict:
    initial_state = {
        "energy": 80,
        "money": 50,
        "knowledge": 0,
        "affection": 0,
        "day": 1,
        "slot": "morning",
    }
    source = world.global_state if isinstance(world.global_state, dict) else {}
    if isinstance(source.get("initial_state"), dict):
        source = source.get("initial_state") or {}
    for key in ("energy", "money", "knowledge", "affection", "day"):
        raw = source.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            initial_state[key] = int(raw)
    slot = str(source.get("slot") or "").strip().lower()
    if slot in TIME_SLOTS:
        initial_state["slot"] = slot
    return initial_state


def compile_author_story_payload(payload: dict) -> AuthorCompileResult:
    errors: list[dict[str, str | None]] = []
    warnings: list[dict[str, str | None]] = []
    mappings: dict[str, dict[str, str]] = {"scenes": {}, "options": {}, "quests": {}}

    try:
        author = AuthorStoryV4.model_validate(payload if isinstance(payload, dict) else {})
    except ValidationError as exc:
        for item in exc.errors():
            location = ".".join(str(part) for part in item.get("loc", ()))
            errors.append(
                diag(
                    code="AUTHOR_SCHEMA_ERROR",
                    path=location or None,
                    message=str(item.get("msg") or "validation error"),
                    suggestion="Check required ASF v4 fields, including entry_mode, writer_journal, and playability_policy.",
                )
            )
        return AuthorCompileResult(pack=None, errors=errors, warnings=warnings, mappings=mappings)

    if author.source_text and not str(author.meta.summary or "").strip():
        author.meta.summary = str(author.source_text or "")[:220]
        warnings.append(
            diag(
                code="AUTHOR_V4_SOURCE_TEXT_SUMMARY",
                path="meta.summary",
                message="meta.summary was seeded from source_text because summary was empty.",
                suggestion="Adjust summary text if you need a different short description.",
            )
        )
    if author.writer_journal:
        warnings.append(
            diag(
                code="AUTHOR_V4_WRITER_JOURNAL_METADATA_ONLY",
                path="writer_journal",
                message="writer_journal is preserved in metadata and does not affect runtime branching.",
                suggestion="Use flow.scenes/options to change playable runtime behavior.",
            )
        )

    style = author.systems.fallback_style or FallbackStyle()

    used_scene_slugs: set[str] = set()
    scene_keys: list[str] = []
    scene_node_map: dict[str, str] = {}
    scene_alias_map: dict[str, str] = {}
    option_ref_map: dict[str, str] = {}
    option_token_map: dict[str, list[str]] = {}

    for scene_idx, scene in enumerate(author.flow.scenes):
        raw_key = scene.scene_key or f"scene_{scene_idx + 1}"
        base_slug = _slugify(raw_key, default=f"scene_{scene_idx + 1}")
        scene_slug = _dedupe_slug(base_slug, used_scene_slugs)
        scene_key = scene_slug
        node_id = f"n_{scene_slug}"
        scene_keys.append(scene_key)
        scene_node_map[scene_key] = node_id
        mappings["scenes"][scene_key] = node_id

        for alias in {raw_key, scene.scene_key, base_slug, scene_key, scene.title}:
            alias_text = str(alias or "").strip().lower()
            if alias_text:
                scene_alias_map[alias_text] = scene_key

    def resolve_scene_ref(ref: str | None, *, path: str) -> str | None:
        key = str(ref or "").strip()
        if not key:
            return None
        lowered = key.lower()
        if lowered in scene_alias_map:
            return scene_node_map.get(scene_alias_map[lowered])
        slug = _slugify(lowered, default="")
        if slug and slug in scene_node_map:
            return scene_node_map.get(slug)
        errors.append(
            diag(
                code="AUTHOR_UNKNOWN_SCENE_REF",
                path=path,
                message=f"Unknown scene reference '{key}'.",
                suggestion="Use an existing flow.scenes[].scene_key.",
            )
        )
        return None

    nodes: list[dict] = []
    for scene_idx, scene in enumerate(author.flow.scenes):
        scene_key = scene_keys[scene_idx]
        node_id = scene_node_map[scene_key]
        compiled_options: list[dict] = []
        option_patterns: dict[str, list[str]] = {}

        for option_idx, option in enumerate(scene.options):
            choice_id = f"c_{scene_key}_{option_idx + 1}"
            option_token = _slugify(option.option_key or f"opt_{option_idx + 1}", default=f"opt_{option_idx + 1}")
            option_ref = f"{scene_key}.{option_token}"
            option_ref_map[option_ref] = choice_id
            option_token_map.setdefault(option_token, []).append(choice_id)
            mappings["options"][option_ref] = choice_id

            next_node_id = node_id
            if option.go_to:
                resolved_next = resolve_scene_ref(
                    option.go_to,
                    path=f"flow.scenes[{scene_idx}].options[{option_idx}].go_to",
                )
                if resolved_next:
                    next_node_id = resolved_next
            elif not scene.is_end:
                errors.append(
                    diag(
                        code="AUTHOR_MISSING_OPTION_TARGET",
                        path=f"flow.scenes[{scene_idx}].options[{option_idx}].go_to",
                        message="Option target is required for non-end scenes.",
                        suggestion="Set go_to to a valid scene_key.",
                    )
                )

            action = _normalize_action(
                action_type=str(option.action_type),
                action_params=option.action_params,
                path=f"flow.scenes[{scene_idx}].options[{option_idx}].action_params",
                warnings=warnings,
            )
            requires_payload = (
                option.requirements.model_dump(mode="json", exclude_none=True)
                if option.requirements
                else None
            )
            effects_payload = _compact_effects(option.effects)
            compiled_option = {
                "choice_id": choice_id,
                "display_text": option.label,
                "action": action,
                "next_node_id": next_node_id,
                "is_key_decision": bool(option.is_key_decision),
            }
            if requires_payload:
                compiled_option["requires"] = requires_payload
            if effects_payload:
                compiled_option["effects"] = effects_payload
            compiled_options.append(compiled_option)

            patterns = _clean_patterns(option.intent_aliases)
            if patterns:
                option_patterns[choice_id] = patterns

        if not option_patterns:
            fallback_patterns = _clean_patterns(scene.free_input_hints)
            if fallback_patterns and compiled_options:
                primary_choice_id = str(compiled_options[0]["choice_id"])
                option_patterns[primary_choice_id] = fallback_patterns
                warnings.append(
                    diag(
                        code="AUTHOR_HINTS_MAPPED_TO_FIRST_OPTION",
                        path=f"flow.scenes[{scene_idx}].free_input_hints",
                        message="free_input_hints were mapped to the first option because no option intent_aliases were set.",
                        suggestion="Prefer explicit option.intent_aliases for predictable mapping.",
                    )
                )

        intents: list[dict] = []
        for option_idx, compiled_option in enumerate(compiled_options):
            choice_id = str(compiled_option["choice_id"])
            patterns = option_patterns.get(choice_id) or []
            if not patterns:
                continue
            intents.append(
                {
                    "intent_id": f"INTENT_{scene_key}_{option_idx + 1}",
                    "alias_choice_id": choice_id,
                    "description": f"Author hint for {compiled_option['display_text']}",
                    "patterns": patterns,
                }
            )

        node_fallback_payload = None
        if scene.fallback is not None:
            scene_tone = str(scene.fallback.tone or style.tone)
            action_type = str(scene.fallback.action_type or style.action_type)
            action_payload = _normalize_action(
                action_type=action_type,
                action_params={},
                path=f"flow.scenes[{scene_idx}].fallback",
                warnings=warnings,
            )
            fallback_variants = _merge_fallback_variants(
                tone=scene_tone,
                overrides=scene.fallback.text_variants,
            )
            node_fallback_payload = {
                "id": f"fb_{scene_key}",
                "action": action_payload,
                "next_node_id_policy": "stay",
                "text_variants": fallback_variants,
            }
            effects_payload = _compact_effects(scene.fallback.effects)
            if effects_payload:
                node_fallback_payload["effects"] = effects_payload
            if scene.fallback.next_scene_key:
                resolved_fallback_target = resolve_scene_ref(
                    scene.fallback.next_scene_key,
                    path=f"flow.scenes[{scene_idx}].fallback.next_scene_key",
                )
                if resolved_fallback_target:
                    node_fallback_payload["next_node_id_policy"] = "explicit_next"
                    node_fallback_payload["next_node_id"] = resolved_fallback_target

        node_payload = {
            "node_id": node_id,
            "scene_brief": _scene_brief(scene),
            "is_end": bool(scene.is_end),
            "choices": compiled_options,
            "intents": intents,
        }
        if node_fallback_payload is not None:
            node_payload["fallback"] = node_fallback_payload
        nodes.append(node_payload)

    start_node_id = None
    if author.flow.start_scene_key:
        start_node_id = resolve_scene_ref(author.flow.start_scene_key, path="flow.start_scene_key")
    if not start_node_id and nodes:
        start_node_id = str(nodes[0]["node_id"])

    def resolve_option_ref(ref: str | None, *, path: str) -> str | None:
        token = str(ref or "").strip()
        if not token:
            return None
        if "." in token:
            raw_scene, raw_option = token.split(".", 1)
            scene_lookup = scene_alias_map.get(raw_scene.strip().lower())
            if not scene_lookup:
                errors.append(
                    diag(
                        code="AUTHOR_UNKNOWN_OPTION_SCENE",
                        path=path,
                        message=f"Unknown scene in option reference '{token}'.",
                        suggestion="Use '<scene_key>.<option_key>' format with an existing scene_key.",
                    )
                )
                return None
            option_slug = _slugify(raw_option, default="")
            ref_key = f"{scene_lookup}.{option_slug}"
            if ref_key in option_ref_map:
                return option_ref_map[ref_key]
        option_slug = _slugify(token, default="")
        matches = option_token_map.get(option_slug) or []
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            errors.append(
                diag(
                    code="AUTHOR_AMBIGUOUS_OPTION_REF",
                    path=path,
                    message=f"Option reference '{token}' is ambiguous across scenes.",
                    suggestion="Use '<scene_key>.<option_key>' to disambiguate.",
                )
            )
            return None
        errors.append(
            diag(
                code="AUTHOR_UNKNOWN_OPTION_REF",
                path=path,
                message=f"Unknown option reference '{token}'.",
                suggestion="Use an existing option reference in scene.option format.",
            )
        )
        return None

    quest_ref_to_id: dict[str, str] = {}
    quests_payload: list[dict] = []
    used_quest_slugs: set[str] = set()

    for quest_idx, quest in enumerate(author.consequence.quest_progression_rules):
        raw_quest_key = quest.quest_key or f"quest_{quest_idx + 1}"
        quest_slug = _dedupe_slug(_slugify(raw_quest_key, default=f"quest_{quest_idx + 1}"), used_quest_slugs)
        quest_id = f"q_{quest_slug}"
        mappings["quests"][quest_slug] = quest_id
        for alias in {raw_quest_key, quest.quest_key, quest_slug, quest_id}:
            alias_text = str(alias or "").strip().lower()
            if alias_text:
                quest_ref_to_id[alias_text] = quest_id

        stages_payload: list[dict] = []
        for stage_idx, stage in enumerate(quest.stages):
            stage_slug = _slugify(stage.stage_key or f"stage_{stage_idx + 1}", default=f"stage_{stage_idx + 1}")
            stage_id = f"stage_{quest_slug}_{stage_slug}"
            milestones_payload: list[dict] = []
            for milestone_idx, milestone in enumerate(stage.milestones):
                milestone_slug = _slugify(
                    milestone.milestone_key or f"milestone_{milestone_idx + 1}",
                    default=f"milestone_{milestone_idx + 1}",
                )
                milestone_id = f"m_{quest_slug}_{stage_slug}_{milestone_slug}"
                trigger = milestone.when
                trigger_payload: dict[str, Any] = {}
                if trigger.scene_key_is:
                    node_ref = resolve_scene_ref(
                        trigger.scene_key_is,
                        path=f"consequence.quest_progression_rules[{quest_idx}].stages[{stage_idx}].milestones[{milestone_idx}].when.scene_key_is",
                    )
                    if node_ref:
                        trigger_payload["node_id_is"] = node_ref
                if trigger.next_scene_key_is:
                    next_ref = resolve_scene_ref(
                        trigger.next_scene_key_is,
                        path=f"consequence.quest_progression_rules[{quest_idx}].stages[{stage_idx}].milestones[{milestone_idx}].when.next_scene_key_is",
                    )
                    if next_ref:
                        trigger_payload["next_node_id_is"] = next_ref
                if trigger.option_ref_is:
                    option_ref = resolve_option_ref(
                        trigger.option_ref_is,
                        path=f"consequence.quest_progression_rules[{quest_idx}].stages[{stage_idx}].milestones[{milestone_idx}].when.option_ref_is",
                    )
                    if option_ref:
                        trigger_payload["executed_choice_id_is"] = option_ref
                if trigger.action_type_is:
                    trigger_payload["action_id_is"] = str(trigger.action_type_is)
                if trigger.fallback_used_is is not None:
                    trigger_payload["fallback_used_is"] = bool(trigger.fallback_used_is)
                if trigger.state_at_least:
                    trigger_payload["state_at_least"] = _compact_thresholds(trigger.state_at_least)
                if trigger.state_delta_at_least:
                    trigger_payload["state_delta_at_least"] = _compact_thresholds(trigger.state_delta_at_least)
                milestone_payload: dict[str, Any] = {
                    "milestone_id": milestone_id,
                    "title": milestone.title,
                    "when": trigger_payload,
                }
                if milestone.description:
                    milestone_payload["description"] = milestone.description
                rewards_payload = _compact_effects(milestone.rewards)
                if rewards_payload:
                    milestone_payload["rewards"] = rewards_payload
                milestones_payload.append(milestone_payload)

            stage_payload: dict[str, Any] = {
                "stage_id": stage_id,
                "title": stage.title,
                "milestones": milestones_payload,
            }
            if stage.description:
                stage_payload["description"] = stage.description
            stage_rewards = _compact_effects(stage.stage_rewards)
            if stage_rewards:
                stage_payload["stage_rewards"] = stage_rewards
            stages_payload.append(stage_payload)

        quest_payload: dict[str, Any] = {
            "quest_id": quest_id,
            "title": quest.title,
            "auto_activate": bool(quest.auto_activate),
            "stages": stages_payload,
        }
        if quest.description:
            quest_payload["description"] = quest.description
        completion_rewards = _compact_effects(quest.completion_rewards)
        if completion_rewards:
            quest_payload["completion_rewards"] = completion_rewards
        quests_payload.append(quest_payload)

    events_payload: list[dict] = []
    used_event_slugs: set[str] = set()
    merged_events = [*(author.systems.events or []), *(author.consequence.event_rules or [])]
    if author.systems.events and author.consequence.event_rules:
        warnings.append(
            diag(
                code="AUTHOR_EVENTS_MERGED",
                path="systems.events|consequence.event_rules",
                message="systems.events and consequence.event_rules were merged during compilation.",
                suggestion="Keep one canonical event list to reduce duplicate intent.",
            )
        )
    for event_idx, event in enumerate(merged_events):
        event_slug = _dedupe_slug(
            _slugify(event.event_key or event.title or f"event_{event_idx + 1}", default=f"event_{event_idx + 1}"),
            used_event_slugs,
        )
        trigger_payload: dict[str, Any] = {}
        if event.trigger.scene_key_is:
            node_ref = resolve_scene_ref(
                event.trigger.scene_key_is,
                path=f"systems.events[{event_idx}].trigger.scene_key_is",
            )
            if node_ref:
                trigger_payload["node_id_is"] = node_ref
        if event.trigger.day_in is not None:
            trigger_payload["day_in"] = list(event.trigger.day_in)
        if event.trigger.slot_in is not None:
            trigger_payload["slot_in"] = list(event.trigger.slot_in)
        if event.trigger.fallback_used_is is not None:
            trigger_payload["fallback_used_is"] = bool(event.trigger.fallback_used_is)
        if event.trigger.state_at_least:
            trigger_payload["state_at_least"] = _compact_thresholds(event.trigger.state_at_least)
        if event.trigger.state_delta_at_least:
            trigger_payload["state_delta_at_least"] = _compact_thresholds(event.trigger.state_delta_at_least)
        event_payload: dict[str, Any] = {
            "event_id": f"ev_{event_slug}",
            "title": event.title,
            "weight": int(event.weight),
            "once_per_run": bool(event.once_per_run),
            "cooldown_steps": int(event.cooldown_steps),
            "trigger": trigger_payload,
        }
        effects_payload = _compact_effects(event.effects)
        if effects_payload:
            event_payload["effects"] = effects_payload
        if event.narration_hint:
            event_payload["narration_hint"] = event.narration_hint
        events_payload.append(event_payload)

    endings_payload: list[dict] = []
    used_ending_slugs: set[str] = set()
    for ending_idx, ending in enumerate(author.ending.ending_rules):
        ending_slug = _dedupe_slug(
            _slugify(ending.ending_key or ending.title or f"ending_{ending_idx + 1}", default=f"ending_{ending_idx + 1}"),
            used_ending_slugs,
        )
        trigger_payload: dict[str, Any] = {}
        if ending.trigger.scene_key_is:
            node_ref = resolve_scene_ref(
                ending.trigger.scene_key_is,
                path=f"ending.ending_rules[{ending_idx}].trigger.scene_key_is",
            )
            if node_ref:
                trigger_payload["node_id_is"] = node_ref
        for key in (
            "day_at_least",
            "day_at_most",
            "energy_at_most",
            "money_at_least",
            "knowledge_at_least",
            "affection_at_least",
        ):
            value = getattr(ending.trigger, key)
            if value is not None:
                trigger_payload[key] = int(value)
        completed_refs: list[str] = []
        for quest_ref in ending.trigger.completed_quests_include:
            ref_key = str(quest_ref or "").strip().lower()
            if ref_key in quest_ref_to_id:
                completed_refs.append(quest_ref_to_id[ref_key])
            elif ref_key.startswith("q_"):
                completed_refs.append(str(quest_ref))
            else:
                warnings.append(
                    diag(
                        code="AUTHOR_UNKNOWN_QUEST_REF",
                        path=f"ending.ending_rules[{ending_idx}].trigger.completed_quests_include",
                        message=f"Unknown quest reference '{quest_ref}' kept as-is.",
                        suggestion="Prefer consequence.quest_progression_rules[].quest_key references.",
                    )
                )
                completed_refs.append(str(quest_ref))
        if completed_refs:
            trigger_payload["completed_quests_include"] = completed_refs
        ending_payload = {
            "ending_id": f"ending_{ending_slug}",
            "title": ending.title,
            "priority": int(ending.priority),
            "outcome": ending.outcome,
            "trigger": trigger_payload,
            "epilogue": ending.epilogue,
        }
        endings_payload.append(ending_payload)

    global_text_variants = _merge_fallback_variants(
        tone=str(style.tone),
        overrides=style.text_variants,
    )
    default_action = _normalize_action(
        action_type=str(style.action_type),
        action_params={},
        path="systems.fallback_style.action_type",
        warnings=warnings,
    )
    default_fallback_payload: dict[str, Any] = {
        "id": "fb_default",
        "action": default_action,
        "next_node_id_policy": "stay",
        "text_variants": global_text_variants,
    }
    default_effects = _compact_effects(style.effects)
    if default_effects:
        default_fallback_payload["effects"] = default_effects

    protagonist = author.characters.protagonist
    raw_characters = [
        {
            "name": protagonist.name,
            "role": protagonist.role or "protagonist",
            "traits": list(protagonist.traits or []),
        },
        *[
            {
                "name": item.name,
                "role": item.role,
                "traits": list(item.traits or []),
            }
            for item in (author.characters.npcs or [])
        ],
    ]
    used_character_ids: set[str] = set()
    characters_payload = []
    for idx, item in enumerate(raw_characters):
        char_id = _dedupe_slug(_slugify(item["name"], default=f"character_{idx + 1}"), used_character_ids)
        characters_payload.append(
            {
                "id": char_id,
                "name": item["name"],
                "role": item["role"],
                "traits": item["traits"],
            }
        )

    if (author.plot.mainline_goal or author.plot.sideline_threads or author.plot.mainline_acts) and not author.consequence.quest_progression_rules:
        warnings.append(
            diag(
                code="AUTHOR_PLOT_NOT_COMPILED_TO_QUESTS",
                path="plot",
                message="plot.* fields are authoring guides and do not create runtime quests unless consequence.quest_progression_rules is provided.",
                suggestion="Use /stories/author-assist task=consistency_check and apply quest suggestions into consequence.quest_progression_rules.",
            )
        )
    if author.action.action_catalog:
        warnings.append(
            diag(
                code="AUTHOR_ACTION_CATALOG_METADATA_ONLY",
                path="action.action_catalog",
                message="action.action_catalog is retained as author metadata and does not create runtime state changes.",
                suggestion="Define executable effects through flow.scenes[].options and consequence rules.",
            )
        )

    initial_state = _project_initial_state(author.world)
    if initial_state.get("slot") not in TIME_SLOTS:
        initial_state["slot"] = "morning"

    pack: dict[str, Any] = {
        "story_id": author.meta.story_id,
        "version": int(author.meta.version),
        "title": author.meta.title,
        "start_node_id": start_node_id,
        "nodes": nodes,
        "characters": characters_payload,
        "initial_state": initial_state,
        "default_fallback": default_fallback_payload,
        "fallback_executors": [],
        "global_fallback_choice_id": None,
        "quests": quests_payload,
        "events": events_payload,
        "endings": endings_payload,
        "author_source_v4": author.model_dump(mode="json", exclude_none=True),
    }
    if author.meta.summary:
        pack["summary"] = author.meta.summary
    if author.meta.locale:
        pack["locale"] = author.meta.locale

    if not start_node_id:
        errors.append(
            diag(
                code="AUTHOR_MISSING_START_SCENE",
                path="flow.start_scene_key",
                message="Could not resolve start scene.",
                suggestion="Set flow.start_scene_key to a valid flow.scenes[].scene_key.",
            )
        )

    return AuthorCompileResult(
        pack=pack,
        errors=errors,
        warnings=warnings,
        mappings=mappings,
    )
