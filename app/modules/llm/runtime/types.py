from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class CircuitState:
    failure_timestamps: deque[float] = field(default_factory=deque)
    open_until: float = 0.0


@dataclass(frozen=True, slots=True)
class LLMTimeoutProfile:
    disable_total_deadline: bool = False
    call_timeout_s: float | None = None
    connect_timeout_s: float | None = None
    read_timeout_s: float | None = None
    write_timeout_s: float | None = None
    pool_timeout_s: float | None = None
