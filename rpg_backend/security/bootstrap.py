from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session as DBSession

from rpg_backend.config.settings import Settings, get_settings
from rpg_backend.security.passwords import hash_password, verify_password
from rpg_backend.storage.engine import engine
from rpg_backend.storage.models import AdminUser
from rpg_backend.storage.repositories.admin_users import get_admin_user_by_email, upsert_bootstrap_admin

_DEFAULT_JWT_SECRET = "dev-only-change-me"
_DEFAULT_ADMIN_EMAIL = "admin@example.com"
_DEFAULT_ADMIN_PASSWORD = "admin123456"
_DEFAULT_INTERNAL_WORKER_TOKEN = "dev-worker-token"


@dataclass(frozen=True)
class ProductionSecretValidationError(RuntimeError):
    message: str

    def __post_init__(self) -> None:
        super().__init__(self.message)


def _is_production(settings: Settings) -> bool:
    return (settings.app_env or "").strip().lower() in {"prod", "production"}


def _has_any_model(settings: Settings) -> bool:
    return any(
        (value or "").strip()
        for value in (
            settings.llm_openai_model,
            settings.llm_openai_route_model,
            settings.llm_openai_narration_model,
        )
    )


def assert_production_secret_requirements(settings: Settings | None = None) -> None:
    current = settings or get_settings()
    if not _is_production(current):
        return

    missing: list[str] = []

    database_url = (current.database_url or "").strip()
    if not database_url:
        missing.append("APP_DATABASE_URL")
    elif database_url.startswith("sqlite"):
        missing.append("APP_DATABASE_URL(non-sqlite required in prod)")

    if not (current.llm_openai_base_url or "").strip():
        missing.append("APP_LLM_OPENAI_BASE_URL")
    if not (current.llm_openai_api_key or "").strip():
        missing.append("APP_LLM_OPENAI_API_KEY")
    if not _has_any_model(current):
        missing.append("APP_LLM_OPENAI_MODEL|APP_LLM_OPENAI_ROUTE_MODEL|APP_LLM_OPENAI_NARRATION_MODEL")
    if not (current.obs_alert_webhook_url or "").strip():
        missing.append("APP_OBS_ALERT_WEBHOOK_URL")

    jwt_secret = (current.auth_jwt_secret or "").strip()
    if not jwt_secret or jwt_secret == _DEFAULT_JWT_SECRET:
        missing.append("APP_AUTH_JWT_SECRET")

    admin_email = (current.admin_bootstrap_email or "").strip().lower()
    if not admin_email or admin_email == _DEFAULT_ADMIN_EMAIL:
        missing.append("APP_ADMIN_BOOTSTRAP_EMAIL")

    admin_password = (current.admin_bootstrap_password or "").strip()
    if not admin_password or admin_password == _DEFAULT_ADMIN_PASSWORD:
        missing.append("APP_ADMIN_BOOTSTRAP_PASSWORD")

    worker_token = (current.internal_worker_token or "").strip()
    if not worker_token or worker_token == _DEFAULT_INTERNAL_WORKER_TOKEN:
        missing.append("APP_INTERNAL_WORKER_TOKEN")

    if missing:
        raise ProductionSecretValidationError(
            "missing or insecure production secrets: " + ", ".join(missing)
        )


def ensure_bootstrap_admin(settings: Settings | None = None) -> AdminUser:
    current = settings or get_settings()
    email = (current.admin_bootstrap_email or "").strip().lower()
    password = (current.admin_bootstrap_password or "").strip()

    if not email:
        raise RuntimeError("APP_ADMIN_BOOTSTRAP_EMAIL is required")
    if not password:
        raise RuntimeError("APP_ADMIN_BOOTSTRAP_PASSWORD is required")

    with DBSession(engine) as db:
        existing = get_admin_user_by_email(db, email)
        if existing is not None and verify_password(password, existing.password_hash):
            target_hash = existing.password_hash
        else:
            target_hash = hash_password(password)
        return upsert_bootstrap_admin(db, email=email, password_hash=target_hash)
