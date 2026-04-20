from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from rpg_backend.author.display import theme_label, topology_label
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.product_adapters import author_preview_from_blueprint, author_story_summary_from_package, package_from_pipeline
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.author.jobs import AuthorJobPublishSource
from rpg_backend.library.service import StoryLibraryService
from rpg_backend.library.storage import SQLiteStoryLibraryStorage
from rpg_backend.main import app
from tests.auth_helpers import ensure_authenticated_client


def _publish_source(
    job_id: str = "job-123",
    *,
    prompt_seed: str = "An envoy tries to hold an archive city together.",
    title: str | None = None,
    premise: str | None = None,
    tone: str | None = None,
    primary_theme: str = "legitimacy_crisis",
    modifiers: list[str] | None = None,
) -> AuthorJobPublishSource:
    base = _publish_v2_source()
    resolved_title = title or base.summary.title
    resolved_premise = premise or base.summary.premise
    resolved_tone = tone or base.summary.tone
    summary = base.summary.model_copy(
        update={
            "title": resolved_title,
            "premise": resolved_premise,
            "tone": resolved_tone,
            "theme": theme_label(primary_theme),
        }
    )
    preview = base.preview.model_copy(
        update={
            "prompt_seed": prompt_seed,
            "story": base.preview.story.model_copy(
                update={
                    "title": resolved_title,
                    "premise": resolved_premise,
                    "tone": resolved_tone,
                }
            ),
            "theme": base.preview.theme.model_copy(
                update={
                    "primary_theme": primary_theme,
                    "modifiers": modifiers or ["succession", "blackout"],
                }
            ),
        }
    )
    return AuthorJobPublishSource(
        source_job_id=job_id,
        owner_user_id="local-dev",
        prompt_seed=prompt_seed,
        preview=preview,
        summary=summary,
        bundle=base.bundle,
    )


class _FakeAuthorJobService:
    def __init__(self, source: AuthorJobPublishSource) -> None:
        self._source = source

    def get_publishable_job_source(self, job_id: str, *, actor_user_id=None) -> AuthorJobPublishSource:
        del actor_user_id
        assert job_id == self._source.source_job_id
        return self._source


def _publish_v2_source(
    seed: str = "董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。想要一个12到15分钟的职场修罗场。",
) -> AuthorJobPublishSource:
    preview_blueprint, _ = run_preview_blueprint_graph(seed, live_mode="deterministic")
    accepted = apply_blueprint_edits(preview_blueprint)
    pipeline = run_author_play_graph(accepted, live_mode="deterministic")
    package = package_from_pipeline(preview_blueprint=preview_blueprint, accepted_blueprint=accepted, pipeline=pipeline)
    return AuthorJobPublishSource(
        source_job_id="job-v2-123",
        owner_user_id="local-dev",
        prompt_seed=seed,
        preview=author_preview_from_blueprint(
            preview_blueprint,
            bound_cast=package.urban_bundle.bound_cast,
            arc_template_id=package.urban_bundle.arc_template_id,
        ),
        summary=author_story_summary_from_package(package),
        bundle=package,
    )


def test_publish_route_is_idempotent_and_story_routes_read_persisted_story(tmp_path) -> None:
    import rpg_backend.main as main_module

    source = _publish_source()
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, email="library-idempotent@example.com", display_name="Library Owner")
        publish_first = client.post(f"/author/jobs/{source.source_job_id}/publish")
        publish_second = client.post(f"/author/jobs/{source.source_job_id}/publish")
        listing = client.get("/stories")
        detail = client.get(f"/stories/{publish_first.json()['story_id']}")
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert publish_first.status_code == 200
    assert publish_second.status_code == 200
    assert publish_first.json()["story_id"] == publish_second.json()["story_id"]
    assert publish_first.json()["topology"] == topology_label(source.preview.structure.cast_topology)

    assert listing.status_code == 200
    assert len(listing.json()["stories"]) == 1
    assert listing.json()["stories"][0]["story_id"] == publish_first.json()["story_id"]
    assert listing.json()["stories"][0]["title"] == source.summary.title
    assert listing.json()["meta"]["total"] == 1
    assert listing.json()["meta"]["sort"] == "published_at_desc"

    assert detail.status_code == 200
    assert detail.json()["story"]["story_id"] == publish_first.json()["story_id"]
    assert detail.json()["preview"]["story"]["title"] == source.summary.title
    assert detail.json()["presentation"]["status"] == "open_for_play"
    assert detail.json()["presentation"]["status_label"] == "Open for play"
    assert detail.json()["presentation"]["dossier_ref"].startswith("Dossier N°")
    assert detail.json()["presentation"]["engine_label"] == "Relationship Drama V2 runtime"
    assert detail.json()["play_overview"]["protagonist"]["title"]
    assert detail.json()["play_overview"]["opening_narration"]
    assert detail.json()["play_overview"]["max_turns"] >= 4


