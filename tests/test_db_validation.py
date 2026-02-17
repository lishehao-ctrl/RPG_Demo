from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.config import DEV_DEFAULT_DB_URL, ensure_dev_database_schema, validate_database_url


def test_validate_database_url_dev_missing_defaults() -> None:
    assert validate_database_url("dev", None) == DEV_DEFAULT_DB_URL


def test_validate_database_url_dev_rejects_memory() -> None:
    with pytest.raises(RuntimeError) as exc:
        validate_database_url("dev", "sqlite:///:memory:")
    assert DEV_DEFAULT_DB_URL in str(exc.value)


def test_validate_database_url_prod_passthrough() -> None:
    url = "sqlite:///:memory:"
    assert validate_database_url("prod", url) == url


def test_dev_schema_guard_raises_when_missing_tables(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'guard.db'}"
    engine = create_engine(db_url, future=True)
    with engine.connect():
        pass

    with pytest.raises(RuntimeError) as exc:
        ensure_dev_database_schema(db_url)
    assert "Run alembic upgrade head" in str(exc.value)
    assert db_url in str(exc.value)


def test_dev_schema_guard_allows_when_alembic_version_present(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'guard_ok.db'}"
    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")

    ensure_dev_database_schema(db_url)
