from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.modules.llm.adapter import (
    AuthorAssistParseError,
    LLMTimeoutProfile,
    LLMUnavailableError,
    get_llm_runtime,
)
from app.modules.llm.runtime.progress import LLMStageEvent, StageEmitter
from app.modules.llm.prompts import build_author_assist_envelope, build_author_assist_prompt
from app.modules.story.author_assist_core.errors import (
    AuthorAssistError,
    AuthorAssistInvalidOutputError,
    AuthorAssistUnavailableError,
)
from app.modules.story.author_assist_core.service import (
    _assist_invalid_output_hint,
    _assist_unavailable_hint,
    normalize_assist_payload,
)
from app.modules.story.author_assist_core.types import LONG_WAIT_ASSIST_TASKS, TWO_STAGE_ASSIST_TASKS, AuthorAssistTask


def author_assist_suggestions(
    *,
    db: Session,
    task: AuthorAssistTask,
    locale: str,
    context: dict,
    stage_emitter: StageEmitter | None = None,
) -> dict:
    runtime = get_llm_runtime()
    timeout_profile = (
        LLMTimeoutProfile(
            disable_total_deadline=True,
            call_timeout_s=None,
            connect_timeout_s=max(0.1, float(settings.llm_connect_timeout_s)),
            read_timeout_s=None,
            write_timeout_s=max(0.1, float(settings.llm_write_timeout_s)),
            pool_timeout_s=max(0.1, float(settings.llm_pool_timeout_s)),
        )
        if task in LONG_WAIT_ASSIST_TASKS
        else None
    )

    try:
        if task in TWO_STAGE_ASSIST_TASKS:
            try:
                parsed, _ = runtime.author_assist_two_stage_with_fallback(
                    db,
                    task=task,
                    locale=locale,
                    context=context,
                    session_id=None,
                    step_id=uuid.uuid4(),
                    timeout_profile=timeout_profile,
                    expand_max_tokens_override=max(256, int(settings.llm_author_assist_expand_max_tokens)),
                    build_max_tokens_override=max(256, int(settings.llm_author_assist_build_max_tokens)),
                    repair_max_tokens_override=max(128, int(settings.llm_author_assist_repair_max_tokens)),
                    expand_temperature_override=0.0,
                    build_temperature_override=0.0,
                    repair_temperature_override=0.0,
                    stage_emitter=stage_emitter,
                )
            except TypeError as exc:
                if "stage_emitter" not in str(exc):
                    raise
                parsed, _ = runtime.author_assist_two_stage_with_fallback(
                    db,
                    task=task,
                    locale=locale,
                    context=context,
                    session_id=None,
                    step_id=uuid.uuid4(),
                    timeout_profile=timeout_profile,
                    expand_max_tokens_override=max(256, int(settings.llm_author_assist_expand_max_tokens)),
                    build_max_tokens_override=max(256, int(settings.llm_author_assist_build_max_tokens)),
                    repair_max_tokens_override=max(128, int(settings.llm_author_assist_repair_max_tokens)),
                    expand_temperature_override=0.0,
                    build_temperature_override=0.0,
                    repair_temperature_override=0.0,
                )
        else:
            prompt = build_author_assist_prompt(task=task, locale=locale, context=context)
            prompt_envelope = build_author_assist_envelope(task=task, locale=locale, context=context)
            try:
                parsed, _ = runtime.author_assist_with_fallback(
                    db,
                    prompt=prompt,
                    prompt_envelope=prompt_envelope,
                    session_id=None,
                    step_id=uuid.uuid4(),
                    timeout_profile=timeout_profile,
                    max_tokens_override=max(256, int(settings.llm_author_assist_max_tokens)),
                    stage_emitter=stage_emitter,
                    stage_locale=locale,
                    stage_task=task,
                )
            except TypeError as exc:
                msg = str(exc)
                if (
                    "stage_emitter" not in msg
                    and "stage_locale" not in msg
                    and "stage_task" not in msg
                ):
                    raise
                parsed, _ = runtime.author_assist_with_fallback(
                    db,
                    prompt=prompt,
                    prompt_envelope=prompt_envelope,
                    session_id=None,
                    step_id=uuid.uuid4(),
                    timeout_profile=timeout_profile,
                    max_tokens_override=max(256, int(settings.llm_author_assist_max_tokens)),
                )
    except AuthorAssistParseError as exc:
        raise AuthorAssistInvalidOutputError(hint=_assist_invalid_output_hint(exc)) from exc
    except LLMUnavailableError as exc:
        raise AuthorAssistUnavailableError(hint=_assist_unavailable_hint(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise AuthorAssistUnavailableError(hint=_assist_unavailable_hint(exc)) from exc

    normalized = normalize_assist_payload(task=task, locale=locale, context=context, payload=parsed)
    normalized["model"] = str(settings.llm_model_generate)
    return normalized


def author_assist_stream(
    *,
    db: Session,
    task: AuthorAssistTask,
    locale: str,
    context: dict,
):
    import queue
    import threading

    _done = object()
    event_queue: queue.Queue[object] = queue.Queue()

    def _emit_stage(event: LLMStageEvent) -> None:
        event_queue.put(("stage", event.to_dict()))

    def _worker() -> None:
        try:
            payload = author_assist_suggestions(
                db=db,
                task=task,
                locale=locale,
                context=context,
                stage_emitter=_emit_stage,
            )
            event_queue.put(("result", payload))
        except AuthorAssistError as exc:
            event_queue.put(
                (
                    "error",
                    {
                        "status": 503,
                        "detail": {
                            "code": exc.code,
                            "message": str(exc.message or "Author assist failed."),
                            "retryable": bool(exc.retryable),
                            "hint": exc.hint,
                        },
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            event_queue.put(
                (
                    "error",
                    {
                        "status": 503,
                        "detail": {
                            "code": "ASSIST_LLM_UNAVAILABLE",
                            "message": "LLM unavailable, please retry.",
                            "retryable": True,
                            "hint": _assist_unavailable_hint(exc),
                        },
                    },
                )
            )
        finally:
            event_queue.put(_done)

    threading.Thread(target=_worker, daemon=True).start()

    while True:
        item = event_queue.get()
        if item is _done:
            break
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        yield item


__all__ = [
    "AuthorAssistError",
    "AuthorAssistUnavailableError",
    "AuthorAssistInvalidOutputError",
    "author_assist_suggestions",
    "author_assist_stream",
    "get_llm_runtime",
]
