from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import ActionLog, Session as GameSession
from app.modules.debug.schemas import (
    DebugBundleIncludeFlagsOut,
    DebugSessionBundleOut,
    DebugSessionListResponse,
    DebugSessionOverviewOut,
    DebugSessionSummaryOut,
    DebugStepDetailOut,
    DebugStepSummaryOut,
    DebugTimelineResponse,
    RuntimeTelemetrySummaryOut,
)
from app.modules.runtime.service import RuntimeNotFoundError, get_session_state
from app.modules.story_domain.schemas import StoryVersionSummary
from app.modules.story_domain.service import list_story_versions
from app.modules.telemetry.service import get_runtime_telemetry_summary


def _safe_run_state(state_json: object) -> dict:
    if isinstance(state_json, dict):
        run_state = state_json.get("run_state")
        if isinstance(run_state, dict):
            return dict(run_state)
    return {}


def _safe_dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _session_exists(db: Session, *, session_id: str) -> None:
    if db.get(GameSession, session_id) is None:
        raise RuntimeNotFoundError("session not found")


def _latest_selection_by_session_ids(db: Session, *, session_ids: list[str]) -> dict[str, dict]:
    if not session_ids:
        return {}

    latest_subq = (
        select(
            ActionLog.session_id.label("sid"),
            func.max(ActionLog.step_index).label("max_step_index"),
        )
        .where(ActionLog.session_id.in_(session_ids))
        .group_by(ActionLog.session_id)
        .subquery()
    )

    rows = db.execute(
        select(
            ActionLog.session_id,
            ActionLog.step_index,
            ActionLog.selection_result_json,
        ).join(
            latest_subq,
            and_(
                ActionLog.session_id == latest_subq.c.sid,
                ActionLog.step_index == latest_subq.c.max_step_index,
            ),
        )
    ).all()

    latest: dict[str, dict] = {}
    for session_id, step_index, selection_result in rows:
        payload = _safe_dict(selection_result)
        payload.setdefault("step_index", int(step_index or 0))
        latest[str(session_id)] = payload
    return latest


def _to_version_summary(row) -> StoryVersionSummary:
    return StoryVersionSummary(
        story_id=row.story_id,
        version=int(row.version),
        status=str(row.status),
        checksum=str(row.checksum),
        created_by=str(row.created_by),
        created_at=row.created_at,
        published_at=row.published_at,
    )


def _to_step_summary(row: ActionLog) -> DebugStepSummaryOut:
    selection = _safe_dict(row.selection_result_json)
    state_after = _safe_dict(row.state_after)
    run_state = _safe_run_state(state_after)

    run_ended = bool(selection.get("run_ended", run_state.get("run_ended", False)))
    ending_id = selection.get("ending_id") or run_state.get("ending_id")

    return DebugStepSummaryOut(
        step_index=int(row.step_index),
        created_at=row.created_at,
        attempted_choice_id=(str(selection.get("attempted_choice_id")) if selection.get("attempted_choice_id") else None),
        executed_choice_id=str(selection.get("executed_choice_id") or "unknown"),
        fallback_used=bool(selection.get("fallback_used", False)),
        fallback_reason=(str(selection.get("fallback_reason")) if selection.get("fallback_reason") else None),
        selection_source=(str(selection.get("selection_source")) if selection.get("selection_source") else None),
        run_ended=run_ended,
        ending_id=(str(ending_id) if ending_id else None),
    )


def _to_step_detail(row: ActionLog) -> DebugStepDetailOut:
    return DebugStepDetailOut(
        session_id=row.session_id,
        step_index=int(row.step_index),
        created_at=row.created_at,
        request_payload_json=_safe_dict(row.request_payload_json),
        selection_result_json=_safe_dict(row.selection_result_json),
        state_before=_safe_dict(row.state_before),
        state_delta=_safe_dict(row.state_delta),
        state_after=_safe_dict(row.state_after),
        llm_trace_json=_safe_dict(row.llm_trace_json),
        classification_json=_safe_dict(row.classification_json),
    )


