from __future__ import annotations

import re
from typing import Any


def normalize_whitespace(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def trim_text(value: Any, limit: int) -> str:
    text = normalize_whitespace(value)
    if len(text) <= limit:
        return text
    clipped = text[: limit + 1]
    for separator in (". ", "; ", ", "):
        idx = clipped.rfind(separator)
        if idx >= max(24, limit // 3):
            return clipped[: idx + 1].strip()
    return text[:limit].rstrip(" ,;")


def coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip().casefold()
    if not text:
        return default
    mappings = {
        "low": 1,
        "medium": 2,
        "moderate": 2,
        "high": 3,
        "critical": 4,
        "severe": 4,
    }
    if text in mappings:
        return mappings[text]
    try:
        return int(float(text))
    except Exception:  # noqa: BLE001
        return default


def unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        lowered = item.casefold()
        if not item or lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(item)
    return ordered


def normalize_id_list(
    value: Any,
    *,
    limit: int,
    text_limit: int = 80,
) -> list[str]:
    if isinstance(value, str):
        items = [value]
    else:
        items = list(value or [])
    normalized = [
        trim_text(item, text_limit)
        for item in items[:limit]
        if isinstance(item, str) and trim_text(item, text_limit)
    ]
    return unique_preserve(normalized)


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", (value or "").casefold())
    return normalized.strip("_") or "item"
