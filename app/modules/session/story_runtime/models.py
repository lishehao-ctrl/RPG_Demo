from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.modules.session.story_choice_gating import PrereqKind

MARKER_REROUTE_LIMIT_REACHED_DEGRADED = "REROUTE_LIMIT_REACHED_DEGRADED"
MARKER_REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED = "REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED"
MARKER_REROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED = "REROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED"


class CandidateKind(str, Enum):
    VISIBLE = "VISIBLE"
    INVISIBLE_INTENT = "INVISIBLE_INTENT"
    FALLBACK_EXECUTOR = "FALLBACK_EXECUTOR"


class SelectionInputSource(str, Enum):
    BUTTON = "BUTTON"
    TEXT = "TEXT"
    EMPTY = "EMPTY"


@dataclass(slots=True)
class CandidateChoice:
    id: str
    kind: CandidateKind
    label: str | None
    action: dict | None
    effects: dict
    effect_ops: dict
    prereq_spec: dict | None
    next_node_id: str | None
    narration_skeleton: str | None
    alias_visible_choice_id: str | None = None
    source_ref: str | None = None


@dataclass(slots=True)
class StoryFallbackTextPlan:
    fallback_variant_text: str | None
    fallback_skeleton_text: str | None
    text_source: str | None


@dataclass(slots=True)
class StoryRuntimeContext:
    runtime_pack: dict
    current_node_id: str
    node: dict
    visible_choices: list[dict]
    fallback_spec: dict
    fallback_next_node_id: str
    fallback_markers: list[str]
    intents: list[dict]
    fallback_executors: list[dict]
    node_fallback_choice_id: str | None
    global_fallback_choice_id: str | None


@dataclass(slots=True)
class SelectionResult:
    selected_visible_choice_id: str | None
    attempted_choice_id: str | None
    mapping_confidence: float | None
    mapping_note: str | None
    internal_reason: str | None
    use_fallback: bool
    input_source: SelectionInputSource = SelectionInputSource.TEXT


@dataclass(slots=True)
class StoryChoiceResolution:
    compiled_action: Any | None
    selected_choice: dict | None
    attempted_choice_id: str | None
    selected_visible_choice_id: str | None
    mapping_confidence: float | None
    mapping_note: str | None
    fallback_reason_code: str | None
    internal_reason: str | None
    input_source: SelectionInputSource
    using_fallback: bool
    reroute_used: bool
    final_action_for_state: dict
    effects_for_state: dict
    effect_ops_for_state: dict
    next_node_id: str
    executed_choice_id: str
    resolved_choice_id: str
    key_decision: bool
    selected_target_kind: CandidateKind
    final_target_kind: CandidateKind
    markers: list[str]
    prereq_kind: PrereqKind
    fallback_executor_skeleton_text: str | None


@dataclass(slots=True)
class QuestStepEvent:
    current_node_id: str
    next_node_id: str
    executed_choice_id: str
    action_id: str | None
    fallback_used: bool


@dataclass(slots=True)
class QuestUpdateResult:
    state_after: dict
    quest_state: dict
    matched_rules: list[dict]


@dataclass(slots=True)
class RuntimeEventContext:
    session_id: str
    step_id: int
    story_node_id: str
    next_node_id: str
    executed_choice_id: str
    action_id: str | None
    fallback_used: bool


@dataclass(slots=True)
class EventResolution:
    state_after: dict
    state_delta: dict
    run_state: dict
    matched_rules: list[dict]
    selected_event_id: str | None
    selected_event_title: str | None
    selected_event_narration_hint: str | None
    selected_event_effects: dict


@dataclass(slots=True)
class EndingResolution:
    run_ended: bool
    ending_id: str | None
    ending_outcome: str | None
    ending_title: str | None
    ending_epilogue: str | None
    run_state: dict
    matched_rules: list[dict]
