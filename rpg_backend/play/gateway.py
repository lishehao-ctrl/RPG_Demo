from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rpg_backend.config import Settings, get_settings
from rpg_backend.responses_transport import (
    ResponsesJSONResponse as PlayGatewayJSONResponse,
    ResponsesJSONTransport,
    build_openai_client,
)


class PlayGatewayError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PlayLLMGateway:
    client: Any
    model: str
    timeout_seconds: float
    max_output_tokens_interpret: int | None
    max_output_tokens_interpret_repair: int | None
    max_output_tokens_ending_judge: int | None
    max_output_tokens_ending_judge_repair: int | None
    max_output_tokens_pyrrhic_critic: int | None
    max_output_tokens_render: int | None
    max_output_tokens_render_repair: int | None
    use_session_cache: bool = False
    enable_thinking: bool = False
    json_content_type_hint: bool = False
    json_object_prompt_only: bool = False
    call_trace: list[dict[str, Any]] = field(default_factory=list, repr=False, compare=False)
    _transport: ResponsesJSONTransport = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_transport",
            ResponsesJSONTransport(
                client=self.client,
                model=self.model,
                timeout_seconds=self.timeout_seconds,
                use_session_cache=self.use_session_cache,
                temperature=0.4,
                enable_thinking=self.enable_thinking,
                explicit_disable_thinking=self.model.startswith("qwen") and not self.enable_thinking,
                json_content_type_hint=self.json_content_type_hint,
                json_object_prompt_only=self.json_object_prompt_only,
                provider_failed_code="play_llm_provider_failed",
                invalid_response_code="play_llm_invalid_response",
                invalid_json_code="play_llm_invalid_json",
                error_factory=self._error_factory,
                call_trace=self.call_trace,
            ),
        )

    @staticmethod
    def _error_factory(code: str, message: str, status_code: int) -> PlayGatewayError:
        return PlayGatewayError(
            code=code,
            message=message,
            status_code=status_code,
        )

    def _invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_output_tokens: int | None,
        previous_response_id: str | None = None,
        operation_name: str | None = None,
        plaintext_fallback_key: str | None = None,
    ) -> PlayGatewayJSONResponse:
        return self._transport.invoke_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_output_tokens=max_output_tokens,
            previous_response_id=previous_response_id,
            operation_name=operation_name,
            plaintext_fallback_key=plaintext_fallback_key,
        )


def get_play_llm_gateway(settings: Settings | None = None) -> PlayLLMGateway:
    resolved = settings or get_settings()
    base_url = resolved.resolved_play_responses_base_url()
    api_key = resolved.resolved_play_responses_api_key()
    model = resolved.resolved_play_responses_model()
    if not base_url or not api_key or not model:
        raise PlayGatewayError(
            code="play_llm_config_missing",
            message=(
                "Either APP_RESPONSES_PLAY_BASE_URL / APP_RESPONSES_PLAY_API_KEY / APP_RESPONSES_PLAY_MODEL "
                "(or generic APP_RESPONSES_BASE_URL / APP_RESPONSES_API_KEY / APP_RESPONSES_MODEL), "
                "or legacy APP_GATEWAY_PLAY_BASE_URL / APP_GATEWAY_PLAY_API_KEY / APP_GATEWAY_PLAY_MODEL "
                "(or APP_GATEWAY_BASE_URL / APP_GATEWAY_API_KEY / APP_GATEWAY_PLAY_MODEL / APP_GATEWAY_MODEL) are required"
            ),
            status_code=500,
        )
    use_session_cache = resolved.resolved_play_responses_use_session_cache()
    client = build_openai_client(
        base_url=base_url,
        api_key=api_key,
        api_keys=resolved.play_responses_api_key_pool(),
        use_session_cache=bool(use_session_cache),
        session_cache_header=resolved.responses_session_cache_header,
        session_cache_value=resolved.responses_session_cache_value,
        requests_per_minute=(
            int(resolved.responses_play_requests_per_minute)
            if resolved.responses_play_requests_per_minute is not None
            else None
        ),
        rate_limit_scope=(
            "play"
            if resolved.responses_play_requests_per_minute is not None
            else None
        ),
        chat_json_stream_mode=resolved.responses_chat_json_stream_mode,
        chat_json_stream_hosts=resolved.responses_chat_json_stream_host_list(),
    )
    return PlayLLMGateway(
        client=client,
        model=model,
        timeout_seconds=float(resolved.responses_timeout_seconds),
        max_output_tokens_interpret=resolved.responses_max_output_tokens_play_interpret,
        max_output_tokens_interpret_repair=resolved.responses_max_output_tokens_play_interpret_repair,
        max_output_tokens_ending_judge=resolved.responses_max_output_tokens_play_ending_judge,
        max_output_tokens_ending_judge_repair=resolved.responses_max_output_tokens_play_ending_judge_repair,
        max_output_tokens_pyrrhic_critic=resolved.responses_max_output_tokens_play_pyrrhic_critic,
        max_output_tokens_render=resolved.responses_max_output_tokens_play_render,
        max_output_tokens_render_repair=resolved.responses_max_output_tokens_play_render_repair,
        use_session_cache=bool(use_session_cache),
        enable_thinking=bool(resolved.responses_enable_thinking_play),
        json_content_type_hint=bool(resolved.responses_json_content_type_hint),
        json_object_prompt_only=bool(resolved.responses_json_object_prompt_only),
    )
