#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

FUN_SCORE_WEIGHTS: dict[str, float] = {
    "overall": 0.40,
    "playability": 0.25,
    "choice_impact": 0.25,
    "tension_curve": 0.10,
}


def _to_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _compute_fun_score(judge_result_dict: dict[str, Any]) -> float:
    overall = _to_score(judge_result_dict.get("overall_score"))
    playability = _to_score(judge_result_dict.get("playability_score"))
    choice_impact = _to_score(judge_result_dict.get("choice_impact_score"))
    tension_curve = _to_score(judge_result_dict.get("tension_curve_score"))
    return (
        FUN_SCORE_WEIGHTS["overall"] * overall
        + FUN_SCORE_WEIGHTS["playability"] * playability
        + FUN_SCORE_WEIGHTS["choice_impact"] * choice_impact
        + FUN_SCORE_WEIGHTS["tension_curve"] * tension_curve
    )


def _aggregate_playthrough_metrics(reports: list[dict[str, Any]]) -> dict[str, float]:
    if not reports:
        return {
            "completion_rate": 0.0,
            "avg_steps": 0.0,
            "meaningful_accept_rate": 0.0,
            "llm_route_success_rate": 0.0,
            "global_help_route_rate": 0.0,
            "non_global_text_route_rate": 0.0,
            "pressure_recoil_trigger_rate": 0.0,
            "npc_stance_mentions_per_run_avg": 0.0,
            "step_error_rate": 0.0,
        }

    completion_count = sum(1 for report in reports if report.get("ended"))
    completed_steps = [int(report.get("steps", 0)) for report in reports if report.get("ended")]
    total_steps = sum(int(report.get("steps", 0)) for report in reports)
    meaningful_steps = sum(int(report.get("meaningful_steps", 0)) for report in reports)
    text_input_steps = sum(int(report.get("text_input_steps", 0)) for report in reports)
    llm_route_steps = sum(int(report.get("llm_route_steps", 0)) for report in reports)
    global_help_route_steps = sum(int(report.get("global_help_route_steps", 0)) for report in reports)
    non_global_text_routes = sum(int(report.get("non_global_text_routes", 0)) for report in reports)
    pressure_recoil_steps = sum(int(report.get("pressure_recoil_steps", 0)) for report in reports)
    npc_stance_mentions = sum(int(report.get("npc_stance_mentions", 0)) for report in reports)
    runtime_error_steps = sum(1 for report in reports if report.get("runtime_error"))

    return {
        "completion_rate": completion_count / len(reports),
        "avg_steps": (sum(completed_steps) / len(completed_steps)) if completed_steps else 0.0,
        "meaningful_accept_rate": (meaningful_steps / total_steps) if total_steps else 0.0,
        "llm_route_success_rate": (llm_route_steps / text_input_steps) if text_input_steps else 0.0,
        "global_help_route_rate": (global_help_route_steps / text_input_steps) if text_input_steps else 0.0,
        "non_global_text_route_rate": (non_global_text_routes / text_input_steps) if text_input_steps else 0.0,
        "pressure_recoil_trigger_rate": pressure_recoil_steps / len(reports),
        "npc_stance_mentions_per_run_avg": npc_stance_mentions / len(reports),
        "step_error_rate": runtime_error_steps / len(reports),
    }


def _build_pack_summary(pack_json: dict[str, Any]) -> dict[str, Any]:
    scenes = pack_json.get("scenes", [])
    moves = pack_json.get("moves", [])
    beats = pack_json.get("beats", [])
    enabled_move_total = sum(len(scene.get("enabled_moves", [])) for scene in scenes if isinstance(scene, dict))
    outcome_distribution = {"success": 0, "partial": 0, "fail_forward": 0}
    palette_distribution: dict[str, int] = {}
    move_ids: list[str] = []
    for move in moves:
        if not isinstance(move, dict):
            continue
        move_id = move.get("id", "")
        if isinstance(move_id, str):
            move_ids.append(move_id)
        for outcome in move.get("outcomes", []):
            if not isinstance(outcome, dict):
                continue
            result = outcome.get("result")
            if result in outcome_distribution:
                outcome_distribution[result] += 1
            outcome_id = outcome.get("id", "")
            if isinstance(outcome_id, str):
                parts = outcome_id.split(".")
                if len(parts) >= 3:
                    palette_id = parts[-1]
                    palette_distribution[palette_id] = palette_distribution.get(palette_id, 0) + 1
    beat_titles = [beat["title"] for beat in beats if isinstance(beat, dict) and isinstance(beat.get("title"), str)]
    return {
        "story_id": pack_json.get("story_id"),
        "title": pack_json.get("title"),
        "description": pack_json.get("description"),
        "npc_count": len(pack_json.get("npcs", [])),
        "npcs": pack_json.get("npcs", []),
        "beat_count": len(beats),
        "beat_titles": beat_titles,
        "scene_count": len(scenes),
        "move_count": len(moves),
        "enabled_moves_avg": enabled_move_total / len(scenes) if scenes else 0.0,
        "move_ids_sample": move_ids[:12],
        "outcome_distribution": outcome_distribution,
        "palette_distribution": palette_distribution,
    }


def _summarize_transcript(report: dict[str, Any]) -> dict[str, Any]:
    transcript = report.get("transcript", [])
    highlights: list[dict[str, Any]] = []
    if transcript:
        indexes = sorted({0, len(transcript) // 2, len(transcript) - 1})
        for idx in indexes:
            entry = transcript[idx]
            action_input = entry.get("action_input", {}) if isinstance(entry, dict) else {}
            recognized = entry.get("recognized", {}) if isinstance(entry, dict) else {}
            resolution = entry.get("resolution", {}) if isinstance(entry, dict) else {}
            highlights.append(
                {
                    "step": entry.get("step"),
                    "scene_id": entry.get("scene_id"),
                    "input_type": action_input.get("type"),
                    "route_source": entry.get("route_source"),
                    "recognized_move_id": recognized.get("move_id"),
                    "resolution_result": resolution.get("result"),
                    "meaningful_change": entry.get("meaningful_change"),
                }
            )
    return {
        "strategy": report.get("strategy"),
        "provider": report.get("provider"),
        "ended": bool(report.get("ended")),
        "steps": int(report.get("steps", 0)),
        "meaningful_steps": int(report.get("meaningful_steps", 0)),
        "text_input_steps": int(report.get("text_input_steps", 0)),
        "llm_route_steps": int(report.get("llm_route_steps", 0)),
        "runtime_error": bool(report.get("runtime_error", False)),
        "runtime_error_code": report.get("runtime_error_code"),
        "runtime_error_stage": report.get("runtime_error_stage"),
        "highlights": highlights,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Story evaluation helper utilities")
    parser.add_argument("--dump-pack-summary", default=None)
    args = parser.parse_args()
    if args.dump_pack_summary:
        payload = json.loads(args.dump_pack_summary)
        print(json.dumps(_build_pack_summary(payload), ensure_ascii=False, indent=2))
        return 0
    print("story_eval_helpers exposes helper utilities for release tooling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
