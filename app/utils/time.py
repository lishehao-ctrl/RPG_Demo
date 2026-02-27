from __future__ import annotations

from datetime import datetime, timezone


def utc_now_aware() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    return utc_now_aware().astimezone(timezone.utc).replace(tzinfo=None)

