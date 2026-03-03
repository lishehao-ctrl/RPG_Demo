from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rpg_backend.domain.constants import (
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
)

StrategyStyle = Literal[
    "fast_dirty",
    "steady_slow",
    "political_safe_resource_heavy",
]


@dataclass(frozen=True)
class MoveTemplate:
    id: str
    label_template: str
    intent_patterns: tuple[str, ...]
    synonym_bank: tuple[str, ...]
    args_schema: dict[str, object]
    resolution_policy: Literal["prefer_success", "prefer_partial", "always_fail_forward"]
    outcome_palette_ids: dict[str, tuple[str, ...]]
    tags: tuple[str, ...]


def _palette_map(success: tuple[str, ...], partial: tuple[str, ...], fail_forward: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    return {
        "success": success,
        "partial": partial,
        "fail_forward": fail_forward,
    }


MOVE_LIBRARY: tuple[MoveTemplate, ...] = (
    MoveTemplate(
        id=GLOBAL_CLARIFY_MOVE_ID,
        label_template="Clarify Intent",
        intent_patterns=("clarify", "explain my plan", "what should I do"),
        synonym_bank=("explain", "clarify", "unclear", "ask"),
        args_schema={"tone": {"type": "string", "enum": ["calm", "urgent", "firm"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_diplomatic", "succ_discovery"),
            ("part_tradeoff", "part_delay"),
            ("fail_pressure", "fail_complication"),
        ),
        tags=("global", "social"),
    ),
    MoveTemplate(
        id=GLOBAL_LOOK_MOVE_ID,
        label_template="Survey Scene",
        intent_patterns=("look around", "scan the area", "observe"),
        synonym_bank=("look", "inspect", "scan", "watch"),
        args_schema={"goal_tag": {"type": "string", "enum": ["clue", "threat", "route"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_discovery", "succ_technical"),
            ("part_delay", "part_noisy"),
            ("fail_misread", "fail_detour"),
        ),
        tags=("global", "investigate"),
    ),
    MoveTemplate(
        id=GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
        label_template="Help Me Progress",
        intent_patterns=("help me progress", "i am stuck", "guide me"),
        synonym_bank=("help", "stuck", "next step", "progress"),
        args_schema={"tone": {"type": "string", "enum": ["direct", "supportive"]}},
        resolution_policy="always_fail_forward",
        outcome_palette_ids=_palette_map(
            ("succ_diplomatic", "succ_discovery"),
            ("part_tradeoff", "part_costly"),
            ("fail_pressure", "fail_detour"),
        ),
        tags=("global", "support"),
    ),
    MoveTemplate(
        id="scan_signal",
        label_template="Trace The Signal",
        intent_patterns=("trace signal", "locate source", "ping relay"),
        synonym_bank=("signal", "trace", "relay", "frequency"),
        args_schema={
            "target_npc": {"type": "string"},
            "goal_tag": {"type": "string", "enum": ["source", "shortcut", "risk"]},
        },
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_discovery", "succ_technical"),
            ("part_noisy", "part_tradeoff"),
            ("fail_misread", "fail_complication"),
        ),
        tags=("investigate", "technical"),
    ),
    MoveTemplate(
        id="convince_guard",
        label_template="Negotiate Passage",
        intent_patterns=("convince guard", "talk them down", "negotiate"),
        synonym_bank=("convince", "negotiate", "persuade", "bargain"),
        args_schema={
            "target_npc": {"type": "string"},
            "tone": {"type": "string", "enum": ["soft", "firm", "blunt"]},
        },
        resolution_policy="prefer_partial",
        outcome_palette_ids=_palette_map(
            ("succ_diplomatic", "succ_bold"),
            ("part_tradeoff", "part_costly"),
            ("fail_complication", "fail_sacrifice"),
        ),
        tags=("social", "support"),
    ),
    MoveTemplate(
        id="sneak_route",
        label_template="Slip Through Side Route",
        intent_patterns=("sneak through", "take side route", "move quietly"),
        synonym_bank=("sneak", "quiet", "route", "bypass"),
        args_schema={
            "goal_tag": {"type": "string", "enum": ["stealth", "speed"]},
            "tone": {"type": "string", "enum": ["careful", "aggressive"]},
        },
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_stealth", "succ_bold"),
            ("part_noisy", "part_delay"),
            ("fail_pressure", "fail_detour"),
        ),
        tags=("stealth", "mobility"),
    ),
    MoveTemplate(
        id="decode_core",
        label_template="Decode Control Pattern",
        intent_patterns=("decode core", "parse code", "read control pattern"),
        synonym_bank=("decode", "pattern", "code", "protocol"),
        args_schema={
            "goal_tag": {"type": "string", "enum": ["stabilize", "unlock", "diagnose"]},
            "target_npc": {"type": "string"},
        },
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_technical", "succ_discovery"),
            ("part_delay", "part_costly"),
            ("fail_misread", "fail_pressure"),
        ),
        tags=("technical", "investigate"),
    ),
    MoveTemplate(
        id="aid_citizen",
        label_template="Protect Civilians",
        intent_patterns=("help civilians", "secure evac route", "aid crowd"),
        synonym_bank=("aid", "protect", "evac", "civilians"),
        args_schema={
            "goal_tag": {"type": "string", "enum": ["rescue", "stabilize", "escort"]},
            "tone": {"type": "string", "enum": ["gentle", "decisive"]},
        },
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_diplomatic", "succ_bold"),
            ("part_tradeoff", "part_costly"),
            ("fail_sacrifice", "fail_complication"),
        ),
        tags=("support", "social"),
    ),
    MoveTemplate(
        id="confront_director",
        label_template="Confront Command",
        intent_patterns=("confront director", "challenge command", "force answer"),
        synonym_bank=("confront", "challenge", "pressure", "command"),
        args_schema={
            "target_npc": {"type": "string"},
            "tone": {"type": "string", "enum": ["cold", "direct", "accusing"]},
        },
        resolution_policy="prefer_partial",
        outcome_palette_ids=_palette_map(
            ("succ_bold", "succ_diplomatic"),
            ("part_noisy", "part_tradeoff"),
            ("fail_complication", "fail_pressure"),
        ),
        tags=("social", "conflict"),
    ),
    MoveTemplate(
        id="stabilize_reactor",
        label_template="Stabilize The Reactor",
        intent_patterns=("stabilize reactor", "hold the core", "cool the chamber"),
        synonym_bank=("stabilize", "reactor", "core", "cooling"),
        args_schema={
            "goal_tag": {"type": "string", "enum": ["cool", "seal", "sustain"]},
            "tone": {"type": "string", "enum": ["steady", "urgent"]},
        },
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_technical", "succ_bold"),
            ("part_costly", "part_tradeoff"),
            ("fail_sacrifice", "fail_pressure"),
        ),
        tags=("technical", "resource"),
    ),
    MoveTemplate(
        id="broker_truce",
        label_template="Broker A Truce",
        intent_patterns=("broker truce", "mediate conflict", "calm both sides"),
        synonym_bank=("truce", "mediate", "calm", "settle"),
        args_schema={"target_npc": {"type": "string"}, "tone": {"type": "string", "enum": ["calm", "firm"]}},
        resolution_policy="prefer_partial",
        outcome_palette_ids=_palette_map(
            ("succ_diplomatic", "succ_discovery"),
            ("part_tradeoff", "part_delay"),
            ("fail_complication", "fail_sacrifice"),
        ),
        tags=("social", "support"),
    ),
    MoveTemplate(
        id="trace_anomaly",
        label_template="Trace The Anomaly",
        intent_patterns=("trace anomaly", "follow glitch", "investigate spike"),
        synonym_bank=("anomaly", "glitch", "spike", "trace"),
        args_schema={"goal_tag": {"type": "string", "enum": ["source", "pattern", "threat"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_discovery", "succ_technical"),
            ("part_noisy", "part_delay"),
            ("fail_misread", "fail_detour"),
        ),
        tags=("investigate", "technical"),
    ),
    MoveTemplate(
        id="reroute_power",
        label_template="Reroute Emergency Power",
        intent_patterns=("reroute power", "redirect grid", "stabilize circuits"),
        synonym_bank=("power", "grid", "reroute", "circuits"),
        args_schema={"goal_tag": {"type": "string", "enum": ["support", "containment", "access"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_technical", "succ_bold"),
            ("part_costly", "part_tradeoff"),
            ("fail_pressure", "fail_complication"),
        ),
        tags=("technical", "resource"),
    ),
    MoveTemplate(
        id="jam_sensors",
        label_template="Jam Sensor Sweep",
        intent_patterns=("jam sensors", "blind surveillance", "cut scan feed"),
        synonym_bank=("jam", "sensors", "blind", "surveillance"),
        args_schema={"goal_tag": {"type": "string", "enum": ["stealth", "distraction"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_stealth", "succ_technical"),
            ("part_noisy", "part_tradeoff"),
            ("fail_detour", "fail_pressure"),
        ),
        tags=("stealth", "technical"),
    ),
    MoveTemplate(
        id="secure_supplies",
        label_template="Secure Field Supplies",
        intent_patterns=("secure supplies", "grab med kit", "collect tools"),
        synonym_bank=("supplies", "tools", "medkit", "resource"),
        args_schema={"goal_tag": {"type": "string", "enum": ["medical", "power", "transport"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_discovery", "succ_bold"),
            ("part_costly", "part_tradeoff"),
            ("fail_sacrifice", "fail_detour"),
        ),
        tags=("resource", "support"),
    ),
    MoveTemplate(
        id="calm_crowd",
        label_template="Calm The Crowd",
        intent_patterns=("calm crowd", "steady evac", "lower panic"),
        synonym_bank=("crowd", "panic", "steady", "evac"),
        args_schema={"tone": {"type": "string", "enum": ["reassuring", "commanding"]}},
        resolution_policy="prefer_partial",
        outcome_palette_ids=_palette_map(
            ("succ_diplomatic", "succ_bold"),
            ("part_tradeoff", "part_delay"),
            ("fail_complication", "fail_pressure"),
        ),
        tags=("support", "social"),
    ),
    MoveTemplate(
        id="flank_patrol",
        label_template="Flank The Patrol",
        intent_patterns=("flank patrol", "circle around", "outmaneuver team"),
        synonym_bank=("flank", "patrol", "outmaneuver", "position"),
        args_schema={"goal_tag": {"type": "string", "enum": ["stealth", "speed", "cover"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_stealth", "succ_bold"),
            ("part_noisy", "part_costly"),
            ("fail_detour", "fail_complication"),
        ),
        tags=("stealth", "conflict"),
    ),
    MoveTemplate(
        id="inspect_infrastructure",
        label_template="Inspect Infrastructure Evidence",
        intent_patterns=("inspect infrastructure", "review incident logs", "analyze field evidence"),
        synonym_bank=("infrastructure", "evidence", "logs", "inspect", "analyze"),
        args_schema={"goal_tag": {"type": "string", "enum": ["logs", "fault", "clue"]}},
        resolution_policy="prefer_success",
        outcome_palette_ids=_palette_map(
            ("succ_discovery", "succ_technical"),
            ("part_delay", "part_tradeoff"),
            ("fail_misread", "fail_detour"),
        ),
        tags=("investigate", "technical"),
    ),
)


MOVE_TEMPLATE_BY_ID: dict[str, MoveTemplate] = {template.id: template for template in MOVE_LIBRARY}
GLOBAL_MOVE_TEMPLATE_IDS = (
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
)
STORY_MOVE_TEMPLATE_IDS = tuple(template.id for template in MOVE_LIBRARY if template.id not in GLOBAL_MOVE_TEMPLATE_IDS)

MOVE_STRATEGY_STYLE_BY_ID: dict[str, StrategyStyle] = {
    GLOBAL_CLARIFY_MOVE_ID: "steady_slow",
    GLOBAL_LOOK_MOVE_ID: "steady_slow",
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID: "steady_slow",
    "scan_signal": "steady_slow",
    "convince_guard": "political_safe_resource_heavy",
    "sneak_route": "fast_dirty",
    "decode_core": "steady_slow",
    "aid_citizen": "political_safe_resource_heavy",
    "confront_director": "fast_dirty",
    "stabilize_reactor": "political_safe_resource_heavy",
    "broker_truce": "steady_slow",
    "trace_anomaly": "fast_dirty",
    "reroute_power": "political_safe_resource_heavy",
    "jam_sensors": "fast_dirty",
    "secure_supplies": "political_safe_resource_heavy",
    "calm_crowd": "steady_slow",
    "flank_patrol": "fast_dirty",
    "inspect_infrastructure": "steady_slow",
}

STRATEGY_STYLES: tuple[StrategyStyle, ...] = (
    "fast_dirty",
    "steady_slow",
    "political_safe_resource_heavy",
)

_missing_styles = sorted(set(MOVE_TEMPLATE_BY_ID) - set(MOVE_STRATEGY_STYLE_BY_ID))
if _missing_styles:  # pragma: no cover - import-time safety for template drift
    raise ValueError(f"missing strategy style mapping for moves: {_missing_styles}")
