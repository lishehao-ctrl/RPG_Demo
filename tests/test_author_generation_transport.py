from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from rpg_backend.author.contracts import FocusedBrief
from rpg_backend.author.gateway import AuthorGatewayError, AuthorLLMGateway
from rpg_backend.author_v2.gateway import AuthorV2LLMGateway
from rpg_backend.author.generation import beats as beat_generation
from rpg_backend.author.generation import cast as cast_generation
from rpg_backend.author.generation import endings as ending_generation
from rpg_backend.author.generation import routes as route_generation
from rpg_backend.author.generation import story_frame as story_generation
from rpg_backend.play.gateway import PlayLLMGateway
from rpg_backend.responses_transport import (
    RawResponsesClient,
    ResponsesJSONTransport,
    ResponsesProviderError,
    _failure_message_bucket,
    usage_to_dict,
)
from tests.author_fixtures import (
    FakeClient,
    author_fixture_bundle,
    cast_draft,
    cast_overview_draft,
    ending_anchor_suggestion_payload,
    route_opportunity_plan_draft,
    story_frame_draft,
    story_frame_scaffold_draft,
    beat_plan_skeleton_draft,
)


def _gateway(client: FakeClient) -> AuthorLLMGateway:
    return AuthorLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        max_output_tokens_overview=700,
        max_output_tokens_beat_plan=900,
        max_output_tokens_beat_skeleton=900,
        max_output_tokens_beat_repair=700,
        max_output_tokens_rulepack=900,
        use_session_cache=True,
    )


def test_shared_transport_usage_normalizer_extracts_cache_fields() -> None:
    usage = usage_to_dict(
        {
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
            "output_tokens_details": {"reasoning_tokens": 12},
            "x_details": [
                {
                    "x_billing_type": "response_api",
                    "prompt_tokens_details": {
                        "cached_tokens": 60,
                        "cache_creation_input_tokens": 20,
                        "cache_type": "ephemeral",
                    },
                }
            ],
        }
    )

    assert usage["input_tokens"] == 120
    assert usage["cached_input_tokens"] == 60
    assert usage["cache_creation_input_tokens"] == 20
    assert usage["billing_type"] == "response_api"
    assert usage["cache_type"] == "ephemeral"


def test_shared_transport_usage_normalizer_maps_chat_completions_tokens() -> None:
    usage = usage_to_dict(
        {
            "prompt_tokens": 18,
            "completion_tokens": 7,
        }
    )

    assert usage["input_tokens"] == 18
    assert usage["output_tokens"] == 7
    assert usage["total_tokens"] == 25


def test_shared_transport_is_single_usage_normalizer_definition() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    matches: list[str] = []
    for path in (repo_root / "rpg_backend").rglob("*.py"):
        if "def usage_to_dict" in path.read_text():
            matches.append(path.relative_to(repo_root).as_posix())
    assert matches == ["rpg_backend/responses_transport.py"]


def test_play_router_module_removed_after_shared_story_profile_refactor() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert not (repo_root / "rpg_backend" / "play" / "router.py").exists()


def test_shared_transport_omits_enable_thinking_flag_when_disabled() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {"response_format": {"type": "json_object"}}


def test_shared_transport_includes_json_object_response_format_when_requested() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type="json_object",
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {"response_format": {"type": "json_object"}}


def test_shared_transport_includes_json_schema_response_format_when_requested() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["pong"],
        "properties": {
            "pong": {"type": "boolean"},
        },
    }
    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type="json_schema",
        response_format_schema=schema,
        response_format_name="demo_schema",
        response_format_strict=True,
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "demo_schema",
                "strict": True,
                "schema": schema,
            },
        },
    }


def test_shared_transport_json_schema_uses_default_permissive_schema_when_missing() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type="json_schema",
    )

    assert response.payload == {"pong": True}
    response_format = client.calls[0]["extra_body"]["response_format"]
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]["schema"]
    assert schema["type"] == "object"
    assert isinstance(schema["properties"], dict)
    assert "_" in schema["properties"]
    assert schema["additionalProperties"] is False


def test_shared_transport_xcode_defaults_to_json_object_without_schema() -> None:
    client = FakeClient([{"pong": True}])
    setattr(client.responses, "_base_url", "https://api.xcode.best/v1")
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="gpt-5.4-mini",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type=None,
    )

    assert response.payload == {"pong": True}
    response_format = client.calls[0]["extra_body"]["response_format"]
    assert response_format["type"] == "json_object"


def test_shared_transport_xcode_respects_explicit_json_object() -> None:
    client = FakeClient([{"pong": True}])
    setattr(client.responses, "_base_url", "https://api.xcode.best/v1")
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="gpt-5.4-mini",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type="json_object",
    )

    assert response.payload == {"pong": True}
    response_format = client.calls[0]["extra_body"]["response_format"]
    assert response_format["type"] == "json_object"


