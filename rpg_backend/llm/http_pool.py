from __future__ import annotations

import atexit
import threading
from typing import Any

import httpx

_pool_lock = threading.Lock()
_clients: dict[tuple[Any, ...], httpx.Client] = {}


def _pool_key(
    *,
    timeout_seconds: float,
    connect_timeout_seconds: float,
    max_connections: int,
    max_keepalive_connections: int,
    http2_enabled: bool,
) -> tuple[Any, ...]:
    return (
        round(float(timeout_seconds), 4),
        round(float(connect_timeout_seconds), 4),
        int(max_connections),
        int(max_keepalive_connections),
        bool(http2_enabled),
    )


def get_shared_sync_client(
    *,
    timeout_seconds: float,
    connect_timeout_seconds: float,
    max_connections: int,
    max_keepalive_connections: int,
    http2_enabled: bool,
) -> httpx.Client:
    key = _pool_key(
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
        http2_enabled=http2_enabled,
    )
    with _pool_lock:
        existing = _clients.get(key)
        if existing is not None:
            return existing

        limits = httpx.Limits(
            max_connections=int(max_connections),
            max_keepalive_connections=int(max_keepalive_connections),
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(
            connect=float(connect_timeout_seconds),
            read=float(timeout_seconds),
            write=float(timeout_seconds),
            pool=float(timeout_seconds),
        )
        client = httpx.Client(timeout=timeout, limits=limits, http2=bool(http2_enabled))
        _clients[key] = client
        return client


def reset_http_pool() -> None:
    with _pool_lock:
        for client in _clients.values():
            client.close()
        _clients.clear()


atexit.register(reset_http_pool)
