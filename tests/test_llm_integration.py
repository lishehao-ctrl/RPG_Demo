import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings
from app.db import session as db_session
from app.db.models import ActionLog, LLMUsageLog, Session, SessionCharacterState
from app.main import app
from app.modules.llm.adapter import get_llm_runtime
from app.modules.llm.schemas import NarrativeOutput, PlayerInputClassification

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "llm.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


def test_llm_classify_success_updates_tags(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    settings.llm_provider_primary = "fake"
    runtime = get_llm_runtime()
    fake = runtime.providers["fake"]
    fake.fail_classify = False

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "please love me"})
    assert resp.status_code == 200

    with db_session.SessionLocal() as db:
        log = db.execute(select(ActionLog).where(ActionLog.session_id == sid).order_by(ActionLog.created_at.desc())).scalars().first()
        assert log is not None
        tags = set(log.classification["behavior_tags"])
        assert "flirt" in tags


def test_llm_classify_fallback_to_stub_on_failure(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    settings.llm_provider_primary = "fake"
    runtime = get_llm_runtime()
    fake = runtime.providers["fake"]
    fake.fail_classify = True

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "please love me"})
    assert resp.status_code == 200

    with db_session.SessionLocal() as db:
        log = db.execute(select(ActionLog).where(ActionLog.session_id == sid).order_by(ActionLog.created_at.desc())).scalars().first()
        assert log is not None
        assert "flirt" in set(log.classification["behavior_tags"])
        fail_logs = db.execute(select(LLMUsageLog).where(LLMUsageLog.session_id == sid, LLMUsageLog.operation == "classify")).scalars().all()
        assert any(x.status == "error" for x in fail_logs)

    fake.fail_classify = False


