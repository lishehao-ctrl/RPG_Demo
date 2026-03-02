from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from app.config.settings import get_settings
from app.eval.story_quality_schema import StoryQualityJudgeResult
from app.llm.factory import resolve_openai_models


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
        self.base_url = (settings.llm_openai_base_url or "").strip()
        self.api_key = (settings.llm_openai_api_key or "").strip()
        self.model = self._resolve_model(settings, model_override=model_override)
        self.timeout_seconds = settings.llm_openai_timeout_seconds
        self.temperature = 0.1
        self.max_retries = max(1, min(settings.llm_openai_generator_max_retries, 3))
        self.chat_completions_url = self._normalize_chat_completions_url(self.base_url)

        if not self.base_url or not self.api_key or not self.model:
            raise StoryQualityJudgeError(
                error_type="misconfigured",
                message="story quality judge missing openai base_url/api_key/model",
                notes=[
                    "check APP_LLM_OPENAI_BASE_URL, APP_LLM_OPENAI_API_KEY, and judge model config",
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
    def _normalize_chat_completions_url(base_url: str) -> str:
        normalized = (base_url or "").strip().rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        if normalized.endswith("/responses"):
            return f"{normalized[:-len('/responses')]}/chat/completions"
        if normalized.endswith("/v1"):
            return f"{normalized}/chat/completions"
        return f"{normalized}/v1/chat/completions"

    @staticmethod
    def _extract_chat_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("chat completions payload missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError("chat completions payload missing first choice object")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ValueError("chat completions payload missing message")
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            fragments: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    fragments.append(part["text"])
            joined = "".join(fragments).strip()
            if joined:
                return joined
        raise ValueError("chat completions payload missing message content")

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

    @staticmethod
    def _is_retriable(exc: Exception) -> bool:
        if isinstance(exc, (json.JSONDecodeError, ValidationError, ValueError)):
            return True
        if isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        return False

    @staticmethod
    def _retry_delay_seconds(attempt: int, exc: Exception) -> float:
        if isinstance(exc, (json.JSONDecodeError, ValidationError, ValueError)):
            return 0.0
        schedule = (0.25, 0.8, 1.5)
        idx = min(max(attempt - 1, 0), len(schedule) - 1)
        return schedule[idx]

    def _call_chat_completions(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.chat_completions_url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    def evaluate(
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

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                payload = self._call_chat_completions(system_prompt=system_prompt, user_prompt=user_prompt)
                content = self._extract_chat_content(payload)
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError("judge output is not a JSON object")
                validated = self.parse_result_payload(parsed)
                return StoryQualityJudgeDecision(
                    result=validated,
                    model=self.model,
                    attempts=attempt,
                    notes=[f"judge_model={self.model}", f"judge_attempts={attempt}"],
                )
            except StoryQualityJudgeError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._is_retriable(exc) or attempt >= self.max_retries:
                    break
                delay = self._retry_delay_seconds(attempt, exc)
                if delay > 0:
                    time.sleep(delay)

        raise StoryQualityJudgeError(
            error_type="judge_failed",
            message=str(last_error) if last_error else "story quality judge failed",
            notes=[f"judge failed after {self.max_retries} attempts"],
        ) from last_error

