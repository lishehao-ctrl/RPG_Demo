from __future__ import annotations

from rpg_backend.api.route_paths import (
    HEALTH_PATH,
    READY_PATH,
    admin_auth_login_path,
    admin_http_health_path,
    admin_user_path,
    admin_users_path,
    session_path,
    sessions_path,
    story_path,
)
from rpg_backend.config.settings import get_settings


def _assert_unauthorized(response) -> None:
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["retryable"] is False


def test_login_success_returns_access_token_and_user(anon_client) -> None:
    settings = get_settings()
    response = anon_client.post(
        admin_auth_login_path(),
        json={
            "email": settings.admin_bootstrap_email,
            "password": settings.admin_bootstrap_password,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == settings.admin_bootstrap_email.strip().lower()
    assert "password_hash" not in body["user"]


def test_login_invalid_password_returns_invalid_credentials(anon_client) -> None:
    settings = get_settings()
    response = anon_client.post(
        admin_auth_login_path(),
        json={"email": settings.admin_bootstrap_email, "password": "wrong-pass"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_all_business_routes_require_auth(anon_client) -> None:
    _assert_unauthorized(anon_client.get(story_path("missing-story")))
    _assert_unauthorized(anon_client.post(sessions_path(), json={"story_id": "x", "version": 1}))
    _assert_unauthorized(anon_client.get(session_path("missing-session")))
    _assert_unauthorized(anon_client.get(admin_http_health_path()))


def test_probes_remain_anonymous(anon_client) -> None:
    health = anon_client.get(HEALTH_PATH)
    assert health.status_code == 200

    ready = anon_client.get(READY_PATH)
    assert ready.status_code in {200, 503}


def test_admin_users_endpoints_return_safe_payload(client) -> None:
    listed = client.get(admin_users_path())
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert items
    first = items[0]
    assert {"id", "email", "role", "is_active", "created_at", "updated_at", "last_login_at"}.issubset(first)
    assert "password_hash" not in first


def test_admin_user_not_found_returns_404_envelope(client) -> None:
    response = client.get(admin_user_path("missing-user"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
