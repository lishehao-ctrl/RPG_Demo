import uuid

import pytest

from app.config import settings
from app.modules.llm.adapter import LLMRuntime, LLMTimeoutProfile
from app.modules.llm.base import LLMProvider
from app.modules.llm.prompts import PromptEnvelope


class _DbStub:
    def __init__(self) -> None:
        self.rows = []

    def add(self, row) -> None:  # noqa: ANN001
        self.rows.append(row)


class _RecordingProvider(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt: str,
        *,
        request_id: str,
        timeout_s: float | None,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "request_id": request_id,
                "timeout_s": timeout_s,
                "model": model,
                "connect_timeout_s": connect_timeout_s,
                "read_timeout_s": read_timeout_s,
                "write_timeout_s": write_timeout_s,
                "pool_timeout_s": pool_timeout_s,
                "max_tokens_override": max_tokens_override,
                "temperature_override": temperature_override,
                "messages_override": messages_override,
            }
        )
        return (
            {"narrative_text": "ok"},
            {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "latency_ms": 1,
                "status": "success",
                "error_message": None,
            },
        )


class _SequenceProvider(LLMProvider):
    name = "fake"

    def __init__(self, payloads: list[object]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt: str,
        *,
        request_id: str,
        timeout_s: float | None,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
    ):
        self.calls.append({"prompt": prompt, "temperature_override": temperature_override})
        payload = self.payloads.pop(0) if self.payloads else {"narrative_text": "ok"}
        return (
            payload,
            {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "latency_ms": 1,
                "status": "success",
                "error_message": None,
            },
        )


def _build_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[LLMRuntime, _RecordingProvider]:
    runtime = LLMRuntime()
    provider = _RecordingProvider()
    runtime.providers = {"fake": provider}

    monkeypatch.setattr(settings, "llm_model_generate", "fake-model")
    monkeypatch.setattr(settings, "llm_max_retries", 1)
    monkeypatch.setattr(settings, "llm_retry_attempts_network", 1)
    monkeypatch.setattr(settings, "llm_timeout_s", 30.0)
    monkeypatch.setattr(settings, "llm_total_deadline_s", 120.0)
    monkeypatch.setattr(settings, "llm_connect_timeout_s", 12.0)
    monkeypatch.setattr(settings, "llm_read_timeout_s", 30.0)
    monkeypatch.setattr(settings, "llm_write_timeout_s", 30.0)
    monkeypatch.setattr(settings, "llm_pool_timeout_s", 8.0)

    return runtime, provider


def test_narrative_default_timeout_profile_uses_global_deadlines(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, provider = _build_runtime(monkeypatch)

    out, used_llm = runtime.narrative_with_fallback(
        _DbStub(),
        prompt='{"task":"seed_expand"}',
        session_id=None,
        step_id=uuid.uuid4(),
    )
    assert used_llm is True
    assert out.narrative_text == "ok"

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["model"] == "fake-model"
    assert isinstance(call["timeout_s"], float)
    assert 0.1 <= call["timeout_s"] <= 30.0
    assert call["connect_timeout_s"] is not None
    assert call["read_timeout_s"] is not None
    assert call["write_timeout_s"] is not None
    assert call["pool_timeout_s"] is not None
    assert call["connect_timeout_s"] <= call["timeout_s"]
    assert call["read_timeout_s"] <= call["timeout_s"]
    assert call["write_timeout_s"] <= call["timeout_s"]
    assert call["pool_timeout_s"] <= call["timeout_s"]
    assert call["temperature_override"] == pytest.approx(0.0)


def test_narrative_long_wait_profile_disables_deadline_and_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, provider = _build_runtime(monkeypatch)
    timeout_profile = LLMTimeoutProfile(
        disable_total_deadline=True,
        call_timeout_s=None,
        connect_timeout_s=12.0,
        read_timeout_s=None,
        write_timeout_s=30.0,
        pool_timeout_s=8.0,
    )

    out, used_llm = runtime.narrative_with_fallback(
        _DbStub(),
        prompt='{"task":"continue_write"}',
        session_id=None,
        step_id=uuid.uuid4(),
        timeout_profile=timeout_profile,
    )
    assert used_llm is True
    assert out.narrative_text == "ok"

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["timeout_s"] is None
    assert call["read_timeout_s"] is None
    assert call["connect_timeout_s"] == pytest.approx(12.0)
    assert call["write_timeout_s"] == pytest.approx(30.0)
    assert call["pool_timeout_s"] == pytest.approx(8.0)


def test_narrative_protocol_v2_passes_messages_only(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, provider = _build_runtime(monkeypatch)
    monkeypatch.setattr(settings, "llm_prompt_protocol_v2_enabled", True)
    envelope = PromptEnvelope(
        system_text="system guard",
        user_text="Story narration task. Return JSON only.",
        schema_name="story_narrative_v1",
        schema_payload={
            "type": "object",
            "additionalProperties": False,
            "required": ["narrative_text"],
            "properties": {"narrative_text": {"type": "string"}},
        },
        tags=("play", "narration"),
    )

    runtime.narrative_with_fallback(
        _DbStub(),
        prompt=envelope.user_text,
        prompt_envelope=envelope,
        session_id=None,
        step_id=uuid.uuid4(),
    )

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert isinstance(call["messages_override"], list)
    assert call["messages_override"][0]["role"] == "system"


def test_narrative_retries_on_parse_failure_without_repair_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LLMRuntime()
    provider = _SequenceProvider(payloads=[{"bad": "shape"}, {"still": "bad"}, {"narrative_text": "ok"}])
    runtime.providers = {"fake": provider}
    monkeypatch.setattr(settings, "llm_model_generate", "fake-model")

    out, used_llm = runtime.narrative_with_fallback(
        _DbStub(),
        prompt='{"task":"seed_expand"}',
        session_id=None,
        step_id=uuid.uuid4(),
    )
    assert used_llm is True
    assert out.narrative_text == "ok"
    # Retries reuse the same prompt instead of repair prompts.
    assert [call["prompt"] for call in provider.calls] == [
        '{"task":"seed_expand"}',
        '{"task":"seed_expand"}',
        '{"task":"seed_expand"}',
    ]
