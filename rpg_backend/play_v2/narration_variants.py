from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import random
import re
from typing import Sequence

from rpg_backend.author.normalize import normalize_whitespace, trim_text

DEFAULT_RECENT_WINDOW = 4
DEFAULT_HARD_BLOCK_TERMS: tuple[str, ...] = ("站边", "体面", "回咬")
DEFAULT_PATTERN_REDACT_TERMS: tuple[str, ...] = (
    "镜头",
    "热搜",
    "公屏",
    "台下",
    "评审",
    "名额",
    "主桌",
    "会议室",
    "家宴",
    "社团",
    "熟人",
)

_PUNCTUATION_RE = re.compile(r"[。！？!?；;，,、:：…\s]+")
_TRAILING_PARTICLES = ("而已", "罢了", "了", "呢", "吧", "啊", "呀", "嘛")
_PATTERN_ENTITY_RE = re.compile(r"(你和|把|对)[\u4e00-\u9fffA-Za-z0-9]{1,8}")
_PATTERN_DIGIT_RE = re.compile(r"[0-9０-９]+")


def canonicalize_phrase(text: str | None) -> str:
    normalized = normalize_whitespace(str(text or ""))
    normalized = _PUNCTUATION_RE.sub("", normalized)
    for particle in _TRAILING_PARTICLES:
        if len(normalized) > len(particle) + 2 and normalized.endswith(particle):
            normalized = normalized[: -len(particle)]
            break
    return trim_text(normalized, 260)


def phrase_fingerprint(text: str | None) -> str:
    canonical = canonicalize_phrase(text)
    if not canonical:
        return ""
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def canonicalize_pattern(text: str | None, *, redact_terms: Sequence[str] = ()) -> str:
    normalized = normalize_whitespace(str(text or ""))
    for raw in (*DEFAULT_PATTERN_REDACT_TERMS, *tuple(redact_terms)):
        token = normalize_whitespace(str(raw or "")).strip()
        if not token:
            continue
        normalized = normalized.replace(token, "<场域>")
    normalized = _PATTERN_ENTITY_RE.sub(lambda match: f"{match.group(1)}<实体>", normalized)
    normalized = _PATTERN_DIGIT_RE.sub("<数值>", normalized)
    normalized = _PUNCTUATION_RE.sub("", normalized)
    normalized = re.sub(r"(?:<实体>){2,}", "<实体>", normalized)
    normalized = re.sub(r"(?:<场域>){2,}", "<场域>", normalized)
    return trim_text(normalized, 260)


def pattern_fingerprint(text: str | None, *, redact_terms: Sequence[str] = ()) -> str:
    canonical = canonicalize_pattern(text, redact_terms=redact_terms)
    if not canonical:
        return ""
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def _contains_hard_block_term(text: str, hard_block_terms: Sequence[str]) -> bool:
    if not text:
        return False
    lowered = text.casefold()
    for term in hard_block_terms:
        candidate = str(term or "").strip()
        if candidate and candidate.casefold() in lowered:
            return True
    return False


