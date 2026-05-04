from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

import rpg_backend.main as main_module
from rpg_backend.library.service import StoryLibraryService
from rpg_backend.library.storage import SQLiteStoryLibraryStorage
from rpg_backend.main import app
from tests.auth_helpers import ensure_authenticated_client
from tests.test_story_library_api import _FakeAuthorJobService, _publish_source


def test_auth_login_logout_relogin_cycle() -> None:
    """Username-only login: same username across restart returns the same user_id."""
    client = TestClient(app)
    username = f"cycle_{uuid4().hex[:8]}"

    first_login = client.post("/auth/login", json={"username": username})
    after_login = client.get("/auth/session")
    logout = client.post("/auth/logout")
    after_logout = client.get("/auth/session")
    second_login = client.post("/auth/login", json={"username": username})
    after_relogin = client.get("/auth/session")

    assert first_login.status_code == 200
    assert after_login.status_code == 200
    assert after_login.json()["authenticated"] is True
    assert after_login.json()["user"]["display_name"] == username

    assert logout.status_code == 204

    # Anonymous fallback: /auth/session always returns authenticated=True with the
    # default actor when no cookie is present. The user_id should differ from the
    # logged-in one.
    assert after_logout.json()["authenticated"] is True
    assert after_logout.json()["user"]["user_id"] != after_login.json()["user"]["user_id"]

    # Re-login with the same username → same user_id (upsert).
    assert second_login.status_code == 200
    assert after_relogin.json()["user"]["user_id"] == after_login.json()["user"]["user_id"]


def test_auth_login_rejects_bad_username() -> None:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": "ab cd"})
    assert response.status_code == 422


def test_logged_out_can_read_public_stories(tmp_path) -> None:
    """Anonymous-by-default: non-authenticated callers can list & view public stories."""
    source = _publish_source("job-auth-public")
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="Public Owner")
        published = owner_client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=public")
        public_list = anon_client.get("/stories")
        public_detail = anon_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert published.status_code == 200
    assert public_list.status_code == 200
    assert [story["story_id"] for story in public_list.json()["stories"]] == [published.json()["story_id"]]
    assert public_detail.status_code == 200


def test_logged_out_cannot_read_private_story_detail(tmp_path) -> None:
    source = _publish_source("job-auth-private")
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="Private Owner")
        published = owner_client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=private")
        hidden = anon_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert published.status_code == 200
    # Private story owned by a real signed-in user is invisible to the anonymous fallback.
    assert hidden.status_code == 404