def test_shared_transport_infers_json_schema_when_schema_supplied_without_type() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type=None,
        response_format_schema={
            "type": "object",
            "properties": {"pong": {"type": "boolean"}},
            "required": ["pong"],
            "additionalProperties": False,
        },
    )

    assert response.payload == {"pong": True}
    response_format = client.calls[0]["extra_body"]["response_format"]
    assert response_format["type"] == "json_schema"


def test_shared_transport_prompt_only_json_mode_keeps_response_format_with_prompt_guard() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        json_object_prompt_only=True,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type="json_object",
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {"response_format": {"type": "json_object"}}
    assert "You must return exactly one strict JSON object." in str(client.calls[0]["instructions"])


def test_shared_transport_can_attach_json_content_type_hint() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        json_content_type_hint=True,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type="json_object",
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {
        "response_format": {"type": "json_object"},
        "content_type": "json",
    }


def test_shared_transport_can_explicitly_disable_thinking() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        explicit_disable_thinking=True,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        response_format_type="json_object",
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {"enable_thinking": False, "response_format": {"type": "json_object"}}


def test_shared_transport_emits_enable_thinking_flag_only_when_enabled() -> None:
    client = FakeClient([{"pong": True}])
    transport = ResponsesJSONTransport(
        client=client,  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=True,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
    )

    response = transport.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {
        "enable_thinking": True,
        "response_format": {"type": "json_object"},
    }


def test_author_v2_qwen_gateway_explicitly_disables_thinking() -> None:
    client = FakeClient([{"pong": True}])
    gateway = AuthorV2LLMGateway(
        client=client,  # type: ignore[arg-type]
        model="qwen3.5-flash",
        profile_id="live_qwen3_5_flash",
        timeout_seconds=45.0,
        max_output_tokens_preview=800,
        max_output_tokens_cast_slots=800,
        max_output_tokens_segment_allocation=1500,
        max_output_tokens_segment_playbook=1600,
        use_session_cache=False,
    )

    response = gateway.invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        operation_name="demo.qwen",
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {"enable_thinking": False, "response_format": {"type": "json_object"}}


def test_play_qwen_gateway_explicitly_disables_thinking_when_play_thinking_off() -> None:
    client = FakeClient([{"pong": True}])
    gateway = PlayLLMGateway(
        client=client,  # type: ignore[arg-type]
        model="qwen3.5-flash",
        timeout_seconds=20.0,
        max_output_tokens_interpret=220,
        max_output_tokens_interpret_repair=320,
        max_output_tokens_ending_judge=180,
        max_output_tokens_ending_judge_repair=120,
        max_output_tokens_pyrrhic_critic=120,
        max_output_tokens_render=420,
        max_output_tokens_render_repair=640,
        use_session_cache=False,
        enable_thinking=False,
    )

    response = gateway._invoke_json(
        system_prompt="Return one strict JSON object.",
        user_payload={"ping": True},
        max_output_tokens=32,
        operation_name="play.demo",
    )

    assert response.payload == {"pong": True}
    assert client.calls[0]["extra_body"] == {
        "enable_thinking": False,
        "response_format": {"type": "json_object"},
    }


def test_shared_transport_records_failed_provider_attempt_in_call_trace() -> None:
    class _FailingClient:
        def __init__(self) -> None:
            self.responses = self

        def create(self, **kwargs):  # noqa: ANN201, ARG002
            raise RuntimeError("connection timed out")

    trace: list[dict[str, object]] = []
    transport = ResponsesJSONTransport(
        client=_FailingClient(),  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
        call_trace=trace,
    )

    try:
        transport.invoke_json(
            system_prompt="Return JSON only.",
            user_payload={"ping": True},
            max_output_tokens=32,
            operation_name="demo.op",
        )
    except RuntimeError as exc:
        assert "provider_failed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected provider failure")

    assert len(trace) == 1
    assert trace[0]["operation"] == "demo.op"
    assert trace[0]["response_received"] is False
    assert trace[0]["failure_code"] == "provider_failed"
    assert trace[0]["failure_message_bucket"] == "timeout"
    assert trace[0]["attempt_index"] == 1


