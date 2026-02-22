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
_INPUT_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_SYSTEM_ERROR_STYLE_RE = re.compile(
    r"(invalid choice|parse error|unknown choice|unknown action|unknown input)",
    flags=re.IGNORECASE,
)
_REJECTION_TONE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfuzzy\b", flags=re.IGNORECASE), "off-beat"),
    (re.compile(r"\bunclear\b", flags=re.IGNORECASE), "open"),
    (re.compile(r"\binvalid\b", flags=re.IGNORECASE), "off-track"),
    (re.compile(r"\bwrong input\b", flags=re.IGNORECASE), "off-beat attempt"),
    (re.compile(r"\bcannot understand\b", flags=re.IGNORECASE), "can still work with this"),
)
_SOFT_AVOID_TONE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfor this turn\b", flags=re.IGNORECASE), "in this moment"),
    (re.compile(r"\bthis turn\b", flags=re.IGNORECASE), "this moment"),
    (re.compile(r"\bthe scene\b", flags=re.IGNORECASE), "the moment around you"),
    (re.compile(r"\bstory keeps moving\b", flags=re.IGNORECASE), "the day keeps moving forward"),
    (re.compile(r"\bscene responds\b", flags=re.IGNORECASE), "moment answers"),
    (re.compile(r"\bscene reacts\b", flags=re.IGNORECASE), "world reacts"),
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
_LEADING_FILLER_TOKENS: set[str] = {
    "a",
    "an",
    "for",
    "having",
    "have",
    "i",
    "i'm",
    "im",
    "just",
    "like",
    "please",
    "to",
    "wanna",
    "want",
}
_TRAILING_FILLER_TOKENS: set[str] = {"a", "an", "and", "for", "please", "the", "to", "with"}
_FOOD_INTENT_TOKENS: set[str] = {
    "bite",
    "breakfast",
    "burger",
    "chick-fil-a",
    "chick-fila",
    "chickfila",
    "dinner",
    "eat",
    "eating",
    "food",
    "lunch",
    "meal",
    "snack",
    "shake",
    "shack",
}
_LOW_SIGNAL_INPUT_TOKENS: set[str] = {"anything", "idk", "nonsense", "random", "whatever"}


def _clean_player_input(player_input: str | None, *, max_len: int = 96) -> str:
    cleaned = " ".join(str(player_input or "").split())
    cleaned = cleaned.strip(" \"'`.,!?;:")
    if len(cleaned) <= max_len:
        return cleaned
    return f"{cleaned[:max_len].rstrip()}..."


def _intent_tokens(player_input: str | None, *, max_tokens: int = 6) -> list[str]:
    cleaned = _clean_player_input(player_input)
    if not cleaned:
        return []
    tokens = _INPUT_TOKEN_RE.findall(cleaned)
    while tokens and tokens[0].lower() in _LEADING_FILLER_TOKENS:
        tokens.pop(0)
    while tokens and tokens[-1].lower() in _TRAILING_FILLER_TOKENS:
        tokens.pop()
    return tokens[:max_tokens]


def _paraphrase_player_intent(player_input: str | None) -> str | None:
    tokens = _intent_tokens(player_input)
    if not tokens:
        return None
    lowered = [token.lower() for token in tokens]
    if len(tokens) == 1 and lowered[0] in _LOW_SIGNAL_INPUT_TOKENS:
        return None

    if "with" in lowered:
        idx = lowered.index("with")
        partners = [token for token in tokens[idx + 1 : idx + 3] if token.lower() not in _TRAILING_FILLER_TOKENS]
        if partners:
            return f"spending a little time with {' '.join(partners)}"

    if any(token in _FOOD_INTENT_TOKENS for token in lowered):
        brand = next(
            (
                token
                for token in tokens
                if token.lower() in {"chick-fil-a", "chick-fila", "chickfila"} or "-" in token
            ),
            None,
        )
        if brand is None and len(tokens) >= 2 and tokens[0][:1].isupper() and tokens[1][:1].isupper():
            brand = f"{tokens[0]} {tokens[1]}"
        if brand:
            return f"grabbing a quick bite at {brand}"
        return "grabbing a quick bite"

    if lowered[0] in {"play", "playing"} and len(tokens) > 1:
        return f"starting {' '.join(tokens[1:5])}"

    if len(tokens) <= 2:
        return f"making a quick move toward {' '.join(tokens[:2])}"
    return f"pushing toward {' '.join(tokens[:5])}"


def _friendly_action_phrase(selected_choice_label: str | None, selected_action_id: str | None) -> str:
    choice_label = " ".join(str(selected_choice_label or "").split())
    if choice_label:
        return f"follow through on {choice_label}"

    action_id = str(selected_action_id or "").strip().lower()
    action_map = {
        "study": "head to class and focus on your notes",
        "work": "pick up a short paid shift",
        "rest": "pause to catch your breath and recover",
        "date": "spend a calm stretch connecting with someone",
    }
    if action_id in action_map:
        return action_map[action_id]
    if action_id:
        return f"commit to {action_id.replace('_', ' ')}"
    return "take the closest available move"


def _friendly_action_consequence(selected_choice_label: str | None, selected_action_id: str | None) -> str:
    if str(selected_choice_label or "").strip():
        return "the choice lands cleanly and gives your next decision more direction"

    action_id = str(selected_action_id or "").strip().lower()
    action_map = {
        "study": "the effort costs energy while your focus gets sharper",
        "work": "your wallet gets a little heavier while the clock keeps pushing forward",
        "rest": "your breathing settles and your footing steadies",
        "date": "the connection warms and the next decision feels easier",
    }
    if action_id in action_map:
        return action_map[action_id]
    return "the pace steadies and the next beat becomes clear"


def sanitize_rejecting_tone(text: str) -> str:
    out = str(text or "")
    for pattern, replacement in _REJECTION_TONE_REPLACEMENTS:
        out = pattern.sub(replacement, out)
    return " ".join(out.split()).strip()


def naturalize_narrative_tone(text: str) -> str:
    out = str(text or "")
    for pattern, replacement in _SOFT_AVOID_TONE_REPLACEMENTS:
        out = pattern.sub(replacement, out)
    return " ".join(out.split()).strip()


def build_free_input_fallback_narrative_text(
    *,
    player_input: str | None,
    selected_choice_label: str | None,
    selected_action_id: str | None,
    quest_nudge_text: str | None = None,
) -> str:
    intent_phrase = _paraphrase_player_intent(player_input)
    if intent_phrase:
        first = f"You steer toward {intent_phrase}, and the moment gives you a workable opening."
    else:
        first = "You make a quick call under pressure, and the moment still gives you room to act."
    second = (
        f"You {_friendly_action_phrase(selected_choice_label, selected_action_id)}, "
        f"and {_friendly_action_consequence(selected_choice_label, selected_action_id)}."
    )
    quest_hint = " ".join(str(quest_nudge_text or "").split()).strip(" .")
    if quest_hint:
        second = second[:-1] + f", while {quest_hint}."
    return naturalize_narrative_tone(sanitize_rejecting_tone(f"{first} {second}"))


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
