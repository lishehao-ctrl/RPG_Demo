from __future__ import annotations

import pytest
from starlette.requests import Request

import rpg_backend.main as main_module
from rpg_backend.config import get_settings
from rpg_backend.quotas import DailyQuotaLimiter, QuotaExceededError


def test_daily_quota_limiter_rejects_after_daily_limit() -> None:
    limiter = DailyQuotaLimiter()

    limiter.check_and_increment(
        ip_key="203.0.113.7",
        user_key="usr_demo",
        ip_limit=1,
        user_limit=10,
    )

    with pytest.raises(QuotaExceededError) as excinfo:
        limiter.check_and_increment(
            ip_key="203.0.113.7",
            user_key="usr_demo",
            ip_limit=1,
            user_limit=10,
        )

    assert excinfo.value.scope == "ip"
    assert excinfo.value.limit == 1


def test_daily_quota_limiter_reserves_multiple_operations() -> None:
    limiter = DailyQuotaLimiter()

    limiter.check_and_increment(
        ip_key="203.0.113.7",
        user_key="usr_demo",
        ip_limit=4,
        user_limit=4,
        amount=3,
    )

    with pytest.raises(QuotaExceededError) as excinfo:
        limiter.check_and_increment(
            ip_key="203.0.113.7",
            user_key="usr_demo",
            ip_limit=4,
            user_limit=4,
            amount=2,
        )

    assert excinfo.value.scope == "ip"


def test_daily_quota_limiter_skips_user_limit_without_real_user_key() -> None:
    limiter = DailyQuotaLimiter()

    limiter.check_and_increment(
        ip_key="203.0.113.7",
        user_key=None,
        ip_limit=10,
        user_limit=1,
    )
    limiter.check_and_increment(
        ip_key="203.0.113.8",
        user_key=None,
        ip_limit=10,
        user_limit=1,
    )


def test_daily_quota_limiter_keeps_real_user_limit_across_ips() -> None:
    limiter = DailyQuotaLimiter()

    limiter.check_and_increment(
        ip_key="203.0.113.7",
        user_key="usr_demo",
        ip_limit=10,
        user_limit=1,
    )

    with pytest.raises(QuotaExceededError) as excinfo:
        limiter.check_and_increment(
            ip_key="203.0.113.8",
            user_key="usr_demo",
            ip_limit=10,
            user_limit=1,
        )

    assert excinfo.value.scope == "user"
    assert excinfo.value.limit == 1


def test_default_actor_is_not_used_as_shared_user_quota_key(monkeypatch) -> None:
    monkeypatch.setenv("APP_DEFAULT_ACTOR_ID", "public-anon")
    get_settings.cache_clear()
    try:
        assert main_module._llm_user_quota_key("public-anon") is None
        assert main_module._llm_user_quota_key("usr_real") == "usr_real"
    finally:
        get_settings.cache_clear()


def _request_with_headers(headers: list[tuple[bytes, bytes]], client_host: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (client_host, 43210),
        }
    )


def test_client_ip_key_prefers_nginx_real_ip_over_spoofed_forwarded_for() -> None:
    request = _request_with_headers(
        [
            (b"x-forwarded-for", b"198.51.100.250, 203.0.113.8"),
            (b"x-real-ip", b"203.0.113.8"),
        ]
    )

    assert main_module._client_ip_key(request) == "203.0.113.8"


def test_client_ip_key_uses_trusted_proxy_side_of_forwarded_chain() -> None:
    request = _request_with_headers(
        [(b"x-forwarded-for", b"198.51.100.250, 203.0.113.9")]
    )

    assert main_module._client_ip_key(request) == "203.0.113.9"