def test_story_detail_contract_stays_content_oriented_for_frontend_scrollspy(tmp_path) -> None:
    import rpg_backend.main as main_module

    source = _publish_source()
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    owner_client = TestClient(app)
    anon_client = TestClient(app)
    try:
        ensure_authenticated_client(owner_client, email="story-detail@example.com", display_name="Detail Owner")
        published = owner_client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=public")
        detail = anon_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert published.status_code == 200
    assert detail.status_code == 200
    body = detail.json()
    assert body["story"]["title"]
    assert len(body["preview"]["beats"]) >= 1
    assert len(body["preview"]["cast_slots"]) >= 1
    assert body["presentation"]["status"] == "open_for_play"
    assert body["play_overview"]["protagonist"]["mandate"]
    assert body["play_overview"]["runtime_profile_label"]


def test_private_story_is_hidden_from_other_actor_until_visibility_changes(tmp_path) -> None:
    import rpg_backend.main as main_module

    source = _publish_source()
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    try:
        ensure_authenticated_client(alice_client, email="alice-library@example.com", display_name="Alice")
        ensure_authenticated_client(bob_client, email="bob-library@example.com", display_name="Bob")
        published = alice_client.post(f"/author/jobs/{source.source_job_id}/publish")
        hidden_list = bob_client.get("/stories")
        hidden_detail = bob_client.get(f"/stories/{published.json()['story_id']}")
        updated = alice_client.patch(
            f"/stories/{published.json()['story_id']}/visibility",
            json={"visibility": "public"},
        )
        public_list = bob_client.get("/stories")
        public_detail = bob_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert published.status_code == 200
    assert hidden_list.status_code == 200
    assert hidden_list.json()["stories"] == []
    assert hidden_detail.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["visibility"] == "public"
    assert public_list.status_code == 200
    assert [story["story_id"] for story in public_list.json()["stories"]] == [published.json()["story_id"]]
    assert public_list.json()["stories"][0]["viewer_can_manage"] is False
    assert public_detail.status_code == 200
    assert public_detail.json()["presentation"]["visibility"] == "public"
    assert public_detail.json()["presentation"]["viewer_can_manage"] is False


def test_story_detail_uses_v2_canonical_package_for_play_overview(tmp_path) -> None:
    import rpg_backend.main as main_module

    source = _publish_v2_source()
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, email="library-v2@example.com", display_name="V2 Owner")
        published = client.post(f"/author/jobs/{source.source_job_id}/publish")
        detail = client.get(f"/stories/{published.json()['story_id']}")
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert published.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["presentation"]["engine_label"] == "Relationship Drama V2 runtime"
    assert detail.json()["play_overview"]["play_length_preset"] == "12_15"