def test_shared_transport_preserves_upstream_http_status_on_provider_error() -> None:
    class _AuthFailClient:
        def __init__(self) -> None:
            self.responses = self

        def create(self, **kwargs):  # noqa: ANN201, ARG002
            raise ResponsesProviderError("无效的令牌", status_code=401)

    trace: list[dict[str, object]] = []
    transport = ResponsesJSONTransport(
        client=_AuthFailClient(),  # type: ignore[arg-type]
        model="demo-model",
        timeout_seconds=20.0,
        use_session_cache=False,
        temperature=0.2,
        enable_thinking=False,
        provider_failed_code="provider_failed",
        invalid_response_code="invalid_response",
        invalid_json_code="invalid_json",
        error_factory=lambda code, message, status_code: RuntimeError(f"{code}:{message}:{status_code}"),
        call_trace=trace,
    )

    try:
        transport.invoke_json(
            system_prompt="Return JSON only.",
            user_payload={"ping": True},
            max_output_tokens=32,
            operation_name="demo.auth",
        )
    except RuntimeError as exc:
        assert "provider_failed:无效的令牌:401" == str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected provider failure")

    assert len(trace) == 1
    assert trace[0]["failure_message_bucket"] == "auth"
    assert trace[0]["failure_status_code"] == 401


def test_failure_message_bucket_classifies_dns_messages() -> None:
    assert _failure_message_bucket("[Errno 8] nodename nor servname provided, or not known") == "dns"


def test_failure_message_bucket_classifies_pending_queue_messages_as_rate_limit() -> None:
    assert _failure_message_bucket("Too many pending requests, please retry later") == "rate_limit"


def test_raw_responses_client_parses_output_blocks(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class _FakeHTTPResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "id": "resp-demo",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "{\"pong\": true}",
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            }

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001
            recorded["client_timeout"] = timeout
            recorded["client_limits"] = limits

        def close(self) -> None:
            recorded["closed"] = True

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201
            recorded["url"] = url
            recorded["headers"] = headers
            recorded["json"] = json
            recorded["request_timeout"] = timeout
            return _FakeHTTPResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(base_url="https://example.test/v1", api_key="secret-key")

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=32,
        timeout=12,
        temperature=0.2,
    )

    assert response.id == "resp-demo"
    assert response.output_text == "{\"pong\": true}"
    assert response.usage["total_tokens"] == 15
    assert recorded["url"] == "https://example.test/v1/chat/completions"
    assert recorded["request_timeout"] == 12
    assert recorded["json"] == {
        "model": "demo-model",
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 32,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    assert recorded["headers"] == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
    }


def test_raw_responses_client_merges_response_format_into_payload(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class _FakeHTTPResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "id": "resp-demo",
                "output_text": "{\"pong\": true}",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            }

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001
            recorded["client_timeout"] = timeout
            recorded["client_limits"] = limits

        def close(self) -> None:
            recorded["closed"] = True

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201
            recorded["json"] = json
            recorded["request_timeout"] = timeout
            return _FakeHTTPResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(base_url="https://example.test/v1", api_key="secret-key")

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=32,
        timeout=12,
        temperature=0.2,
        extra_body={"response_format": {"type": "json_object"}},
    )

    assert response.output_text == "{\"pong\": true}"
    assert recorded["request_timeout"] == 12
    assert recorded["json"] == {
        "model": "demo-model",
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 32,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }


def test_raw_responses_client_uses_chat_completions_for_beecode(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class _FakeStreamResponse:
        status_code = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return None

        def iter_lines(self):  # noqa: ANN201
            yield 'data: {"id":"chatcmpl-demo","choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}'
            yield 'data: {"id":"chatcmpl-demo","choices":[{"delta":{"content":"{\\"pong\\": true}"},"finish_reason":null}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}'
            yield "data: [DONE]"

        def read(self):  # noqa: ANN201
            return b""

        @property
        def text(self) -> str:
            return ""

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001
            recorded["client_timeout"] = timeout
            recorded["client_limits"] = limits

        def close(self) -> None:
            recorded["closed"] = True

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            raise AssertionError("beecode chat/completions should use stream path")

        def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201
            recorded["method"] = method
            recorded["url"] = url
            recorded["headers"] = headers
            recorded["json"] = json
            recorded["request_timeout"] = timeout
            return _FakeStreamResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(base_url="https://beecode.cc/v1", api_key="secret-key")

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=32,
        timeout=12,
        temperature=0.2,
        previous_response_id="resp-previous",
        extra_body={"response_format": {"type": "json_object"}, "enable_thinking": False},
    )

    assert response.id == "chatcmpl-demo"
    assert response.output_text == "{\"pong\": true}"
    assert response.usage["total_tokens"] == 15
    assert recorded["method"] == "POST"
    assert recorded["url"] == "https://beecode.cc/v1/chat/completions"
    assert recorded["request_timeout"] == 12
    assert recorded["json"] == {
        "model": "demo-model",
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 32,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": True,
    }
    assert recorded["headers"] == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def test_raw_responses_client_stream_parses_message_content_blocks(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class _FakeStreamResponse:
        status_code = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return None

        def iter_lines(self):  # noqa: ANN201
            yield 'data: {"id":"chatcmpl-demo","choices":[{"message":{"role":"assistant","content":"{\\"pong\\": true}"}}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}'
            yield "data: [DONE]"

        def read(self):  # noqa: ANN201
            return b""

        @property
        def text(self) -> str:
            return ""

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001, ARG002
            return None

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            raise AssertionError("stream path should be used for beecode chat/completions")

        def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201
            recorded["method"] = method
            recorded["url"] = url
            recorded["headers"] = headers
            recorded["json"] = json
            recorded["request_timeout"] = timeout
            return _FakeStreamResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(base_url="https://beecode.cc/v1", api_key="secret-key")

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=32,
        timeout=12,
        temperature=0.2,
        extra_body={"response_format": {"type": "json_object"}},
    )

    assert response.id == "chatcmpl-demo"
    assert response.output_text == "{\"pong\": true}"
    assert response.usage["total_tokens"] == 15


