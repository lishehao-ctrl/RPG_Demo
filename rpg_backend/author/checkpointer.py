from __future__ import annotations

import json
import random
import sqlite3
from functools import lru_cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    SerializerProtocol,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from rpg_backend.author.contracts import (
    BeatPlanDraft,
    BeatSpec,
    CastDraft,
    CastOverviewDraft,
    DesignBundle,
    EndingIntentDraft,
    EndingRulesDraft,
    FocusedBrief,
    NormalizedSeedPacket,
    OverviewCastDraft,
    RouteAffordancePackDraft,
    RouteOpportunityPlanDraft,
    RulePack,
    StateSchema,
    StoryBible,
    StoryFrameDraft,
)
from rpg_backend.config import Settings, get_settings
from rpg_backend.sqlite_utils import connect_sqlite


AUTHOR_CHECKPOINT_ALLOWLIST = (
    FocusedBrief,
    NormalizedSeedPacket,
    StoryFrameDraft,
    CastOverviewDraft,
    OverviewCastDraft,
    CastDraft,
    BeatPlanDraft,
    StoryBible,
    StateSchema,
    BeatSpec,
    DesignBundle,
    RouteOpportunityPlanDraft,
    RouteAffordancePackDraft,
    EndingIntentDraft,
    EndingRulesDraft,
    RulePack,
)


