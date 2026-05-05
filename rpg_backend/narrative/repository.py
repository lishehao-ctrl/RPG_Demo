from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rpg_backend.narrative.contracts import (
    AdvisorMessage,
    CastMember,
    NarrativeWorld,
    StoryMessage,
    StoryOption,
)


class NarrativeNotFoundError(LookupError):
    pass


class NarrativeRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        if self._db_path != ":memory:":
            path = Path(self._db_path)
            if path.parent != Path():
                path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema(connection)
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS narrative_worlds (
                world_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                seed TEXT NOT NULL,
                title TEXT NOT NULL,
                cast_json TEXT NOT NULL,
                advisor_persona TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS narrative_story_messages (
                world_id TEXT NOT NULL,
                ord INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                options_json TEXT NOT NULL DEFAULT '[]',
                chosen_option_index INTEGER,
                PRIMARY KEY (world_id, ord),
                FOREIGN KEY (world_id) REFERENCES narrative_worlds(world_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS narrative_advisor_messages (
                world_id TEXT NOT NULL,
                ord INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                PRIMARY KEY (world_id, ord),
                FOREIGN KEY (world_id) REFERENCES narrative_worlds(world_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_narrative_worlds_owner ON narrative_worlds(owner_user_id, created_at DESC)"
        )
        connection.commit()

    # ------------------------------------------------------------------
    # World CRUD
    # ------------------------------------------------------------------

    def create_world(
        self,
        *,
        world_id: str,
        owner_user_id: str,
        seed: str,
        title: str,
        cast: list[CastMember],
        advisor_persona: str,
    ) -> NarrativeWorld:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO narrative_worlds
                (world_id, owner_user_id, seed, title, cast_json, advisor_persona, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    world_id,
                    owner_user_id,
                    seed,
                    title,
                    json.dumps([c.model_dump() for c in cast], ensure_ascii=False),
                    advisor_persona,
                    created_at,
                ),
            )
            conn.commit()
        return NarrativeWorld(
            world_id=world_id,
            owner_user_id=owner_user_id,
            seed=seed,
            title=title,
            cast=cast,
            advisor_persona=advisor_persona,
            created_at=created_at,
        )

    def get_world(self, world_id: str) -> NarrativeWorld:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM narrative_worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
        if row is None:
            raise NarrativeNotFoundError(f"narrative world not found: {world_id}")
        return _row_to_world(row)

    def list_worlds_for_owner(self, owner_user_id: str) -> list[NarrativeWorld]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM narrative_worlds WHERE owner_user_id = ? ORDER BY created_at DESC",
                (owner_user_id,),
            ).fetchall()
        return [_row_to_world(row) for row in rows]

    # ------------------------------------------------------------------
    # Story messages
    # ------------------------------------------------------------------

    def append_story_message(self, world_id: str, message: StoryMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO narrative_story_messages
                (world_id, ord, role, content, options_json, chosen_option_index)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    world_id,
                    message.ord,
                    message.role,
                    message.content,
                    json.dumps([o.model_dump() for o in message.options], ensure_ascii=False),
                    message.chosen_option_index,
                ),
            )
            conn.commit()

    def list_story_messages(self, world_id: str) -> list[StoryMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ord, role, content, options_json, chosen_option_index
                FROM narrative_story_messages
                WHERE world_id = ?
                ORDER BY ord ASC
                """,
                (world_id,),
            ).fetchall()
        return [_row_to_story_message(row) for row in rows]

    def next_story_ord(self, world_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(ord), -1) AS max_ord FROM narrative_story_messages WHERE world_id = ?",
                (world_id,),
            ).fetchone()
        return int(row["max_ord"]) + 1

    # ------------------------------------------------------------------
    # Advisor messages
    # ------------------------------------------------------------------

    def append_advisor_message(self, world_id: str, message: AdvisorMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO narrative_advisor_messages
                (world_id, ord, role, content)
                VALUES (?, ?, ?, ?)
                """,
                (world_id, message.ord, message.role, message.content),
            )
            conn.commit()

    def list_advisor_messages(self, world_id: str) -> list[AdvisorMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ord, role, content
                FROM narrative_advisor_messages
                WHERE world_id = ?
                ORDER BY ord ASC
                """,
                (world_id,),
            ).fetchall()
        return [
            AdvisorMessage(
                ord=int(row["ord"]),
                role=row["role"],
                content=row["content"],
            )
            for row in rows
        ]

    def next_advisor_ord(self, world_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(ord), -1) AS max_ord FROM narrative_advisor_messages WHERE world_id = ?",
                (world_id,),
            ).fetchone()
        return int(row["max_ord"]) + 1


def _row_to_world(row: sqlite3.Row) -> NarrativeWorld:
    cast_raw = json.loads(row["cast_json"])
    cast = [CastMember.model_validate(item) for item in cast_raw]
    return NarrativeWorld(
        world_id=row["world_id"],
        owner_user_id=row["owner_user_id"],
        seed=row["seed"],
        title=row["title"],
        cast=cast,
        advisor_persona=row["advisor_persona"],
        created_at=row["created_at"],
    )


def _row_to_story_message(row: sqlite3.Row) -> StoryMessage:
    options_raw: Any = json.loads(row["options_json"]) if row["options_json"] else []
    options: list[StoryOption] = []
    if isinstance(options_raw, list):
        for item in options_raw:
            if isinstance(item, dict):
                try:
                    options.append(StoryOption.model_validate(item))
                except Exception:  # noqa: BLE001
                    continue
    chosen = row["chosen_option_index"]
    return StoryMessage(
        ord=int(row["ord"]),
        role=row["role"],
        content=row["content"],
        options=options,
        chosen_option_index=int(chosen) if chosen is not None else None,
    )
