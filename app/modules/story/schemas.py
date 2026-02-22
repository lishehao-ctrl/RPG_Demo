from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StoryAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_params(self):
        allowed = {"study", "work", "rest", "date", "gift"}
        if self.action_id not in allowed:
            raise ValueError("unknown action_id")

        if self.action_id in {"study", "work", "rest"}:
            if self.params not in ({},):
                raise ValueError("params must be empty for simple actions")

        if self.action_id == "date":
            if not isinstance(self.params.get("target"), str) or not self.params.get("target"):
                raise ValueError("date requires target")

        if self.action_id == "gift":
            if not isinstance(self.params.get("target"), str) or not self.params.get("target"):
                raise ValueError("gift requires target")
            if not isinstance(self.params.get("gift_type"), str) or not self.params.get("gift_type"):
                raise ValueError("gift requires gift_type")

        return self


class StoryChoiceRequires(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_money: int | None = None
    min_energy: int | None = None
    min_affection: int | None = None
    day_at_least: int | None = None
    slot_in: list[Literal["morning", "afternoon", "night"]] | None = None


class StoryChoiceEffects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy: int | float | None = None
    money: int | float | None = None
    knowledge: int | float | None = None
    affection: int | float | None = None

    @staticmethod
    def _validate_effect_value(value: Any, field_name: str) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError(f"{field_name} cannot be bool")
        if isinstance(value, (int, float)):
            return value
        raise ValueError(f"{field_name} has invalid effect value type")

    @model_validator(mode="after")
    def validate_effects(self):
        for field_name in ("energy", "money", "knowledge", "affection"):
            self._validate_effect_value(getattr(self, field_name), field_name)
        return self


class StoryChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_id: str
    display_text: str
    action: StoryAction
    requires: StoryChoiceRequires | None = None
    effects: StoryChoiceEffects | None = None
    next_node_id: str
    is_key_decision: bool = False


class QuestTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id_is: str | None = None
    next_node_id_is: str | None = None
    executed_choice_id_is: str | None = None
    action_id_is: str | None = None
    fallback_used_is: bool | None = None
    state_at_least: dict[str, int | float] = Field(default_factory=dict)
    state_delta_at_least: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_threshold_maps(self):
        for attr in ("state_at_least", "state_delta_at_least"):
            data = getattr(self, attr)
            for key, value in data.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{attr}.{key} must be numeric")
        return self


class QuestStageMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestone_id: str
    title: str
    description: str | None = None
    when: QuestTrigger = Field(default_factory=QuestTrigger)
    rewards: StoryChoiceEffects | None = None


class QuestStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str
    title: str
    description: str | None = None
    milestones: list[QuestStageMilestone] = Field(min_length=1)
    stage_rewards: StoryChoiceEffects | None = None


class StoryQuest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str
    title: str
    description: str | None = None
    auto_activate: bool = True
    stages: list[QuestStage] = Field(min_length=1)
    completion_rewards: StoryChoiceEffects | None = None


class StoryRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_days: int = Field(default=7, ge=1)
    max_steps: int = Field(default=24, ge=1)
    default_timeout_outcome: Literal["neutral", "fail"] = "neutral"


class StoryEventTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id_is: str | None = None
    day_in: list[int] | None = None
    slot_in: list[Literal["morning", "afternoon", "night"]] | None = None
    fallback_used_is: bool | None = None
    state_at_least: dict[str, int | float] = Field(default_factory=dict)
    state_delta_at_least: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_trigger(self):
        if self.day_in is not None:
            normalized_days: list[int] = []
            for value in self.day_in:
                if isinstance(value, bool):
                    raise ValueError("day_in values must be integers")
                ivalue = int(value)
                if ivalue < 1:
                    raise ValueError("day_in values must be >= 1")
                normalized_days.append(ivalue)
            self.day_in = normalized_days

        for attr in ("state_at_least", "state_delta_at_least"):
            data = getattr(self, attr)
            for key, value in data.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{attr}.{key} must be numeric")
        return self


class StoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    title: str
    weight: int = Field(default=1, ge=1)
    once_per_run: bool = True
    cooldown_steps: int = Field(default=2, ge=0)
    trigger: StoryEventTrigger = Field(default_factory=StoryEventTrigger)
    effects: StoryChoiceEffects | None = None
    narration_hint: str | None = None


class StoryEndingTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id_is: str | None = None
    day_at_least: int | None = None
    day_at_most: int | None = None
    energy_at_most: int | None = None
    money_at_least: int | None = None
    knowledge_at_least: int | None = None
    affection_at_least: int | None = None
    completed_quests_include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trigger(self):
        for attr in ("day_at_least", "day_at_most"):
            value = getattr(self, attr)
            if value is not None and value < 1:
                raise ValueError(f"{attr} must be >= 1")
        return self


class StoryEnding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str
    title: str
    priority: int = 100
    outcome: Literal["success", "neutral", "fail"]
    trigger: StoryEndingTrigger = Field(default_factory=StoryEndingTrigger)
    epilogue: str


class StoryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str
    alias_choice_id: str
    description: str | None = None
    patterns: list[str] = Field(default_factory=list)


class StoryFallbackTextVariants(BaseModel):
    model_config = ConfigDict(extra="forbid")

    NO_INPUT: str | None = None
    BLOCKED: str | None = None
    FALLBACK: str | None = None
    DEFAULT: str | None = None


class StoryFallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    action: StoryAction
    next_node_id_policy: str
    next_node_id: str | None = None
    effects: StoryChoiceEffects | None = None
    text_variants: StoryFallbackTextVariants | None = None


class FallbackExecutorNarration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skeleton: str | None = None


class FallbackExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    action_id: str | None = None
    action_params: dict = Field(default_factory=dict)
    effects: StoryChoiceEffects = Field(default_factory=StoryChoiceEffects)
    prereq: StoryChoiceRequires | None = None
    next_node_id: str | None = None
    narration: FallbackExecutorNarration | None = None

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action_id is None:
            return self
        if self.action_id not in {"study", "work", "rest", "date", "gift", "clarify"}:
            raise ValueError("fallback executor action_id is invalid")
        if not isinstance(self.action_params, dict):
            raise ValueError("fallback executor action_params must be an object")
        return self


class StoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    scene_brief: str
    choices: list[StoryChoice]
    intents: list[StoryIntent] = Field(default_factory=list)
    node_fallback_choice_id: str | None = None
    fallback: StoryFallback | None = None
    is_end: bool = False


class StoryPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str
    version: int
    title: str
    summary: str | None = None
    locale: str | None = None
    start_node_id: str
    nodes: list[StoryNode]
    characters: list[dict] = Field(default_factory=list)
    initial_state: dict = Field(default_factory=dict)
    default_fallback: StoryFallback | None = None
    fallback_executors: list[FallbackExecutor] = Field(default_factory=list)
    global_fallback_choice_id: str | None = None
    quests: list[StoryQuest] = Field(default_factory=list)
    events: list[StoryEvent] = Field(default_factory=list)
    endings: list[StoryEnding] = Field(default_factory=list)
    run_config: StoryRunConfig | None = None
    author_source_v3: dict | None = None
    author_source_v4: dict | None = None


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class AuthorDiagnostic(BaseModel):
    code: str
    path: str | None = None
    message: str
    suggestion: str | None = None


class AuthorCompileDiagnostics(BaseModel):
    errors: list[AuthorDiagnostic] = Field(default_factory=list)
    warnings: list[AuthorDiagnostic] = Field(default_factory=list)
    mappings: dict = Field(default_factory=dict)


class PlayabilityMetrics(BaseModel):
    ending_reach_rate: float = 0.0
    stuck_turn_rate: float = 0.0
    no_progress_rate: float = 0.0
    branch_coverage: float = 0.0


class PlayabilityReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pass_: bool = Field(alias="pass")
    blocking_errors: list[AuthorDiagnostic] = Field(default_factory=list)
    warnings: list[AuthorDiagnostic] = Field(default_factory=list)
    metrics: PlayabilityMetrics = Field(default_factory=PlayabilityMetrics)


class ValidateAuthorResponse(BaseModel):
    valid: bool
    errors: list[AuthorDiagnostic] = Field(default_factory=list)
    warnings: list[AuthorDiagnostic] = Field(default_factory=list)
    compiled_preview: dict | None = None
    playability: PlayabilityReport


class CompileAuthorResponse(BaseModel):
    pack: dict
    diagnostics: AuthorCompileDiagnostics


class AuthorAssistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    locale: str = "en"
    context: dict = Field(default_factory=dict)


class AuthorAssistResponse(BaseModel):
    suggestions: dict = Field(default_factory=dict)
    patch_preview: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str
    model: str


class StoryListItem(BaseModel):
    story_id: str
    version: int
    title: str
    is_published: bool
    is_playable: bool
    summary: str | None = None


class StoryListResponse(BaseModel):
    stories: list[StoryListItem] = Field(default_factory=list)
