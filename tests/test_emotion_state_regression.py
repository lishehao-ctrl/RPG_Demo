import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session as db_session
from app.db.models import ActionLog, Character, Session, SessionCharacterState
from app.main import app
from app.modules.llm.schemas import NarrativeOutput, PlayerInputClassification
from app.modules.narrative.emotion_state import DEFAULT_EMOTION_WINDOW, compute_emotion_score

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "emotion_regression.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


class _RuntimeStub:
    def classify_with_fallback(self, *args, **kwargs):
        return (
            PlayerInputClassification(
                intent="friendly",
                tone="calm",
                behavior_tags=["kind"],
                risk_tags=[],
                confidence=0.9,
            ),
            True,
        )

    def narrative_with_fallback(self, db, *, prompt: str, session_id, step_id=None):
        return (
            NarrativeOutput(
                narrative_text="ok",
                choices=[
                    {"id": "c1", "text": "A", "type": "dialog"},
                    {"id": "c2", "text": "B", "type": "action"},
                ],
            ),
            True,
        )


def test_emotion_state_rolls_back_with_snapshot(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    from app.modules.session import service as session_service

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: _RuntimeStub())

    def _fixed_affection(**kwargs):
        current = int(kwargs["current_score_visible"])
        return {
            "new_score_visible": current + 5,
            "new_relation_vector": kwargs["relation_vector"],
            "new_drift": kwargs["drift"],
            "score_delta": 5,
            "vector_delta": {},
            "rule_hits": [],
        }

    monkeypatch.setattr(session_service, "apply_affection", _fixed_affection)

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])

    with db_session.SessionLocal() as db:
        state = db.execute(select(SessionCharacterState).where(SessionCharacterState.session_id == sid)).scalars().first()
        assert state is not None
        state.score_visible = 30
        char_id = state.character_id
        db.commit()

    step1 = client.post(f"/sessions/{sid}/step", json={"input_text": "one"})
    assert step1.status_code == 200
    snap = client.post(f"/sessions/{sid}/snapshot")
    assert snap.status_code == 200
    snapshot_id = snap.json()["snapshot_id"]

    assert client.post(f"/sessions/{sid}/step", json={"input_text": "two"}).status_code == 200
    assert client.post(f"/sessions/{sid}/step", json={"input_text": "three"}).status_code == 200

    rolled = client.post(f"/sessions/{sid}/rollback", params={"snapshot_id": snapshot_id})
    assert rolled.status_code == 200

    with db_session.SessionLocal() as db:
        score = compute_emotion_score(sid, char_id, window=DEFAULT_EMOTION_WINDOW, db_session=db)
        assert score == 35


def test_emotion_state_last_n_ordering_is_stable(tmp_path: Path) -> None:
    _prepare_db(tmp_path)

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])

    with db_session.SessionLocal() as db:
        state = db.execute(select(SessionCharacterState).where(SessionCharacterState.session_id == sid)).scalars().first()
        assert state is not None
        char_id = state.character_id
        state.score_visible = 60

        id3 = uuid.UUID(int=3)
        id1 = uuid.UUID(int=1)
        id2 = uuid.UUID(int=2)

        db.add(ActionLog(id=id3, session_id=sid, player_input="a", affection_delta=[{"char_id": str(char_id), "dim": "emotion", "delta": 30}]))
        db.add(ActionLog(id=id1, session_id=sid, player_input="b", affection_delta=[{"char_id": str(char_id), "dim": "emotion", "delta": 10}]))
        db.add(ActionLog(id=id2, session_id=sid, player_input="c", affection_delta=[{"char_id": str(char_id), "dim": "emotion", "delta": 20}]))
        db.commit()

    with db_session.SessionLocal() as db:
        score1 = compute_emotion_score(sid, char_id, window=2, db_session=db)
        score2 = compute_emotion_score(sid, char_id, window=2, db_session=db)

    assert score1 == 50
    assert score2 == 50


def test_active_character_selection_is_deterministic(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    from app.modules.session import service as session_service

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])

    with db_session.SessionLocal() as db:
        sess = db.get(Session, sid)
        assert sess is not None

        new_char = Character(
            name="AAA NPC",
            base_personality={},
            initial_relation_vector={"trust": 0.0, "respect": 0.0, "fear": 0.0, "attraction": 0.0},
            initial_visible_score=40,
        )
        db.add(new_char)
        db.flush()
        db.add(
            SessionCharacterState(
                session_id=sid,
                character_id=new_char.id,
                score_visible=40,
                relation_vector={"trust": 0.0, "respect": 0.0, "fear": 0.0, "attraction": 0.0},
                personality_drift={},
            )
        )
        db.commit()

    with db_session.SessionLocal() as db:
        sess = db.get(Session, sid)
        assert sess is not None
        selected = [session_service._resolve_active_character_state(db, sess, None)[1].name for _ in range(3)]

    assert selected == ["AAA NPC", "AAA NPC", "AAA NPC"]
