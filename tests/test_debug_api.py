from __future__ import annotations

import json
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.config import settings
from app.db.session import engine
from app.main import app


def _pack(*, story_id: str = "campus_week_v1") -> dict:
    with open("examples/storypacks/campus_week_v1.json", "r", encoding="utf-8") as f:
        pack = json.load(f)

    if story_id != pack["story_id"]:
        pack["story_id"] = story_id
        pack["title"] = f"{pack['title']} ({story_id})"
    return pack


def _author_headers(author_token: str | None = None) -> dict:
    if not author_token:
        return {}
    return {"X-Author-Token": author_token}


def _player_headers(player_token: str | None = None) -> dict:
    if not player_token:
        return {}
    return {"X-Player-Token": player_token}


def _create_and_publish_story(
    client: TestClient,
    *,
    story_id: str = "campus_week_v1",
    author_token: str | None = None,
) -> None:
    pack = _pack(story_id=story_id)
    headers = _author_headers(author_token)
    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
        headers=headers,
    )
    assert created.status_code == 201
    version = int(created.json()["version"])
    published = client.post(
        f"/api/v1/stories/{pack['story_id']}/publish",
        json={"version": version},
        headers=headers,
    )
    assert published.status_code == 200


def _create_session(
    client: TestClient,
    *,
    story_id: str = "campus_week_v1",
    player_token: str | None = None,
) -> str:
    created = client.post(
        "/api/v1/sessions",
        json={"story_id": story_id},
        headers=_player_headers(player_token),
    )
    assert created.status_code == 201
    return str(created.json()["session_id"])


def _step(
    client: TestClient,
    sid: str,
    payload: dict,
    *,
    key: str,
    player_token: str | None = None,
) -> dict:
    headers = {"X-Idempotency-Key": key, **_player_headers(player_token)}
    res = client.post(
        f"/api/v1/sessions/{sid}/step",
        json=payload,
        headers=headers,
    )
    assert res.status_code == 200
    return res.json()


@contextmanager
def _capture_select_statements() -> list[str]:
    statements: list[str] = []

    def _listener(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001,ANN201
        del conn, cursor, parameters, context, executemany
        sql = str(statement).lstrip().upper()
        if sql.startswith("SELECT"):
            statements.append(str(statement))

    event.listen(engine, "before_cursor_execute", _listener)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _listener)


