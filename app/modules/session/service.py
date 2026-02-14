import re
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    ActionLog,
    Branch,
    Character,
    DialogueNode,
    Session as StorySession,
    SessionCharacterState,
    SessionSnapshot,
    User,
)
from app.modules.affection.engine import apply_affection
from app.modules.branch.engine import build_branch_context, resolve_branch
from app.modules.replay.engine import ReplayEngine, upsert_replay_report
from app.modules.session.schemas import ChoiceOut, SessionStateOut

replay_engine = ReplayEngine()


def classify_input_stub(input_text: str | None, choice_id: str | None) -> dict:
    text = (input_text or '').lower()
    tags = []

    if re.search(r'\b(thank|please|sorry|help)\b', text):
        tags.append('kind')
    if re.search(r'\b(love|date|cute|kiss)\b', text):
        tags.append('flirt')
    if re.search(r'\b(stupid|hate|kill|idiot|shut up)\b', text):
        tags.append('aggressive')
    if re.search(r'\b(respect|honor|promise)\b', text):
        tags.append('respectful')
    if re.search(r'\b(lie|cheat|fake)\b', text):
        tags.append('deceptive')

    if not tags:
        tags = ['kind']

    intent = 'neutral'
    tone = 'calm'
    if 'aggressive' in tags:
        intent = 'hostile'
        tone = 'harsh'
    elif 'flirt' in tags:
        intent = 'romantic'
        tone = 'warm'

    return {'behavior_tags': sorted(set(tags)), 'intent': intent, 'tone': tone, 'choice_id': choice_id}


def _ensure_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user:
        return user
    user = User(id=user_id, google_sub=f'dev-{user_id}', email=f'{user_id}@dev.local', display_name='Dev User')
    db.add(user)
    db.flush()
    return user


def _get_or_create_default_character(db: Session) -> Character:
    char = db.execute(select(Character).where(Character.name == 'Default Heroine')).scalar_one_or_none()
    if char:
        return char
    char = Character(
        name='Default Heroine',
        base_personality={'kind': 0.7},
        initial_relation_vector={'trust': 0.5, 'respect': 0.5, 'fear': 0.1, 'attraction': 0.2},
        initial_visible_score=50,
    )
    db.add(char)
    db.flush()
    return char


def _require_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> StorySession:
    sess = db.get(StorySession, session_id)
    if not sess or sess.user_id != user_id:
        raise HTTPException(status_code=404, detail='session not found')
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
                'id': node.id,
                'parent_node_id': node.parent_node_id,
                'narrative_text': node.narrative_text,
                'choices': [ChoiceOut(**c) for c in (node.choices or [])],
                'created_at': node.created_at,
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
                'id': cs.id,
                'character_id': cs.character_id,
                'score_visible': cs.score_visible,
                'relation_vector': cs.relation_vector,
                'personality_drift': cs.personality_drift,
                'updated_at': cs.updated_at,
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
            status='active',
            current_node_id=None,
            global_flags={},
            route_flags={},
            active_characters=[str(char.id)],
            memory_summary='',
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


def step_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID, input_text: str | None, choice_id: str | None):
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        if sess.status != 'active':
            raise HTTPException(status_code=409, detail={'code': 'SESSION_NOT_ACTIVE'})

        deterministic_cost = 20 + (len(input_text or '') // 4)
        if deterministic_cost > sess.token_budget_remaining:
            raise HTTPException(status_code=409, detail={'code': 'TOKEN_BUDGET_EXCEEDED'})

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
                behavior_tags=cls['behavior_tags'],
            )
            cs.score_visible = result['new_score_visible']
            cs.relation_vector = result['new_relation_vector']
            cs.personality_drift = result['new_drift']
            cs.updated_at = datetime.utcnow()

            affection_delta.append(
                {
                    'char_id': str(cs.character_id),
                    'score_delta': result['score_delta'],
                    'vector_delta': result['vector_delta'],
                }
            )
            for hit in result['rule_hits']:
                hit_copy = dict(hit)
                hit_copy['character_id'] = str(cs.character_id)
                rule_hits_all.append(hit_copy)

        ctx = build_branch_context(sess, char_states)
        branches = []
        if sess.current_node_id is not None:
            branches = db.execute(
                select(Branch).where(Branch.from_node_id == sess.current_node_id)
            ).scalars().all()
        chosen_branch, branch_evaluation = resolve_branch(branches, ctx)

        narrative_text = f"[stub] {cls['intent']}/{cls['tone']} input processed."
        choices = [
            {'id': 'c1', 'text': 'Continue', 'type': 'dialog'},
            {'id': 'c2', 'text': 'Pause', 'type': 'action'},
        ]

        next_remaining = sess.token_budget_remaining - deterministic_cost
        branch_result = {
            'chosen_branch_id': str(chosen_branch.id) if chosen_branch else None,
            'route_type': chosen_branch.route_type if chosen_branch else None,
            'token_budget_remaining': next_remaining,
        }

        node = DialogueNode(
            session_id=sess.id,
            parent_node_id=sess.current_node_id,
            node_type='player',
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
            player_input=input_text or '',
            classification=cls,
            matched_rules=rule_hits_all,
            affection_delta=affection_delta,
            branch_evaluation=branch_evaluation,
        )
        db.add(log)

        sess.current_node_id = node.id
        sess.token_budget_used += deterministic_cost
        sess.token_budget_remaining = next_remaining
        sess.updated_at = datetime.utcnow()

    return {
        'node_id': node.id,
        'narrative_text': narrative_text,
        'choices': choices,
        'affection_delta': affection_delta,
        'cost': {'tokens_in': deterministic_cost, 'tokens_out': 0, 'provider': 'none'},
    }