def test_llm_generate_success_creates_node_choices(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    settings.llm_provider_primary = "fake"
    runtime = get_llm_runtime()
    fake = runtime.providers["fake"]
    fake.fail_generate = False

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["narrative_text"].startswith("[llm]")
    assert len(body["choices"]) >= 2
    assert all(c["type"] in {"dialog", "action"} for c in body["choices"])


def test_llm_generate_repair_on_invalid_json(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    settings.llm_provider_primary = "fake"
    runtime = get_llm_runtime()
    fake = runtime.providers["fake"]
    fake.invalid_generate_once = True

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert resp.status_code == 200
    assert resp.json()["narrative_text"]


def test_llm_usage_logs_written_and_budget_uses_usage_tokens(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    settings.llm_provider_primary = "fake"
    runtime = get_llm_runtime()
    fake = runtime.providers["fake"]
    fake.fail_classify = False
    fake.fail_generate = False

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    before = client.get(f"/sessions/{sid}").json()["token_budget_remaining"]
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello world"})
    assert resp.status_code == 200
    cost = resp.json()["cost"]
    assert cost["tokens_in"] >= 0
    assert cost["tokens_out"] >= 0

    after = client.get(f"/sessions/{sid}").json()["token_budget_remaining"]
    assert before - after == cost["tokens_in"] + cost["tokens_out"]

    with db_session.SessionLocal() as db:
        rows = db.execute(select(LLMUsageLog).where(LLMUsageLog.session_id == sid)).scalars().all()
        assert rows
        assert any(r.operation == "classify" for r in rows)
        assert any(r.operation == "generate" for r in rows)


def test_llm_generate_fallback_template_on_failure(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    settings.llm_provider_primary = "fake"
    runtime = get_llm_runtime()
    fake = runtime.providers["fake"]
    fake.fail_generate = True

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert resp.status_code == 200
    assert resp.json()["narrative_text"].startswith("[fallback]")

    with db_session.SessionLocal() as db:
        sess = db.get(Session, sid)
        assert sess is not None
        assert sess.current_node_id is not None
        gen_rows = db.execute(select(LLMUsageLog).where(LLMUsageLog.session_id == sid, LLMUsageLog.operation == "generate")).scalars().all()
        assert gen_rows
        assert any(r.status == "error" for r in gen_rows)

    fake.fail_generate = False


def test_llm_usage_logs_persist_step_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])

    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert resp.status_code == 200

    with db_session.SessionLocal() as db:
        rows = db.execute(select(LLMUsageLog).where(LLMUsageLog.session_id == sid)).scalars().all()
        assert rows
        assert all(r.step_id is not None for r in rows)
        assert len({r.step_id for r in rows}) == 1


def test_token_budget_decrement_is_guarded_atomically(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    settings.llm_provider_primary = "fake"

    from app.modules.session import service as session_service

    original_sum = session_service._sum_step_tokens

    def _racey_sum(db, session_id, step_id):
        db.execute(text("UPDATE sessions SET token_budget_remaining=0 WHERE id=:sid"), {"sid": str(session_id)})
        return 20, 0

    monkeypatch.setattr(session_service, "_sum_step_tokens", _racey_sum)

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert resp.status_code == 200

    with db_session.SessionLocal() as db:
        sess = db.get(Session, sid)
        assert sess.token_budget_used == 20

    monkeypatch.setattr(session_service, "_sum_step_tokens", original_sum)


def test_budget_preflight_blocks_llm_calls_when_budget_near_exhausted(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)

    from app.modules.session import service as session_service

    class _NeverCallRuntime:
        classify_called = 0
        narrative_called = 0

        def classify_with_fallback(self, *args, **kwargs):
            self.classify_called += 1
            raise AssertionError('classify should not be called under preflight exhaustion')

        def narrative_with_fallback(self, *args, **kwargs):
            self.narrative_called += 1
            raise AssertionError('narrative should not be called under preflight exhaustion')

    runtime = _NeverCallRuntime()
    monkeypatch.setattr(session_service, 'get_llm_runtime', lambda: runtime)

    original_total = settings.session_token_budget_total
    settings.session_token_budget_total = session_service._preflight_required_budget('hello') - 1
    try:
        client = TestClient(app)
        sid = uuid.UUID(client.post('/sessions').json()['id'])

        before = client.get(f'/sessions/{sid}').json()
        resp = client.post(f'/sessions/{sid}/step', json={'input_text': 'hello'})
        assert resp.status_code == 409
        assert resp.json()['detail']['code'] == 'TOKEN_BUDGET_EXCEEDED'
        assert runtime.classify_called == 0
        assert runtime.narrative_called == 0

        after = client.get(f'/sessions/{sid}').json()
        assert after['token_budget_remaining'] == before['token_budget_remaining']
        assert after['token_budget_used'] == before['token_budget_used']
    finally:
        settings.session_token_budget_total = original_total


def test_step_blocks_before_provider_when_budget_too_low(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)

    from app.modules.session import service as session_service

    class _CountRuntime:
        classify_calls = 0
        narrative_calls = 0

        def classify_with_fallback(self, *args, **kwargs):
            self.classify_calls += 1
            raise AssertionError('classify should not be called when budget is below reserve')

        def narrative_with_fallback(self, *args, **kwargs):
            self.narrative_calls += 1
            raise AssertionError('narrative should not be called when budget is below reserve')

    runtime = _CountRuntime()
    monkeypatch.setattr(session_service, 'get_llm_runtime', lambda: runtime)

    original_total = settings.session_token_budget_total
    settings.session_token_budget_total = session_service._preflight_required_budget('hello') - 1
    try:
        client = TestClient(app)
        sid = client.post('/sessions').json()['id']

        resp = client.post(f'/sessions/{sid}/step', json={'input_text': 'hello'})
        assert resp.status_code == 409
        assert resp.json()['detail']['code'] == 'TOKEN_BUDGET_EXCEEDED'
        assert runtime.classify_calls == 0
        assert runtime.narrative_calls == 0
    finally:
        settings.session_token_budget_total = original_total


def test_step_reserve_then_refund_settles_to_actual(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)

    from app.modules.session import service as session_service
    from app.db.models import Session as StorySession

    class _ReserveRuntime:
        def classify_with_fallback(self, *args, **kwargs):
            return (
                PlayerInputClassification(
                    intent='friendly',
                    tone='calm',
                    behavior_tags=['kind'],
                    risk_tags=[],
                    confidence=0.9,
                ),
                True,
            )

        def narrative_with_fallback(self, db, *, prompt: str, session_id, step_id=None):
            # simulate state mutation after reserve, before settle path
            sess = db.get(StorySession, session_id)
            sess.token_budget_remaining = 0
            return (
                NarrativeOutput(
                    narrative_text='ok',
                    choices=[
                        {'id': 'c1', 'text': 'A', 'type': 'dialog'},
                        {'id': 'c2', 'text': 'B', 'type': 'action'},
                    ],
                ),
                True,
            )

    runtime = _ReserveRuntime()
    monkeypatch.setattr(session_service, 'get_llm_runtime', lambda: runtime)
    monkeypatch.setattr(session_service, '_preflight_required_budget', lambda _text: 200)
    monkeypatch.setattr(session_service, '_sum_step_tokens', lambda db, session_id, step_id: (12, 3))

    original_total = settings.session_token_budget_total
    settings.session_token_budget_total = 1000
    try:
        client = TestClient(app)
        sid = uuid.UUID(client.post('/sessions').json()['id'])
        before = client.get(f'/sessions/{sid}').json()

        resp = client.post(f'/sessions/{sid}/step', json={'input_text': 'hello'})
        assert resp.status_code == 200

        after = client.get(f'/sessions/{sid}').json()
        assert before['token_budget_remaining'] - after['token_budget_remaining'] == 15

        with db_session.SessionLocal() as db:
            sess = db.get(Session, sid)
            assert sess is not None
            assert sess.token_budget_used == 15
    finally:
        settings.session_token_budget_total = original_total


def test_step_injects_emotion_state_and_policy_matches_band(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)

    from app.modules.session import service as session_service

    class _CaptureRuntime:
        def __init__(self) -> None:
            self.prompt: str | None = None

        def classify_with_fallback(self, *args, **kwargs):
            return (
                PlayerInputClassification(
                    intent='friendly',
                    tone='calm',
                    behavior_tags=['kind'],
                    risk_tags=[],
                    confidence=0.9,
                ),
                True,
            )

        def narrative_with_fallback(self, db, *, prompt: str, session_id, step_id=None):
            self.prompt = prompt
            return (
                NarrativeOutput(
                    narrative_text='ok',
                    choices=[
                        {'id': 'c1', 'text': 'A', 'type': 'dialog'},
                        {'id': 'c2', 'text': 'B', 'type': 'action'},
                    ],
                ),
                True,
            )

    runtime = _CaptureRuntime()
    monkeypatch.setattr(session_service, 'get_llm_runtime', lambda: runtime)

    client = TestClient(app)
    sid = uuid.UUID(client.post('/sessions').json()['id'])

    with db_session.SessionLocal() as db:
        sess = db.get(Session, sid)
        assert sess is not None
        sess.route_flags = {'story_id': 'noir'}
        state = db.execute(
            select(SessionCharacterState).where(SessionCharacterState.session_id == sid)
        ).scalars().first()
        assert state is not None
        state.score_visible = 80
        db.commit()

    resp = client.post(f'/sessions/{sid}/step', json={'input_text': 'hello'})
    assert resp.status_code == 200
    assert runtime.prompt is not None

    marker = '{"memory_summary"'
    idx = runtime.prompt.rfind(marker)
    assert idx >= 0
    payload = json.loads(runtime.prompt[idx:])

    assert 'emotion_state' in payload
    emotion_state = payload['emotion_state']
    assert set(emotion_state.keys()) == {'character', 'score', 'band', 'window', 'story_id'}
    assert emotion_state['story_id'] == 'noir'

    assert 'behavior_policy' in payload
    expected = session_service.select_behavior_policy(emotion_state['story_id'], emotion_state['band']).model_dump(mode='json')
    assert payload['behavior_policy'] == expected