def test_raw_responses_client_can_disable_stream_chat_json_for_beecode(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class _FakeHTTPResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "id": "resp-demo",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "{\"pong\": true}",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001
            recorded["client_timeout"] = timeout
            recorded["client_limits"] = limits

        def close(self) -> None:
            recorded["closed"] = True

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201
            recorded["url"] = url
            recorded["headers"] = headers
            recorded["json"] = json
            recorded["request_timeout"] = timeout
            return _FakeHTTPResponse()

        def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            raise AssertionError("stream path should be disabled when chat_json_stream_mode=off")

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(
        base_url="https://beecode.cc/v1",
        api_key="secret-key",
        chat_json_stream_mode="off",
    )

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=32,
        timeout=12,
        temperature=0.2,
        extra_body={"response_format": {"type": "json_object"}},
    )

    assert response.id == "resp-demo"
    assert response.output_text == "{\"pong\": true}"
    assert response.usage["total_tokens"] == 15
    assert recorded["url"] == "https://beecode.cc/v1/chat/completions"
    assert recorded["json"] == {
        "model": "demo-model",
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 32,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    assert recorded["headers"] == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def test_raw_responses_client_can_force_stream_chat_json_for_nonlisted_host(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    class _FakeStreamResponse:
        status_code = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return None

        def iter_lines(self):  # noqa: ANN201
            yield 'data: {"id":"chatcmpl-demo","choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}'
            yield 'data: {"id":"chatcmpl-demo","choices":[{"delta":{"content":"{\\"pong\\": true}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}'
            yield "data: [DONE]"

        def read(self):  # noqa: ANN201
            return b""

        @property
        def text(self) -> str:
            return ""

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001, ARG002
            return None

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            raise AssertionError("stream path should be forced when chat_json_stream_mode=force")

        def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201
            recorded["method"] = method
            recorded["url"] = url
            recorded["headers"] = headers
            recorded["json"] = json
            recorded["request_timeout"] = timeout
            return _FakeStreamResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(
        base_url="https://example.test/v1",
        api_key="secret-key",
        chat_json_stream_mode="force",
    )

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=32,
        timeout=12,
        temperature=0.2,
        extra_body={"response_format": {"type": "json_object"}},
    )

    assert response.id == "chatcmpl-demo"
    assert response.output_text == "{\"pong\": true}"
    assert response.usage["total_tokens"] == 15
    assert recorded["method"] == "POST"
    assert recorded["url"] == "https://example.test/v1/chat/completions"
    assert recorded["json"] == {
        "model": "demo-model",
        "messages": [
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "ping"},
        ],
        "max_tokens": 32,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": True,
    }


def test_raw_responses_client_raises_provider_message_on_http_error(monkeypatch) -> None:
    class _FakeHTTPResponse:
        status_code = 403

        def json(self):  # noqa: ANN201
            return {
                "error": {
                    "message": "Your request was blocked.",
                }
            }

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001
            self.timeout = timeout

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            return _FakeHTTPResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(base_url="https://example.test/v1", api_key="secret-key")

    try:
        client.responses.create(
            model="demo-model",
            instructions="Return JSON only.",
            input="ping",
            max_output_tokens=32,
            timeout=12,
        )
    except RuntimeError as exc:
        assert str(exc) == "Your request was blocked."
    else:
        raise AssertionError("expected RuntimeError")


