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


def test_logged_out_cannot_create_narrative_template() -> None:
    client = TestClient(app)
    response = client.post(
        "/narrative/templates",
        json={"seed": "A reviewer finds a hidden palace audit log."},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_session_required"


def test_authoring_disabled_blocks_signed_in_narrative_template_create(monkeypatch) -> None:
    monkeypatch.setenv("APP_PUBLIC_DEMO_AUTHORING_ENABLED", "false")
    main_module.get_settings.cache_clear()
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, display_name="AuthoringOff")
        response = client.post(
            "/narrative/templates",
            json={"seed": "A reviewer finds a hidden palace audit log."},
        )
    finally:
        main_module.get_settings.cache_clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Not found"


def test_quota_error_uses_frontend_error_envelope(monkeypatch) -> None:
    monkeypatch.setenv("APP_PUBLIC_DEMO_DAILY_IP_LLM_LIMIT", "2")
    monkeypatch.setenv("APP_PUBLIC_DEMO_DAILY_USER_LLM_LIMIT", "2")
    main_module.get_settings.cache_clear()
    original_limiter = main_module.llm_quota_limiter
    main_module.llm_quota_limiter = main_module.DailyQuotaLimiter()
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, display_name="QuotaEnvelope")
        response = client.post(
            "/narrative/templates",
            json={"seed": "A reviewer finds a hidden palace audit log."},
        )
    finally:
        main_module.llm_quota_limiter = original_limiter
        main_module.get_settings.cache_clear()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "ip_llm_quota_exceeded"


def test_invalid_turn_validation_runs_before_quota_debit(monkeypatch) -> None:
    class RejectingNarrativeService:
        estimated = False
        advanced = False

        def validate_advance_request(self, *_args, **_kwargs) -> None:
            raise main_module.NarrativeServiceError(
                code="option_out_of_range",
                message="chosen_option_index 99 is out of range.",
                status_code=422,
            )

        def estimate_advance_llm_operation_cost(self, *_args, **_kwargs) -> int:
            self.estimated = True
            return 1

        def advance(self, *_args, **_kwargs):  # noqa: ANN202
            self.advanced = True
            raise AssertionError("advance should not run for invalid input")

    monkeypatch.setenv("APP_PUBLIC_DEMO_DAILY_IP_LLM_LIMIT", "1")
    monkeypatch.setenv("APP_PUBLIC_DEMO_DAILY_USER_LLM_LIMIT", "1")
    main_module.get_settings.cache_clear()
    original_service = main_module.narrative_service
    original_limiter = main_module.llm_quota_limiter
    fake_service = RejectingNarrativeService()
    test_limiter = main_module.DailyQuotaLimiter()
    main_module.narrative_service = fake_service
    main_module.llm_quota_limiter = test_limiter
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, display_name="InvalidBeforeQuota")
        response = client.post(
            "/narrative/sessions/sess_invalid/story/turns",
            json={"chosen_option_index": 99},
        )
    finally:
        main_module.narrative_service = original_service
        main_module.llm_quota_limiter = original_limiter
        main_module.get_settings.cache_clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "option_out_of_range"
    assert fake_service.estimated is False
    assert fake_service.advanced is False
    assert test_limiter._counts == {}


def test_logged_out_cannot_mutate_story_visibility(tmp_path) -> None:
    source = _publish_source("job-auth-mutate")
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="Mutation Owner")
        published = owner_client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=public")
        response = anon_client.patch(
            f"/stories/{published.json()['story_id']}/visibility",
            json={"visibility": "private"},
        )
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert published.status_code == 200
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_session_required"


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
