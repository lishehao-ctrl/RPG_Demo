from __future__ import annotations

import json
import time
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.modules.llm.prompts import PromptEnvelope
from app.modules.llm.providers import DoubaoProvider, FakeProvider
from app.modules.llm.runtime.chat_completions_client import parse_llm_output
from app.modules.llm.runtime.errors import LLMUnavailableError
from app.modules.llm.runtime.progress import StageEmitter, emit_stage
from app.modules.llm.runtime.parsers import (
    format_narrative_chain_error,
    narrative_error_kind,
    narrative_raw_snippet,
    parse_narrative,
)
from app.modules.llm.runtime.protocol import protocol_messages
from app.modules.llm.runtime.transport import TransportOps
from app.modules.llm.runtime.types import LLMTimeoutProfile
from app.modules.llm.schemas import NarrativeOutput, StorySelectionOutput


class LLMRuntime(TransportOps):
    def __init__(self) -> None:
        super().__init__()
        proxy_provider = DoubaoProvider(
            api_key=settings.llm_doubao_api_key,
            base_url=settings.llm_doubao_base_url,
            temperature=settings.llm_doubao_temperature,
            max_tokens=settings.llm_doubao_max_tokens,
        )
        self.providers = {
            "fake": FakeProvider(),
            "proxy": proxy_provider,
        }

    @staticmethod
    def _parse_narrative(raw: object) -> NarrativeOutput:
        return parse_narrative(raw)

    @staticmethod
    def _provider_name() -> str:
        return "fake" if str(settings.env or "").strip().lower() == "test" else "proxy"

    @staticmethod
    def _deadline_at(profile: LLMTimeoutProfile) -> float | None:
        if profile.disable_total_deadline:
            return None
        return time.monotonic() + max(0.1, float(settings.llm_total_deadline_s))

    @staticmethod
    def _strict_temperature() -> float:
        return 0.0

    def narrative_with_fallback(
        self,
        db: Session,
        *,
        prompt: str,
        prompt_envelope: PromptEnvelope | None = None,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None = None,
        timeout_profile: LLMTimeoutProfile | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        stage_emitter: StageEmitter | None = None,
        stage_locale: str | None = None,
        stage_request_kind: str | None = None,
    ) -> tuple[NarrativeOutput, bool]:
        del temperature_override
        provider_name = self._provider_name()
        if provider_name not in self.providers:
            raise LLMUnavailableError(f"Unknown LLM provider: {provider_name}")

        profile = self._resolve_timeout_profile(timeout_profile)
        prompt_messages = protocol_messages(prompt_envelope)
        deadline_at = self._deadline_at(profile)
        if stage_request_kind:
            emit_stage(
                stage_emitter,
                stage_code="play.narration.start",
                locale=stage_locale or settings.story_default_locale,
                request_kind=stage_request_kind,
            )

        try:
            raw = self._call_with_protocol_fallback(
                db,
                provider_name=provider_name,
                payload=prompt,
                model=settings.llm_model_generate,
                session_id=session_id,
                step_id=step_id,
                deadline_at=deadline_at,
                timeout_profile=profile,
                max_tokens_override=max_tokens_override,
                temperature_override=self._strict_temperature(),
                messages_override=prompt_messages,
                validator=parse_narrative,
                stage_emitter=stage_emitter,
                stage_locale=stage_locale or settings.story_default_locale,
                stage_request_kind=stage_request_kind,
            )
            return parse_narrative(raw), True
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailableError(
                format_narrative_chain_error(
                    exc,
                    error_kind=narrative_error_kind(exc),
                    raw_snippet=narrative_raw_snippet(exc, None),
                )
            ) from exc

    def select_story_choice_with_fallback(
        self,
        db: Session,
        *,
        prompt: str,
        prompt_envelope: PromptEnvelope | None = None,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None = None,
        stage_emitter: StageEmitter | None = None,
        stage_locale: str | None = None,
        stage_request_kind: str | None = None,
    ) -> tuple[StorySelectionOutput, bool]:
        provider_name = self._provider_name()
        if provider_name not in self.providers:
            raise LLMUnavailableError(f"Unknown LLM provider: {provider_name}")

        prompt_messages = protocol_messages(prompt_envelope)
        deadline_at = time.monotonic() + max(0.1, float(settings.llm_total_deadline_s))
        emit_stage(
            stage_emitter,
            stage_code="play.selection.start",
            locale=stage_locale or settings.story_default_locale,
            request_kind=stage_request_kind or "free_input",
        )

        def _validate_selection(raw: object) -> StorySelectionOutput:
            payload = raw
            if isinstance(payload, str):
                parsed_json = parse_llm_output(
                    payload,
                    required_fields=("choice_id", "use_fallback", "confidence", "intent_id", "notes"),
                )
                payload = parsed_json
            if not isinstance(payload, dict):
                raise ValueError("selection output must be a JSON object")
            return StorySelectionOutput.model_validate(payload)

        try:
            raw = self._call_with_protocol_fallback(
                db,
                provider_name=provider_name,
                payload=prompt,
                model=settings.llm_model_generate,
                session_id=session_id,
                step_id=step_id,
                deadline_at=deadline_at,
                temperature_override=self._strict_temperature(),
                messages_override=prompt_messages,
                validator=_validate_selection,
                stage_emitter=stage_emitter,
                stage_locale=stage_locale or settings.story_default_locale,
                stage_request_kind=stage_request_kind or "free_input",
            )
            if isinstance(raw, str):
                raw = json.loads(raw)
            parsed = StorySelectionOutput.model_validate(raw)
            return parsed, True
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailableError(
                format_narrative_chain_error(
                    exc,
                    error_kind=narrative_error_kind(exc),
                    raw_snippet=narrative_raw_snippet(exc, None),
                )
            ) from exc


_runtime: LLMRuntime | None = None


def get_llm_runtime() -> LLMRuntime:
    global _runtime
    if _runtime is None:
        _runtime = LLMRuntime()
    return _runtime