class SQLiteCheckpointSaver(BaseCheckpointSaver[str]):
    def __init__(self, db_path: str, *, serde: SerializerProtocol | None = None) -> None:
        super().__init__(
            serde=serde or JsonPlusSerializer(allowed_msgpack_modules=AUTHOR_CHECKPOINT_ALLOWLIST)
        )
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        connection = connect_sqlite(self._db_path)
        self._ensure_schema(connection)
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS author_checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                checkpoint_type TEXT NOT NULL,
                checkpoint_blob BLOB NOT NULL,
                metadata_type TEXT NOT NULL,
                metadata_blob BLOB NOT NULL,
                parent_checkpoint_id TEXT,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS author_checkpoint_writes (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                write_idx INTEGER NOT NULL,
                channel TEXT NOT NULL,
                value_type TEXT NOT NULL,
                value_blob BLOB NOT NULL,
                task_path TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS author_checkpoint_blobs (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL,
                channel TEXT NOT NULL,
                version_key TEXT NOT NULL,
                value_type TEXT NOT NULL,
                value_blob BLOB NOT NULL,
                PRIMARY KEY (thread_id, checkpoint_ns, channel, version_key)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_author_checkpoints_thread ON author_checkpoints (thread_id, checkpoint_ns, checkpoint_id DESC)"
        )
        connection.commit()

    @staticmethod
    def _version_key(version: str | int | float) -> str:
        return json.dumps(version, ensure_ascii=True, separators=(",", ":"))

    def _load_blobs(
        self,
        connection: sqlite3.Connection,
        thread_id: str,
        checkpoint_ns: str,
        versions: ChannelVersions,
    ) -> dict[str, Any]:
        channel_values: dict[str, Any] = {}
        for channel, version in versions.items():
            row = connection.execute(
                """
                SELECT value_type, value_blob
                FROM author_checkpoint_blobs
                WHERE thread_id = ?
                  AND checkpoint_ns = ?
                  AND channel = ?
                  AND version_key = ?
                """,
                (thread_id, checkpoint_ns, channel, self._version_key(version)),
            ).fetchone()
            if row is None:
                continue
            typed_value = (str(row["value_type"]), bytes(row["value_blob"]))
            if typed_value[0] != "empty":
                channel_values[channel] = self.serde.loads_typed(typed_value)
        return channel_values

    def _load_writes(
        self,
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> list[tuple[str, str, Any]]:
        rows = connection.execute(
            """
            SELECT task_id, channel, value_type, value_blob
            FROM author_checkpoint_writes
            WHERE thread_id = ?
              AND checkpoint_ns = ?
              AND checkpoint_id = ?
            ORDER BY write_idx ASC, task_id ASC
            """,
            (thread_id, checkpoint_ns, checkpoint_id),
        ).fetchall()
        return [
            (
                str(row["task_id"]),
                str(row["channel"]),
                self.serde.loads_typed((str(row["value_type"]), bytes(row["value_blob"]))),
            )
            for row in rows
        ]

    def _checkpoint_tuple_from_row(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> CheckpointTuple:
        thread_id = str(row["thread_id"])
        checkpoint_ns = str(row["checkpoint_ns"])
        checkpoint_id = str(row["checkpoint_id"])
        checkpoint = self.serde.loads_typed((str(row["checkpoint_type"]), bytes(row["checkpoint_blob"])))
        metadata = self.serde.loads_typed((str(row["metadata_type"]), bytes(row["metadata_blob"])))
        checkpoint_with_values = {
            **checkpoint,
            "channel_values": self._load_blobs(connection, thread_id, checkpoint_ns, checkpoint["channel_versions"]),
        }
        parent_checkpoint_id = row["parent_checkpoint_id"]
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint_with_values,
            metadata=metadata,
            pending_writes=self._load_writes(
                connection,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
            ),
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": str(parent_checkpoint_id),
                    }
                }
                if parent_checkpoint_id
                else None
            ),
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)
        with self._connect() as connection:
            if checkpoint_id:
                row = connection.execute(
                    """
                    SELECT *
                    FROM author_checkpoints
                    WHERE thread_id = ?
                      AND checkpoint_ns = ?
                      AND checkpoint_id = ?
                    """,
                    (thread_id, checkpoint_ns, checkpoint_id),
                ).fetchone()
                if row is None:
                    return None
                return self._checkpoint_tuple_from_row(connection, row)
            row = connection.execute(
                """
                SELECT *
                FROM author_checkpoints
                WHERE thread_id = ?
                  AND checkpoint_ns = ?
                ORDER BY checkpoint_id DESC
                LIMIT 1
                """,
                (thread_id, checkpoint_ns),
            ).fetchone()
            if row is None:
                return None
            return self._checkpoint_tuple_from_row(connection, row)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ):
        thread_id = config["configurable"]["thread_id"] if config else None
        checkpoint_ns = config["configurable"].get("checkpoint_ns") if config else None
        checkpoint_id = get_checkpoint_id(config) if config else None
        before_checkpoint_id = get_checkpoint_id(before) if before else None
        query = [
            "SELECT * FROM author_checkpoints WHERE 1=1",
        ]
        params: list[Any] = []
        if thread_id is not None:
            query.append("AND thread_id = ?")
            params.append(thread_id)
        if checkpoint_ns is not None:
            query.append("AND checkpoint_ns = ?")
            params.append(checkpoint_ns)
        if checkpoint_id is not None:
            query.append("AND checkpoint_id = ?")
            params.append(checkpoint_id)
        if before_checkpoint_id is not None:
            query.append("AND checkpoint_id < ?")
            params.append(before_checkpoint_id)
        query.append("ORDER BY thread_id ASC, checkpoint_ns ASC, checkpoint_id DESC")
        with self._connect() as connection:
            rows = connection.execute(" ".join(query), params).fetchall()
            remaining = limit
            for row in rows:
                tuple_ = self._checkpoint_tuple_from_row(connection, row)
                if filter and not all(tuple_.metadata.get(key) == value for key, value in filter.items()):
                    continue
                yield tuple_
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        break

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        checkpoint_copy = checkpoint.copy()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = str(checkpoint["id"])
        values: dict[str, Any] = checkpoint_copy.pop("channel_values")  # type: ignore[misc]
        with self._connect() as connection:
            for channel, version in new_versions.items():
                if channel in values:
                    value_type, value_blob = self.serde.dumps_typed(values[channel])
                else:
                    value_type, value_blob = ("empty", b"")
                connection.execute(
                    """
                    INSERT INTO author_checkpoint_blobs (
                        thread_id, checkpoint_ns, channel, version_key, value_type, value_blob
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(thread_id, checkpoint_ns, channel, version_key) DO UPDATE SET
                        value_type = excluded.value_type,
                        value_blob = excluded.value_blob
                    """,
                    (
                        thread_id,
                        checkpoint_ns,
                        channel,
                        self._version_key(version),
                        value_type,
                        value_blob,
                    ),
                )
            checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint_copy)
            metadata_type, metadata_blob = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
            connection.execute(
                """
                INSERT INTO author_checkpoints (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    checkpoint_type,
                    checkpoint_blob,
                    metadata_type,
                    metadata_blob,
                    parent_checkpoint_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET
                    checkpoint_type = excluded.checkpoint_type,
                    checkpoint_blob = excluded.checkpoint_blob,
                    metadata_type = excluded.metadata_type,
                    metadata_blob = excluded.metadata_blob,
                    parent_checkpoint_id = excluded.parent_checkpoint_id
                """,
                (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    checkpoint_type,
                    checkpoint_blob,
                    metadata_type,
                    metadata_blob,
                    config["configurable"].get("checkpoint_id"),
                ),
            )
            connection.commit()
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes,
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        with self._connect() as connection:
            for index, (channel, value) in enumerate(writes):
                write_idx = WRITES_IDX_MAP.get(channel, index)
                value_type, value_blob = self.serde.dumps_typed(value)
                if write_idx >= 0:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO author_checkpoint_writes (
                            thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx, channel, value_type, value_blob, task_path
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            thread_id,
                            checkpoint_ns,
                            checkpoint_id,
                            task_id,
                            write_idx,
                            channel,
                            value_type,
                            value_blob,
                            task_path,
                        ),
                    )
                    continue
                connection.execute(
                    """
                    INSERT INTO author_checkpoint_writes (
                        thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx, channel, value_type, value_blob, task_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx) DO UPDATE SET
                        channel = excluded.channel,
                        value_type = excluded.value_type,
                        value_blob = excluded.value_blob,
                        task_path = excluded.task_path
                    """,
                    (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        task_id,
                        write_idx,
                        channel,
                        value_type,
                        value_blob,
                        task_path,
                    ),
                )
            connection.commit()

    def delete_thread(self, thread_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM author_checkpoints WHERE thread_id = ?", (thread_id,))
            connection.execute("DELETE FROM author_checkpoint_writes WHERE thread_id = ?", (thread_id,))
            connection.execute("DELETE FROM author_checkpoint_blobs WHERE thread_id = ?", (thread_id,))
            connection.commit()

    def delete_for_runs(self, run_ids) -> None:
        for run_id in run_ids:
            self.delete_thread(str(run_id))

    def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        with self._connect() as connection:
            checkpoint_rows = connection.execute(
                "SELECT * FROM author_checkpoints WHERE thread_id = ?",
                (source_thread_id,),
            ).fetchall()
            for row in checkpoint_rows:
                connection.execute(
                    """
                    INSERT INTO author_checkpoints (
                        thread_id, checkpoint_ns, checkpoint_id, checkpoint_type, checkpoint_blob, metadata_type, metadata_blob, parent_checkpoint_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET
                        checkpoint_type = excluded.checkpoint_type,
                        checkpoint_blob = excluded.checkpoint_blob,
                        metadata_type = excluded.metadata_type,
                        metadata_blob = excluded.metadata_blob,
                        parent_checkpoint_id = excluded.parent_checkpoint_id
                    """,
                    (
                        target_thread_id,
                        row["checkpoint_ns"],
                        row["checkpoint_id"],
                        row["checkpoint_type"],
                        row["checkpoint_blob"],
                        row["metadata_type"],
                        row["metadata_blob"],
                        row["parent_checkpoint_id"],
                    ),
                )
            write_rows = connection.execute(
                "SELECT * FROM author_checkpoint_writes WHERE thread_id = ?",
                (source_thread_id,),
            ).fetchall()
            for row in write_rows:
                connection.execute(
                    """
                    INSERT INTO author_checkpoint_writes (
                        thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx, channel, value_type, value_blob, task_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx) DO UPDATE SET
                        channel = excluded.channel,
                        value_type = excluded.value_type,
                        value_blob = excluded.value_blob,
                        task_path = excluded.task_path
                    """,
                    (
                        target_thread_id,
                        row["checkpoint_ns"],
                        row["checkpoint_id"],
                        row["task_id"],
                        row["write_idx"],
                        row["channel"],
                        row["value_type"],
                        row["value_blob"],
                        row["task_path"],
                    ),
                )
            blob_rows = connection.execute(
                "SELECT * FROM author_checkpoint_blobs WHERE thread_id = ?",
                (source_thread_id,),
            ).fetchall()
            for row in blob_rows:
                connection.execute(
                    """
                    INSERT INTO author_checkpoint_blobs (
                        thread_id, checkpoint_ns, channel, version_key, value_type, value_blob
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(thread_id, checkpoint_ns, channel, version_key) DO UPDATE SET
                        value_type = excluded.value_type,
                        value_blob = excluded.value_blob
                    """,
                    (
                        target_thread_id,
                        row["checkpoint_ns"],
                        row["channel"],
                        row["version_key"],
                        row["value_type"],
                        row["value_blob"],
                    ),
                )
            connection.commit()

    def prune(self, thread_ids, *, strategy: str = "keep_latest") -> None:
        with self._connect() as connection:
            for thread_id in thread_ids:
                if strategy == "delete":
                    connection.execute("DELETE FROM author_checkpoints WHERE thread_id = ?", (thread_id,))
                    connection.execute("DELETE FROM author_checkpoint_writes WHERE thread_id = ?", (thread_id,))
                    connection.execute("DELETE FROM author_checkpoint_blobs WHERE thread_id = ?", (thread_id,))
                    continue
                namespaces = connection.execute(
                    "SELECT DISTINCT checkpoint_ns FROM author_checkpoints WHERE thread_id = ?",
                    (thread_id,),
                ).fetchall()
                for namespace_row in namespaces:
                    checkpoint_ns = str(namespace_row["checkpoint_ns"])
                    latest = connection.execute(
                        """
                        SELECT checkpoint_id
                        FROM author_checkpoints
                        WHERE thread_id = ?
                          AND checkpoint_ns = ?
                        ORDER BY checkpoint_id DESC
                        LIMIT 1
                        """,
                        (thread_id, checkpoint_ns),
                    ).fetchone()
                    if latest is None:
                        continue
                    latest_id = str(latest["checkpoint_id"])
                    connection.execute(
                        """
                        DELETE FROM author_checkpoints
                        WHERE thread_id = ?
                          AND checkpoint_ns = ?
                          AND checkpoint_id != ?
                        """,
                        (thread_id, checkpoint_ns, latest_id),
                    )
                    connection.execute(
                        """
                        DELETE FROM author_checkpoint_writes
                        WHERE thread_id = ?
                          AND checkpoint_ns = ?
                          AND checkpoint_id != ?
                        """,
                        (thread_id, checkpoint_ns, latest_id),
                    )
                    connection.execute(
                        """
                        DELETE FROM author_checkpoint_blobs
                        WHERE thread_id = ?
                          AND checkpoint_ns = ?
                          AND NOT EXISTS (
                              SELECT 1
                              FROM author_checkpoints c
                              WHERE c.thread_id = author_checkpoint_blobs.thread_id
                                AND c.checkpoint_ns = author_checkpoint_blobs.checkpoint_ns
                          )
                        """,
                        (thread_id, checkpoint_ns),
                    )
            connection.commit()

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(self, config: RunnableConfig | None, *, filter=None, before=None, limit=None):
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: RunnableConfig, writes, task_id: str, task_path: str = "") -> None:
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)

    async def adelete_for_runs(self, run_ids) -> None:
        self.delete_for_runs(run_ids)

    async def acopy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        self.copy_thread(source_thread_id, target_thread_id)

    async def aprune(self, thread_ids, *, strategy: str = "keep_latest") -> None:
        self.prune(thread_ids, strategy=strategy)

    def get_next_version(self, current: str | None, channel: None) -> str:
        if current is None:
            current_version = 0
        elif isinstance(current, int):
            current_version = current
        else:
            current_version = int(str(current).split(".")[0])
        next_version = current_version + 1
        return f"{next_version:032}.{random.random():016}"


@lru_cache
def _get_author_checkpointer_by_db_path(db_path: str) -> SQLiteCheckpointSaver:
    return SQLiteCheckpointSaver(db_path)


def get_author_checkpointer(
    settings: Settings | None = None,
    *,
    db_path: str | None = None,
) -> SQLiteCheckpointSaver:
    resolved_db_path = db_path or (settings.runtime_state_db_path if settings is not None else get_settings().runtime_state_db_path)
    return _get_author_checkpointer_by_db_path(resolved_db_path)


def graph_config(*, run_id: str, recursion_limit: int = 64) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": run_id,
        },
        "recursion_limit": recursion_limit,
    }
