from __future__ import annotations

from types import SimpleNamespace

from rpg_backend.llm.task_specs import (
    AUTHOR_BEAT_CHANNEL,
    AUTHOR_OVERVIEW_CHANNEL,
    PLAY_CHANNEL,
    build_readiness_probe_task,
    build_responses_task_spec_bundle,
    validate_readiness_probe_payload,
)


def test_readiness_probe_task_and_payload_validation() -> None:
    spec = build_readiness_probe_task()
    assert spec.task_name == "readiness_probe"
    assert spec.user_payload == "who are you"
    parsed = validate_readiness_probe_payload({"ok": True, "who": "worker-ready"})
    assert parsed.ok is True


def test_responses_task_specs_are_centralized_and_resolved_from_settings() -> None:
    settings = SimpleNamespace(
        responses_enable_thinking_play=False,
        responses_enable_thinking_author_overview=False,
        responses_enable_thinking_author_beat=True,
        responses_enable_thinking_story_quality_judge=True,
    )
    specs = build_responses_task_spec_bundle(settings=settings)  # type: ignore[arg-type]

    assert specs.play_interpret.channel == PLAY_CHANNEL
    assert specs.play_render.channel == PLAY_CHANNEL
    assert specs.author_overview.channel == AUTHOR_OVERVIEW_CHANNEL
    assert specs.author_beat.channel == AUTHOR_BEAT_CHANNEL
    assert specs.story_quality_judge.channel is None
    assert specs.play_interpret.enable_thinking is False
    assert specs.author_beat.enable_thinking is True
    assert specs.story_quality_judge.enable_thinking is True
    assert specs.play_interpret.output_mode == "strict_json"
    assert specs.play_render.output_mode == "text"
