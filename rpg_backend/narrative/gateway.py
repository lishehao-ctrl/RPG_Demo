from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rpg_backend.config import Settings, get_settings
from rpg_backend.responses_transport import (
    ResponsesJSONResponse,
    ResponsesJSONTransport,
    build_openai_client,
)


class NarrativeGatewayError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class NarrativeLLMGateway:
    transport: ResponsesJSONTransport
    model: str

    def invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        operation_name: str,
        max_output_tokens: int | None = 1500,
    ) -> ResponsesJSONResponse:
        return self.transport.invoke_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_output_tokens=max_output_tokens,
            operation_name=operation_name,
            response_format_type="json_object",
        )


def _error_factory(code: str, message: str, status_code: int) -> NarrativeGatewayError:
    return NarrativeGatewayError(code=code, message=message, status_code=status_code)


def get_narrative_gateway(settings: Settings | None = None) -> NarrativeLLMGateway | None:
    resolved = settings or get_settings()
    base_url = resolved.resolved_play_responses_base_url()
    api_key = resolved.resolved_play_responses_api_key()
    model = resolved.resolved_play_responses_model()
    if not base_url or not api_key or not model:
        return None
    use_session_cache = bool(resolved.resolved_responses_use_session_cache()) if hasattr(
        resolved, "resolved_responses_use_session_cache"
    ) else bool(resolved.responses_use_session_cache or False)
    client = build_openai_client(
        base_url=base_url,
        api_key=api_key,
        api_keys=resolved.play_responses_api_key_pool(),
        use_session_cache=use_session_cache,
        session_cache_header=resolved.responses_session_cache_header,
        session_cache_value=resolved.responses_session_cache_value,
        requests_per_minute=(
            int(resolved.responses_play_requests_per_minute)
            if resolved.responses_play_requests_per_minute is not None
            else None
        ),
        rate_limit_scope=("narrative" if resolved.responses_play_requests_per_minute is not None else None),
        chat_json_stream_mode=resolved.responses_chat_json_stream_mode,
        chat_json_stream_hosts=resolved.responses_chat_json_stream_host_list(),
    )
    transport = ResponsesJSONTransport(
        client=client,
        model=model,
        timeout_seconds=float(resolved.responses_timeout_seconds),
        use_session_cache=use_session_cache,
        temperature=0.7,
        enable_thinking=False,
        explicit_disable_thinking=model.startswith("qwen"),
        json_content_type_hint=bool(resolved.responses_json_content_type_hint),
        json_object_prompt_only=bool(resolved.responses_json_object_prompt_only),
        provider_failed_code="llm_provider_failed",
        invalid_response_code="llm_invalid_response",
        invalid_json_code="llm_invalid_json",
        error_factory=_error_factory,
    )
    return NarrativeLLMGateway(transport=transport, model=model)
