from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from tools.urban_author_play_benchmarks.gold_set import v1_topic_gold_14
from tools.urban_author_play_benchmarks.light_ab_shared import (
    BASELINE_LOCK_DEFAULT,
    BASELINE_LOCK_SCHEMA_VERSION,
    build_holdout_case_catalog,
    build_rpm_budget,
    play_eval_signature,
    rpm_budget_limits,
    select_light_case_catalog,
    strict_no_repair_fallback,
)
from tools.urban_author_play_benchmarks.live_eval_common import run_case_catalog_live_eval
from tools.urban_author_play_benchmarks.native_cn_live_eval import _write_json


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_light_ab_baseline_refresh(
    output_dir: Path,
    *,
    baseline_lock: Path = BASELINE_LOCK_DEFAULT,
    baseline_name: str = "baseline",
    case_max_workers: int = 40,
    total_rpm_limit: int = 200,
) -> dict[str, Any]:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    case_catalog = select_light_case_catalog(v1_topic_gold_14())
    holdout_catalog = build_holdout_case_catalog(case_catalog)
    _write_json(root / "light_case_set.json", case_catalog)
    _write_json(root / "light_holdout_case_set.json", holdout_catalog)

    rpm_budget = build_rpm_budget(total_rpm_limit)
    with strict_no_repair_fallback(enabled=True):
        with rpm_budget_limits(
            total_rpm_limit=rpm_budget["total"],
        ):
            baseline_payload = run_case_catalog_live_eval(
                root / "baseline",
                case_catalog=case_catalog,
                case_set_filename="light_case_set.json",
                blockers_filename="light_blockers.md",
                blockers_title="Light AB Baseline Blockers (npc_texture_v2)",
                enable_llm_text_audit=True,
                case_max_workers=case_max_workers,
            )
            baseline_holdout_payload = run_case_catalog_live_eval(
                root / "baseline_holdout",
                case_catalog=holdout_catalog,
                case_set_filename="light_holdout_case_set.json",
                blockers_filename="light_holdout_blockers.md",
                blockers_title="Light AB Holdout Baseline Blockers (npc_texture_v2)",
                enable_llm_text_audit=True,
                case_max_workers=case_max_workers,
            )

    case_ids = [case.case_id for case in case_catalog]
    holdout_case_ids = [case.case_id for case in holdout_catalog]
    lock_payload = {
        "baseline_name": baseline_name,
        "baseline_profile": "npc_texture_v2",
        "baseline_artifacts_dir": str(Path(str(baseline_payload["artifacts_dir"])).resolve()),
        "baseline_signature": play_eval_signature(
            dict(baseline_payload["play_eval_summary"]),
            expected_case_ids=case_ids,
        ),
        "baseline_holdout_artifacts_dir": str(Path(str(baseline_holdout_payload["artifacts_dir"])).resolve()),
        "baseline_holdout_signature": play_eval_signature(
            dict(baseline_holdout_payload["play_eval_summary"]),
            expected_case_ids=holdout_case_ids,
        ),
        "generated_at_utc": _utc_now_iso(),
        "schema_version": BASELINE_LOCK_SCHEMA_VERSION,
    }
    baseline_lock_path = baseline_lock.expanduser().resolve()
    baseline_lock_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_lock_path.write_text(json.dumps(lock_payload, ensure_ascii=False, indent=2, sort_keys=True))

    manifest = {
        "baseline_lock": str(baseline_lock_path),
        "baseline_name": baseline_name,
        "baseline_profile": "npc_texture_v2",
        "case_count": len(case_catalog),
        "holdout_case_count": len(holdout_catalog),
        "rpm_budget": rpm_budget,
        "schema_version": BASELINE_LOCK_SCHEMA_VERSION,
        "strict_no_repair_fallback_enabled": True,
    }
    _write_json(root / "light_baseline_refresh_manifest.json", manifest)
    return {
        "artifacts_dir": str(root),
        "baseline_lock_path": str(baseline_lock_path),
        "baseline_lock_payload": lock_payload,
        "baseline": baseline_payload,
        "holdout": baseline_holdout_payload,
        "manifest": manifest,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh light AB baseline artifacts and lock.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--baseline-lock", type=Path, default=BASELINE_LOCK_DEFAULT)
    parser.add_argument("--baseline-name", default="baseline")
    parser.add_argument("--case-max-workers", type=int, default=40)
    parser.add_argument("--total-rpm-limit", type=int, default=200)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_light_ab_baseline_refresh(
        args.output_dir,
        baseline_lock=args.baseline_lock,
        baseline_name=str(args.baseline_name),
        case_max_workers=int(args.case_max_workers),
        total_rpm_limit=int(args.total_rpm_limit),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
