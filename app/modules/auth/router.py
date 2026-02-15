from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.db.session import get_db
from app.modules.auth.dev_auth import (
    build_google_auth_url,
    create_access_token,
    exchange_code_for_tokens,
    get_current_user,
    upsert_google_user,
    verify_google_id_token,
    verify_oauth_state_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"user": {"id": str(user["id"]), "email": user.get("email"), "display_name": user.get("display_name")}}


@router.get("/google/login")
def google_login():
    return {"auth_url": build_google_auth_url()}


@router.get("/google/callback")
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if error:
        with db.begin():
            db.add(
                AuditLog(
                    event_type="google_oauth_callback_error",
                    payload={"error": error, "error_description": error_description},
                    created_at=datetime.utcnow(),
                )
            )
        raise HTTPException(
            status_code=400,
            detail={"code": "GOOGLE_OAUTH_ERROR", "error": error, "error_description": error_description},
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail={"code": "MISSING_CODE_OR_STATE"})

    verify_oauth_state_token(state)

    try:
        token_data = exchange_code_for_tokens(code)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="token_exchange_failed") from exc

    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="missing_id_token")

    claims = verify_google_id_token(id_token)

    with db.begin():
        user = upsert_google_user(db, claims)

    access_token = create_access_token(user_id=user.id, email=user.email)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "google_sub": user.google_sub,
            "email": user.email,
            "display_name": user.display_name,
        },
    }
