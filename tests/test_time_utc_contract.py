from __future__ import annotations

from datetime import timezone
from pathlib import Path

from app.utils.time import utc_now_aware, utc_now_naive


def test_utc_now_aware_returns_aware_utc() -> None:
    now = utc_now_aware()
    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(now)


def test_utc_now_naive_is_utc_naive_timestamp() -> None:
    before = utc_now_aware()
    naive = utc_now_naive()
    after = utc_now_aware()

    assert naive.tzinfo is None
    as_aware = naive.replace(tzinfo=timezone.utc)
    assert before <= as_aware <= after


def test_no_datetime_utcnow_in_app_code() -> None:
    banned = "datetime.utcnow("
    hits: list[str] = []
    for path in Path("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if banned in text:
            hits.append(str(path))

    assert hits == []

