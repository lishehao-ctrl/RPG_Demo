from app.modules.story.fallback_narration import (
    build_free_input_fallback_narrative_text,
    build_fallback_narration_context,
    contains_internal_story_tokens,
    contains_system_error_style_phrase,
    extract_skeleton_anchor_tokens,
    naturalize_narrative_tone,
    sanitize_rejecting_tone,
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


def test_build_free_input_fallback_narrative_text_acknowledge_and_redirect() -> None:
    text = build_free_input_fallback_narrative_text(
        player_input="Play RPG game with Alice and talk through strategy",
        selected_choice_label="Walk with Alice before class",
        selected_action_id="date",
    )
    lowered = text.lower()
    assert "steer toward" in lowered
    assert "alice" in lowered
    assert "follow through on walk with alice before class" in lowered
    assert '"' not in text
    for blocked in ("for this turn", "the scene", "story keeps moving"):
        assert blocked not in lowered


def test_build_free_input_fallback_narrative_text_avoids_rejecting_tone_words() -> None:
    text = build_free_input_fallback_narrative_text(
        player_input="unclear fuzzy invalid wrong input cannot understand",
        selected_choice_label=None,
        selected_action_id="rest",
    )
    lowered = text.lower()
    for blocked in ("fuzzy", "unclear", "invalid", "wrong input", "cannot understand"):
        assert blocked not in lowered


def test_build_free_input_fallback_narrative_text_paraphrases_food_intent_without_quote() -> None:
    text = build_free_input_fallback_narrative_text(
        player_input="Having a Chick-fila",
        selected_choice_label=None,
        selected_action_id="rest",
    )
    lowered = text.lower()
    assert "chick-fila" in lowered
    assert "having a chick-fila" not in lowered
    assert '"' not in text
    assert "pause to catch your breath and recover" in lowered


def test_build_free_input_fallback_narrative_text_includes_subtle_quest_nudge_when_provided() -> None:
    text = build_free_input_fallback_narrative_text(
        player_input="study tonight",
        selected_choice_label=None,
        selected_action_id="study",
        quest_nudge_text="the week's plan still has a clear next step",
    )
    lowered = text.lower()
    assert "while the week's plan still has a clear next step" in lowered
    for blocked in ("main quest", "side quest", "objective", "stage", "milestone"):
        assert blocked not in lowered


def test_naturalize_narrative_tone_soft_avoids_system_like_phrases() -> None:
    source = "For this turn, the scene responds and the story keeps moving."
    cleaned = naturalize_narrative_tone(source).lower()
    assert "for this turn" not in cleaned
    assert "the scene" not in cleaned
    assert "story keeps moving" not in cleaned


def test_sanitize_rejecting_tone_rewrites_blocked_words() -> None:
    source = "Your intention is fuzzy and unclear, invalid, wrong input, cannot understand."
    cleaned = sanitize_rejecting_tone(source).lower()
    for blocked in ("fuzzy", "unclear", "invalid", "wrong input", "cannot understand"):
        assert blocked not in cleaned
