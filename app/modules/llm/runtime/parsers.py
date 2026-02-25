from __future__ import annotations

import json
import re

import httpx
from pydantic import ValidationError

from app.modules.llm.runtime.errors import (
    NARRATIVE_ERROR_HTTP_STATUS,
    NARRATIVE_ERROR_JSON_PARSE,
    NARRATIVE_ERROR_NETWORK,
    NARRATIVE_ERROR_SCHEMA_VALIDATE,
    NARRATIVE_ERROR_TIMEOUT,
    NarrativeParseError,
)
from app.modules.llm.schemas import NarrativeOutput

_TOKEN_REDACTION_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", re.IGNORECASE)


def sanitize_raw_snippet(raw: object, max_len: int = 200) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        try:
            text = json.dumps(raw, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            text = str(raw)
    else:
        text = str(raw)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _TOKEN_REDACTION_RE.sub("[REDACTED_KEY]", text)
    text = " ".join(text.split())
    text = text.replace("|", "/")
    if not text:
        return None
    return text[:max_len]


def extract_json_fragment(raw_text: str) -> str | None:
    if not raw_text:
        return None
    fenced = _FENCED_JSON_RE.search(raw_text)
    if fenced:
        return fenced.group(1).strip()
    left = raw_text.find("{")
    right = raw_text.rfind("}")
    if left == -1 or right == -1 or right <= left:
        return None
    return raw_text[left : right + 1].strip()


def narrative_error_kind(exc: Exception) -> str:
    if isinstance(exc, NarrativeParseError):
        return exc.error_kind
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return NARRATIVE_ERROR_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return NARRATIVE_ERROR_HTTP_STATUS
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ),
    ):
        return NARRATIVE_ERROR_NETWORK
    return NARRATIVE_ERROR_NETWORK


def narrative_raw_snippet(exc: Exception, raw: object | None) -> str | None:
    if isinstance(exc, NarrativeParseError) and exc.raw_snippet:
        return exc.raw_snippet
    return sanitize_raw_snippet(raw)


def format_narrative_chain_error(
    last_error: Exception | None,
    *,
    error_kind: str | None,
    raw_snippet: str | None,
) -> str:
    detail = f": {last_error}" if last_error else ""
    message = f"narrative provider chain exhausted{detail}"
    if error_kind:
        message = f"{message} | kind={error_kind}"
    if raw_snippet:
        message = f"{message} | raw={raw_snippet}"
    return message


def parse_narrative(raw: object) -> NarrativeOutput:
    parsed_payload: object = raw
    original_raw_snippet = sanitize_raw_snippet(raw)

    if isinstance(parsed_payload, str):
        raw_text = parsed_payload.strip()
        if not raw_text:
            raise NarrativeParseError(
                "narrative json parse error: empty response",
                error_kind=NARRATIVE_ERROR_JSON_PARSE,
                raw_snippet=original_raw_snippet,
            )
        try:
            parsed_payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            fragment = extract_json_fragment(raw_text)
            if fragment:
                try:
                    parsed_payload = json.loads(fragment)
                except json.JSONDecodeError as fragment_exc:
                    raise NarrativeParseError(
                        f"narrative json parse error: {fragment_exc}",
                        error_kind=NARRATIVE_ERROR_JSON_PARSE,
                        raw_snippet=original_raw_snippet,
                    ) from exc
            else:
                raise NarrativeParseError(
                    f"narrative json parse error: {exc}",
                    error_kind=NARRATIVE_ERROR_JSON_PARSE,
                    raw_snippet=original_raw_snippet,
                ) from exc

    try:
        return NarrativeOutput.model_validate(parsed_payload)
    except ValidationError as exc:
        raise NarrativeParseError(
            f"narrative schema validate error: {exc}",
            error_kind=NARRATIVE_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        ) from exc
