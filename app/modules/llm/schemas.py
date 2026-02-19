from typing import Literal

from pydantic import BaseModel, Field


class LLMChoice(BaseModel):
    id: str
    text: str
    type: Literal["dialog", "action"]


class NarrativeOutput(BaseModel):
    narrative_text: str
    choices: list[LLMChoice] = Field(min_length=2, max_length=4)


class StorySelectionOutput(BaseModel):
    choice_id: str | None = None
    use_fallback: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    intent_id: str | None = None
    notes: str | None = None


class UsageMeta(BaseModel):
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    status: str = "success"
    error_message: str | None = None
