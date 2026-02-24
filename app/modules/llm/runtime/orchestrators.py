from __future__ import annotations

import json
import time
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.modules.llm.prompts import (
    PromptEnvelope,
    build_author_cast_expand_envelope,
    build_author_idea_expand_envelope,
    build_author_story_build_envelope,
)
from app.modules.llm.providers import DoubaoProvider, FakeProvider
from app.modules.llm.runtime.author_overview import build_overview_rows_from_blueprint
from app.modules.llm.runtime.chat_completions_client import parse_llm_output
from app.modules.llm.runtime.errors import AuthorAssistParseError, LLMUnavailableError
from app.modules.llm.runtime.progress import StageEmitter, emit_stage
from app.modules.llm.runtime.parsers import (
    assist_error_kind,
    assist_raw_snippet,
    format_assist_chain_error,
    format_narrative_chain_error,
    narrative_error_kind,
    narrative_raw_snippet,
    parse_author_assist,
    parse_author_cast_blueprint,
    parse_author_idea_blueprint,
    parse_narrative,
)
from app.modules.llm.runtime.protocol import protocol_messages
from app.modules.llm.runtime.transport import TransportOps
from app.modules.llm.runtime.types import LLMTimeoutProfile
from app.modules.llm.schemas import NarrativeOutput, StorySelectionOutput

_CAST_MIN_NPC = 3
_CAST_ROLE_BUCKET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "support": ("support", "friend", "ally", "mentor", "helper", "teammate", "assistant", "guide"),
    "rival": ("rival", "enemy", "opposition", "competitor", "antagonist", "threat"),
    "gatekeeper": ("gatekeeper", "authority", "teacher", "advisor", "professor", "manager", "admin", "parent"),
}


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _existing_npc_roster(context: dict | None) -> list[dict[str, str]]:
    if not isinstance(context, dict):
        return []
    draft = context.get("draft")
    if not isinstance(draft, dict):
        return []
    characters = draft.get("characters")
    if not isinstance(characters, dict):
        return []
    raw_npcs = characters.get("npcs")
    if not isinstance(raw_npcs, list):
        return []

    roster: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_npcs:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        roster.append(
            {
                "name": name,
                "role": _clean_text(item.get("role")),
            }
        )
    return roster


def _role_bucket(role_text: str) -> str | None:
    normalized = _clean_text(role_text).lower()
    if not normalized:
        return None
    for bucket, keywords in _CAST_ROLE_BUCKET_KEYWORDS.items():
        if any(token in normalized for token in keywords):
            return bucket
    return None


