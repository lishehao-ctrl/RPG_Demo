from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.domain.conflict_tags import NPCConflictTag
from rpg_backend.domain.constants import GLOBAL_MOVE_IDS

StrategyStyle = Literal[
    "fast_dirty",
    "steady_slow",
    "political_safe_resource_heavy",
]


class Beat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    step_budget: int = Field(ge=1)
    required_events: list[str] = Field(default_factory=list)
    npc_quota: int = Field(ge=0)
    entry_scene_id: str


class ExitCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    condition_kind: Literal["always", "state_equals", "event_present", "beat_progress_gte"] = "always"
    key: str | None = None
    value: Any | None = None
    next_scene_id: str | None = None
    end_story: bool = False


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    beat_id: str
    scene_seed: str
    present_npcs: list[str] = Field(default_factory=list)
    enabled_moves: list[str] = Field(min_length=3, max_length=5)
    always_available_moves: list[str] = Field(min_length=2, max_length=3)
    exit_conditions: list[ExitCondition] = Field(default_factory=list)
    is_terminal: bool = False


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "always",
        "event_present",
        "state_equals",
        "state_gte",
        "inventory_has",
        "beat_progress_gte",
    ] = "always"
    key: str | None = None
    value: Any | None = None


class Effect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "set_state",
        "inc_state",
        "add_event",
        "add_inventory",
        "remove_inventory",
        "set_flag",
        "advance_beat_progress",
        "cost",
    ]
    key: str | None = None
    value: Any | None = None


class NarrationSlots(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_reaction: str
    world_shift: str
    clue_delta: str
    cost_delta: str
    next_hook: str


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    result: Literal["success", "partial", "fail_forward"]
    preconditions: list[Condition] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    next_scene_id: str | None = None
    narration_slots: NarrationSlots


class Move(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    strategy_style: StrategyStyle
    intents: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    args_schema: dict[str, Any] = Field(default_factory=dict)
    resolution_policy: Literal["prefer_success", "prefer_partial", "always_fail_forward"] = "prefer_success"
    outcomes: list[Outcome] = Field(min_length=1)


class NPCProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    red_line: str = Field(min_length=1, max_length=160)
    conflict_tags: list[NPCConflictTag] = Field(min_length=1, max_length=3)


class StoryPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    title: str
    description: str
    npcs: list[str] = Field(min_length=3, max_length=5)
    npc_profiles: list[NPCProfile] = Field(min_length=3, max_length=5)
    beats: list[Beat] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    moves: list[Move] = Field(min_length=1)
    input_hint: str = "Describe what you do next."
    style_guard: str = "Keep narration concise, concrete, and forward-moving."
