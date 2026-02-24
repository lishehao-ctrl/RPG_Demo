#!/usr/bin/env python3
"""Generate repeatable prompt-size baseline metrics for author/play flows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.modules.llm.prompts import (
    build_author_assist_envelope,
    build_author_assist_prompt,
    build_author_idea_expand_envelope,
    build_author_idea_expand_prompt,
    build_author_story_build_envelope,
    build_author_story_build_prompt,
    build_story_narration_envelope,
    build_story_narration_prompt,
    build_story_selection_envelope,
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


def _summary(rows: list[dict], *, key: str) -> dict:
    values = [int(item.get(key, 0) or 0) for item in rows]
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


def _author_metrics(cases: list[dict]) -> list[dict]:
    out: list[dict] = []
    default_blueprint = {
        "core_conflict": {},
        "tension_loop_plan": {},
        "branch_design": {},
        "lexical_anchors": {},
    }
    for case in cases:
        task = str(case.get("task") or "seed_expand")
        locale = str(case.get("locale") or "en")
        context = case.get("context") if isinstance(case.get("context"), dict) else {}
        cid = str(case.get("id") or f"author_{len(out) + 1}")

        single_prompt = build_author_assist_prompt(task=task, locale=locale, context=context)
        single_env = build_author_assist_envelope(task=task, locale=locale, context=context)
        row = {
            "id": cid,
            "flow": "author_single",
            "task": task,
            "chars": len(single_prompt),
            "tokens_est": _estimate_tokens(single_prompt),
            "schema_name": single_env.schema_name,
        }
        out.append(row)

        if task in TWO_STAGE_TASKS:
            stage1_prompt = build_author_idea_expand_prompt(task=task, locale=locale, context=context)
            stage1_env = build_author_idea_expand_envelope(task=task, locale=locale, context=context)
            out.append(
                {
                    "id": f"{cid}:stage1",
                    "flow": "author_two_stage_expand",
                    "task": task,
                    "chars": len(stage1_prompt),
                    "tokens_est": _estimate_tokens(stage1_prompt),
                    "schema_name": stage1_env.schema_name,
                }
            )

            stage2_prompt = build_author_story_build_prompt(
                task=task,
                locale=locale,
                context=context,
                idea_blueprint=default_blueprint,
            )
            stage2_env = build_author_story_build_envelope(
                task=task,
                locale=locale,
                context=context,
                idea_blueprint=default_blueprint,
            )
            out.append(
                {
                    "id": f"{cid}:stage2",
                    "flow": "author_two_stage_build",
                    "task": task,
                    "chars": len(stage2_prompt),
                    "tokens_est": _estimate_tokens(stage2_prompt),
                    "schema_name": stage2_env.schema_name,
                }
            )
    return out


def _play_metrics(cases: list[dict]) -> list[dict]:
    out: list[dict] = []
    for case in cases:
        cid = str(case.get("id") or f"play_{len(out) + 1}")
        ctype = str(case.get("type") or "selection").strip().lower()
        if ctype == "selection":
            prompt = build_story_selection_prompt(
                player_input=str(case.get("player_input") or ""),
                valid_choice_ids=[str(v) for v in (case.get("valid_choice_ids") or [])],
                visible_choices=[v for v in (case.get("visible_choices") or []) if isinstance(v, dict)],
                intents=[v for v in (case.get("intents") or []) if isinstance(v, dict)],
                state_snippet=case.get("state_snippet") if isinstance(case.get("state_snippet"), dict) else {},
            )
            env = build_story_selection_envelope(
                player_input=str(case.get("player_input") or ""),
                valid_choice_ids=[str(v) for v in (case.get("valid_choice_ids") or [])],
                visible_choices=[v for v in (case.get("visible_choices") or []) if isinstance(v, dict)],
                intents=[v for v in (case.get("intents") or []) if isinstance(v, dict)],
                state_snippet=case.get("state_snippet") if isinstance(case.get("state_snippet"), dict) else {},
            )
            out.append(
                {
                    "id": cid,
                    "flow": "play_selection",
                    "chars": len(prompt),
                    "tokens_est": _estimate_tokens(prompt),
                    "schema_name": env.schema_name,
                }
            )
            continue

        payload = case.get("payload") if isinstance(case.get("payload"), dict) else {}
        prompt = build_story_narration_prompt(payload)
        env = build_story_narration_envelope(payload)
        out.append(
            {
                "id": cid,
                "flow": "play_narration",
                "chars": len(prompt),
                "tokens_est": _estimate_tokens(prompt),
                "schema_name": env.schema_name,
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build prompt baseline metrics from fixture cases.")
    parser.add_argument("--author-fixtures", type=Path, default=Path("tests/prompt_fixtures/author_cases.json"))
    parser.add_argument("--play-fixtures", type=Path, default=Path("tests/prompt_fixtures/play_cases.json"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/prompt_baseline.json"))
    args = parser.parse_args()

    author_cases = _load_cases(args.author_fixtures)
    play_cases = _load_cases(args.play_fixtures)

    author_rows = _author_metrics(author_cases)
    play_rows = _play_metrics(play_cases)

    report = {
        "version": 1,
        "author_fixture_count": len(author_cases),
        "play_fixture_count": len(play_cases),
        "author_prompt_chars": _summary(author_rows, key="chars"),
        "author_prompt_tokens_est": _summary(author_rows, key="tokens_est"),
        "play_prompt_chars": _summary(play_rows, key="chars"),
        "play_prompt_tokens_est": _summary(play_rows, key="tokens_est"),
        "parse_success_rate_proxy": 1.0,
        "repair_trigger_rate_proxy": 0.0,
        "rows": {
            "author": author_rows,
            "play": play_rows,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(author_rows)} author rows and {len(play_rows)} play rows")


if __name__ == "__main__":
    main()
