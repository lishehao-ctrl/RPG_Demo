from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from rpg_backend.config.settings import Settings, get_settings

TaskOutputMode = Literal["strict_json", "text"]

PLAY_CHANNEL = "play_agent"
AUTHOR_OVERVIEW_CHANNEL = "author_overview"
AUTHOR_BEAT_CHANNEL = "author_beat"


@dataclass(frozen=True)
class ResponsesTaskTemplate:
    task_name: str
    developer_prompt: str
    output_mode: TaskOutputMode
    channel: str | None = None
    thinking_setting_field: str | None = None


@dataclass(frozen=True)
class ResponsesTaskSpec:
    task_name: str
    developer_prompt: str
    output_mode: TaskOutputMode
    channel: str | None
    enable_thinking: bool


@dataclass(frozen=True)
class ResponsesTaskSpecBundle:
    play_interpret: ResponsesTaskSpec
    play_render: ResponsesTaskSpec
    author_overview: ResponsesTaskSpec
    author_beat: ResponsesTaskSpec
    story_quality_judge: ResponsesTaskSpec


@dataclass(frozen=True)
class TaskSpec:
    task_name: str
    system_prompt: str
    user_payload: Any


class ReadinessProbePayload(BaseModel):
    ok: bool
    who: str


def _resolve_task(template: ResponsesTaskTemplate, settings: Settings) -> ResponsesTaskSpec:
    enable_thinking = False
    if template.thinking_setting_field is not None:
        enable_thinking = bool(getattr(settings, template.thinking_setting_field))
    return ResponsesTaskSpec(
        task_name=template.task_name,
        developer_prompt=template.developer_prompt,
        output_mode=template.output_mode,
        channel=template.channel,
        enable_thinking=enable_thinking,
    )


def build_responses_task_spec_bundle(settings: Settings | None = None) -> ResponsesTaskSpecBundle:
    resolved_settings = settings or get_settings()

    play_interpret = _resolve_task(
        ResponsesTaskTemplate(
            task_name="interpret_turn",
            developer_prompt=(
                "You are the Play Agent. For a text player action, select exactly one candidate key. "
                "Return strict JSON only with keys: selected_key, confidence, interpreted_intent."
            ),
            output_mode="strict_json",
            channel=PLAY_CHANNEL,
            thinking_setting_field="responses_enable_thinking_play",
        ),
        resolved_settings,
    )
    play_render = _resolve_task(
        ResponsesTaskTemplate(
            task_name="render_resolved_turn",
            developer_prompt=(
                "You are the Play Agent. Render concise player-facing narration from deterministic resolution. "
                "Do not change outcome facts. Return narration text only, no JSON and no markdown fences."
            ),
            output_mode="text",
            channel=PLAY_CHANNEL,
            thinking_setting_field="responses_enable_thinking_play",
        ),
        resolved_settings,
    )
    author_overview = _resolve_task(
        ResponsesTaskTemplate(
            task_name="generate_overview",
            developer_prompt=(
                "You are the Author Agent. Compile one StoryOverview JSON object. "
                "Return strict JSON only. No prose, no markdown fences."
            ),
            output_mode="strict_json",
            channel=AUTHOR_OVERVIEW_CHANNEL,
            thinking_setting_field="responses_enable_thinking_author_overview",
        ),
        resolved_settings,
    )
    author_beat = _resolve_task(
        ResponsesTaskTemplate(
            task_name="generate_beat",
            developer_prompt=(
                "You are the Author Agent. Compile one BeatDraft JSON object. "
                "Return strict JSON only. No prose, no markdown fences."
            ),
            output_mode="strict_json",
            channel=AUTHOR_BEAT_CHANNEL,
            thinking_setting_field="responses_enable_thinking_author_beat",
        ),
        resolved_settings,
    )
    story_quality_judge = _resolve_task(
        ResponsesTaskTemplate(
            task_name="judge_story_quality",
            developer_prompt=(
                "You are a strict evaluator for interactive narrative packs. "
                "Return strict JSON only. Score each axis from 0 to 10."
            ),
            output_mode="strict_json",
            channel=None,
            thinking_setting_field="responses_enable_thinking_story_quality_judge",
        ),
        resolved_settings,
    )
    return ResponsesTaskSpecBundle(
        play_interpret=play_interpret,
        play_render=play_render,
        author_overview=author_overview,
        author_beat=author_beat,
        story_quality_judge=story_quality_judge,
    )


def build_readiness_probe_task() -> TaskSpec:
    return TaskSpec(
        task_name="readiness_probe",
        system_prompt="Readiness probe. Return JSON only with keys ok, who.",
        user_payload="who are you",
    )


def validate_readiness_probe_payload(payload: dict[str, Any]) -> ReadinessProbePayload:
    try:
        parsed = ReadinessProbePayload.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    if parsed.ok is not True:
        raise ValueError("probe response ok is not true")
    if not parsed.who.strip():
        raise ValueError("probe response who is blank")
    return parsed
