from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Story, StoryVersion, User
from app.modules.story_domain.schemas import (
    EndingDefV1,
    GlobalFallbackV1,
    StoryAuditIssue,
    StoryPackV1,
    resolve_effective_fallbacks_endings,
)
from app.utils.time import utc_now_naive


def _pack_checksum(pack: dict) -> str:
    canonical = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _issue(*, code: str, severity: str, path: str, message: str, suggestion: str | None = None) -> StoryAuditIssue:
    return StoryAuditIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        path=path,
        message=message,
        suggestion=suggestion,
    )


def _audit_default_hub_node_id(pack_model: StoryPackV1, node_ids: set[str]) -> str:
    if "n_hub" in node_ids:
        return "n_hub"
    return pack_model.start_node_id


def _audit_resolve_fallback_target_for_node(
    *,
    node: object,
    fallback: GlobalFallbackV1,
    fallback_by_id: dict[str, GlobalFallbackV1],
    default_hub_node_id: str,
) -> str:
    if fallback.target_node_id:
        return fallback.target_node_id

    node_fallback_id = str(getattr(node, "node_fallback_id", "") or "").strip()
    if node_fallback_id and node_fallback_id in fallback_by_id:
        linked = fallback_by_id[node_fallback_id]
        if linked.target_node_id:
            return linked.target_node_id

    return default_hub_node_id


def _build_adjacency_with_fallbacks(
    pack_model: StoryPackV1,
    *,
    effective_fallbacks: list[GlobalFallbackV1],
) -> dict[str, list[str]]:
    node_ids = {node.node_id for node in pack_model.nodes}
    fallback_by_id = {item.fallback_id: item for item in effective_fallbacks}
    default_hub_node_id = _audit_default_hub_node_id(pack_model, node_ids)
    adjacency: dict[str, list[str]] = {}

    for node in pack_model.nodes:
        edges: list[str] = []
        seen: set[str] = set()

        for choice in node.choices:
            nxt = str(choice.next_node_id)
            if nxt in node_ids and nxt not in seen:
                seen.add(nxt)
                edges.append(nxt)

        for fallback in effective_fallbacks:
            nxt = _audit_resolve_fallback_target_for_node(
                node=node,
                fallback=fallback,
                fallback_by_id=fallback_by_id,
                default_hub_node_id=default_hub_node_id,
            )
            if nxt in node_ids and nxt not in seen:
                seen.add(nxt)
                edges.append(nxt)

        adjacency[node.node_id] = edges

    return adjacency


def _reachable_nodes(
    pack_model: StoryPackV1,
    *,
    effective_fallbacks: list[GlobalFallbackV1],
) -> tuple[set[str], dict[str, list[str]]]:
    adjacency = _build_adjacency_with_fallbacks(pack_model, effective_fallbacks=effective_fallbacks)

    visited: set[str] = set()
    stack = [pack_model.start_node_id]
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        for nxt in adjacency.get(node_id, []):
            if nxt not in visited:
                stack.append(nxt)
    return visited, adjacency


