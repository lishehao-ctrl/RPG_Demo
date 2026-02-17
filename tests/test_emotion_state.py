import uuid

from app.modules.narrative.emotion_state import DEFAULT_EMOTION_WINDOW, build_emotion_state, score_to_band


def test_emotion_score_deterministic_and_clamped() -> None:
    session_id = uuid.uuid4()
    character_id = uuid.uuid4()

    rows_high = [
        {"id": str(uuid.uuid4()), "affection_delta": [{"char_id": str(character_id), "dim": "emotion", "delta": 10}]},
        {"id": str(uuid.uuid4()), "affection_delta": [{"char_id": str(character_id), "dim": "emotion", "delta": 10}]},
    ]
    out1 = build_emotion_state(
        session_id=session_id,
        character={"id": character_id, "name": "A", "baseline": 95},
        story_id="default",
        action_rows=rows_high,
        window=DEFAULT_EMOTION_WINDOW,
    )
    out2 = build_emotion_state(
        session_id=session_id,
        character={"id": character_id, "name": "A", "baseline": 95},
        story_id="default",
        action_rows=rows_high,
        window=DEFAULT_EMOTION_WINDOW,
    )
    assert out1["score"] == 100
    assert out2 == out1

    rows_low = [
        {"id": str(uuid.uuid4()), "affection_delta": [{"char_id": str(character_id), "dim": "emotion", "delta": -10}]},
        {"id": str(uuid.uuid4()), "affection_delta": [{"char_id": str(character_id), "dim": "emotion", "delta": -10}]},
    ]
    low = build_emotion_state(
        session_id=session_id,
        character={"id": character_id, "name": "A", "baseline": -95},
        story_id="default",
        action_rows=rows_low,
        window=DEFAULT_EMOTION_WINDOW,
    )
    assert low["score"] == -100


def test_score_to_band_story_specific_breakpoints() -> None:
    score = 25
    default_band = score_to_band("default", score)
    alt_band = score_to_band("noir", score)

    assert default_band != alt_band
