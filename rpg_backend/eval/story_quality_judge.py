from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from rpg_backend.config.settings import get_settings
from rpg_backend.eval.story_quality_schema import StoryQualityJudgeResult
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import resolve_openai_models
from rpg_backend.llm.json_gateway import JsonGateway, JsonGatewayError
from rpg_backend.llm.worker_client import WorkerClientError, get_worker_client


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
        self.model = self._resolve_model(settings, model_override=model_override)
        self.timeout_seconds = settings.llm_openai_timeout_seconds
        self.temperature = 0.1
        self.max_retries = max(1, min(settings.llm_openai_generator_max_retries, 3))
        try:
            worker_client = get_worker_client()
        except WorkerClientError as exc:
            raise LLMProviderConfigError(
                f"llm worker misconfigured for story quality judge: {exc.error_code}: {exc.message}"
            ) from exc

        self._json_gateway = JsonGateway(
            default_timeout_seconds=float(self.timeout_seconds),
            worker_client=worker_client,
        )

        if not self.model:
            raise StoryQualityJudgeError(
                error_type="misconfigured",
                message="story quality judge missing model",
                notes=[
                    "check APP_LLM_OPENAI_GENERATOR_MODEL / APP_LLM_OPENAI_ROUTE_MODEL / APP_LLM_OPENAI_MODEL",
                ],
            )

    @staticmethod
    def _resolve_model(settings, *, model_override: str | None = None) -> str:
        override = (model_override or "").strip()
        if override:
            return override
        configured = (settings.llm_openai_generator_model or "").strip()
        if configured:
            return configured
        route_model, _ = resolve_openai_models(
            settings.llm_openai_route_model,
            settings.llm_openai_narration_model,
            settings.llm_openai_model,
        )
        return route_model

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
        system_prompt = (
            "You are a strict evaluator for interactive narrative packs. "
            "Return JSON only. Score each axis from 0 to 10. "
            "Use low scores when completion exists but player agency, coherence, or fidelity is weak."
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
            gateway_result = await self._json_gateway.call_json_object(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model,
                temperature=float(self.temperature),
                max_retries=self.max_retries,
                timeout_seconds=float(self.timeout_seconds),
            )
        except JsonGatewayError as exc:
            raise StoryQualityJudgeError(
                error_type="judge_failed",
                message=f"{exc.error_code}: {exc.message}",
                notes=[f"judge failed after {exc.attempts or self.max_retries} attempts"],
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise StoryQualityJudgeError(
                error_type="judge_failed",
                message=str(exc),
                notes=[f"judge failed after {self.max_retries} attempts"],
            ) from exc

        validated = self.parse_result_payload(gateway_result.payload)
        attempts = int(gateway_result.attempts or 1)
        return StoryQualityJudgeDecision(
            result=validated,
            model=self.model,
            attempts=attempts,
            notes=[f"judge_model={self.model}", f"judge_attempts={attempts}"],
        )
