import asyncio
import json
import uuid
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import LLMUsageLog
from app.modules.llm.base import LLMProvider
from app.modules.llm.prompts import build_classification_prompt, build_repair_prompt
from app.modules.llm.providers import DoubaoProvider, FakeProvider
from app.modules.llm.schemas import NarrativeOutput, PlayerInputClassification, UsageMeta


class LLMRuntime:
    def __init__(self):
        self.providers: dict[str, LLMProvider] = {
            "fake": FakeProvider(),
            "doubao": DoubaoProvider(api_key=settings.llm_doubao_api_key, base_url=settings.llm_doubao_base_url),
        }

    def _estimate_cost(self, provider: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        table = settings.llm_price_table.get(provider) or settings.llm_price_table.get("default") or {}
        if not table:
            return None
        pin = float(table.get("input_per_1k", 0.0))
        pout = float(table.get("output_per_1k", 0.0))
        return round((prompt_tokens / 1000.0) * pin + (completion_tokens / 1000.0) * pout, 6)

    def _log_usage(self, db: Session, *, session_id: uuid.UUID | None, step_id: uuid.UUID | None, operation: str, usage: dict):
        cost = usage.get("cost_estimate")
        if cost is None:
            cost = self._estimate_cost(usage.get("provider", "default"), int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0))
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
            cost_estimate=cost,
            created_at=datetime.utcnow(),
        )
        db.add(row)

    def _run(self, coro):
        return asyncio.run(coro)

    def _call_with_retries(self, db: Session, *, provider_name: str, operation: str, payload: str, model: str, session_id: uuid.UUID | None, step_id: uuid.UUID | None, retries: int):
        provider = self.providers[provider_name]
        last_exc = None
        for _ in range(retries):
            try:
                if operation == "classify":
                    result, usage = self._run(provider.classify(payload, request_id=str(uuid.uuid4()), timeout_s=settings.llm_timeout_s, model=model))
                elif operation == "generate":
                    result, usage = self._run(provider.generate(payload, request_id=str(uuid.uuid4()), timeout_s=settings.llm_timeout_s, model=model))
                else:
                    result, usage = self._run(provider.summarize(payload, request_id=str(uuid.uuid4()), timeout_s=settings.llm_timeout_s, model=model))
                usage["provider"] = provider_name
                usage["model"] = model
                usage["status"] = usage.get("status", "success")
                self._log_usage(db, session_id=session_id, step_id=step_id, operation=operation, usage=usage)
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self._log_usage(
                    db,
                    session_id=session_id,
                    step_id=step_id,
                    operation=operation,
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

    def classify_with_fallback(self, db: Session, *, text: str, session_id: uuid.UUID | None, step_id: uuid.UUID | None = None) -> tuple[PlayerInputClassification, bool]:
        prompt = build_classification_prompt(text)
        provider_chain = [settings.llm_provider_primary] + list(settings.llm_provider_fallbacks)

        for idx, provider_name in enumerate(provider_chain):
            if provider_name not in self.providers:
                continue
            retries = settings.llm_max_retries if idx == 0 else 1
            try:
                raw = self._call_with_retries(
                    db,
                    provider_name=provider_name,
                    operation="classify",
                    payload=prompt,
                    model=settings.llm_model_classify,
                    session_id=session_id,
                    step_id=step_id,
                    retries=retries,
                )
                if isinstance(raw, str):
                    raw = json.loads(raw)
                parsed = PlayerInputClassification.model_validate(raw)
                return parsed, True
            except (ValidationError, ValueError, TypeError, RuntimeError, json.JSONDecodeError):
                continue

        return PlayerInputClassification(
            intent="neutral",
            tone="calm",
            behavior_tags=["kind"],
            risk_tags=[],
            confidence=0.4,
        ), False

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
                        operation="generate",
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
                            operation="generate",
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