def test_story_listing_supports_accessible_mine_and_public_views(tmp_path) -> None:
    import rpg_backend.main as main_module

    alice_source = _publish_source("job-alice")
    bob_source = _publish_source("job-bob", title="Public Harbor Compact")
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.story_library_service = library_service
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    try:
        ensure_authenticated_client(alice_client, email="alice-views@example.com", display_name="Alice")
        ensure_authenticated_client(bob_client, email="bob-views@example.com", display_name="Bob")
        main_module.author_job_service = _FakeAuthorJobService(alice_source)
        alice_story = alice_client.post(f"/author/jobs/{alice_source.source_job_id}/publish?visibility=private")
        main_module.author_job_service = _FakeAuthorJobService(bob_source)
        bob_story = bob_client.post(f"/author/jobs/{bob_source.source_job_id}/publish?visibility=public")
        accessible = alice_client.get("/stories")
        mine = alice_client.get("/stories", params={"view": "mine"})
        public_only = alice_client.get("/stories", params={"view": "public"})
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert alice_story.status_code == 200
    assert bob_story.status_code == 200
    assert accessible.status_code == 200
    assert mine.status_code == 200
    assert public_only.status_code == 200

    accessible_ids = [story["story_id"] for story in accessible.json()["stories"]]
    mine_ids = [story["story_id"] for story in mine.json()["stories"]]
    public_ids = [story["story_id"] for story in public_only.json()["stories"]]

    assert accessible.json()["meta"]["view"] == "accessible"
    assert mine.json()["meta"]["view"] == "mine"
    assert public_only.json()["meta"]["view"] == "public"
    assert alice_story.json()["story_id"] in accessible_ids
    assert bob_story.json()["story_id"] in accessible_ids
    assert mine_ids == [alice_story.json()["story_id"]]
    assert public_ids == [bob_story.json()["story_id"]]


def test_story_cursor_is_bound_to_view_dimension(tmp_path) -> None:
    import rpg_backend.main as main_module

    alice_source = _publish_source("job-view-alice")
    bob_source = _publish_source("job-view-bob", title="Public View Story")
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.story_library_service = library_service
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    try:
        ensure_authenticated_client(alice_client, email="alice-cursor@example.com", display_name="Alice")
        ensure_authenticated_client(bob_client, email="bob-cursor@example.com", display_name="Bob")
        main_module.author_job_service = _FakeAuthorJobService(alice_source)
        alice_client.post(f"/author/jobs/{alice_source.source_job_id}/publish?visibility=private")
        main_module.author_job_service = _FakeAuthorJobService(bob_source)
        bob_client.post(f"/author/jobs/{bob_source.source_job_id}/publish?visibility=public")
        first_page = alice_client.get("/stories", params={"view": "accessible", "limit": 1})
        mismatched = alice_client.get(
            "/stories",
            params={"view": "public", "limit": 1, "cursor": first_page.json()["meta"]["next_cursor"]},
        )
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert first_page.status_code == 200
    assert first_page.json()["meta"]["next_cursor"] is not None
    assert mismatched.status_code == 400
    assert mismatched.json()["error"]["code"] == "story_cursor_invalid"


def test_owner_can_delete_story_and_non_owner_cannot(tmp_path) -> None:
    import rpg_backend.main as main_module

    source = _publish_source("job-delete")
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_author_service = main_module.author_job_service
    original_library_service = main_module.story_library_service
    main_module.author_job_service = _FakeAuthorJobService(source)
    main_module.story_library_service = library_service
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    try:
        ensure_authenticated_client(alice_client, email="alice-delete@example.com", display_name="Alice")
        ensure_authenticated_client(bob_client, email="bob-delete@example.com", display_name="Bob")
        published = alice_client.post(f"/author/jobs/{source.source_job_id}/publish?visibility=private")
        blocked = bob_client.delete(f"/stories/{published.json()['story_id']}")
        deleted = alice_client.delete(f"/stories/{published.json()['story_id']}")
        detail = alice_client.get(f"/stories/{published.json()['story_id']}")
    finally:
        main_module.author_job_service = original_author_service
        main_module.story_library_service = original_library_service

    assert published.status_code == 200
    assert blocked.status_code == 404
    assert deleted.status_code == 200
    assert deleted.json() == {"story_id": published.json()["story_id"], "deleted": True}
    assert detail.status_code == 404


