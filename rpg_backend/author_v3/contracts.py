from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import StoryShellId
from rpg_backend.author_v2.contracts import NpcGender, NpcLoyaltyBias, SlotFunctionId, WorldlyDesireType


class WorldSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_seed: str = Field(min_length=1, max_length=4000)
    detected_shell: StoryShellId
    setting_description: str = Field(min_length=1, max_length=200)
    tone: str = Field(min_length=1, max_length=60)
    character_count: int = Field(ge=4, le=7)
    theme_keywords: list[str] = Field(default_factory=list, max_length=10)


class ForgedCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=30)
    gender: NpcGender
    public_identity: str = Field(min_length=1, max_length=120)
    hidden_need: str = Field(min_length=1, max_length=180)
    worldly_desire: WorldlyDesireType
    fear: str = Field(min_length=1, max_length=120)
    shame_trigger: str = Field(min_length=1, max_length=120)
    breaking_point: str = Field(min_length=1, max_length=120)
    speech_pattern: str = Field(min_length=1, max_length=120)
    loyalty_bias: NpcLoyaltyBias
    route_eligible: bool = False


class RelationshipStance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trust_level: float = Field(ge=0.0, le=1.0)
    dependency_level: float = Field(ge=0.0, le=1.0)
    hidden_dynamic: str = Field(min_length=1, max_length=180)
    tension_source: str = Field(min_length=1, max_length=180)
    power_asymmetry: float = Field(ge=-1.0, le=1.0)


class RelationshipEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_a_id: str = Field(min_length=1, max_length=64)
    character_b_id: str = Field(min_length=1, max_length=64)
    public_facade: str = Field(min_length=1, max_length=120)
    hidden_truth: str = Field(min_length=1, max_length=180)
    tension_score: float = Field(ge=0.0, le=1.0)
    hooks: list[str] = Field(default_factory=list, max_length=4)
    stance_a_to_b: RelationshipStance
    stance_b_to_a: RelationshipStance


class WorldConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: WorldSeed
    setting: str = Field(min_length=1, max_length=200)
    social_arena: str = Field(min_length=1, max_length=120)
    story_shell_id: StoryShellId
    characters: list[ForgedCharacter] = Field(min_length=4, max_length=7)
    relationship_edges: list[RelationshipEdge] = Field(min_length=3)
    protagonist_id: str = Field(min_length=1, max_length=64)


class RelationshipMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edges: list[RelationshipEdge]
    tension_density: float
    power_imbalance_score: float
    connectivity_score: float
    hook_pairs: list[tuple[str, str]]
    slot_assignments: dict[str, SlotFunctionId]