def _scc_components(nodes: list[str], adjacency: dict[str, list[str]]) -> list[set[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    out: list[set[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for nxt in adjacency.get(node, []):
            if nxt not in indices:
                strongconnect(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], indices[nxt])

        if low[node] == indices[node]:
            component: set[str] = set()
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.add(w)
                if w == node:
                    break
            out.append(component)

    for node in nodes:
        if node not in indices:
            strongconnect(node)
    return out


def audit_story_pack(pack: dict) -> tuple[list[StoryAuditIssue], list[StoryAuditIssue]]:
    try:
        pack_model = StoryPackV1.model_validate(pack)
    except Exception as exc:  # noqa: BLE001
        return [
            _issue(
                code="PACK_SCHEMA_INVALID",
                severity="error",
                path="$",
                message=str(exc),
                suggestion="Fix schema validation errors first.",
            )
        ], []

    errors: list[StoryAuditIssue] = []
    warnings: list[StoryAuditIssue] = []
    node_map = {node.node_id: node for node in pack_model.nodes}
    node_ids = set(node_map.keys())
    effective_fallbacks, effective_endings = resolve_effective_story_assets(pack_model)
    ending_ids = {item.ending_id for item in effective_endings}

    reachable, adjacency = _reachable_nodes(pack_model, effective_fallbacks=effective_fallbacks)
    for node_id in sorted(node_ids - reachable):
        errors.append(
            _issue(
                code="UNREACHABLE_NODE",
                severity="error",
                path=f"nodes[{node_id}]",
                message=f"Node `{node_id}` is unreachable from start_node.",
                suggestion="Add an incoming path from a reachable node or remove this node.",
            )
        )

    for node in pack_model.nodes:
        for idx, choice in enumerate(node.choices):
            if not str(choice.text or "").strip():
                errors.append(
                    _issue(
                        code="CHOICE_TEXT_EMPTY",
                        severity="error",
                        path=f"nodes[{node.node_id}].choices[{idx}].text",
                        message="Choice text must be non-empty.",
                        suggestion="Provide a clear player-facing action text.",
                    )
                )
            if not [str(tag).strip() for tag in choice.intent_tags if str(tag).strip()]:
                errors.append(
                    _issue(
                        code="CHOICE_INTENT_EMPTY",
                        severity="error",
                        path=f"nodes[{node.node_id}].choices[{idx}].intent_tags",
                        message="Choice must define at least one non-empty intent tag.",
                        suggestion="Add intent tags for free-input mapping quality.",
                    )
                )
            if not choice.range_effects:
                errors.append(
                    _issue(
                        code="CHOICE_RANGE_EFFECT_EMPTY",
                        severity="error",
                        path=f"nodes[{node.node_id}].choices[{idx}].range_effects",
                        message="Choice must define at least one range effect.",
                        suggestion="Attach at least one deterministic gameplay effect.",
                    )
                )
            if choice.next_node_id not in node_ids:
                errors.append(
                    _issue(
                        code="CHOICE_NEXT_NODE_INVALID",
                        severity="error",
                        path=f"nodes[{node.node_id}].choices[{idx}].next_node_id",
                        message=f"Choice points to missing node `{choice.next_node_id}`.",
                        suggestion="Point next_node_id to an existing node.",
                    )
                )
            if choice.ending_id is not None and choice.ending_id not in ending_ids:
                errors.append(
                    _issue(
                        code="CHOICE_ENDING_INVALID",
                        severity="error",
                        path=f"nodes[{node.node_id}].choices[{idx}].ending_id",
                        message=f"Choice references missing ending `{choice.ending_id}`.",
                        suggestion="Use an ending_id from effective ending definitions.",
                    )
                )

    for idx, fallback in enumerate(effective_fallbacks):
        if not fallback.range_effects:
            errors.append(
                _issue(
                    code="FALLBACK_RANGE_EFFECT_EMPTY",
                    severity="error",
                    path=f"effective_fallbacks[{idx}].range_effects",
                    message=f"Fallback `{fallback.fallback_id}` must define at least one range effect.",
                    suggestion="Attach deterministic range effects for fallback execution.",
                )
            )
        if fallback.target_node_id is not None and fallback.target_node_id not in node_ids:
            errors.append(
                _issue(
                    code="FALLBACK_TARGET_INVALID",
                    severity="error",
                    path=f"effective_fallbacks[{idx}].target_node_id",
                    message=f"Fallback `{fallback.fallback_id}` target node is missing.",
                    suggestion="Set target_node_id to an existing node.",
                )
            )
        if fallback.ending_id is not None and fallback.ending_id not in ending_ids:
            errors.append(
                _issue(
                    code="FALLBACK_ENDING_INVALID",
                    severity="error",
                    path=f"effective_fallbacks[{idx}].ending_id",
                    message=f"Fallback `{fallback.fallback_id}` references missing ending `{fallback.ending_id}`.",
                    suggestion="Use an ending_id from effective ending definitions.",
                )
            )

    reachable_nodes = sorted(reachable)
    sccs = _scc_components(reachable_nodes, adjacency)
    fallback_by_id = {item.fallback_id: item for item in effective_fallbacks}
    for component in sccs:
        has_cycle = len(component) > 1
        if len(component) == 1:
            node_id = next(iter(component))
            has_cycle = node_id in adjacency.get(node_id, [])
        if not has_cycle:
            continue

        has_outgoing = False
        has_ending_exit = False
        for node_id in component:
            node = node_map.get(node_id)
            if node is None:
                continue
            for nxt in adjacency.get(node_id, []):
                if nxt not in component:
                    has_outgoing = True
            for choice in node.choices:
                if choice.ending_id:
                    has_ending_exit = True
            node_fallback_id = str(node.node_fallback_id or "").strip()
            if node_fallback_id and node_fallback_id in fallback_by_id:
                if fallback_by_id[node_fallback_id].ending_id:
                    has_ending_exit = True
        label = ",".join(sorted(component))
        if not has_outgoing and not has_ending_exit:
            errors.append(
                _issue(
                    code="TRAP_LOOP",
                    severity="error",
                    path=f"graph.scc[{label}]",
                    message=f"Reachable cycle `{label}` has no exit and no ending path.",
                    suggestion="Add an outgoing edge or an ending trigger to break the trap loop.",
                )
            )
        else:
            warnings.append(
                _issue(
                    code="LOOP_WITH_EXIT",
                    severity="warning",
                    path=f"graph.scc[{label}]",
                    message=f"Cycle `{label}` is reachable but has exits.",
                    suggestion="Verify pacing and ensure players receive clear progression hints.",
                )
            )

    return errors, warnings


def validate_story_pack(pack: dict) -> list[str]:
    try:
        pack_model = StoryPackV1.model_validate(pack)
        # Ensure the merged default+override sets are valid and reachable.
        resolve_effective_story_assets(pack_model)
        return []
    except Exception as exc:  # noqa: BLE001
        return [str(exc)]


def resolve_effective_story_assets(pack: StoryPackV1) -> tuple[list[GlobalFallbackV1], list[EndingDefV1]]:
    fallbacks, endings = resolve_effective_fallbacks_endings(pack)
    return list(fallbacks), list(endings)


def _ensure_default_user(db: Session, *, user_id: str | None = None) -> User:
    if user_id:
        row = db.get(User, user_id)
        if row is None:
            raise ValueError("owner_user_id not found")
        return row

    stmt = select(User).where(User.external_ref == settings.default_user_external_ref)
    row = db.execute(stmt).scalar_one_or_none()
    if row:
        return row
    row = User(
        external_ref=settings.default_user_external_ref,
        display_name=settings.default_user_display_name,
    )
    db.add(row)
    db.flush()
    return row


def _assert_story_owner(db: Session, *, story_id: str, actor_user_id: str | None) -> Story:
    story = db.execute(select(Story).where(Story.story_id == story_id)).scalar_one_or_none()
    if story is None:
        raise ValueError("story not found")
    if actor_user_id and str(story.owner_user_id) != str(actor_user_id):
        raise PermissionError("story ownership mismatch")
    return story


def create_or_update_story_draft(
    db: Session,
    *,
    story_id: str,
    title: str,
    pack: dict,
    owner_user_id: str | None,
) -> tuple[str, int, str]:
    pack_model = StoryPackV1.model_validate(pack)
    checksum = _pack_checksum(pack)

    owner = _ensure_default_user(db, user_id=owner_user_id)
    story = db.execute(select(Story).where(Story.story_id == story_id)).scalar_one_or_none()
    if story is None:
        story = Story(story_id=story_id, owner_user_id=owner.id, title=title)
        db.add(story)
        db.flush()

    latest_version = db.execute(
        select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version.desc())
    ).scalars().first()
    next_version = 1 if latest_version is None else int(latest_version.version) + 1

    story_version = StoryVersion(
        story_id=story_id,
        version=next_version,
        status="draft",
        pack_json=pack,
        pack_schema_version=str(pack_model.schema_version),
        checksum=checksum,
        created_by=owner.id,
    )
    db.add(story_version)
    story.updated_at = utc_now_naive()
    db.flush()

    return story_id, next_version, "draft"


def publish_story_version(
    db: Session,
    *,
    story_id: str,
    version: int,
    actor_user_id: str | None = None,
) -> tuple[str, int, str]:
    _assert_story_owner(db, story_id=story_id, actor_user_id=actor_user_id)
    target = db.execute(
        select(StoryVersion).where(
            StoryVersion.story_id == story_id,
            StoryVersion.version == version,
        )
    ).scalar_one_or_none()
    if target is None:
        raise ValueError("story version not found")

    all_versions = db.execute(select(StoryVersion).where(StoryVersion.story_id == story_id)).scalars().all()
    for row in all_versions:
        if row.version == version:
            row.status = "published"
            row.published_at = utc_now_naive()
        elif row.status == "published":
            row.status = "archived"

    story = db.execute(select(Story).where(Story.story_id == story_id)).scalar_one_or_none()
    if story is None:
        raise ValueError("story not found")
    story.active_published_version = version
    story.updated_at = utc_now_naive()
    db.flush()
    return story_id, version, "published"


def get_published_story_pack(db: Session, *, story_id: str) -> tuple[int, dict]:
    story = db.execute(select(Story).where(Story.story_id == story_id)).scalar_one_or_none()
    if story is None or story.active_published_version is None:
        raise ValueError("published story not found")

    version = int(story.active_published_version)
    row = db.execute(
        select(StoryVersion).where(
            StoryVersion.story_id == story_id,
            StoryVersion.version == version,
            StoryVersion.status == "published",
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("published story version not found")

    return version, dict(row.pack_json)


def list_published_story_catalog(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            Story.story_id.label("story_id"),
            Story.title.label("title"),
            Story.active_published_version.label("published_version"),
            Story.updated_at.label("updated_at"),
        )
        .join(
            StoryVersion,
            (StoryVersion.story_id == Story.story_id)
            & (StoryVersion.version == Story.active_published_version)
            & (StoryVersion.status == "published"),
        )
        .where(Story.active_published_version.is_not(None))
        .order_by(Story.updated_at.desc(), Story.story_id.asc())
    ).all()

    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "story_id": str(row.story_id),
                "title": str(row.title),
                "published_version": int(row.published_version),
                "updated_at": row.updated_at,
            }
        )
    return out


def get_story_pack(db: Session, *, story_id: str, version: int | None) -> tuple[int, dict]:
    if version is not None:
        row = db.execute(
            select(StoryVersion).where(
                StoryVersion.story_id == story_id,
                StoryVersion.version == version,
                StoryVersion.status.in_(["published", "draft"]),
            )
        ).scalar_one_or_none()
        if row is None:
            raise ValueError("story version not found")
        return int(row.version), dict(row.pack_json)

    return get_published_story_pack(db, story_id=story_id)


def list_story_versions(
    db: Session,
    *,
    story_id: str,
    actor_user_id: str | None = None,
) -> list[StoryVersion]:
    _assert_story_owner(db, story_id=story_id, actor_user_id=actor_user_id)
    rows = (
        db.execute(select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version.desc()))
        .scalars()
        .all()
    )
    return list(rows)


