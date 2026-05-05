from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from rpg_backend.config import Settings, get_settings
from rpg_backend.responses_transport import ResponsesJSONResponse, ResponsesJSONTransport, build_openai_client

logger = logging.getLogger(__name__)

ConcreteAuthorV3LiveMode = Literal["live_gpt_5_4_mini"]
AuthorV3RunMode = Literal[
    "deterministic",
    "live_priority",
    "pure_gpt",
    "live_gpt_5_4_mini",
]
AUTHOR_V3_PRIORITY_CHAIN: tuple[ConcreteAuthorV3LiveMode, ...] = ("live_gpt_5_4_mini",)


class AuthorV3GatewayError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _emit_gateway_log(message: str) -> None:
    if logger.hasHandlers():
        logger.warning(message)
        return
    print(message)


def _summarize_value(value: Any, *, limit: int = 160) -> str:
    text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _format_validation_error(exc: ValidationError) -> str:
    lines: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in (error.get("loc") or ())) or "<root>"
        error_type = str(error.get("type") or "unknown_error")
        message = str(error.get("msg") or "validation failed")
        invalid_input = _summarize_value(error.get("input"))
        line = f"{loc}: type={error_type}; msg={message}; input={invalid_input}"
        ctx = error.get("ctx")
        expected = ctx.get("expected") if isinstance(ctx, dict) else None
        if error_type in {"literal_error", "enum"} and expected:
            line = f"{line}; allowed={expected}"
        lines.append(line)
    return "\n".join(lines) if lines else str(exc)


def _response_payload(response: ResponsesJSONResponse) -> Any:
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return parsed
    payload = getattr(response, "payload", None)
    if payload is not None:
        try:
            object.__setattr__(response, "parsed", payload)
        except Exception:  # noqa: BLE001
            pass
    return payload


@dataclass(frozen=True)
class AuthorV3LLMGateway:
    client: Any
    model: str
    profile_id: AuthorV3RunMode
    timeout_seconds: float
    max_output_tokens_world_forge: int | None = 4000
    max_output_tokens_tension_weaver: int | None = 3000
    max_output_tokens_storylet_compiler: int | None = 2000
    max_output_tokens_quality_evaluator: int | None = 1500
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
    def _error_factory(code: str, message: str, status_code: int) -> AuthorV3GatewayError:
        return AuthorV3GatewayError(code=code, message=message, status_code=status_code)

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
        response_model: type[BaseModel] | None = None,
        max_retries: int = 1,
    ) -> ResponsesJSONResponse:
        effective_schema = response_model.model_json_schema() if response_model is not None else response_format_schema
        resolved_response_format = response_format_type
        if resolved_response_format is None:
            resolved_response_format = "json_schema" if isinstance(effective_schema, dict) else "json_object"

        original_system_prompt = system_prompt
        original_user_payload = dict(user_payload)
        current_system_prompt = system_prompt
        current_user_payload = dict(user_payload)
        total_validation_retries = 0
        retry_limit = max(0, int(max_retries))

        for attempt in range(retry_limit + 1):
            try:
                response = self._transport.invoke_json(
                    system_prompt=current_system_prompt,
                    user_payload=current_user_payload,
                    max_output_tokens=max_output_tokens,
                    operation_name=operation_name,
                    response_format_type=resolved_response_format,
                    response_format_schema=effective_schema,
                    response_format_name=response_format_name,
                    response_format_strict=response_format_strict,
                )
                parsed_payload = _response_payload(response)
                if response_model is None:
                    return response
                response_model.model_validate(parsed_payload)
                _emit_gateway_log(
                    f"[author_v3.gateway] operation={operation_name} validation_retries={total_validation_retries}"
                )
                return response
            except ValidationError as exc:
                if attempt >= retry_limit:
                    _emit_gateway_log(
                        "[author_v3.gateway] "
                        f"operation={operation_name} validation_retries={total_validation_retries} "
                        f"status=failed\n{_format_validation_error(exc)}"
                    )
                    raise
                total_validation_retries += 1
                err_msg = _format_validation_error(exc)
                _emit_gateway_log(
                    "[author_v3.gateway] "
                    f"operation={operation_name} retry={total_validation_retries}/{retry_limit}\n{err_msg}"
                )
                current_system_prompt = (
                    f"{original_system_prompt}\n\n"
                    "⚠️ 上次输出验证失败，请严格遵守 schema 的 enum 和类型约束。\n"
                    f"上次错误：\n{err_msg}\n\n"
                    "只输出完全符合 schema 的 JSON 对象。"
                )
                current_user_payload = dict(original_user_payload)
                current_user_payload["validation_feedback"] = (
                    f"⚠️ 上次输出验证失败：\n{err_msg}\n\n请严格按照 schema 的 enum 和类型约束重新输出。"
                )
                current_user_payload["validation_retry"] = total_validation_retries
                continue
            except AuthorV3GatewayError as exc:
                if exc.code != "llm_invalid_json":
                    raise
                if attempt >= retry_limit:
                    raise
                err_msg = str(exc)[:200]
                current_system_prompt = original_system_prompt
                current_user_payload = dict(original_user_payload)
                current_user_payload["json_retry_feedback"] = (
                    "The previous JSON output was malformed: "
                    + err_msg
                    + "\nPlease output strictly valid JSON with all fields double-quoted and arrays/objects properly comma-separated."
                )
                current_user_payload["json_retry"] = attempt + 1
                continue

        raise RuntimeError("unreachable")


