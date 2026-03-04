from __future__ import annotations

_SESSION_CONFLICT_ERROR_CODE = "session_conflict_retry"
_SESSION_CONFLICT_MESSAGE = "session advanced by another action; retry with new client_action_id"


def session_conflict_code() -> str:
    return _SESSION_CONFLICT_ERROR_CODE


def build_session_conflict_detail(
    *,
    session_id: str,
    expected_turn_index: int,
    actual_turn_index: int,
) -> dict[str, object]:
    return {
        "error_code": _SESSION_CONFLICT_ERROR_CODE,
        "message": _SESSION_CONFLICT_MESSAGE,
        "session_id": session_id,
        "expected_turn_index": expected_turn_index,
        "actual_turn_index": actual_turn_index,
        "retryable": True,
    }
