from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sqlite3
from pathlib import Path

from rpg_backend.author.display import topology_label
from rpg_backend.config import get_settings
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.library.contracts import (
    PublishedStoryCard,
    PublishedStoryRecord,
    PublishedStoryThemeFacet,
)


def _fts_query(value: str) -> str | None:
    terms = re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE)
    if not terms:
        return None
    return " AND ".join(f"{term}*" for term in terms)


@dataclass(frozen=True)
class StoryLibraryPage:
    records: list[PublishedStoryRecord]
    total: int
    theme_facets: list[PublishedStoryThemeFacet]
    next_offset: int | None


class SQLiteStoryLibraryStorage:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._fts_enabled = True

    def _ensure_parent_dir(self) -> None:
        if self._db_path == ":memory:":
            return
        path = Path(self._db_path)
        if path.parent != Path():
            path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        self._ensure_parent_dir()
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        self._ensure_schema(connection)
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS published_stories (
                story_id TEXT PRIMARY KEY,
                source_job_id TEXT NOT NULL UNIQUE,
                prompt_seed TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                one_liner TEXT NOT NULL DEFAULT '',
                premise TEXT NOT NULL DEFAULT '',
                theme TEXT NOT NULL DEFAULT '',
                tone TEXT NOT NULL DEFAULT '',
                npc_count INTEGER NOT NULL DEFAULT 0,
                beat_count INTEGER NOT NULL DEFAULT 0,
                topology TEXT NOT NULL DEFAULT '',
                owner_user_id TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT 'private',
                package_version TEXT NOT NULL DEFAULT 'relationship_drama_v2',
                summary_json TEXT NOT NULL,
                preview_json TEXT NOT NULL,
                bundle_json TEXT NOT NULL,
                published_at TEXT NOT NULL,
                play_count INTEGER NOT NULL DEFAULT 0,
                unique_player_count INTEGER NOT NULL DEFAULT 0,
                ending_distribution_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS story_player_records (
                story_id TEXT NOT NULL,
                player_user_id TEXT NOT NULL,
                first_completed_at TEXT NOT NULL,
                PRIMARY KEY (story_id, player_user_id)
            )
            """
        )
        self._migrate_story_columns(connection)
        self._purge_non_v2_records(connection)
        self._backfill_owner_visibility(connection)
        self._backfill_story_cards(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_published_stories_published_at ON published_stories (published_at DESC, story_id DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_published_stories_theme ON published_stories (theme COLLATE NOCASE)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_published_stories_play_count ON published_stories (play_count DESC, story_id DESC)"
        )
        # One-shot migration: drop rows whose bundle no longer round-trips through
        # the current package contract. We track migration state via PRAGMA
        # user_version so this only runs the first time a fresh schema boots.
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version < 1:
            self._purge_unreadable_records(connection)
            connection.execute("PRAGMA user_version = 1")
        self._ensure_search_index(connection)
        connection.commit()

    def _purge_unreadable_records(self, connection: sqlite3.Connection) -> None:
        """Delete rows whose bundle no longer validates against the current package shape.

        Pre-pivot stories accumulate as the contract evolves; the list endpoint
        skips them at read time, but they still inflate `total` and clutter
        searches. Run once on schema migration to prune them definitively.
        """
        rows = connection.execute("SELECT story_id, bundle_json FROM published_stories").fetchall()
        bad_ids: list[str] = []
        for row in rows:
            payload_text = str(row["bundle_json"] or "")
            if not payload_text:
                bad_ids.append(str(row["story_id"]))
                continue
            try:
                RelationshipDramaV2Package.model_validate_json(payload_text)
            except Exception:  # noqa: BLE001 — validation error or any parse failure
                bad_ids.append(str(row["story_id"]))
        if not bad_ids:
            return
        connection.executemany(
            "DELETE FROM published_stories WHERE story_id = ?",
            [(story_id,) for story_id in bad_ids],
        )
        if self._fts_enabled:
            try:
                connection.executemany(
                    "DELETE FROM published_story_search WHERE story_id = ?",
                    [(story_id,) for story_id in bad_ids],
                )
            except sqlite3.OperationalError:
                self._fts_enabled = False

    def _purge_non_v2_records(self, connection: sqlite3.Connection) -> None:
        story_rows = connection.execute(
            """
            SELECT story_id
            FROM published_stories
            WHERE package_version IS NULL OR package_version != 'relationship_drama_v2'
            """
        ).fetchall()
        story_ids = [str(row["story_id"]) for row in story_rows]
        if not story_ids:
            return
        connection.executemany(
            "DELETE FROM published_stories WHERE story_id = ?",
            [(story_id,) for story_id in story_ids],
        )
        if self._fts_enabled:
            try:
                connection.executemany(
                    "DELETE FROM published_story_search WHERE story_id = ?",
                    [(story_id,) for story_id in story_ids],
                )
            except sqlite3.OperationalError:
                self._fts_enabled = False

    def _migrate_story_columns(self, connection: sqlite3.Connection) -> None:
        required_columns = {
            "title": "TEXT NOT NULL DEFAULT ''",
            "one_liner": "TEXT NOT NULL DEFAULT ''",
            "premise": "TEXT NOT NULL DEFAULT ''",
            "theme": "TEXT NOT NULL DEFAULT ''",
            "tone": "TEXT NOT NULL DEFAULT ''",
            "npc_count": "INTEGER NOT NULL DEFAULT 0",
            "beat_count": "INTEGER NOT NULL DEFAULT 0",
            "topology": "TEXT NOT NULL DEFAULT ''",
            "owner_user_id": f"TEXT NOT NULL DEFAULT '{get_settings().default_actor_id}'",
            "visibility": "TEXT NOT NULL DEFAULT 'private'",
            "package_version": "TEXT NOT NULL DEFAULT 'relationship_drama_v2'",
            "play_count": "INTEGER NOT NULL DEFAULT 0",
            "unique_player_count": "INTEGER NOT NULL DEFAULT 0",
            "ending_distribution_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        existing_columns = set()
        for row in connection.execute("PRAGMA table_info(published_stories)").fetchall():
            if isinstance(row, sqlite3.Row):
                existing_columns.add(str(row["name"]))
            else:
                existing_columns.add(str(row[1]))
        for column_name, definition in required_columns.items():
            if column_name in existing_columns:
                continue
            try:
                connection.execute(
                    f"ALTER TABLE published_stories ADD COLUMN {column_name} {definition}"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    def _backfill_owner_visibility(self, connection: sqlite3.Connection) -> None:
        default_actor_id = get_settings().default_actor_id
        connection.execute(
            """
            UPDATE published_stories
            SET owner_user_id = ?
            WHERE owner_user_id IS NULL OR owner_user_id = ''
            """,
            (default_actor_id,),
        )
        connection.execute(
            """
            UPDATE published_stories
            SET visibility = 'private'
            WHERE visibility IS NULL OR visibility = ''
            """
        )

    @staticmethod
    def _row_card_payload(row: sqlite3.Row) -> dict[str, object]:
        # ending_distribution_json may legitimately be missing on rows from older
        # schemas pre-Phase-B; tolerate that until ALTER+backfill runs.
        try:
            ending_dist_raw = row["ending_distribution_json"]
        except (IndexError, KeyError):
            ending_dist_raw = None
        ending_distribution: dict[str, int] = {}
        if ending_dist_raw:
            try:
                parsed = json.loads(str(ending_dist_raw))
                if isinstance(parsed, dict):
                    ending_distribution = {str(k): int(v) for k, v in parsed.items()}
            except (json.JSONDecodeError, TypeError, ValueError):
                ending_distribution = {}
        try:
            play_count = int(row["play_count"])
        except (IndexError, KeyError, TypeError, ValueError):
            play_count = 0
        try:
            unique_player_count = int(row["unique_player_count"])
        except (IndexError, KeyError, TypeError, ValueError):
            unique_player_count = 0
        return {
            "story_id": row["story_id"],
            "title": row["title"],
            "one_liner": row["one_liner"],
            "premise": row["premise"],
            "theme": row["theme"],
            "tone": row["tone"],
            "npc_count": row["npc_count"],
            "beat_count": row["beat_count"],
            "topology": row["topology"],
            "visibility": row["visibility"],
            "published_at": row["published_at"],
            "play_count": play_count,
            "unique_player_count": unique_player_count,
            "ending_distribution": ending_distribution,
        }

    @classmethod
    def _row_to_record(cls, row: sqlite3.Row) -> PublishedStoryRecord:
        summary_payload = json.loads(str(row["summary_json"]))
        preview_payload = json.loads(str(row["preview_json"]))
        bundle_payload = json.loads(str(row["bundle_json"]))
        story = PublishedStoryCard.model_validate(cls._row_card_payload(row))
        return PublishedStoryRecord.model_validate(
            {
                "story": story.model_dump(mode="json"),
                "owner_user_id": row["owner_user_id"],
                "source_job_id": row["source_job_id"],
                "prompt_seed": row["prompt_seed"],
                "visibility": row["visibility"],
                "package_version": "relationship_drama_v2",
                "summary": summary_payload,
                "preview": preview_payload,
                "bundle": RelationshipDramaV2Package.model_validate(bundle_payload),
            }
        )

    @classmethod
    def _row_to_record_safe(cls, row: sqlite3.Row) -> PublishedStoryRecord | None:
        """List-side hydration that tolerates rows whose bundle no longer matches.

        Pre-pivot stories live in the same DB but their bundle schema doesn't
        round-trip through the current package contract. Browsing endpoints
        should silently skip those rows; detail endpoints (which call the
        strict version) still surface a 404 instead.
        """
        try:
            return cls._row_to_record(row)
        except Exception:  # noqa: BLE001 — pydantic ValidationError or similar
            return None

    @staticmethod
    def _story_columns_from_payloads(
        *,
        summary_payload: dict[str, object],
        preview_payload: dict[str, object],
    ) -> dict[str, object]:
        structure = preview_payload.get("structure") if isinstance(preview_payload, dict) else None
        cast_topology = structure.get("cast_topology") if isinstance(structure, dict) else ""
        return {
            "title": summary_payload.get("title") or "",
            "one_liner": summary_payload.get("one_liner") or "",
            "premise": summary_payload.get("premise") or "",
            "theme": summary_payload.get("theme") or "",
            "tone": summary_payload.get("tone") or "",
            "npc_count": int(summary_payload.get("npc_count") or 0),
            "beat_count": int(summary_payload.get("beat_count") or 0),
            "topology": topology_label(str(cast_topology)),
        }

    def _backfill_story_cards(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT story_id, summary_json, preview_json
            FROM published_stories
            WHERE title = ''
               OR one_liner = ''
               OR premise = ''
               OR theme = ''
               OR tone = ''
               OR npc_count = 0
               OR beat_count = 0
               OR topology = ''
            """
        ).fetchall()
        for row in rows:
            summary_payload = json.loads(str(row["summary_json"]))
            preview_payload = json.loads(str(row["preview_json"]))
            columns = self._story_columns_from_payloads(
                summary_payload=summary_payload,
                preview_payload=preview_payload,
            )
            connection.execute(
                """
                UPDATE published_stories
                SET title = :title,
                    one_liner = :one_liner,
                    premise = :premise,
                    theme = :theme,
                    tone = :tone,
                    npc_count = :npc_count,
                    beat_count = :beat_count,
                    topology = :topology
                WHERE story_id = :story_id
                """,
                {
                    "story_id": row["story_id"],
                    **columns,
                },
            )

    def _ensure_search_index(self, connection: sqlite3.Connection) -> None:
        if not self._fts_enabled:
            return
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS published_story_search
                USING fts5(
                    story_id UNINDEXED,
                    title,
                    one_liner,
                    premise,
                    theme,
                    tone,
                    prompt_seed,
                    tokenize = 'porter unicode61'
                )
                """
            )
        except sqlite3.OperationalError:
            self._fts_enabled = False
            return
        story_count = int(
            connection.execute("SELECT COUNT(*) FROM published_stories").fetchone()[0]
        )
        search_count = int(
            connection.execute("SELECT COUNT(*) FROM published_story_search").fetchone()[0]
        )
        if story_count == search_count:
            return
        connection.execute("DELETE FROM published_story_search")
        connection.execute(
            """
            INSERT INTO published_story_search (
                story_id, title, one_liner, premise, theme, tone, prompt_seed
            )
            SELECT story_id, title, one_liner, premise, theme, tone, prompt_seed
            FROM published_stories
            """
        )

    def _insert_search_document(self, connection: sqlite3.Connection, record: PublishedStoryRecord) -> None:
        if not self._fts_enabled:
            return
        try:
            connection.execute(
                """
                INSERT INTO published_story_search (
                    story_id, title, one_liner, premise, theme, tone, prompt_seed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.story.story_id,
                    record.story.title,
                    record.story.one_liner,
                    record.story.premise,
                    record.story.theme,
                    record.story.tone,
                    record.prompt_seed,
                ),
            )
        except sqlite3.OperationalError:
            self._fts_enabled = False

    def get_by_source_job_id(self, source_job_id: str) -> PublishedStoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM published_stories
                WHERE source_job_id = ?
                """,
                (source_job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_story(self, story_id: str) -> PublishedStoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM published_stories
                WHERE story_id = ?
                """,
                (story_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    @staticmethod
    def _visibility_clause(*, include_public: bool, table_alias: str | None = None) -> str:
        owner_column = f"{table_alias}.owner_user_id" if table_alias else "owner_user_id"
        visibility_column = f"{table_alias}.visibility" if table_alias else "visibility"
        if include_public:
            return f"({owner_column} = ? OR {visibility_column} = 'public')"
        return f"{owner_column} = ?"

    @staticmethod
    def _public_only_clause(*, table_alias: str | None = None) -> str:
        visibility_column = f"{table_alias}.visibility" if table_alias else "visibility"
        return f"{visibility_column} = 'public'"

    def list_stories(
        self,
        *,
        actor_user_id: str | None,
        query: str | None = None,
        theme: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: str = "published_at_desc",
        include_public: bool = True,
        public_only: bool = False,
    ) -> StoryLibraryPage:
        with self._connect() as connection:
            total = self._count_matching_stories(
                connection,
                actor_user_id=actor_user_id,
                query=query,
                theme=theme,
                include_public=include_public,
                public_only=public_only,
            )
            facets = self._theme_facets(
                connection,
                actor_user_id=actor_user_id,
                query=query,
                include_public=include_public,
                public_only=public_only,
            )
            rows = self._search_rows(
                connection,
                actor_user_id=actor_user_id,
                query=query,
                theme=theme,
                limit=limit + 1,
                offset=offset,
                sort=sort,
                include_public=include_public,
                public_only=public_only,
            )
        records = [r for r in (self._row_to_record_safe(row) for row in rows[:limit]) if r is not None]
        has_more = len(rows) > limit
        next_offset = offset + limit if has_more else None
        return StoryLibraryPage(
            records=records,
            total=total,
            theme_facets=facets,
            next_offset=next_offset,
        )

    def _count_matching_stories(
        self,
        connection: sqlite3.Connection,
        *,
        actor_user_id: str | None,
        query: str | None,
        theme: str | None,
        include_public: bool,
        public_only: bool,
    ) -> int:
        if public_only:
            filters: list[str] = [self._public_only_clause()]
            params: list[object] = []
        else:
            if actor_user_id is None:
                raise ValueError("actor_user_id is required when public_only is false")
            filters = [self._visibility_clause(include_public=include_public)]
            params = [actor_user_id]
        if query and self._fts_enabled:
            fts_query = _fts_query(query)
            if fts_query:
                filters.append(
                    """
                    story_id IN (
                        SELECT story_id
                        FROM published_story_search
                        WHERE published_story_search MATCH ?
                    )
                    """
                )
                params.append(fts_query)
        elif query:
            like_value = f"%{query.strip()}%"
            filters.append(
                """
                (
                    title LIKE ? COLLATE NOCASE
                    OR one_liner LIKE ? COLLATE NOCASE
                    OR premise LIKE ? COLLATE NOCASE
                    OR theme LIKE ? COLLATE NOCASE
                    OR tone LIKE ? COLLATE NOCASE
                    OR prompt_seed LIKE ? COLLATE NOCASE
                )
                """
            )
            params.extend([like_value] * 6)
        if theme:
            filters.append("theme = ? COLLATE NOCASE")
            params.append(theme.strip())
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        row = connection.execute(
            f"SELECT COUNT(*) AS count FROM published_stories {where_clause}",
            params,
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    def _theme_facets(
        self,
        connection: sqlite3.Connection,
        *,
        actor_user_id: str | None,
        query: str | None,
        include_public: bool,
        public_only: bool,
    ) -> list[PublishedStoryThemeFacet]:
        if public_only:
            params: list[object] = []
            where_clause = f"WHERE {self._public_only_clause()}"
        else:
            if actor_user_id is None:
                raise ValueError("actor_user_id is required when public_only is false")
            params = [actor_user_id]
            where_clause = f"WHERE {self._visibility_clause(include_public=include_public)}"
        if query and self._fts_enabled:
            fts_query = _fts_query(query)
            if fts_query:
                where_clause += (
                    """
                    AND story_id IN (
                        SELECT story_id
                        FROM published_story_search
                        WHERE published_story_search MATCH ?
                    )
                    """
                )
                params.append(fts_query)
        elif query:
            like_value = f"%{query.strip()}%"
            where_clause += (
                """
                AND (
                    title LIKE ? COLLATE NOCASE
                    OR one_liner LIKE ? COLLATE NOCASE
                    OR premise LIKE ? COLLATE NOCASE
                    OR theme LIKE ? COLLATE NOCASE
                    OR tone LIKE ? COLLATE NOCASE
                    OR prompt_seed LIKE ? COLLATE NOCASE
                )
                """
            )
            params.extend([like_value] * 6)
        rows = connection.execute(
            f"""
            SELECT theme, COUNT(*) AS count
            FROM published_stories
            {where_clause}
            GROUP BY theme
            ORDER BY count DESC, theme ASC
            """,
            params,
        ).fetchall()
        return [
            PublishedStoryThemeFacet.model_validate(
                {
                    "theme": row["theme"],
                    "count": row["count"],
                }
            )
            for row in rows
            if str(row["theme"]).strip()
        ]

    def _search_rows(
        self,
        connection: sqlite3.Connection,
        *,
        actor_user_id: str | None,
        query: str | None,
        theme: str | None,
        limit: int,
        offset: int,
        sort: str,
        include_public: bool,
        public_only: bool,
    ) -> list[sqlite3.Row]:
        if query:
            return self._search_rows_by_query(
                connection,
                actor_user_id=actor_user_id,
                query=query,
                theme=theme,
                limit=limit,
                offset=offset,
                sort=sort,
                include_public=include_public,
                public_only=public_only,
            )
        if public_only:
            params: list[object] = []
            where_clause = f"WHERE {self._public_only_clause()}"
        else:
            if actor_user_id is None:
                raise ValueError("actor_user_id is required when public_only is false")
            params = [actor_user_id]
            where_clause = f"WHERE {self._visibility_clause(include_public=include_public)}"
        if theme:
            where_clause += " AND theme = ? COLLATE NOCASE"
            params.append(theme.strip())
        order_clause = (
            "play_count DESC, published_at DESC, story_id DESC"
            if sort == "play_count_desc"
            else "published_at DESC, story_id DESC"
        )
        return connection.execute(
            f"""
            SELECT *
            FROM published_stories
            {where_clause}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    def _search_rows_by_query(
        self,
        connection: sqlite3.Connection,
        *,
        actor_user_id: str | None,
        query: str,
        theme: str | None,
        limit: int,
        offset: int,
        sort: str,
        include_public: bool,
        public_only: bool,
    ) -> list[sqlite3.Row]:
        if not self._fts_enabled:
            return self._search_rows_by_like(
                connection,
                actor_user_id=actor_user_id,
                query=query,
                theme=theme,
                limit=limit,
                offset=offset,
                sort=sort,
                include_public=include_public,
                public_only=public_only,
            )
        fts_query = _fts_query(query)
        if fts_query is None:
            return self._search_rows_by_like(
                connection,
                actor_user_id=actor_user_id,
                query=query,
                theme=theme,
                limit=limit,
                offset=offset,
                sort=sort,
                include_public=include_public,
                public_only=public_only,
            )
        order_clause = (
            "rank ASC, stories.published_at DESC, stories.story_id DESC"
            if sort == "relevance"
            else "stories.play_count DESC, stories.published_at DESC, stories.story_id DESC"
            if sort == "play_count_desc"
            else "stories.published_at DESC, stories.story_id DESC"
        )
        if public_only:
            params: list[object] = [fts_query]
            scope_clause = self._public_only_clause(table_alias="stories")
        else:
            if actor_user_id is None:
                raise ValueError("actor_user_id is required when public_only is false")
            params = [fts_query, actor_user_id]
            scope_clause = self._visibility_clause(include_public=include_public, table_alias="stories")
        theme_clause = ""
        if theme:
            theme_clause = "AND stories.theme = ? COLLATE NOCASE"
            params.append(theme.strip())
        return connection.execute(
            f"""
            SELECT stories.*, bm25(published_story_search, 8.0, 4.0, 3.0, 1.5, 1.0, 0.5) AS rank
            FROM published_story_search
            JOIN published_stories AS stories
                ON stories.story_id = published_story_search.story_id
            WHERE published_story_search MATCH ?
            AND {scope_clause}
            {theme_clause}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    def _search_rows_by_like(
        self,
        connection: sqlite3.Connection,
        *,
        actor_user_id: str | None,
        query: str,
        theme: str | None,
        limit: int,
        offset: int,
        sort: str,
        include_public: bool,
        public_only: bool,
    ) -> list[sqlite3.Row]:
        like_value = f"%{query.strip()}%"
        if public_only:
            params: list[object] = [*([like_value] * 6)]
            scope_clause = self._public_only_clause()
        else:
            if actor_user_id is None:
                raise ValueError("actor_user_id is required when public_only is false")
            params = [actor_user_id, *([like_value] * 6)]
            scope_clause = self._visibility_clause(include_public=include_public)
        theme_clause = ""
        if theme:
            theme_clause = "AND theme = ? COLLATE NOCASE"
            params.append(theme.strip())
        order_clause = (
            """
            (
                (CASE WHEN title LIKE ? COLLATE NOCASE THEN 6 ELSE 0 END)
                + (CASE WHEN one_liner LIKE ? COLLATE NOCASE THEN 4 ELSE 0 END)
                + (CASE WHEN premise LIKE ? COLLATE NOCASE THEN 3 ELSE 0 END)
                + (CASE WHEN theme LIKE ? COLLATE NOCASE THEN 2 ELSE 0 END)
                + (CASE WHEN tone LIKE ? COLLATE NOCASE THEN 1 ELSE 0 END)
                + (CASE WHEN prompt_seed LIKE ? COLLATE NOCASE THEN 1 ELSE 0 END)
            ) DESC,
            published_at DESC,
            story_id DESC
            """
            if sort == "relevance"
            else "published_at DESC, story_id DESC"
        )
        return connection.execute(
            f"""
            SELECT *
            FROM published_stories
            WHERE {scope_clause}
            AND (
                title LIKE ? COLLATE NOCASE
                OR one_liner LIKE ? COLLATE NOCASE
                OR premise LIKE ? COLLATE NOCASE
                OR theme LIKE ? COLLATE NOCASE
                OR tone LIKE ? COLLATE NOCASE
                OR prompt_seed LIKE ? COLLATE NOCASE
            )
            {theme_clause}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
            """,
            [
                *params,
                *([like_value] * 6 if sort == "relevance" else []),
                limit,
                offset,
            ],
        ).fetchall()

    def insert_story(self, record: PublishedStoryRecord) -> PublishedStoryRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO published_stories (
                    story_id,
                    source_job_id,
                    prompt_seed,
                    title,
                    one_liner,
                    premise,
                    theme,
                    tone,
                    npc_count,
                    beat_count,
                    topology,
                    owner_user_id,
                    visibility,
                    package_version,
                    summary_json,
                    preview_json,
                    bundle_json,
                    published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.story.story_id,
                    record.source_job_id,
                    record.prompt_seed,
                    record.story.title,
                    record.story.one_liner,
                    record.story.premise,
                    record.story.theme,
                    record.story.tone,
                    record.story.npc_count,
                    record.story.beat_count,
                    record.story.topology,
                    record.owner_user_id,
                    record.visibility,
                    record.package_version,
                    record.summary.model_dump_json(),
                    record.preview.model_dump_json(),
                    record.bundle.model_dump_json(),
                    record.story.published_at.isoformat(),
                ),
            )
            self._insert_search_document(connection, record)
            connection.commit()
        return record

    def update_story_visibility(self, *, story_id: str, visibility: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE published_stories
                SET visibility = ?
                WHERE story_id = ?
                """,
                (visibility, story_id),
            )
            connection.commit()

    _ENDING_ID_MAX_LEN = 80
    _ENDING_DIST_MAX_KEYS = 20  # cap to avoid unbounded growth from junk ending_ids

    def record_play_completion(
        self,
        *,
        story_id: str,
        player_user_id: str | None,
        ending_id: str,
        completed_at: datetime,
    ) -> None:
        """Bump play_count and (for distinct logged-in players) unique_player_count.

        Anonymous plays (player_user_id is None) increment play_count and the
        ending_distribution but do not contribute to unique_player_count.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT play_count, unique_player_count, ending_distribution_json FROM published_stories WHERE story_id = ?",
                (story_id,),
            ).fetchone()
            if row is None:
                return
            try:
                ending_distribution = json.loads(str(row["ending_distribution_json"] or "{}"))
                if not isinstance(ending_distribution, dict):
                    ending_distribution = {}
            except (json.JSONDecodeError, TypeError):
                ending_distribution = {}
            # Sanitize the ending_id key — bounded length, fall back to "unknown"
            # for empty or whitespace. Drop the new key silently if the dict is
            # already at the per-world cap (and the key is novel) to avoid
            # unbounded growth from buggy upstream data.
            ending_key = (str(ending_id) or "").strip()[: self._ENDING_ID_MAX_LEN] or "unknown"
            if ending_key in ending_distribution or len(ending_distribution) < self._ENDING_DIST_MAX_KEYS:
                ending_distribution[ending_key] = int(ending_distribution.get(ending_key, 0)) + 1
            new_play_count = int(row["play_count"]) + 1
            new_unique = int(row["unique_player_count"])

            if player_user_id:
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO story_player_records (story_id, player_user_id, first_completed_at)
                    VALUES (?, ?, ?)
                    """,
                    (story_id, player_user_id, completed_at.isoformat()),
                ).rowcount
                if inserted:
                    new_unique += 1

            connection.execute(
                """
                UPDATE published_stories
                SET play_count = ?,
                    unique_player_count = ?,
                    ending_distribution_json = ?
                WHERE story_id = ?
                """,
                (new_play_count, new_unique, json.dumps(ending_distribution), story_id),
            )
            connection.commit()

    def delete_story(self, *, story_id: str, owner_user_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM published_stories
                WHERE story_id = ? AND owner_user_id = ?
                """,
                (story_id, owner_user_id),
            )
            if self._fts_enabled:
                try:
                    connection.execute(
                        "DELETE FROM published_story_search WHERE story_id = ?",
                        (story_id,),
                    )
                except sqlite3.OperationalError:
                    self._fts_enabled = False
            connection.commit()
            return cursor.rowcount > 0

    def delete_non_v2_stories(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT story_id
                FROM published_stories
                WHERE package_version IS NULL OR package_version != 'relationship_drama_v2'
                """
            ).fetchall()
            story_ids = [str(row["story_id"]) for row in rows]
            if not story_ids:
                return []
            connection.executemany(
                "DELETE FROM published_stories WHERE story_id = ?",
                [(story_id,) for story_id in story_ids],
            )
            if self._fts_enabled:
                try:
                    connection.executemany(
                        "DELETE FROM published_story_search WHERE story_id = ?",
                        [(story_id,) for story_id in story_ids],
                    )
                except sqlite3.OperationalError:
                    self._fts_enabled = False
            connection.commit()
            return story_ids
