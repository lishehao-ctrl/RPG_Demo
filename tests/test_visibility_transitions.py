"""Tests for the three-state visibility model: private / unlisted / public.

unlisted is the new state introduced in Phase B. The contract:
- public:   list endpoints surface it; anyone fetches detail
- unlisted: list endpoints HIDE it; anyone with the story_id can fetch detail
- private:  list endpoints hide it; only owner can fetch detail
"""

from __future__ import annotations

import rpg_backend.main as main_module
from fastapi.testclient import TestClient

from rpg_backend.library.service import StoryLibraryService
from rpg_backend.library.storage import SQLiteStoryLibraryStorage
from rpg_backend.main import app
from tests.auth_helpers import ensure_authenticated_client
from tests.test_story_library_api import _FakeAuthorJobService, _publish_source


def _swap_in_library(tmp_path):
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_library = main_module.story_library_service
    main_module.story_library_service = library_service
    return library_service, original_library


def _restore_main(original_author, original_library):
    main_module.author_job_service = original_author
    main_module.story_library_service = original_library


def _publish_with_visibility(client: TestClient, source_job_id: str, visibility: str):
    return client.post(f"/author/jobs/{source_job_id}/publish?visibility={visibility}")


def test_unlisted_world_hidden_from_listing_but_detail_readable_by_anyone(tmp_path) -> None:
    source = _publish_source("job-unlisted-1")
    _, original_library = _swap_in_library(tmp_path)
    original_author = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="UnlistedOwner")
        published = _publish_with_visibility(owner_client, source.source_job_id, "unlisted")

        public_list = anon_client.get("/stories?view=public")
        anon_detail = anon_client.get(f"/stories/{published.json()['story_id']}")
        owner_detail = owner_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        _restore_main(original_author, original_library)

    assert published.status_code == 200
    assert published.json()["visibility"] == "unlisted"
    # Listing should not contain the unlisted story.
    listed_ids = [s["story_id"] for s in public_list.json()["stories"]]
    assert published.json()["story_id"] not in listed_ids
    # Anyone with the story_id can read detail.
    assert anon_detail.status_code == 200
    assert anon_detail.json()["story"]["visibility"] == "unlisted"
    # Owner can manage.
    assert owner_detail.json()["presentation"]["viewer_can_manage"] is True


def test_private_world_invisible_to_non_owner(tmp_path) -> None:
    source = _publish_source("job-private-vis")
    _, original_library = _swap_in_library(tmp_path)
    original_author = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="PrivateOwner")
        published = _publish_with_visibility(owner_client, source.source_job_id, "private")

        public_list = anon_client.get("/stories?view=public")
        anon_detail = anon_client.get(f"/stories/{published.json()['story_id']}")
        owner_detail = owner_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        _restore_main(original_author, original_library)

    assert published.status_code == 200
    listed_ids = [s["story_id"] for s in public_list.json()["stories"]]
    assert published.json()["story_id"] not in listed_ids
    assert anon_detail.status_code == 404
    assert owner_detail.status_code == 200


def test_public_world_appears_in_listings_and_detail(tmp_path) -> None:
    source = _publish_source("job-public-vis")
    _, original_library = _swap_in_library(tmp_path)
    original_author = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="PublicOwner")
        published = _publish_with_visibility(owner_client, source.source_job_id, "public")
        public_list = anon_client.get("/stories?view=public")
        anon_detail = anon_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        _restore_main(original_author, original_library)

    assert published.status_code == 200
    listed_ids = [s["story_id"] for s in public_list.json()["stories"]]
    assert published.json()["story_id"] in listed_ids
    assert anon_detail.status_code == 200


def test_visibility_can_be_promoted_private_to_unlisted_to_public(tmp_path) -> None:
    source = _publish_source("job-vis-promote")
    _, original_library = _swap_in_library(tmp_path)
    original_author = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="Promoter")
        published = _publish_with_visibility(owner_client, source.source_job_id, "private")
        story_id = published.json()["story_id"]

        # private → unlisted
        owner_client.patch(f"/stories/{story_id}/visibility", json={"visibility": "unlisted"})
        anon_after_unlisted = anon_client.get(f"/stories/{story_id}")

        # unlisted → public
        owner_client.patch(f"/stories/{story_id}/visibility", json={"visibility": "public"})
        anon_after_public = anon_client.get(f"/stories/{story_id}")
        public_list_after = anon_client.get("/stories?view=public")
    finally:
        _restore_main(original_author, original_library)

    assert anon_after_unlisted.status_code == 200
    assert anon_after_unlisted.json()["story"]["visibility"] == "unlisted"
    assert anon_after_public.status_code == 200
    assert anon_after_public.json()["story"]["visibility"] == "public"
    assert story_id in [s["story_id"] for s in public_list_after.json()["stories"]]


def test_visibility_demotion_public_to_private_hides_from_others(tmp_path) -> None:
    source = _publish_source("job-vis-demote")
    _, original_library = _swap_in_library(tmp_path)
    original_author = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="Demoter")
        published = _publish_with_visibility(owner_client, source.source_job_id, "public")
        story_id = published.json()["story_id"]

        owner_client.patch(f"/stories/{story_id}/visibility", json={"visibility": "private"})
        anon_after_demote = anon_client.get(f"/stories/{story_id}")
    finally:
        _restore_main(original_author, original_library)

    assert anon_after_demote.status_code == 404


def test_invalid_visibility_value_rejected(tmp_path) -> None:
    source = _publish_source("job-vis-invalid")
    _, original_library = _swap_in_library(tmp_path)
    original_author = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    owner_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, display_name="VisCheck")
        published = _publish_with_visibility(owner_client, source.source_job_id, "private")
        bad = owner_client.patch(
            f"/stories/{published.json()['story_id']}/visibility",
            json={"visibility": "secret"},
        )
    finally:
        _restore_main(original_author, original_library)

    assert bad.status_code == 422