def test_raw_responses_client_retries_pending_overload_once_then_succeeds(monkeypatch) -> None:
    recorded: dict[str, int] = {"stream_count": 0}
    sleep_calls: list[float] = []

    class _PendingResponse:
        status_code = 429

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return None

        def read(self):  # noqa: ANN201
            return b'{"error":{"message":"Too many pending requests, please retry later"}}'

        @property
        def text(self) -> str:
            return '{"error":{"message":"Too many pending requests, please retry later"}}'

        def iter_lines(self):  # noqa: ANN201
            return iter(())

    class _SuccessResponse:
        status_code = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return None

        def iter_lines(self):  # noqa: ANN201
            yield 'data: {"id":"resp-demo","choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}'
            yield 'data: {"id":"resp-demo","choices":[{"delta":{"content":"{\\"ok\\": true}"},"finish_reason":"stop"}],"usage":{"total_tokens":1}}'
            yield "data: [DONE]"

        def read(self):  # noqa: ANN201
            return b""

        @property
        def text(self) -> str:
            return ""

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001, ARG002
            return None

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            raise AssertionError("beecode chat/completions should use stream path")

        def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            recorded["stream_count"] += 1
            if recorded["stream_count"] == 1:
                return _PendingResponse()
            return _SuccessResponse()

    def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    monkeypatch.setattr("rpg_backend.responses_transport.time.sleep", _fake_sleep)
    client = RawResponsesClient(base_url="https://beecode.cc/v1", api_key="secret-key")

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=16,
        timeout=10,
        extra_body={"response_format": {"type": "json_object"}},
    )

    assert response.output_text == "{\"ok\": true}"
    assert recorded["stream_count"] == 2
    assert sleep_calls == [5.0]


def test_raw_responses_client_pending_overload_retry_exhausted_raises(monkeypatch) -> None:
    recorded: dict[str, int] = {"stream_count": 0}
    sleep_calls: list[float] = []

    class _PendingResponse:
        status_code = 429

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return None

        def read(self):  # noqa: ANN201
            return b'{"error":{"message":"Too many pending requests, please retry later"}}'

        @property
        def text(self) -> str:
            return '{"error":{"message":"Too many pending requests, please retry later"}}'

        def iter_lines(self):  # noqa: ANN201
            return iter(())

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001, ARG002
            return None

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            raise AssertionError("beecode chat/completions should use stream path")

        def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            recorded["stream_count"] += 1
            return _PendingResponse()

    def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    monkeypatch.setattr("rpg_backend.responses_transport.time.sleep", _fake_sleep)
    client = RawResponsesClient(base_url="https://beecode.cc/v1", api_key="secret-key")

    try:
        client.responses.create(
            model="demo-model",
            instructions="Return JSON only.",
            input="ping",
            max_output_tokens=16,
            timeout=10,
            extra_body={"response_format": {"type": "json_object"}},
        )
    except RuntimeError as exc:
        assert "Too many pending requests" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert recorded["stream_count"] == 2
    assert sleep_calls == [5.0]


def test_raw_responses_client_retries_empty_content_once_and_rotates_key(monkeypatch) -> None:
    recorded: dict[str, object] = {"post_count": 0, "auth_headers": []}
    sleep_calls: list[float] = []

    class _EmptyResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "id": "resp-empty",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                        }
                    }
                ],
                "usage": {"total_tokens": 1},
            }

    class _SuccessResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {
                "id": "resp-ok",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "{\"ok\": true}",
                        }
                    }
                ],
                "usage": {"total_tokens": 2},
            }

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001, ARG002
            return None

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            recorded["post_count"] = int(recorded["post_count"]) + 1
            cast_headers = recorded["auth_headers"]
            assert isinstance(cast_headers, list)
            cast_headers.append(headers.get("Authorization"))
            if int(recorded["post_count"]) == 1:
                return _EmptyResponse()
            return _SuccessResponse()

    def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    monkeypatch.setattr("rpg_backend.responses_transport.time.sleep", _fake_sleep)
    client = RawResponsesClient(
        base_url="https://example.test/v1",
        api_key="key-a",
        api_keys=("key-a", "key-b"),
        chat_json_stream_mode="off",
    )

    response = client.responses.create(
        model="demo-model",
        instructions="Return JSON only.",
        input="ping",
        max_output_tokens=16,
        timeout=10,
        extra_body={"response_format": {"type": "json_object"}},
    )

    assert response.id == "resp-ok"
    assert response.output_text == "{\"ok\": true}"
    assert recorded["post_count"] == 2
    assert recorded["auth_headers"] == ["Bearer key-a", "Bearer key-b"]
    assert sleep_calls == [0.5]


