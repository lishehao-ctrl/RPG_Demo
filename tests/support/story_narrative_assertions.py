import re

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
    "__fallback__",
    "next_node_id",
    "choice_id",
    "intent_id",
    "confidence",
    "delta_scale",
)

_SYSTEM_ERROR_STYLE_RE = re.compile(
    r"(invalid choice|parse error|unknown choice|unknown action|unknown input)",
    flags=re.IGNORECASE,
)


def assert_no_internal_story_tokens(text: str) -> None:
    for pattern in _INTERNAL_TOKEN_PATTERNS:
        assert pattern.search(text) is None

    lowered = str(text or "").lower()
    for field_name in _INTERNAL_FIELD_LEAKS:
        assert field_name not in lowered


def assert_no_system_error_style_phrases(text: str) -> None:
    assert _SYSTEM_ERROR_STYLE_RE.search(text) is None
