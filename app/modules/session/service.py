import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    ActionLog,
    Character,
    LLMUsageLog,
    Session as StorySession,
    SessionStepIdempotency,
    SessionCharacterState,
    SessionSnapshot,
    Story,
)
from app.modules.llm.adapter import LLMUnavailableError, get_llm_runtime
from app.modules.narrative.ending_engine import resolve_run_ending
from app.modules.narrative.event_engine import advance_runtime_events
from app.modules.narrative.quest_engine import advance_quest_state, init_quest_state, summarize_quest_for_narration
from app.modules.narrative.state_engine import default_initial_state, normalize_run_state, normalize_state
from app.modules.replay.engine import ReplayEngine, upsert_replay_report
from app.modules.session import debug_views, idempotency, runtime_pack, fallback as runtime_fallback, selection
from app.modules.session.schemas import ChoiceOut, SessionStateOut
from app.modules.session.story_choice_gating import evaluate_choice_availability
from app.modules.session.story_runtime.models import SelectionResult
from app.modules.session.story_runtime.pipeline import StoryRuntimePipelineDeps, run_story_runtime_pipeline

replay_engine = ReplayEngine()
_STORY_FALLBACK_BUILTIN_TEXT = "[fallback] The scene advances quietly. Choose the next move."


def _get_or_create_default_character(db: Session) -> Character:
    char = db.execute(select(Character).where(Character.name == "Default Heroine")).scalar_one_or_none()
    if char:
        return char
    char = Character(
        name="Default Heroine",
        base_personality={"kind": 0.7},
        initial_relation_vector={"trust": 0.5, "respect": 0.5, "fear": 0.1, "attraction": 0.2},
        initial_visible_score=50,
    )
    db.add(char)
    db.flush()
    return char


def _require_session(db: Session, session_id: uuid.UUID) -> StorySession:
    sess = db.get(StorySession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


def _resolve_story_node_id(sess: StorySession) -> str | None:
    story_node_id = str(sess.story_node_id or "").strip()
    return story_node_id or None


def _serialize_state(db: Session, sess: StorySession) -> SessionStateOut:
    char_states = db.execute(
        select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
    ).scalars().all()

    normalized_state = normalize_state(sess.state_json)
    story_node_id = _resolve_story_node_id(sess)
    current_node = None
    if sess.story_id and story_node_id:
        if sess.story_version is not None:
            story_row = db.execute(
                select(Story).where(
                    Story.story_id == sess.story_id,
                    Story.version == sess.story_version,
                )
            ).scalar_one_or_none()
        else:
            story_row = db.execute(
                select(Story)
                .where(Story.story_id == sess.story_id, Story.is_published.is_(True))
                .order_by(Story.version.desc())
            ).scalars().first()
        if story_row is not None:
            runtime_pack = normalize_pack_for_runtime(story_row.pack_json or {})
            node = _story_node(runtime_pack, story_node_id)
            if node:
                response_choices = _story_choices_for_response(node, normalized_state)
                scene_text = str(node.get("scene_brief") or "").strip() or "(no current node narrative)"
                current_node = {
                    "id": story_node_id,
                    "parent_node_id": None,
                    "narrative_text": scene_text,
                    "choices": [ChoiceOut(**c) for c in response_choices],
                    "created_at": sess.updated_at,
                }

    return SessionStateOut(
        id=sess.id,
        status=sess.status,
        current_node_id=story_node_id,
        story_id=sess.story_id,
        story_version=sess.story_version,
        global_flags=sess.global_flags,
        active_characters=sess.active_characters,
        state_json=normalized_state,
        memory_summary=sess.memory_summary,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        character_states=[
            {
                "id": cs.id,
                "character_id": cs.character_id,
                "score_visible": cs.score_visible,
                "relation_vector": cs.relation_vector,
                "personality_drift": cs.personality_drift,
                "updated_at": cs.updated_at,
            }
            for cs in char_states
        ],
        current_node=current_node,
    )


def _load_story_pack(db: Session, story_id: str, version: int | None = None) -> Story:
    if version is not None:
        row = db.execute(select(Story).where(Story.story_id == story_id, Story.version == version)).scalar_one_or_none()
    else:
        row = db.execute(
            select(Story)
            .where(Story.story_id == story_id, Story.is_published.is_(True))
            .order_by(Story.version.desc())
        ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "STORY_NOT_FOUND"})
    return row


def _story_node(pack: dict, node_id: str) -> dict | None:
    return runtime_pack.story_node(pack, node_id)


