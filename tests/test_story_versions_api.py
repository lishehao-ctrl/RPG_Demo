from __future__ import annotations

import copy
import json

from fastapi.testclient import TestClient

from app.main import app


def _pack(path: str = "examples/storypacks/campus_week_v1.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _pack_with_identity(*, story_id: str, title: str) -> dict:
    base = copy.deepcopy(_pack())
    base["story_id"] = story_id
    base["title"] = title
    return base


def _create_and_publish(client: TestClient) -> int:
    pack = _pack()
    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = int(created.json()["version"])
    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 200
    return version


def _create_and_publish_pack(client: TestClient, pack: dict) -> int:
    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = int(created.json()["version"])
    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 200
    return version


def test_story_versions_list_and_detail() -> None:
    client = TestClient(app)
    _create_and_publish(client)

    created_draft = client.post("/api/v1/stories/campus_week_v1/drafts", json={})
    assert created_draft.status_code == 201
    draft_detail = created_draft.json()
    assert draft_detail["version"] == 2
    assert draft_detail["status"] == "draft"

    listed = client.get("/api/v1/stories/campus_week_v1/versions")
    assert listed.status_code == 200
    versions = listed.json()["versions"]
    assert [item["version"] for item in versions] == [2, 1]
    assert versions[0]["status"] == "draft"
    assert versions[1]["status"] == "published"

    detail = client.get("/api/v1/stories/campus_week_v1/versions/2")
    assert detail.status_code == 200
    body = detail.json()
    assert body["story_id"] == "campus_week_v1"
    assert body["version"] == 2
    assert isinstance(body["pack"], dict)


def test_create_draft_requires_published_story() -> None:
    client = TestClient(app)
    pack = _pack()

    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201

    copied = client.post("/api/v1/stories/campus_week_v1/drafts", json={})
    assert copied.status_code == 404
    assert copied.json()["detail"]["code"] == "NOT_FOUND"


def test_update_story_draft_and_reject_published_update() -> None:
    client = TestClient(app)
    _create_and_publish(client)

    created_draft = client.post("/api/v1/stories/campus_week_v1/drafts", json={})
    assert created_draft.status_code == 201

    detail = client.get("/api/v1/stories/campus_week_v1/versions/2")
    pack = detail.json()["pack"]
    pack["title"] = "Campus Week Updated"
    pack["nodes"][0]["choices"][0]["text"] = "Study with full focus"

    updated = client.put(
        "/api/v1/stories/campus_week_v1/versions/2",
        json={"title": "Campus Week Updated", "pack": pack},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Campus Week Updated"
    assert updated.json()["pack"]["nodes"][0]["choices"][0]["text"] == "Study with full focus"

    cannot_update_published = client.put(
        "/api/v1/stories/campus_week_v1/versions/1",
        json={"pack": pack},
    )
    assert cannot_update_published.status_code == 409
    assert cannot_update_published.json()["detail"]["code"] == "VERSION_NOT_DRAFT"


def test_story_catalog_returns_only_published_stories() -> None:
    client = TestClient(app)

    published_pack = _pack_with_identity(story_id="catalog_pub_v1", title="Catalog Published")
    _create_and_publish_pack(client, published_pack)

    draft_pack = _pack_with_identity(story_id="catalog_draft_v1", title="Catalog Draft")
    created = client.post(
        "/api/v1/stories",
        json={"story_id": draft_pack["story_id"], "title": draft_pack["title"], "pack": draft_pack},
    )
    assert created.status_code == 201

    listed = client.get("/api/v1/stories/catalog/published")
    assert listed.status_code == 200
    body = listed.json()
    story_ids = {item["story_id"] for item in body["stories"]}
    assert "catalog_pub_v1" in story_ids
    assert "catalog_draft_v1" not in story_ids


def test_story_catalog_includes_title_version_updated_at() -> None:
    client = TestClient(app)
    pack = _pack_with_identity(story_id="catalog_fields_v1", title="Catalog Fields")
    published_version = _create_and_publish_pack(client, pack)

    listed = client.get("/api/v1/stories/catalog/published")
    assert listed.status_code == 200
    target = next(item for item in listed.json()["stories"] if item["story_id"] == "catalog_fields_v1")
    assert target["title"] == "Catalog Fields"
    assert int(target["published_version"]) == published_version
    assert isinstance(target["updated_at"], str)
    assert target["updated_at"].endswith("Z")


def test_story_catalog_empty_when_no_published_story() -> None:
    client = TestClient(app)
    listed = client.get("/api/v1/stories/catalog/published")
    assert listed.status_code == 200
    assert listed.json() == {"stories": []}


def test_story_catalog_order_is_updated_desc_then_story_id() -> None:
    client = TestClient(app)
    _create_and_publish_pack(client, _pack_with_identity(story_id="catalog_order_a", title="Order A"))
    _create_and_publish_pack(client, _pack_with_identity(story_id="catalog_order_b", title="Order B"))

    listed = client.get("/api/v1/stories/catalog/published")
    assert listed.status_code == 200
    story_ids = [item["story_id"] for item in listed.json()["stories"]]
    idx_a = story_ids.index("catalog_order_a")
    idx_b = story_ids.index("catalog_order_b")
    assert idx_b < idx_a
