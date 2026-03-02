from __future__ import annotations

import pytest

from app.eval.story_quality_judge import StoryQualityJudge, StoryQualityJudgeError


def _valid_payload() -> dict[str, object]:
    return {
        "overall_score": 8.2,
        "playability_score": 8.1,
        "coherence_score": 8.0,
        "tension_curve_score": 7.9,
        "choice_impact_score": 8.3,
        "prompt_fidelity_score": 8.4,
        "major_issues": ["midgame stakes spike is abrupt"],
        "strengths": ["clear objective ladder", "costly decisions remain playable"],
        "verdict": "pass",
    }


def test_judge_response_schema_valid() -> None:
    parsed = StoryQualityJudge.parse_result_payload(_valid_payload())
    assert parsed.overall_score == 8.2
    assert parsed.prompt_fidelity_score == 8.4
    assert parsed.verdict == "pass"


def test_judge_response_schema_invalid_raises() -> None:
    payload = _valid_payload()
    payload["verdict"] = "excellent"
    with pytest.raises(StoryQualityJudgeError) as exc_info:
        StoryQualityJudge.parse_result_payload(payload)
    assert exc_info.value.error_type == "judge_schema_invalid"


def test_judge_parser_handles_missing_fields() -> None:
    payload = _valid_payload()
    payload.pop("overall_score")
    with pytest.raises(StoryQualityJudgeError) as exc_info:
        StoryQualityJudge.parse_result_payload(payload)
    assert exc_info.value.error_type == "judge_schema_invalid"
    assert "overall_score" in str(exc_info.value)

