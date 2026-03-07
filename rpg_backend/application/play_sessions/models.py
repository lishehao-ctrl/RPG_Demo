from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rpg_backend.application.story_draft.models import OpeningGuidanceView


@dataclass(frozen=True)
class SessionStepCommand:
    client_action_id: str
    input_type: str | None = None
    move_id: str | None = None
    text: str | None = None
    dev_mode: bool = False

    def to_request_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "client_action_id": self.client_action_id,
            "dev_mode": self.dev_mode,
        }
        if self.input_type is not None or self.move_id is not None or self.text is not None:
            payload["input"] = {
                "type": self.input_type,
                "move_id": self.move_id,
                "text": self.text,
            }
        return payload


@dataclass(frozen=True)
class SessionSnapshot:
    id: str
    story_id: str
    version: int
    current_scene_id: str
    beat_index: int
    state_json: dict[str, Any]
    beat_progress_json: dict[str, Any]
    ended: bool
    turn_count: int


@dataclass(frozen=True)
class SessionActionSnapshot:
    id: str
    session_id: str
    client_action_id: str
    request_json: dict[str, Any]
    response_json: dict[str, Any]


@dataclass(frozen=True)
class StepRecognizedView:
    interpreted_intent: str
    move_id: str
    confidence: float
    route_source: str
    llm_duration_ms: int | None = None
    llm_gateway_mode: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StepRecognizedView":
        return cls(
            interpreted_intent=str(payload.get("interpreted_intent") or ""),
            move_id=str(payload.get("move_id") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            route_source=str(payload.get("route_source") or ""),
            llm_duration_ms=int(payload["llm_duration_ms"]) if isinstance(payload.get("llm_duration_ms"), int) else None,
            llm_gateway_mode=str(payload.get("llm_gateway_mode")) if payload.get("llm_gateway_mode") is not None else None,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "interpreted_intent": self.interpreted_intent,
            "move_id": self.move_id,
            "confidence": self.confidence,
            "route_source": self.route_source,
        }
        if self.llm_duration_ms is not None:
            payload["llm_duration_ms"] = self.llm_duration_ms
        if self.llm_gateway_mode is not None:
            payload["llm_gateway_mode"] = self.llm_gateway_mode
        return payload


@dataclass(frozen=True)
class StepResolutionView:
    result: str
    costs_summary: str
    consequences_summary: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StepResolutionView":
        return cls(
            result=str(payload.get("result") or ""),
            costs_summary=str(payload.get("costs_summary") or ""),
            consequences_summary=str(payload.get("consequences_summary") or ""),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "costs_summary": self.costs_summary,
            "consequences_summary": self.consequences_summary,
        }


@dataclass(frozen=True)
class StepUiMoveView:
    move_id: str
    label: str
    risk_hint: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StepUiMoveView":
        return cls(
            move_id=str(payload.get("move_id") or ""),
            label=str(payload.get("label") or ""),
            risk_hint=str(payload.get("risk_hint") or ""),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "move_id": self.move_id,
            "label": self.label,
            "risk_hint": self.risk_hint,
        }


@dataclass(frozen=True)
class StepUiView:
    moves: tuple[StepUiMoveView, ...]
    input_hint: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "StepUiView":
        moves = tuple(StepUiMoveView.from_payload(item) for item in payload.get("moves") or [] if isinstance(item, dict))
        return cls(moves=moves, input_hint=str(payload.get("input_hint") or ""))

    def to_payload(self) -> dict[str, Any]:
        return {
            "moves": [item.to_payload() for item in self.moves],
            "input_hint": self.input_hint,
        }


@dataclass(frozen=True)
class SessionStepResult:
    session_id: str
    version: int
    scene_id: str
    narration_text: str
    recognized: StepRecognizedView
    resolution: StepResolutionView
    ui: StepUiView
    debug: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SessionStepResult":
        return cls(
            session_id=str(payload.get("session_id") or ""),
            version=int(payload.get("version") or 0),
            scene_id=str(payload.get("scene_id") or ""),
            narration_text=str(payload.get("narration_text") or ""),
            recognized=StepRecognizedView.from_payload(payload.get("recognized") or {}),
            resolution=StepResolutionView.from_payload(payload.get("resolution") or {}),
            ui=StepUiView.from_payload(payload.get("ui") or {}),
            debug=(payload.get("debug") if isinstance(payload.get("debug"), dict) else None),
        )

    @classmethod
    def from_runtime_payload(
        cls,
        *,
        session_id: str,
        version: int,
        payload: dict[str, Any],
        include_debug: bool,
    ) -> "SessionStepResult":
        debug = payload.get("debug") if include_debug and isinstance(payload.get("debug"), dict) else None
        return cls(
            session_id=session_id,
            version=version,
            scene_id=str(payload.get("scene_id") or ""),
            narration_text=str(payload.get("narration_text") or ""),
            recognized=StepRecognizedView.from_payload(payload.get("recognized") or {}),
            resolution=StepResolutionView.from_payload(payload.get("resolution") or {}),
            ui=StepUiView.from_payload(payload.get("ui") or {}),
            debug=debug,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "version": self.version,
            "scene_id": self.scene_id,
            "narration_text": self.narration_text,
            "recognized": self.recognized.to_payload(),
            "resolution": self.resolution.to_payload(),
            "ui": self.ui.to_payload(),
        }
        if self.debug is not None:
            payload["debug"] = self.debug
        return payload


@dataclass(frozen=True)
class SessionCreateView:
    session_id: str
    story_id: str
    version: int
    scene_id: str
    state_summary: dict[str, int]
    opening_guidance: OpeningGuidanceView


@dataclass(frozen=True)
class SessionView:
    session_id: str
    scene_id: str
    beat_progress: dict[str, Any]
    ended: bool
    state_summary: dict[str, int]
    opening_guidance: OpeningGuidanceView
    state: dict[str, Any] | None = None


@dataclass(frozen=True)
class SessionHistoryTurnView:
    turn_index: int
    scene_id: str
    narration_text: str
    recognized: StepRecognizedView
    resolution: StepResolutionView
    ui: StepUiView
    ended: bool = False

    @classmethod
    def from_step_result(cls, turn_index: int, result: SessionStepResult, *, ended: bool) -> "SessionHistoryTurnView":
        return cls(
            turn_index=turn_index,
            scene_id=result.scene_id,
            narration_text=result.narration_text,
            recognized=result.recognized,
            resolution=result.resolution,
            ui=result.ui,
            ended=ended,
        )


@dataclass(frozen=True)
class SessionHistoryView:
    session_id: str
    history: tuple[SessionHistoryTurnView, ...]
