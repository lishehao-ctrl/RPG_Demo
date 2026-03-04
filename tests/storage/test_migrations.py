from __future__ import annotations

import pytest
from sqlalchemy import inspect

from rpg_backend.storage.engine import engine

from rpg_backend.storage.migrations import (
    DatabaseMigrationError,
    assert_schema_current,
    get_current_revision,
    get_head_revision,
    run_downgrade,
    run_upgrade,
)


def test_upgrade_head_matches_current_revision() -> None:
    run_upgrade("head")
    assert get_current_revision() == get_head_revision()
    inspector = inspect(engine)
    assert "adminuser" in inspector.get_table_names()


def test_downgrade_and_upgrade_roundtrip() -> None:
    head_revision = get_head_revision()

    run_downgrade("base")
    assert get_current_revision() is None

    run_upgrade("head")
    assert get_current_revision() == head_revision


def test_assert_schema_current_fails_when_revision_is_behind() -> None:
    run_downgrade("base")

    with pytest.raises(DatabaseMigrationError) as exc_info:
        assert_schema_current()

    assert exc_info.value.code in {"schema_revision_missing", "schema_revision_mismatch"}

    run_upgrade("head")
    assert_schema_current()
