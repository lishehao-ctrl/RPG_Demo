from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from tools.urban_author_play_benchmarks.gold_eval_runner_common import print_runner_result, run_gold_eval_suite
from tools.urban_author_play_benchmarks.gold_set import mini_gold_realistic_6

DEFAULT_CASE_MAX_WORKERS = 8
DEFAULT_TOTAL_RPM_LIMIT = 300
DEFAULT_CASE_TIMEOUT_SECONDS = 1500.0
DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS = 3600.0
DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS = 600.0
DEFAULT_SELECT_ID_PROBABILITY = 0.1
DEFAULT_TYPING_RHYTHM_ENABLED = False
DEFAULT_DRAFT_INTENT_PROBABILITY = 0.2
DEFAULT_DRAFT_CALL_COUNT_MIN = 1
DEFAULT_DRAFT_CALL_COUNT_MAX = 1
DEFAULT_DRAFT_DEBOUNCE_MS = 250
DEFAULT_SESSION_PLAY_EVAL_PERSONA_LIMIT = 5
DEFAULT_LLM_TEXT_AUDIT_PERSONA_LIMIT = 3


def run_gold_eval_mini(
    output_dir: Path,
    *,
    case_max_workers: int = DEFAULT_CASE_MAX_WORKERS,
    total_rpm_limit: int = DEFAULT_TOTAL_RPM_LIMIT,
    case_timeout_seconds: float = DEFAULT_CASE_TIMEOUT_SECONDS,
    case_aggregate_timeout_seconds: float = DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS,
    session_play_eval_timeout_seconds: float = DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS,
    select_id_probability: float = DEFAULT_SELECT_ID_PROBABILITY,
    typing_rhythm_enabled: bool = DEFAULT_TYPING_RHYTHM_ENABLED,
    draft_intent_probability: float = DEFAULT_DRAFT_INTENT_PROBABILITY,
    draft_call_count_min: int = DEFAULT_DRAFT_CALL_COUNT_MIN,
    draft_call_count_max: int = DEFAULT_DRAFT_CALL_COUNT_MAX,
    draft_debounce_ms: int = DEFAULT_DRAFT_DEBOUNCE_MS,
    session_play_eval_persona_limit: int | None = DEFAULT_SESSION_PLAY_EVAL_PERSONA_LIMIT,
    llm_text_audit_persona_limit: int | None = DEFAULT_LLM_TEXT_AUDIT_PERSONA_LIMIT,
    baseline_artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    case_catalog = mini_gold_realistic_6()
    if (smoke_case_limit := os.getenv("SMOKE_CASE_LIMIT")):
        case_catalog = case_catalog[: max(1, int(smoke_case_limit))]
    return run_gold_eval_suite(
        output_dir=output_dir,
        suite_type="mini",
        profile="mini",
        case_catalog=case_catalog,
        case_set_filename="mini_case_set.json",
        blockers_filename="blockers.md",
        blockers_title="Gold Eval Mini Blockers",
        case_max_workers=case_max_workers,
        total_rpm_limit=total_rpm_limit,
        case_timeout_seconds=case_timeout_seconds,
        case_aggregate_timeout_seconds=case_aggregate_timeout_seconds,
        session_play_eval_timeout_seconds=session_play_eval_timeout_seconds,
        select_id_probability=select_id_probability,
        typing_rhythm_enabled=typing_rhythm_enabled,
        draft_intent_probability=draft_intent_probability,
        draft_call_count_min=draft_call_count_min,
        draft_call_count_max=draft_call_count_max,
        draft_debounce_ms=draft_debounce_ms,
        session_play_eval_persona_limit=session_play_eval_persona_limit,
        llm_text_audit_persona_limit=llm_text_audit_persona_limit,
        baseline_artifacts_dir=baseline_artifacts_dir,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run mini gold eval (realistic-12-case) with forced persona self-play + play_eval + llm_text_audit."
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--case-max-workers", type=int, default=DEFAULT_CASE_MAX_WORKERS)
    parser.add_argument("--total-rpm-limit", type=int, default=DEFAULT_TOTAL_RPM_LIMIT)
    parser.add_argument("--case-timeout-seconds", type=float, default=DEFAULT_CASE_TIMEOUT_SECONDS)
    parser.add_argument("--case-aggregate-timeout-seconds", type=float, default=DEFAULT_CASE_AGGREGATE_TIMEOUT_SECONDS)
    parser.add_argument("--session-play-eval-timeout-seconds", type=float, default=DEFAULT_SESSION_PLAY_EVAL_TIMEOUT_SECONDS)
    parser.add_argument("--select-id-probability", type=float, default=DEFAULT_SELECT_ID_PROBABILITY)
    parser.add_argument("--typing-rhythm-enabled", action="store_true")
    parser.add_argument("--typing-rhythm-disabled", action="store_true")
    parser.add_argument("--draft-intent-probability", type=float, default=DEFAULT_DRAFT_INTENT_PROBABILITY)
    parser.add_argument("--draft-call-count-min", type=int, default=DEFAULT_DRAFT_CALL_COUNT_MIN)
    parser.add_argument("--draft-call-count-max", type=int, default=DEFAULT_DRAFT_CALL_COUNT_MAX)
    parser.add_argument("--draft-debounce-ms", type=int, default=DEFAULT_DRAFT_DEBOUNCE_MS)
    parser.add_argument("--session-play-eval-persona-limit", type=int, default=DEFAULT_SESSION_PLAY_EVAL_PERSONA_LIMIT)
    parser.add_argument("--llm-text-audit-persona-limit", type=int, default=DEFAULT_LLM_TEXT_AUDIT_PERSONA_LIMIT)
    parser.add_argument("--baseline-artifacts-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    typing_rhythm_enabled = (
        True
        if bool(args.typing_rhythm_enabled)
        else (False if bool(args.typing_rhythm_disabled) else DEFAULT_TYPING_RHYTHM_ENABLED)
    )
    result = run_gold_eval_mini(
        args.output_dir,
        case_max_workers=max(1, int(args.case_max_workers)),
        total_rpm_limit=max(1, int(args.total_rpm_limit)),
        case_timeout_seconds=max(30.0, float(args.case_timeout_seconds)),
        case_aggregate_timeout_seconds=max(60.0, float(args.case_aggregate_timeout_seconds)),
        session_play_eval_timeout_seconds=max(30.0, float(args.session_play_eval_timeout_seconds)),
        select_id_probability=min(max(float(args.select_id_probability), 0.0), 1.0),
        typing_rhythm_enabled=typing_rhythm_enabled,
        draft_intent_probability=min(max(float(args.draft_intent_probability), 0.0), 1.0),
        draft_call_count_min=max(1, int(args.draft_call_count_min)),
        draft_call_count_max=max(1, int(args.draft_call_count_max)),
        draft_debounce_ms=max(0, int(args.draft_debounce_ms)),
        session_play_eval_persona_limit=(
            max(1, int(args.session_play_eval_persona_limit))
            if args.session_play_eval_persona_limit is not None
            else None
        ),
        llm_text_audit_persona_limit=(
            max(1, int(args.llm_text_audit_persona_limit))
            if args.llm_text_audit_persona_limit is not None
            else None
        ),
        baseline_artifacts_dir=(args.baseline_artifacts_dir.resolve() if args.baseline_artifacts_dir is not None else None),
    )
    print_runner_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
