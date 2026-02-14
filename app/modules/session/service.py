import re
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    ActionLog,
    Branch,
    Character,
    DialogueNode,
    LLMUsageLog,
    Session as StorySession,
    SessionCharacterState,
    SessionSnapshot,
    User,
)
from app.modules.affection.engine import apply_affection
from app.modules.branch.engine import build_branch_context, resolve_branch
from app.modules.llm.adapter import get_llm_runtime
from app.modules.narrative.prompt_builder import build_step_prompt
from app.modules.replay.engine import ReplayEngine, upsert_replay_report
from app.modules.session.schemas import ChoiceOut, SessionStateOut

replay_engine = ReplayEngine()


def classify_input_stub(input_text: str | None, choice_id: str | None) -> dict:
    text = (input_text or "").lower()
    tags = []

    if re.search(r"\b(thank|please|sorry|help)\b", text):
        tags.append("kind")
    if re.search(r"\b(love|date|cute|kiss)\b", text):
        tags.append("flirt")
    if re.search(r"\b(stupid|hate|kill|idiot|shut up)\b", text):
        tags.append("aggressive")
    if re.search(r"\b(respect|honor|promise)\b", text):
        tags.append("respectful")
    if re.search(r"\b(lie|cheat|fake)\b", text):
        tags.append("deceptive")

    if not tags:
        tags = ["kind"]

    intent = "neutral"
    tone = "calm"
    if "aggressive" in tags:
        intent = "hostile"
        tone = "harsh"
    elif "flirt" in tags:
        intent = "romantic"
        tone = "warm"
    elif "kind" in tags:
        intent = "friendly"

    return {"behavior_tags": sorted(set(tags)), "intent": intent, "tone": tone, "choice_id": choice_id, "risk_tags": [], "confidence": 0.6}


def _ensure_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user:
        return user
    user = User(id=user_id, google_sub=f"dev-{user_id}", email=f"{user_id}@dev.local", display_name="Dev User")
    db.add(user)
    db.flush()
    return user


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


def _require_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> StorySession:
    sess = db.get(StorySession, session_id)
    if not sess or sess.user_id != user_id:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


