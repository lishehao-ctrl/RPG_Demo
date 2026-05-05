from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rpg_backend.narrative.contracts import (
    AdvisorMessage,
    CastMember,
    NarrativeSession,
    NarrativeTemplate,
    StoryMessage,
    StoryOption,
    TemplateVisibility,
)


class NarrativeNotFoundError(LookupError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            CREATE TABLE IF NOT EXISTS narrative_templates (
                template_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                seed TEXT NOT NULL,
                title TEXT NOT NULL,
                cast_json TEXT NOT NULL,
                advisor_persona TEXT NOT NULL,
                opening_passage TEXT NOT NULL,
                opening_options_json TEXT NOT NULL DEFAULT '[]',
                visibility TEXT NOT NULL DEFAULT 'private',
                play_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS narrative_sessions (
                session_id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                player_user_id TEXT NOT NULL,
                turn_count INTEGER NOT NULL DEFAULT 0,
                turn_budget INTEGER NOT NULL DEFAULT 12,
                ending_label TEXT,
                ending_subtitle TEXT,
                ending_passage TEXT,
                created_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL,
                FOREIGN KEY (template_id) REFERENCES narrative_templates(template_id) ON DELETE CASCADE
            )
            """
        )
        # Migrate existing sessions (pre-budget schema) — add columns if missing.
        # Idempotent: SQLite errors silently if column already exists, so we
        # check pragma first.
        existing_cols = {row[1] for row in connection.execute("PRAGMA table_info(narrative_sessions)").fetchall()}
        for col, ddl in (
            ("turn_budget", "ALTER TABLE narrative_sessions ADD COLUMN turn_budget INTEGER NOT NULL DEFAULT 12"),
            ("ending_label", "ALTER TABLE narrative_sessions ADD COLUMN ending_label TEXT"),
            ("ending_subtitle", "ALTER TABLE narrative_sessions ADD COLUMN ending_subtitle TEXT"),
            ("ending_passage", "ALTER TABLE narrative_sessions ADD COLUMN ending_passage TEXT"),
        ):
            if col not in existing_cols:
                connection.execute(ddl)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS narrative_story_messages (
                session_id TEXT NOT NULL,
                ord INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                options_json TEXT NOT NULL DEFAULT '[]',
                chosen_option_index INTEGER,
                PRIMARY KEY (session_id, ord),
                FOREIGN KEY (session_id) REFERENCES narrative_sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS narrative_advisor_messages (
                session_id TEXT NOT NULL,
                ord INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                PRIMARY KEY (session_id, ord),
                FOREIGN KEY (session_id) REFERENCES narrative_sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_narrative_templates_owner "
            "ON narrative_templates(owner_user_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_narrative_templates_public "
            "ON narrative_templates(visibility, created_at DESC) WHERE visibility = 'public'"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_narrative_sessions_player "
            "ON narrative_sessions(player_user_id, last_active_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_narrative_sessions_template "
            "ON narrative_sessions(template_id)"
        )
        connection.commit()

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def create_template(
        self,
        *,
        template_id: str,
        owner_user_id: str,
        seed: str,
        title: str,
        cast: list[CastMember],
        advisor_persona: str,
        opening_passage: str,
        opening_options: list[StoryOption],
        visibility: TemplateVisibility,
    ) -> NarrativeTemplate:
        created_at = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO narrative_templates
                (template_id, owner_user_id, seed, title, cast_json,
                 advisor_persona, opening_passage, opening_options_json,
                 visibility, play_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    template_id,
                    owner_user_id,
                    seed,
                    title,
                    json.dumps([c.model_dump() for c in cast], ensure_ascii=False),
                    advisor_persona,
                    opening_passage,
                    json.dumps([o.model_dump() for o in opening_options], ensure_ascii=False),
                    visibility,
                    created_at,
                ),
            )
            conn.commit()
        return NarrativeTemplate(
            template_id=template_id,
            owner_user_id=owner_user_id,
            seed=seed,
            title=title,
            cast=cast,
            advisor_persona=advisor_persona,
            opening_passage=opening_passage,
            opening_options=opening_options,
            visibility=visibility,
            play_count=0,
            created_at=created_at,
        )

    def get_template(self, template_id: str) -> NarrativeTemplate:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM narrative_templates WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise NarrativeNotFoundError(f"narrative template not found: {template_id}")
        return _row_to_template(row)

    def list_public_templates(self, limit: int = 50) -> list[NarrativeTemplate]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM narrative_templates
                WHERE visibility = 'public'
                ORDER BY play_count DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_template(r) for r in rows]

    def list_templates_for_owner(self, owner_user_id: str) -> list[NarrativeTemplate]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM narrative_templates
                WHERE owner_user_id = ?
                ORDER BY created_at DESC
                """,
                (owner_user_id,),
            ).fetchall()
        return [_row_to_template(r) for r in rows]

    def update_template_visibility(
        self, template_id: str, visibility: TemplateVisibility
    ) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE narrative_templates SET visibility = ? WHERE template_id = ?",
                (visibility, template_id),
            )
            if cur.rowcount == 0:
                raise NarrativeNotFoundError(template_id)
            conn.commit()

    def increment_play_count(self, template_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE narrative_templates SET play_count = play_count + 1 WHERE template_id = ?",
                (template_id,),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(
        self,
        *,
        session_id: str,
        template_id: str,
        player_user_id: str,
        turn_budget: int = 12,
    ) -> NarrativeSession:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO narrative_sessions
                (session_id, template_id, player_user_id, turn_count, turn_budget, created_at, last_active_at)
                VALUES (?, ?, ?, 0, ?, ?, ?)
                """,
                (session_id, template_id, player_user_id, turn_budget, now, now),
            )
            conn.commit()
        return NarrativeSession(
            session_id=session_id,
            template_id=template_id,
            player_user_id=player_user_id,
            turn_count=0,
            turn_budget=turn_budget,
            ending_label=None,
            ending_subtitle=None,
            ending_passage=None,
            created_at=now,
            last_active_at=now,
        )

    def record_session_ending(
        self,
        session_id: str,
        *,
        label: str,
        subtitle: str,
        passage: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE narrative_sessions
                SET ending_label = ?, ending_subtitle = ?, ending_passage = ?, last_active_at = ?
                WHERE session_id = ?
                """,
                (label, subtitle, passage, _utc_now(), session_id),
            )
            conn.commit()

    def list_completed_endings_for_template(
        self, template_id: str
    ) -> list[tuple[str, int]]:
        """Return [(label, count)] for all completed sessions on this template,
        ordered by count desc."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ending_label, COUNT(*) AS n
                FROM narrative_sessions
                WHERE template_id = ? AND ending_label IS NOT NULL
                GROUP BY ending_label
                ORDER BY n DESC, ending_label ASC
                """,
                (template_id,),
            ).fetchall()
        return [(str(row["ending_label"]), int(row["n"])) for row in rows]

    def count_completed_sessions_for_template(self, template_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM narrative_sessions WHERE template_id = ? AND ending_label IS NOT NULL",
                (template_id,),
            ).fetchone()
        return int(row["n"])

    def get_session(self, session_id: str) -> NarrativeSession:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM narrative_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise NarrativeNotFoundError(f"narrative session not found: {session_id}")
        return _row_to_session(row)

    def list_sessions_for_player(self, player_user_id: str) -> list[NarrativeSession]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM narrative_sessions
                WHERE player_user_id = ?
                ORDER BY last_active_at DESC
                """,
                (player_user_id,),
            ).fetchall()
        return [_row_to_session(r) for r in rows]

    def touch_session(self, session_id: str, *, increment_turns: int = 0) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE narrative_sessions
                SET last_active_at = ?, turn_count = turn_count + ?
                WHERE session_id = ?
                """,
                (_utc_now(), increment_turns, session_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Story messages (per session)
    # ------------------------------------------------------------------

    def append_story_message(self, session_id: str, message: StoryMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO narrative_story_messages
                (session_id, ord, role, content, options_json, chosen_option_index)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message.ord,
                    message.role,
                    message.content,
                    json.dumps([o.model_dump() for o in message.options], ensure_ascii=False),
                    message.chosen_option_index,
                ),
            )
            conn.commit()

    def list_story_messages(self, session_id: str) -> list[StoryMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ord, role, content, options_json, chosen_option_index
                FROM narrative_story_messages
                WHERE session_id = ?
                ORDER BY ord ASC
                """,
                (session_id,),
            ).fetchall()
        return [_row_to_story_message(r) for r in rows]

    def next_story_ord(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(ord), -1) AS max_ord FROM narrative_story_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["max_ord"]) + 1

    def update_story_message_choice(
        self, session_id: str, ord_value: int, chosen_option_index: int
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE narrative_story_messages
                SET chosen_option_index = ?
                WHERE session_id = ? AND ord = ?
                """,
                (chosen_option_index, session_id, ord_value),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Advisor messages (per session)
    # ------------------------------------------------------------------

    def append_advisor_message(self, session_id: str, message: AdvisorMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO narrative_advisor_messages
                (session_id, ord, role, content)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, message.ord, message.role, message.content),
            )
            conn.commit()

    def list_advisor_messages(self, session_id: str) -> list[AdvisorMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ord, role, content
                FROM narrative_advisor_messages
                WHERE session_id = ?
                ORDER BY ord ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            AdvisorMessage(
                ord=int(row["ord"]),
                role=row["role"],
                content=row["content"],
            )
            for row in rows
        ]

    def next_advisor_ord(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(ord), -1) AS max_ord FROM narrative_advisor_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["max_ord"]) + 1


