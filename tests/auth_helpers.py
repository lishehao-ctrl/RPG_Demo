from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient


def ensure_authenticated_client(
    client: TestClient,
    *,
    email: str | None = None,
    display_name: str,
    username: str | None = None,
    password: str | None = None,  # noqa: ARG001 — kept for legacy call sites
):
    """Log a TestClient into a unique anonymous-style account.

    The new auth model is username-only. We derive a unique username from
    `display_name` (sanitized) plus a random suffix so each test run gets a
    fresh account regardless of how many tests share the same display name.
    `email` / `password` are accepted but ignored — they're vestigial from the
    earlier scrypt-based scheme and removing them everywhere is a separate cleanup.
    """
    if username is None:
        base = re.sub(r"[^A-Za-z0-9_]", "_", display_name) or "user"
        username = f"{base[:8]}_{uuid4().hex[:8]}"
    response = client.post("/auth/login", json={"username": username})
    assert response.status_code == 200, response.text
    # Backend normalizes usernames to lowercase; stash the canonical form so
    # call sites comparing against the response don't have to remember.
    setattr(client, "test_username", username.lower())
    return response
