from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from rpg_backend.config import get_settings


def _load_story_ids_to_delete(story_db: str) -> list[str]:
    with sqlite3.connect(story_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT story_id
            FROM published_stories
            WHERE package_version IS NULL OR package_version != 'relationship_drama_v2'
            """
        ).fetchall()
    return [str(row["story_id"]) for row in rows]


def _delete_story_rows(story_db: str, story_ids: list[str]) -> int:
    if not story_ids:
        return 0
    with sqlite3.connect(story_db) as connection:
        connection.executemany(
            "DELETE FROM published_stories WHERE story_id = ?",
            [(story_id,) for story_id in story_ids],
        )
        try:
            connection.executemany(
                "DELETE FROM published_story_search WHERE story_id = ?",
                [(story_id,) for story_id in story_ids],
            )
        except sqlite3.OperationalError:
            pass
        connection.commit()
    return len(story_ids)


def _delete_play_rows(play_db: str, story_ids: list[str]) -> int:
    if not story_ids:
        return 0
    with sqlite3.connect(play_db) as connection:
        cursor = connection.executemany(
            "DELETE FROM play_sessions WHERE story_id = ?",
            [(story_id,) for story_id in story_ids],
        )
        connection.commit()
        return max(int(cursor.rowcount), 0)


def cleanup_non_v2_stories(*, story_db: str, play_db: str) -> dict[str, Any]:
    story_ids = _load_story_ids_to_delete(story_db)
    stories_deleted = _delete_story_rows(story_db, story_ids)
    sessions_deleted = _delete_play_rows(play_db, story_ids)
    return {
        "story_db": story_db,
        "play_db": play_db,
        "stories_deleted": stories_deleted,
        "sessions_deleted": sessions_deleted,
        "deleted_story_ids": story_ids,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Delete non-v2 stories and related play sessions.")
    parser.add_argument(
        "--story-db",
        default=settings.story_library_db_path,
        type=str,
        help="Path to story library sqlite database.",
    )
    parser.add_argument(
        "--play-db",
        default=settings.runtime_state_db_path,
        type=str,
        help="Path to play session sqlite database.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = cleanup_non_v2_stories(story_db=str(Path(args.story_db)), play_db=str(Path(args.play_db)))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