def test_raw_responses_client_does_not_retry_non_pending_http_error(monkeypatch) -> None:
    recorded: dict[str, int] = {"stream_count": 0}
    sleep_calls: list[float] = []

    class _UnauthorizedResponse:
        status_code = 401

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return None

        def read(self):  # noqa: ANN201
            return b'{"error":{"message":"Unauthorized"}}'

        @property
        def text(self) -> str:
            return '{"error":{"message":"Unauthorized"}}'

        def iter_lines(self):  # noqa: ANN201
            return iter(())

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001, ARG002
            return None

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            raise AssertionError("beecode chat/completions should use stream path")

        def stream(self, method: str, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            recorded["stream_count"] += 1
            return _UnauthorizedResponse()

    def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    monkeypatch.setattr("rpg_backend.responses_transport.time.sleep", _fake_sleep)
    client = RawResponsesClient(base_url="https://beecode.cc/v1", api_key="secret-key")

    try:
        client.responses.create(
            model="demo-model",
            instructions="Return JSON only.",
            input="ping",
            max_output_tokens=16,
            timeout=10,
            extra_body={"response_format": {"type": "json_object"}},
        )
    except RuntimeError as exc:
        assert "Unauthorized" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert recorded["stream_count"] == 1
    assert sleep_calls == []


def test_raw_responses_client_reuses_http_client_across_calls(monkeypatch) -> None:
    recorded: dict[str, int] = {"init_count": 0, "post_count": 0}

    class _FakeHTTPResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {"id": "resp-demo", "output_text": "{\"ok\": true}", "usage": {"total_tokens": 1}}

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001
            recorded["init_count"] += 1

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            recorded["post_count"] += 1
            return _FakeHTTPResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(base_url="https://example.test/v1", api_key="secret-key")

    client.responses.create(model="m", instructions="i", input="a", max_output_tokens=8, timeout=10)
    client.responses.create(model="m", instructions="i", input="b", max_output_tokens=8, timeout=10)

    assert recorded["init_count"] == 1
    assert recorded["post_count"] == 2


def test_raw_responses_client_rebuilds_client_after_transport_error(monkeypatch) -> None:
    recorded: dict[str, int] = {"init_count": 0, "post_count": 0}

    class _FakeHTTPResponse:
        status_code = 200

        def json(self):  # noqa: ANN201
            return {"id": "resp-demo", "output_text": "{\"ok\": true}", "usage": {"total_tokens": 1}}

    class _FakeHTTPClient:
        def __init__(self, *, timeout: float, limits=None) -> None:  # noqa: ANN001
            self.instance_id = recorded["init_count"]
            recorded["init_count"] += 1
            self._failed_once = False

        def close(self) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float):  # noqa: ANN201, ARG002
            recorded["post_count"] += 1
            if self.instance_id == 0 and not self._failed_once:
                self._failed_once = True
                request = httpx.Request("POST", url)
                raise httpx.ConnectError("boom", request=request)
            return _FakeHTTPResponse()

    monkeypatch.setattr("rpg_backend.responses_transport.httpx.Client", _FakeHTTPClient)
    client = RawResponsesClient(base_url="https://example.test/v1", api_key="secret-key")

    response = client.responses.create(model="m", instructions="i", input="a", max_output_tokens=8, timeout=10)

    assert response.id == "resp-demo"
    assert recorded["init_count"] >= 2
    assert recorded["post_count"] >= 2


def test_gateway_formats_requests_and_parses_models() -> None:
    client = FakeClient(
        [
            story_frame_scaffold_draft().model_dump(mode="json"),
            cast_overview_draft().model_dump(mode="json"),
            cast_draft().model_dump(mode="json"),
            beat_plan_skeleton_draft().model_dump(mode="json"),
        ]
    )
    gateway = _gateway(client)
    focused_brief = author_fixture_bundle().focused_brief

    story_frame = story_generation.generate_story_frame(gateway, focused_brief)
    cast_overview = cast_generation.generate_cast_overview(
        gateway,
        focused_brief,
        story_frame.value,
        previous_response_id=story_frame.response_id,
    )
    cast = cast_generation.generate_story_cast(
        gateway,
        focused_brief,
        story_frame.value,
        cast_overview.value,
        previous_response_id=cast_overview.response_id or story_frame.response_id,
    )
    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        focused_brief,
        story_frame.value,
        cast.value,
        previous_response_id=cast.response_id or story_frame.response_id,
    )

    assert story_frame.value.title == "Archive Blackout"
    assert cast.value.cast[0].name == "Envoy Iri"
    assert beat_plan.value.beats[0].title == "The First Nightfall"
    assert client.calls[0]["model"] == "demo-model"
    assert client.calls[0]["max_output_tokens"] == 900
    assert "Return one strict JSON object matching StoryFrameScaffoldDraft" in client.calls[0]["instructions"]
    assert "Return one strict JSON object matching CastOverviewDraft" in client.calls[1]["instructions"]
    assert "Return one strict JSON object matching CastDraft" in client.calls[2]["instructions"]
    assert "Return one strict JSON object matching BeatPlanSkeletonDraft" in client.calls[3]["instructions"]
    assert client.calls[1]["previous_response_id"] == "resp-1"
    assert client.calls[2]["previous_response_id"] == "resp-2"
    assert client.calls[3]["previous_response_id"] == "resp-3"
    beat_skeleton_payload = json.loads(client.calls[3]["input"])
    assert "author_context" in beat_skeleton_payload
    assert "story_frame" not in beat_skeleton_payload
    assert "cast" not in beat_skeleton_payload


