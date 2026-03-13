from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rpg_backend.domain.conflict_tags import NPCConflictTag
from rpg_backend.domain.constants import GLOBAL_MOVE_IDS

StrategyStyle = Literal[
    "fast_dirty",
    "steady_slow",
    "political_safe_resource_heavy",
]


def _normalize_bounded_text(value: Any, *, max_length: int) -> Any:
    if not isinstance(value, str):
        return value

    text = " ".join(value.strip().split())
    if len(text) <= max_length:
        return text

    clipped = text[: max_length + 1]
    for separator in (". ", "! ", "? ", "; ", ", "):
        idx = clipped.rfind(separator)
        if idx >= max_length // 2:
            return clipped[: idx + 1].strip()
    return text[:max_length].rstrip(" ,;")


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
    pressure_signature: str | None = Field(default=None, max_length=220)


class OpeningGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro_text: str = Field(min_length=1, max_length=320)
    goal_hint: str = Field(min_length=1, max_length=220)
    starter_prompts: list[str] = Field(min_length=3, max_length=3)

    @field_validator("intro_text", mode="before")
    @classmethod
    def normalize_intro_text(cls, value: Any) -> Any:
        return _normalize_bounded_text(value, max_length=320)

    @field_validator("goal_hint", mode="before")
    @classmethod
    def normalize_goal_hint(cls, value: Any) -> Any:
        return _normalize_bounded_text(value, max_length=220)

    @model_validator(mode="after")
    def validate_starter_prompts(self) -> "OpeningGuidance":
        normalized: list[str] = []
        for prompt in self.starter_prompts:
            trimmed = prompt.strip()
            if not trimmed:
                raise ValueError("starter_prompts entries must be non-empty")
            normalized.append(trimmed)
        self.starter_prompts = normalized
        self.intro_text = self.intro_text.strip()
        self.goal_hint = self.goal_hint.strip()
        return self


class StoryPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    title: str
    description: str
    ending_shape_note: str | None = Field(default=None, max_length=220)
    move_bias_note: str | None = Field(default=None, max_length=220)
    npcs: list[str] = Field(min_length=3, max_length=5)
    npc_profiles: list[NPCProfile] = Field(min_length=3, max_length=5)
    beats: list[Beat] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    moves: list[Move] = Field(min_length=1)
    input_hint: str = "Describe what you do next."
    style_guard: str = "Keep narration concise, concrete, and forward-moving."
    opening_guidance: OpeningGuidance | None = None
