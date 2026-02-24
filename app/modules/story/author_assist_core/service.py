from __future__ import annotations

from .deterministic_tasks import _clean_text
from .errors import AuthorAssistInvalidOutputError
from .postprocess import _postprocess_assist_payload
from .types import AuthorAssistTask


def _assist_unavailable_hint(exc: Exception) -> str:
    detail = _clean_text(exc, fallback="")
    if "NARRATIVE_NETWORK" in detail or "ASSIST_NETWORK" in detail or "nodename nor servname" in detail or "ConnectError" in detail:
        return "Check network/DNS reachability to the configured LLM endpoint, then retry."
    if "NARRATIVE_TIMEOUT" in detail or "ASSIST_TIMEOUT" in detail or "timeout" in detail.lower():
        return "The model call timed out. Retry once network latency is stable."
    return "Check model provider configuration and retry."


def _assist_invalid_output_hint(exc: Exception) -> str:
    detail = _clean_text(exc, fallback="")
    if "ASSIST_JSON_PARSE" in detail:
        return "Model output was not valid JSON. Retry once."
    if "ASSIST_SCHEMA_VALIDATE" in detail or "schema" in detail.lower():
        return "Model output shape was invalid. Retry once."
    return "Model output was invalid for author-assist schema. Please retry."


def normalize_assist_payload(*, task: AuthorAssistTask, locale: str, context: dict, payload: object) -> dict:
    parsed = payload if isinstance(payload, dict) else {}
    if (
        not isinstance(parsed.get("suggestions"), dict)
        or not isinstance(parsed.get("patch_preview"), list)
        or not isinstance(parsed.get("warnings"), list)
    ):
        raise AuthorAssistInvalidOutputError(
            hint="Model response was not valid assist JSON structure.",
        )
    return _postprocess_assist_payload(task=task, locale=locale, context=context, payload=parsed)