def test_gateway_compiles_story_frame_from_semantics_without_second_llm_call() -> None:
    client = FakeClient([story_frame_scaffold_draft().model_dump(mode="json")])
    gateway = _gateway(client)

    story_frame = story_generation.generate_story_frame(
        gateway,
        author_fixture_bundle().focused_brief,
    )

    assert story_frame.value.title == "Archive Blackout"
    assert story_frame.response_id == "resp-1"
    assert story_frame.value.premise.startswith("In ")
    assert len(client.calls) == 1


def test_gateway_retries_story_frame_semantics_after_invalid_json() -> None:
    client = FakeClient(["not json at all", story_frame_scaffold_draft().model_dump(mode="json")])
    gateway = _gateway(client)

    story_frame = story_generation.generate_story_frame(
        gateway,
        FocusedBrief(
            story_kernel="A mediator keeping a city together",
            setting_signal="city during a blackout and succession crisis",
            core_conflict="keep a city together while a blackout and succession crisis strains civic order",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )

    assert len(client.calls) == 2
    assert story_frame.value.title == "Archive Blackout"


def test_gateway_stabilizes_generic_story_frame_scaffold_before_compile() -> None:
    fixture = author_fixture_bundle()
    client = FakeClient(
        [
            {
                "title_seed": "A Mediator Keeping A City Together",
                "setting_frame": "city during a blackout and succession crisis",
                "protagonist_mandate": "a mediator keeping a city together",
                "opposition_force": "keep a city together while a blackout and succession crisis strains civic order",
                "stakes_core": "Prevent coalition collapse.",
                "tone": "hopeful political fantasy",
                "world_rules": fixture.story_frame.world_rules,
                "truths": [item.model_dump(mode="json") for item in fixture.story_frame.truths],
                "state_axis_choices": [item.model_dump(mode="json") for item in fixture.story_frame.state_axis_choices],
                "flags": [item.model_dump(mode="json") for item in fixture.story_frame.flags],
            }
        ]
    )
    gateway = _gateway(client)

    story_frame = story_generation.generate_story_frame(
        gateway,
        FocusedBrief(
            story_kernel="A mediator keeping a city together",
            setting_signal="city during a blackout and succession crisis",
            core_conflict="keep a city together while a blackout and succession crisis strains civic order",
            tone_signal="Hopeful civic fantasy.",
            hard_constraints=[],
            forbidden_tones=[],
        ),
    )

    assert story_frame.value.title == "The Dimmed Accord"
    assert "A Mediator Keeping A City Together" not in story_frame.value.premise


def test_gateway_compiles_beat_plan_from_single_semantics_call() -> None:
    client = FakeClient([beat_plan_skeleton_draft().model_dump(mode="json")])
    gateway = _gateway(client)
    fixture = author_fixture_bundle()

    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        fixture.cast_draft,
    )

    assert beat_plan.response_id == "resp-1"
    assert len(client.calls) == 1
    assert [beat.title for beat in beat_plan.value.beats] == [
        "The First Nightfall",
        "The Public Ledger",
        "The Dawn Bargain",
    ]
    assert [beat.milestone_kind for beat in beat_plan.value.beats] == [
        "reveal",
        "containment",
        "commitment",
    ]
    assert all(beat.return_hooks for beat in beat_plan.value.beats)


def test_gateway_retries_beat_plan_skeleton_after_invalid_json() -> None:
    client = FakeClient(["not json at all", beat_plan_skeleton_draft().model_dump(mode="json")])
    gateway = _gateway(client)
    fixture = author_fixture_bundle()

    beat_plan = beat_generation.generate_beat_plan(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        fixture.cast_draft,
    )

    assert len(client.calls) == 2
    assert [beat.title for beat in beat_plan.value.beats] == [
        "The First Nightfall",
        "The Public Ledger",
        "The Dawn Bargain",
    ]


def test_gateway_compiles_cast_member_semantics_and_replaces_role_label_name() -> None:
    client = FakeClient(
        [
            {
                "name": "Leverage Broker",
                "agenda_detail": "Uses a private shipping ledger to squeeze concessions out of every public delay.",
                "red_line_detail": "Will burn the room down politically before accepting exclusion from the settlement.",
                "pressure_detail": "Starts framing every compromise as proof that the balance of power must change immediately.",
            }
        ]
    )
    gateway = _gateway(client)
    fixture = author_fixture_bundle()
    slot = fixture.cast_overview.cast_slots[2].model_dump(mode="json")

    member = cast_generation.generate_story_cast_member(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        slot,
        existing_cast=[
            fixture.cast_draft.cast[0].model_dump(mode="json"),
            fixture.cast_draft.cast[1].model_dump(mode="json"),
        ],
    )

    assert member.value.name != "Leverage Broker"
    assert member.value.role == "Coalition rival"
    assert "Exploit the blackout to reshape the balance of power." in member.value.agenda
    assert "Will not accept being shut out of the final order." in member.value.red_line
    assert "Frames every emergency as proof that someone else should lose authority." in member.value.pressure_signature


