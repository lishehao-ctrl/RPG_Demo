import httpx

from rpg_cli import (
    DEFAULT_BACKEND_URL,
    STEP_IDEMPOTENCY_HEADER,
    backend_url,
    build_step_headers,
    is_request_in_progress_response,
)


def test_backend_url_default(monkeypatch) -> None:
    monkeypatch.delenv("BACKEND_URL", raising=False)
    assert backend_url() == DEFAULT_BACKEND_URL


def test_backend_url_env(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_URL", "http://localhost:9999/")
    assert backend_url() == "http://localhost:9999"


def test_build_step_headers_generates_key() -> None:
    key, headers = build_step_headers()
    assert isinstance(key, str) and key
    assert headers == {STEP_IDEMPOTENCY_HEADER: key}


def test_build_step_headers_uses_given_key() -> None:
    key, headers = build_step_headers("abc-123")
    assert key == "abc-123"
    assert headers == {STEP_IDEMPOTENCY_HEADER: "abc-123"}


def test_is_request_in_progress_response_true() -> None:
    request = httpx.Request("POST", "http://test/sessions/x/step")
    response = httpx.Response(409, request=request, json={"detail": {"code": "REQUEST_IN_PROGRESS"}})
    assert is_request_in_progress_response(response) is True


def test_is_request_in_progress_response_false() -> None:
    request = httpx.Request("POST", "http://test/sessions/x/step")
    response = httpx.Response(409, request=request, json={"detail": {"code": "OTHER"}})
    assert is_request_in_progress_response(response) is False