def normalize_pack_for_runtime(pack_json: dict | None) -> dict:
    return runtime_pack.normalize_pack_for_runtime(pack_json)


def _resolve_runtime_fallback(node: dict, current_node_id: str, node_ids: set[str]) -> tuple[dict, str, list[str]]:
    return runtime_fallback.resolve_runtime_fallback(node, current_node_id, node_ids)


def _fallback_executed_choice_id(fallback: dict, current_node_id: str) -> str:
    return runtime_fallback.fallback_executed_choice_id(fallback, current_node_id)


def _select_fallback_text_variant(
    fallback: dict,
    reason_code: str | None,
    locale: str | None = None,
) -> str | None:
    return runtime_fallback.select_fallback_text_variant(fallback, reason_code, locale)


def _select_story_choice(
    *,
    db: Session,
    sess: StorySession,
    player_input: str,
    visible_choices: list[dict],
    intents: list[dict] | None,
    current_story_state: dict,
) -> SelectionResult:
    return selection.select_story_choice(
        db=db,
        sess=sess,
        player_input=player_input,
        visible_choices=visible_choices,
        intents=intents,
        current_story_state=current_story_state,
        llm_runtime_getter=get_llm_runtime,
    )


def _story_choices_for_response(node: dict, state_json: dict | None) -> list[dict]:
    out = []
    state = normalize_state(state_json)
    for choice in (node.get("choices") or []):
        action_id = ((choice.get("action") or {}).get("action_id") or "action")
        is_available, unavailable_reason = evaluate_choice_availability(choice, state)
        item = {
            "id": str(choice.get("choice_id")),
            "text": str(choice.get("display_text", "")),
            "type": str(action_id),
            "is_available": bool(is_available),
        }
        if not is_available and unavailable_reason:
            item["unavailable_reason"] = unavailable_reason
        out.append(item)
    return out


def _apply_choice_effects(state: dict, effects: dict | None) -> dict:
    if not effects:
        return normalize_state(state)
    out = dict(state)
    for key in ("energy", "money", "knowledge", "affection"):
        if key in effects and effects.get(key) is not None:
            out[key] = int(out.get(key, 0)) + int(effects.get(key) or 0)
    return normalize_state(out)


def _compute_state_delta(before: dict, after: dict) -> dict:
    delta: dict = {}
    for key, before_value in before.items():
        after_value = after.get(key)
        if before_value == after_value:
            continue
        if isinstance(before_value, int) and isinstance(after_value, int):
            delta[key] = after_value - before_value
        else:
            delta[key] = after_value
    return delta


def _format_effects_suffix(effects: dict | None) -> str:
    if not isinstance(effects, dict):
        return ""
    parts: list[str] = []
    for key in sorted(effects.keys(), key=lambda item: str(item)):
        value = effects.get(key)
        if value is None:
            continue
        try:
            numeric = int(value)
        except Exception:  # noqa: BLE001
            continue
        if numeric == 0:
            continue
        sign = "+" if numeric > 0 else ""
        parts.append(f"{key} {sign}{numeric}")
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def create_session(db: Session, story_id: str, version: int | None = None) -> StorySession:
    with db.begin():
        story_id_text = str(story_id or "").strip()
        if not story_id_text:
            raise HTTPException(status_code=400, detail={"code": "STORY_REQUIRED"})
        char = _get_or_create_default_character(db)
        story_row = _load_story_pack(db, story_id_text, version)
        runtime_pack = normalize_pack_for_runtime(story_row.pack_json or {})
        start_node_id = str(runtime_pack.get("start_node_id") or "").strip()
        if not start_node_id or _story_node(runtime_pack, start_node_id) is None:
            raise HTTPException(status_code=400, detail={"code": "INVALID_STORY_START_NODE"})

        initial_state = default_initial_state()
        initial_state["quest_state"] = init_quest_state(runtime_pack.get("quests") or [])
        initial_state["run_state"] = normalize_run_state(None)

        sess = StorySession(
            status="active",
            story_node_id=start_node_id,
            global_flags={},
            active_characters=[str(char.id)],
            state_json=normalize_state(initial_state),
            memory_summary="",
            story_id=story_row.story_id,
            story_version=story_row.version,
        )
        db.add(sess)
        db.flush()

        scs = SessionCharacterState(
            session_id=sess.id,
            character_id=char.id,
            score_visible=char.initial_visible_score,
            relation_vector=char.initial_relation_vector,
            personality_drift={},
        )
        db.add(scs)
    db.refresh(sess)
    return sess


