from __future__ import annotations

import json
import re
import uuid
from typing import Literal

from sqlalchemy.orm import Session

from app.config import settings
from app.modules.llm.adapter import LLMUnavailableError, get_llm_runtime
from app.modules.llm.prompts import build_author_assist_prompt
from app.modules.story.constants import AUTHOR_ASSIST_TASKS_V4

AuthorAssistTask = Literal[*AUTHOR_ASSIST_TASKS_V4]

_WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9'_-]*")


def _clean_text(value: object, *, fallback: str = "") -> str:
    text = " ".join(str(value or "").split())
    return text or fallback


def _slugify(value: object, *, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", _clean_text(value).lower()).strip("_")
    return text or fallback


def _extract_keywords(text: str, *, limit: int = 4) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in _WORD_RE.findall(text.lower()):
        if len(token) < 3:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= limit:
            break
    return out


def _patch(path: str, label: str, value: object) -> dict:
    return {
        "id": _slugify(path, fallback="patch"),
        "path": path,
        "label": label,
        "value": value,
    }


def _bootstrap_scenes() -> list[dict]:
    return [
        {
            "scene_key": "scene_intro",
            "title": "Morning Pressure",
            "setup": "The morning opens with limited time and competing priorities.",
            "dramatic_question": "What do you secure first before the day tightens?",
            "free_input_hints": ["study", "work", "rest", "alice"],
            "options": [
                {
                    "option_key": "focus_class",
                    "label": "Lock in one focused study block",
                    "intent_aliases": ["study", "class", "library", "focus"],
                    "action_type": "study",
                    "go_to": "scene_afternoon",
                    "is_key_decision": False,
                },
                {
                    "option_key": "quick_shift",
                    "label": "Take a short paid shift",
                    "intent_aliases": ["work", "job", "money", "shift"],
                    "action_type": "work",
                    "go_to": "scene_afternoon",
                    "is_key_decision": False,
                },
                {
                    "option_key": "reset_pace",
                    "label": "Pause to recover your pace",
                    "intent_aliases": ["rest", "recover", "pause", "food"],
                    "action_type": "rest",
                    "go_to": "scene_afternoon",
                    "is_key_decision": False,
                },
            ],
            "is_end": False,
            "intent_module": {
                "author_input": "Starter scene with three actionable routes.",
                "intent_tags": ["setup", "tradeoff"],
                "parse_notes": "Keeps choice fanout manageable for first-time authors.",
                "aliases": ["start", "morning", "first move"],
            },
        },
        {
            "scene_key": "scene_afternoon",
            "title": "Afternoon Convergence",
            "setup": "Your earlier decisions narrow the afternoon into one decisive push.",
            "dramatic_question": "What matters most before evening closes in?",
            "free_input_hints": ["finish", "talk", "recover"],
            "options": [
                {
                    "option_key": "close_strong",
                    "label": "Close the day with disciplined progress",
                    "intent_aliases": ["finish", "focus", "complete"],
                    "action_type": "study",
                    "is_key_decision": True,
                },
                {
                    "option_key": "protect_relationship",
                    "label": "Make time for one important relationship",
                    "intent_aliases": ["alice", "talk", "date"],
                    "action_type": "date",
                    "is_key_decision": True,
                },
            ],
            "is_end": True,
            "intent_module": {
                "author_input": "Second beat that resolves the short arc.",
                "intent_tags": ["resolution", "decision"],
                "parse_notes": "End scene keeps two clear finishing tones.",
                "aliases": ["afternoon", "resolution"],
            },
        },
    ]


def _deterministic_layer_bootstrap(locale: str, context: dict) -> tuple[dict, list[dict], list[str]]:
    global_brief = _clean_text(
        context.get("global_brief") or context.get("brief") or context.get("premise"),
        fallback="A grounded campus week story about balancing study, money, and relationships.",
    )
    title_seed = _clean_text(context.get("title"), fallback="Campus Week Story")
    story_id = _slugify(context.get("story_id") or title_seed, fallback="author_story_v4")
    scenes = _bootstrap_scenes()
    suggestions = {
        "meta": {
            "story_id": story_id,
            "version": int(context.get("version") or 1),
            "title": title_seed,
            "summary": global_brief,
            "locale": locale,
        },
        "world": {
            "era": "Contemporary semester",
            "location": "University district",
            "boundaries": "No supernatural powers; time, stamina, and money constrain choices.",
            "social_rules": "Reputation and consistency shape how people respond over the week.",
            "global_state": {
                "initial_state": {
                    "energy": 80,
                    "money": 50,
                    "knowledge": 0,
                    "affection": 0,
                    "day": 1,
                    "slot": "morning",
                }
            },
            "intent_module": {
                "author_input": global_brief,
                "intent_tags": ["grounded", "campus", "weekly_arc"],
                "parse_notes": "Global brief was decomposed into world constraints and social rules.",
                "aliases": ["world", "setting", "rules"],
            },
        },
        "characters": {
            "protagonist": {
                "name": "You",
                "role": "student",
                "traits": ["driven", "tired", "adaptive"],
                "resources": {"focus": "limited", "schedule": "tight"},
            },
            "npcs": [
                {"name": "Alice", "role": "close friend", "traits": ["warm", "observant"]},
            ],
            "relationship_axes": {
                "trust": "consistency under pressure",
                "affection": "time invested in meaningful moments",
            },
            "intent_module": {
                "author_input": "Character layer extracted from brief.",
                "intent_tags": ["character_conflict", "relationship_pressure"],
                "parse_notes": "Added one anchor NPC to keep social choices concrete.",
                "aliases": ["cast", "npc", "protagonist"],
            },
        },
        "plot": {
            "mainline_goal": "Finish the week with stable progress and intact relationships.",
            "mainline_acts": [
                {
                    "act_key": "act_setup",
                    "title": "Act I - Setup",
                    "objective": "Establish weekly pressure and available routes.",
                    "scene_keys": ["scene_intro"],
                },
                {
                    "act_key": "act_resolution",
                    "title": "Act II - Resolution",
                    "objective": "Resolve the trade-off before evening.",
                    "scene_keys": ["scene_afternoon"],
                },
            ],
            "sideline_threads": [
                "Keep energy stable before major pushes.",
                "Protect one meaningful relationship beat.",
            ],
            "intent_module": {
                "author_input": "Two-act weekly micro-arc.",
                "intent_tags": ["mainline", "sideline"],
                "parse_notes": "Acts organize writing; runtime branching still comes from scenes.",
                "aliases": ["plot", "acts", "threads"],
            },
        },
        "flow": {
            "start_scene_key": "scene_intro",
            "scenes": scenes,
            "intent_module": {
                "author_input": "Flow seeded from global brief.",
                "intent_tags": ["branching", "scene_flow"],
                "parse_notes": "Scene graph is minimal and ready for iterative expansion.",
                "aliases": ["scene", "node", "flow"],
            },
        },
        "action": {
            "action_catalog": [
                {"action_id": "study", "label": "Study"},
                {"action_id": "work", "label": "Work"},
                {"action_id": "rest", "label": "Rest"},
                {"action_id": "date", "label": "Social"},
                {"action_id": "gift", "label": "Gift"},
            ],
            "input_mapping_policy": "intent_alias_only_visible_choice",
            "intent_module": {
                "author_input": "Keep free input constrained to visible options.",
                "intent_tags": ["mapping", "safety"],
                "parse_notes": "Prevents free-input from bypassing runtime choice semantics.",
                "aliases": ["action", "mapping", "input"],
            },
        },
        "consequence": {
            "state_axes": ["energy", "money", "knowledge", "affection", "day", "slot"],
            "quest_progression_rules": [],
            "event_rules": [],
            "intent_module": {
                "author_input": "State axes and progression hooks.",
                "intent_tags": ["consequence", "progression"],
                "parse_notes": "Start simple; add quests/events after core scenes are stable.",
                "aliases": ["state", "quest", "event"],
            },
        },
        "ending": {
            "ending_rules": [
                {
                    "ending_key": "steady_finish",
                    "title": "Steady Finish",
                    "priority": 100,
                    "outcome": "success",
                    "trigger": {"day_at_least": 5, "knowledge_at_least": 8},
                    "epilogue": "You close the week with steady momentum and room to breathe.",
                }
            ],
            "intent_module": {
                "author_input": "Ending seeded from mainline goal.",
                "intent_tags": ["ending", "closure"],
                "parse_notes": "Single success ending scaffold to refine later.",
                "aliases": ["ending", "closure"],
            },
        },
        "systems": {
            "fallback_style": {"tone": "supportive", "action_type": "rest"},
            "events": [],
            "intent_module": {
                "author_input": "System defaults for fallback behavior.",
                "intent_tags": ["fallback"],
                "parse_notes": "Supportive fallback prevents rejection tone for free input.",
                "aliases": ["system", "fallback"],
            },
        },
    }

    patch_preview = [
        _patch("meta", "Set story metadata", suggestions["meta"]),
        _patch("world", "Set world layer", suggestions["world"]),
        _patch("characters", "Set character layer", suggestions["characters"]),
        _patch("plot", "Set plot layer", suggestions["plot"]),
        _patch("flow", "Set flow layer", suggestions["flow"]),
        _patch("action", "Set action layer", suggestions["action"]),
        _patch("consequence", "Set consequence layer", suggestions["consequence"]),
        _patch("ending", "Set ending layer", suggestions["ending"]),
        _patch("systems", "Set systems layer", suggestions["systems"]),
    ]
    warnings = [
        f"Locale target is '{locale}'. Suggestions remain editable before compile.",
        "All patches are optional; review before applying.",
    ]
    return suggestions, patch_preview, warnings


def _deterministic_layer_refine(context: dict) -> tuple[dict, list[dict], list[str]]:
    layer = _clean_text(context.get("layer"), fallback="world").lower()
    author_input = _clean_text(
        context.get("author_input") or context.get("layer_input"),
        fallback="Refine this layer with clearer stakes and causality.",
    )

    if layer == "characters":
        suggestions = {
            "characters": {
                "relationship_axes": {
                    "trust": "grows when promises are kept under pressure",
                    "respect": "rises when trade-offs are handled intentionally",
                },
                "intent_module": {
                    "author_input": author_input,
                    "intent_tags": ["character_refine", "relationship_tone"],
                    "parse_notes": "Added relationship axes to support repeatable NPC responses.",
                    "aliases": ["relationship", "npcs"],
                },
            }
        }
        patch_preview = [
            _patch("characters.relationship_axes", "Refine relationship axes", suggestions["characters"]["relationship_axes"]),
            _patch("characters.intent_module", "Refresh characters intent notes", suggestions["characters"]["intent_module"]),
        ]
        return suggestions, patch_preview, []

    if layer == "plot":
        suggestions = {
            "plot": {
                "sideline_threads": [
                    "A small earning opportunity stays open if energy permits.",
                    "A fragile social thread can recover with timely attention.",
                ],
                "intent_module": {
                    "author_input": author_input,
                    "intent_tags": ["plot_refine", "sideline_balance"],
                    "parse_notes": "Sidelines were tuned to complement, not replace, the mainline.",
                    "aliases": ["acts", "threads"],
                },
            }
        }
        patch_preview = [
            _patch("plot.sideline_threads", "Refine sideline threads", suggestions["plot"]["sideline_threads"]),
            _patch("plot.intent_module", "Refresh plot intent notes", suggestions["plot"]["intent_module"]),
        ]
        return suggestions, patch_preview, []

    if layer == "scene" or layer == "flow":
        scene_patch = {
            "dramatic_question": "What cost are you willing to accept right now for long-term momentum?",
            "free_input_hints": ["study", "work", "rest", "alice", "recover"],
            "intent_module": {
                "author_input": author_input,
                "intent_tags": ["scene_refine", "choice_contrast"],
                "parse_notes": "Strengthened question + hints to improve free-input mapping quality.",
                "aliases": ["scene", "choice"],
            },
        }
        suggestions = {"flow": {"scene_patch": scene_patch}}
        patch_preview = [
            _patch("flow.scenes[current].dramatic_question", "Refine dramatic question", scene_patch["dramatic_question"]),
            _patch("flow.scenes[current].free_input_hints", "Refine free-input hints", scene_patch["free_input_hints"]),
            _patch("flow.scenes[current].intent_module", "Refresh scene intent notes", scene_patch["intent_module"]),
        ]
        return suggestions, patch_preview, ["Patch paths use [current]; UI should map to selected scene index."]

    if layer == "action":
        suggestions = {
            "action": {
                "input_mapping_policy": "intent_alias_only_visible_choice",
                "intent_module": {
                    "author_input": author_input,
                    "intent_tags": ["action_refine", "mapping_policy"],
                    "parse_notes": "Mapping policy locked to avoid free-input bypassing choice gates.",
                    "aliases": ["action", "intent", "mapping"],
                },
            }
        }
        patch_preview = [
            _patch("action.input_mapping_policy", "Set mapping policy", suggestions["action"]["input_mapping_policy"]),
            _patch("action.intent_module", "Refresh action intent notes", suggestions["action"]["intent_module"]),
        ]
        return suggestions, patch_preview, []

    if layer == "consequence":
        suggestions = {
            "consequence": {
                "state_axes": ["energy", "money", "knowledge", "affection", "day", "slot"],
                "intent_module": {
                    "author_input": author_input,
                    "intent_tags": ["consequence_refine", "state_clarity"],
                    "parse_notes": "State axes were normalized for predictable narrative summaries.",
                    "aliases": ["state", "effects", "quest"],
                },
            }
        }
        patch_preview = [
            _patch("consequence.state_axes", "Normalize consequence state axes", suggestions["consequence"]["state_axes"]),
            _patch("consequence.intent_module", "Refresh consequence intent notes", suggestions["consequence"]["intent_module"]),
        ]
        return suggestions, patch_preview, []

    if layer == "ending":
        ending_rules = [
            {
                "ending_key": "tired_but_intact",
                "title": "Tired but Intact",
                "priority": 120,
                "outcome": "neutral",
                "trigger": {"day_at_least": 5, "energy_at_most": 25},
                "epilogue": "You made it through the week, but the cost still sits in your bones.",
            }
        ]
        suggestions = {
            "ending": {
                "ending_rules": ending_rules,
                "intent_module": {
                    "author_input": author_input,
                    "intent_tags": ["ending_refine", "outcome_balance"],
                    "parse_notes": "Added a neutral fallback ending to avoid binary finish states.",
                    "aliases": ["ending", "outcome"],
                },
            }
        }
        patch_preview = [
            _patch("ending.ending_rules", "Add a neutral ending rule", ending_rules),
            _patch("ending.intent_module", "Refresh ending intent notes", suggestions["ending"]["intent_module"]),
        ]
        return suggestions, patch_preview, []

    if layer == "systems":
        suggestions = {
            "systems": {
                "fallback_style": {"tone": "supportive", "action_type": "rest"},
                "intent_module": {
                    "author_input": author_input,
                    "intent_tags": ["systems_refine", "fallback_tone"],
                    "parse_notes": "Supportive fallback prevents reject-tone responses on free input misses.",
                    "aliases": ["fallback", "system"],
                },
            }
        }
        patch_preview = [
            _patch("systems.fallback_style", "Refine fallback style", suggestions["systems"]["fallback_style"]),
            _patch("systems.intent_module", "Refresh systems intent notes", suggestions["systems"]["intent_module"]),
        ]
        return suggestions, patch_preview, []

    suggestions = {
        "world": {
            "boundaries": "Keep consequences grounded in schedule pressure and limited personal bandwidth.",
            "intent_module": {
                "author_input": author_input,
                "intent_tags": ["world_refine", "consistency"],
                "parse_notes": "World constraints tightened to improve causal coherence.",
                "aliases": ["world", "rules"],
            },
        }
    }
    patch_preview = [
        _patch("world.boundaries", "Refine world boundaries", suggestions["world"]["boundaries"]),
        _patch("world.intent_module", "Refresh world intent notes", suggestions["world"]["intent_module"]),
    ]
    return suggestions, patch_preview, []


def _deterministic_scene_options(context: dict) -> tuple[dict, list[dict], list[str]]:
    scene_title = _clean_text(context.get("scene_title"), fallback="Current Scene")
    next_scene_key = _slugify(context.get("next_scene_key"), fallback="next_scene")
    options = [
        {
            "option_key": "focus_study",
            "label": f"Push for progress in {scene_title}",
            "intent_aliases": ["study", "focus", "class", "library"],
            "action_type": "study",
            "go_to": next_scene_key,
            "is_key_decision": False,
        },
        {
            "option_key": "take_shift",
            "label": "Pick up a short paid shift",
            "intent_aliases": ["work", "job", "money", "shift"],
            "action_type": "work",
            "go_to": next_scene_key,
            "is_key_decision": False,
        },
        {
            "option_key": "recover_window",
            "label": "Pause and recover before the next beat",
            "intent_aliases": ["rest", "recover", "pause", "break"],
            "action_type": "rest",
            "go_to": next_scene_key,
            "is_key_decision": False,
        },
    ]
    suggestions = {"flow": {"scene_options": options}}
    patch_preview = [
        _patch("flow.scenes[current].options", "Replace current scene options with 3 balanced options", options),
    ]
    warnings = ["Patch paths use [current]; UI should map to selected scene index."]
    return suggestions, patch_preview, warnings


def _deterministic_intent_aliases(context: dict) -> tuple[dict, list[dict], list[str]]:
    label = _clean_text(context.get("option_label"), fallback="Take action")
    action_type = _clean_text(context.get("action_type"), fallback="rest").lower()
    base = _extract_keywords(label, limit=4)
    action_defaults = {
        "study": ["study", "class", "learn"],
        "work": ["work", "job", "money"],
        "rest": ["rest", "recover", "pause"],
        "date": ["date", "meet", "talk"],
        "gift": ["gift", "present", "flowers"],
    }
    aliases = []
    seen: set[str] = set()
    for token in base + action_defaults.get(action_type, ["action", "move"]):
        normalized = token.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(normalized)
        if len(aliases) >= 6:
            break

    suggestions = {"intent_aliases": aliases}
    patch_preview = [
        _patch("flow.scenes[current].options[current].intent_aliases", "Set intent aliases for current option", aliases),
    ]
    warnings = ["Patch paths use [current]; UI should map to selected scene/option indices."]
    return suggestions, patch_preview, warnings


def _deterministic_consistency_check(context: dict) -> tuple[dict, list[dict], list[str]]:
    draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
    if not draft and isinstance(context.get("story"), dict):
        draft = context.get("story")

    flow = draft.get("flow") if isinstance(draft.get("flow"), dict) else {}
    scenes = flow.get("scenes") if isinstance(flow.get("scenes"), list) else []
    start_scene_key = str(flow.get("start_scene_key") or "").strip()
    scene_keys = [str(item.get("scene_key") or "").strip() for item in scenes if isinstance(item, dict)]

    warnings: list[str] = []
    patches: list[dict] = []

    if scenes and (not start_scene_key or start_scene_key not in scene_keys):
        fallback_start = next((key for key in scene_keys if key), "scene_intro")
        patches.append(_patch("flow.start_scene_key", "Repair missing or invalid start_scene_key", fallback_start))
        warnings.append("start_scene_key was missing or invalid; suggested a deterministic repair.")

    for idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        options = scene.get("options") if isinstance(scene.get("options"), list) else []
        is_end = bool(scene.get("is_end", False))
        if not is_end and not (2 <= len(options) <= 4):
            warnings.append(
                f"flow.scenes[{idx}] should keep 2-4 options for non-end scene readability (current={len(options)})."
            )

    ending = draft.get("ending") if isinstance(draft.get("ending"), dict) else {}
    ending_rules = ending.get("ending_rules") if isinstance(ending.get("ending_rules"), list) else []
    if not ending_rules:
        default_ending = {
            "ending_key": "default_week_close",
            "title": "Week Close",
            "priority": 150,
            "outcome": "neutral",
            "trigger": {"day_at_least": 5},
            "epilogue": "The week closes with unfinished threads and one clear next step.",
        }
        patches.append(_patch("ending.ending_rules", "Seed at least one ending rule", [default_ending]))
        warnings.append("No ending rules detected; suggested a neutral default ending.")

    suggestions = {
        "consistency": {
            "status": "review",
            "issues_found": len(warnings),
        }
    }
    return suggestions, patches, warnings


def _default_playability_policy() -> dict:
    return {
        "ending_reach_rate_min": 0.6,
        "stuck_turn_rate_max": 0.05,
        "no_progress_rate_max": 0.25,
        "branch_coverage_warn_below": 0.3,
        "rollout_strategies": 3,
        "rollout_runs_per_strategy": 80,
    }


def _writer_turn(*, phase: str, author_text: str, assistant_text: str, accepted_patch_ids: list[str] | None = None) -> dict:
    return {
        "turn_id": f"turn_{_slugify(author_text or phase, fallback=phase)}",
        "phase": phase,
        "author_text": _clean_text(author_text),
        "assistant_text": _clean_text(assistant_text),
        "accepted_patch_ids": list(accepted_patch_ids or []),
        "created_at": None,
    }


def _deterministic_story_ingest(locale: str, context: dict) -> tuple[dict, list[dict], list[str]]:
    base_context = dict(context or {})
    source_text = _clean_text(base_context.get("source_text") or base_context.get("global_brief") or base_context.get("brief"))
    suggestions, patch_preview, warnings = _deterministic_layer_bootstrap(locale, base_context)
    suggestions["format_version"] = 4
    suggestions["entry_mode"] = "ingest"
    suggestions["source_text"] = source_text
    suggestions["writer_journal"] = [
        _writer_turn(
            phase="seed",
            author_text=source_text or "Imported source text.",
            assistant_text="Parsed into layered RPG draft with a runnable scene graph scaffold.",
        )
    ]
    suggestions["playability_policy"] = _default_playability_policy()

    patch_preview = [
        _patch("format_version", "Lock author format to ASF v4", 4),
        _patch("entry_mode", "Set entry mode to ingest", "ingest"),
        _patch("source_text", "Keep imported source text for traceability", source_text),
        *_patches_with_unique_ids(patch_preview),
        _patch("writer_journal", "Seed writer journal from ingest pass", suggestions["writer_journal"]),
        _patch("playability_policy", "Apply default playability policy", suggestions["playability_policy"]),
    ]
    warnings.append("Ingest suggestions are editable; patch application strategy is controlled by the UI.")
    return suggestions, patch_preview, warnings


def _deterministic_seed_expand(locale: str, context: dict) -> tuple[dict, list[dict], list[str]]:
    base_context = dict(context or {})
    seed_text = _clean_text(base_context.get("seed_text") or base_context.get("global_brief") or base_context.get("brief"))
    suggestions, patch_preview, warnings = _deterministic_layer_bootstrap(locale, base_context)
    suggestions["format_version"] = 4
    suggestions["entry_mode"] = "spark"
    suggestions["source_text"] = None
    suggestions["writer_journal"] = [
        _writer_turn(
            phase="expand",
            author_text=seed_text or "Spark seed.",
            assistant_text="Expanded into world, conflict, and a two-beat playable skeleton.",
        )
    ]
    suggestions["playability_policy"] = _default_playability_policy()
    patch_preview = [
        _patch("format_version", "Lock author format to ASF v4", 4),
        _patch("entry_mode", "Set entry mode to spark", "spark"),
        *_patches_with_unique_ids(patch_preview),
        _patch("writer_journal", "Append expansion turn in writer journal", suggestions["writer_journal"]),
        _patch("playability_policy", "Apply default playability policy", suggestions["playability_policy"]),
    ]
    return suggestions, patch_preview, warnings


def _patches_with_unique_ids(patches: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for idx, patch in enumerate(patches or []):
        candidate = dict(patch or {})
        patch_id = str(candidate.get("id") or f"patch_{idx}")
        if patch_id in seen:
            patch_id = f"{patch_id}_{idx + 1}"
        seen.add(patch_id)
        candidate["id"] = patch_id
        out.append(candidate)
    return out


def _deterministic_scene_deepen(context: dict) -> tuple[dict, list[dict], list[str]]:
    refine_context = dict(context or {})
    layer = _clean_text(refine_context.get("layer"), fallback="flow").lower()
    if layer in {"world", "characters", "plot", "flow", "scene"}:
        return _deterministic_layer_refine({"layer": layer, **refine_context})
    return _deterministic_layer_refine({"layer": "flow", **refine_context})


def _deterministic_option_weave(context: dict) -> tuple[dict, list[dict], list[str]]:
    aliases, alias_patches, warnings = _deterministic_intent_aliases(context)
    scene_key = _clean_text(context.get("scene_key"), fallback="scene_intro")
    next_scene_key = _clean_text(context.get("next_scene_key"), fallback=scene_key)
    option_patch = _patch(
        "flow.scenes[current].options[current].go_to",
        "Set deterministic go_to for woven option",
        next_scene_key,
    )
    suggestions = {
        "option_weave": {
            "intent_aliases": aliases.get("intent_aliases") if isinstance(aliases, dict) else [],
            "go_to": next_scene_key,
        }
    }
    return suggestions, [*alias_patches, option_patch], warnings


def _deterministic_consequence_balance(context: dict) -> tuple[dict, list[dict], list[str]]:
    refine_suggestions, refine_patches, warnings = _deterministic_layer_refine({"layer": "consequence", **context})
    balance_patch = _patch(
        "consequence.state_axes",
        "Keep baseline playable state axes",
        ["energy", "money", "knowledge", "affection", "day", "slot"],
    )
    warnings = [*warnings, "Balance suggestions are conservative; tune effects after playability validation."]
    return refine_suggestions, [*refine_patches, balance_patch], warnings


def _deterministic_ending_design(context: dict) -> tuple[dict, list[dict], list[str]]:
    return _deterministic_layer_refine({"layer": "ending", **context})


def _deterministic_assist(task: AuthorAssistTask, locale: str, context: dict) -> dict:
    if task == "story_ingest":
        suggestions, patch_preview, warnings = _deterministic_story_ingest(locale, context)
    elif task == "seed_expand":
        suggestions, patch_preview, warnings = _deterministic_seed_expand(locale, context)
    elif task == "beat_to_scene":
        suggestions, patch_preview, warnings = _deterministic_scene_options(context)
    elif task == "scene_deepen":
        suggestions, patch_preview, warnings = _deterministic_scene_deepen(context)
    elif task == "option_weave":
        suggestions, patch_preview, warnings = _deterministic_option_weave(context)
    elif task == "consequence_balance":
        suggestions, patch_preview, warnings = _deterministic_consequence_balance(context)
    elif task == "ending_design":
        suggestions, patch_preview, warnings = _deterministic_ending_design(context)
    else:
        suggestions, patch_preview, warnings = _deterministic_consistency_check(context)
    return {
        "suggestions": suggestions,
        "patch_preview": patch_preview,
        "warnings": warnings,
        "provider": "deterministic_fallback",
        "model": "heuristic-v2",
    }


def _coerce_assist_payload(raw: object) -> dict | None:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
    elif isinstance(raw, dict):
        parsed = raw
    else:
        return None

    suggestions = parsed.get("suggestions") if isinstance(parsed.get("suggestions"), dict) else None
    patch_preview = parsed.get("patch_preview") if isinstance(parsed.get("patch_preview"), list) else None
    warnings = parsed.get("warnings") if isinstance(parsed.get("warnings"), list) else []
    if suggestions is None or patch_preview is None:
        return None
    return {
        "suggestions": suggestions,
        "patch_preview": patch_preview,
        "warnings": [str(item) for item in warnings],
    }


def author_assist_suggestions(
    *,
    db: Session,
    task: AuthorAssistTask,
    locale: str,
    context: dict,
) -> dict:
    runtime = get_llm_runtime()
    prompt = build_author_assist_prompt(task=task, locale=locale, context=context)
    fallback_warning: str | None = None
    try:
        out, _ = runtime.narrative_with_fallback(
            db,
            prompt=prompt,
            session_id=None,
            step_id=uuid.uuid4(),
        )
        parsed = _coerce_assist_payload(out.narrative_text)
        if parsed:
            parsed["provider"] = str(settings.llm_provider_primary)
            parsed["model"] = str(settings.llm_model_generate)
            return parsed
        fallback_warning = "LLM assist output was not valid JSON; served deterministic suggestions."
    except LLMUnavailableError:
        fallback_warning = "LLM assist unavailable; served deterministic suggestions."
    except Exception as exc:  # noqa: BLE001
        fallback_warning = f"LLM assist failed ({type(exc).__name__}); served deterministic suggestions."

    fallback_payload = _deterministic_assist(task, locale, context)
    if fallback_warning:
        warnings = list(fallback_payload.get("warnings") or [])
        warnings.append(fallback_warning)
        fallback_payload["warnings"] = warnings
    return fallback_payload
