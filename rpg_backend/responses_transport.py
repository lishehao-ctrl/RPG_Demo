from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Generic, Literal, TypeVar
from urllib.parse import urlparse

import httpx

T = TypeVar("T")
ErrorFactory = Callable[[str, str, int], Exception]


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_MISSING_COMMA_BETWEEN_OBJECTS_RE = re.compile(r"}(\s*\n\s*){")
_MISSING_COMMA_BETWEEN_VALUES_RE = re.compile(r'("(?:[^"\\]|\\.)*"|\d|true|false|null|\]|\})(\s*\n\s*)("[^"]+"\s*:)')


def _repair_json_text(text: str) -> str:
    """Best-effort cleanup for common LLM JSON malformations.

    Cleans up:
    - trailing commas before } or ]
    - missing commas between adjacent objects on separate lines
    - missing commas between a value and the next key
    """
    repaired = text
    repaired = _TRAILING_COMMA_RE.sub(r"\1", repaired)
    repaired = _MISSING_COMMA_BETWEEN_OBJECTS_RE.sub(r"},\1{", repaired)
    repaired = _MISSING_COMMA_BETWEEN_VALUES_RE.sub(r"\1,\2\3", repaired)
    return repaired


def _try_parse_json(text: str) -> tuple[Any, bool, str | None]:
    """Try strict json.loads, then a repair pass.

    Returns (payload, was_repaired, error_message).
    """
    try:
        return json.loads(text), False, None
    except Exception as exc:  # noqa: BLE001
        first_error = str(exc)
    repaired = _repair_json_text(text)
    if repaired != text:
        try:
            return json.loads(repaired), True, None
        except Exception:  # noqa: BLE001
            pass
    return None, False, first_error


class _RequestsPerMinuteLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.requests_per_minute = max(1, int(requests_per_minute))
        self._lock = threading.Lock()
        self._recent_requests: deque[float] = deque()

    def acquire(self) -> None:
        window_seconds = 60.0
        while True:
            now = time.monotonic()
            sleep_for = 0.0
            with self._lock:
                cutoff = now - window_seconds
                while self._recent_requests and self._recent_requests[0] <= cutoff:
                    self._recent_requests.popleft()
                if len(self._recent_requests) < self.requests_per_minute:
                    self._recent_requests.append(now)
                    return
                sleep_for = max(0.0, self._recent_requests[0] + window_seconds - now)
            if sleep_for > 0:
                time.sleep(sleep_for)


_RPM_LIMITERS_LOCK = threading.Lock()
_RPM_LIMITERS: dict[str, _RequestsPerMinuteLimiter] = {}
_PENDING_OVERLOAD_RETRY_DELAY_SECONDS = 5.0
_EMPTY_CONTENT_RETRY_DELAY_SECONDS = 0.5
_DEFAULT_JSON_SCHEMA_NAME = "structured_output"
_DEFAULT_STREAM_CHAT_JSON_HOSTS: tuple[str, ...] = ("api.xcode.best", "beecode.cc")
_DEFAULT_PERMISSIVE_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "_": {
            "type": "string",
            "description": "Optional placeholder. Real output can use any keys.",
        }
    },
    "additionalProperties": False,
}


def _acquire_rpm_slot(*, scope: str, requests_per_minute: int) -> None:
    normalized_scope = str(scope or "").strip() or "default"
    with _RPM_LIMITERS_LOCK:
        limiter = _RPM_LIMITERS.get(normalized_scope)
        if limiter is None or limiter.requests_per_minute != int(requests_per_minute):
            limiter = _RequestsPerMinuteLimiter(int(requests_per_minute))
            _RPM_LIMITERS[normalized_scope] = limiter
    limiter.acquire()


