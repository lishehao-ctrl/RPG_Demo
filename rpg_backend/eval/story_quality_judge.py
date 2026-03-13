from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from rpg_backend.config.settings import get_settings
from rpg_backend.eval.story_quality_schema import StoryQualityJudgeResult
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import get_responses_agent_bundle


@dataclass
class StoryQualityJudgeDecision:
    result: StoryQualityJudgeResult
    model: str
    attempts: int
    notes: list[str] = field(default_factory=list)


class StoryQualityJudgeError(RuntimeError):
    def __init__(self, *, error_type: str, message: str, notes: list[str] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.notes = notes or []


class StoryQualityJudge:
    """LLM-based subjective judge for generated story quality."""

    def __init__(self, *, model_override: str | None = None) -> None:
        settings = get_settings()
        self.bundle = get_responses_agent_bundle()
        self.model = (model_override or "").strip() or self.bundle.model
        self.timeout_seconds = float(settings.responses_timeout_seconds)
        self.temperature = 0.1
        self.enable_thinking = bool(settings.responses_enable_thinking_story_quality_judge)

        if not self.model:
            raise StoryQualityJudgeError(
                error_type="misconfigured",
                message="story quality judge missing model",
                notes=["check APP_RESPONSES_MODEL"],
            )

    @staticmethod
    def parse_result_payload(payload: dict[str, Any]) -> StoryQualityJudgeResult:
        try:
            return StoryQualityJudgeResult.model_validate(payload)
        except ValidationError as exc:
            raise StoryQualityJudgeError(
                error_type="judge_schema_invalid",
                message=str(exc),
                notes=["judge response does not match StoryQualityJudgeResult schema"],
            ) from exc

    async def evaluate(
        self,
        *,
        prompt_text: str,
        expected_tone: str | None,
        pack_summary: dict[str, Any],
        transcript_summary: dict[str, Any],
        metrics: dict[str, Any],
    ) -> StoryQualityJudgeDecision:
        developer_prompt = (
            "You are a strict evaluator for interactive narrative packs. "
            "Return strict JSON only. Score each axis from 0 to 10."
        )
        user_prompt = json.dumps(
            {
                "task": "judge_story_quality",
                "prompt_text": prompt_text,
                "expected_tone": expected_tone or "",
                "pack_summary": pack_summary,
                "transcript_summary": transcript_summary,
                "metrics": metrics,
                "required_output": {
                    "overall_score": "number 0..10",
                    "playability_score": "number 0..10",
                    "coherence_score": "number 0..10",
                    "tension_curve_score": "number 0..10",
                    "choice_impact_score": "number 0..10",
                    "prompt_fidelity_score": "number 0..10",
                    "major_issues": "array of strings",
                    "strengths": "array of strings",
                    "verdict": "pass|borderline|fail",
                },
            },
            ensure_ascii=False,
        )

        try:
            result = await self.bundle.author_agent.transport.create(
                model=self.model,
                input=[
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": developer_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_prompt}],
                    },
                ],
                previous_response_id=None,
                timeout=float(self.timeout_seconds),
                extra_body={"enable_thinking": self.enable_thinking},
            )
        except LLMProviderConfigError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StoryQualityJudgeError(
                error_type="judge_failed",
                message=str(exc),
                notes=["judge responses call failed"],
            ) from exc

        try:
            payload = json.loads(result.output_text)
        except Exception as exc:  # noqa: BLE001
            raise StoryQualityJudgeError(
                error_type="judge_invalid_json",
                message=str(exc),
                notes=["judge output is not valid JSON"],
            ) from exc

        if not isinstance(payload, dict):
            raise StoryQualityJudgeError(
                error_type="judge_invalid_json",
                message="judge output is not a JSON object",
            )

        validated = self.parse_result_payload(payload)
        return StoryQualityJudgeDecision(
            result=validated,
            model=self.model,
            attempts=1,
            notes=[f"judge_model={self.model}", "judge_attempts=1", f"response_id={result.response_id or ''}"],
        )
