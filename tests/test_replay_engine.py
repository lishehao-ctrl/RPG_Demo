import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session as db_session
from app.db.models import ActionLog, Branch, ReplayReport, SessionCharacterState
from app.main import app
from app.modules.replay.engine import ReplayEngine

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / 'replay.db'
    env = os.environ.copy()
    env['DATABASE_URL'] = f'sqlite:///{db_path}'
    proc = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f'sqlite+pysqlite:///{db_path}')


def _seed_branches_for_current_node(session_id: uuid.UUID, node_id: uuid.UUID) -> None:
    with db_session.SessionLocal() as db:
        cs = db.execute(select(SessionCharacterState).where(SessionCharacterState.session_id == session_id)).scalars().first()
        assert cs is not None
        trust_path = f'characters.{cs.character_id}.trust'
        score_path = f'characters.{cs.character_id}.score_visible'

        b_high = Branch(
            from_node_id=node_id,
            priority=30,
            is_exclusive=True,
            is_default=False,
            route_type='high_route',
            rule_expr={'op': 'gte', 'left': score_path, 'right': 40},
        )
        b_low = Branch(
            from_node_id=node_id,
            priority=10,
            is_exclusive=False,
            is_default=False,
            route_type='low_route',
            rule_expr={'op': 'gte', 'left': score_path, 'right': 40},
        )
        b_near = Branch(
            from_node_id=node_id,
            priority=5,
            is_exclusive=False,
            is_default=False,
            route_type='trust_gate',
            rule_expr={'op': 'gte', 'left': trust_path, 'right': 0.95},
        )
        db.add_all([b_high, b_low, b_near])
        db.commit()


def test_replay_report_is_deterministic_and_contains_required_keys(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    sid = uuid.UUID(client.post('/sessions').json()['id'])
    first = client.post(f'/sessions/{sid}/step', json={'input_text': 'hello there'})
    assert first.status_code == 200
    node_id = uuid.UUID(first.json()['node_id'])

    _seed_branches_for_current_node(sid, node_id)

    second = client.post(f'/sessions/{sid}/step', json={'input_text': 'please love me'})
    assert second.status_code == 200

    end1 = client.post(f'/sessions/{sid}/end')
    assert end1.status_code == 200
    end2 = client.post(f'/sessions/{sid}/end')
    assert end2.status_code == 200
    assert end1.json()['route_type'] == end2.json()['route_type']
    assert end1.json()['replay_report_id'] == end2.json()['replay_report_id']

    replay1 = client.get(f'/sessions/{sid}/replay')
    replay2 = client.get(f'/sessions/{sid}/replay')
    assert replay1.status_code == 200
    assert replay2.status_code == 200
    assert replay1.json() == replay2.json()

    payload = replay1.json()
    required = {
        'session_id',
        'route_type',
        'decision_points',
        'affection_timeline',
        'relation_vector_final',
        'affection_attribution',
        'missed_routes',
        'what_if',
    }
    assert required.issubset(payload.keys())

    matched_miss = [m for m in payload['missed_routes'] if m.get('matched') is True]
    assert any(m.get('route_type') == 'low_route' and m.get('reason') == 'priority lost' for m in matched_miss)

    near_miss = [m for m in payload['missed_routes'] if m.get('matched') is False]
    assert any('trust' in (m.get('unlock_hint') or '') and '>=' in (m.get('unlock_hint') or '') for m in near_miss)

    with db_session.SessionLocal() as db:
        report_rows = db.execute(select(ReplayReport).where(ReplayReport.session_id == sid)).scalars().all()
        assert len(report_rows) == 1
        last_log = db.execute(select(ActionLog).where(ActionLog.session_id == sid).order_by(ActionLog.created_at.desc())).scalars().first()
        assert last_log is not None
        assert len(last_log.branch_evaluation) == 3
        assert all('trace' in item for item in last_log.branch_evaluation)

        engine = ReplayEngine()
        rebuilt = engine.build_report(sid, db)
        assert rebuilt == payload


def test_replay_timeline_starts_from_persisted_character_baseline(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    sid = uuid.UUID(client.post('/sessions').json()['id'])
    with db_session.SessionLocal() as db:
        state = db.execute(select(SessionCharacterState).where(SessionCharacterState.session_id == sid)).scalars().first()
        assert state is not None
        state.score_visible = 73
        state.relation_vector = {'trust': 0.7, 'attraction': 0.2, 'fear': 0.05, 'respect': 0.6}
        db.commit()
        char_id = str(state.character_id)

    with db_session.SessionLocal() as db:
        report = ReplayEngine().build_report(sid, db)

    first = report['affection_timeline'][char_id][0]
    assert first['step_index'] == 0
    assert first['score_visible'] == 73
    assert first['relation_vector']['trust'] == 0.7
    assert first['relation_vector']['respect'] == 0.6


def test_replay_timeline_last_point_matches_persisted_final_state(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    sid = uuid.UUID(client.post('/sessions').json()['id'])
    step = client.post(f'/sessions/{sid}/step', json={'input_text': 'please love me'})
    assert step.status_code == 200

    with db_session.SessionLocal() as db:
        state = db.execute(select(SessionCharacterState).where(SessionCharacterState.session_id == sid)).scalars().first()
        assert state is not None
        report = ReplayEngine().build_report(sid, db)

    points = report['affection_timeline'][str(state.character_id)]
    assert len(points) >= 2
    last = points[-1]
    assert last['score_visible'] == state.score_visible
    assert last['relation_vector'] == state.relation_vector