def create_snapshot(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> SessionSnapshot:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        cutoff = datetime.utcnow()
        char_states = db.execute(
            select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
        ).scalars().all()

        payload = {
            'session': {
                'id': str(sess.id),
                'status': sess.status,
                'current_node_id': str(sess.current_node_id) if sess.current_node_id else None,
                'global_flags': sess.global_flags,
                'route_flags': sess.route_flags,
                'active_characters': sess.active_characters,
                'memory_summary': sess.memory_summary,
                'token_budget_used': sess.token_budget_used,
                'token_budget_remaining': sess.token_budget_remaining,
            },
            'character_states': [
                {
                    'id': str(cs.id),
                    'character_id': str(cs.character_id),
                    'score_visible': cs.score_visible,
                    'relation_vector': cs.relation_vector,
                    'personality_drift': cs.personality_drift,
                    'updated_at': cs.updated_at.isoformat(),
                }
                for cs in char_states
            ],
            'cutoff_ts': cutoff.isoformat(),
        }

        snapshot = SessionSnapshot(session_id=sess.id, snapshot_name='manual', state_blob=payload, created_at=cutoff)
        db.add(snapshot)
        db.flush()
    db.refresh(snapshot)
    return snapshot


def rollback_to_snapshot(db: Session, session_id: uuid.UUID, user_id: uuid.UUID, snapshot_id: uuid.UUID) -> StorySession:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        snapshot = db.get(SessionSnapshot, snapshot_id)
        if not snapshot or snapshot.session_id != sess.id:
            raise HTTPException(status_code=404, detail='snapshot not found')

        payload = snapshot.state_blob
        cutoff = datetime.fromisoformat(payload['cutoff_ts'])

        s = payload['session']
        sess.status = s['status']
        sess.current_node_id = uuid.UUID(s['current_node_id']) if s['current_node_id'] else None
        sess.global_flags = s['global_flags']
        sess.route_flags = s['route_flags']
        sess.active_characters = s['active_characters']
        sess.memory_summary = s['memory_summary']
        sess.token_budget_used = s['token_budget_used']
        sess.token_budget_remaining = s['token_budget_remaining']
        sess.updated_at = datetime.utcnow()

        db.execute(delete(SessionCharacterState).where(SessionCharacterState.session_id == sess.id))
        for cs in payload['character_states']:
            db.add(
                SessionCharacterState(
                    id=uuid.UUID(cs['id']),
                    session_id=sess.id,
                    character_id=uuid.UUID(cs['character_id']),
                    score_visible=cs['score_visible'],
                    relation_vector=cs['relation_vector'],
                    personality_drift=cs['personality_drift'],
                    updated_at=datetime.fromisoformat(cs['updated_at']),
                )
            )

        db.execute(
            delete(DialogueNode).where(DialogueNode.session_id == sess.id, DialogueNode.created_at > cutoff)
        )
        db.execute(
            delete(ActionLog).where(ActionLog.session_id == sess.id, ActionLog.created_at > cutoff)
        )

    return sess


def end_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        sess.status = 'ended'
        sess.updated_at = datetime.utcnow()

        report = replay_engine.build_report(session_id=sess.id, db=db)
        replay_row = upsert_replay_report(db, session_id=sess.id, report=report)
        db.flush()

    return {
        'ended': True,
        'replay_report_id': str(replay_row.id),
        'route_type': report.get('route_type', 'default'),
    }


def get_replay(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    _require_session(db, session_id, user_id)
    from app.db.models import ReplayReport

    row = db.execute(select(ReplayReport).where(ReplayReport.session_id == session_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={'code': 'REPLAY_NOT_READY'})
    return row.report_json
