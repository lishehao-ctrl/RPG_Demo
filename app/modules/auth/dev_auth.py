import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db import session as db_session

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_ENDPOINT = "https://oauth2.googleapis.com/tokeninfo"


def create_access_token(*, user_id: uuid.UUID, email: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email or "",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_exp_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_oauth_state_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "purpose": "google_oauth_state",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "nonce": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_oauth_state_token(state_token: str) -> dict:
    try:
        payload = jwt.decode(state_token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="invalid_state") from exc
    if payload.get("purpose") != "google_oauth_state":
        raise HTTPException(status_code=400, detail="invalid_state")
    return payload


def build_google_auth_url() -> str:
    state = create_oauth_state_token()
    query = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": settings.google_oauth_scopes,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(query)}"


def exchange_code_for_tokens(code: str) -> dict:
    payload = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
        resp.raise_for_status()
        return resp.json()


def verify_google_id_token(id_token: str) -> dict:
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(GOOGLE_TOKENINFO_ENDPOINT, params={"id_token": id_token})
        resp.raise_for_status()
        claims = resp.json()
    aud = claims.get("aud")
    if settings.google_client_id and aud != settings.google_client_id:
        raise HTTPException(status_code=400, detail="invalid_id_token_audience")
    if not claims.get("sub"):
        raise HTTPException(status_code=400, detail="invalid_id_token")
    return claims


def upsert_google_user(db: Session, claims: dict) -> User:
    google_sub = claims["sub"]
    email = claims.get("email", "")
    name = claims.get("name") or claims.get("given_name") or ""

    user = db.execute(select(User).where(User.google_sub == google_sub)).scalar_one_or_none()
    if user is None:
        user = User(
            google_sub=google_sub,
            email=email or f"{google_sub}@google.local",
            display_name=name,
        )
        db.add(user)
        db.flush()
    else:
        user.email = email or user.email
        user.display_name = name or user.display_name
    return user


def _dev_fallback_user(db: Session, x_user_id: str | None) -> User:
    uid = DEFAULT_USER_ID if not x_user_id else uuid.UUID(x_user_id)
    user = db.get(User, uid)
    if user:
        return user
    user = User(id=uid, google_sub=f"dev-{uid}", email=f"{uid}@dev.local", display_name="Dev User")
    db.add(user)
    db.flush()
    return user


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            user_id = uuid.UUID(payload.get("sub", ""))
        except (JWTError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="invalid_token") from exc

        with db_session.SessionLocal() as db:
            user = db.get(User, user_id)
            if not user:
                raise HTTPException(status_code=401, detail="user_not_found")
            return {"id": user.id, "email": user.email, "display_name": user.display_name}

    if settings.env == "dev":
        with db_session.SessionLocal() as db:
            user = _dev_fallback_user(db, x_user_id)
            db.commit()
            return {"id": user.id, "email": user.email, "display_name": user.display_name}

    raise HTTPException(status_code=401, detail="missing_bearer_token")