@dataclass
class NarrationVariantSampler:
    recent_fingerprints: Sequence[str] = ()
    hard_block_terms: Sequence[str] = ()
    max_recent: int = DEFAULT_RECENT_WINDOW
    rng: random.Random = field(default_factory=random.SystemRandom)
    _recent: set[str] = field(default_factory=set, init=False)
    _used_fingerprints: set[str] = field(default_factory=set, init=False)
    _used_canonicals: set[str] = field(default_factory=set, init=False)
    diversity_guard_hits: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._recent = {
            str(item).strip()
            for item in list(self.recent_fingerprints)[-max(1, self.max_recent) :]
            if str(item).strip()
        }

    def sample_phrase(self, candidates: Sequence[str], *, fallback: str | None = None) -> str:
        cleaned_candidates = [trim_text(normalize_whitespace(str(item or "")), 4000) for item in candidates]
        cleaned_candidates = [item for item in cleaned_candidates if item]
        fallback_text = trim_text(normalize_whitespace(str(fallback or "")), 4000)
        if not cleaned_candidates:
            return fallback_text

        tier_best: list[str] = []
        tier_recent_only: list[str] = []
        tier_hard_block_only: list[str] = []
        tier_fallback: list[str] = []

        for text in cleaned_candidates:
            canonical = canonicalize_phrase(text)
            fingerprint = phrase_fingerprint(text)
            hard_blocked = _contains_hard_block_term(text, self.hard_block_terms)
            repeated_recent = bool(fingerprint and fingerprint in self._recent)
            repeated_turn = bool(fingerprint and fingerprint in self._used_fingerprints)
            repeated_canonical = bool(canonical and canonical in self._used_canonicals)

            if not hard_blocked and not repeated_recent and not repeated_turn and not repeated_canonical:
                tier_best.append(text)
                continue
            if not hard_blocked and not repeated_turn and not repeated_canonical:
                tier_recent_only.append(text)
                continue
            if not repeated_turn and not repeated_canonical:
                tier_hard_block_only.append(text)
                continue
            tier_fallback.append(text)

        for index, pool in enumerate((tier_best, tier_recent_only, tier_hard_block_only, tier_fallback)):
            if pool:
                selected = self.rng.choice(pool)
                if index > 0:
                    self.diversity_guard_hits += 1
                selected_fingerprint = phrase_fingerprint(selected)
                selected_canonical = canonicalize_phrase(selected)
                if selected_fingerprint:
                    self._used_fingerprints.add(selected_fingerprint)
                if selected_canonical:
                    self._used_canonicals.add(selected_canonical)
                return selected
        return fallback_text


def append_narration_history(
    *,
    recent_fingerprints: Sequence[str],
    recent_phrases: Sequence[str],
    recent_pattern_fingerprints: Sequence[str] = (),
    narration: str,
    max_recent: int = DEFAULT_RECENT_WINDOW,
    pattern_redact_terms: Sequence[str] = (),
) -> tuple[list[str], list[str], list[str]]:
    cap = max(1, int(max_recent))
    cleaned_fingerprints = [str(item).strip() for item in recent_fingerprints if str(item).strip()]
    cleaned_phrases = [
        trim_text(normalize_whitespace(str(item)), 320)
        for item in recent_phrases
        if trim_text(normalize_whitespace(str(item)), 320)
    ]
    cleaned_patterns = [str(item).strip() for item in recent_pattern_fingerprints if str(item).strip()]

    aligned_len = min(len(cleaned_fingerprints), len(cleaned_phrases))
    aligned_patterns: list[str] = []
    pairs: list[tuple[str, str, str]] = []
    if aligned_len > 0:
        aligned_fingerprints = cleaned_fingerprints[-aligned_len:]
        aligned_phrases = cleaned_phrases[-aligned_len:]
        if len(cleaned_patterns) >= aligned_len:
            aligned_patterns = cleaned_patterns[-aligned_len:]
        else:
            aligned_patterns = [
                pattern_fingerprint(item, redact_terms=pattern_redact_terms)
                for item in aligned_phrases
            ]
        pairs = list(zip(aligned_fingerprints, aligned_phrases, aligned_patterns))

    fingerprint = phrase_fingerprint(narration)
    phrase = trim_text(normalize_whitespace(narration), 320)
    pattern = pattern_fingerprint(narration, redact_terms=pattern_redact_terms)
    if fingerprint and phrase and pattern:
        pairs.append((fingerprint, phrase, pattern))

    deduped_latest: dict[str, tuple[str, str]] = {}
    for fp, text, pt in pairs:
        if not fp or not text or not pt:
            continue
        deduped_latest.pop(fp, None)
        deduped_latest[fp] = (text, pt)

    recent_pairs = list(deduped_latest.items())[-cap:]
    return (
        [item[0] for item in recent_pairs],
        [item[1][0] for item in recent_pairs],
        [item[1][1] for item in recent_pairs],
    )
