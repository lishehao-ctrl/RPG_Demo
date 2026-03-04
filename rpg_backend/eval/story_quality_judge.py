from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from rpg_backend.config.settings import get_settings
from rpg_backend.eval.story_quality_schema import StoryQualityJudgeResult
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import resolve_openai_models
from rpg_backend.llm.json_gateway import JsonGateway, JsonGatewayError
from rpg_backend.llm.openai_compat import extract_chat_content, parse_json_object
from rpg_backend.llm.retry_policy import is_retriable_llm_error, retry_delay_seconds
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
        self.gateway_mode = str(getattr(settings, "llm_gateway_mode", "local") or "local").strip().lower()
        self.base_url = (settings.llm_openai_base_url or "").strip()
        self.api_key = (settings.llm_openai_api_key or "").strip()
        self.model = self._resolve_model(settings, model_override=model_override)
        self.timeout_seconds = settings.llm_openai_timeout_seconds
        self.temperature = 0.1
        self.max_retries = max(1, min(settings.llm_openai_generator_max_retries, 3))
        worker_client = None
        if self.gateway_mode == "worker":
            try:
                worker_client = get_worker_client()
            except WorkerClientError as exc:
                raise LLMProviderConfigError(
                    f"llm worker misconfigured for story quality judge: {exc.error_code}: {exc.message}"
                ) from exc
        self._json_gateway = JsonGateway(
            gateway_mode=self.gateway_mode,
            base_url=self.base_url,
            api_key=self.api_key,
            default_timeout_seconds=float(self.timeout_seconds),
            connect_timeout_seconds=5.0,
            max_connections=100,
            max_keepalive_connections=20,
            http2_enabled=False,
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
        if self.gateway_mode != "worker" and (not self.base_url or not self.api_key):
            raise StoryQualityJudgeError(
                error_type="misconfigured",
                message="story quality judge missing openai base_url/api_key",
                notes=["check APP_LLM_OPENAI_BASE_URL and APP_LLM_OPENAI_API_KEY"],
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

    def _call_chat_completions(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        try:
            result = self._json_gateway.call_json_object(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model,
                temperature=float(self.temperature),
                # evaluate() handles judge retry policy; keep transport call single-shot.
                max_retries=1,
                timeout_seconds=float(self.timeout_seconds),
            )
        except JsonGatewayError as exc:
            raise RuntimeError(f"{exc.error_code}: {exc.message}") from exc
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(result.payload, ensure_ascii=False),
                    }
                }
            ]
        }

    def evaluate(
        self,
        *,
        prompt_text: str,
        expected_tone: str | None,
        pack_summary: dict[str, Any],
        transcript_summary: dict[str, Any],
        metrics: dict[str, Any],
    ) -> StoryQualityJudgeDecision:
        gateway_mode = str(getattr(self, "gateway_mode", "local") or "local").strip().lower()
        temperature = float(getattr(self, "temperature", 0.1))
        timeout_seconds = float(getattr(self, "timeout_seconds", 30.0))
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

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if gateway_mode == "worker":
                    gateway_result = self._json_gateway.call_json_object(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model=self.model,
                        temperature=temperature,
                        max_retries=self.max_retries,
                        timeout_seconds=timeout_seconds,
                    )
                    parsed = gateway_result.payload
                    attempts = gateway_result.attempts
                else:
                    raw = self._call_chat_completions(system_prompt=system_prompt, user_prompt=user_prompt)
                    parsed = parse_json_object(extract_chat_content(raw))
                    attempts = attempt
                validated = self.parse_result_payload(parsed)
                return StoryQualityJudgeDecision(
                    result=validated,
                    model=self.model,
                    attempts=attempts,
                    notes=[f"judge_model={self.model}", f"judge_attempts={attempts}"],
                )
            except StoryQualityJudgeError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if gateway_mode == "worker":
                    break
                if not is_retriable_llm_error(exc) or attempt >= self.max_retries:
                    break
                delay = retry_delay_seconds(attempt, exc)
                if delay > 0:
                    time.sleep(delay)

        if isinstance(last_error, JsonGatewayError):
            raise StoryQualityJudgeError(
                error_type="judge_failed",
                message=f"{last_error.error_code}: {last_error.message}",
                notes=[f"judge failed after {last_error.attempts or self.max_retries} attempts"],
            ) from last_error
        raise StoryQualityJudgeError(
            error_type="judge_failed",
            message=str(last_error) if last_error else "story quality judge failed",
            notes=[f"judge failed after {self.max_retries} attempts"],
        ) from last_error
