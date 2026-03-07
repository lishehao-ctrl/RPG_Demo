from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeStepResult:
    scene_id: str
    beat_index: int
    ended: bool
    narration_text: str
    recognized: dict[str, Any]
    resolution: dict[str, Any]
    ui: dict[str, Any]
    runtime_metrics: dict[str, Any]
    debug: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scene_id": self.scene_id,
            "beat_index": self.beat_index,
            "ended": self.ended,
            "narration_text": self.narration_text,
            "recognized": self.recognized,
            "resolution": self.resolution,
            "ui": self.ui,
            "runtime_metrics": self.runtime_metrics,
        }
        if self.debug is not None:
            payload["debug"] = self.debug
        return payload
