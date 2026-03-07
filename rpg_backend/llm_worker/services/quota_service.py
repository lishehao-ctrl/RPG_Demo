from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from rpg_backend.config.settings import get_settings
from rpg_backend.infrastructure.db.async_engine import async_engine
from rpg_backend.infrastructure.db.transaction import transactional
from rpg_backend.infrastructure.repositories.llm_quota_async import (
    adjust_quota_tokens,
    cleanup_old_windows,
    current_window_epoch_minute,
    reserve_quota_window,
)


@dataclass(frozen=True)
class ModelQuotaLimit:
    rpm: int
    tpm: int


@dataclass(frozen=True)
class QuotaReservation:
    allowed: bool
    error_code: str | None
    model: str
    window_epoch_minute: int
    estimated_tokens: int


class QuotaService:
    def __init__(self) -> None:
        settings = get_settings()
        self._default_rpm = max(1, int(getattr(settings, "llm_worker_default_rpm", 300)))
        self._default_tpm = max(1, int(getattr(settings, "llm_worker_default_tpm", 600_000)))
        self._model_limits = self._parse_limits(getattr(settings, "llm_worker_model_limits_json", "{}"))

    @staticmethod
    def _parse_limits(raw_value: str) -> dict[str, ModelQuotaLimit]:
        text = (raw_value or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception:  # noqa: BLE001
            return {}
        if not isinstance(payload, dict):
            return {}
        parsed: dict[str, ModelQuotaLimit] = {}
        for model, value in payload.items():
            if not isinstance(model, str) or not isinstance(value, dict):
                continue
            rpm = value.get("rpm")
            tpm = value.get("tpm")
            if not isinstance(rpm, int) or not isinstance(tpm, int):
                continue
            if rpm <= 0 or tpm <= 0:
                continue
            parsed[model.strip()] = ModelQuotaLimit(rpm=rpm, tpm=tpm)
        return parsed

    def model_limit(self, model: str) -> ModelQuotaLimit:
        normalized = (model or "").strip()
        limit = self._model_limits.get(normalized)
        if limit is not None:
            return limit
        return ModelQuotaLimit(rpm=self._default_rpm, tpm=self._default_tpm)

    @staticmethod
    def estimate_tokens(
        *,
        system_prompt: str,
        user_prompt: str,
        output_token_estimate: int,
    ) -> int:
        input_chars = len(system_prompt or "") + len(user_prompt or "")
        input_est = max(1, input_chars // 4)
        output_est = max(1, int(output_token_estimate))
        return input_est + output_est

    async def reserve_async(
        self,
        *,
        model: str,
        estimated_tokens: int,
        now: datetime | None = None,
    ) -> QuotaReservation:
        limits = self.model_limit(model)
        window_minute = current_window_epoch_minute(now=now)
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            async with transactional(db):
                reservation = await reserve_quota_window(
                    db,
                    model=model,
                    window_epoch_minute=window_minute,
                    rpm_limit=limits.rpm,
                    tpm_limit=limits.tpm,
                    estimated_tokens=max(1, int(estimated_tokens)),
                    now=now,
                )
        if reservation.allowed:
            return QuotaReservation(
                allowed=True,
                error_code=None,
                model=reservation.model,
                window_epoch_minute=reservation.window_epoch_minute,
                estimated_tokens=reservation.estimated_tokens,
            )
        return QuotaReservation(
            allowed=False,
            error_code="worker_rate_limited",
            model=reservation.model,
            window_epoch_minute=reservation.window_epoch_minute,
            estimated_tokens=reservation.estimated_tokens,
        )

    async def reconcile_async(
        self,
        *,
        model: str,
        window_epoch_minute: int,
        estimated_tokens: int,
        actual_total_tokens: int | None,
    ) -> None:
        if actual_total_tokens is None:
            return
        delta = int(actual_total_tokens) - max(1, int(estimated_tokens))
        if delta == 0:
            return
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            async with transactional(db):
                await adjust_quota_tokens(
                    db,
                    model=model,
                    window_epoch_minute=window_epoch_minute,
                    delta_tokens=delta,
                )

    async def cleanup_async(self, *, keep_last_minutes: int = 120, now: datetime | None = None) -> int:
        current_minute = current_window_epoch_minute(now=now)
        threshold = current_minute - max(1, int(keep_last_minutes))
        async with AsyncSession(async_engine, expire_on_commit=False) as db:
            async with transactional(db):
                return await cleanup_old_windows(db, min_window_epoch_minute=threshold)
