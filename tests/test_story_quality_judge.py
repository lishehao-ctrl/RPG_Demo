from __future__ import annotations

import asyncio
import pytest

from rpg_backend.eval.story_quality_judge import StoryQualityJudge, StoryQualityJudgeError
from rpg_backend.llm.json_gateway import JsonGatewayError, JsonGatewayResult


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


def _new_judge_for_retry_tests(max_retries: int = 3) -> StoryQualityJudge:
    judge = StoryQualityJudge.__new__(StoryQualityJudge)
    judge.model = "judge-model"
    judge.max_retries = max_retries
    judge.temperature = 0.1
    judge.timeout_seconds = 10.0
    return judge


def test_judge_does_not_retry_on_401(monkeypatch) -> None:
    judge = _new_judge_for_retry_tests(max_retries=3)
    call_count = 0

    class _FailingGateway:
        async def call_json_object(self, **_kwargs):  # noqa: ANN003, ANN201
            nonlocal call_count
            call_count += 1
            raise JsonGatewayError(
                error_code="json_task_http_error",
                message="status=401",
                retryable=False,
                status_code=401,
                attempts=1,
            )

    judge._json_gateway = _FailingGateway()

    with pytest.raises(StoryQualityJudgeError) as exc_info:
        asyncio.run(
            judge.evaluate(
                prompt_text="prompt",
                expected_tone="tense",
                pack_summary={"scenes": 14},
                transcript_summary={"steps": 14},
                metrics={"completion_rate": 1.0},
            )
        )

    assert exc_info.value.error_type == "judge_failed"
    assert "status=401" in str(exc_info.value)
    assert call_count == 1


def test_judge_respects_gateway_attempts_on_success(monkeypatch) -> None:
    judge = _new_judge_for_retry_tests(max_retries=3)
    call_count = 0

    class _FlakyGateway:
        async def call_json_object(self, **_kwargs):  # noqa: ANN003, ANN201
            nonlocal call_count
            call_count += 1
            return JsonGatewayResult(
                payload=_valid_payload(),
                attempts=3,
                duration_ms=120,
            )

    judge._json_gateway = _FlakyGateway()

    decision = asyncio.run(
        judge.evaluate(
            prompt_text="prompt",
            expected_tone="tense",
            pack_summary={"scenes": 14},
            transcript_summary={"steps": 14},
            metrics={"completion_rate": 1.0},
        )
    )

    assert decision.attempts == 3
    assert decision.result.verdict == "pass"
    assert call_count == 1


def test_judge_returns_failed_when_gateway_raises_runtime_error(monkeypatch) -> None:
    judge = _new_judge_for_retry_tests(max_retries=3)

    class _RuntimeFailingGateway:
        async def call_json_object(self, **_kwargs):  # noqa: ANN003, ANN201
            nonlocal call_count
            call_count += 1
            raise RuntimeError("upstream exploded")

    call_count = 0
    judge._json_gateway = _RuntimeFailingGateway()

    with pytest.raises(StoryQualityJudgeError) as exc_info:
        asyncio.run(
            judge.evaluate(
                prompt_text="prompt",
                expected_tone="tense",
                pack_summary={"scenes": 14},
                transcript_summary={"steps": 14},
                metrics={"completion_rate": 1.0},
            )
        )

    assert exc_info.value.error_type == "judge_failed"
    assert "upstream exploded" in str(exc_info.value)
    assert call_count == 1
