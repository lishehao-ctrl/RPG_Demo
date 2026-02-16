from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CharacterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    character_id: str
    archetype: str = "default"


class BehaviorPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    disclosure_level: Literal["closed", "guarded", "balanced", "open", "transparent"]
    helpfulness: int = Field(ge=0, le=100)
    aggression: int = Field(ge=0, le=100)


_DEFAULT_POLICY = BehaviorPolicy(disclosure_level="balanced", helpfulness=50, aggression=30)


def derive_behavior_policy(profile: CharacterProfile | None, trust_score: int | None) -> BehaviorPolicy:
    if profile is None or trust_score is None:
        return _DEFAULT_POLICY

    try:
        trust = int(trust_score)
    except (TypeError, ValueError):
        return _DEFAULT_POLICY
    trust = max(0, min(100, trust))

    if trust <= 24:
        return BehaviorPolicy(disclosure_level="closed", helpfulness=10, aggression=70)
    if trust <= 49:
        return BehaviorPolicy(disclosure_level="guarded", helpfulness=30, aggression=50)
    if trust <= 74:
        return BehaviorPolicy(disclosure_level="balanced", helpfulness=50, aggression=30)
    if trust <= 99:
        return BehaviorPolicy(disclosure_level="open", helpfulness=75, aggression=15)
    return BehaviorPolicy(disclosure_level="transparent", helpfulness=95, aggression=5)
