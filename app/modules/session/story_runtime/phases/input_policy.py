from __future__ import annotations

import re

_BLOCK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PROMPT_INJECTION", re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE)),
    ("PROMPT_INJECTION", re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE)),
    ("PROMPT_INJECTION", re.compile(r"\bdeveloper\s+message\b", re.IGNORECASE)),
    ("CODE_INJECTION", re.compile(r"<script\b", re.IGNORECASE)),
    ("SQL_INJECTION", re.compile(r"\bdrop\s+table\b", re.IGNORECASE)),
    ("SHELL_ABUSE", re.compile(r"\brm\s+-rf\b", re.IGNORECASE)),
    ("JAILBREAK", re.compile(r"\bjailbreak\b", re.IGNORECASE)),
)


def apply_input_policy(player_input: str | None, *, max_chars: int = 1024) -> tuple[str | None, bool, str | None]:
    raw = " ".join(str(player_input or "").split()).strip()
    if not raw:
        return None, False, None

    if max_chars > 0 and len(raw) > max_chars:
        raw = raw[:max_chars].rstrip()

    for reason, pattern in _BLOCK_PATTERNS:
        if pattern.search(raw):
            return raw, True, reason
    return raw, False, None