# --------------------------------------------------------------------------
# Row → model conversions
# --------------------------------------------------------------------------


def _row_to_template(row: sqlite3.Row) -> NarrativeTemplate:
    cast_raw = json.loads(row["cast_json"])
    cast = [CastMember.model_validate(item) for item in cast_raw]
    options_raw: Any = json.loads(row["opening_options_json"]) if row["opening_options_json"] else []
    options: list[StoryOption] = []
    if isinstance(options_raw, list):
        for item in options_raw:
            if isinstance(item, dict):
                try:
                    options.append(StoryOption.model_validate(item))
                except Exception:  # noqa: BLE001
                    continue
    return NarrativeTemplate(
        template_id=row["template_id"],
        owner_user_id=row["owner_user_id"],
        seed=row["seed"],
        title=row["title"],
        cast=cast,
        advisor_persona=row["advisor_persona"],
        opening_passage=row["opening_passage"],
        opening_options=options,
        visibility=row["visibility"],
        play_count=int(row["play_count"]),
        created_at=row["created_at"],
    )


def _row_to_session(row: sqlite3.Row) -> NarrativeSession:
    keys = row.keys()
    return NarrativeSession(
        session_id=row["session_id"],
        template_id=row["template_id"],
        player_user_id=row["player_user_id"],
        turn_count=int(row["turn_count"]),
        turn_budget=int(row["turn_budget"]) if "turn_budget" in keys else 12,
        ending_label=row["ending_label"] if "ending_label" in keys else None,
        ending_subtitle=row["ending_subtitle"] if "ending_subtitle" in keys else None,
        ending_passage=row["ending_passage"] if "ending_passage" in keys else None,
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
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
