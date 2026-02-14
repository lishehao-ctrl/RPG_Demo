import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.db import session as db_session
from app.db.models import User
from app.main import app
from app.modules.auth import router as auth_router
from app.modules.auth.dev_auth import create_access_token, verify_oauth_state_token

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "auth.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


def test_google_login_builds_url_contains_state_and_scopes(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    old_client = settings.google_client_id
    old_redirect = settings.google_redirect_uri
    old_scopes = settings.google_oauth_scopes
    settings.google_client_id = "cid"
    settings.google_redirect_uri = "http://127.0.0.1:8000/auth/google/callback"
    settings.google_oauth_scopes = "openid email profile"
    try:
        client = TestClient(app)
        resp = client.get("/auth/google/login")
        assert resp.status_code == 200
        auth_url = resp.json()["auth_url"]
        qs = parse_qs(urlparse(auth_url).query)
        assert qs["client_id"][0] == "cid"
        assert qs["scope"][0] == "openid email profile"
        assert "state" in qs
        verify_oauth_state_token(qs["state"][0])
    finally:
        settings.google_client_id = old_client
        settings.google_redirect_uri = old_redirect
        settings.google_oauth_scopes = old_scopes


def test_google_callback_upserts_user_and_returns_jwt(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    old_secret = settings.jwt_secret
    settings.jwt_secret = "test-secret"

    state = client.get("/auth/google/login").json()["auth_url"]
    qs = parse_qs(urlparse(state).query)
    signed_state = qs["state"][0]

    def fake_exchange(_: str) -> dict:
        return {"id_token": "id-token"}

    def fake_verify(_: str) -> dict:
        return {"sub": "google-sub-1", "email": "u@example.com", "name": "User One", "aud": settings.google_client_id}

    monkeypatch.setattr(auth_router, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(auth_router, "verify_google_id_token", fake_verify)

    try:
        resp = client.get("/auth/google/callback", params={"code": "abc", "state": signed_state})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        token = body["access_token"]
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        assert payload["sub"]

        with db_session.SessionLocal() as db:
            user = db.query(User).filter(User.google_sub == "google-sub-1").first()
            assert user is not None
            assert user.email == "u@example.com"
    finally:
        settings.jwt_secret = old_secret


def test_production_rejects_x_user_id_when_env_not_dev(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    old_env = settings.env
    settings.env = "prod"
    try:
        client = TestClient(app)
        resp = client.post("/sessions", headers={"X-User-Id": str(uuid.uuid4())})
        assert resp.status_code == 401
    finally:
        settings.env = old_env


def test_bearer_token_auth_works_for_sessions(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    old_env = settings.env
    old_secret = settings.jwt_secret
    settings.env = "prod"
    settings.jwt_secret = "test-secret"
    try:
        uid = uuid.uuid4()
        with db_session.SessionLocal() as db:
            db.add(User(id=uid, google_sub="google-sub-2", email="b@example.com", display_name="Bearer User"))
            db.commit()

        token = create_access_token(user_id=uid, email="b@example.com")

        client = TestClient(app)
        resp = client.post("/sessions", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
    finally:
        settings.env = old_env
        settings.jwt_secret = old_secret
