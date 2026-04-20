from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rpg_backend.config import get_settings
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase
from tools.urban_author_play_benchmarks.holdout_case_catalog import build_holdout_case_catalog as _build_holdout_case_catalog

LIGHT_CASES_PER_SHELL = 2
LIGHT_SHELL_ORDER: tuple[str, ...] = (
    "wealth_families",
    "office_power",
    "entertainment_scandal",
    "campus_romance",
)
LIGHT_HOLDOUT_SEED = 20260401
LIGHT_HOLDOUT_VARIANTS_PER_CASE = 2
BASELINE_LOCK_SCHEMA_VERSION = 1
BASELINE_LOCK_DEFAULT = Path(".benchmarks/light_ab_baseline.lock.json")


@contextmanager
def rpm_budget_limits(*, total_rpm_limit: int) -> Iterator[None]:
    total = max(1, int(total_rpm_limit))
    env_updates = {
        "APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE": total,
        "APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE": total,
        "APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE": total,
        "APP_RESPONSES_GLOBAL_REQUESTS_PER_MINUTE": None,
        "APP_RESPONSES_GLOBAL_RATE_LIMIT_SCOPE": None,
    }
    previous = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            if isinstance(value, int):
                os.environ[key] = str(max(1, value))
            else:
                os.environ[key] = str(value)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def strict_no_repair_fallback(enabled: bool) -> Iterator[None]:
    key = "APP_INTERNAL_TEST_STRICT_NO_REPAIR_FALLBACK"
    previous = os.environ.get(key)
    if enabled:
        os.environ[key] = "true"
    else:
        os.environ.pop(key, None)
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
        get_settings.cache_clear()


def select_light_case_catalog(case_catalog: list[UrbanGoldCase]) -> list[UrbanGoldCase]:
    by_shell: dict[str, list[UrbanGoldCase]] = {}
    for case in case_catalog:
        by_shell.setdefault(case.expected_shell, []).append(case)
    selected: list[UrbanGoldCase] = []
    for shell_id in LIGHT_SHELL_ORDER:
        candidates = sorted(by_shell.get(shell_id, []), key=lambda case: case.case_id)
        if len(candidates) < LIGHT_CASES_PER_SHELL:
            raise RuntimeError(
                f"light AB requires at least {LIGHT_CASES_PER_SHELL} cases for shell `{shell_id}`, "
                f"but only found {len(candidates)}"
            )
        selected.extend(candidates[:LIGHT_CASES_PER_SHELL])
    return selected


def build_holdout_case_catalog(case_catalog: list[UrbanGoldCase]) -> list[UrbanGoldCase]:
    return _build_holdout_case_catalog(
        case_catalog,
        seed=LIGHT_HOLDOUT_SEED,
        variants_per_case=LIGHT_HOLDOUT_VARIANTS_PER_CASE,
    )


def play_eval_signature(summary: dict[str, object], *, expected_case_ids: list[str]) -> str:
    case_ids = sorted(str(row.get("case_id") or "") for row in list(summary.get("cases") or []))
    payload = {
        "expected_case_ids": sorted(expected_case_ids),
        "case_ids": case_ids,
        "top_flags": dict(summary.get("top_flags") or {}),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_rpm_budget(total_rpm_limit: int) -> dict[str, int]:
    budget = max(1, int(total_rpm_limit))
    return {
        "total": budget,
        "author": budget,
        "play": budget,
        "helper": budget,
    }
