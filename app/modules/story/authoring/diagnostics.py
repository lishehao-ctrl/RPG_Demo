from __future__ import annotations


def diag(
    *,
    code: str,
    path: str | None,
    message: str,
    suggestion: str | None = None,
) -> dict[str, str | None]:
    return {
        "code": code,
        "path": path,
        "message": message,
        "suggestion": suggestion,
    }


def looks_like_author_pre_v4_payload(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    raw_version = payload.get("format_version")
    try:
        version = int(raw_version)
    except Exception:  # noqa: BLE001
        version = 0
    return version != 4


def author_v4_required_message() -> str:
    return (
        "Author API now requires ASF v4 payload: include format_version=4 and use "
        "entry_mode/source_text/meta/world/characters/plot/flow/action/consequence/ending/systems "
        "plus writer_journal and playability_policy."
    )
