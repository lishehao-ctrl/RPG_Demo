from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(normalize_text(text)))


def match_choice_by_player_input(*, player_input: str, choices: list[dict]) -> tuple[str | None, float]:
    input_tokens = tokenize(player_input)
    if not input_tokens:
        return None, 0.0

    best_choice_id: str | None = None
    best_score = 0.0
    for choice in choices:
        choice_id = str(choice.get("choice_id") or "").strip()
        if not choice_id:
            continue

        score = 0.0
        text_tokens = tokenize(str(choice.get("text") or ""))
        intent_tags = [normalize_text(tag) for tag in (choice.get("intent_tags") or []) if str(tag).strip()]
        intent_tokens = set()
        for tag in intent_tags:
            intent_tokens |= tokenize(tag)

        overlap_text = input_tokens & text_tokens
        overlap_intent = input_tokens & intent_tokens
        score += len(overlap_text) * 2.0
        score += len(overlap_intent) * 3.0

        if normalize_text(player_input) == normalize_text(str(choice.get("text") or "")):
            score += 4.0

        if score > best_score:
            best_score = score
            best_choice_id = choice_id

    if best_score <= 0:
        return None, 0.0

    confidence = min(0.95, 0.55 + best_score / 10.0)
    return best_choice_id, round(confidence, 2)


def is_risky_input(player_input: str) -> bool:
    lower = normalize_text(player_input)
    danger_patterns = (
        "ignore previous",
        "system prompt",
        "developer instruction",
        "<script",
        "drop table",
        "sudo",
    )
    return any(pat in lower for pat in danger_patterns)
