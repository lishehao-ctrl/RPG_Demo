from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from rpg_backend.author_v2.contracts import QualityTuningProfile
from rpg_backend.config import get_settings
from tools.urban_author_play_benchmarks.gold_eval_full_runner import run_gold_eval_full
from tools.urban_author_play_benchmarks.gold_eval_mini_runner import run_gold_eval_mini

SUCCESS_PLAY = {"completed", "partial_success"}
SUCCESS_LLM = {"completed", "partial_success"}

METRIC_PRIORITY: tuple[str, ...] = (
    "play_turn.control_effectiveness",
    "play_session.control_tradeoff_quality",
    "llm_turn.anti_template_stiffness",
    "llm_session.style_consistency",
    "llm_turn.tone_naturalness",
    "llm_turn.character_specificity",
)


@dataclass(frozen=True)
class MetricSpec:
    key: str
    domain: str
    level: str
    score_key: str


METRIC_SPECS: dict[str, MetricSpec] = {
    "play_turn.control_effectiveness": MetricSpec(
        key="play_turn.control_effectiveness",
        domain="play",
        level="turn",
        score_key="control_effectiveness",
    ),
    "play_session.control_tradeoff_quality": MetricSpec(
        key="play_session.control_tradeoff_quality",
        domain="play",
        level="session",
        score_key="control_tradeoff_quality",
    ),
    "llm_turn.anti_template_stiffness": MetricSpec(
        key="llm_turn.anti_template_stiffness",
        domain="llm",
        level="turn",
        score_key="anti_template_stiffness",
    ),
    "llm_session.style_consistency": MetricSpec(
        key="llm_session.style_consistency",
        domain="llm",
        level="session",
        score_key="style_consistency",
    ),
    "llm_turn.tone_naturalness": MetricSpec(
        key="llm_turn.tone_naturalness",
        domain="llm",
        level="turn",
        score_key="tone_naturalness",
    ),
    "llm_turn.character_specificity": MetricSpec(
        key="llm_turn.character_specificity",
        domain="llm",
        level="turn",
        score_key="character_specificity",
    ),
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        raw = line.strip()
        if not raw:
            continue
        rows.append(json.loads(raw))
    return rows


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _persona_dirs(artifacts_dir: Path) -> list[Path]:
    root = artifacts_dir / "deep_play" / "self_play"
    if not root.exists():
        return []
    out: list[Path] = []
    for case_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for mode_dir in sorted(path for path in case_dir.iterdir() if path.is_dir()):
            personas_dir = mode_dir / "personas"
            if not personas_dir.exists():
                continue
            out.extend(sorted(path for path in personas_dir.iterdir() if path.is_dir()))
    return out


def _turn_context_by_index(persona_dir: Path) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    for row in _read_jsonl(persona_dir / "turn_logs.jsonl"):
        turn_index = int(row.get("turn_index", 0) or 0)
        if turn_index <= 0:
            continue
        output[turn_index] = row
    return output


def _resolve_case_persona(persona_dir: Path) -> tuple[str, str]:
    persona_id = persona_dir.name
    case_id = "unknown"
    try:
        case_id = persona_dir.parents[3].name
    except Exception:  # noqa: BLE001
        pass
    return case_id, persona_id


def _compute_metrics_mean(artifacts_dir: Path) -> dict[str, dict[str, float | int]]:
    values: dict[str, list[float]] = {key: [] for key in METRIC_PRIORITY}
    for persona_dir in _persona_dirs(artifacts_dir):
        for row in _read_jsonl(persona_dir / "turn_play_eval_logs.jsonl"):
            if str(row.get("play_eval_status") or "") not in SUCCESS_PLAY:
                continue
            scores = dict(row.get("scores") or {})
            parsed = _safe_float(scores.get("control_effectiveness"))
            if parsed is not None:
                values["play_turn.control_effectiveness"].append(parsed)
        play_session = persona_dir / "session_play_eval_report.json"
        if play_session.exists():
            row = _read_json(play_session)
            if str(row.get("play_eval_status") or "") in SUCCESS_PLAY:
                scores = dict(row.get("scores") or {})
                parsed = _safe_float(scores.get("control_tradeoff_quality"))
                if parsed is not None:
                    values["play_session.control_tradeoff_quality"].append(parsed)
        for row in _read_jsonl(persona_dir / "turn_llm_text_audit_logs.jsonl"):
            if str(row.get("llm_audit_status") or "") not in SUCCESS_LLM:
                continue
            scores = dict(row.get("scores") or {})
            for metric in (
                "llm_turn.anti_template_stiffness",
                "llm_turn.tone_naturalness",
                "llm_turn.character_specificity",
            ):
                parsed = _safe_float(scores.get(METRIC_SPECS[metric].score_key))
                if parsed is not None:
                    values[metric].append(parsed)
        llm_session = persona_dir / "session_llm_text_audit_report.json"
        if llm_session.exists():
            row = _read_json(llm_session)
            if str(row.get("llm_audit_status") or "") in SUCCESS_LLM:
                scores = dict(row.get("scores") or {})
                parsed = _safe_float(scores.get("style_consistency"))
                if parsed is not None:
                    values["llm_session.style_consistency"].append(parsed)

    return {
        key: {
            "mean": round((sum(series) / len(series)), 4) if series else 0.0,
            "sample_count": len(series),
        }
        for key, series in values.items()
    }


def _lowest_metric(metrics_mean: dict[str, dict[str, float | int]]) -> dict[str, Any]:
    ranked = sorted(
        METRIC_PRIORITY,
        key=lambda key: (
            float(dict(metrics_mean.get(key) or {}).get("mean", 0.0)),
            METRIC_PRIORITY.index(key),
        ),
    )
    metric_key = ranked[0]
    metric_payload = dict(metrics_mean.get(metric_key) or {})
    return {
        "metric_key": metric_key,
        "mean": float(metric_payload.get("mean", 0.0)),
        "sample_count": int(metric_payload.get("sample_count", 0)),
        "tie_break_rule": "metric_priority_order",
        "priority_order": list(METRIC_PRIORITY),
    }


def _representative_turn(
    *,
    turn_map: dict[int, dict[str, Any]],
    preferred_turn_index: int | None,
) -> tuple[int | None, dict[str, Any] | None]:
    if preferred_turn_index is not None and preferred_turn_index in turn_map:
        return preferred_turn_index, turn_map[preferred_turn_index]
    if not turn_map:
        return None, None
    turn_index = max(turn_map)
    return turn_index, turn_map[turn_index]


def _collect_case_study_candidates(
    *,
    artifacts_dir: Path,
    metric_spec: MetricSpec,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for persona_dir in _persona_dirs(artifacts_dir):
        case_id, persona_id = _resolve_case_persona(persona_dir)
        turn_map = _turn_context_by_index(persona_dir)
        if metric_spec.domain == "play" and metric_spec.level == "turn":
            for row in _read_jsonl(persona_dir / "turn_play_eval_logs.jsonl"):
                if str(row.get("play_eval_status") or "") not in SUCCESS_PLAY:
                    continue
                scores = dict(row.get("scores") or {})
                score = _safe_float(scores.get(metric_spec.score_key))
                if score is None:
                    continue
                turn_index = int(row.get("turn_index", 0) or 0)
                turn_ctx = turn_map.get(turn_index, {})
                candidates.append(
                    {
                        "case_id": str(row.get("case_id") or case_id),
                        "persona_id": str(row.get("persona_id") or persona_id),
                        "story_shell_id": str(row.get("story_shell_id") or "unknown"),
                        "segment_role": str(row.get("segment_role") or turn_ctx.get("segment_role") or "unknown"),
                        "turn_index": turn_index,
                        "raw_action_text": str(turn_ctx.get("raw_action_text") or ""),
                        "narration": str(turn_ctx.get("narration") or ""),
                        "progress_summary": str(turn_ctx.get("progress_summary") or ""),
                        "move_family": str(turn_ctx.get("selected_move_family") or ""),
                        "target_id": str(turn_ctx.get("selected_target_id") or ""),
                        "consequence_tags": list(turn_ctx.get("consequence_tags") or []),
                        "score": score,
                        "flags": list(row.get("flags") or []),
                        "main_issue": str(row.get("main_issue") or ""),
                    }
                )
        elif metric_spec.domain == "play" and metric_spec.level == "session":
            session_path = persona_dir / "session_play_eval_report.json"
            if not session_path.exists():
                continue
            row = _read_json(session_path)
            if str(row.get("play_eval_status") or "") not in SUCCESS_PLAY:
                continue
            scores = dict(row.get("scores") or {})
            score = _safe_float(scores.get(metric_spec.score_key))
            if score is None:
                continue
            summary_path = persona_dir / "run_summary.json"
            preferred_turn_index = None
            if summary_path.exists():
                preferred_turn_index = _read_json(summary_path).get("worst_turn_index")
            turn_index, turn_ctx = _representative_turn(
                turn_map=turn_map,
                preferred_turn_index=int(preferred_turn_index) if isinstance(preferred_turn_index, int) else None,
            )
            turn_ctx = turn_ctx or {}
            candidates.append(
                {
                    "case_id": str(row.get("case_id") or case_id),
                    "persona_id": str(row.get("persona_id") or persona_id),
                    "story_shell_id": str(turn_ctx.get("story_shell_id") or "unknown"),
                    "segment_role": str(turn_ctx.get("segment_role") or "unknown"),
                    "turn_index": turn_index,
                    "raw_action_text": str(turn_ctx.get("raw_action_text") or ""),
                    "narration": str(turn_ctx.get("narration") or ""),
                    "progress_summary": str(turn_ctx.get("progress_summary") or ""),
                    "move_family": str(turn_ctx.get("selected_move_family") or ""),
                    "target_id": str(turn_ctx.get("selected_target_id") or ""),
                    "consequence_tags": list(turn_ctx.get("consequence_tags") or []),
                    "score": score,
                    "flags": list(row.get("top_issues") or []),
                    "main_issue": str(row.get("worst_moment") or ""),
                }
            )
        elif metric_spec.domain == "llm" and metric_spec.level == "turn":
            for row in _read_jsonl(persona_dir / "turn_llm_text_audit_logs.jsonl"):
                if str(row.get("llm_audit_status") or "") not in SUCCESS_LLM:
                    continue
                scores = dict(row.get("scores") or {})
                score = _safe_float(scores.get(metric_spec.score_key))
                if score is None:
                    continue
                turn_index = int(row.get("turn_index", 0) or 0)
                turn_ctx = turn_map.get(turn_index, {})
                candidates.append(
                    {
                        "case_id": str(row.get("case_id") or case_id),
                        "persona_id": str(row.get("persona_id") or persona_id),
                        "story_shell_id": str(row.get("story_shell_id") or "unknown"),
                        "segment_role": str(row.get("segment_role") or turn_ctx.get("segment_role") or "unknown"),
                        "turn_index": turn_index,
                        "raw_action_text": str(turn_ctx.get("raw_action_text") or ""),
                        "narration": str(turn_ctx.get("narration") or ""),
                        "progress_summary": str(turn_ctx.get("progress_summary") or ""),
                        "move_family": str(turn_ctx.get("selected_move_family") or ""),
                        "target_id": str(turn_ctx.get("selected_target_id") or ""),
                        "consequence_tags": list(turn_ctx.get("consequence_tags") or []),
                        "score": score,
                        "flags": list(row.get("flags") or []),
                        "main_issue": str(row.get("main_issue") or ""),
                    }
                )
        else:
            session_path = persona_dir / "session_llm_text_audit_report.json"
            if not session_path.exists():
                continue
            row = _read_json(session_path)
            if str(row.get("llm_audit_status") or "") not in SUCCESS_LLM:
                continue
            scores = dict(row.get("scores") or {})
            score = _safe_float(scores.get(metric_spec.score_key))
            if score is None:
                continue
            summary_path = persona_dir / "run_summary.json"
            preferred_turn_index = None
            if summary_path.exists():
                preferred_turn_index = _read_json(summary_path).get("worst_turn_index")
            turn_index, turn_ctx = _representative_turn(
                turn_map=turn_map,
                preferred_turn_index=int(preferred_turn_index) if isinstance(preferred_turn_index, int) else None,
            )
            turn_ctx = turn_ctx or {}
            candidates.append(
                {
                    "case_id": str(row.get("case_id") or case_id),
                    "persona_id": str(row.get("persona_id") or persona_id),
                    "story_shell_id": str(turn_ctx.get("story_shell_id") or "unknown"),
                    "segment_role": str(turn_ctx.get("segment_role") or "unknown"),
                    "turn_index": turn_index,
                    "raw_action_text": str(turn_ctx.get("raw_action_text") or ""),
                    "narration": str(turn_ctx.get("narration") or ""),
                    "progress_summary": str(turn_ctx.get("progress_summary") or ""),
                    "move_family": str(turn_ctx.get("selected_move_family") or ""),
                    "target_id": str(turn_ctx.get("selected_target_id") or ""),
                    "consequence_tags": list(turn_ctx.get("consequence_tags") or []),
                    "score": score,
                    "flags": list(row.get("top_issues") or []),
                    "main_issue": str(row.get("worst_moment") or ""),
                }
            )
    return sorted(
        candidates,
        key=lambda item: (
            float(item.get("score", 0.0)),
            str(item.get("case_id") or ""),
            str(item.get("persona_id") or ""),
            int(item.get("turn_index") or 0),
        ),
    )


def _select_case_study_samples(
    *,
    candidates: list[dict[str, Any]],
    limit: int = 20,
    max_per_case: int = 2,
    max_per_persona: int = 2,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    case_counter: Counter[str] = Counter()
    persona_counter: Counter[str] = Counter()
    shell_seen: set[str] = set()

    for row in candidates:
        if len(selected) >= limit:
            break
        case_id = str(row.get("case_id") or "unknown")
        persona_id = str(row.get("persona_id") or "unknown")
        shell_id = str(row.get("story_shell_id") or "unknown")
        if case_counter[case_id] >= max_per_case or persona_counter[persona_id] >= max_per_persona:
            continue
        if shell_id not in shell_seen:
            selected.append(row)
            case_counter[case_id] += 1
            persona_counter[persona_id] += 1
            shell_seen.add(shell_id)
            continue

    for row in candidates:
        if len(selected) >= limit:
            break
        case_id = str(row.get("case_id") or "unknown")
        persona_id = str(row.get("persona_id") or "unknown")
        if case_counter[case_id] >= max_per_case or persona_counter[persona_id] >= max_per_persona:
            continue
        if row in selected:
            continue
        selected.append(row)
        case_counter[case_id] += 1
        persona_counter[persona_id] += 1

    return selected[:limit]


def _case_study_root_causes(samples: list[dict[str, Any]]) -> dict[str, Any]:
    flag_counter: Counter[str] = Counter()
    segment_counter: Counter[str] = Counter()
    move_counter: Counter[str] = Counter()
    issue_counter: Counter[str] = Counter()
    for row in samples:
        flag_counter.update(str(item) for item in list(row.get("flags") or []) if str(item).strip())
        segment_counter.update([str(row.get("segment_role") or "unknown")])
        move_counter.update([str(row.get("move_family") or "unknown")])
        issue = str(row.get("main_issue") or "").strip()
        if issue:
            issue_counter.update([issue[:80]])
    return {
        "top_flags": [{"flag": key, "count": int(value)} for key, value in flag_counter.most_common(8)],
        "top_segment_roles": [{"segment_role": key, "count": int(value)} for key, value in segment_counter.most_common(8)],
        "top_move_families": [{"move_family": key, "count": int(value)} for key, value in move_counter.most_common(8)],
        "top_issues": [{"issue": key, "count": int(value)} for key, value in issue_counter.most_common(8)],
    }


def _case_study_markdown(
    *,
    metric_key: str,
    samples: list[dict[str, Any]],
    root_causes: dict[str, Any],
) -> str:
    lines = [
        f"# Case Study 20: {metric_key}",
        "",
        "## Root Causes",
        "",
    ]
    for item in list(root_causes.get("top_flags") or []):
        lines.append(f"- flag `{item['flag']}`: {int(item['count'])}")
    for item in list(root_causes.get("top_segment_roles") or []):
        lines.append(f"- segment `{item['segment_role']}`: {int(item['count'])}")
    lines.extend(["", "## Samples", ""])
    for index, row in enumerate(samples, start=1):
        lines.append(
            f"{index}. case={row.get('case_id')} persona={row.get('persona_id')} turn={row.get('turn_index')} "
            f"score={float(row.get('score', 0.0)):.4f} segment={row.get('segment_role')} move={row.get('move_family')}"
        )
        lines.append(f"   - action: {str(row.get('raw_action_text') or '')[:100]}")
        lines.append(f"   - narration: {str(row.get('narration') or '')[:140]}")
        lines.append(f"   - issue: {str(row.get('main_issue') or '')[:120]}")
    return "\n".join(lines) + "\n"


def _extract_quality_profile_from_artifacts(artifacts_dir: Path) -> dict[str, Any] | None:
    for path in (artifacts_dir / "deep_play" / "self_play").rglob("compiled_play_plan.json"):
        try:
            payload = _read_json(path)
        except Exception:  # noqa: BLE001
            continue
        profile = dict(payload.get("quality_tuning_profile") or {})
        if profile:
            return profile
    return None


def _base_quality_profile() -> dict[str, Any]:
    return QualityTuningProfile().model_dump(mode="json")


def _append_unique_moves(dst: list[str], moves: list[str]) -> list[str]:
    merged = [str(item) for item in list(dst) if str(item)]
    for move in moves:
        token = str(move).strip()
        if token and token not in merged:
            merged.append(token)
    return merged[:6]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _apply_segment_intensity_boost(profile: dict[str, Any], segment_roles: list[str], delta: float) -> None:
    intensity = dict(dict(profile.get("author") or {}).get("progression_intensity_by_segment") or {})
    for role in segment_roles:
        current = float(intensity.get(role, 1.0))
        intensity[role] = round(_clamp(current + delta, 0.8, 1.6), 4)
    profile.setdefault("author", {})["progression_intensity_by_segment"] = intensity


def _propose_tuning_candidate(
    *,
    base_profile: dict[str, Any],
    metric_key: str,
    root_causes: dict[str, Any],
    round_index: int,
) -> tuple[dict[str, Any], list[str]]:
    candidate = json.loads(json.dumps(base_profile))
    candidate.setdefault("round_label", f"round_{round_index}")
    candidate.setdefault("note", "")
    play = dict(candidate.get("play") or {})
    author = dict(candidate.get("author") or {})
    notes: list[str] = []

    if metric_key == "play_turn.control_effectiveness":
        play["control_bias_low_confidence"] = round(
            _clamp(float(play.get("control_bias_low_confidence", 0.62)) + 0.05, 0.0, 1.0),
            4,
        )
        play["control_bias_leverage_bonus"] = round(
            _clamp(float(play.get("control_bias_leverage_bonus", 3.0)) + 0.5, 0.0, 6.0),
            4,
        )
        promote = dict(author.get("move_priority_promote_by_segment") or {})
        for role in ("pressure", "reversal"):
            promote[role] = _append_unique_moves(list(promote.get(role) or []), ["accuse", "public_reveal", "probe_secret"])
        author["move_priority_promote_by_segment"] = promote
        play["intent_control_contract_hint_weight"] = round(
            _clamp(float(play.get("intent_control_contract_hint_weight", 1.0)) + 0.2, 0.3, 2.0),
            4,
        )
        play["compose_control_contract_hint_weight"] = round(
            _clamp(float(play.get("compose_control_contract_hint_weight", 1.0)) + 0.15, 0.3, 2.0),
            4,
        )
        author["control_contract_hint_weight"] = round(
            _clamp(float(author.get("control_contract_hint_weight", 1.0)) + 0.1, 0.3, 2.0),
            4,
        )
        _apply_segment_intensity_boost(candidate, ["pressure", "reversal"], 0.05)
        notes.append("提高 free_input 低置信控场升级强度，并增强换手合同 prompt 提示。")
    elif metric_key == "play_session.control_tradeoff_quality":
        play["key_burst_pass2_enabled"] = True
        play["key_burst_pass2_max_retry"] = int(min(int(play.get("key_burst_pass2_max_retry", 1)) + 1, 2))
        play["key_burst_pass2_latency_budget_ms"] = round(
            _clamp(float(play.get("key_burst_pass2_latency_budget_ms", 8000.0)) + 1500.0, 1000.0, 60000.0),
            4,
        )
        _apply_segment_intensity_boost(candidate, ["reveal", "terminal"], 0.06)
        cues = dict(author.get("render_cue_boost_by_segment") or {})
        for role in ("reveal", "terminal"):
            cue_list = [str(item) for item in list(cues.get(role) or []) if str(item).strip()]
            if "style:control:force_public_settlement" not in cue_list:
                cue_list.insert(0, "style:control:force_public_settlement")
            cues[role] = cue_list[:5]
        author["render_cue_boost_by_segment"] = cues
        play["compose_control_contract_hint_weight"] = round(
            _clamp(float(play.get("compose_control_contract_hint_weight", 1.0)) + 0.2, 0.3, 2.0),
            4,
        )
        play["compose_evidence_hint_weight"] = round(
            _clamp(float(play.get("compose_evidence_hint_weight", 1.0)) + 0.2, 0.3, 2.0),
            4,
        )
        author["control_contract_hint_weight"] = round(
            _clamp(float(author.get("control_contract_hint_weight", 1.0)) + 0.15, 0.3, 2.0),
            4,
        )
        notes.append("增强 key_burst 的两步生成，并提高换手合同与可见证据提示权重。")
    elif metric_key == "llm_turn.anti_template_stiffness":
        play["normal_style_case_max"] = int(min(int(play.get("normal_style_case_max", 2)) + 1, 3))
        play["key_burst_style_case_max"] = int(min(int(play.get("key_burst_style_case_max", 3)) + 1, 4))
        play["compose_style_guidance_weight"] = round(
            _clamp(float(play.get("compose_style_guidance_weight", 1.0)) + 0.15, 0.3, 2.0),
            4,
        )
        play["compose_voice_hint_weight"] = round(
            _clamp(float(play.get("compose_voice_hint_weight", 1.0)) + 0.1, 0.3, 2.0),
            4,
        )
        notes.append("增加 style-case 多样化供给，并提升风格引导权重。")
    elif metric_key == "llm_session.style_consistency":
        play["compose_voice_hint_weight"] = round(
            _clamp(float(play.get("compose_voice_hint_weight", 1.0)) + 0.2, 0.3, 2.0),
            4,
        )
        play["normal_supporting_payload_limit"] = int(min(int(play.get("normal_supporting_payload_limit", 1)) + 1, 2))
        play["key_burst_supporting_payload_limit"] = int(min(int(play.get("key_burst_supporting_payload_limit", 2)) + 1, 3))
        notes.append("提高跨回合口吻一致性输入密度与 voice hint 影响力。")
    elif metric_key == "llm_turn.tone_naturalness":
        play["normal_shell_token_limit"] = int(max(int(play.get("normal_shell_token_limit", 5)) - 1, 3))
        play["compose_style_guidance_weight"] = round(
            _clamp(float(play.get("compose_style_guidance_weight", 1.0)) + 0.1, 0.3, 2.0),
            4,
        )
        notes.append("降低壳词堆叠，提升自然口语化引导。")
    elif metric_key == "llm_turn.character_specificity":
        play["compose_voice_hint_weight"] = round(
            _clamp(float(play.get("compose_voice_hint_weight", 1.0)) + 0.25, 0.3, 2.0),
            4,
        )
        play["normal_supporting_payload_limit"] = int(min(int(play.get("normal_supporting_payload_limit", 1)) + 1, 2))
        notes.append("增强角色口吻原子在主写链中的权重。")

    for item in list(root_causes.get("top_segment_roles") or [])[:2]:
        role = str(item.get("segment_role") or "").strip()
        if role in {"opening", "misread", "pressure", "reversal", "reveal", "terminal"}:
            _apply_segment_intensity_boost(candidate, [role], 0.02)

    candidate["play"] = play
    candidate["author"] = author
    validated = QualityTuningProfile.model_validate(candidate)
    return validated.model_dump(mode="json"), notes or ["按最低分指标执行结构化轻量调参。"]


def _dict_diff(before: Any, after: Any) -> Any:
    if isinstance(before, dict) and isinstance(after, dict):
        out: dict[str, Any] = {}
        keys = set(before) | set(after)
        for key in sorted(keys):
            if key not in before:
                out[key] = after[key]
                continue
            if key not in after:
                out[key] = None
                continue
            diff = _dict_diff(before[key], after[key])
            if diff not in ({}, []):
                out[key] = diff
        return out
    if isinstance(before, list) and isinstance(after, list):
        return after if before != after else []
    return after if before != after else {}


def _metric_delta(
    *,
    before: dict[str, dict[str, float | int]],
    after: dict[str, dict[str, float | int]],
) -> dict[str, float]:
    return {
        key: round(
            float(dict(after.get(key) or {}).get("mean", 0.0))
            - float(dict(before.get(key) or {}).get("mean", 0.0)),
            4,
        )
        for key in METRIC_PRIORITY
    }


def _rollback_decision(
    *,
    target_metric_key: str,
    deltas: dict[str, float],
    improve_threshold: float,
    guardrail_drop_threshold: float,
) -> dict[str, Any]:
    target_delta = float(deltas.get(target_metric_key, 0.0))
    other_deltas = [float(deltas.get(key, 0.0)) for key in METRIC_PRIORITY if key != target_metric_key]
    other_min_delta = min(other_deltas) if other_deltas else 0.0
    should_rollback = target_delta < float(improve_threshold) and other_min_delta <= -abs(float(guardrail_drop_threshold))
    return {
        "target_metric_key": target_metric_key,
        "target_delta": round(target_delta, 4),
        "other_min_delta": round(other_min_delta, 4),
        "improve_threshold": round(float(improve_threshold), 4),
        "guardrail_drop_threshold": round(-abs(float(guardrail_drop_threshold)), 4),
        "rollback_triggered": should_rollback,
        "rule": "target_delta < improve_threshold AND other_min_delta <= -guardrail_drop_threshold",
    }


def _round_compare_markdown(
    *,
    round_index: int,
    target_metric_key: str,
    deltas: dict[str, float],
    rollback: dict[str, Any],
    accepted_source: str,
) -> str:
    lines = [
        f"# Round {round_index:02d} Compare",
        "",
        f"- target_metric: `{target_metric_key}`",
        f"- accepted_source: `{accepted_source}`",
        f"- rollback_triggered: `{rollback['rollback_triggered']}`",
        "",
        "## Deltas (post - pre)",
        "",
    ]
    for key in METRIC_PRIORITY:
        lines.append(f"- `{key}`: {float(deltas.get(key, 0.0)):+.4f}")
    lines.extend(
        [
            "",
            "## Rollback Gate",
            "",
            f"- target_delta: {float(rollback['target_delta']):+.4f}",
            f"- other_min_delta: {float(rollback['other_min_delta']):+.4f}",
            f"- improve_threshold: {float(rollback['improve_threshold']):+.4f}",
            f"- guardrail_drop_threshold: {float(rollback['guardrail_drop_threshold']):+.4f}",
        ]
    )
    return "\n".join(lines) + "\n"


def _git_checkpoint() -> dict[str, Any]:
    head = ""
    dirty = False
    branch = ""
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        head = ""
    try:
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        branch = ""
    try:
        status = subprocess.check_output(["git", "status", "--porcelain"], text=True)
        dirty = bool(status.strip())
    except Exception:  # noqa: BLE001
        dirty = False
    return {
        "git_head": head,
        "git_branch": branch,
        "git_dirty": dirty,
    }


@contextmanager
def _quality_patch_env(patch_path: Path | None):
    old = os.environ.get("APP_QUALITY_TUNING_PATCH_PATH")
    if patch_path is None:
        os.environ.pop("APP_QUALITY_TUNING_PATCH_PATH", None)
    else:
        os.environ["APP_QUALITY_TUNING_PATCH_PATH"] = str(patch_path.resolve())
    get_settings.cache_clear()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("APP_QUALITY_TUNING_PATCH_PATH", None)
        else:
            os.environ["APP_QUALITY_TUNING_PATCH_PATH"] = old
        get_settings.cache_clear()


def _run_suite(
    *,
    suite_type: str,
    output_dir: Path,
    profile_payload: dict[str, Any] | None,
    case_max_workers: int,
    total_rpm_limit: int,
    case_timeout_seconds: float,
    case_aggregate_timeout_seconds: float,
    session_play_eval_timeout_seconds: float,
    select_id_probability: float,
) -> dict[str, Any]:
    patch_path: Path | None = None
    if profile_payload is not None:
        patch_path = output_dir / "quality_tuning_patch.json"
        _write_json(
            patch_path,
            {
                "schema_version": 1,
                "quality_tuning_profile": profile_payload,
            },
        )
    with _quality_patch_env(patch_path):
        if suite_type == "mini":
            return run_gold_eval_mini(
                output_dir,
                case_max_workers=case_max_workers,
                total_rpm_limit=total_rpm_limit,
                case_timeout_seconds=case_timeout_seconds,
                case_aggregate_timeout_seconds=case_aggregate_timeout_seconds,
                session_play_eval_timeout_seconds=session_play_eval_timeout_seconds,
                select_id_probability=select_id_probability,
            )
        return run_gold_eval_full(
            output_dir,
            profile="standard",
            case_max_workers=case_max_workers,
            total_rpm_limit=total_rpm_limit,
            case_timeout_seconds=case_timeout_seconds,
            case_aggregate_timeout_seconds=case_aggregate_timeout_seconds,
            session_play_eval_timeout_seconds=session_play_eval_timeout_seconds,
            select_id_probability=select_id_probability,
        )


def _loop_summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Five-Round Quality Loop Summary",
        "",
        f"- rounds: {int(payload.get('rounds', 0))}",
        f"- accepted_final_round: {payload.get('accepted_final_round')}",
        f"- final_suite: {payload.get('final_suite')}",
        "",
        "## Accepted Metrics By Round (mean)",
        "",
    ]
    accepted_curve = list(payload.get("accepted_curve") or [])
    for row in accepted_curve:
        lines.append(
            f"- round {int(row.get('round', 0)):02d} ({row.get('suite')}): "
            + " | ".join(
                f"{metric}={float(row.get(metric, 0.0)):.4f}"
                for metric in METRIC_PRIORITY
            )
        )
    lines.extend(["", "## Rollback Decisions", ""])
    for row in list(payload.get("round_results") or []):
        lines.append(
            f"- round {int(row.get('round', 0)):02d}: rollback={bool(row.get('rolled_back'))} "
            f"target={row.get('target_metric_key')} target_delta={float(row.get('target_delta', 0.0)):+.4f} "
            f"other_min_delta={float(row.get('other_min_delta', 0.0)):+.4f}"
        )
    return "\n".join(lines) + "\n"


def run_five_round_quality_loop(
    output_dir: Path,
    *,
    rounds: int = 5,
    mini_rounds: int = 4,
    case_max_workers: int = 40,
    total_rpm_limit: int = 200,
    case_timeout_seconds: float = 600.0,
    case_aggregate_timeout_seconds: float = 1800.0,
    session_play_eval_timeout_seconds: float = 300.0,
    select_id_probability: float = 0.1,
    improve_threshold: float = 0.1,
    guardrail_drop_threshold: float = 0.15,
) -> dict[str, Any]:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    accepted_profile: dict[str, Any] | None = None
    round_results: list[dict[str, Any]] = []
    accepted_curve: list[dict[str, Any]] = []
    final_suite = "mini"

    for round_index in range(1, max(1, rounds) + 1):
        suite_type = "mini" if round_index <= max(0, mini_rounds) else "full"
        final_suite = suite_type
        round_dir = root / f"round_{round_index:02d}_{suite_type}"
        pre_dir = round_dir / "pre_eval"
        post_dir = round_dir / "post_eval"
        round_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = _git_checkpoint()

        pre_result = _run_suite(
            suite_type=suite_type,
            output_dir=pre_dir,
            profile_payload=accepted_profile,
            case_max_workers=case_max_workers,
            total_rpm_limit=total_rpm_limit,
            case_timeout_seconds=case_timeout_seconds,
            case_aggregate_timeout_seconds=case_aggregate_timeout_seconds,
            session_play_eval_timeout_seconds=session_play_eval_timeout_seconds,
            select_id_probability=select_id_probability,
        )
        pre_artifacts = Path(str(pre_result.get("artifacts_dir") or pre_dir))
        pre_metrics = _compute_metrics_mean(pre_artifacts)
        if accepted_profile is None:
            accepted_profile = _extract_quality_profile_from_artifacts(pre_artifacts) or _base_quality_profile()

        lowest = _lowest_metric(pre_metrics)
        metric_key = str(lowest["metric_key"])
        metric_spec = METRIC_SPECS[metric_key]
        candidates = _collect_case_study_candidates(
            artifacts_dir=pre_artifacts,
            metric_spec=metric_spec,
        )
        samples = _select_case_study_samples(candidates=candidates, limit=20)
        root_causes = _case_study_root_causes(samples)
        case_study_payload = {
            "metric_key": metric_key,
            "sample_count": len(samples),
            "samples": samples,
            "root_causes": root_causes,
        }
        _write_json(round_dir / "case_study_20.json", case_study_payload)
        (round_dir / "case_study_20.md").write_text(
            _case_study_markdown(metric_key=metric_key, samples=samples, root_causes=root_causes)
        )

        candidate_profile, tuning_notes = _propose_tuning_candidate(
            base_profile=accepted_profile,
            metric_key=metric_key,
            root_causes=root_causes,
            round_index=round_index,
        )
        patch_diff = _dict_diff(accepted_profile, candidate_profile)
        proposed_patch_payload = {
            "schema_version": 1,
            "target_metric_key": metric_key,
            "notes": tuning_notes,
            "quality_tuning_profile": patch_diff,
            "quality_tuning_profile_full": candidate_profile,
        }
        _write_json(round_dir / "proposed_tuning_patch.json", proposed_patch_payload)

        post_result = _run_suite(
            suite_type=suite_type,
            output_dir=post_dir,
            profile_payload=candidate_profile,
            case_max_workers=case_max_workers,
            total_rpm_limit=total_rpm_limit,
            case_timeout_seconds=case_timeout_seconds,
            case_aggregate_timeout_seconds=case_aggregate_timeout_seconds,
            session_play_eval_timeout_seconds=session_play_eval_timeout_seconds,
            select_id_probability=select_id_probability,
        )
        post_artifacts = Path(str(post_result.get("artifacts_dir") or post_dir))
        post_metrics = _compute_metrics_mean(post_artifacts)
        deltas = _metric_delta(before=pre_metrics, after=post_metrics)
        rollback = _rollback_decision(
            target_metric_key=metric_key,
            deltas=deltas,
            improve_threshold=improve_threshold,
            guardrail_drop_threshold=guardrail_drop_threshold,
        )
        rolled_back = bool(rollback["rollback_triggered"])
        accepted_source = "pre" if rolled_back else "post"
        accepted_metrics = pre_metrics if rolled_back else post_metrics
        accepted_artifacts = pre_artifacts if rolled_back else post_artifacts
        if not rolled_back:
            accepted_profile = candidate_profile

        metrics_payload = {
            "pre": pre_metrics,
            "post": post_metrics,
            "accepted_source": accepted_source,
            "accepted": accepted_metrics,
        }
        _write_json(round_dir / "metrics_mean.json", metrics_payload)
        _write_json(round_dir / "lowest_metric.json", lowest)
        _write_json(round_dir / "rollback_decision.json", rollback)
        round_compare = {
            "round": round_index,
            "suite": suite_type,
            "target_metric_key": metric_key,
            "deltas": deltas,
            "accepted_source": accepted_source,
            "rollback": rollback,
        }
        _write_json(round_dir / "round_compare.json", round_compare)
        (round_dir / "round_compare.md").write_text(
            _round_compare_markdown(
                round_index=round_index,
                target_metric_key=metric_key,
                deltas=deltas,
                rollback=rollback,
                accepted_source=accepted_source,
            )
        )
        round_manifest = {
            "round": round_index,
            "suite": suite_type,
            "checkpoint": checkpoint,
            "target_metric_key": metric_key,
            "rolled_back": rolled_back,
            "accepted_source": accepted_source,
            "pre_artifacts_dir": str(pre_artifacts),
            "post_artifacts_dir": str(post_artifacts),
            "accepted_artifacts_dir": str(accepted_artifacts),
            "improve_threshold": improve_threshold,
            "guardrail_drop_threshold": guardrail_drop_threshold,
        }
        _write_json(round_dir / "round_manifest.json", round_manifest)

        perf_summary = _read_json(accepted_artifacts / "performance_summary.json")
        round_result = {
            "round": round_index,
            "suite": suite_type,
            "target_metric_key": metric_key,
            "rolled_back": rolled_back,
            "target_delta": rollback["target_delta"],
            "other_min_delta": rollback["other_min_delta"],
            "accepted_artifacts_dir": str(accepted_artifacts),
            "accepted_metrics_mean": {key: float(dict(accepted_metrics.get(key) or {}).get("mean", 0.0)) for key in METRIC_PRIORITY},
            "accepted_performance_summary": perf_summary,
        }
        round_results.append(round_result)
        accepted_curve.append(
            {
                "round": round_index,
                "suite": suite_type,
                **{key: float(dict(accepted_metrics.get(key) or {}).get("mean", 0.0)) for key in METRIC_PRIORITY},
            }
        )

    summary = {
        "rounds": max(1, rounds),
        "mini_rounds": max(0, mini_rounds),
        "accepted_final_round": round_results[-1]["round"] if round_results else 0,
        "final_suite": final_suite,
        "round_results": round_results,
        "accepted_curve": accepted_curve,
    }
    _write_json(root / "five_round_loop_summary.json", summary)
    (root / "five_round_loop_summary.md").write_text(_loop_summary_markdown(summary))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run five-round strict eval optimization loop with auto rollback.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--mini-rounds", type=int, default=4)
    parser.add_argument("--case-max-workers", type=int, default=40)
    parser.add_argument("--total-rpm-limit", type=int, default=200)
    parser.add_argument("--case-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--case-aggregate-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--session-play-eval-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--select-id-probability", type=float, default=0.1)
    parser.add_argument("--improve-threshold", type=float, default=0.1)
    parser.add_argument("--guardrail-drop-threshold", type=float, default=0.15)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_five_round_quality_loop(
        args.output_dir,
        rounds=max(1, int(args.rounds)),
        mini_rounds=max(0, int(args.mini_rounds)),
        case_max_workers=max(1, int(args.case_max_workers)),
        total_rpm_limit=max(1, int(args.total_rpm_limit)),
        case_timeout_seconds=max(30.0, float(args.case_timeout_seconds)),
        case_aggregate_timeout_seconds=max(60.0, float(args.case_aggregate_timeout_seconds)),
        session_play_eval_timeout_seconds=max(30.0, float(args.session_play_eval_timeout_seconds)),
        select_id_probability=min(max(float(args.select_id_probability), 0.0), 1.0),
        improve_threshold=max(0.0, float(args.improve_threshold)),
        guardrail_drop_threshold=max(0.0, float(args.guardrail_drop_threshold)),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
