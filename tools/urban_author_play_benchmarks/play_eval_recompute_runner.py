from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

from rpg_backend.author_v2.contracts import CompiledPlayPlan, UrbanPreviewBlueprint
from rpg_backend.play_v2.contracts import UrbanSuggestedAction
from tools.urban_author_play_benchmarks import play_eval as play_eval_tools
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase, v1_topic_gold_14
from tools.urban_author_play_benchmarks.live_eval_common import (
    blockers_markdown,
    persona_coverage_summary,
    play_eval_summary,
)
from tools.urban_author_play_benchmarks.native_cn_live_eval import _case_play_eval_summary, _write_json
from tools.urban_author_play_benchmarks.self_play_runner import (
    SelfPlayRunSummary,
    SelfPlayTurnLog,
    _resolve_persona_pack_for_plan,
    _session_play_eval_payload,
    _turn_play_eval_payload,
)

KNOWN_VARIANTS: tuple[str, ...] = ("npc_texture_v2",)
DEFAULT_RECOMPUTE_VARIANTS: tuple[str, ...] = ("npc_texture_v2",)
LIVE_MODE = "live_gpt_5_4_mini"
METRIC_KEYS: tuple[str, ...] = (
    "avg_strategic_tension_curve",
    "avg_consequence_legibility",
    "avg_payoff_realization",
    "avg_npc_interest_divergence",
    "avg_control_tradeoff_quality",
    "avg_shell_system_activation",
    "avg_ending_cost_integrity",
    "avg_replay_variance",
    "avg_turn_consequence_impact",
    "avg_turn_intent_binding",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    payload = []
    for row in rows:
        if hasattr(row, "model_dump"):
            payload.append(json.dumps(row.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        else:
            payload.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    path.write_text("\n".join(payload))


def _resolve_case_artifact_dir(
    *,
    variant_root: Path,
    case_id: str,
) -> Path:
    case_root = variant_root / "deep_play" / "self_play" / case_id
    preferred = case_root / LIVE_MODE
    if preferred.exists():
        return preferred
    live_dirs = sorted(path for path in case_root.glob("live_*") if path.is_dir())
    if live_dirs:
        return live_dirs[0]
    raise FileNotFoundError(f"missing deep-play artifacts for case `{case_id}` under {case_root}")


def _rebuild_selected_suggestion(log: SelfPlayTurnLog) -> UrbanSuggestedAction:
    candidates = list(log.suggested_actions_snapshot or []) + list(log.next_suggested_actions or [])
    for item in candidates:
        if (
            str(item.get("lane_id") or "") == str(log.selected_lane_id or "")
            and str(item.get("move_family") or "") == log.selected_move_family
            and str(item.get("target_id") or "") == str(log.selected_target_id or "")
        ):
            return UrbanSuggestedAction.model_validate(item)
    if candidates:
        for item in candidates:
            if str(item.get("lane_id") or "") == str(log.selected_lane_id or ""):
                return UrbanSuggestedAction.model_validate(item)
    return UrbanSuggestedAction(
        suggestion_id=f"{log.segment_id}_{log.selected_lane_id or 'side'}",
        lane_id=(log.selected_lane_id or "side"),  # type: ignore[arg-type]
        label=str(log.selected_lane_id or "临时建议"),
        prompt=log.raw_action_text[:220],
        move_family=log.selected_move_family,  # type: ignore[arg-type]
        target_id=log.selected_target_id,
        scene_frame=str(log.state_after.get("scene_frame") or log.state_before.get("scene_frame") or "private"),  # type: ignore[arg-type]
    )


def _recompute_case_play_eval(case_artifact_dir: Path) -> dict[str, Any]:
    preview = UrbanPreviewBlueprint.model_validate(_read_json(case_artifact_dir / "preview_blueprint.json"))
    plan = CompiledPlayPlan.model_validate(_read_json(case_artifact_dir / "compiled_play_plan.json"))
    persona_pack = _resolve_persona_pack_for_plan(plan)
    case_id = case_artifact_dir.parent.name
    personas_root = case_artifact_dir / "personas"
    from tools.urban_author_play_benchmarks.self_play_runner import PERSONA_CONFIGS

    for persona_dir in sorted(personas_root.iterdir()):
        if not persona_dir.is_dir():
            continue
        logs = [SelfPlayTurnLog.model_validate(row) for row in _read_jsonl(persona_dir / "turn_logs.jsonl")]
        summary = SelfPlayRunSummary.model_validate(_read_json(persona_dir / "run_summary.json"))
        persona_id = summary.persona_id
        rebuilt_turn_records: list[play_eval_tools.TurnPlayEvalRecord] = []
        for log in logs:
            selected = _rebuild_selected_suggestion(log)
            rebuilt_turn_records.append(
                play_eval_tools.evaluate_turn(
                    _turn_play_eval_payload(
                        case_id=case_id,
                        plan=plan,
                        persona=PERSONA_CONFIGS[persona_id],
                        log=log,
                        selected_suggestion=selected,
                    )
                )
            )
        _write_jsonl(persona_dir / "turn_play_eval_logs.jsonl", rebuilt_turn_records)
        session_report = play_eval_tools.evaluate_session(
            _session_play_eval_payload(
                case_id=case_id,
                preview=preview,
                plan=plan,
                persona_pack=persona_pack,
                persona_id=persona_id,
                logs=logs,
                summary=summary,
                turn_play_eval_logs=rebuilt_turn_records,
            )
        )
        _write_json(persona_dir / "session_play_eval_report.json", session_report)
    return _case_play_eval_summary(case_id, case_artifact_dir)


def _mean_case_metric(summary_payload: dict[str, Any], key: str) -> float:
    rows = list(summary_payload.get("cases") or [])
    values = [float(row.get(key, 0.0)) for row in rows]
    return round(sum(values) / len(values), 4) if values else 0.0


def _build_play_eval_ab_summary(assembled: dict[str, dict[str, Any]]) -> dict[str, Any]:
    variants = {
        variant: {
            "play_v2_narration_profile": assembled[variant]["author_summary"]["config"]["play_v2_narration_profile"],
            **{key: _mean_case_metric(assembled[variant]["play_eval_summary"], key) for key in METRIC_KEYS},
            "top_flags": assembled[variant]["play_eval_summary"].get("top_flags", {}),
        }
        for variant in assembled
    }
    mainline_variant = "npc_texture_v2"
    return {
        "mainline_variant": mainline_variant,
        "variants": variants,
        "comparisons": {},
        "mainline": variants.get(mainline_variant, {}),
    }


def _effect_report(play_eval_ab_summary: dict[str, Any]) -> str:
    lines = [
        "# Play Eval Effect Report",
        "",
        "## Mainline",
        "",
    ]
    mainline_variant = str(play_eval_ab_summary.get("mainline_variant") or "npc_texture_v2")
    mainline = dict(play_eval_ab_summary.get("mainline") or {})
    if not mainline:
        lines.append(f"- 未发现 `{mainline_variant}` 可汇总数据。")
        return "\n".join(lines).rstrip() + "\n"
    lines.append(f"- variant: `{mainline_variant}`")
    lines.append(f"- profile: `{mainline.get('play_v2_narration_profile', 'npc_texture_v2')}`")
    lines.append("")
    lines.append("metrics:")
    for key in METRIC_KEYS:
        lines.append(f"- `{key}`: {float(mainline.get(key, 0.0)):.4f}")
    lines.append("")
    lines.append("top_flags:")
    for key, value in sorted(dict(mainline.get("top_flags") or {}).items()):
        lines.append(f"- `{key}`: {int(value)}")
    return "\n".join(lines).rstrip() + "\n"


def recompute_v1_topic_play_eval(
    output_dir: Path,
    *,
    case_catalog: list[UrbanGoldCase] | None = None,
    variants: tuple[str, ...] = DEFAULT_RECOMPUTE_VARIANTS,
    max_workers: int = 5,
) -> dict[str, Any]:
    root = output_dir.resolve()
    catalog = case_catalog or v1_topic_gold_14()
    unsupported = [variant for variant in variants if variant not in KNOWN_VARIANTS]
    if unsupported:
        raise ValueError(f"unsupported variants for recompute: {unsupported}; only {KNOWN_VARIANTS} is allowed")
    variant_payloads: dict[str, Any] = {}
    for variant in variants:
        variant_root = root / variant
        author_summary = _read_json(variant_root / "author_summary.json")
        token_usage_summary = _read_json(variant_root / "token_usage_summary.json")
        case_summaries: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    _recompute_case_play_eval,
                    _resolve_case_artifact_dir(
                        variant_root=variant_root,
                        case_id=case.case_id,
                    ),
                ): case.case_id
                for case in catalog
            }
            for future in as_completed(future_map):
                case_summaries.append(future.result())
        case_summaries.sort(key=lambda item: item["case_id"])
        play_eval_summary_payload = play_eval_summary(case_summaries)
        persona_coverage_payload = persona_coverage_summary(case_summaries)
        _write_json(variant_root / "play_eval_summary.json", play_eval_summary_payload)
        _write_json(variant_root / "persona_coverage_summary.json", persona_coverage_payload)
        blockers = blockers_markdown(
            title=f"Mainline Blockers ({variant})",
            case_catalog=catalog,
            author_summary=author_summary,
            play_eval_summary_payload=play_eval_summary_payload,
            token_usage_summary_payload=token_usage_summary,
            persona_coverage_payload=persona_coverage_payload,
        )
        (variant_root / "blockers.md").write_text(blockers)
        variant_payloads[variant] = {
            "play_eval_summary": play_eval_summary_payload,
            "case_summaries": case_summaries,
        }
    assembled: dict[str, Any] = {}
    for variant in KNOWN_VARIANTS:
        author_summary_path = root / variant / "author_summary.json"
        play_eval_summary_path = root / variant / "play_eval_summary.json"
        if not author_summary_path.exists():
            continue
        if variant not in variant_payloads and not play_eval_summary_path.exists():
            continue
        assembled[variant] = {
            "author_summary": _read_json(author_summary_path),
            "play_eval_summary": (
                variant_payloads[variant]["play_eval_summary"]
                if variant in variant_payloads
                else _read_json(play_eval_summary_path)
            ),
        }
    play_eval_ab_summary = _build_play_eval_ab_summary(assembled)
    _write_json(root / "play_eval_ab_summary.json", play_eval_ab_summary)
    (root / "play_eval_effect_report.md").write_text(_effect_report(play_eval_ab_summary))
    return {
        "artifacts_dir": str(root),
        "variants": variant_payloads,
        "play_eval_ab_summary": play_eval_ab_summary,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recompute play-eval pass on existing 14-topic live-eval artifacts.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--variant", dest="variants", action="append", choices=KNOWN_VARIANTS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = recompute_v1_topic_play_eval(
        args.output_dir,
        variants=tuple(args.variants) if args.variants else DEFAULT_RECOMPUTE_VARIANTS,
        max_workers=args.max_workers,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