def get_session_state(db: Session, session_id: uuid.UUID) -> SessionStateOut:
    sess = _require_session(db, session_id)
    return _serialize_state(db, sess)


def get_llm_trace(db: Session, session_id: uuid.UUID, limit: int = 50) -> dict:
    return debug_views.get_llm_trace(db, session_id, limit=limit)


def get_layer_inspector(db: Session, session_id: uuid.UUID, limit: int = 20) -> dict:
    return debug_views.get_layer_inspector(db, session_id, limit=limit)


def _sum_step_tokens(db: Session, session_id: uuid.UUID, step_id: uuid.UUID) -> tuple[int, int]:
    prompt_tokens = (
        db.execute(
            select(func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0)).where(
                LLMUsageLog.session_id == session_id,
                LLMUsageLog.step_id == step_id,
            )
        ).scalar_one()
        or 0
    )
    completion_tokens = (
        db.execute(
            select(func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0)).where(
                LLMUsageLog.session_id == session_id,
                LLMUsageLog.step_id == step_id,
            )
        ).scalar_one()
        or 0
    )
    return int(prompt_tokens), int(completion_tokens)


def _sum_step_usage(db: Session, session_id: uuid.UUID, step_id: uuid.UUID) -> tuple[int, int]:
    return _sum_step_tokens(db, session_id, step_id)


def _step_provider(db: Session, session_id: uuid.UUID, step_id: uuid.UUID) -> str:
    latest_usage = db.execute(
        select(LLMUsageLog)
        .where(
            LLMUsageLog.session_id == session_id,
            LLMUsageLog.step_id == step_id,
            LLMUsageLog.operation == "generate",
            LLMUsageLog.status == "success",
        )
        .order_by(LLMUsageLog.created_at.desc())
    ).scalars().first()
    return latest_usage.provider if latest_usage else "none"


def _run_story_runtime_pipeline(
    *,
    db: Session,
    sess: StorySession,
    choice_id: str | None,
    player_input: str | None,
) -> dict:
    def _bound_select_story_choice(
        *,
        player_input: str,
        visible_choices: list[dict],
        intents: list[dict] | None,
        current_story_state: dict,
    ) -> SelectionResult:
        return _select_story_choice(
            db=db,
            sess=sess,
            player_input=player_input,
            visible_choices=visible_choices,
            intents=intents,
            current_story_state=current_story_state,
        )

    deps = StoryRuntimePipelineDeps(
        load_story_pack=_load_story_pack,
        normalize_pack_for_runtime=normalize_pack_for_runtime,
        story_node=_story_node,
        resolve_runtime_fallback=_resolve_runtime_fallback,
        select_story_choice=_bound_select_story_choice,
        fallback_executed_choice_id=_fallback_executed_choice_id,
        select_fallback_text_variant=_select_fallback_text_variant,
        sum_step_usage=_sum_step_usage,
        step_provider=_step_provider,
        apply_choice_effects=_apply_choice_effects,
        compute_state_delta=_compute_state_delta,
        format_effects_suffix=_format_effects_suffix,
        story_choices_for_response=_story_choices_for_response,
        advance_quest_state=advance_quest_state,
        advance_runtime_events=advance_runtime_events,
        resolve_run_ending=resolve_run_ending,
        summarize_quest_for_narration=summarize_quest_for_narration,
        llm_runtime_getter=get_llm_runtime,
    )
    try:
        return run_story_runtime_pipeline(
            db=db,
            sess=sess,
            choice_id=choice_id,
            player_input=player_input,
            fallback_builtin_text=_STORY_FALLBACK_BUILTIN_TEXT,
            deps=deps,
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "LLM_UNAVAILABLE", "message": str(exc)}) from exc


def _normalized_optional_text(value: str | None) -> str | None:
    return idempotency.normalized_optional_text(value)


def _normalized_optional_idempotency_key(value: str | None) -> str | None:
    return idempotency.normalized_optional_idempotency_key(value)


def _request_hash(*, choice_id: str | None, player_input: str | None) -> str:
    return idempotency.request_hash(choice_id=choice_id, player_input=player_input)


def _safe_response_payload(payload: dict) -> dict:
    return idempotency.safe_response_payload(payload)


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    return idempotency.as_utc_datetime(value)


def _idempotency_expiry(now: datetime | None = None) -> datetime:
    return idempotency.idempotency_expiry(now)


def _is_stale_in_progress(row: SessionStepIdempotency, now: datetime | None = None) -> bool:
    return idempotency.is_stale_in_progress(row, now)


