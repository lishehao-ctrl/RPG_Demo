from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True, frozen=True)
class LLMStageEvent:
    stage_code: str
    locale: str
    label: str
    task: str | None = None
    request_kind: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "stage_code": str(self.stage_code or "").strip(),
            "label": str(self.label or "").strip(),
            "locale": str(self.locale or "").strip(),
        }
        if self.task:
            payload["task"] = str(self.task)
        if self.request_kind:
            payload["request_kind"] = str(self.request_kind)
        return payload


StageEmitter = Callable[[LLMStageEvent], None]


def normalize_stage_locale(locale: str | None) -> str:
    value = str(locale or "").strip().lower()
    return "zh" if value.startswith("zh") else "en"


def stage_label(
    stage_code: str,
    *,
    locale: str,
    task: str | None = None,
    request_kind: str | None = None,
) -> str:
    use_zh = normalize_stage_locale(locale) == "zh"
    code = str(stage_code or "").strip()
    req_kind = str(request_kind or "").strip().lower()

    if code == "play.selection.start":
        return "正在发送意图映射请求..." if use_zh else "Sending intent mapping request..."
    if code == "play.narration.start":
        return "正在发送叙事生成请求..." if use_zh else "Sending narrative generation request..."
    if code == "llm.retry":
        return "正在尝试重新请求..." if use_zh else "Retrying request..."

    if req_kind == "free_input":
        return "正在发送意图映射请求..." if use_zh else "Sending intent mapping request..."
    return "正在发送请求..." if use_zh else "Sending request..."


def build_stage_event(
    *,
    stage_code: str,
    locale: str | None = None,
    task: str | None = None,
    request_kind: str | None = None,
) -> LLMStageEvent:
    locale_norm = normalize_stage_locale(locale)
    return LLMStageEvent(
        stage_code=str(stage_code or "").strip(),
        locale=locale_norm,
        label=stage_label(
            str(stage_code or "").strip(),
            locale=locale_norm,
            task=task,
            request_kind=request_kind,
        ),
        task=(str(task).strip() if task is not None else None) or None,
        request_kind=(str(request_kind).strip() if request_kind is not None else None) or None,
    )


def emit_stage(
    stage_emitter: StageEmitter | None,
    *,
    stage_code: str,
    locale: str | None = None,
    task: str | None = None,
    request_kind: str | None = None,
) -> None:
    if stage_emitter is None:
        return
    event = build_stage_event(
        stage_code=stage_code,
        locale=locale,
        task=task,
        request_kind=request_kind,
    )
    try:
        stage_emitter(event)
    except Exception:  # noqa: BLE001
        # Stage signal must never break the primary LLM workflow.
        return


__all__ = [
    "LLMStageEvent",
    "StageEmitter",
    "normalize_stage_locale",
    "stage_label",
    "build_stage_event",
    "emit_stage",
]
