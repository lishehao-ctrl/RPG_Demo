from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def current_window_epoch_minute(*, now: datetime | None = None) -> int:
    value = now or utc_now()
    return int(value.timestamp() // 60)


@dataclass(frozen=True)
class QuotaReservationResult:
    allowed: bool
    model: str
    window_epoch_minute: int
    rpm_limit: int
    tpm_limit: int
    estimated_tokens: int


async def reserve_quota_window(
    db: AsyncSession,
    *,
    model: str,
    window_epoch_minute: int,
    rpm_limit: int,
    tpm_limit: int,
    estimated_tokens: int,
    now: datetime | None = None,
) -> QuotaReservationResult:
    model_value = str(model or "").strip() or "unknown"
    minute_value = int(window_epoch_minute)
    now_value = now or utc_now()
    rpm_limit_value = max(1, int(rpm_limit))
    tpm_limit_value = max(1, int(tpm_limit))
    token_value = max(1, int(estimated_tokens))

    await db.exec(
        text(
            """
            INSERT INTO llmquotawindow (model, window_epoch_minute, rpm_used, tpm_used, updated_at)
            VALUES (:model, :window_epoch_minute, 0, 0, :updated_at)
            ON CONFLICT (model, window_epoch_minute) DO NOTHING
            """
        ),
        params={
            "model": model_value,
            "window_epoch_minute": minute_value,
            "updated_at": now_value,
        },
    )
    update_result = await db.exec(
        text(
            """
            UPDATE llmquotawindow
            SET rpm_used = rpm_used + 1,
                tpm_used = tpm_used + :tokens,
                updated_at = :updated_at
            WHERE model = :model
              AND window_epoch_minute = :window_epoch_minute
              AND rpm_used + 1 <= :rpm_limit
              AND tpm_used + :tokens <= :tpm_limit
            """
        ),
        params={
            "model": model_value,
            "window_epoch_minute": minute_value,
            "tokens": token_value,
            "updated_at": now_value,
            "rpm_limit": rpm_limit_value,
            "tpm_limit": tpm_limit_value,
        },
    )
    await db.commit()

    return QuotaReservationResult(
        allowed=bool(update_result.rowcount and int(update_result.rowcount) == 1),
        model=model_value,
        window_epoch_minute=minute_value,
        rpm_limit=rpm_limit_value,
        tpm_limit=tpm_limit_value,
        estimated_tokens=token_value,
    )


async def adjust_quota_tokens(
    db: AsyncSession,
    *,
    model: str,
    window_epoch_minute: int,
    delta_tokens: int,
    now: datetime | None = None,
) -> None:
    if int(delta_tokens) == 0:
        return
    model_value = str(model or "").strip() or "unknown"
    minute_value = int(window_epoch_minute)
    now_value = now or utc_now()
    await db.exec(
        text(
            """
            UPDATE llmquotawindow
            SET tpm_used = CASE
                WHEN tpm_used + :delta_tokens < 0 THEN 0
                ELSE tpm_used + :delta_tokens
            END,
            updated_at = :updated_at
            WHERE model = :model
              AND window_epoch_minute = :window_epoch_minute
            """
        ),
        params={
            "delta_tokens": int(delta_tokens),
            "updated_at": now_value,
            "model": model_value,
            "window_epoch_minute": minute_value,
        },
    )
    await db.commit()


async def cleanup_old_windows(
    db: AsyncSession,
    *,
    min_window_epoch_minute: int,
) -> int:
    delete_result = await db.exec(
        text("DELETE FROM llmquotawindow WHERE window_epoch_minute < :min_window_epoch_minute"),
        params={"min_window_epoch_minute": int(min_window_epoch_minute)},
    )
    await db.commit()
    return int(delete_result.rowcount or 0)
