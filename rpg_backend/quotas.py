from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock


class QuotaExceededError(RuntimeError):
    def __init__(self, *, scope: str, limit: int) -> None:
        self.scope = scope
        self.limit = limit
        super().__init__(f"{scope} daily LLM quota exceeded ({limit})")


@dataclass
class DailyQuotaLimiter:
    """Small in-process daily limiter for public demo LLM calls.

    The demo uses one uvicorn process in production, so an in-memory guard is
    enough to stop accidental public burn. A multi-instance deployment should
    replace this with Redis or database-backed counters.
    """

    _counts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    @staticmethod
    def _day_key(now: datetime | None = None) -> str:
        current = now or datetime.now(timezone.utc)
        return current.astimezone(timezone.utc).date().isoformat()

    def check_and_increment(
        self,
        *,
        ip_key: str,
        user_key: str | None,
        ip_limit: int | None,
        user_limit: int | None,
        amount: int = 1,
        now: datetime | None = None,
    ) -> None:
        debit = max(1, int(amount))
        day = self._day_key(now)
        ip_counter = ("ip", day, ip_key)
        user_counter = ("user", day, user_key) if user_key else None
        with self._lock:
            stale_keys = [key for key in self._counts if key[1] != day]
            for key in stale_keys:
                del self._counts[key]
            if ip_limit is not None and self._counts.get(ip_counter, 0) + debit > ip_limit:
                raise QuotaExceededError(scope="ip", limit=ip_limit)
            if (
                user_limit is not None
                and user_counter is not None
                and self._counts.get(user_counter, 0) + debit > user_limit
            ):
                raise QuotaExceededError(scope="user", limit=user_limit)
            if ip_limit is not None:
                self._counts[ip_counter] = self._counts.get(ip_counter, 0) + debit
            if user_limit is not None and user_counter is not None:
                self._counts[user_counter] = self._counts.get(user_counter, 0) + debit

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
