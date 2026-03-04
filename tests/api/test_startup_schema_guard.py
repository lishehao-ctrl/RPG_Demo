from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import rpg_backend.llm_worker.main as worker_main
import rpg_backend.main as backend_main
from rpg_backend.storage.migrations import DatabaseMigrationError


def test_backend_startup_fails_when_schema_revision_is_not_current(monkeypatch) -> None:
    def _fail_guard() -> None:
        raise DatabaseMigrationError(
            code="schema_revision_mismatch",
            message="schema is behind",
            details={"current_revision": "old", "head_revision": "new"},
        )

    monkeypatch.setattr(backend_main, "assert_schema_current", _fail_guard)

    with pytest.raises(DatabaseMigrationError):
        with TestClient(backend_main.app):
            pass


def test_worker_startup_fails_when_schema_revision_is_not_current(monkeypatch) -> None:
    def _fail_guard() -> None:
        raise DatabaseMigrationError(
            code="schema_revision_missing",
            message="schema missing",
            details={"current_revision": None, "head_revision": "new"},
        )

    monkeypatch.setattr(worker_main, "assert_schema_current", _fail_guard)

    with pytest.raises(DatabaseMigrationError):
        with TestClient(worker_main.app):
            pass
