from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dev_auth import (
    build_google_auth_url,
    create_access_token,
    exchange_code_for_tokens,
    upsert_google_user,
    verify_google_id_token,
    verify_oauth_state_token,
    get_current_user,
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
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
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
