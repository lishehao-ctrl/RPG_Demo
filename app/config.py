import os
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, inspect, text

DEV_DEFAULT_DB_URL = "sqlite:///./dev.db"
DEV_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "sessions": {"state_json", "story_node_id"},
    "action_logs": {"state_before", "state_after", "state_delta"},
}
DEV_FORBIDDEN_TABLES: set[str] = {"users", "audit_logs"}
DEV_FORBIDDEN_COLUMNS: dict[str, set[str]] = {
    "sessions": {"user_id"},
}


class Settings(BaseSettings):
    app_name: str = "rpg_demo"
    env: str = "dev"
    database_url: str = "sqlite+pysqlite:///./app.db"
    redis_url: str = "redis://localhost:6379/0"

    llm_provider_primary: str = "fake"
    llm_provider_fallbacks: list[str] = Field(default_factory=list)
    llm_model_generate: str = "fake-generate-v1"
    llm_timeout_s: float = 8.0
    llm_max_retries: int = 2
    llm_total_deadline_s: float = 10.0
    llm_connect_timeout_s: float = 2.0
    llm_read_timeout_s: float = 8.0
    llm_write_timeout_s: float = 8.0
    llm_pool_timeout_s: float = 2.0
    llm_retry_attempts_network: int = 2
    llm_retry_backoff_base_ms: int = 150
    llm_retry_backoff_max_ms: int = 1200
    llm_circuit_breaker_window_s: float = 60.0
    llm_circuit_breaker_fail_threshold: int = 3
    llm_circuit_breaker_open_s: float = 30.0

    step_idempotency_ttl_s: int = 86400
    step_idempotency_in_progress_stale_s: int = 30

    demo_default_story_id: str = "campus_week_v1"
    demo_default_story_version: int | None = 1
    demo_step_retry_max_attempts: int = 3
    demo_step_retry_backoff_ms: int = 350

    story_map_min_confidence: float = 0.6
    story_fallback_id_unique_packwide: bool = False
    story_fallback_llm_enabled: bool = False
    story_fallback_llm_max_chars: int = 500
    story_fallback_show_effects_in_text: bool = False
    story_default_locale: str = "en"

    llm_doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    llm_doubao_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def _is_sqlite_memory_url(db_url: str) -> bool:
    candidate = (db_url or "").strip().lower()
    if not candidate.startswith("sqlite"):
        return False
    if ":memory:" in candidate:
        return True
    return candidate in {
        "sqlite://",
        "sqlite:///",
        "sqlite+pysqlite://",
        "sqlite+pysqlite:///",
    }


def validate_database_url(env: str, db_url: str | None) -> str:
    env_value = (env or "").strip().lower()
    if env_value != "dev":
        return db_url or ""

    if not db_url or not db_url.strip():
        return DEV_DEFAULT_DB_URL

    if _is_sqlite_memory_url(db_url):
        raise RuntimeError(
            "DATABASE_URL cannot be sqlite :memory: when ENV=dev because sessions will disappear. "
            f"Set DATABASE_URL={DEV_DEFAULT_DB_URL} or another file-based sqlite url."
        )
    return db_url


@lru_cache(maxsize=1)
def current_alembic_head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini_path))
    script_dir = ScriptDirectory.from_config(cfg)
    head = script_dir.get_current_head()
    if not head:
        raise RuntimeError("Unable to resolve Alembic head revision from migration scripts.")
    return str(head)


def _dev_upgrade_message(db_url: str) -> str:
    return (
        "Run "
        f"ENV=dev DATABASE_URL={db_url} python -m alembic upgrade head "
        "or ./scripts/dev.sh"
    )


def ensure_dev_database_schema(
    db_url: str,
    required_tables: Iterable[str] = ("alembic_version", "sessions", "stories", "session_step_idempotency"),
    required_columns: dict[str, set[str]] = DEV_REQUIRED_COLUMNS,
    forbidden_tables: Iterable[str] = DEV_FORBIDDEN_TABLES,
    forbidden_columns: dict[str, set[str]] = DEV_FORBIDDEN_COLUMNS,
) -> None:
    if not db_url:
        return
    engine = create_engine(db_url, future=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    problems: list[str] = []

    missing_tables = [name for name in required_tables if name not in tables]
    if missing_tables:
        problems.append(f"missing tables: {', '.join(sorted(missing_tables))}")

    present_forbidden_tables = [name for name in forbidden_tables if name in tables]
    if present_forbidden_tables:
        problems.append(f"forbidden legacy tables present: {', '.join(sorted(present_forbidden_tables))}")

    db_revision = None
    if "alembic_version" in tables:
        with engine.connect() as conn:
            db_revision = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
        db_revision = str(db_revision or "").strip()
        head = current_alembic_head_revision()
        if db_revision != head:
            problems.append(f"alembic_version={db_revision or 'empty'} (expected {head})")

    for table_name, expected_cols in required_columns.items():
        if table_name not in tables:
            continue
        actual_cols = {col["name"] for col in inspector.get_columns(table_name)}
        missing_cols = sorted(col for col in expected_cols if col not in actual_cols)
        for col in missing_cols:
            problems.append(f"missing column {table_name}.{col}")

    for table_name, blocked_cols in forbidden_columns.items():
        if table_name not in tables:
            continue
        actual_cols = {col["name"] for col in inspector.get_columns(table_name)}
        present_cols = sorted(col for col in blocked_cols if col in actual_cols)
        for col in present_cols:
            problems.append(f"forbidden legacy column present {table_name}.{col}")

    if problems:
        details = "; ".join(problems)
        raise RuntimeError(f"dev schema mismatch for DATABASE_URL={db_url}: {details}. {_dev_upgrade_message(db_url)}")


settings = Settings()
_raw_db_url = os.getenv("DATABASE_URL")
if settings.env == "dev":
    settings.database_url = validate_database_url(settings.env, _raw_db_url)
else:
    settings.database_url = validate_database_url(settings.env, _raw_db_url or settings.database_url)