def resolve_author_v3_live_mode_chain(mode: AuthorV3RunMode) -> tuple[ConcreteAuthorV3LiveMode, ...]:
    if mode == "deterministic":
        return ()
    if mode in {"live_priority", "pure_gpt"}:
        return AUTHOR_V3_PRIORITY_CHAIN
    return (mode,)


def _resolved_profile_settings(mode: ConcreteAuthorV3LiveMode, settings: Settings) -> tuple[str, str, str, bool]:
    if mode == "live_gpt_5_4_mini":
        return (
            settings.resolved_responses_base_url(),
            settings.resolved_responses_api_key(),
            settings.resolved_author_responses_model() or "gpt-5.4-mini",
            settings.resolved_responses_use_session_cache(),
        )
    raise AuthorV3GatewayError(
        code="llm_mode_invalid",
        message=f"live gateway does not support mode={mode}",
        status_code=400,
    )


def get_author_v3_llm_gateway(
    mode: AuthorV3RunMode,
    settings: Settings | None = None,
) -> AuthorV3LLMGateway | None:
    if mode == "deterministic":
        return None
    chain = resolve_author_v3_live_mode_chain(mode)
    if not chain:
        return None
    resolved = settings or get_settings()
    selected_mode = chain[0]
    base_url, api_key, model, use_session_cache = _resolved_profile_settings(selected_mode, resolved)
    if not base_url or not api_key or not model:
        raise AuthorV3GatewayError(
            code="llm_config_missing",
            message=f"missing live gateway configuration for mode={selected_mode}",
            status_code=500,
        )
    client = build_openai_client(
        base_url=base_url,
        api_key=api_key,
        api_keys=resolved.responses_api_key_pool(),
        use_session_cache=bool(use_session_cache),
        session_cache_header=resolved.responses_session_cache_header,
        session_cache_value=resolved.responses_session_cache_value,
        requests_per_minute=(
            int(resolved.responses_author_requests_per_minute)
            if resolved.responses_author_requests_per_minute is not None
            else None
        ),
        rate_limit_scope=("author_v3" if resolved.responses_author_requests_per_minute is not None else None),
        chat_json_stream_mode=resolved.responses_chat_json_stream_mode,
        chat_json_stream_hosts=resolved.responses_chat_json_stream_host_list(),
    )
    return AuthorV3LLMGateway(
        client=client,
        model=model,
        profile_id=selected_mode,
        timeout_seconds=float(resolved.responses_timeout_seconds),
        use_session_cache=bool(use_session_cache),
        json_content_type_hint=bool(resolved.responses_json_content_type_hint),
        json_object_prompt_only=bool(resolved.responses_json_object_prompt_only),
    )