def test_story_listing_supports_keyword_search_and_theme_facets(tmp_path) -> None:
    import rpg_backend.main as main_module

    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_library_service = main_module.story_library_service
    main_module.story_library_service = library_service
    client = TestClient(app)
    try:
        harbor_source = _publish_source(
            "job-harbor",
            prompt_seed="A harbor inspector must stop quarantine profiteers before the vote collapses.",
            title="Harbor Compact",
            premise="A harbor inspector must stop quarantine profiteers before the vote collapses.",
            tone="Tense civic fantasy",
            primary_theme="logistics_quarantine_crisis",
            modifiers=["harbor", "quarantine"],
        )
        archive_source = _publish_source(
            "job-archive",
            prompt_seed="An archivist exposes forged ledgers before the certification hearing closes.",
            title="Archive Accord",
            premise="An archivist exposes forged ledgers before the certification hearing closes.",
            tone="Procedural civic suspense",
            primary_theme="truth_record_crisis",
            modifiers=["archive", "ledger"],
        )
        for source in (harbor_source, archive_source):
            library_service.publish_story(
                owner_user_id="usr_search_owner",
                source_job_id=source.source_job_id,
                prompt_seed=source.prompt_seed,
                summary=source.summary,
                preview=source.preview,
                bundle=source.bundle,
                visibility="public",
            )

        search_response = client.get("/stories", params={"q": "harbor"})
        theme_response = client.get("/stories", params={"theme": "Truth and record crisis"})
    finally:
        main_module.story_library_service = original_library_service

    assert search_response.status_code == 200
    assert [story["title"] for story in search_response.json()["stories"]] == ["Harbor Compact"]
    assert search_response.json()["meta"] == {
        "query": "harbor",
        "theme": None,
        "view": "accessible",
        "sort": "relevance",
        "limit": 20,
        "next_cursor": None,
        "has_more": False,
        "total": 1,
    }
    assert search_response.json()["facets"]["themes"] == [
        {"theme": "Logistics quarantine crisis", "count": 1}
    ]

    assert theme_response.status_code == 200
    assert [story["title"] for story in theme_response.json()["stories"]] == ["Archive Accord"]
    assert theme_response.json()["meta"]["query"] is None
    assert theme_response.json()["meta"]["theme"] == "Truth and record crisis"
    assert theme_response.json()["meta"]["view"] == "accessible"
    assert theme_response.json()["meta"]["sort"] == "published_at_desc"


def test_story_listing_tolerates_pre_migrated_story_columns(tmp_path) -> None:
    db_path = tmp_path / "stories.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE published_stories (
            story_id TEXT PRIMARY KEY,
            source_job_id TEXT NOT NULL UNIQUE,
            prompt_seed TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            one_liner TEXT NOT NULL DEFAULT '',
            premise TEXT NOT NULL DEFAULT '',
            theme TEXT NOT NULL DEFAULT '',
            tone TEXT NOT NULL DEFAULT '',
            npc_count INTEGER NOT NULL DEFAULT 0,
            beat_count INTEGER NOT NULL DEFAULT 0,
            topology TEXT NOT NULL DEFAULT '',
            summary_json TEXT NOT NULL,
            preview_json TEXT NOT NULL,
            bundle_json TEXT NOT NULL,
            published_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(db_path)))

    response = library_service.list_stories(actor_user_id=None)

    assert response.stories == []
    assert response.meta is not None
    assert response.meta.total == 0


def test_story_listing_paginates_with_cursor(tmp_path) -> None:
    import rpg_backend.main as main_module

    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    original_library_service = main_module.story_library_service
    main_module.story_library_service = library_service
    client = TestClient(app)
    try:
        for index in range(3):
            source = _publish_source(
                f"job-{index}",
                prompt_seed=f"A search seed {index}",
                title=f"Story {index}",
                premise=f"Story premise {index}",
            )
            library_service.publish_story(
                owner_user_id="usr_page_owner",
                source_job_id=source.source_job_id,
                prompt_seed=source.prompt_seed,
                summary=source.summary,
                preview=source.preview,
                bundle=source.bundle,
                visibility="public",
            )

        first_page = client.get("/stories", params={"limit": 1})
        second_page = client.get(
            "/stories",
            params={"limit": 1, "cursor": first_page.json()["meta"]["next_cursor"]},
        )
    finally:
        main_module.story_library_service = original_library_service

    assert first_page.status_code == 200
    assert first_page.json()["meta"]["has_more"] is True
    assert first_page.json()["meta"]["next_cursor"]
    assert len(first_page.json()["stories"]) == 1

    assert second_page.status_code == 200
    assert len(second_page.json()["stories"]) == 1
    assert first_page.json()["stories"][0]["story_id"] != second_page.json()["stories"][0]["story_id"]
