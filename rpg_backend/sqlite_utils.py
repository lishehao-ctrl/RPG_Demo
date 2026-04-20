from __future__ import annotations

from pathlib import Path
import sqlite3


def ensure_sqlite_parent_dir(db_path: str) -> None:
    if db_path == ":memory:":
        return
    path = Path(db_path)
    if path.parent != Path():
        path.parent.mkdir(parents=True, exist_ok=True)


def connect_sqlite(db_path: str) -> sqlite3.Connection:
    ensure_sqlite_parent_dir(db_path)
    # Use an explicit busy timeout to avoid transient lock failures under threaded workloads.
    connection = sqlite3.connect(db_path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        # When another writer briefly holds the lock, keep the connection usable
        # and rely on the existing journal mode on disk.
        pass
    connection.execute("PRAGMA foreign_keys=ON")
    return connection
