from pydantic import BaseModel, Field


class NarrativeOutput(BaseModel):
    narrative_text: str


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
