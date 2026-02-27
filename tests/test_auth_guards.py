from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _pack() -> dict:
    with open("examples/storypacks/campus_week_v1.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _publish_story(client: TestClient) -> None:
    pack = _pack()
    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = int(created.json()["version"])
    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 200


def test_author_token_guard_and_owner_mismatch() -> None:
    settings.author_api_token = "author-secret"
    client = TestClient(app)
    pack = _pack()

    missing = client.post("/api/v1/stories/validate", json={"pack": pack})
    assert missing.status_code == 401

    ok = client.post(
        "/api/v1/stories/validate",
        json={"pack": pack},
        headers={"X-Author-Token": "author-secret"},
    )
    assert ok.status_code == 200

    owner_mismatch = client.post(
        "/api/v1/stories",
        json={
            "story_id": pack["story_id"],
            "title": pack["title"],
            "pack": pack,
            "owner_user_id": "not-token-owner",
        },
        headers={"X-Author-Token": "author-secret"},
    )
    assert owner_mismatch.status_code == 403
    assert owner_mismatch.json()["detail"]["code"] == "FORBIDDEN"


def test_player_token_guard_and_runtime_access() -> None:
    settings.player_api_token = "player-secret"
    client = TestClient(app)
    _publish_story(client)

    missing = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"})
    assert missing.status_code == 401

    mismatch = client.post(
        "/api/v1/sessions",
        json={"story_id": "campus_week_v1", "user_id": "other-user"},
        headers={"X-Player-Token": "player-secret"},
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["detail"]["code"] == "FORBIDDEN"

    created = client.post(
        "/api/v1/sessions",
        json={"story_id": "campus_week_v1"},
        headers={"X-Player-Token": "player-secret"},
    )
    assert created.status_code == 201
    sid = created.json()["session_id"]

    step_missing_token = client.post(
        f"/api/v1/sessions/{sid}/step",
        json={"choice_id": "c_study"},
        headers={"X-Idempotency-Key": "guard-1"},
    )
    assert step_missing_token.status_code == 401

    step_ok = client.post(
        f"/api/v1/sessions/{sid}/step",
        json={"choice_id": "c_study"},
        headers={
            "X-Idempotency-Key": "guard-2",
            "X-Player-Token": "player-secret",
        },
    )
    assert step_ok.status_code == 200
