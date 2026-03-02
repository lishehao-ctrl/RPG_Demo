from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from rpg_backend.config.settings import get_settings
from rpg_backend.observability.context import get_request_id

LOGGER_NAME = "rpg_backend"
_configured = False


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, service: str, env: str):
        super().__init__()
        self.service = service
        self.env = env

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "env": self.env,
            "event": getattr(record, "event", "log"),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update({k: v for k, v in fields.items() if v is not None})

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _parse_log_level(name: str) -> int:
    normalized = (name or "INFO").strip().upper()
    return getattr(logging, normalized, logging.INFO)


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(_parse_log_level(settings.obs_log_level))
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service=settings.app_name, env=settings.app_env))
    logger.addHandler(handler)
    _configured = True


def log_event(event: str, *, level: str = "INFO", request_id: str | None = None, **fields: Any) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        configure_logging()
        logger = logging.getLogger(LOGGER_NAME)
    logger.log(
        _parse_log_level(level),
        "",
        extra={
            "event": event,
            "request_id": request_id,
            "fields": fields,
        },
    )


def text_digest_12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build_input_log_fields(
    action_input: dict[str, Any],
    *,
    redact_text: bool,
) -> dict[str, Any]:
    input_type = str(action_input.get("type") or "unknown")
    fields: dict[str, Any] = {"input_type": input_type}
    if input_type == "text":
        value = str(action_input.get("text") or "")
        fields["input_text_len"] = len(value)
        fields["input_text_sha256_12"] = text_digest_12(value)
        if not redact_text:
            fields["input_text"] = value
    elif input_type == "button":
        fields["input_move_id"] = action_input.get("move_id")
    return fields
