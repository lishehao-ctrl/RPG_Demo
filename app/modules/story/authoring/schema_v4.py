from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ACTION_TYPES = {"study", "work", "rest", "date", "gift"}
TIME_SLOTS = {"morning", "afternoon", "night"}


class Effects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy: int | float | None = None
    money: int | float | None = None
    knowledge: int | float | None = None
    affection: int | float | None = None

    @model_validator(mode="after")
    def validate_values(self):
        for field_name in ("energy", "money", "knowledge", "affection"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} must be numeric")
        return self


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_money: int | None = None
    min_energy: int | None = None
    min_affection: int | None = None
    day_at_least: int | None = None
    slot_in: list[Literal["morning", "afternoon", "night"]] | None = None


class FallbackTextVariants(BaseModel):
    model_config = ConfigDict(extra="forbid")

    NO_INPUT: str | None = None
    BLOCKED: str | None = None
    FALLBACK: str | None = None
    DEFAULT: str | None = None


class SceneFallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone: Literal["neutral", "calm", "supportive"] | None = None
    action_type: Literal["study", "work", "rest", "date", "gift"] | None = None
    effects: Effects | None = None
    text_variants: FallbackTextVariants | None = None
    next_scene_key: str | None = None


class IntentModule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author_input: str | None = None
    intent_tags: list[str] = Field(default_factory=list)
    parse_notes: str | None = None
    aliases: list[str] = Field(default_factory=list)


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    title: str = Field(min_length=1)
    summary: str | None = None
    locale: str = "en"


class World(BaseModel):
    model_config = ConfigDict(extra="forbid")

    era: str = Field(min_length=1)
    location: str = Field(min_length=1)
    boundaries: str = Field(min_length=1)
    social_rules: str | None = None
    global_state: dict = Field(default_factory=dict)
    intent_module: IntentModule = Field(default_factory=IntentModule)


class Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    role: str | None = None
    traits: list[str] = Field(default_factory=list)


class Protagonist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    role: str | None = None
    traits: list[str] = Field(default_factory=list)
    resources: dict = Field(default_factory=dict)


class Characters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protagonist: Protagonist
    npcs: list[Character] = Field(default_factory=list)
    relationship_axes: dict = Field(default_factory=dict)
    intent_module: IntentModule = Field(default_factory=IntentModule)


class Act(BaseModel):
    model_config = ConfigDict(extra="forbid")

    act_key: str | None = None
    title: str = Field(min_length=1)
    objective: str | None = None
    scene_keys: list[str] = Field(default_factory=list)


class Plot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mainline_acts: list[Act] = Field(default_factory=list)
    sideline_threads: list[str] = Field(default_factory=list)
    mainline_goal: str | None = None
    intent_module: IntentModule = Field(default_factory=IntentModule)


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_key: str | None = None
    label: str = Field(min_length=1)
    intent_aliases: list[str] = Field(default_factory=list)
    action_type: Literal["study", "work", "rest", "date", "gift"]
    action_params: dict = Field(default_factory=dict)
    go_to: str | None = None
    effects: Effects | None = None
    requirements: Requirements | None = None
    is_key_decision: bool = False


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_key: str | None = None
    title: str = Field(min_length=1)
    setup: str = Field(min_length=1)
    dramatic_question: str | None = None
    options: list[Option] = Field(default_factory=list)
    free_input_hints: list[str] = Field(default_factory=list)
    fallback: SceneFallback | None = None
    is_end: bool = False
    intent_module: IntentModule = Field(default_factory=IntentModule)

    @model_validator(mode="after")
    def validate_options(self):
        option_count = len(self.options)
        if self.is_end:
            if option_count > 4:
                raise ValueError("end scenes allow at most 4 options")
            return self
        if option_count < 2 or option_count > 4:
            raise ValueError("non-end scenes require 2 to 4 options")
        return self


class Flow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_scene_key: str | None = None
    scenes: list[Scene] = Field(min_length=1)
    intent_module: IntentModule = Field(default_factory=IntentModule)


class ActionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: Literal["study", "work", "rest", "date", "gift"]
    label: str | None = None
    defaults: dict = Field(default_factory=dict)


class ActionLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_catalog: list[ActionEntry] = Field(default_factory=list)
    input_mapping_policy: str = "intent_alias_only_visible_choice"
    intent_module: IntentModule = Field(default_factory=IntentModule)


class QuestTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_key_is: str | None = None
    next_scene_key_is: str | None = None
    option_ref_is: str | None = None
    action_type_is: Literal["study", "work", "rest", "date", "gift"] | None = None
    fallback_used_is: bool | None = None
    state_at_least: dict[str, int | float] = Field(default_factory=dict)
    state_delta_at_least: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_thresholds(self):
        for attr in ("state_at_least", "state_delta_at_least"):
            value = getattr(self, attr) or {}
            for key, item in value.items():
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise ValueError(f"{attr}.{key} must be numeric")
        return self


