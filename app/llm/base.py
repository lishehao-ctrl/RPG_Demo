from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class RouteIntentResult(BaseModel):
    move_id: str
    args: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    interpreted_intent: str


class LLMProviderConfigError(RuntimeError):
    """Raised when provider is selected but missing required config."""


class LLMRouteError(RuntimeError):
    """Raised when provider cannot return a valid routed intent."""


class LLMNarrationError(RuntimeError):
    """Raised when provider cannot render narration text."""


class LLMProvider(ABC):
    @abstractmethod
    def route_intent(self, scene_context: dict[str, Any], text: str) -> RouteIntentResult:
        raise NotImplementedError

    @abstractmethod
    def render_narration(self, slots: dict[str, Any], style_guard: str) -> str:
        raise NotImplementedError