def _needs_cast_expansion(context: dict | None) -> bool:
    roster = _existing_npc_roster(context)
    if len(roster) < _CAST_MIN_NPC:
        return True

    buckets: set[str] = set()
    for item in roster:
        bucket = _role_bucket(item.get("role", ""))
        if bucket:
            buckets.add(bucket)
    return len(buckets) < 2


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

    def author_assist_two_stage_with_fallback(
        self,
        db: Session,
        *,
        task: str,
        locale: str,
        context: dict,
        session_id: uuid.UUID | None,
        step_id: uuid.UUID | None = None,
        timeout_profile: LLMTimeoutProfile | None = None,
        expand_max_tokens_override: int | None = None,
        build_max_tokens_override: int | None = None,
        repair_max_tokens_override: int | None = None,
        expand_temperature_override: float | None = None,
        build_temperature_override: float | None = None,
        repair_temperature_override: float | None = None,
        stage_emitter: StageEmitter | None = None,
    ) -> tuple[dict, bool]:
        del repair_max_tokens_override
        del expand_temperature_override
        del build_temperature_override
        del repair_temperature_override

        provider_name = self._provider_name()
        if provider_name not in self.providers:
            raise LLMUnavailableError(f"Unknown LLM provider: {provider_name}")

        profile = self._resolve_timeout_profile(timeout_profile)
        deadline_at = self._deadline_at(profile)

        expand_envelope = build_author_idea_expand_envelope(task=task, locale=locale, context=context)
        expand_messages = protocol_messages(expand_envelope)
        emit_stage(
            stage_emitter,
            stage_code="author.expand.start",
            locale=locale,
            task=task,
        )

        try:
            expand_raw = self._call_with_protocol_fallback(
                db,
                provider_name=provider_name,
                payload=expand_envelope.user_text,
                model=settings.llm_model_generate,
                session_id=session_id,
                step_id=step_id,
                deadline_at=deadline_at,
                timeout_profile=profile,
                max_tokens_override=expand_max_tokens_override,
                temperature_override=self._strict_temperature(),
                messages_override=expand_messages,
                validator=parse_author_idea_blueprint,
                stage_emitter=stage_emitter,
                stage_locale=locale,
                stage_task=task,
            )
            blueprint = parse_author_idea_blueprint(expand_raw)
            overview_rows = build_overview_rows_from_blueprint(task=task, blueprint=blueprint)
            cast_blueprint: dict | None = None

            if _needs_cast_expansion(context):
                cast_envelope = build_author_cast_expand_envelope(
                    task=task,
                    locale=locale,
                    context=context,
                    idea_blueprint=blueprint,
                )
                cast_messages = protocol_messages(cast_envelope)
                emit_stage(
                    stage_emitter,
                    stage_code="author.cast.start",
                    locale=locale,
                    task=task,
                )
                cast_raw = self._call_with_protocol_fallback(
                    db,
                    provider_name=provider_name,
                    payload=cast_envelope.user_text,
                    model=settings.llm_model_generate,
                    session_id=session_id,
                    step_id=step_id,
                    deadline_at=deadline_at,
                    timeout_profile=profile,
                    max_tokens_override=expand_max_tokens_override,
                    temperature_override=self._strict_temperature(),
                    messages_override=cast_messages,
                    validator=parse_author_cast_blueprint,
                    stage_emitter=stage_emitter,
                    stage_locale=locale,
                    stage_task=task,
                )
                cast_blueprint = parse_author_cast_blueprint(cast_raw)

            build_envelope = build_author_story_build_envelope(
                task=task,
                locale=locale,
                context=context,
                idea_blueprint=blueprint,
                cast_blueprint=cast_blueprint,
            )
            build_messages = protocol_messages(build_envelope)
            emit_stage(
                stage_emitter,
                stage_code="author.build.start",
                locale=locale,
                task=task,
                overview_source="author_idea_blueprint_v1",
                overview_rows=overview_rows,
            )
            build_raw = self._call_with_protocol_fallback(
                db,
                provider_name=provider_name,
                payload=build_envelope.user_text,
                model=settings.llm_model_generate,
                session_id=session_id,
                step_id=step_id,
                deadline_at=deadline_at,
                timeout_profile=profile,
                max_tokens_override=build_max_tokens_override,
                temperature_override=self._strict_temperature(),
                messages_override=build_messages,
                validator=parse_author_assist,
                stage_emitter=stage_emitter,
                stage_locale=locale,
                stage_task=task,
            )
            return parse_author_assist(build_raw), True
        except AuthorAssistParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailableError(
                format_assist_chain_error(
                    exc,
                    error_kind=assist_error_kind(exc),
                    raw_snippet=assist_raw_snippet(exc, None),
                )
            ) from exc

    def author_assist_with_fallback(
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
        stage_task: str | None = None,
    ) -> tuple[dict, bool]:
        del temperature_override
        provider_name = self._provider_name()
        if provider_name not in self.providers:
            raise LLMUnavailableError(f"Unknown LLM provider: {provider_name}")

        profile = self._resolve_timeout_profile(timeout_profile)
        prompt_messages = protocol_messages(prompt_envelope)
        deadline_at = self._deadline_at(profile)
        emit_stage(
            stage_emitter,
            stage_code="author.single.start",
            locale=stage_locale or "en",
            task=stage_task,
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
                validator=parse_author_assist,
                stage_emitter=stage_emitter,
                stage_locale=stage_locale or "en",
                stage_task=stage_task,
            )
            return parse_author_assist(raw), True
        except AuthorAssistParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailableError(
                format_assist_chain_error(
                    exc,
                    error_kind=assist_error_kind(exc),
                    raw_snippet=assist_raw_snippet(exc, None),
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
