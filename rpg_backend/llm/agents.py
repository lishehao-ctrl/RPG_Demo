from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rpg_backend.llm.response_sessions import (
    AUTHOR_SCOPE_TYPE,
    PLAY_CHANNEL,
    PLAY_SCOPE_TYPE,
    ResponseSessionStore,
)
from rpg_backend.llm.responses_transport import ResponsesTransport, ResponsesTransportResult
from rpg_backend.llm.task_specs import ResponsesTaskSpec


@dataclass(frozen=True)
class AgentUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class AgentDiagnostics:
    agent_model: str
    agent_mode: str
    response_id: str | None
    reasoning_summary: str | None
    duration_ms: int
    usage: AgentUsage


@dataclass(frozen=True)
class PlayInterpretResult:
    selected_key: str
    confidence: float
    interpreted_intent: str
    diagnostics: AgentDiagnostics


@dataclass(frozen=True)
class PlayRenderResult:
    narration_text: str
    diagnostics: AgentDiagnostics


@dataclass(frozen=True)
class AuthorStructuredResult:
    payload: dict[str, Any]
    diagnostics: AgentDiagnostics



def _message(role: str, text: str) -> dict[str, Any]:
    return {
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }



def _strict_json_payload(text: str) -> dict[str, Any]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("model output is not a JSON object")
    return parsed



def _diagnostics_from_result(*, model: str, result: ResponsesTransportResult) -> AgentDiagnostics:
    return AgentDiagnostics(
        agent_model=model,
        agent_mode="responses",
        response_id=result.response_id,
        reasoning_summary=result.reasoning_summary,
        duration_ms=int(result.duration_ms),
        usage=AgentUsage(
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
        ),
    )


class PlayAgent:
    def __init__(
        self,
        *,
        transport: ResponsesTransport,
        session_store: ResponseSessionStore,
        model: str,
        timeout_seconds: float,
        interpret_task_spec: ResponsesTaskSpec,
        render_task_spec: ResponsesTaskSpec,
    ) -> None:
        self.transport = transport
        self.session_store = session_store
        self.model = str(model)
        self.timeout_seconds = float(timeout_seconds)
        self.interpret_task_spec = interpret_task_spec
        self.render_task_spec = render_task_spec

    async def _invoke(
        self,
        *,
        session_id: str,
        task_spec: ResponsesTaskSpec,
        user_payload: dict[str, Any],
    ) -> ResponsesTransportResult:
        user_text = json.dumps(user_payload, ensure_ascii=False, sort_keys=True)

        async def _call(previous_response_id: str | None) -> ResponsesTransportResult:
            return await self.transport.create(
                model=self.model,
                input=[
                    _message("developer", task_spec.developer_prompt),
                    _message("user", user_text),
                ],
                previous_response_id=previous_response_id,
                timeout=self.timeout_seconds,
                extra_body={"enable_thinking": task_spec.enable_thinking},
            )

        return await self.session_store.call_with_cursor(
            scope_type=PLAY_SCOPE_TYPE,
            scope_id=session_id,
            channel=task_spec.channel or PLAY_CHANNEL,
            model=self.model,
            invoke=_call,
        )

    async def interpret_turn(
        self,
        *,
        session_id: str,
        scene_context: dict[str, Any],
        route_candidates: list[dict[str, Any]],
        text: str,
    ) -> PlayInterpretResult:
        result = await self._invoke(
            session_id=session_id,
            task_spec=self.interpret_task_spec,
            user_payload={
                "task": self.interpret_task_spec.task_name,
                "player_text": text,
                "scene_context": scene_context,
                "route_candidates": route_candidates,
            },
        )
        payload = _strict_json_payload(result.output_text)

        selected_key = str(payload.get("selected_key") or "").strip()
        confidence = float(payload.get("confidence") or 0.0)
        interpreted_intent = str(payload.get("interpreted_intent") or "").strip()

        if not selected_key:
            raise ValueError("interpret_turn returned empty selected_key")
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("interpret_turn returned confidence outside [0,1]")
        if not interpreted_intent:
            raise ValueError("interpret_turn returned empty interpreted_intent")

        return PlayInterpretResult(
            selected_key=selected_key,
            confidence=confidence,
            interpreted_intent=interpreted_intent,
            diagnostics=_diagnostics_from_result(model=self.model, result=result),
        )

    async def render_resolved_turn(
        self,
        *,
        session_id: str,
        narration_context: dict[str, Any],
        prompt_slots: dict[str, Any],
        style_guard: str,
    ) -> PlayRenderResult:
        result = await self._invoke(
            session_id=session_id,
            task_spec=self.render_task_spec,
            user_payload={
                "task": self.render_task_spec.task_name,
                "style_guard": style_guard,
                "narration_context": narration_context,
                "prompt_slots": prompt_slots,
            },
        )

        narration_text = str(result.output_text or "").strip()
        if not narration_text:
            raise ValueError("render_resolved_turn returned empty narration")

        return PlayRenderResult(
            narration_text=narration_text,
            diagnostics=_diagnostics_from_result(model=self.model, result=result),
        )


class AuthorAgent:
    def __init__(
        self,
        *,
        transport: ResponsesTransport,
        session_store: ResponseSessionStore,
        model: str,
        timeout_seconds: float,
        overview_task_spec: ResponsesTaskSpec,
        beat_task_spec: ResponsesTaskSpec,
    ) -> None:
        self.transport = transport
        self.session_store = session_store
        self.model = str(model)
        self.timeout_seconds = float(timeout_seconds)
        self.overview_task_spec = overview_task_spec
        self.beat_task_spec = beat_task_spec

    async def _invoke_structured(
        self,
        *,
        run_id: str,
        task_spec: ResponsesTaskSpec,
        user_payload: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> AuthorStructuredResult:
        if task_spec.channel is None:
            raise ValueError("author structured task requires a continuity channel")
        user_text = json.dumps(user_payload, ensure_ascii=False, sort_keys=True)

        async def _call(previous_response_id: str | None) -> ResponsesTransportResult:
            return await self.transport.create(
                model=self.model,
                input=[
                    _message("developer", task_spec.developer_prompt),
                    _message("user", user_text),
                ],
                previous_response_id=previous_response_id,
                timeout=float(timeout_seconds or self.timeout_seconds),
                extra_body={"enable_thinking": task_spec.enable_thinking},
            )

        result = await self.session_store.call_with_cursor(
            scope_type=AUTHOR_SCOPE_TYPE,
            scope_id=run_id,
            channel=task_spec.channel,
            model=self.model,
            invoke=_call,
        )
        payload = _strict_json_payload(result.output_text)
        return AuthorStructuredResult(
            payload=payload,
            diagnostics=_diagnostics_from_result(model=self.model, result=result),
        )

    async def generate_overview(
        self,
        *,
        run_id: str,
        raw_brief: str,
        output_schema: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> AuthorStructuredResult:
        return await self._invoke_structured(
            run_id=run_id,
            task_spec=self.overview_task_spec,
            user_payload={
                "task": self.overview_task_spec.task_name,
                "raw_brief": raw_brief,
                "output_schema": output_schema,
            },
            timeout_seconds=timeout_seconds,
        )

    async def generate_beat(
        self,
        *,
        run_id: str,
        payload: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> AuthorStructuredResult:
        request_payload = dict(payload)
        request_payload["task"] = self.beat_task_spec.task_name
        return await self._invoke_structured(
            run_id=run_id,
            task_spec=self.beat_task_spec,
            user_payload=request_payload,
            timeout_seconds=timeout_seconds,
        )
