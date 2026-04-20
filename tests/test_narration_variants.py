from __future__ import annotations

from rpg_backend.play_v2.narration_variants import (
    NarrationVariantSampler,
    append_narration_history,
    canonicalize_pattern,
    canonicalize_phrase,
    pattern_fingerprint,
    phrase_fingerprint,
)


def test_canonicalize_phrase_strips_punctuation_and_particle() -> None:
    assert canonicalize_phrase("  这一下，真的要翻车了。。  ") == "这一下真的要翻车"


def test_sampler_avoids_recent_fingerprints_when_candidates_sufficient() -> None:
    recent = [phrase_fingerprint("第一句"), phrase_fingerprint("第二句")]
    sampler = NarrationVariantSampler(recent_fingerprints=recent, hard_block_terms=(), max_recent=4)

    picked = sampler.sample_phrase(("第一句", "第二句", "第三句"), fallback="第一句")

    assert picked == "第三句"


def test_sampler_falls_back_to_non_empty_when_pool_is_constrained() -> None:
    sampler = NarrationVariantSampler(
        recent_fingerprints=(phrase_fingerprint("站边"),),
        hard_block_terms=("站边",),
        max_recent=4,
    )

    picked = sampler.sample_phrase(("站边",), fallback="备用句")

    assert picked in {"站边", "备用句"}
    assert picked


def test_canonicalize_pattern_masks_entities_and_arena_tokens() -> None:
    pattern = canonicalize_pattern("镜头会先记录江烨失手，台下也会把苏清贴上标签。", redact_terms=("江烨", "苏清"))
    assert "江烨" not in pattern
    assert "苏清" not in pattern
    assert "镜头" not in pattern
    assert "台下" not in pattern
    assert "<场域>" in pattern


def test_append_narration_history_keeps_recent_window_of_four() -> None:
    fingerprints: list[str] = []
    phrases: list[str] = []
    patterns: list[str] = []
    for index in range(1, 7):
        fingerprints, phrases, patterns = append_narration_history(
            recent_fingerprints=fingerprints,
            recent_phrases=phrases,
            recent_pattern_fingerprints=patterns,
            narration=f"第{index}句",
            max_recent=4,
        )

    assert len(fingerprints) == 4
    assert len(phrases) == 4
    assert len(patterns) == 4
    assert phrases == ["第3句", "第4句", "第5句", "第6句"]
    assert patterns[-1] == pattern_fingerprint("第6句")


def test_append_narration_history_duplicate_fingerprint_moves_to_tail() -> None:
    fingerprints = [
        phrase_fingerprint("第1句"),
        phrase_fingerprint("同一句。"),
        phrase_fingerprint("第3句"),
        phrase_fingerprint("第4句"),
    ]
    phrases = ["第1句", "同一句。", "第3句", "第4句"]
    patterns = [pattern_fingerprint(item) for item in phrases]

    next_fingerprints, next_phrases, next_patterns = append_narration_history(
        recent_fingerprints=fingerprints,
        recent_phrases=phrases,
        recent_pattern_fingerprints=patterns,
        narration="同一句",
        max_recent=4,
    )

    assert len(next_fingerprints) == 4
    assert len(next_phrases) == 4
    assert len(next_patterns) == 4
    assert next_phrases == ["第1句", "第3句", "第4句", "同一句"]
    assert next_fingerprints.count(phrase_fingerprint("同一句")) == 1
    assert next_fingerprints[-1] == phrase_fingerprint("同一句")
