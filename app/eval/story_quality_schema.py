from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StoryQualityJudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_score: float = Field(ge=0.0, le=10.0)
    playability_score: float = Field(ge=0.0, le=10.0)
    coherence_score: float = Field(ge=0.0, le=10.0)
    tension_curve_score: float = Field(ge=0.0, le=10.0)
    choice_impact_score: float = Field(ge=0.0, le=10.0)
    prompt_fidelity_score: float = Field(ge=0.0, le=10.0)
    major_issues: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    verdict: Literal["pass", "borderline", "fail"]

