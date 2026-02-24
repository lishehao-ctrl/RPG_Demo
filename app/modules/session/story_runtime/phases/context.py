from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Session as StorySession
from app.modules.session.story_runtime.models import StoryRuntimeContext


def phase_load_runtime_context(
    *,
    db: Session,
    sess: StorySession,
    deps: Any,
) -> StoryRuntimeContext:
    story_row = deps.load_story_pack(db, sess.story_id, sess.story_version)
    runtime_pack = deps.normalize_pack_for_runtime(story_row.pack_json or {})
    story_node_id = str(sess.story_node_id or "").strip()
    if story_node_id:
        current_node_id = story_node_id
    else:
        raise HTTPException(status_code=400, detail={"code": "STORY_NODE_MISSING"})

    node = deps.story_node(runtime_pack, current_node_id)
    if not node:
        raise HTTPException(status_code=400, detail={"code": "STORY_NODE_MISSING"})

    node_ids = {
        str(n.get("node_id"))
        for n in (runtime_pack.get("nodes") or [])
        if (n or {}).get("node_id") is not None
    }
    visible_choices = [dict(c) for c in (node.get("choices") or []) if isinstance(c, dict)]
    fallback_spec, fallback_next_node_id, fallback_markers = deps.resolve_runtime_fallback(
        node=node,
        current_node_id=current_node_id,
        node_ids=node_ids,
    )
    fallback_executors = [
        dict(item)
        for item in (runtime_pack.get("fallback_executors") or [])
        if isinstance(item, dict)
    ]
    return StoryRuntimeContext(
        runtime_pack=runtime_pack,
        current_node_id=current_node_id,
        node=node,
        visible_choices=visible_choices,
        fallback_spec=fallback_spec,
        fallback_next_node_id=fallback_next_node_id,
        fallback_markers=fallback_markers,
        intents=[dict(v) for v in (node.get("intents") or []) if isinstance(v, dict)],
        fallback_executors=fallback_executors,
        node_fallback_choice_id=(
            str(node.get("node_fallback_choice_id"))
            if (node.get("node_fallback_choice_id") is not None)
            else None
        ),
        global_fallback_choice_id=(
            str(runtime_pack.get("global_fallback_choice_id"))
            if runtime_pack.get("global_fallback_choice_id") is not None
            else None
        ),
    )


def resolve_node_fallback_choice(context: StoryRuntimeContext) -> dict | None:
    if not context.node_fallback_choice_id:
        return None
    return next(
        (c for c in context.visible_choices if str(c.get("choice_id")) == str(context.node_fallback_choice_id)),
        None,
    )


def resolve_global_fallback_executor(context: StoryRuntimeContext) -> dict | None:
    if not context.global_fallback_choice_id:
        return None
    return next(
        (e for e in context.fallback_executors if str(e.get("id")) == str(context.global_fallback_choice_id)),
        None,
    )
