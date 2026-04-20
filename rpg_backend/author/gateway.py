from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rpg_backend.config import Settings, get_settings
from rpg_backend.responses_transport import (
    ResponsesJSONResponse as GatewayJSONResponse,
    ResponsesJSONTransport,
    StructuredResponse,
    build_openai_client,
)


class AuthorGatewayError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AuthorLLMGateway:
    client: Any
    model: str
    timeout_seconds: float
    max_output_tokens_overview: int | None
    max_output_tokens_beat_plan: int | None
    max_output_tokens_beat_skeleton: int | None
    max_output_tokens_beat_repair: int | None
    max_output_tokens_rulepack: int | None
    use_session_cache: bool = False
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
                temperature=0.2,
                enable_thinking=False,
                explicit_disable_thinking=self.model.startswith("qwen"),
                json_content_type_hint=self.json_content_type_hint,
                json_object_prompt_only=self.json_object_prompt_only,
                provider_failed_code="llm_provider_failed",
                invalid_response_code="llm_invalid_response",
                invalid_json_code="llm_invalid_json",
                error_factory=self._error_factory,
                call_trace=self.call_trace,
            ),
        )

    @staticmethod
    def _error_factory(code: str, message: str, status_code: int) -> AuthorGatewayError:
        return AuthorGatewayError(
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
    ) -> GatewayJSONResponse:
        return self._transport.invoke_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_output_tokens=max_output_tokens,
            previous_response_id=previous_response_id,
            operation_name=operation_name,
        )


def get_author_llm_gateway(settings: Settings | None = None) -> AuthorLLMGateway:
    resolved = settings or get_settings()
    base_url = resolved.resolved_author_responses_base_url()
    api_key = resolved.resolved_author_responses_api_key()
    model = resolved.resolved_author_responses_model()
    if not base_url or not api_key or not model:
        raise AuthorGatewayError(
            code="llm_config_missing",
            message=(
                "Either APP_RESPONSES_AUTHOR_BASE_URL / APP_RESPONSES_AUTHOR_API_KEY / APP_RESPONSES_AUTHOR_MODEL "
                "(or generic APP_RESPONSES_BASE_URL / APP_RESPONSES_API_KEY / APP_RESPONSES_MODEL), "
                "or legacy APP_GATEWAY_AUTHOR_BASE_URL / APP_GATEWAY_AUTHOR_API_KEY / APP_GATEWAY_AUTHOR_MODEL "
                "(or APP_GATEWAY_BASE_URL / APP_GATEWAY_API_KEY / APP_GATEWAY_MODEL) are required"
            ),
            status_code=500,
        )
    use_session_cache = resolved.resolved_author_responses_use_session_cache()
    client = build_openai_client(
        base_url=base_url,
        api_key=api_key,
        api_keys=resolved.author_responses_api_key_pool(),
        use_session_cache=bool(use_session_cache),
        session_cache_header=resolved.responses_session_cache_header,
        session_cache_value=resolved.responses_session_cache_value,
        requests_per_minute=(
            int(resolved.responses_author_qwen_requests_per_minute)
            if resolved.responses_author_qwen_requests_per_minute is not None and model.startswith("qwen")
            else (
                int(resolved.responses_author_requests_per_minute)
                if resolved.responses_author_requests_per_minute is not None
                else None
            )
        ),
        rate_limit_scope=(
            "author:qwen"
            if model.startswith("qwen")
            else ("author" if resolved.responses_author_requests_per_minute is not None else None)
        ),
        chat_json_stream_mode=resolved.responses_chat_json_stream_mode,
        chat_json_stream_hosts=resolved.responses_chat_json_stream_host_list(),
    )
    return AuthorLLMGateway(
        client=client,
        model=model,
        timeout_seconds=float(resolved.responses_timeout_seconds),
        max_output_tokens_overview=resolved.responses_max_output_tokens_author_overview,
        max_output_tokens_beat_plan=resolved.responses_max_output_tokens_author_beat_plan,
        max_output_tokens_beat_skeleton=resolved.responses_max_output_tokens_author_beat_skeleton,
        max_output_tokens_beat_repair=resolved.responses_max_output_tokens_author_beat_repair,
        max_output_tokens_rulepack=resolved.responses_max_output_tokens_author_rulepack,
        use_session_cache=bool(use_session_cache),
        json_content_type_hint=bool(resolved.responses_json_content_type_hint),
        json_object_prompt_only=bool(resolved.responses_json_object_prompt_only),
    )
