"""Coverage for the Phase D endpoints added for the social-sharing flow."""

from __future__ import annotations

from datetime import datetime, timezone

import rpg_backend.main as main_module
from fastapi.testclient import TestClient

from rpg_backend.library.service import StoryLibraryService
from rpg_backend.library.storage import SQLiteStoryLibraryStorage
from rpg_backend.main import app
from tests.auth_helpers import ensure_authenticated_client
from tests.test_story_library_api import _FakeAuthorJobService, _publish_source


def _swap_library(tmp_path):
    library = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author = main_module.author_job_service
    original_library = main_module.story_library_service
    main_module.story_library_service = library
    return library, original_author, original_library


def _restore(original_author, original_library):
    main_module.author_job_service = original_author
    main_module.story_library_service = original_library


# -------------------- /me/worlds --------------------

def test_me_worlds_requires_signed_in_user(tmp_path) -> None:
    _, original_author, original_library = _swap_library(tmp_path)
    main_module.author_job_service = _FakeAuthorJobService(_publish_source("job-me-anon"))
    try:
        anon = TestClient(app)
        response = anon.get("/me/worlds")
    finally:
        _restore(original_author, original_library)
    # No cookie at all → falls through to anonymous fallback for `get_required_request_user`
    # but `/me/worlds` uses the strict session dep, so it must 401.
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_session_required"


def test_me_worlds_returns_only_callers_own_stories(tmp_path) -> None:
    alice_source = _publish_source("job-me-alice")
    bob_source = _publish_source("job-me-bob", title="Bob's World")
    _, original_author, original_library = _swap_library(tmp_path)
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    try:
        ensure_authenticated_client(alice_client, display_name="Alice")
        ensure_authenticated_client(bob_client, display_name="Bob")
        main_module.author_job_service = _FakeAuthorJobService(alice_source)
        alice_pub = alice_client.post(f"/author/jobs/{alice_source.source_job_id}/publish?visibility=private")
        main_module.author_job_service = _FakeAuthorJobService(bob_source)
        bob_pub = bob_client.post(f"/author/jobs/{bob_source.source_job_id}/publish?visibility=public")

        alice_worlds = alice_client.get("/me/worlds")
        bob_worlds = bob_client.get("/me/worlds")
    finally:
        _restore(original_author, original_library)

    assert alice_pub.status_code == 200
    assert bob_pub.status_code == 200

    alice_ids = {s["story_id"] for s in alice_worlds.json()["stories"]}
    bob_ids = {s["story_id"] for s in bob_worlds.json()["stories"]}
    assert alice_pub.json()["story_id"] in alice_ids
    assert bob_pub.json()["story_id"] in bob_ids
    # Cross-contamination check: each user only sees their own work.
    assert bob_pub.json()["story_id"] not in alice_ids
    assert alice_pub.json()["story_id"] not in bob_ids


def test_me_worlds_includes_private_unlisted_and_public(tmp_path) -> None:
    sources = {
        "private": _publish_source("job-me-priv", title="Mine Private"),
        "unlisted": _publish_source("job-me-unlisted", title="Mine Unlisted"),
        "public": _publish_source("job-me-pub", title="Mine Public"),
    }
    _, original_author, original_library = _swap_library(tmp_path)
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, display_name="OwnerAll")
        published_ids = []
        for visibility, source in sources.items():
            main_module.author_job_service = _FakeAuthorJobService(source)
            response = client.post(f"/author/jobs/{source.source_job_id}/publish?visibility={visibility}")
            published_ids.append(response.json()["story_id"])
        worlds = client.get("/me/worlds")
    finally:
        _restore(original_author, original_library)

    visible_ids = {s["story_id"] for s in worlds.json()["stories"]}
    for sid in published_ids:
        assert sid in visible_ids


# -------------------- /stories?sort=play_count_desc --------------------

