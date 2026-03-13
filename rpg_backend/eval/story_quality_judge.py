from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from rpg_backend.config.settings import Settings, get_settings
from rpg_backend.eval.story_quality_schema import StoryQualityJudgeResult
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import get_responses_agent_bundle
from rpg_backend.llm.json_gateway import JsonGatewayError, ResponsesJsonGateway
from rpg_backend.llm.task_specs import build_responses_task_spec_bundle


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

    def __init__(self, *, model_override: str | None = None, settings: Settings | None = None) -> None:
        resolved_settings = settings or get_settings()
        self.bundle = get_responses_agent_bundle()
        self.task_spec = self.bundle.task_specs.story_quality_judge
        self._json_gateway = ResponsesJsonGateway(transport=self.bundle.author_agent.transport)
        self.model = (model_override or "").strip() or self.bundle.model
        self.timeout_seconds = float(resolved_settings.responses_timeout_seconds)
        self.temperature = 0.1
        self.max_retries = 1

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
        task_spec = getattr(self, "task_spec", None) or build_responses_task_spec_bundle().story_quality_judge
        user_prompt = json.dumps(
            {
                "task": task_spec.task_name,
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
            result = await self._json_gateway.call_json_object(
                model=self.model,
                system_prompt=task_spec.developer_prompt,
                user_prompt=user_prompt,
                temperature=self.temperature,
                timeout_seconds=float(self.timeout_seconds),
                enable_thinking=task_spec.enable_thinking,
            )
        except LLMProviderConfigError:
            raise
        except JsonGatewayError as exc:
            error_type = "judge_invalid_json" if exc.error_code == "json_task_invalid_response" else "judge_failed"
            raise StoryQualityJudgeError(
                error_type=error_type,
                message=str(exc),
                notes=[f"error_code={exc.error_code}", f"attempts={exc.attempts}"],
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise StoryQualityJudgeError(
                error_type="judge_failed",
                message=str(exc),
                notes=["judge responses call failed"],
            ) from exc

        validated = self.parse_result_payload(result.payload)
        return StoryQualityJudgeDecision(
            result=validated,
            model=self.model,
            attempts=int(result.attempts),
            notes=[
                f"judge_model={self.model}",
                f"judge_attempts={int(result.attempts)}",
                f"response_id={result.response_id or ''}",
            ],
        )
