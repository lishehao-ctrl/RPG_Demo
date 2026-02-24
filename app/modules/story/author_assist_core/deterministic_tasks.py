from __future__ import annotations

import re
from copy import deepcopy

from .types import ASSIST_ACTION_TYPES, AuthorAssistTask

_WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9'_-]*")
_CJK_SEGMENT_RE = re.compile(r"[\u4e00-\u9fff]{2,8}")
_GENERIC_LABEL_RE = re.compile(r"^(option(\s+[a-z0-9]+)?|take action|continue|next)$", re.IGNORECASE)
_ASSIST_ACTION_TYPES = ASSIST_ACTION_TYPES
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


def _dedupe_text_items(values: list[object], *, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        text = _clean_text(item, fallback="")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _is_generic_option_label(label: str) -> bool:
    text = _clean_text(label, fallback="")
    if not text:
        return True
    return bool(_GENERIC_LABEL_RE.match(text))


def _patch(path: str, label: str, value: object) -> dict:
    return {
        "id": _slugify(path, fallback="patch"),
        "path": path,
        "label": label,
        "value": value,
    }


def _scene_list_from_context(context: dict) -> list[dict]:
    draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
    flow = draft.get("flow") if isinstance(draft.get("flow"), dict) else {}
    scenes = flow.get("scenes") if isinstance(flow.get("scenes"), list) else []
    return [deepcopy(item) for item in scenes if isinstance(item, dict)]


def _scene_key_set(scenes: list[dict]) -> set[str]:
    out: set[str] = set()
    for scene in scenes:
        key = _clean_text(scene.get("scene_key"), fallback="").lower()
        if key:
            out.add(key)
    return out


def _ensure_unique_scene_key(base_key: str, scenes: list[dict]) -> str:
    used = _scene_key_set(scenes)
    candidate = _slugify(base_key, fallback="scene_new")
    if candidate not in used:
        return candidate
    idx = 2
    while f"{candidate}_{idx}" in used:
        idx += 1
    return f"{candidate}_{idx}"


def _find_scene_index(scenes: list[dict], scene_key: str | None) -> int:
    target = _clean_text(scene_key, fallback="").lower()
    if target:
        for idx, scene in enumerate(scenes):
            key = _clean_text(scene.get("scene_key"), fallback="").lower()
            if key == target:
                return idx
    return 0 if scenes else -1


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
        "choice_contrast_warn_below": 0.45,
        "dominant_strategy_warn_above": 0.75,
        "recovery_window_warn_below": 0.55,
        "tension_loop_warn_below": 0.50,
        "dominant_strategy_block_above": 0.90,
        "low_branch_with_dominant_block_below": 0.20,
        "recovery_window_block_below": 0.25,
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


def _deterministic_continue_write(context: dict) -> tuple[dict, list[dict], list[str]]:
    scenes = _scene_list_from_context(context)
    warnings: list[str] = []
    if not scenes:
        scenes = _bootstrap_scenes()
        warnings.append("Draft had no scenes; seeded baseline scenes before appending.")

    target_scene_key = context.get("target_scene_key") or context.get("scene_key")
    target_index = _find_scene_index(scenes, target_scene_key)
    if target_index < 0:
        target_index = 0
    target_scene = scenes[target_index]
    target_key = _clean_text(target_scene.get("scene_key"), fallback=f"scene_{target_index + 1}")
    followup_key = _ensure_unique_scene_key(f"{target_key}_followup", scenes)

    target_options = target_scene.get("options") if isinstance(target_scene.get("options"), list) else []
    target_next_hint = ""
    for option in target_options:
        next_key = _clean_text(option.get("go_to"), fallback="")
        if next_key:
            target_next_hint = next_key
            break
    if not target_next_hint:
        target_next_hint = _clean_text(context.get("next_scene_key"), fallback="")
    if not target_next_hint:
        target_next_hint = followup_key

    if target_options:
        target_options[0]["go_to"] = followup_key

    followup_scene = {
        "scene_key": followup_key,
        "title": "Follow-up Beat",
        "setup": "The story escalates after your latest decision and forces a sharper trade-off.",
        "dramatic_question": "Do you push through pressure now or secure recovery first?",
        "free_input_hints": ["push", "recover", "reset", "advance"],
        "is_end": False,
        "fallback": None,
        "intent_module": {
            "author_input": _clean_text(context.get("continue_input"), fallback="Continue writing after the last decision."),
            "intent_tags": ["continue_write", "followup"],
            "parse_notes": "Appended one playable follow-up scene and rewired an upstream option.",
            "aliases": ["continue", "followup", "next beat"],
        },
        "options": [
            {
                "option_key": "push_forward",
                "label": "Push through the pressure and advance",
                "intent_aliases": ["push", "advance", "focus", "commit"],
                "action_type": "study",
                "go_to": target_next_hint,
                "effects": {"energy": -12, "knowledge": 3},
                "requirements": {},
                "is_key_decision": True,
            },
            {
                "option_key": "stabilize",
                "label": "Stabilize first, then continue",
                "intent_aliases": ["recover", "stabilize", "rest", "reset"],
                "action_type": "rest",
                "go_to": target_next_hint,
                "effects": {"energy": 16},
                "requirements": {},
                "is_key_decision": False,
            },
        ],
    }

    scenes.insert(target_index + 1, followup_scene)

    draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
    plot = draft.get("plot") if isinstance(draft.get("plot"), dict) else {}
    acts = deepcopy(plot.get("mainline_acts")) if isinstance(plot.get("mainline_acts"), list) else []
    linked = False
    for act in acts:
        if not isinstance(act, dict):
            continue
        keys = act.get("scene_keys") if isinstance(act.get("scene_keys"), list) else []
        normalized_keys = [_clean_text(item, fallback="") for item in keys if _clean_text(item, fallback="")]
        if target_key in normalized_keys:
            insert_idx = normalized_keys.index(target_key) + 1
            normalized_keys.insert(insert_idx, followup_key)
            act["scene_keys"] = normalized_keys
            linked = True
            break
    if acts and not linked:
        last_keys = acts[-1].get("scene_keys") if isinstance(acts[-1].get("scene_keys"), list) else []
        acts[-1]["scene_keys"] = [_clean_text(item, fallback="") for item in last_keys if _clean_text(item, fallback="")]
        acts[-1]["scene_keys"].append(followup_key)
        linked = True

    suggestions = {
        "continue_write": {
            "target_scene_key": target_key,
            "appended_scene_key": followup_key,
            "operation": "append",
            "preserve_existing": bool(context.get("preserve_existing", True)),
        }
    }
    patch_preview = [
        _patch("flow.scenes", "Append one follow-up scene and wire upstream go_to", scenes),
    ]
    if linked:
        patch_preview.append(_patch("plot.mainline_acts", "Append new scene key to matching act", acts))
    return suggestions, patch_preview, warnings


def _deterministic_trim_content(context: dict) -> tuple[dict, list[dict], list[str]]:
    scenes = _scene_list_from_context(context)
    if not scenes:
        return (
            {"trim_content": {"status": "noop", "reason": "no scenes"}},
            [],
            ["No scenes available to trim."],
        )

    target_scope = _clean_text(context.get("target_scope"), fallback="scene").lower()
    target_scene_key = context.get("target_scene_key") or context.get("scene_key")
    target_scene_index = _find_scene_index(scenes, target_scene_key)
    if target_scene_index < 0:
        target_scene_index = 0
    warnings: list[str] = [
        "Destructive trim patch generated; review in Debug before applying.",
    ]
    patch_preview: list[dict] = []
    suggestions: dict = {
        "trim_content": {
            "target_scope": target_scope,
            "operation": "trim",
        }
    }

    if target_scope == "option":
        scene = scenes[target_scene_index]
        options = scene.get("options") if isinstance(scene.get("options"), list) else []
        if not options:
            warnings.append("Target scene has no options; no trim patch produced.")
            return suggestions, patch_preview, warnings

        target_option_key = _clean_text(context.get("target_option_key"), fallback="")
        option_index = 0
        if target_option_key:
            for idx, option in enumerate(options):
                if _clean_text(option.get("option_key"), fallback="").lower() == target_option_key.lower():
                    option_index = idx
                    break
        removed_option = options.pop(option_index)
        suggestions["trim_content"]["removed_option_key"] = _clean_text(removed_option.get("option_key"), fallback="option")

        scene_is_end = bool(scene.get("is_end"))
        if not scene_is_end:
            while len(options) < 2:
                options.append(
                    {
                        "option_key": _ensure_unique_scene_key("recovery_patch", [{"scene_key": o.get("option_key", "")} for o in options]),
                        "label": "Take a small recovery beat",
                        "intent_aliases": ["rest", "recover", "reset"],
                        "action_type": "rest",
                        "go_to": _clean_text(context.get("next_scene_key"), fallback=_clean_text(scene.get("scene_key"), fallback="scene_next")),
                        "effects": {"energy": 10},
                        "requirements": {},
                        "is_key_decision": False,
                    }
                )
            for option in options:
                if not _clean_text(option.get("go_to"), fallback=""):
                    option["go_to"] = _clean_text(context.get("next_scene_key"), fallback=_clean_text(scene.get("scene_key"), fallback="scene_next"))

        scene["options"] = options[:4]
        patch_preview.append(_patch("flow.scenes", "Trim target option and repair scene option count", scenes))
        return suggestions, patch_preview, warnings

    if len(scenes) == 1:
        warnings.append("Only one scene exists; skipping scene trim to keep draft playable.")
        return suggestions, patch_preview, warnings

    removed_scene = scenes.pop(target_scene_index)
    removed_scene_key = _clean_text(removed_scene.get("scene_key"), fallback="")
    suggestions["trim_content"]["removed_scene_key"] = removed_scene_key
    fallback_scene_key = _clean_text(scenes[min(target_scene_index, len(scenes) - 1)].get("scene_key"), fallback="")

    for scene in scenes:
        options = scene.get("options") if isinstance(scene.get("options"), list) else []
        for option in options:
            if _clean_text(option.get("go_to"), fallback="").lower() == removed_scene_key.lower():
                option["go_to"] = fallback_scene_key

    if not any(bool(scene.get("is_end")) for scene in scenes):
        scenes[-1]["is_end"] = True

    draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
    flow = draft.get("flow") if isinstance(draft.get("flow"), dict) else {}
    start_scene_key = _clean_text(flow.get("start_scene_key"), fallback="")
    if not start_scene_key or start_scene_key.lower() == removed_scene_key.lower():
        start_scene_key = fallback_scene_key

    plot = draft.get("plot") if isinstance(draft.get("plot"), dict) else {}
    acts = deepcopy(plot.get("mainline_acts")) if isinstance(plot.get("mainline_acts"), list) else []
    for act in acts:
        if not isinstance(act, dict):
            continue
        keys = act.get("scene_keys") if isinstance(act.get("scene_keys"), list) else []
        cleaned = [_clean_text(item, fallback="") for item in keys if _clean_text(item, fallback="")]
        act["scene_keys"] = [item for item in cleaned if item.lower() != removed_scene_key.lower()]

    patch_preview.extend(
        [
            _patch("flow.scenes", "Trim target scene and repair references", scenes),
            _patch("flow.start_scene_key", "Repair start scene after trim", start_scene_key),
            _patch("plot.mainline_acts", "Prune removed scene from act mappings", acts),
        ]
    )
    return suggestions, patch_preview, warnings


def _deterministic_spice_branch(context: dict) -> tuple[dict, list[dict], list[str]]:
    scenes = _scene_list_from_context(context)
    if not scenes:
        return (
            {"spice_branch": {"status": "noop", "reason": "no scenes"}},
            [],
            ["No scenes available to spice."],
        )
    target_scene_index = _find_scene_index(scenes, context.get("target_scene_key") or context.get("scene_key"))
    if target_scene_index < 0:
        target_scene_index = 0
    scene = scenes[target_scene_index]
    options = scene.get("options") if isinstance(scene.get("options"), list) else []
    scene_key = _clean_text(scene.get("scene_key"), fallback=f"scene_{target_scene_index + 1}")
    next_key = _clean_text(context.get("next_scene_key"), fallback=scene_key)
    is_end = bool(scene.get("is_end"))

    def _is_recovery(option: dict) -> bool:
        action_type = _clean_text(option.get("action_type"), fallback="")
        if action_type == "rest":
            return True
        effect = option.get("effects") if isinstance(option.get("effects"), dict) else {}
        return int(effect.get("energy", 0)) > 0

    def _is_pressure(option: dict) -> bool:
        action_type = _clean_text(option.get("action_type"), fallback="")
        if action_type in {"study", "work", "gift", "date"}:
            return True
        effect = option.get("effects") if isinstance(option.get("effects"), dict) else {}
        return int(effect.get("energy", 0)) < 0

    has_pressure = any(_is_pressure(option) for option in options)
    has_recovery = any(_is_recovery(option) for option in options)

    if not has_pressure:
        options.append(
            {
                "option_key": "pressure_path",
                "label": "Take the high-pressure push",
                "intent_aliases": ["push", "risk", "rush", "commit"],
                "action_type": "work",
                "go_to": next_key if not is_end else "",
                "effects": {"energy": -14, "money": 18},
                "requirements": {},
                "is_key_decision": True,
            }
        )
    if not has_recovery:
        options.append(
            {
                "option_key": "recovery_path",
                "label": "Stabilize before the next push",
                "intent_aliases": ["recover", "rest", "reset"],
                "action_type": "rest",
                "go_to": next_key if not is_end else "",
                "effects": {"energy": 14},
                "requirements": {},
                "is_key_decision": False,
            }
        )

    if not is_end:
        while len(options) < 2:
            options.append(
                {
                    "option_key": "fallback_choice",
                    "label": "Take a steady move",
                    "intent_aliases": ["steady", "move"],
                    "action_type": "study",
                    "go_to": next_key,
                    "effects": {"knowledge": 1, "energy": -6},
                    "requirements": {},
                    "is_key_decision": False,
                }
            )
        for option in options:
            if not _clean_text(option.get("go_to"), fallback=""):
                option["go_to"] = next_key
    options = options[:4]
    scene["options"] = options

    suggestions = {
        "spice_branch": {
            "scene_key": scene_key,
            "option_count": len(options),
            "pressure_present": any(_is_pressure(option) for option in options),
            "recovery_present": any(_is_recovery(option) for option in options),
        }
    }
    patch_preview = [
        _patch("flow.scenes[current].options", "Spice current branch with pressure/recovery contrast", options),
    ]
    warnings = ["Patch paths use [current]; UI should map to selected scene index."]
    return suggestions, patch_preview, warnings


def _deterministic_tension_rebalance(context: dict) -> tuple[dict, list[dict], list[str]]:
    scenes = _scene_list_from_context(context)
    if not scenes:
        return (
            {"tension_rebalance": {"status": "noop", "reason": "no scenes"}},
            [],
            ["No scenes available to rebalance."],
        )

    warnings: list[str] = []
    changed = False
    recovery_added = 0
    for scene in scenes:
        is_end = bool(scene.get("is_end"))
        options = scene.get("options") if isinstance(scene.get("options"), list) else []
        scene_key = _clean_text(scene.get("scene_key"), fallback="scene_next")
        next_key = _clean_text(context.get("next_scene_key"), fallback=scene_key)
        has_recovery = False

        for option in options:
            effects = option.get("effects") if isinstance(option.get("effects"), dict) else {}
            for key in ("energy", "money", "knowledge", "affection"):
                raw = effects.get(key)
                if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    continue
                clamped = max(-30, min(int(raw), 30))
                if clamped != int(raw):
                    effects[key] = clamped
                    changed = True
            if effects:
                option["effects"] = effects

            requirements = option.get("requirements") if isinstance(option.get("requirements"), dict) else {}
            for key, high in (("min_energy", 90), ("min_money", 250), ("min_affection", 90), ("day_at_least", 14)):
                raw = requirements.get(key)
                if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    continue
                clamped = max(0 if key != "day_at_least" else 1, min(int(raw), high))
                if clamped != int(raw):
                    requirements[key] = clamped
                    changed = True
            if requirements:
                option["requirements"] = requirements

            action_type = _clean_text(option.get("action_type"), fallback="")
            if action_type == "rest" or int((effects or {}).get("energy", 0)) > 0:
                has_recovery = True
            if not is_end and not _clean_text(option.get("go_to"), fallback=""):
                option["go_to"] = next_key
                changed = True

        if not is_end and not has_recovery:
            if len(options) < 4:
                options.append(
                    {
                        "option_key": "rebalance_recovery",
                        "label": "Take a recovery window",
                        "intent_aliases": ["recover", "rest", "stabilize"],
                        "action_type": "rest",
                        "go_to": next_key,
                        "effects": {"energy": 12},
                        "requirements": {},
                        "is_key_decision": False,
                    }
                )
                recovery_added += 1
                changed = True
            elif options:
                options[-1]["action_type"] = "rest"
                options[-1]["effects"] = {"energy": 10}
                recovery_added += 1
                changed = True
        scene["options"] = options[:4]

    if changed:
        warnings.append("Rebalance patches normalized extreme values and recovery coverage.")
    suggestions = {
        "tension_rebalance": {
            "scenes_touched": len(scenes),
            "recovery_paths_added": recovery_added,
        }
    }
    patch_preview = [
        _patch("flow.scenes", "Rebalance tension loops, effects, and recovery windows", scenes),
    ]
    return suggestions, patch_preview, warnings


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
    elif task == "continue_write":
        suggestions, patch_preview, warnings = _deterministic_continue_write(context)
    elif task == "trim_content":
        suggestions, patch_preview, warnings = _deterministic_trim_content(context)
    elif task == "spice_branch":
        suggestions, patch_preview, warnings = _deterministic_spice_branch(context)
    elif task == "tension_rebalance":
        suggestions, patch_preview, warnings = _deterministic_tension_rebalance(context)
    else:
        suggestions, patch_preview, warnings = _deterministic_consistency_check(context)
    return {
        "suggestions": suggestions,
        "patch_preview": patch_preview,
        "warnings": warnings,
        "model": "heuristic-v2",
    }

