from __future__ import annotations

from app.config import settings
from app.modules.session.runtime_pack import implicit_fallback_spec
from app.modules.story.constants import RESERVED_CHOICE_ID_PREFIX
from app.modules.story.fallback_narration import select_fallback_skeleton_text


def is_valid_story_action(action: dict | None) -> bool:
    if not isinstance(action, dict):
        return False
    action_id = str(action.get("action_id") or "")
    params = action.get("params")
    if not isinstance(params, dict):
        return False

    if action_id in {"study", "work", "rest", "clarify"}:
        return params == {}
    if action_id == "date":
        return isinstance(params.get("target"), str) and bool(str(params.get("target")))
    if action_id == "gift":
        return (
            isinstance(params.get("target"), str)
            and bool(str(params.get("target")))
            and isinstance(params.get("gift_type"), str)
            and bool(str(params.get("gift_type")))
        )
    return False


def resolve_runtime_fallback(node: dict, current_node_id: str, node_ids: set[str]) -> tuple[dict, str, list[str]]:
    fallback = dict((node.get("fallback") or {}))
    fallback_source = str(node.get("_fallback_source") or "node")
    markers: list[str] = []
    if fallback_source == "implicit":
        markers.append("FALLBACK_CONFIG_IMPLICIT")
        markers.append("FALLBACK_CONFIG_MISSING")

    fallback_id = fallback.get("id")
    if isinstance(fallback_id, str) and fallback_id.startswith(RESERVED_CHOICE_ID_PREFIX):
        fallback["id"] = None
        markers.append("FALLBACK_CONFIG_RESERVED_ID_PREFIX")

    malformed = False
    if not is_valid_story_action(fallback.get("action")):
        malformed = True

    policy = str(fallback.get("next_node_id_policy") or "")
    next_node_id = current_node_id
    if policy == "stay":
        next_node_id = current_node_id
    elif policy == "explicit_next":
        candidate = str(fallback.get("next_node_id") or "")
        if not candidate or candidate not in node_ids:
            malformed = True
        else:
            next_node_id = candidate
    else:
        malformed = True

    if malformed:
        fallback = implicit_fallback_spec()
        next_node_id = current_node_id
        markers.append("FALLBACK_CONFIG_INVALID")
        if "FALLBACK_CONFIG_IMPLICIT" not in markers:
            markers.append("FALLBACK_CONFIG_IMPLICIT")

    return fallback, next_node_id, sorted(set(markers))


def fallback_executed_choice_id(fallback: dict, current_node_id: str) -> str:
    fallback_id = fallback.get("id")
    if fallback_id and not str(fallback_id).startswith(RESERVED_CHOICE_ID_PREFIX):
        return str(fallback_id)
    return f"__fallback__:{current_node_id}"


def select_fallback_text_variant(
    fallback: dict,
    reason_code: str | None,
    locale: str | None = None,
) -> str | None:
    return select_fallback_skeleton_text(
        text_variants=((fallback or {}).get("text_variants") if isinstance(fallback, dict) else None),
        reason=reason_code,
        locale=locale or settings.story_default_locale,
    )