def list_debug_sessions(
    db: Session,
    *,
    story_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> DebugSessionListResponse:
    stmt = select(GameSession)
    if story_id:
        stmt = stmt.where(GameSession.story_id == story_id)
    if status:
        stmt = stmt.where(GameSession.status == status)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.execute(total_stmt).scalar_one() or 0)

    rows = (
        db.execute(stmt.order_by(GameSession.updated_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )

    session_ids = [str(row.id) for row in rows]
    latest_map = _latest_selection_by_session_ids(db, session_ids=session_ids)

    sessions: list[DebugSessionSummaryOut] = []
    for row in rows:
        run_state = _safe_run_state(row.state_json)
        last_selection = latest_map.get(str(row.id), {})

        sessions.append(
            DebugSessionSummaryOut(
                session_id=row.id,
                story_id=row.story_id,
                story_version=int(row.story_version),
                status=row.status,
                story_node_id=row.story_node_id,
                step_index=int(run_state.get("step_index", 0) or 0),
                fallback_count=int(run_state.get("fallback_count", 0) or 0),
                run_ended=bool(run_state.get("run_ended", False)),
                last_step_index=(int(last_selection.get("step_index", 0) or 0) if last_selection else None),
                last_executed_choice_id=(
                    str(last_selection.get("executed_choice_id")) if last_selection.get("executed_choice_id") else None
                ),
                last_fallback_reason=(
                    str(last_selection.get("fallback_reason")) if last_selection.get("fallback_reason") else None
                ),
                last_selection_source=(
                    str(last_selection.get("selection_source")) if last_selection.get("selection_source") else None
                ),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    return DebugSessionListResponse(total=total, limit=limit, offset=offset, sessions=sessions)


def get_debug_session_overview(db: Session, *, session_id: str) -> DebugSessionOverviewOut:
    state = get_session_state(db, session_id=session_id)
    run_state = _safe_run_state(state.state_json)
    return DebugSessionOverviewOut(
        session_id=state.session_id,
        story_id=state.story_id,
        story_version=state.story_version,
        status=state.status,
        story_node_id=state.story_node_id,
        state_json=state.state_json,
        run_state=run_state,
        current_node=state.current_node,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


def get_debug_timeline(
    db: Session,
    *,
    session_id: str,
    limit: int,
    offset: int,
) -> DebugTimelineResponse:
    _session_exists(db, session_id=session_id)

    total = int(
        db.execute(select(func.count()).select_from(ActionLog).where(ActionLog.session_id == session_id)).scalar_one() or 0
    )

    rows = (
        db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == session_id)
            .order_by(ActionLog.step_index.asc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    steps = [_to_step_summary(row) for row in rows]
    return DebugTimelineResponse(session_id=session_id, total=total, limit=limit, offset=offset, steps=steps)


def get_debug_step_detail(db: Session, *, session_id: str, step_index: int) -> DebugStepDetailOut:
    row = db.execute(
        select(ActionLog).where(ActionLog.session_id == session_id, ActionLog.step_index == step_index)
    ).scalar_one_or_none()
    if row is None:
        raise RuntimeNotFoundError("session step not found")

    return _to_step_detail(row)


def get_debug_latest_step_detail(db: Session, *, session_id: str) -> DebugStepDetailOut | None:
    _session_exists(db, session_id=session_id)

    row = (
        db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == session_id)
            .order_by(ActionLog.step_index.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    return _to_step_detail(row)


def get_debug_session_bundle(
    db: Session,
    *,
    session_id: str,
    timeline_limit: int,
    timeline_offset: int,
    include_flags: DebugBundleIncludeFlagsOut,
    actor_user_id: str | None,
) -> DebugSessionBundleOut:
    overview = get_debug_session_overview(db, session_id=session_id)
    timeline = get_debug_timeline(db, session_id=session_id, limit=timeline_limit, offset=timeline_offset)

    telemetry = None
    if include_flags.telemetry:
        telemetry = RuntimeTelemetrySummaryOut.model_validate(get_runtime_telemetry_summary())

    versions: list[StoryVersionSummary] = []
    if include_flags.versions:
        version_rows = list_story_versions(db, story_id=overview.story_id, actor_user_id=actor_user_id)
        versions = [_to_version_summary(row) for row in version_rows]

    latest_step_detail = None
    if include_flags.latest_step_detail:
        latest_step_detail = get_debug_latest_step_detail(db, session_id=session_id)

    return DebugSessionBundleOut(
        session_id=session_id,
        include=include_flags,
        overview=overview,
        timeline=timeline,
        telemetry=telemetry,
        versions=versions,
        latest_step_detail=latest_step_detail,
    )
