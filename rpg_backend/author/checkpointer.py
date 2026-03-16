from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver


@lru_cache
def get_author_checkpointer() -> InMemorySaver:
    return InMemorySaver()


def graph_config(*, run_id: str, recursion_limit: int = 64) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": run_id,
        },
        "recursion_limit": recursion_limit,
    }
