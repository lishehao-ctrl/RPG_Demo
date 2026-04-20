from __future__ import annotations

from typing import Any


def _float(value: Any) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return 0


def build_semantic_autotune_patch(
    *,
    play_eval_ab_summary: dict[str, Any],
    failure_pack_eval_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    delta = dict(play_eval_ab_summary.get("delta") or {})
    flag_delta = dict(play_eval_ab_summary.get("flag_delta") or {})
    failure_delta = dict((failure_pack_eval_summary or {}).get("delta") or {})
    failure_flag_delta = dict((failure_pack_eval_summary or {}).get("focus_flag_delta") or {})

    score = {
        "control_tradeoff_quality": _float(delta.get("avg_control_tradeoff_quality")),
        "npc_interest_divergence": _float(delta.get("avg_npc_interest_divergence")),
        "payoff_realization": _float(delta.get("avg_payoff_realization")),
        "shell_system_activation": _float(delta.get("avg_shell_system_activation")),
        "intent_binding": _float(delta.get("avg_turn_intent_binding")),
    }
    flags = {
        "角色反应太泛": _int(flag_delta.get("角色反应太泛")),
        "选择不够痛": _int(flag_delta.get("选择不够痛")),
        "爆点没落地": _int(flag_delta.get("爆点没落地")),
        "发酵停滞": _int(flag_delta.get("发酵停滞")),
    }
    if failure_pack_eval_summary:
        flags["发酵停滞"] += _int(failure_flag_delta.get("发酵停滞"))
        flags["爆点没落地"] += _int(failure_flag_delta.get("爆点没落地"))

    recommendations: dict[str, Any] = {
        "utility_weight_profile": {},
        "cost_intensity_profile": {
            "segment_role_multiplier_delta": {},
            "control_action_multiplier_delta": {},
            "shell_multiplier_delta": {},
        },
        "callback_policy": {
            "due_turn_min_offset_delta": 0,
            "due_turn_max_offset_delta": 0,
        },
        "question_progress_policy": {},
    }
    notes: list[str] = []

    if score["npc_interest_divergence"] < 0 or flags["角色反应太泛"] > 0:
        recommendations["utility_weight_profile"].update(
            {
                "utility_delta_weight_delta": 1,
                "role_diversity_weight_delta": 1,
                "intent_hit_weight_delta": 1 if score["intent_binding"] < 0 else 0,
            }
        )
        notes.append("角色分化偏弱：提高 utility/role_diversity 权重，优先让“谁得利谁出手”。")

    if score["control_tradeoff_quality"] < 0 or flags["选择不够痛"] >= 0:
        recommendations["cost_intensity_profile"]["control_action_multiplier_delta"].update(
            {
                "redirect": 0.08,
                "detonate": 0.12,
                "press": -0.05,
            }
        )
        recommendations["callback_policy"]["due_turn_min_offset_delta"] = -1
        notes.append("控雷交换偏弱：提高 redirect/detonate 成本强度并缩短回咬时滞。")

    payoff_regressed = score["payoff_realization"] < 0 or flags["爆点没落地"] > 0
    if payoff_regressed or _float(failure_delta.get("avg_payoff_realization")) < 0:
        recommendations["cost_intensity_profile"]["segment_role_multiplier_delta"].update(
            {
                "reveal": 0.1,
                "terminal": 0.15,
            }
        )
        recommendations["question_progress_policy"].update(
            {
                "key_segment_force_resolve_secret_exposure_delta": -1,
                "key_segment_force_resolve_progress_threshold_delta": -1,
            }
        )
        notes.append("关键段落锤偏弱：提升 reveal/terminal 强度并提前触发 resolve 条件。")

    if flags["发酵停滞"] >= 0:
        recommendations["callback_policy"]["due_turn_max_offset_delta"] = -1
        recommendations["cost_intensity_profile"]["segment_role_multiplier_delta"].update(
            {
                "pressure": 0.08,
                "reversal": 0.08,
            }
        )
        notes.append("发酵停滞未改善：收紧 callback 到期窗口并提高 pressure/reversal 段推进力度。")

    if score["shell_system_activation"] < 0:
        recommendations["cost_intensity_profile"]["shell_multiplier_delta"].update(
            {
                "entertainment_scandal": 0.05,
                "campus_romance": 0.05,
            }
        )
        notes.append("壳子系统激活下降：提高校园/娱乐关键壳子的强度偏置。")

    return {
        "schema_version": 1,
        "signals": {
            "delta": score,
            "flags": flags,
        },
        "recommended_overrides": recommendations,
        "notes": notes or ["当前回合指标稳定，可维持现策略并继续观察下一轮。"],
    }


def render_semantic_autotune_notes(patch: dict[str, Any]) -> str:
    notes = list(patch.get("notes") or [])
    lines = [
        "# Light Semantic Autotune Notes",
        "",
        "## Signals",
        "",
    ]
    signals = dict(patch.get("signals") or {})
    delta = dict(signals.get("delta") or {})
    flags = dict(signals.get("flags") or {})
    for key in sorted(delta):
        lines.append(f"- `{key}`: {float(delta.get(key, 0.0)):+.4f}")
    lines.extend(["", "## Flags", ""])
    for key in sorted(flags):
        lines.append(f"- `{key}`: {int(flags.get(key, 0)):+d}")
    lines.extend(["", "## Recommendations", ""])
    for note in notes:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