def test_gateway_retries_cast_member_semantics_after_invalid_json() -> None:
    client = FakeClient(
        [
            "not json at all",
            {
                "name": "Mara Kestrel",
                "agenda_detail": "Uses a private relief ledger to force concessions whenever the room stalls.",
                "red_line_detail": "Will take public blame over quiet exclusion from the settlement.",
                "pressure_detail": "Sharpens into open leverage the moment delay starts protecting someone else.",
            },
        ]
    )
    gateway = _gateway(client)
    fixture = author_fixture_bundle()
    slot = fixture.cast_overview.cast_slots[2].model_dump(mode="json")

    member = cast_generation.generate_story_cast_member(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        slot,
        existing_cast=[
            fixture.cast_draft.cast[0].model_dump(mode="json"),
            fixture.cast_draft.cast[1].model_dump(mode="json"),
        ],
    )

    assert len(client.calls) == 2
    assert member.value.name == "Mara Kestrel"
    assert "Exploit the blackout to reshape the balance of power." in member.value.agenda


def test_gateway_raises_stable_error_for_invalid_json() -> None:
    client = FakeClient(["not json at all", "not json at all", "not json at all"])
    gateway = _gateway(client)

    try:
        story_generation.generate_story_frame(
            gateway,
            author_fixture_bundle().focused_brief,
        )
    except AuthorGatewayError as exc:
        assert exc.code == "llm_invalid_json"
    else:  # pragma: no cover
        raise AssertionError("Expected AuthorGatewayError")


def test_rule_generation_uses_author_context_packets() -> None:
    client = FakeClient(
        [
            route_opportunity_plan_draft().model_dump(mode="json"),
            ending_anchor_suggestion_payload(),
        ]
    )
    gateway = _gateway(client)
    fixture = author_fixture_bundle()

    route_generation.generate_route_opportunity_plan_result(gateway, fixture.design_bundle, previous_response_id="resp-a")
    ending_generation.generate_ending_anchor_suggestions(gateway, fixture.design_bundle, previous_response_id="resp-b")

    route_payload = json.loads(client.calls[0]["input"])
    ending_payload = json.loads(client.calls[1]["input"])
    assert "author_context" in route_payload
    assert "story_bible" not in route_payload
    assert "state_schema" not in route_payload
    assert "beat_spine" not in route_payload
    assert "author_context" in ending_payload
    assert "story_bible" not in ending_payload


def test_gateway_retries_story_frame_glean_after_invalid_json() -> None:
    client = FakeClient(
        [
            "not json at all",
            story_frame_draft().model_dump(mode="json"),
        ]
    )
    gateway = _gateway(client)
    fixture = author_fixture_bundle()

    repaired = story_generation.glean_story_frame(
        gateway,
        fixture.focused_brief,
        fixture.story_frame,
        previous_response_id="resp-start",
    )

    assert len(client.calls) == 2
    assert repaired.value.title == fixture.story_frame.title
    assert client.calls[0]["previous_response_id"] == "resp-start"
    assert client.calls[1]["previous_response_id"] == "resp-start"


def test_gateway_retries_route_affordance_generation_after_invalid_json() -> None:
    fixture = author_fixture_bundle()
    client = FakeClient(
        [
            "not json at all",
            {
                "route_unlock_rules": [
                    {
                        "rule_id": "b1_unlock",
                        "beat_id": "b1",
                        "conditions": {"required_truths": ["truth_1"]},
                        "unlock_route_id": "b1_reveal_truth_route",
                        "unlock_affordance_tag": "reveal_truth",
                    }
                ],
                "affordance_effect_profiles": [
                    {
                        "affordance_tag": "reveal_truth",
                        "default_story_function": "reveal",
                        "axis_deltas": {"external_pressure": 1},
                        "stance_deltas": {},
                        "can_add_truth": True,
                        "can_add_event": False,
                    }
                ],
            },
        ]
    )
    gateway = _gateway(client)

    pack = route_generation.generate_route_affordance_pack_result(
        gateway,
        fixture.design_bundle,
        previous_response_id="resp-route",
    )

    assert len(client.calls) == 2
    assert pack.value.route_unlock_rules
    assert pack.value.affordance_effect_profiles
    assert client.calls[0]["previous_response_id"] == "resp-route"
    assert client.calls[1]["previous_response_id"] == "resp-route"