class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone_key: str | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    when: QuestTrigger = Field(default_factory=QuestTrigger)
    rewards: Effects | None = None


class QuestStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_key: str | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    milestones: list[Milestone] = Field(min_length=1)
    stage_rewards: Effects | None = None


class Quest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_key: str | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    auto_activate: bool = True
    stages: list[QuestStage] = Field(min_length=1)
    completion_rewards: Effects | None = None


class EventTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_key_is: str | None = None
    day_in: list[int] | None = None
    slot_in: list[Literal["morning", "afternoon", "night"]] | None = None
    fallback_used_is: bool | None = None
    state_at_least: dict[str, int | float] = Field(default_factory=dict)
    state_delta_at_least: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fields(self):
        if self.day_in is not None:
            normalized: list[int] = []
            for raw in self.day_in:
                if isinstance(raw, bool):
                    raise ValueError("day_in values must be integers")
                value = int(raw)
                if value < 1:
                    raise ValueError("day_in values must be >= 1")
                normalized.append(value)
            self.day_in = normalized
        for attr in ("state_at_least", "state_delta_at_least"):
            value = getattr(self, attr) or {}
            for key, item in value.items():
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise ValueError(f"{attr}.{key} must be numeric")
        return self


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_key: str | None = None
    title: str = Field(min_length=1)
    weight: int = Field(default=1, ge=1)
    once_per_run: bool = True
    cooldown_steps: int = Field(default=2, ge=0)
    trigger: EventTrigger = Field(default_factory=EventTrigger)
    effects: Effects | None = None
    narration_hint: str | None = None


class EndingTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_key_is: str | None = None
    day_at_least: int | None = None
    day_at_most: int | None = None
    energy_at_most: int | None = None
    money_at_least: int | None = None
    knowledge_at_least: int | None = None
    affection_at_least: int | None = None
    completed_quests_include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_days(self):
        if self.day_at_least is not None and self.day_at_least < 1:
            raise ValueError("day_at_least must be >= 1")
        if self.day_at_most is not None and self.day_at_most < 1:
            raise ValueError("day_at_most must be >= 1")
        return self


class EndingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_key: str | None = None
    title: str = Field(min_length=1)
    priority: int = 100
    outcome: Literal["success", "neutral", "fail"]
    trigger: EndingTrigger = Field(default_factory=EndingTrigger)
    epilogue: str = Field(min_length=1)


class Consequence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_axes: list[str] = Field(default_factory=list)
    quest_progression_rules: list[Quest] = Field(default_factory=list)
    event_rules: list[Event] = Field(default_factory=list)
    intent_module: IntentModule = Field(default_factory=IntentModule)


class EndingLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_rules: list[EndingRule] = Field(default_factory=list)
    intent_module: IntentModule = Field(default_factory=IntentModule)


class FallbackStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone: Literal["neutral", "calm", "supportive"] = "supportive"
    action_type: Literal["study", "work", "rest", "date", "gift"] = "rest"
    effects: Effects | None = None
    text_variants: FallbackTextVariants | None = None


class Systems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fallback_style: FallbackStyle | None = None
    events: list[Event] = Field(default_factory=list)
    intent_module: IntentModule = Field(default_factory=IntentModule)


class WriterTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str | None = None
    phase: Literal["seed", "expand", "structure", "balance", "ending"] = "seed"
    author_text: str = ""
    assistant_text: str = ""
    accepted_patch_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None


class PlayabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_reach_rate_min: float = 0.60
    stuck_turn_rate_max: float = 0.05
    no_progress_rate_max: float = 0.25
    branch_coverage_warn_below: float = 0.30
    rollout_strategies: int = Field(default=3, ge=1, le=5)
    rollout_runs_per_strategy: int = Field(default=80, ge=1, le=200)
    rollout_step_cap: int | None = Field(default=None, ge=8, le=120)

    @model_validator(mode="after")
    def normalize_thresholds(self):
        self.ending_reach_rate_min = min(0.95, max(0.20, float(self.ending_reach_rate_min)))
        self.stuck_turn_rate_max = min(0.50, max(0.00, float(self.stuck_turn_rate_max)))
        self.no_progress_rate_max = min(0.80, max(0.00, float(self.no_progress_rate_max)))
        self.branch_coverage_warn_below = min(0.90, max(0.00, float(self.branch_coverage_warn_below)))
        return self


class AuthorStoryV4(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[4] = 4
    entry_mode: Literal["spark", "ingest"] = "spark"
    source_text: str | None = None
    meta: Meta
    world: World
    characters: Characters
    plot: Plot = Field(default_factory=Plot)
    flow: Flow
    action: ActionLayer = Field(default_factory=ActionLayer)
    consequence: Consequence = Field(default_factory=Consequence)
    ending: EndingLayer = Field(default_factory=EndingLayer)
    systems: Systems = Field(default_factory=Systems)
    writer_journal: list[WriterTurn] = Field(default_factory=list)
    playability_policy: PlayabilityPolicy = Field(default_factory=PlayabilityPolicy)
