import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import settings
from app.db import session as db_session
from app.db.models import ActionLog, LLMUsageLog, Session
from app.main import app
from app.modules.llm.adapter import get_llm_runtime

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
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "TOKEN_BUDGET_EXCEEDED"

    with db_session.SessionLocal() as db:
        sess = db.get(Session, sid)
        assert sess.token_budget_remaining == settings.session_token_budget_total

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
