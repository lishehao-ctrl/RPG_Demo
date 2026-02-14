from typing import Literal

from pydantic import BaseModel, Field


class LLMChoice(BaseModel):
    id: str
    text: str
    type: Literal["dialog", "action"]


class PlayerInputClassification(BaseModel):
    intent: Literal["neutral", "romantic", "hostile", "friendly"]
    tone: Literal["calm", "warm", "harsh", "serious"]
    behavior_tags: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class NarrativeOutput(BaseModel):
    narrative_text: str
    choices: list[LLMChoice] = Field(min_length=2, max_length=4)


class UsageMeta(BaseModel):
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    status: str = "success"
    error_message: str | None = None
    cost_estimate: float | None = None
