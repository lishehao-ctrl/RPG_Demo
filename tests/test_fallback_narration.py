from app.modules.story.fallback_narration import (
    build_fallback_narration_context,
    contains_internal_story_tokens,
    contains_system_error_style_phrase,
    extract_skeleton_anchor_tokens,
    safe_polish_text,
    select_fallback_skeleton_text,
    validate_polished_text,
)


def test_select_fallback_skeleton_text_neutral_keys_only() -> None:
    variants = {
        "NO_INPUT": "no input",
        "BLOCKED": "blocked",
        "FALLBACK": "fallback",
        "DEFAULT": "default",
    }

    assert select_fallback_skeleton_text(variants, "NO_INPUT", "en") == "no input"
    assert select_fallback_skeleton_text(variants, "PREREQ_BLOCKED", "en") == "blocked"
    assert select_fallback_skeleton_text(variants, "INVALID_CHOICE_ID", "en") == "fallback"
    assert select_fallback_skeleton_text(variants, "SOME_UNKNOWN_REASON", "en") == "fallback"
    assert select_fallback_skeleton_text(variants, None, "en") == "default"


def test_select_fallback_skeleton_text_locale_resolution() -> None:
    variants = {
        "FALLBACK": {"en": "fallback en", "zh": "回退文案"},
        "DEFAULT": "default en",
    }

    assert select_fallback_skeleton_text(variants, "FALLBACK", "zh") == "回退文案"
    assert select_fallback_skeleton_text(variants, "FALLBACK", "ja") == "fallback en"


def test_build_fallback_narration_context_has_deterministic_fields() -> None:
    ctx = build_fallback_narration_context(
        locale="en",
        node_id="n1",
        fallback_reason="FALLBACK",
        player_input="hello",
        mapping_note="AMBIGUOUS_FIRST_MATCH",
        attempted_choice_id="c1",
        attempted_choice_label="Study",
        visible_choices=[{"choice_id": "c1", "display_text": "Study"}],
        state_snippet_source={"money": 10, "energy": 5},
        skeleton_text="You pause and reassess.",
    )
    assert ctx["node_id"] == "n1"
    assert ctx["fallback_reason"] == "FALLBACK"
    assert ctx["visible_choices"] == [{"id": "c1", "label": "Study"}]


def test_extract_skeleton_anchor_tokens_for_en() -> None:
    anchors = extract_skeleton_anchor_tokens("You pause briefly before choosing another option.", "en")
    assert anchors is not None
    assert len(anchors) >= 2


def test_validate_polished_text_rejects_internal_tokens_and_fields() -> None:
    assert validate_polished_text("contains NO_MATCH", max_chars=200) is False
    assert validate_polished_text("mentions next_node_id", max_chars=200) is False
    assert validate_polished_text("mentions __fallback__", max_chars=200) is False


def test_validate_polished_text_rejects_system_error_style_phrase_when_enabled() -> None:
    assert validate_polished_text(
        "This says unknown input and should fail.",
        max_chars=200,
        enforce_error_phrase_denylist=True,
    ) is False


def test_safe_polish_text_falls_back_to_skeleton() -> None:
    skeleton = "You hesitate and watch the moment pass."
    polished = safe_polish_text(
        candidate_text="contains INVALID_CHOICE_ID token",
        skeleton_text=skeleton,
        max_chars=200,
    )
    assert polished == skeleton


def test_contains_helpers() -> None:
    assert contains_internal_story_tokens("REROUTE_LIMIT_REACHED_DEGRADED") is True
    assert contains_internal_story_tokens("Clean player-facing narration.") is False
    assert contains_system_error_style_phrase("This says parse error.") is True
    assert contains_system_error_style_phrase("This is narrative only.") is False
