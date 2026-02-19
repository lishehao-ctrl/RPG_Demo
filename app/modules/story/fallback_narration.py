from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Fixed stopword set for deterministic token anchors (no external dependency).
EXTRACT_STOPWORDS_EN: set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "their",
    "then",
    "there",
    "they",
    "this",
    "to",
    "was",
    "were",
    "with",
    "you",
}

_TOKEN_RE = re.compile(r"[a-zA-Z]+")
_SYSTEM_ERROR_STYLE_RE = re.compile(
    r"(invalid choice|parse error|unknown choice|unknown action|unknown input)",
    flags=re.IGNORECASE,
)
_INTERNAL_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bNO_INPUT\b"),
    re.compile(r"\bINVALID_CHOICE_ID\b"),
    re.compile(r"\bNO_MATCH\b"),
    re.compile(r"\bLLM_PARSE_ERROR\b"),
    re.compile(r"\bPREREQ_BLOCKED\b"),
    re.compile(r"\bFALLBACK_CONFIG_INVALID\b"),
    re.compile(r"\bREROUTE_LIMIT_REACHED_DEGRADED\b"),
    re.compile(r"\bREROUTED_TARGET_PREREQ_BLOCKED_DEGRADED\b"),
    re.compile(r"\bREROUTED_TARGET_PREREQ_INVALID_SPEC_DEGRADED\b"),
)
_INTERNAL_FIELD_LEAKS: tuple[str, ...] = (
    "next_node_id",
    "__fallback__",
    "choice_id",
    "intent_id",
    "confidence",
    "delta_scale",
)


def _candidate_reason_keys(reason: str | None) -> list[str]:
    raw = str(reason or "").strip().upper()
    if not raw:
        return ["DEFAULT"]
    if raw in {"NO_INPUT", "BLOCKED", "FALLBACK", "DEFAULT"}:
        keys = [raw]
    elif raw in {"PREREQ_BLOCKED"}:
        keys = ["BLOCKED"]
    else:
        keys = ["FALLBACK"]
    if "DEFAULT" not in keys:
        keys.append("DEFAULT")
    return keys


def _ordered_english_tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def tokenize_english(text: str) -> set[str]:
    return set(_ordered_english_tokens(text))


def _resolve_variant_text(value: Any, locale: str) -> str | None:
    if isinstance(value, str):
        return value if value else None
    if not isinstance(value, Mapping):
        return None

    locale_key = str(locale or "en")
    localized = value.get(locale_key)
    if isinstance(localized, str) and localized:
        return localized

    english = value.get("en")
    if isinstance(english, str) and english:
        return english

    for key in sorted(value.keys(), key=lambda item: str(item)):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def select_fallback_skeleton_text(
    text_variants: dict | None,
    reason: str | None,
    locale: str,
) -> str | None:
    variants = text_variants or {}
    if not isinstance(variants, dict):
        return None

    for key in _candidate_reason_keys(reason):
        exact = _resolve_variant_text(variants.get(key), locale)
        if exact:
            return exact
    return None


def build_fallback_narration_context(
    *,
    locale: str,
    node_id: str,
    fallback_reason: str | None,
    player_input: str | None,
    mapping_note: str | None,
    attempted_choice_id: str | None,
    attempted_choice_label: str | None,
    visible_choices: list[dict] | None,
    state_snippet_source: dict | None,
    skeleton_text: str,
) -> dict:
    normalized_visible_choices = []
    for choice in (visible_choices or []):
        if not isinstance(choice, Mapping):
            continue
        choice_id = choice.get("choice_id")
        if choice_id is None:
            choice_id = choice.get("id")
        label = choice.get("display_text")
        if label is None:
            label = choice.get("label")
        if label is None:
            label = choice.get("text")
        normalized_visible_choices.append(
            {
                "id": (str(choice_id) if choice_id is not None else ""),
                "label": (str(label) if label is not None else ""),
            }
        )

    state_source = state_snippet_source if isinstance(state_snippet_source, Mapping) else {}
    state_snippet = {str(key): state_source[key] for key in sorted(state_source.keys(), key=lambda k: str(k))}

    return {
        "locale": str(locale or "en"),
        "node_id": str(node_id),
        "fallback_reason": fallback_reason,
        "player_input": player_input or "",
        "mapping_note": mapping_note or "",
        "attempted_choice_id": attempted_choice_id,
        "attempted_choice_label": attempted_choice_label,
        "visible_choices": normalized_visible_choices,
        "short_recent_summary": [],
        "state_snippet": state_snippet,
        "skeleton_text": skeleton_text,
    }


def extract_skeleton_anchor_tokens(skeleton_text: str, locale: str) -> list[str] | None:
    if str(locale or "").lower() != "en":
        return None

    seen: set[str] = set()
    selected: list[str] = []
    for token in _ordered_english_tokens(skeleton_text):
        if token in seen:
            continue
        seen.add(token)
        if token in EXTRACT_STOPWORDS_EN or len(token) < 4:
            continue
        selected.append(token)
        if len(selected) == 3:
            break
    if len(selected) < 3:
        return None
    return selected


def contains_internal_story_tokens(text: str) -> bool:
    for pattern in _INTERNAL_TOKEN_PATTERNS:
        if pattern.search(text):
            return True
    lowered = str(text or "").lower()
    for field_name in _INTERNAL_FIELD_LEAKS:
        if field_name in lowered:
            return True
    return False


def contains_system_error_style_phrase(text: str) -> bool:
    return _SYSTEM_ERROR_STYLE_RE.search(text) is not None


def validate_polished_text(
    polished: str,
    max_chars: int,
    required_anchor_tokens: list[str] | None = None,
    enforce_error_phrase_denylist: bool = False,
) -> bool:
    if not isinstance(polished, str):
        return False
    if not polished.strip():
        return False
    if len(polished) > int(max_chars):
        return False
    if contains_internal_story_tokens(polished):
        return False
    if enforce_error_phrase_denylist and contains_system_error_style_phrase(polished):
        return False

    if required_anchor_tokens:
        required = [str(t).lower() for t in required_anchor_tokens if str(t).strip()]
        if required:
            polished_tokens = tokenize_english(polished)
            hits = sum(1 for token in required if token in polished_tokens)
            required_hits = 2 if len(required) >= 3 else len(required)
            if hits < required_hits:
                return False
    return True


def safe_polish_text(
    candidate_text: str,
    skeleton_text: str,
    max_chars: int,
    required_anchor_tokens: list[str] | None = None,
    enforce_error_phrase_denylist: bool = False,
) -> str:
    if validate_polished_text(
        candidate_text,
        max_chars=max_chars,
        required_anchor_tokens=required_anchor_tokens,
        enforce_error_phrase_denylist=enforce_error_phrase_denylist,
    ):
        return candidate_text
    return skeleton_text