def test_debug_sessions_list_returns_filtered_results() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")
    _create_and_publish_story(client, story_id="campus_week_alt")

    _create_session(client, story_id="campus_week_v1")
    ended_sid = _create_session(client, story_id="campus_week_v1")
    _step(client, ended_sid, {"choice_id": "c_join_enemy"}, key="debug-list-end")
    _create_session(client, story_id="campus_week_alt")

    res = client.get(
        "/api/v1/debug/sessions",
        params={"story_id": "campus_week_v1", "status": "ended", "limit": 20, "offset": 0},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["session_id"] == ended_sid
    assert body["sessions"][0]["story_id"] == "campus_week_v1"
    assert body["sessions"][0]["status"] == "ended"


def test_debug_sessions_list_uses_constant_query_count() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")

    for idx in range(8):
        sid = _create_session(client, story_id="campus_week_v1")
        _step(client, sid, {"choice_id": "c_study"}, key=f"debug-query-{idx}")

    with _capture_select_statements() as selects:
        res = client.get(
            "/api/v1/debug/sessions",
            params={"story_id": "campus_week_v1", "limit": 20, "offset": 0},
        )

    assert res.status_code == 200
    assert len(selects) <= 3


def test_debug_bundle_full_default_returns_all_sections() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")
    sid = _create_session(client, story_id="campus_week_v1")
    _step(client, sid, {"choice_id": "c_study"}, key="debug-bundle-1")

    res = client.get(f"/api/v1/debug/sessions/{sid}/bundle")
    assert res.status_code == 200
    body = res.json()

    assert body["session_id"] == sid
    assert body["include"]["telemetry"] is True
    assert body["include"]["versions"] is True
    assert body["include"]["latest_step_detail"] is True
    assert body["overview"]["session_id"] == sid
    assert body["timeline"]["limit"] == 50
    assert isinstance(body["telemetry"], dict)
    assert isinstance(body["versions"], list)
    assert len(body["versions"]) >= 1
    assert isinstance(body["latest_step_detail"], dict)
    assert body["latest_step_detail"]["step_index"] == 1


def test_debug_bundle_include_subset_returns_requested_sections_only() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")
    sid = _create_session(client, story_id="campus_week_v1")
    _step(client, sid, {"choice_id": "c_study"}, key="debug-bundle-2")

    res = client.get(
        f"/api/v1/debug/sessions/{sid}/bundle",
        params={"include": "telemetry", "timeline_limit": 20},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["include"]["telemetry"] is True
    assert body["include"]["versions"] is False
    assert body["include"]["latest_step_detail"] is False
    assert isinstance(body["telemetry"], dict)
    assert body["versions"] == []
    assert body["latest_step_detail"] is None
    assert body["timeline"]["limit"] == 20


def test_debug_bundle_requires_author_token_when_enabled() -> None:
    settings.author_api_token = "author-secret"
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1", author_token="author-secret")
    sid = _create_session(client, story_id="campus_week_v1")

    missing = client.get(f"/api/v1/debug/sessions/{sid}/bundle")
    assert missing.status_code == 401

    ok = client.get(
        f"/api/v1/debug/sessions/{sid}/bundle",
        headers={"X-Author-Token": "author-secret"},
    )
    assert ok.status_code == 200


def test_debug_timeline_orders_by_step_index() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")
    sid = _create_session(client, story_id="campus_week_v1")

    _step(client, sid, {"choice_id": "c_study"}, key="debug-timeline-1")
    _step(client, sid, {"player_input": "off_topic sing"}, key="debug-timeline-2")

    res = client.get(f"/api/v1/debug/sessions/{sid}/timeline", params={"limit": 100, "offset": 0})
    assert res.status_code == 200
    body = res.json()
    steps = body["steps"]
    assert body["total"] == 2
    assert [item["step_index"] for item in steps] == [1, 2]
    assert steps[0]["executed_choice_id"] == "c_study"
    assert isinstance(steps[1]["executed_choice_id"], str)


def test_timeline_has_run_ended_and_ending_fields_after_ending_step() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")
    sid = _create_session(client, story_id="campus_week_v1")

    _step(client, sid, {"choice_id": "c_join_enemy"}, key="debug-ending-1")

    timeline = client.get(f"/api/v1/debug/sessions/{sid}/timeline", params={"limit": 100, "offset": 0})
    assert timeline.status_code == 200
    timeline_body = timeline.json()
    assert timeline_body["total"] == 1
    assert timeline_body["steps"][0]["run_ended"] is True
    assert isinstance(timeline_body["steps"][0]["ending_id"], str)

    detail = client.get(f"/api/v1/debug/sessions/{sid}/steps/1")
    assert detail.status_code == 200
    selection = detail.json()["selection_result_json"]
    assert selection["run_ended"] is True
    assert isinstance(selection["ending_id"], str)
    assert "ending_outcome" in selection
    assert selection["step_index"] == 1


def test_debug_step_detail_contains_state_and_llm_trace() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")
    sid = _create_session(client, story_id="campus_week_v1")

    _step(client, sid, {"choice_id": "c_study"}, key="debug-detail-1")

    detail = client.get(f"/api/v1/debug/sessions/{sid}/steps/1")
    assert detail.status_code == 200
    body = detail.json()

    assert body["session_id"] == sid
    assert body["step_index"] == 1
    assert isinstance(body["request_payload_json"], dict)
    assert isinstance(body["selection_result_json"], dict)
    assert isinstance(body["state_before"], dict)
    assert isinstance(body["state_delta"], dict)
    assert isinstance(body["state_after"], dict)
    assert isinstance(body["llm_trace_json"], dict)
    assert isinstance(body["classification_json"], dict)
    assert "selection_source" in body["selection_result_json"]
    assert "provider" in body["llm_trace_json"]
    assert "fallback_reason" in body["classification_json"]


def test_debug_step_detail_contains_raw_and_effective_tier() -> None:
    client = TestClient(app)
    _create_and_publish_story(client, story_id="campus_week_v1")
    sid = _create_session(client, story_id="campus_week_v1")

    _step(client, sid, {"player_input": "off_topic sing"}, key="debug-tier-1")
    detail = client.get(f"/api/v1/debug/sessions/{sid}/steps/1")
    assert detail.status_code == 200
    selection = detail.json()["selection_result_json"]
    assert "raw_intensity_tier" in selection
    assert "effective_intensity_tier" in selection


def test_debug_routes_require_author_token_when_enabled() -> None:
    settings.author_api_token = "author-secret"
    client = TestClient(app)

    missing = client.get("/api/v1/debug/sessions")
    assert missing.status_code == 401

    ok = client.get(
        "/api/v1/debug/sessions",
        headers={"X-Author-Token": "author-secret"},
    )
    assert ok.status_code == 200
    assert "sessions" in ok.json()