def get_story_version_detail(
    db: Session,
    *,
    story_id: str,
    version: int,
    actor_user_id: str | None = None,
) -> StoryVersion:
    _assert_story_owner(db, story_id=story_id, actor_user_id=actor_user_id)
    row = db.execute(
        select(StoryVersion).where(
            StoryVersion.story_id == story_id,
            StoryVersion.version == version,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("story version not found")
    return row


def create_story_draft_from_published(
    db: Session,
    *,
    story_id: str,
    title: str | None = None,
    actor_user_id: str | None = None,
) -> tuple[str, int, str]:
    story = _assert_story_owner(db, story_id=story_id, actor_user_id=actor_user_id)
    if story.active_published_version is None:
        raise ValueError("published story not found")

    source = db.execute(
        select(StoryVersion).where(
            StoryVersion.story_id == story_id,
            StoryVersion.version == int(story.active_published_version),
            StoryVersion.status == "published",
        )
    ).scalar_one_or_none()
    if source is None:
        raise ValueError("published story version not found")

    owner = _ensure_default_user(db, user_id=story.owner_user_id)
    latest = db.execute(
        select(StoryVersion).where(StoryVersion.story_id == story_id).order_by(StoryVersion.version.desc())
    ).scalars().first()
    next_version = 1 if latest is None else int(latest.version) + 1
    pack = dict(source.pack_json)
    pack_model = StoryPackV1.model_validate(pack)
    checksum = _pack_checksum(pack)

    row = StoryVersion(
        story_id=story_id,
        version=next_version,
        status="draft",
        pack_json=pack,
        pack_schema_version=str(pack_model.schema_version),
        checksum=checksum,
        created_by=owner.id,
    )
    db.add(row)
    if title is not None and str(title).strip():
        story.title = str(title).strip()
    story.updated_at = utc_now_naive()
    db.flush()
    return story_id, next_version, "draft"


def update_story_draft_version(
    db: Session,
    *,
    story_id: str,
    version: int,
    pack: dict,
    title: str | None = None,
    actor_user_id: str | None = None,
) -> tuple[str, int, str]:
    story = _assert_story_owner(db, story_id=story_id, actor_user_id=actor_user_id)
    row = db.execute(
        select(StoryVersion).where(
            StoryVersion.story_id == story_id,
            StoryVersion.version == version,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("story version not found")
    if row.status != "draft":
        raise RuntimeError("only draft version can be updated")

    pack_model = StoryPackV1.model_validate(pack)
    row.pack_json = pack
    row.pack_schema_version = str(pack_model.schema_version)
    row.checksum = _pack_checksum(pack)
    if title is not None and str(title).strip():
        story.title = str(title).strip()
    story.updated_at = utc_now_naive()
    db.flush()
    return story_id, version, "draft"
