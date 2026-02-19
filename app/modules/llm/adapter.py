import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import LLMUsageLog
from app.modules.llm.base import LLMProvider
from app.modules.llm.prompts import build_repair_prompt
from app.modules.llm.providers import DoubaoProvider, FakeProvider
from app.modules.llm.schemas import NarrativeOutput, StorySelectionOutput


class LLMRuntime:
    def __init__(self):
        self.providers: dict[str, LLMProvider] = {
            "fake": FakeProvider(),
            "doubao": DoubaoProvider(api_key=settings.llm_doubao_api_key, base_url=settings.llm_doubao_base_url),
        }

    def _log_usage(self, db: Session, *, session_id: uuid.UUID | None, step_id: uuid.UUID | None, operation: str, usage: dict):
        row = LLMUsageLog(
            session_id=session_id,
            provider=usage.get("provider", "unknown"),
            model=usage.get("model", "unknown"),
            operation=operation,
            step_id=step_id,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=int(usage.get("latency_ms", 0) or 0),
            status=usage.get("status", "success"),
            error_message=usage.get("error_message"),
            created_at=datetime.utcnow(),
        )
        db.add(row)

    def _run(self, coro):
        return asyncio.run(coro)

    def _call_with_retries(
        self,
        db: Session,
        *,
        provider_name: str,
        payload: str,
        model: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None,
        retries: int,
    ):
        provider = self.providers[provider_name]
        last_exc = None
        for _ in range(retries):
            try:
                result, usage = self._run(
                    provider.generate(
                        payload,
                        request_id=str(uuid.uuid4()),
                        timeout_s=settings.llm_timeout_s,
                        model=model,
                    )
                )
                usage["provider"] = provider_name
                usage["model"] = model
                usage["status"] = usage.get("status", "success")
                self._log_usage(db, session_id=session_id, step_id=step_id, operation="generate", usage=usage)
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._log_usage(
                    db,
                    session_id=session_id,
                    step_id=step_id,
                    operation="generate",
                    usage={
                        "provider": provider_name,
                        "model": model,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "latency_ms": 0,
                        "status": "error",
                        "error_message": str(exc),
                    },
                )
        raise RuntimeError(str(last_exc) if last_exc else "llm call failed")

    def narrative_with_fallback(self, db: Session, *, prompt: str, session_id: uuid.UUID | None, step_id: uuid.UUID | None = None) -> tuple[NarrativeOutput, bool]:
        provider_chain = [settings.llm_provider_primary] + list(settings.llm_provider_fallbacks)

        for idx, provider_name in enumerate(provider_chain):
            if provider_name not in self.providers:
                continue
            retries = settings.llm_max_retries if idx == 0 else 1
            for _ in range(retries):
                raw = None
                try:
                    raw = self._call_with_retries(
                        db,
                        provider_name=provider_name,
                        payload=prompt,
                        model=settings.llm_model_generate,
                        session_id=session_id,
                        step_id=step_id,
                        retries=1,
                    )
                    parsed = self._parse_narrative(raw)
                    return parsed, True
                except Exception:
                    try:
                        repair_raw = self._call_with_retries(
                            db,
                            provider_name=provider_name,
                            payload=build_repair_prompt(str(raw)),
                            model=settings.llm_model_generate,
                            session_id=session_id,
                            step_id=step_id,
                            retries=1,
                        )
                        parsed = self._parse_narrative(repair_raw)
                        return parsed, True
                    except Exception:
                        continue

        fallback = NarrativeOutput(
            narrative_text="[fallback] Your words linger in the air while the story pauses for your next move.",
            choices=[
                {"id": "c1", "text": "Continue", "type": "dialog"},
                {"id": "c2", "text": "Observe silently", "type": "action"},
            ],
        )
        return fallback, False

    def select_story_choice_with_fallback(
        self,
        db: Session,
        *,
        prompt: str,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None = None,
    ) -> tuple[StorySelectionOutput, bool]:
        provider_chain = [settings.llm_provider_primary] + list(settings.llm_provider_fallbacks)
        for idx, provider_name in enumerate(provider_chain):
            if provider_name not in self.providers:
                continue
            retries = settings.llm_max_retries if idx == 0 else 1
            for _ in range(retries):
                raw = None
                try:
                    raw = self._call_with_retries(
                        db,
                        provider_name=provider_name,
                        payload=prompt,
                        model=settings.llm_model_generate,
                        session_id=session_id,
                        step_id=step_id,
                        retries=1,
                    )
                    if isinstance(raw, str):
                        raw = json.loads(raw)
                    parsed = StorySelectionOutput.model_validate(raw)
                    return parsed, True
                except Exception:
                    try:
                        repair_raw = self._call_with_retries(
                            db,
                            provider_name=provider_name,
                            payload=build_repair_prompt(str(raw)),
                            model=settings.llm_model_generate,
                            session_id=session_id,
                            step_id=step_id,
                            retries=1,
                        )
                        if isinstance(repair_raw, str):
                            repair_raw = json.loads(repair_raw)
                        parsed = StorySelectionOutput.model_validate(repair_raw)
                        return parsed, True
                    except Exception:
                        continue

        fallback = StorySelectionOutput(
            choice_id=None,
            use_fallback=True,
            confidence=0.0,
            intent_id=None,
            notes="selector_fallback",
        )
        return fallback, False

    @staticmethod
    def _parse_narrative(raw) -> NarrativeOutput:
        if isinstance(raw, str):
            raw = json.loads(raw)
        return NarrativeOutput.model_validate(raw)


_runtime: LLMRuntime | None = None


def get_llm_runtime() -> LLMRuntime:
    global _runtime
    if _runtime is None:
        _runtime = LLMRuntime()
    return _runtime