def _serialize_state(db: Session, sess: StorySession) -> SessionStateOut:
    char_states = db.execute(
        select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
    ).scalars().all()

    current_node = None
    if sess.current_node_id:
        node = db.get(DialogueNode, sess.current_node_id)
        if node:
            current_node = {
                "id": node.id,
                "parent_node_id": node.parent_node_id,
                "narrative_text": node.narrative_text,
                "choices": [ChoiceOut(**c) for c in (node.choices or [])],
                "created_at": node.created_at,
            }

    return SessionStateOut(
        id=sess.id,
        user_id=sess.user_id,
        status=sess.status,
        current_node_id=sess.current_node_id,
        global_flags=sess.global_flags,
        route_flags=sess.route_flags,
        active_characters=sess.active_characters,
        memory_summary=sess.memory_summary,
        token_budget_used=sess.token_budget_used,
        token_budget_remaining=sess.token_budget_remaining,
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


def create_session(db: Session, user_id: uuid.UUID) -> StorySession:
    with db.begin():
        _ensure_user(db, user_id)
        char = _get_or_create_default_character(db)
        sess = StorySession(
            user_id=user_id,
            status="active",
            current_node_id=None,
            global_flags={},
            route_flags={},
            active_characters=[str(char.id)],
            memory_summary="",
            token_budget_used=0,
            token_budget_remaining=settings.session_token_budget_total,
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


def get_session_state(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> SessionStateOut:
    sess = _require_session(db, session_id, user_id)
    return _serialize_state(db, sess)


def _preflight_required_budget(input_text: str | None) -> int:
    conservative_cost = 20 + (len(input_text or "") // 4)
    return (
        conservative_cost
        + settings.llm_preflight_classify_max_tokens
        + settings.llm_preflight_generate_prompt_max_tokens
        + settings.llm_preflight_generate_completion_max_tokens
    )


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


def step_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID, input_text: str | None, choice_id: str | None):
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        if sess.status != "active":
            raise HTTPException(status_code=409, detail={"code": "SESSION_NOT_ACTIVE"})

        conservative_cost = 20 + (len(input_text or "") // 4)
        preflight_required_budget = _preflight_required_budget(input_text)
        if preflight_required_budget > sess.token_budget_remaining or sess.token_budget_remaining <= 0:
            raise HTTPException(status_code=409, detail={"code": "TOKEN_BUDGET_EXCEEDED"})

        step_id = uuid.uuid4()
        llm_runtime = get_llm_runtime()

        llm_classification, classify_ok = llm_runtime.classify_with_fallback(db, text=input_text or "", session_id=sess.id, step_id=step_id)
        if classify_ok:
            cls = llm_classification.model_dump()
        else:
            cls = classify_input_stub(input_text, choice_id)

        char_states = db.execute(
            select(SessionCharacterState)
            .where(SessionCharacterState.session_id == sess.id)
            .order_by(SessionCharacterState.character_id.asc())
        ).scalars().all()

        affection_delta = []
        rule_hits_all = []
        for cs in char_states:
            result = apply_affection(
                current_score_visible=cs.score_visible,
                relation_vector=cs.relation_vector or {},
                drift=cs.personality_drift or {},
                behavior_tags=cls["behavior_tags"],
            )
            cs.score_visible = result["new_score_visible"]
            cs.relation_vector = result["new_relation_vector"]
            cs.personality_drift = result["new_drift"]
            cs.updated_at = datetime.utcnow()

            affection_delta.append(
                {
                    "char_id": str(cs.character_id),
                    "score_delta": result["score_delta"],
                    "vector_delta": result["vector_delta"],
                }
            )
            for hit in result["rule_hits"]:
                hit_copy = dict(hit)
                hit_copy["character_id"] = str(cs.character_id)
                rule_hits_all.append(hit_copy)

        ctx = build_branch_context(sess, char_states)
        branches = []
        if sess.current_node_id is not None:
            branches = db.execute(
                select(Branch).where(Branch.from_node_id == sess.current_node_id)
            ).scalars().all()
        chosen_branch, branch_evaluation = resolve_branch(branches, ctx)

        character_compact = [
            {
                "character_id": str(cs.character_id),
                "score_visible": cs.score_visible,
                "relation_vector": cs.relation_vector or {},
            }
            for cs in char_states
        ]

        branch_result = {
            "chosen_branch_id": str(chosen_branch.id) if chosen_branch else None,
            "route_type": chosen_branch.route_type if chosen_branch else None,
        }

        narrative_prompt = build_step_prompt(
            memory_summary=sess.memory_summary or "",
            branch_result=branch_result,
            character_compact=character_compact,
            player_input=input_text or "",
            classification={
                "intent": cls.get("intent"),
                "tone": cls.get("tone"),
                "behavior_tags": cls.get("behavior_tags", []),
            },
        )

        llm_narrative, _ = llm_runtime.narrative_with_fallback(db, prompt=narrative_prompt, session_id=sess.id, step_id=step_id)
        narrative_text = llm_narrative.narrative_text
        choices = [c.model_dump() for c in llm_narrative.choices]

        db.flush()
        tokens_in, tokens_out = _sum_step_tokens(db, sess.id, step_id)
        actual_total = tokens_in + tokens_out
        deterministic_cost = actual_total if actual_total > 0 else conservative_cost
        if deterministic_cost > sess.token_budget_remaining:
            raise HTTPException(status_code=409, detail={"code": "TOKEN_BUDGET_EXCEEDED"})

        budget_update = db.execute(
            update(StorySession)
            .where(StorySession.id == sess.id, StorySession.token_budget_remaining >= deterministic_cost)
            .values(
                token_budget_used=StorySession.token_budget_used + deterministic_cost,
                token_budget_remaining=StorySession.token_budget_remaining - deterministic_cost,
                updated_at=datetime.utcnow(),
            )
        )
        if budget_update.rowcount != 1:
            raise HTTPException(status_code=409, detail={"code": "TOKEN_BUDGET_EXCEEDED"})
        db.refresh(sess)

        next_remaining = sess.token_budget_remaining
        branch_result["token_budget_remaining"] = next_remaining

        node = DialogueNode(
            session_id=sess.id,
            parent_node_id=sess.current_node_id,
            node_type="player",
            player_input=input_text,
            narrative_text=narrative_text,
            choices=choices,
            branch_decision=branch_result,
        )
        db.add(node)
        db.flush()

        log = ActionLog(
            session_id=sess.id,
            node_id=node.id,
            player_input=input_text or "",
            classification=cls,
            matched_rules=rule_hits_all,
            affection_delta=affection_delta,
            branch_evaluation=branch_evaluation,
        )
        db.add(log)

        sess.current_node_id = node.id
        sess.updated_at = datetime.utcnow()

        latest_usage = db.execute(
            select(LLMUsageLog)
            .where(
                LLMUsageLog.session_id == sess.id,
                LLMUsageLog.step_id == step_id,
                LLMUsageLog.operation == "generate",
                LLMUsageLog.status == "success",
            )
            .order_by(LLMUsageLog.created_at.desc())
        ).scalars().first()
        provider_name = latest_usage.provider if latest_usage else "none"

    return {
        "node_id": node.id,
        "narrative_text": narrative_text,
        "choices": choices,
        "affection_delta": affection_delta,
        "cost": {"tokens_in": tokens_in, "tokens_out": tokens_out, "provider": provider_name},
    }


def create_snapshot(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> SessionSnapshot:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        cutoff = datetime.utcnow()
        char_states = db.execute(
            select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
        ).scalars().all()

        node_ids = [str(v) for v in db.execute(select(DialogueNode.id).where(DialogueNode.session_id == sess.id)).scalars().all()]
        action_log_ids = [str(v) for v in db.execute(select(ActionLog.id).where(ActionLog.session_id == sess.id)).scalars().all()]

        payload = {
            "session": {
                "id": str(sess.id),
                "status": sess.status,
                "current_node_id": str(sess.current_node_id) if sess.current_node_id else None,
                "global_flags": sess.global_flags,
                "route_flags": sess.route_flags,
                "active_characters": sess.active_characters,
                "memory_summary": sess.memory_summary,
                "token_budget_used": sess.token_budget_used,
                "token_budget_remaining": sess.token_budget_remaining,
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
            "dialogue_node_ids": node_ids,
            "action_log_ids": action_log_ids,
        }

        snapshot = SessionSnapshot(session_id=sess.id, snapshot_name="manual", state_blob=payload, created_at=cutoff)
        db.add(snapshot)
        db.flush()
    db.refresh(snapshot)
    return snapshot


def rollback_to_snapshot(db: Session, session_id: uuid.UUID, user_id: uuid.UUID, snapshot_id: uuid.UUID) -> StorySession:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        snapshot = db.get(SessionSnapshot, snapshot_id)
        if not snapshot or snapshot.session_id != sess.id:
            raise HTTPException(status_code=404, detail="snapshot not found")

        payload = snapshot.state_blob
        s = payload["session"]
        sess.status = s["status"]
        sess.current_node_id = uuid.UUID(s["current_node_id"]) if s["current_node_id"] else None
        sess.global_flags = s["global_flags"]
        sess.route_flags = s["route_flags"]
        sess.active_characters = s["active_characters"]
        sess.memory_summary = s["memory_summary"]
        sess.token_budget_used = s["token_budget_used"]
        sess.token_budget_remaining = s["token_budget_remaining"]
        sess.updated_at = datetime.utcnow()

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

        keep_node_ids = [uuid.UUID(v) for v in payload.get("dialogue_node_ids", [])]
        keep_action_log_ids = [uuid.UUID(v) for v in payload.get("action_log_ids", [])]

        action_delete = delete(ActionLog).where(ActionLog.session_id == sess.id)
        if keep_action_log_ids:
            action_delete = action_delete.where(ActionLog.id.not_in(keep_action_log_ids))
        db.execute(action_delete)

        node_delete = delete(DialogueNode).where(DialogueNode.session_id == sess.id)
        if keep_node_ids:
            node_delete = node_delete.where(DialogueNode.id.not_in(keep_node_ids))
        db.execute(node_delete)

    return sess


def end_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        sess.status = "ended"
        sess.updated_at = datetime.utcnow()

        report = replay_engine.build_report(session_id=sess.id, db=db)
        replay_row = upsert_replay_report(db, session_id=sess.id, report=report)
        db.flush()

    return {
        "ended": True,
        "replay_report_id": str(replay_row.id),
        "route_type": report.get("route_type", "default"),
    }


def get_replay(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    _require_session(db, session_id, user_id)
    from app.db.models import ReplayReport

    row = db.execute(select(ReplayReport).where(ReplayReport.session_id == session_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "REPLAY_NOT_READY"})
    return row.report_json
