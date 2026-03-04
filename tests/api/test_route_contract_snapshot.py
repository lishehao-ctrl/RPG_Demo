from __future__ import annotations

from rpg_backend.api.route_paths import (
    HEALTH_PATH,
    READY_PATH,
    admin_auth_login_path,
    admin_http_health_path,
    admin_llm_call_health_path,
    admin_readiness_health_path,
    admin_runtime_errors_path,
    admin_session_feedback_path,
    admin_session_timeline_path,
    admin_user_path,
    admin_users_path,
    session_path,
    session_step_path,
    sessions_path,
    story_path,
    story_publish_path,
    stories_generate_path,
    stories_path,
)
from rpg_backend.main import app


def test_backend_openapi_path_snapshot_is_stable() -> None:
    expected_paths = {
        HEALTH_PATH,
        READY_PATH,
        stories_path(),
        stories_generate_path(),
        story_path("{story_id}"),
        story_publish_path("{story_id}"),
        sessions_path(),
        session_path("{session_id}"),
        session_step_path("{session_id}"),
        admin_auth_login_path(),
        admin_users_path(),
        admin_user_path("{user_id}"),
        admin_session_timeline_path("{session_id}"),
        admin_session_feedback_path("{session_id}"),
        admin_runtime_errors_path(),
        admin_http_health_path(),
        admin_llm_call_health_path(),
        admin_readiness_health_path(),
    }
    actual_paths = set(app.openapi()["paths"].keys())
    assert actual_paths == expected_paths
