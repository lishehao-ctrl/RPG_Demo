from __future__ import annotations

HEALTH_PATH = "/health"
READY_PATH = "/ready"

API_V2_STORIES_PREFIX = "/v2/stories"
API_V2_SESSIONS_PREFIX = "/v2/sessions"
API_V2_ADMIN_SESSIONS_PREFIX = "/v2/admin/sessions"
API_V2_ADMIN_OBSERVABILITY_PREFIX = "/v2/admin/observability"

LEGACY_STORIES_PREFIX = "/stories"
LEGACY_SESSIONS_PREFIX = "/sessions"
LEGACY_ADMIN_PREFIX = "/admin"


def stories_path() -> str:
    return API_V2_STORIES_PREFIX


def story_path(story_id: str) -> str:
    return f"{API_V2_STORIES_PREFIX}/{story_id}"


def story_publish_path(story_id: str) -> str:
    return f"{API_V2_STORIES_PREFIX}/{story_id}/publish"


def stories_generate_path() -> str:
    return f"{API_V2_STORIES_PREFIX}/generate"


def sessions_path() -> str:
    return API_V2_SESSIONS_PREFIX


def session_path(session_id: str) -> str:
    return f"{API_V2_SESSIONS_PREFIX}/{session_id}"


def session_step_path(session_id: str) -> str:
    return f"{API_V2_SESSIONS_PREFIX}/{session_id}/step"


def admin_session_timeline_path(session_id: str) -> str:
    return f"{API_V2_ADMIN_SESSIONS_PREFIX}/{session_id}/timeline"


def admin_session_feedback_path(session_id: str) -> str:
    return f"{API_V2_ADMIN_SESSIONS_PREFIX}/{session_id}/feedback"


def admin_runtime_errors_path() -> str:
    return f"{API_V2_ADMIN_OBSERVABILITY_PREFIX}/runtime-errors"


def admin_http_health_path() -> str:
    return f"{API_V2_ADMIN_OBSERVABILITY_PREFIX}/http-health"


def admin_llm_call_health_path() -> str:
    return f"{API_V2_ADMIN_OBSERVABILITY_PREFIX}/llm-call-health"


def admin_readiness_health_path() -> str:
    return f"{API_V2_ADMIN_OBSERVABILITY_PREFIX}/readiness-health"