class ResponsesProviderError(RuntimeError):
    """Raised by raw provider transport with optional upstream HTTP status."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ResponsesJSONResponse:
    payload: dict[str, Any]
    response_id: str | None
    usage: dict[str, Any]
    input_characters: int


@dataclass(frozen=True)
class StructuredResponse(Generic[T]):
    value: T
    response_id: str | None


def _coerce_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str):
        return direct
    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "output_text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        if parts:
            return "".join(parts)
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if isinstance(block.get("text"), str):
                            parts.append(block["text"])
                    if parts:
                        return "".join(parts)
    return ""


def _coerce_error_message(payload: Any, *, status_code: int) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return f"provider returned HTTP {status_code}"


def usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        raw = usage.model_dump()
    elif isinstance(usage, dict):
        raw = usage
    else:
        raw = {}
        for key in dir(usage):
            if key.startswith("_"):
                continue
            try:
                raw[key] = getattr(usage, key)
            except Exception:  # noqa: BLE001
                continue
    normalized: dict[str, Any] = {}
    input_details = raw.get("input_tokens_details")
    if isinstance(input_details, dict) and isinstance(input_details.get("cached_tokens"), (int, float)):
        normalized["cached_input_tokens"] = int(input_details["cached_tokens"])
    output_details = raw.get("output_tokens_details")
    if isinstance(output_details, dict) and isinstance(output_details.get("reasoning_tokens"), (int, float)):
        normalized["reasoning_tokens"] = int(output_details["reasoning_tokens"])
    x_details = raw.get("x_details")
    if isinstance(x_details, list) and x_details:
        detail = x_details[0]
        if isinstance(detail, dict):
            if isinstance(detail.get("x_billing_type"), str):
                normalized["billing_type"] = detail["x_billing_type"]
            prompt_details = detail.get("prompt_tokens_details")
            if isinstance(prompt_details, dict):
                if isinstance(prompt_details.get("cached_tokens"), (int, float)):
                    normalized["cached_input_tokens"] = int(prompt_details["cached_tokens"])
                if isinstance(prompt_details.get("cache_creation_input_tokens"), (int, float)):
                    normalized["cache_creation_input_tokens"] = int(prompt_details["cache_creation_input_tokens"])
                cache_creation = prompt_details.get("cache_creation")
                if isinstance(cache_creation, dict):
                    for key, value in cache_creation.items():
                        if isinstance(value, (int, float)):
                            normalized[str(key)] = int(value)
                if isinstance(prompt_details.get("cache_type"), str):
                    normalized["cache_type"] = prompt_details["cache_type"]
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            normalized[str(key)] = int(value)
    prompt_tokens = raw.get("prompt_tokens")
    if "input_tokens" not in normalized and isinstance(prompt_tokens, (int, float)) and not isinstance(prompt_tokens, bool):
        normalized["input_tokens"] = int(prompt_tokens)
    completion_tokens = raw.get("completion_tokens")
    if "output_tokens" not in normalized and isinstance(completion_tokens, (int, float)) and not isinstance(completion_tokens, bool):
        normalized["output_tokens"] = int(completion_tokens)
    if "total_tokens" not in normalized and all(
        isinstance(normalized.get(key), int) for key in ("input_tokens", "output_tokens")
    ):
        normalized["total_tokens"] = int(normalized["input_tokens"]) + int(normalized["output_tokens"])
    return normalized


def _failure_message_bucket(message: str) -> str:
    lowered = str(message or "").casefold()
    if any(token in lowered for token in ("timeout", "timed out", "deadline exceeded")):
        return "timeout"
    if any(
        token in lowered
        for token in (
            "could not resolve host",
            "nodename nor servname",
            "name or service not known",
            "temporary failure in name resolution",
            "dns",
        )
    ):
        return "dns"
    if any(token in lowered for token in ("connection reset", "connection aborted", "connection refused", "connect", "network")):
        return "connection"
    if any(token in lowered for token in ("429", "rate limit", "too many requests", "pending requests")):
        return "rate_limit"
    if any(
        token in lowered
        for token in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "invalid api key",
            "invalid token",
            "无效的令牌",
            "授权格式错误",
            "未授权",
            "鉴权",
            "令牌",
        )
    ):
        return "auth"
    if any(token in lowered for token in ("500", "502", "503", "504", "bad gateway", "service unavailable", "server error")):
        return "service"
    return "unknown"


def _is_beecode_base_url(base_url: str) -> bool:
    try:
        hostname = (urlparse(str(base_url)).hostname or "").strip().lower()
    except Exception:
        hostname = ""
    return hostname == "beecode.cc" or hostname.endswith(".beecode.cc")


def _is_xcode_base_url(base_url: str) -> bool:
    try:
        hostname = (urlparse(str(base_url)).hostname or "").strip().lower()
    except Exception:
        hostname = ""
    return hostname == "api.xcode.best" or hostname.endswith(".xcode.best")


def _supports_stream_chat_json(base_url: str) -> bool:
    return _is_xcode_base_url(base_url) or _is_beecode_base_url(base_url)


def _normalize_hostname_list(raw_hosts: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not raw_hosts:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_hosts:
        candidate = str(item or "").strip().lower()
        if not candidate:
            continue
        if candidate.startswith("http://") or candidate.startswith("https://"):
            try:
                candidate = (urlparse(candidate).hostname or "").strip().lower()
            except Exception:
                candidate = ""
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
    return tuple(out)


def _base_url_matches_host_set(base_url: str, host_set: tuple[str, ...]) -> bool:
    try:
        hostname = (urlparse(str(base_url)).hostname or "").strip().lower()
    except Exception:
        hostname = ""
    if not hostname:
        return False
    for candidate in host_set:
        if hostname == candidate or hostname.endswith(f".{candidate}"):
            return True
    return False


def _normalize_stream_mode(raw_mode: str | None) -> Literal["auto", "force", "off"]:
    lowered = str(raw_mode or "").strip().lower()
    if lowered in {"force", "always", "on", "true", "1"}:
        return "force"
    if lowered in {"off", "disable", "disabled", "never", "false", "0"}:
        return "off"
    return "auto"


def _is_pending_overload_error(*, status_code: int | None, message: str) -> bool:
    if isinstance(status_code, int) and status_code == 429:
        return True
    lowered = str(message or "").casefold()
    return "too many pending requests" in lowered


def _is_empty_content_error(*, status_code: int | None, message: str) -> bool:
    if isinstance(status_code, int) and status_code >= 400:
        return False
    lowered = str(message or "").casefold()
    return any(
        token in lowered
        for token in (
            "provider returned empty content",
            "empty response",
            "empty content",
            "message content was null",
        )
    )


class _RawResponsesResource:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_keys: tuple[str, ...] | None = None,
        default_headers: dict[str, str] | None = None,
        requests_per_minute: int | None = None,
        rate_limit_scope: str | None = None,
        chat_json_stream_mode: Literal["auto", "force", "off"] = "auto",
        chat_json_stream_hosts: tuple[str, ...] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._use_chat_completions = True
        explicit_pool = tuple(key for key in (api_keys or ()) if str(key).strip())
        fallback = str(api_key).strip()
        self._api_key_pool = explicit_pool or ((fallback,) if fallback else ())
        self._api_key = self._api_key_pool[0] if self._api_key_pool else ""
        self._api_key_index = 0
        self._api_key_lock = threading.Lock()
        self._default_headers = dict(default_headers or {})
        self._requests_per_minute = int(requests_per_minute) if requests_per_minute is not None else None
        self._rate_limit_scope = str(rate_limit_scope or "").strip() or self._base_url
        self._chat_json_stream_mode = _normalize_stream_mode(chat_json_stream_mode)
        parsed_stream_hosts = _normalize_hostname_list(chat_json_stream_hosts)
        self._chat_json_stream_hosts = parsed_stream_hosts or _DEFAULT_STREAM_CHAT_JSON_HOSTS
        self._client_lock = threading.Lock()
        self._client: httpx.Client | None = None

    def _should_use_stream_chat(self, endpoint_url: str) -> bool:
        if not endpoint_url.endswith("/chat/completions"):
            return False
        if self._chat_json_stream_mode == "force":
            return True
        if self._chat_json_stream_mode == "off":
            return False
        if self._chat_json_stream_hosts:
            return _base_url_matches_host_set(self._base_url, self._chat_json_stream_hosts)
        return _supports_stream_chat_json(self._base_url)

    def _next_api_key(self) -> str:
        if not self._api_key_pool:
            return self._api_key
        if len(self._api_key_pool) == 1:
            return self._api_key_pool[0]
        with self._api_key_lock:
            index = self._api_key_index
            self._api_key_index = (self._api_key_index + 1) % len(self._api_key_pool)
        return self._api_key_pool[index]

    def _build_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=60.0,
            limits=httpx.Limits(
                max_connections=200,
                max_keepalive_connections=100,
            ),
        )

    def _get_or_create_client(self) -> httpx.Client:
        with self._client_lock:
            if self._client is None:
                self._client = self._build_client()
            return self._client

    def _reset_client(self) -> None:
        with self._client_lock:
            previous = self._client
            self._client = self._build_client()
        if previous is not None:
            previous.close()

    def close(self) -> None:
        with self._client_lock:
            previous = self._client
            self._client = None
        if previous is not None:
            previous.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return

    def _request_via_stream_chat_completions(
        self,
        *,
        endpoint_url: str,
        headers: dict[str, str],
        request_payload: dict[str, Any],
        timeout_seconds: float,
    ) -> SimpleNamespace:
        streamed_payload = dict(request_payload)
        streamed_payload["stream"] = True
        for attempt in range(2):
            client = self._get_or_create_client()
            try:
                with client.stream(
                    "POST",
                    endpoint_url,
                    headers=headers,
                    json=streamed_payload,
                    timeout=timeout_seconds,
                ) as response:
                    if response.status_code >= 400:
                        try:
                            body = json.loads(response.read())
                        except Exception:
                            body = response.text
                        raise ResponsesProviderError(
                            _coerce_error_message(body, status_code=response.status_code),
                            status_code=response.status_code,
                        )
                    output_parts: list[str] = []
                    usage: dict[str, Any] = {}
                    response_id: str | None = None
                    for raw_line in response.iter_lines():
                        line = str(raw_line or "").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        chunk_text = line[len("data:") :].strip()
                        if chunk_text == "[DONE]":
                            break
                        try:
                            chunk_payload = json.loads(chunk_text)
                        except Exception:
                            continue
                        if response_id is None and isinstance(chunk_payload.get("id"), str):
                            response_id = chunk_payload["id"]
                        chunk_usage = chunk_payload.get("usage")
                        if isinstance(chunk_usage, dict):
                            usage = chunk_usage
                        choices = chunk_payload.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        first_choice = choices[0]
                        if not isinstance(first_choice, dict):
                            continue
                        delta = first_choice.get("delta")
                        if not isinstance(delta, dict):
                            delta = {}
                        content = delta.get("content")
                        if isinstance(content, str):
                            output_parts.append(content)
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and isinstance(block.get("text"), str):
                                    output_parts.append(block["text"])
                        message = first_choice.get("message")
                        if isinstance(message, dict):
                            message_content = message.get("content")
                            if isinstance(message_content, str):
                                output_parts.append(message_content)
                            elif isinstance(message_content, list):
                                for block in message_content:
                                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                                        output_parts.append(block["text"])
                        chunk_output_text = chunk_payload.get("output_text")
                        if isinstance(chunk_output_text, str):
                            output_parts.append(chunk_output_text)
                    merged_output = "".join(output_parts).strip()
                    if not merged_output:
                        raise ResponsesProviderError(
                            "provider returned empty content",
                            status_code=response.status_code,
                        )
                    return SimpleNamespace(
                        id=response_id,
                        output_text=merged_output,
                        usage=usage,
                    )
            except ResponsesProviderError:
                raise
            except httpx.HTTPError as exc:
                if attempt == 0:
                    self._reset_client()
                    continue
                raise ResponsesProviderError(
                    str(exc),
                    status_code=getattr(getattr(exc, "response", None), "status_code", None),
                ) from exc
        raise ResponsesProviderError("provider request failed without response", status_code=None)

    def create(self, **kwargs: Any) -> SimpleNamespace:  # noqa: ANN401
        timeout = kwargs.pop("timeout", None)
        extra_body = kwargs.pop("extra_body", None)
        payload = dict(kwargs)
        if isinstance(extra_body, dict):
            payload.update(extra_body)
        if self._requests_per_minute and self._requests_per_minute > 0:
            _acquire_rpm_slot(
                scope=self._rate_limit_scope,
                requests_per_minute=self._requests_per_minute,
            )
        endpoint_url, request_payload = self._prepare_request_payload(payload)
        use_stream_chat = self._should_use_stream_chat(endpoint_url)
        pending_retry_attempted = False
        empty_content_retry_attempted = False
        while True:
            active_api_key = self._next_api_key()
            headers = {
                "Authorization": f"Bearer {active_api_key}",
                "Content-Type": "application/json",
                **self._default_headers,
            }
            if _is_beecode_base_url(self._base_url):
                headers.setdefault("Accept", "application/json")
            try:
                if use_stream_chat:
                    return self._request_via_stream_chat_completions(
                        endpoint_url=endpoint_url,
                        headers=headers,
                        request_payload=request_payload,
                        timeout_seconds=timeout or 60.0,
                    )
                response: httpx.Response | None = None
                for attempt in range(2):
                    client = self._get_or_create_client()
                    try:
                        response = client.post(
                            endpoint_url,
                            headers=headers,
                            json=request_payload,
                            timeout=timeout or 60.0,
                        )
                        break
                    except httpx.HTTPError as exc:
                        if attempt == 0:
                            self._reset_client()
                            continue
                        raise ResponsesProviderError(
                            str(exc),
                            status_code=getattr(getattr(exc, "response", None), "status_code", None),
                        ) from exc
                if response is None:
                    raise ResponsesProviderError("provider request failed without response", status_code=None)
                try:
                    body = response.json()
                except Exception:
                    body = response.text
                if response.status_code >= 400:
                    raise ResponsesProviderError(
                        _coerce_error_message(body, status_code=response.status_code),
                        status_code=response.status_code,
                    )
                if not isinstance(body, dict):
                    raise ResponsesProviderError("provider returned a non-object response payload", status_code=response.status_code)
                output_text = _coerce_output_text(body).strip()
                if not output_text:
                    raise ResponsesProviderError("provider returned empty content", status_code=response.status_code)
                return SimpleNamespace(
                    id=body.get("id"),
                    output_text=output_text,
                    usage=body.get("usage"),
                )
            except ResponsesProviderError as exc:
                message = str(exc)
                if (not pending_retry_attempted) and _is_pending_overload_error(
                    status_code=getattr(exc, "status_code", None),
                    message=message,
                ):
                    pending_retry_attempted = True
                    time.sleep(_PENDING_OVERLOAD_RETRY_DELAY_SECONDS)
                    continue
                if (not empty_content_retry_attempted) and _is_empty_content_error(
                    status_code=getattr(exc, "status_code", None),
                    message=message,
                ):
                    empty_content_retry_attempted = True
                    time.sleep(_EMPTY_CONTENT_RETRY_DELAY_SECONDS)
                    continue
                raise

    def _prepare_request_payload(self, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        instructions = str(payload.get("instructions") or "").strip()
        input_text = payload.get("input")
        if not isinstance(input_text, str):
            input_text = json.dumps(input_text, ensure_ascii=False, sort_keys=True)
        messages: list[dict[str, str]] = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        messages.append({"role": "user", "content": input_text})

        chat_payload: dict[str, Any] = {
            "model": payload.get("model"),
            "messages": messages,
        }
        if isinstance(payload.get("max_output_tokens"), int):
            chat_payload["max_tokens"] = int(payload["max_output_tokens"])
        if isinstance(payload.get("temperature"), (int, float)) and not isinstance(payload.get("temperature"), bool):
            chat_payload["temperature"] = float(payload["temperature"])
        response_format = payload.get("response_format")
        if isinstance(response_format, dict):
            chat_payload["response_format"] = response_format
        else:
            chat_payload["response_format"] = {"type": "json_object"}
        # Pass through provider-specific extras already promoted from `extra_body`
        # into `payload` by `RawResponsesClient.create()`. Without this,
        # qwen3.5-flash's `enable_thinking=False` is lost here and the model
        # defaults to thinking-on (3000+ reasoning_tokens per call, ~30s instead
        # of ~2s). Also covers thinking_budget / chat_template_kwargs / content_type.
        _passthrough_keys = ("enable_thinking", "thinking_budget", "chat_template_kwargs", "content_type")
        for _key in _passthrough_keys:
            if _key in payload and _key not in chat_payload:
                chat_payload[_key] = payload[_key]
        return f"{self._base_url}/chat/completions", chat_payload


class RawResponsesClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_keys: tuple[str, ...] | None = None,
        default_headers: dict[str, str] | None = None,
        requests_per_minute: int | None = None,
        rate_limit_scope: str | None = None,
        chat_json_stream_mode: Literal["auto", "force", "off"] = "auto",
        chat_json_stream_hosts: tuple[str, ...] | None = None,
    ) -> None:
        self.responses = _RawResponsesResource(
            base_url=base_url,
            api_key=api_key,
            api_keys=api_keys,
            default_headers=default_headers,
            requests_per_minute=requests_per_minute,
            rate_limit_scope=rate_limit_scope,
            chat_json_stream_mode=chat_json_stream_mode,
            chat_json_stream_hosts=chat_json_stream_hosts,
        )


def build_openai_client(
    *,
    base_url: str,
    api_key: str,
    api_keys: tuple[str, ...] | None = None,
    use_session_cache: bool,
    session_cache_header: str,
    session_cache_value: str,
    requests_per_minute: int | None = None,
    rate_limit_scope: str | None = None,
    chat_json_stream_mode: Literal["auto", "force", "off"] = "auto",
    chat_json_stream_hosts: tuple[str, ...] | None = None,
) -> RawResponsesClient:
    global_rpm_raw = str(os.environ.get("APP_RESPONSES_GLOBAL_REQUESTS_PER_MINUTE") or "").strip()
    if global_rpm_raw:
        try:
            requests_per_minute = max(1, int(global_rpm_raw))
            rate_limit_scope = str(os.environ.get("APP_RESPONSES_GLOBAL_RATE_LIMIT_SCOPE") or "").strip() or "responses:global"
        except ValueError:
            pass
    default_headers: dict[str, str] = {}
    if use_session_cache:
        default_headers = {
            session_cache_header: session_cache_value,
        }
    return RawResponsesClient(
        base_url=base_url,
        api_key=api_key,
        api_keys=api_keys,
        default_headers=default_headers,
        requests_per_minute=requests_per_minute,
        rate_limit_scope=rate_limit_scope,
        chat_json_stream_mode=chat_json_stream_mode,
        chat_json_stream_hosts=chat_json_stream_hosts,
    )


def _provider_error_status_code(exc: Exception) -> int:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and 100 <= status <= 599:
        return status
    return 502


@dataclass
class ResponsesJSONTransport:
    client: Any
    model: str
    timeout_seconds: float
    use_session_cache: bool
    temperature: float
    enable_thinking: bool
    provider_failed_code: str
    invalid_response_code: str
    invalid_json_code: str
    error_factory: ErrorFactory
    explicit_disable_thinking: bool = False
    json_content_type_hint: bool = False
    json_object_prompt_only: bool = False
    call_trace: list[dict[str, Any]] = field(default_factory=list)

    _JSON_OBJECT_PROMPT_PREFIX = (
        "You must return exactly one strict JSON object. "
        "Do not output markdown, fences, comments, or any extra prose."
    )

    def _is_xcode_mode(self) -> bool:
        responses_resource = getattr(self.client, "responses", None)
        base_url = getattr(responses_resource, "_base_url", "")
        return _is_xcode_base_url(str(base_url))

    @staticmethod
    def _resolved_schema_payload(
        response_format_schema: dict[str, Any] | None,
        *,
        xcode_mode: bool,
    ) -> dict[str, Any]:
        if not isinstance(response_format_schema, dict):
            payload = dict(_DEFAULT_PERMISSIVE_OBJECT_SCHEMA)
        else:
            payload = dict(response_format_schema)
        if str(payload.get("type") or "").strip().lower() != "object":
            return payload
        properties = payload.get("properties")
        if not isinstance(properties, dict) or not properties:
            payload["properties"] = dict(_DEFAULT_PERMISSIVE_OBJECT_SCHEMA["properties"])
            properties = payload["properties"]
        if xcode_mode:
            payload["additionalProperties"] = False
            payload["required"] = [str(key) for key in properties.keys()]
        else:
            payload.setdefault("additionalProperties", False)
        return payload

    def invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_output_tokens: int | None,
        previous_response_id: str | None = None,
        operation_name: str | None = None,
        plaintext_fallback_key: str | None = None,
        response_format_type: Literal["json_object", "json_schema"] | None = None,
        response_format_schema: dict[str, Any] | None = None,
        response_format_name: str | None = None,
        response_format_strict: bool = True,
    ) -> ResponsesJSONResponse:
        xcode_mode = self._is_xcode_mode()
        resolved_response_format = response_format_type
        if resolved_response_format is None:
            resolved_response_format = "json_schema" if isinstance(response_format_schema, dict) else "json_object"

        user_text = json.dumps(user_payload, ensure_ascii=False, sort_keys=True)
        input_characters = len(user_text)
        instructions = system_prompt
        if resolved_response_format == "json_object" and self.json_object_prompt_only:
            instructions = f"{self._JSON_OBJECT_PROMPT_PREFIX}\n\n{system_prompt}"
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": user_text,
            "max_output_tokens": max_output_tokens,
            "timeout": self.timeout_seconds,
            "temperature": self.temperature,
        }
        extra_body: dict[str, Any] = {}
        if self.enable_thinking:
            extra_body["enable_thinking"] = True
        elif self.explicit_disable_thinking:
            extra_body["enable_thinking"] = False
        if resolved_response_format == "json_object":
            # Always send explicit response_format for provider-side JSON enforcement.
            # Keep prompt-prefix behavior as an additive safeguard when enabled.
            extra_body["response_format"] = {"type": "json_object"}
            if self.json_content_type_hint:
                extra_body["content_type"] = "json"
        elif resolved_response_format == "json_schema":
            schema_name = (response_format_name or _DEFAULT_JSON_SCHEMA_NAME).strip() or _DEFAULT_JSON_SCHEMA_NAME
            schema_payload = self._resolved_schema_payload(
                response_format_schema,
                xcode_mode=xcode_mode,
            )
            extra_body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": bool(response_format_strict),
                    "schema": schema_payload,
                },
            }
        if extra_body:
            request_kwargs["extra_body"] = extra_body
        if self.use_session_cache and previous_response_id:
            request_kwargs["previous_response_id"] = previous_response_id
        operation = operation_name or "unknown"
        attempt_index = sum(1 for entry in self.call_trace if entry.get("operation") == operation) + 1
        try:
            response = self.client.responses.create(**request_kwargs)
        except Exception as exc:  # noqa: BLE001
            status_code = _provider_error_status_code(exc)
            self.call_trace.append(
                {
                    "operation": operation,
                    "response_id": None,
                    "used_previous_response_id": bool(previous_response_id),
                    "session_cache_enabled": bool(self.use_session_cache),
                    "max_output_tokens": max_output_tokens,
                    "input_characters": input_characters,
                    "response_format_type": resolved_response_format,
                    "json_object_prompt_only": bool(self.json_object_prompt_only),
                    "json_content_type_hint": bool(self.json_content_type_hint),
                    "usage": {},
                    "attempt_index": attempt_index,
                    "response_received": False,
                    "failure_code": self.provider_failed_code,
                    "failure_message_bucket": _failure_message_bucket(str(exc)),
                    "failure_status_code": status_code,
                }
            )
            raise self.error_factory(self.provider_failed_code, str(exc), status_code) from exc
        try:
            content = response.output_text
        except Exception as exc:  # noqa: BLE001
            raise self.error_factory(
                self.invalid_response_code,
                "provider response did not include message content",
                502,
            ) from exc
        text = str(content or "").strip()
        original_text = text
        if not text:
            raise self.error_factory(
                self.invalid_json_code,
                "provider returned empty content",
                502,
            )
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        payload, _, parse_error = _try_parse_json(text)
        if payload is None:
            if plaintext_fallback_key and original_text:
                payload = {plaintext_fallback_key: original_text}
            else:
                raise self.error_factory(self.invalid_json_code, parse_error or "invalid JSON", 502)
        if not isinstance(payload, dict):
            raise self.error_factory(
                self.invalid_json_code,
                "provider returned a non-object JSON payload",
                502,
            )
        usage = usage_to_dict(getattr(response, "usage", None))
        self.call_trace.append(
            {
                "operation": operation,
                "response_id": getattr(response, "id", None),
                "used_previous_response_id": bool(previous_response_id),
                "session_cache_enabled": bool(self.use_session_cache),
                "max_output_tokens": max_output_tokens,
                "input_characters": input_characters,
                "response_format_type": resolved_response_format,
                "json_object_prompt_only": bool(self.json_object_prompt_only),
                "json_content_type_hint": bool(self.json_content_type_hint),
                "usage": usage,
                "attempt_index": attempt_index,
                "response_received": True,
                "failure_code": None,
                "failure_message_bucket": None,
            }
        )
        return ResponsesJSONResponse(
            payload=payload,
            response_id=getattr(response, "id", None),
            usage=usage,
            input_characters=input_characters,
        )