def _extract_http_error_code(exc: HTTPException) -> str:
    return idempotency.extract_http_error_code(exc)


def _extract_http_error_message(exc: HTTPException) -> str | None:
    return idempotency.extract_http_error_message(exc)


def _require_step_preconditions(sess: StorySession) -> None:
    if sess.status != "active":
        raise HTTPException(status_code=409, detail={"code": "SESSION_NOT_ACTIVE"})
    if not sess.story_id:
        raise HTTPException(status_code=400, detail={"code": "STORY_REQUIRED"})


def _persist_idempotency_failed(
    db: Session,
    *,
    session_id: uuid.UUID,
    idempotency_key: str,
    request_hash: str,
    error_code: str,
    error_message: str | None = None,
) -> None:
    idempotency.persist_idempotency_failed(
        db,
        session_id=session_id,
        idempotency_key=idempotency_key,
        request_hash_value=request_hash,
        error_code=error_code,
        error_message=error_message,
    )


def step_session(
    db: Session,
    session_id: uuid.UUID,
    choice_id: str | None,
    player_input: str | None = None,
    idempotency_key: str | None = None,
):
    normalized_choice_id = _normalized_optional_text(choice_id)
    normalized_player_input = _normalized_optional_text(player_input)
    normalized_idempotency_key = _normalized_optional_idempotency_key(idempotency_key)
    if normalized_choice_id and normalized_player_input:
        raise HTTPException(
            status_code=422,
            detail={"code": "INPUT_CONFLICT", "message": "Provide exactly one of choice_id or player_input."},
        )

    if not normalized_idempotency_key:
        with db.begin():
            sess = _require_session(db, session_id)
            _require_step_preconditions(sess)
            return _run_story_runtime_pipeline(
                db=db,
                sess=sess,
                choice_id=normalized_choice_id,
                player_input=normalized_player_input,
            )

    request_hash = _request_hash(choice_id=normalized_choice_id, player_input=normalized_player_input)

    replay_payload: dict | None = None
    execution_started = False
    try:
        phase1_done = False
        for _ in range(2):
            try:
                with db.begin():
                    sess = _require_session(db, session_id)
                    row = db.execute(
                        select(SessionStepIdempotency).where(
                            SessionStepIdempotency.session_id == session_id,
                            SessionStepIdempotency.idempotency_key == normalized_idempotency_key,
                        )
                    ).scalar_one_or_none()

                    now = datetime.now(timezone.utc)
                    expiry = _idempotency_expiry(now)

                    if row is None:
                        row = SessionStepIdempotency(
                            session_id=session_id,
                            idempotency_key=normalized_idempotency_key,
                            request_hash=request_hash,
                            status=idempotency.IDEMPOTENCY_STATUS_IN_PROGRESS,
                            response_json=None,
                            error_code=None,
                            created_at=now,
                            updated_at=now,
                            expires_at=expiry,
                        )
                        db.add(row)
                        db.flush()
                    elif row.request_hash != request_hash:
                        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED"})
                    elif row.status == idempotency.IDEMPOTENCY_STATUS_SUCCEEDED and isinstance(row.response_json, dict):
                        replay_payload = dict(row.response_json)
                    elif row.status == idempotency.IDEMPOTENCY_STATUS_IN_PROGRESS and not _is_stale_in_progress(row, now):
                        raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS"})
                    else:
                        row.status = idempotency.IDEMPOTENCY_STATUS_IN_PROGRESS
                        row.error_code = None
                        row.updated_at = now
                        row.expires_at = expiry
                phase1_done = True
                break
            except IntegrityError:
                db.rollback()
                continue

        if not phase1_done:
            raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS"})

        if replay_payload is not None:
            return replay_payload

        execution_started = True
        with db.begin():
            sess = _require_session(db, session_id)
            _require_step_preconditions(sess)
            response_payload = _run_story_runtime_pipeline(
                db=db,
                sess=sess,
                choice_id=normalized_choice_id,
                player_input=normalized_player_input,
            )
            safe_payload = _safe_response_payload(response_payload)
            row = db.execute(
                select(SessionStepIdempotency).where(
                    SessionStepIdempotency.session_id == session_id,
                    SessionStepIdempotency.idempotency_key == normalized_idempotency_key,
                )
            ).scalar_one_or_none()
            if row is not None and row.request_hash == request_hash:
                now = datetime.now(timezone.utc)
                row.status = idempotency.IDEMPOTENCY_STATUS_SUCCEEDED
                row.response_json = safe_payload
                row.error_code = None
                row.updated_at = now
                row.expires_at = _idempotency_expiry(now)
            return safe_payload
    except HTTPException as exc:
        if execution_started:
            _persist_idempotency_failed(
                db,
                session_id=session_id,
                idempotency_key=normalized_idempotency_key,
                request_hash=request_hash,
                error_code=_extract_http_error_code(exc),
                error_message=_extract_http_error_message(exc),
            )
        raise
    except Exception:
        if execution_started:
            _persist_idempotency_failed(
                db,
                session_id=session_id,
                idempotency_key=normalized_idempotency_key,
                request_hash=request_hash,
                error_code="INTERNAL_ERROR",
            )
        raise


