from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NarrativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative_text: str


class EndingHighlightOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class EndingStatsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_steps: int = Field(ge=0)
    fallback_count: int = Field(ge=0)
    fallback_rate: float = Field(ge=0.0, le=1.0)
    explicit_count: int = Field(ge=0)
    rule_count: int = Field(ge=0)
    llm_count: int = Field(ge=0)
    fallback_source_count: int = Field(ge=0)
    energy_delta: float
    money_delta: float
    knowledge_delta: float
    affection_delta: float


class EndingReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    one_liner: str = Field(min_length=1)
    life_summary: str = Field(min_length=1)
    highlights: list[EndingHighlightOut] = Field(min_length=1, max_length=5)
    stats: EndingStatsOut
    persona_tags: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def normalize_tags(self):
        cleaned = []
        for tag in self.persona_tags:
            t = " ".join(str(tag).split())
            if t:
                cleaned.append(t)
        if not cleaned:
            raise ValueError("persona_tags cannot be empty")
        self.persona_tags = cleaned[:6]
        return self


class EndingBundleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative_text: str = Field(min_length=1)
    ending_report: EndingReportOut


NARRATIVE_SCHEMA_NAME = "story_narrative_v1"
NARRATIVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["narrative_text"],
    "properties": {
        "narrative_text": {"type": "string"},
    },
}


ENDING_REPORT_SCHEMA_NAME = "story_ending_report_v1"
ENDING_REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "one_liner", "life_summary", "highlights", "stats", "persona_tags"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "one_liner": {"type": "string", "minLength": 1},
        "life_summary": {"type": "string", "minLength": 1},
        "highlights": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "detail"],
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "detail": {"type": "string", "minLength": 1},
                },
            },
        },
        "stats": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "total_steps",
                "fallback_count",
                "fallback_rate",
                "explicit_count",
                "rule_count",
                "llm_count",
                "fallback_source_count",
                "energy_delta",
                "money_delta",
                "knowledge_delta",
                "affection_delta",
            ],
            "properties": {
                "total_steps": {"type": "integer", "minimum": 0},
                "fallback_count": {"type": "integer", "minimum": 0},
                "fallback_rate": {"type": "number", "minimum": 0, "maximum": 1},
                "explicit_count": {"type": "integer", "minimum": 0},
                "rule_count": {"type": "integer", "minimum": 0},
                "llm_count": {"type": "integer", "minimum": 0},
                "fallback_source_count": {"type": "integer", "minimum": 0},
                "energy_delta": {"type": "number"},
                "money_delta": {"type": "number"},
                "knowledge_delta": {"type": "number"},
                "affection_delta": {"type": "number"},
            },
        },
        "persona_tags": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {"type": "string", "minLength": 1},
        },
    },
}


ENDING_BUNDLE_SCHEMA_NAME = "story_ending_bundle_v1"
ENDING_BUNDLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["narrative_text", "ending_report"],
    "properties": {
        "narrative_text": {"type": "string", "minLength": 1},
        "ending_report": ENDING_REPORT_SCHEMA,
    },
}


class SelectionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["choice", "fallback"]
    target_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class SelectionMappingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["choice", "fallback"]
    target_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    intensity_tier: Literal[-2, -1, 0, 1, 2]
    reason: str | None = None
    top_candidates: list[SelectionCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_top_candidates(self):
        if len(self.top_candidates) > 3:
            self.top_candidates = self.top_candidates[:3]
        return self


SelectionDecisionCodeV3 = Literal[
    "SELECT_CHOICE",
    "FALLBACK_NO_MATCH",
    "FALLBACK_LOW_CONF",
    "FALLBACK_OFF_TOPIC",
    "FALLBACK_INPUT_POLICY",
]
SelectionFallbackReasonCodeV3 = Literal["NO_MATCH", "LOW_CONF", "OFF_TOPIC", "INPUT_POLICY"]


class SelectionCandidateV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["choice", "fallback"]
    target_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class SelectionMappingOutputV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["3.0"]
    decision_code: SelectionDecisionCodeV3
    target_type: Literal["choice", "fallback"]
    target_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    intensity_tier: Literal[-2, -1, 0, 1, 2]
    fallback_reason_code: SelectionFallbackReasonCodeV3 | None = None
    reason: str | None = None
    top_candidates: list[SelectionCandidateV3] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_top_candidates(self):
        if len(self.top_candidates) > 3:
            self.top_candidates = self.top_candidates[:3]
        return self


SELECTION_MAPPING_SCHEMA_NAME = "story_selection_mapping_v2"
SELECTION_MAPPING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["target_type", "target_id", "confidence", "intensity_tier", "top_candidates"],
    "properties": {
        "target_type": {"enum": ["choice", "fallback"]},
        "target_id": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "intensity_tier": {"type": "integer", "enum": [-2, -1, 0, 1, 2]},
        "reason": {"type": ["string", "null"]},
        "top_candidates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["target_type", "target_id", "confidence"],
                "properties": {
                    "target_type": {"enum": ["choice", "fallback"]},
                    "target_id": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}


SELECTION_MAPPING_SCHEMA_V3_NAME = "story_selection_mapping_v3"
SELECTION_MAPPING_SCHEMA_V3 = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "decision_code",
        "target_type",
        "target_id",
        "confidence",
        "intensity_tier",
        "fallback_reason_code",
        "top_candidates",
    ],
    "properties": {
        "schema_version": {"enum": ["3.0"]},
        "decision_code": {
            "enum": [
                "SELECT_CHOICE",
                "FALLBACK_NO_MATCH",
                "FALLBACK_LOW_CONF",
                "FALLBACK_OFF_TOPIC",
                "FALLBACK_INPUT_POLICY",
            ]
        },
        "target_type": {"enum": ["choice", "fallback"]},
        "target_id": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "intensity_tier": {"type": "integer", "enum": [-2, -1, 0, 1, 2]},
        "fallback_reason_code": {"type": ["string", "null"], "enum": ["NO_MATCH", "LOW_CONF", "OFF_TOPIC", "INPUT_POLICY", None]},
        "reason": {"type": ["string", "null"]},
        "top_candidates": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["target_type", "target_id", "confidence"],
                "properties": {
                    "target_type": {"enum": ["choice", "fallback"]},
                    "target_id": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}
