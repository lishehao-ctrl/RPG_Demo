#!/usr/bin/env python3
"""Compare current prompt metrics against baseline and summarize runtime usage logs."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.modules.llm.prompts import (
    build_author_assist_prompt,
    build_author_idea_expand_prompt,
    build_author_story_build_prompt,
    build_story_narration_prompt,
    build_story_selection_prompt,
)

TWO_STAGE_TASKS = {"seed_expand", "story_ingest", "continue_write"}


def _estimate_tokens(text: str) -> int:
    return max(1, len(str(text or "")) // 4)


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1)))))
    return int(ordered[idx])


def _summary(values: list[int]) -> dict:
    if not values:
        return {"count": 0, "mean": 0, "p95": 0, "max": 0}
    return {
        "count": len(values),
        "mean": round(mean(values), 2),
        "p95": _p95(values),
        "max": max(values),
    }


def _load_cases(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"fixture file must be a JSON array: {path}")
    return [item for item in raw if isinstance(item, dict)]


def _compute_prompt_metrics(author_cases: list[dict], play_cases: list[dict]) -> dict:
    author_prompt_lengths: list[int] = []
    author_prompt_tokens: list[int] = []
    play_prompt_lengths: list[int] = []
    play_prompt_tokens: list[int] = []

    default_blueprint = {
        "core_conflict": {},
        "tension_loop_plan": {},
        "branch_design": {},
        "lexical_anchors": {},
    }

    for case in author_cases:
        task = str(case.get("task") or "seed_expand")
        locale = str(case.get("locale") or "en")
        context = case.get("context") if isinstance(case.get("context"), dict) else {}
        prompts = [build_author_assist_prompt(task=task, locale=locale, context=context)]
        if task in TWO_STAGE_TASKS:
            prompts.append(build_author_idea_expand_prompt(task=task, locale=locale, context=context))
            prompts.append(
                build_author_story_build_prompt(
                    task=task,
                    locale=locale,
                    context=context,
                    idea_blueprint=default_blueprint,
                )
            )
        for prompt in prompts:
            author_prompt_lengths.append(len(prompt))
            author_prompt_tokens.append(_estimate_tokens(prompt))

    for case in play_cases:
        ctype = str(case.get("type") or "selection").strip().lower()
        if ctype == "selection":
            prompt = build_story_selection_prompt(
                player_input=str(case.get("player_input") or ""),
                valid_choice_ids=[str(v) for v in (case.get("valid_choice_ids") or [])],
                visible_choices=[v for v in (case.get("visible_choices") or []) if isinstance(v, dict)],
                intents=[v for v in (case.get("intents") or []) if isinstance(v, dict)],
                state_snippet=case.get("state_snippet") if isinstance(case.get("state_snippet"), dict) else {},
            )
        else:
            payload = case.get("payload") if isinstance(case.get("payload"), dict) else {}
            prompt = build_story_narration_prompt(payload)
        play_prompt_lengths.append(len(prompt))
        play_prompt_tokens.append(_estimate_tokens(prompt))

    return {
        "author_prompt_chars": _summary(author_prompt_lengths),
        "author_prompt_tokens_est": _summary(author_prompt_tokens),
        "play_prompt_chars": _summary(play_prompt_lengths),
        "play_prompt_tokens_est": _summary(play_prompt_tokens),
    }


def _diff_summary(current: dict, baseline: dict) -> dict:
    out: dict[str, dict] = {}
    for key in (
        "author_prompt_chars",
        "author_prompt_tokens_est",
        "play_prompt_chars",
        "play_prompt_tokens_est",
    ):
        cur = current.get(key) if isinstance(current.get(key), dict) else {}
        base = baseline.get(key) if isinstance(baseline.get(key), dict) else {}
        out[key] = {
            "current_mean": float(cur.get("mean", 0) or 0),
            "baseline_mean": float(base.get("mean", 0) or 0),
            "delta_mean": round(float(cur.get("mean", 0) or 0) - float(base.get("mean", 0) or 0), 2),
            "current_p95": int(cur.get("p95", 0) or 0),
            "baseline_p95": int(base.get("p95", 0) or 0),
            "delta_p95": int(cur.get("p95", 0) or 0) - int(base.get("p95", 0) or 0),
        }
    return out


def _usage_metrics(db_path: Path) -> dict:
    if not db_path.exists():
        return {
            "db_exists": False,
            "row_count": 0,
            "p95_latency_ms": 0,
            "author_invalid_output_rate": None,
            "play_parse_error_rate": None,
            "avg_prompt_tokens": 0,
        }

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llm_usage_logs'")
        if cursor.fetchone() is None:
            return {
                "db_exists": True,
                "row_count": 0,
                "p95_latency_ms": 0,
                "author_invalid_output_rate": None,
                "play_parse_error_rate": None,
                "avg_prompt_tokens": 0,
            }

        rows = cursor.execute(
            "SELECT operation, status, error_message, latency_ms, prompt_tokens FROM llm_usage_logs"
        ).fetchall()
    finally:
        conn.close()

    latencies = [int(row[3] or 0) for row in rows]
    prompt_tokens = [int(row[4] or 0) for row in rows]
    error_rows = [row for row in rows if str(row[1] or "") == "error"]

    author_error_rows = [
        row
        for row in error_rows
        if "assist" in str(row[2] or "").lower()
        or "assist_" in str(row[2] or "").lower()
    ]
    author_invalid_rows = [
        row
        for row in author_error_rows
        if "assist_schema_validate" in str(row[2] or "").lower() or "assist_json_parse" in str(row[2] or "").lower()
    ]

    play_error_rows = [row for row in error_rows if "narrative_" in str(row[2] or "").lower()]
    play_parse_rows = [
        row
        for row in play_error_rows
        if "narrative_schema_validate" in str(row[2] or "").lower() or "narrative_json_parse" in str(row[2] or "").lower()
    ]

    return {
        "db_exists": True,
        "row_count": len(rows),
        "p95_latency_ms": _p95(latencies),
        "author_invalid_output_rate": (
            round(len(author_invalid_rows) / len(author_error_rows), 4) if author_error_rows else None
        ),
        "play_parse_error_rate": round(len(play_parse_rows) / len(play_error_rows), 4) if play_error_rows else None,
        "avg_prompt_tokens": round(mean(prompt_tokens), 2) if prompt_tokens else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate current prompt quality and compare against baseline.")
    parser.add_argument("--author-fixtures", type=Path, default=Path("tests/prompt_fixtures/author_cases.json"))
    parser.add_argument("--play-fixtures", type=Path, default=Path("tests/prompt_fixtures/play_cases.json"))
    parser.add_argument("--baseline", type=Path, default=Path("artifacts/prompt_baseline.json"))
    parser.add_argument("--db", type=Path, default=Path("app.db"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/prompt_quality.json"))
    args = parser.parse_args()

    author_cases = _load_cases(args.author_fixtures)
    play_cases = _load_cases(args.play_fixtures)
    current = _compute_prompt_metrics(author_cases, play_cases)

    baseline: dict = {}
    if args.baseline.exists():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))

    report = {
        "version": 1,
        "current": current,
        "baseline_path": str(args.baseline),
        "baseline_available": bool(baseline),
        "comparison": _diff_summary(current, baseline) if baseline else {},
        "usage_metrics": _usage_metrics(args.db),
        "acceptance_targets": {
            "author_invalid_output_rate": "down",
            "play_parse_error_rate": "down",
            "p95_latency_ms": "stable_or_down",
            "avg_prompt_tokens": "down",
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