def create_snapshot(db: Session, session_id: uuid.UUID) -> SessionSnapshot:
    with db.begin():
        sess = _require_session(db, session_id)
        cutoff = datetime.now(timezone.utc)
        char_states = db.execute(
            select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
        ).scalars().all()

        action_log_ids = [str(v) for v in db.execute(select(ActionLog.id).where(ActionLog.session_id == sess.id)).scalars().all()]

        payload = {
            "session": {
                "id": str(sess.id),
                "status": sess.status,
                "story_node_id": _resolve_story_node_id(sess),
                "global_flags": sess.global_flags,
                "active_characters": sess.active_characters,
                "state_json": normalize_state(sess.state_json),
                "memory_summary": sess.memory_summary,
            },
            "character_states": [
                {
                    "id": str(cs.id),
                    "character_id": str(cs.character_id),
                    "score_visible": cs.score_visible,
                    "relation_vector": cs.relation_vector,
                    "personality_drift": cs.personality_drift,
                    "updated_at": cs.updated_at.isoformat(),
                }
                for cs in char_states
            ],
            "cutoff_ts": cutoff.isoformat(),
            "action_log_ids": action_log_ids,
        }

        snapshot = SessionSnapshot(session_id=sess.id, snapshot_name="manual", state_blob=payload, created_at=cutoff)
        db.add(snapshot)
        db.flush()
    db.refresh(snapshot)
    return snapshot


def rollback_to_snapshot(db: Session, session_id: uuid.UUID, snapshot_id: uuid.UUID) -> StorySession:
    with db.begin():
        sess = _require_session(db, session_id)
        snapshot = db.get(SessionSnapshot, snapshot_id)
        if not snapshot or snapshot.session_id != sess.id:
            raise HTTPException(status_code=404, detail="snapshot not found")

        payload = snapshot.state_blob
        s = payload["session"]
        sess.status = s["status"]
        sess.story_node_id = str(s.get("story_node_id") or "").strip() or None
        sess.global_flags = s["global_flags"]
        sess.active_characters = s["active_characters"]
        sess.state_json = normalize_state(s.get("state_json"))
        sess.memory_summary = s["memory_summary"]
        sess.updated_at = datetime.now(timezone.utc)

        db.execute(delete(SessionCharacterState).where(SessionCharacterState.session_id == sess.id))
        for cs in payload["character_states"]:
            db.add(
                SessionCharacterState(
                    id=uuid.UUID(cs["id"]),
                    session_id=sess.id,
                    character_id=uuid.UUID(cs["character_id"]),
                    score_visible=cs["score_visible"],
                    relation_vector=cs["relation_vector"],
                    personality_drift=cs["personality_drift"],
                    updated_at=datetime.fromisoformat(cs["updated_at"]),
                )
            )

        keep_action_log_ids = [uuid.UUID(v) for v in payload.get("action_log_ids", [])]

        action_delete = delete(ActionLog).where(ActionLog.session_id == sess.id)
        if keep_action_log_ids:
            action_delete = action_delete.where(ActionLog.id.not_in(keep_action_log_ids))
        db.execute(action_delete)

    return sess


def end_session(db: Session, session_id: uuid.UUID) -> dict:
    with db.begin():
        sess = _require_session(db, session_id)
        sess.status = "ended"
        sess.updated_at = datetime.now(timezone.utc)

        report = replay_engine.build_report(session_id=sess.id, db=db)
        replay_row = upsert_replay_report(db, session_id=sess.id, report=report)
        db.flush()

    return {
        "ended": True,
        "replay_report_id": str(replay_row.id),
    }


def get_replay(db: Session, session_id: uuid.UUID) -> dict:
    _require_session(db, session_id)
    from app.db.models import ReplayReport

    row = db.execute(select(ReplayReport).where(ReplayReport.session_id == session_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "REPLAY_NOT_READY"})
    return row.report_json