def test_play_count_desc_sort_orders_by_popularity(tmp_path) -> None:
    storage = SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3"))
    library = StoryLibraryService(storage)
    original_author = main_module.author_job_service
    original_library = main_module.story_library_service
    main_module.story_library_service = library
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, display_name="HotSorter")

        story_ids = []
        for i in range(3):
            source = _publish_source(f"job-hot-{i}", title=f"Story {i}")
            main_module.author_job_service = _FakeAuthorJobService(source)
            response = client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=public")
            story_ids.append(response.json()["story_id"])

        # Story 1 = 5 plays, Story 2 = 10 plays, Story 0 = 1 play
        plays = {story_ids[0]: 1, story_ids[1]: 5, story_ids[2]: 10}
        for sid, count in plays.items():
            for _ in range(count):
                storage.record_play_completion(
                    story_id=sid,
                    player_user_id=None,
                    ending_id="ending_a",
                    completed_at=datetime.now(timezone.utc),
                )

        hot = client.get("/stories?view=public&sort=play_count_desc")
    finally:
        _restore(original_author, original_library)

    assert hot.status_code == 200
    ordered_ids = [s["story_id"] for s in hot.json()["stories"]]
    assert ordered_ids[0] == story_ids[2]  # 10 plays first
    assert ordered_ids[1] == story_ids[1]  # 5 plays
    assert ordered_ids[2] == story_ids[0]  # 1 play


# -------------------- /play/:id/replay --------------------

def test_replay_endpoint_404_for_unknown_session() -> None:
    client = TestClient(app)
    response = client.get("/play/sessions/does-not-exist/replay")
    assert response.status_code == 404


def test_replay_endpoint_returns_in_progress_session(tmp_path) -> None:
    """A fresh session has no ending yet; replay should report completed=false."""
    source = _publish_source("job-replay-inprog")
    library = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author = main_module.author_job_service
    original_library = main_module.story_library_service
    original_play = main_module.play_session_service
    # Rebind play service to the same library so cross-store tests don't pollute.
    from rpg_backend.play.service import PlaySessionService
    from rpg_backend.config import get_settings
    main_module.story_library_service = library
    main_module.play_session_service = PlaySessionService(
        story_library_service=library, settings=get_settings()
    )
    main_module.author_job_service = _FakeAuthorJobService(source)
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, display_name="ReplayAuthor")
        published = client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=public")
        session = client.post("/play/sessions", json={"story_id": published.json()["story_id"]})
        replay = client.get(f"/play/sessions/{session.json()['session_id']}/replay")
    finally:
        main_module.author_job_service = original_author
        main_module.story_library_service = original_library
        main_module.play_session_service = original_play

    assert session.status_code == 200, session.text
    assert replay.status_code == 200
    body = replay.json()
    assert body["session_id"] == session.json()["session_id"]
    assert body["story_id"] == published.json()["story_id"]
    assert body["completed"] is False
    assert body["ending"] is None
    # Title should match the world's title — not fall back to the story_id.
    assert body["story_title"] and body["story_title"] != body["story_id"]
    # Opening narration is the GM's first turn; transcript should already include it.
    assert len(body["entries"]) >= 1


def test_replay_endpoint_does_not_require_auth(tmp_path) -> None:
    """Replay URLs are public-by-link: anonymous viewers can fetch them."""
    source = _publish_source("job-replay-public")
    library = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author = main_module.author_job_service
    original_library = main_module.story_library_service
    original_play = main_module.play_session_service
    from rpg_backend.play.service import PlaySessionService
    from rpg_backend.config import get_settings
    main_module.story_library_service = library
    main_module.play_session_service = PlaySessionService(
        story_library_service=library, settings=get_settings()
    )
    main_module.author_job_service = _FakeAuthorJobService(source)
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="ReplayOwner")
        published = owner_client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=public")
        session = owner_client.post("/play/sessions", json={"story_id": published.json()["story_id"]})
        anon_replay = anon_client.get(f"/play/sessions/{session.json()['session_id']}/replay")
    finally:
        main_module.author_job_service = original_author
        main_module.story_library_service = original_library
        main_module.play_session_service = original_play

    assert anon_replay.status_code == 200


# -------------------- username case-insensitive --------------------

def test_username_case_insensitive_resolves_same_account() -> None:
    client = TestClient(app)
    upper = client.post("/auth/login", json={"username": "ShehaoTest"})
    same_id = upper.json()["user"]["user_id"]
    client.post("/auth/logout")
    lower = client.post("/auth/login", json={"username": "shehaotest"})
    mixed = client.post("/auth/login", json={"username": "SHEHAOTEST"})

    assert upper.status_code == 200
    assert lower.status_code == 200
    assert mixed.status_code == 200
    assert lower.json()["user"]["user_id"] == same_id
    assert mixed.json()["user"]["user_id"] == same_id
