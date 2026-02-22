from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.support.db_runtime import prepare_sqlite_db


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "author_assist.db")


def _base_context() -> dict:
    return {
        "format_version": 4,
        "global_brief": "A student balances classes, side work, and relationships over one week.",
        "layer": "world",
        "story_id": "assist_story",
        "title": "Assist Story",
        "mainline_goal": "Reach the weekend with momentum.",
        "scene_key": "scene_intro",
        "scene_title": "Morning Setup",
        "option_label": "Focus on study",
        "action_type": "study",
    }


@pytest.mark.parametrize(
    "task",
    [
        "story_ingest",
        "seed_expand",
        "beat_to_scene",
        "scene_deepen",
        "option_weave",
        "consequence_balance",
        "ending_design",
        "consistency_check",
    ],
)
def test_author_assist_tasks_return_stable_shape(tmp_path: Path, task: str) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": task,
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    assert isinstance(body.get("suggestions"), dict)
    assert isinstance(body.get("patch_preview"), list)
    assert isinstance(body.get("warnings"), list)
    assert isinstance(body.get("provider"), str) and body["provider"]
    assert isinstance(body.get("model"), str) and body["model"]

    for patch in body["patch_preview"]:
        assert isinstance(patch, dict)
        assert isinstance(patch.get("id"), str) and patch["id"]
        assert isinstance(patch.get("path"), str) and patch["path"]
        assert isinstance(patch.get("label"), str) and patch["label"]
        assert "value" in patch


def test_author_assist_rejects_unknown_task(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": "unknown_task",
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "ASSIST_TASK_V4_REQUIRED"
