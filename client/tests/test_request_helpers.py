import os

from rpg_cli import DEFAULT_BACKEND_URL, DEFAULT_USER_ID, backend_url, user_id


def test_backend_url_default(monkeypatch) -> None:
    monkeypatch.delenv("BACKEND_URL", raising=False)
    assert backend_url() == DEFAULT_BACKEND_URL


def test_backend_url_env(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_URL", "http://localhost:9999/")
    assert backend_url() == "http://localhost:9999"


def test_user_id_default(monkeypatch) -> None:
    monkeypatch.delenv("X_USER_ID", raising=False)
    assert user_id() == DEFAULT_USER_ID


def test_user_id_env(monkeypatch) -> None:
    monkeypatch.setenv("X_USER_ID", "11111111-1111-1111-1111-111111111111")
    assert user_id() == "11111111-1111-1111-1111-111111111111"


def test_auth_token_env(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_TOKEN", "abc")
    assert os.getenv("AUTH_TOKEN") == "abc"
