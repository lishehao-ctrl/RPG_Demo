from __future__ import annotations

from tests.helpers.route_paths import (
    HEALTH_PATH,
    LEGACY_V2_ADMIN_PREFIX,
    LEGACY_V2_SESSIONS_PREFIX,
    LEGACY_V2_STORIES_PREFIX,
)


def _assert_not_found_envelope(response) -> None:
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["retryable"] is False


def test_v2_business_routes_are_removed(client) -> None:
    responses = [
        client.get(f"{LEGACY_V2_STORIES_PREFIX}/demo-story"),
        client.post(f"{LEGACY_V2_STORIES_PREFIX}/generate", json={"seed_text": "legacy route"}),
        client.get(f"{LEGACY_V2_SESSIONS_PREFIX}/demo-session"),
        client.post(
            f"{LEGACY_V2_SESSIONS_PREFIX}/demo-session/step",
            json={"client_action_id": "legacy-step", "input": {"type": "move", "move_id": "m1"}},
        ),
        client.get(f"{LEGACY_V2_ADMIN_PREFIX}/sessions/demo-session/timeline"),
        client.get(f"{LEGACY_V2_ADMIN_PREFIX}/observability/runtime-errors"),
    ]
    for response in responses:
        _assert_not_found_envelope(response)


def test_probe_routes_stay_unversioned(client) -> None:
    health = client.get(HEALTH_PATH)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    _assert_not_found_envelope(client.get("/v2/health"))
