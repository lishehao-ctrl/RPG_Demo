from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from rpg_backend.config import Settings, get_settings
from rpg_backend.responses_transport import ResponsesJSONResponse, ResponsesJSONTransport, build_openai_client

ConcreteAuthorV2LiveMode = Literal["live_qwen3_5_plus", "live_qwen3_5_flash", "live_gpt_5_4_mini"]
AuthorV2RunMode = Literal[
    "deterministic",
    "live_priority",
    "pure_gpt",
    "mainline_live",
    "live_qwen3_5_plus",
    "live_qwen3_5_flash",
    "live_gpt_5_4_mini",
]
AUTHOR_V2_PRIORITY_CHAIN: tuple[ConcreteAuthorV2LiveMode, ...] = (
    "live_gpt_5_4_mini",
    "live_qwen3_5_flash",
    "live_qwen3_5_plus",
)


class AuthorV2GatewayError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AuthorV2LLMGateway:
    client: Any
    model: str
    profile_id: AuthorV2RunMode
    timeout_seconds: float
    max_output_tokens_preview: int | None
    max_output_tokens_cast_slots: int | None
    max_output_tokens_segment_allocation: int | None
    max_output_tokens_segment_playbook: int | None
    max_output_tokens_voice_atoms: int | None = None
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
    def _error_factory(code: str, message: str, status_code: int) -> AuthorV2GatewayError:
        return AuthorV2GatewayError(code=code, message=message, status_code=status_code)

    def invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_output_tokens: int | None,
        operation_name: str,
        response_format_type: Literal["json_object", "json_schema"] | None = None,
        response_format_schema: dict[str, Any] | None = None,
        response_format_name: str | None = None,
        response_format_strict: bool = True,
    ) -> ResponsesJSONResponse:
        resolved_response_format = response_format_type
        if resolved_response_format is None:
            resolved_response_format = "json_object"
        return self._transport.invoke_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            max_output_tokens=max_output_tokens,
            operation_name=operation_name,
            response_format_type=resolved_response_format,
            response_format_schema=response_format_schema,
            response_format_name=response_format_name,
            response_format_strict=response_format_strict,
        )


def resolve_author_v2_live_mode_chain(mode: AuthorV2RunMode) -> tuple[ConcreteAuthorV2LiveMode, ...]:
    if mode in {"live_priority", "mainline_live"}:
        return AUTHOR_V2_PRIORITY_CHAIN
    if mode == "deterministic":
        return ()
    if mode == "pure_gpt":
        return ("live_gpt_5_4_mini",)
    return (mode,)


def _resolved_profile_settings(mode: ConcreteAuthorV2LiveMode, settings: Settings) -> tuple[str, str, str, bool]:
    if mode == "live_qwen3_5_plus":
        return (
            settings.resolved_author_responses_base_url(),
            settings.resolved_author_responses_api_key(),
            "qwen3.5-plus",
            settings.resolved_author_responses_use_session_cache(),
        )
    if mode == "live_qwen3_5_flash":
        return (
            settings.resolved_author_responses_base_url(),
            settings.resolved_author_responses_api_key(),
            "qwen3.5-flash",
            settings.resolved_author_responses_use_session_cache(),
        )
    if mode == "live_gpt_5_4_mini":
        return (
            settings.resolved_responses_base_url(),
            settings.resolved_responses_api_key(),
            "gpt-5.4-mini",
            settings.resolved_responses_use_session_cache(),
        )
    raise AuthorV2GatewayError(
        code="llm_mode_invalid",
        message=f"live gateway does not support mode={mode}",
        status_code=400,
    )


def get_author_v2_llm_gateway(
    mode: ConcreteAuthorV2LiveMode,
    *,
    settings: Settings | None = None,
) -> AuthorV2LLMGateway:
    resolved = settings or get_settings()
    base_url, api_key, model, use_session_cache = _resolved_profile_settings(mode, resolved)
    if not base_url or not api_key or not model:
        raise AuthorV2GatewayError(
            code="llm_config_missing",
            message=f"missing live gateway configuration for mode={mode}",
            status_code=500,
        )
    client = build_openai_client(
        base_url=base_url,
        api_key=api_key,
        api_keys=(
            resolved.author_responses_api_key_pool()
            if mode in {"live_qwen3_5_plus", "live_qwen3_5_flash"}
            else resolved.responses_api_key_pool()
        ),
        use_session_cache=bool(use_session_cache),
        session_cache_header=resolved.responses_session_cache_header,
        session_cache_value=resolved.responses_session_cache_value,
        requests_per_minute=(
            int(resolved.responses_author_qwen_requests_per_minute)
            if mode in {"live_qwen3_5_plus", "live_qwen3_5_flash"}
            and resolved.responses_author_qwen_requests_per_minute is not None
            else (
                int(resolved.responses_author_requests_per_minute)
                if resolved.responses_author_requests_per_minute is not None
                else None
            )
        ),
        rate_limit_scope=(
            "author_v2:qwen"
            if mode in {"live_qwen3_5_plus", "live_qwen3_5_flash"}
            else ("author_v2" if resolved.responses_author_requests_per_minute is not None else None)
        ),
        chat_json_stream_mode=resolved.responses_chat_json_stream_mode,
        chat_json_stream_hosts=resolved.responses_chat_json_stream_host_list(),
    )
    timeout_seconds = float(
        resolved.responses_timeout_seconds_author_v2_qwen
        if mode in {"live_qwen3_5_plus", "live_qwen3_5_flash"}
        else resolved.responses_timeout_seconds
    )
    return AuthorV2LLMGateway(
        client=client,
        model=model,
        profile_id=mode,
        timeout_seconds=timeout_seconds,
        max_output_tokens_preview=resolved.responses_max_output_tokens_author_overview,
        max_output_tokens_cast_slots=resolved.responses_max_output_tokens_author_overview,
        max_output_tokens_segment_allocation=resolved.responses_max_output_tokens_author_beat_plan,
        max_output_tokens_segment_playbook=resolved.responses_max_output_tokens_author_scene,
        max_output_tokens_voice_atoms=resolved.responses_max_output_tokens_author_overview,
        use_session_cache=bool(use_session_cache),
        json_content_type_hint=bool(resolved.responses_json_content_type_hint),
        json_object_prompt_only=bool(resolved.responses_json_object_prompt_only),
    )
