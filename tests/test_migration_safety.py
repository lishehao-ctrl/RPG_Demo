from __future__ import annotations

import json
import sqlite3

from rpg_backend.auth.storage import SQLiteAuthStorage
from rpg_backend.library.storage import SQLiteStoryLibraryStorage


def test_auth_legacy_schema_is_archived_before_username_schema_rebuild(tmp_path) -> None:
    db_path = tmp_path / "auth.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE auth_users (
                user_id TEXT PRIMARY KEY,
                normalized_email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE auth_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO auth_users (
                user_id, normalized_email, password_hash, display_name, created_at
            ) VALUES ('legacy-user', 'legacy@example.com', 'hash', 'Legacy', '2026-05-01T00:00:00')
            """
        )

    storage = SQLiteAuthStorage(str(db_path))
    assert storage.get_user_by_username("new-user") is None

    with sqlite3.connect(db_path) as connection:
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        ]
        legacy_user_tables = [name for name in table_names if name.startswith("auth_users_legacy_")]
        assert legacy_user_tables
        archived_count = connection.execute(
            f"SELECT COUNT(*) FROM {legacy_user_tables[0]} WHERE user_id = 'legacy-user'"
        ).fetchone()[0]
        new_columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(auth_users)").fetchall()
        ]

    assert archived_count == 1
    assert "username" in new_columns
    assert "password_hash" not in new_columns


def test_story_schema_migration_archives_non_v2_rows_before_active_removal(tmp_path) -> None:
    db_path = tmp_path / "stories.sqlite3"
    storage = SQLiteStoryLibraryStorage(str(db_path))
    connection = storage._connect()
    try:
        connection.execute(
            """
            INSERT INTO published_stories (
                story_id, source_job_id, prompt_seed, title, one_liner, premise,
                theme, tone, npc_count, beat_count, topology, owner_user_id,
                visibility, package_version, summary_json, preview_json,
                bundle_json, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-story",
                "legacy-job",
                "legacy seed",
                "Legacy",
                "old",
                "old premise",
                "legacy",
                "legacy",
                1,
                1,
                "solo",
                "owner",
                "private",
                "relationship_drama_v1",
                json.dumps({"title": "Legacy"}),
                json.dumps({"structure": {"cast_topology": "solo"}}),
                json.dumps({"old": True}),
                "2026-05-01T00:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    storage = SQLiteStoryLibraryStorage(str(db_path))
    connection = storage._connect()
    try:
        active_count = connection.execute(
            "SELECT COUNT(*) FROM published_stories WHERE story_id = 'legacy-story'"
        ).fetchone()[0]
        archived = connection.execute(
            """
            SELECT reason, row_json
            FROM published_story_migration_archive
            WHERE story_id = 'legacy-story'
            """
        ).fetchone()
    finally:
        connection.close()

    assert active_count == 0
    assert archived is not None
    assert archived[0] == "non_relationship_drama_v2"
    assert json.loads(archived[1])["source_job_id"] == "legacy-job"
