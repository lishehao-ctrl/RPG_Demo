from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PLAY_EVAL_FLAGS = ("角色反应太泛", "选择不够痛", "爆点没落地", "控雷失效", "发酵停滞", "壳子系统未激活")
KEY_SEGMENT_ROLES = {"reveal", "terminal"}
SHELL_KEY_SEGMENT_ANCHORS: dict[str, tuple[str, ...]] = {
    "entertainment_scandal": ("镜头", "热搜", "公关", "切割", "公屏", "版本"),
    "campus_romance": ("台下", "评审", "名额", "社团", "熟人", "站队"),
    "office_power": ("会议室", "汇报线", "考核", "职级", "项目线"),
    "wealth_families": ("董事会", "家宴", "继承", "顺位", "家族"),
}


class TurnPlayEvalScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consequence_impact: int = Field(ge=1, le=5)
    intent_binding: int = Field(ge=1, le=5)
    pressure_exchange: int = Field(ge=1, le=5)
    control_effectiveness: int = Field(ge=1, le=5)
    trigger_conversion: int = Field(ge=1, le=5)
    foreshadow_clarity: int = Field(ge=1, le=5)
    shell_signal_fidelity: int = Field(ge=1, le=5)
    npc_agency_reversal: int = Field(ge=1, le=5)


class TurnPlayEvalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    turn_index: int = Field(ge=1)
    story_shell_id: str = Field(min_length=1)
    segment_role: str = Field(min_length=1)
    play_eval_status: Literal["completed", "failed"] = "completed"
    scores: TurnPlayEvalScores | None = None
    strongest_signal: str | None = Field(default=None, max_length=220)
    main_issue: str | None = Field(default=None, max_length=220)
    flags: list[str] = Field(default_factory=list, max_length=6)
    key_segment_shell_anchor_hit: bool | None = None
    play_eval_error: str | None = Field(default=None, max_length=240)


class SessionPlayEvalScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategic_tension_curve: int = Field(ge=1, le=5)
    consequence_legibility: int = Field(ge=1, le=5)
    payoff_realization: int = Field(ge=1, le=5)
    npc_interest_divergence: int = Field(ge=1, le=5)
    control_tradeoff_quality: int = Field(ge=1, le=5)
    shell_system_activation: int = Field(ge=1, le=5)
    ending_cost_integrity: int = Field(ge=1, le=5)
    replay_variance: int = Field(ge=1, le=5)


class SessionPlayEvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    play_eval_status: Literal["completed", "failed"] = "completed"
    scores: SessionPlayEvalScores | None = None
    best_moment: str | None = Field(default=None, max_length=240)
    worst_moment: str | None = Field(default=None, max_length=240)
    one_sentence_verdict: str | None = Field(default=None, max_length=240)
    top_issues: list[str] = Field(default_factory=list, max_length=5)
    top_strengths: list[str] = Field(default_factory=list, max_length=5)
    extended_metrics: dict[str, float] | None = None
    play_eval_error: str | None = Field(default=None, max_length=240)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _clamp_score(value: int) -> int:
    return max(1, min(5, int(value)))


def _score_1_to_5(value: Any, *, default: int = 3) -> int:
    return _clamp_score(_safe_int(value, default))


def _numeric_dict_magnitude(values: dict[str, Any]) -> int:
    magnitude = 0
    for raw in values.values():
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            magnitude += abs(int(raw))
    return magnitude


def _relationship_delta_magnitude(values: dict[str, Any]) -> tuple[int, int]:
    if not isinstance(values, dict):
        return 0, 0
    touched = 0
    magnitude = 0
    for nested in values.values():
        if not isinstance(nested, dict):
            continue
        nested_mag = _numeric_dict_magnitude(nested)
        if nested_mag > 0:
            touched += 1
            magnitude += nested_mag
    return touched, magnitude


def _delta_sign_presence(global_deltas: dict[str, Any], relation_deltas: dict[str, Any]) -> tuple[bool, bool]:
    has_positive = False
    has_negative = False
    for raw in list(global_deltas.values()):
        if isinstance(raw, (int, float)):
            if raw > 0:
                has_positive = True
            if raw < 0:
                has_negative = True
    for nested in list(relation_deltas.values()):
        if not isinstance(nested, dict):
            continue
        for raw in list(nested.values()):
            if isinstance(raw, (int, float)):
                if raw > 0:
                    has_positive = True
                if raw < 0:
                    has_negative = True
    return has_positive, has_negative


def _flatten_reaction_causes(reaction_causes: dict[str, Any]) -> list[str]:
    if not isinstance(reaction_causes, dict):
        return []
    tags: list[str] = []
    for raw in reaction_causes.values():
        if not isinstance(raw, list):
            continue
        tags.extend(str(item) for item in raw if isinstance(item, str))
    return tags


def _normalize_flags(values: list[str]) -> list[str]:
    allowed = set(PLAY_EVAL_FLAGS)
    return [flag for flag in values if flag in allowed][:6]


def _key_segment_shell_anchor_hit(
    *,
    story_shell_id: str,
    segment_role: str,
    narration: str,
) -> bool | None:
    if segment_role not in KEY_SEGMENT_ROLES:
        return None
    anchors = SHELL_KEY_SEGMENT_ANCHORS.get(story_shell_id)
    if not anchors:
        return None
    text = str(narration or "").strip()
    if not text:
        return False
    return any(anchor in text for anchor in anchors)


def evaluate_turn(payload: dict[str, Any]) -> TurnPlayEvalRecord:
    case_id = str(payload.get("case_id") or "unknown_case")
    persona_id = str(payload.get("persona_id") or "unknown_persona")
    turn_index = max(1, _safe_int(payload.get("turn_index"), 1))
    story_shell_id = str(payload.get("story_shell_id") or "unknown_shell")
    segment_role = str(payload.get("segment_role") or "opening")
    try:
        selected = dict(payload.get("selected_suggestion") or {})
        feedback = dict(payload.get("feedback") or {})
        global_deltas = dict(feedback.get("last_turn_global_deltas") or {})
        relation_deltas = dict(feedback.get("last_turn_relationship_deltas") or {})
        reaction_causes = dict(feedback.get("last_turn_reaction_causes") or {})
        consequence_tags = [str(item) for item in list(feedback.get("consequence_tags") or []) if isinstance(item, str)]
        consequences = [str(item) for item in list(feedback.get("last_turn_consequences") or []) if isinstance(item, str)]
        narration = str(payload.get("narration") or "")
        reaction_tags = _flatten_reaction_causes(reaction_causes)
        control_resolution = dict(feedback.get("control_resolution") or payload.get("control_resolution") or {})
        lane_id = str(selected.get("lane_id") or "")
        move_family = str(selected.get("move_family") or "")
        target_id = str(selected.get("target_id") or "")
        reveal_phase = segment_role in KEY_SEGMENT_ROLES
        global_mag = _numeric_dict_magnitude(global_deltas)
        relation_touched, relation_mag = _relationship_delta_magnitude(relation_deltas)
        pressure_mag = global_mag + relation_mag
        has_positive, has_negative = _delta_sign_presence(global_deltas, relation_deltas)
        tags = set(consequence_tags)
        has_trigger = any(":triggered" in tag for tag in tags)
        has_foreshadow = any(":foreshadowed" in tag for tag in tags)
        has_press = any(":press" in tag for tag in tags)
        has_redirect = any(":redirect" in tag for tag in tags)
        has_detonate = any(":detonate" in tag for tag in tags)
        has_npc_action = any("latent:npc_action" in tag for tag in tags)
        has_relationship_debt = any("latent:relationship_debt" in tag for tag in tags)
        has_public_wave = any("latent:public_wave" in tag for tag in tags)
        action_type = str(control_resolution.get("action_type") or "none")
        control_applied = bool(control_resolution.get("applied"))
        intent_signals = sum(
            1
            for marker in ("intent_loss_triggered", "opportunity_window", "protective_stake", "sacrifice_window")
            if marker in set(reaction_tags)
        )

        consequence_impact = 1
        if pressure_mag >= 3:
            consequence_impact += 1
        if pressure_mag >= 7:
            consequence_impact += 1
        if relation_touched >= 2 or relation_mag >= 4:
            consequence_impact += 1
        if has_trigger or has_detonate:
            consequence_impact += 1
        if any(abs(_safe_int(global_deltas.get(key))) >= 2 for key in ("public_image", "route_lock", "secret_exposure", "scene_heat")):
            consequence_impact += 1
        consequence_impact = _clamp_score(consequence_impact)

        intent_binding = 1
        if target_id:
            intent_binding += 1
        if relation_touched >= 1:
            intent_binding += 1
        if intent_signals >= 1:
            intent_binding += 1
        if relation_touched >= 2 or intent_signals >= 2:
            intent_binding += 1
        intent_binding = _clamp_score(intent_binding)

        pressure_exchange = 1
        if pressure_mag >= 3:
            pressure_exchange += 1
        if has_positive and has_negative:
            pressure_exchange += 1
        if lane_id in {"side", "burst"} or move_family in {"betray", "public_reveal", "accuse"}:
            pressure_exchange += 1
        if has_redirect or has_detonate or has_trigger:
            pressure_exchange += 1
        pressure_exchange = _clamp_score(pressure_exchange)

        if action_type == "none":
            control_effectiveness = 2 + (1 if has_press or has_redirect or has_detonate else 0)
        else:
            control_effectiveness = 1
            if control_applied:
                control_effectiveness += 2
                if any(f":{action_type}" in tag for tag in tags):
                    control_effectiveness += 1
                if action_type == "detonate" and (has_trigger or has_detonate):
                    control_effectiveness += 1
        control_effectiveness = _clamp_score(control_effectiveness)

        trigger_conversion = 1
        if has_foreshadow:
            trigger_conversion += 1
        if has_trigger or has_detonate:
            trigger_conversion += 2
        if reveal_phase and (has_trigger or has_detonate):
            trigger_conversion += 1
        trigger_conversion = _clamp_score(trigger_conversion)
        if reveal_phase and not (has_trigger or has_detonate):
            trigger_conversion = min(trigger_conversion, 3)

        foreshadow_clarity = 1
        if has_foreshadow:
            foreshadow_clarity += 2
        if has_foreshadow and consequences:
            foreshadow_clarity += 1
        if has_trigger and has_foreshadow:
            foreshadow_clarity += 1
        elif has_trigger:
            foreshadow_clarity += 1
        foreshadow_clarity = _clamp_score(foreshadow_clarity)

        shell_signal_fidelity = 2
        if has_trigger or has_foreshadow:
            shell_signal_fidelity += 1
        if story_shell_id == "entertainment_scandal":
            if has_public_wave or abs(_safe_int(global_deltas.get("public_image"))) >= 1:
                shell_signal_fidelity += 1
            if has_trigger and (has_public_wave or has_npc_action):
                shell_signal_fidelity += 1
        elif story_shell_id == "campus_romance":
            if has_relationship_debt or relation_touched >= 1:
                shell_signal_fidelity += 1
            if relation_touched >= 2 or abs(_safe_int(global_deltas.get("route_lock"))) >= 1:
                shell_signal_fidelity += 1
        else:
            if pressure_mag >= 4:
                shell_signal_fidelity += 1
            if has_trigger:
                shell_signal_fidelity += 1
        key_segment_anchor_hit = _key_segment_shell_anchor_hit(
            story_shell_id=story_shell_id,
            segment_role=segment_role,
            narration=narration,
        )
        if key_segment_anchor_hit is False:
            shell_signal_fidelity = max(1, shell_signal_fidelity - 1)
        shell_signal_fidelity = _clamp_score(shell_signal_fidelity)

        npc_agency_reversal = 1
        if has_npc_action:
            npc_agency_reversal += 2
        if has_trigger and has_npc_action:
            npc_agency_reversal += 1
        if relation_touched >= 2:
            npc_agency_reversal += 1
        if not target_id and (has_npc_action or relation_touched >= 1):
            npc_agency_reversal += 1
        npc_agency_reversal = _clamp_score(npc_agency_reversal)

        flags: list[str] = []
        if intent_binding <= 2:
            flags.append("角色反应太泛")
        if pressure_exchange <= 2:
            flags.append("选择不够痛")
        if reveal_phase and trigger_conversion <= 2:
            flags.append("爆点没落地")
        if action_type != "none" and control_effectiveness <= 2:
            flags.append("控雷失效")
        if foreshadow_clarity <= 2 and not (has_trigger or has_detonate):
            flags.append("发酵停滞")
        if shell_signal_fidelity <= 2:
            flags.append("壳子系统未激活")
        if key_segment_anchor_hit is False and story_shell_id in {"campus_romance", "entertainment_scandal"}:
            flags.append("壳子系统未激活")
        normalized_flags = _normalize_flags(flags)

        strongest_signal = None
        if consequences:
            strongest_signal = max(consequences, key=len)[:220]
        elif isinstance(control_resolution.get("summary"), str) and str(control_resolution.get("summary")).strip():
            strongest_signal = str(control_resolution.get("summary"))[:220]
        elif isinstance(payload.get("progress_summary"), str):
            strongest_signal = str(payload.get("progress_summary"))[:220] or None

        main_issue = None
        if "爆点没落地" in normalized_flags:
            main_issue = "前兆有了，但没有完成本回合应有的落锤。"
        elif "角色反应太泛" in normalized_flags:
            main_issue = "意图命中不足，反应仍偏通用态度。"
        elif "选择不够痛" in normalized_flags:
            main_issue = "代价交换偏平，局势没有被迫换手。"
        elif "控雷失效" in normalized_flags:
            main_issue = "控雷动作没有有效改变风险走向。"
        elif "发酵停滞" in normalized_flags:
            main_issue = "积压事件没有继续升温或转化。"
        elif "壳子系统未激活" in normalized_flags:
            main_issue = "壳子机制信号过弱，场域辨识度不足。"

        return TurnPlayEvalRecord(
            case_id=case_id,
            persona_id=persona_id,
            turn_index=turn_index,
            story_shell_id=story_shell_id,
            segment_role=segment_role,
            play_eval_status="completed",
            scores=TurnPlayEvalScores(
                consequence_impact=consequence_impact,
                intent_binding=intent_binding,
                pressure_exchange=pressure_exchange,
                control_effectiveness=control_effectiveness,
                trigger_conversion=trigger_conversion,
                foreshadow_clarity=foreshadow_clarity,
                shell_signal_fidelity=shell_signal_fidelity,
                npc_agency_reversal=npc_agency_reversal,
            ),
            strongest_signal=strongest_signal,
            main_issue=main_issue,
            flags=normalized_flags,
            key_segment_shell_anchor_hit=key_segment_anchor_hit,
        )
    except Exception as exc:  # noqa: BLE001
        return TurnPlayEvalRecord(
            case_id=case_id,
            persona_id=persona_id,
            turn_index=turn_index,
            story_shell_id=story_shell_id,
            segment_role=segment_role,
            play_eval_status="failed",
            play_eval_error=str(exc)[:240],
        )


def evaluate_session(payload: dict[str, Any]) -> SessionPlayEvalReport:
    case_id = str(payload.get("case_id") or "unknown_case")
    persona_id = str(payload.get("persona_id") or "unknown_persona")
    try:
        run_summary = dict(payload.get("run_summary") or {})
        turn_summary = dict(payload.get("turn_play_eval_summary") or {})
        avg_turn_scores = dict(turn_summary.get("avg_scores") or {})
        turn_logs = [dict(item) for item in list(payload.get("turn_logs") or []) if isinstance(item, dict)]
        turn_count = max(1, _safe_int(run_summary.get("turn_count"), len(turn_logs)))
        ending_reached = bool(run_summary.get("ending_reached"))
        ending_strength = _safe_int(run_summary.get("ending_strength"), 0)
        lane_counts = dict(run_summary.get("lane_counts") or {})
        unique_lanes = len([lane for lane, count in lane_counts.items() if _safe_int(count) > 0])
        unique_targets = len(
            {
                str(item.get("selected_target_id"))
                for item in turn_logs
                if isinstance(item.get("selected_target_id"), str) and str(item.get("selected_target_id"))
            }
        )
        flag_counts = dict(turn_summary.get("flag_counts") or {})
        key_segment_anchor_hit_rate = turn_summary.get("key_segment_shell_anchor_hit_rate")
        if key_segment_anchor_hit_rate is None:
            key_segment_hits = 0
            key_segment_total = 0
            for row in turn_logs:
                turn_play_eval = row.get("turn_play_eval")
                if not isinstance(turn_play_eval, dict):
                    continue
                marker = turn_play_eval.get("key_segment_shell_anchor_hit")
                if marker is None:
                    continue
                key_segment_total += 1
                if bool(marker):
                    key_segment_hits += 1
            key_segment_anchor_hit_rate = (
                round(key_segment_hits / key_segment_total, 4)
                if key_segment_total > 0
                else 0.0
            )
        key_segment_anchor_hit_rate = max(0.0, min(1.0, float(key_segment_anchor_hit_rate)))

        def _avg_turn_metric(metric: str, default: int = 3) -> int:
            candidate = avg_turn_scores.get(metric)
            if candidate is not None:
                return _score_1_to_5(candidate, default=default)
            values: list[int] = []
            for row in turn_logs:
                turn_play_eval = row.get("turn_play_eval")
                if not isinstance(turn_play_eval, dict):
                    continue
                scores = dict(turn_play_eval.get("scores") or {})
                if metric in scores:
                    values.append(_score_1_to_5(scores.get(metric), default=default))
            if not values:
                return default
            return _score_1_to_5(round(mean(values)), default=default)

        avg_consequence_impact = _avg_turn_metric("consequence_impact")
        avg_intent_binding = _avg_turn_metric("intent_binding")
        avg_pressure_exchange = _avg_turn_metric("pressure_exchange")
        avg_control_effectiveness = _avg_turn_metric("control_effectiveness")
        avg_trigger_conversion = _avg_turn_metric("trigger_conversion", default=2)
        avg_foreshadow_clarity = _avg_turn_metric("foreshadow_clarity", default=2)
        avg_shell_fidelity = _avg_turn_metric("shell_signal_fidelity", default=2)
        avg_npc_agency_reversal = _avg_turn_metric("npc_agency_reversal", default=2)

        triggered_count = 0
        foreshadow_count = 0
        detonate_count = 0
        control_attempts = 0
        control_success = 0
        consequence_turns = 0
        scene_question_resolved_turns = 0
        scene_question_tracked_turns = 0
        callback_due_turns = 0
        callback_trigger_turns = 0
        triggered_kind_counter: Counter[str] = Counter()
        for row in turn_logs:
            tags = [str(tag) for tag in list(row.get("consequence_tags") or []) if isinstance(tag, str)]
            tag_set = set(tags)
            if any(":triggered" in tag for tag in tag_set):
                triggered_count += 1
            if any(":foreshadowed" in tag for tag in tag_set):
                foreshadow_count += 1
            if any(":detonate" in tag for tag in tag_set):
                detonate_count += 1
            for tag in tag_set:
                if tag.startswith("latent:") and tag.endswith(":triggered"):
                    pieces = tag.split(":")
                    if len(pieces) >= 3:
                        triggered_kind_counter.update([pieces[1]])
            state_feedback = dict(row.get("state_feedback") or {})
            if list(state_feedback.get("last_turn_consequences") or []):
                consequence_turns += 1
            resolution = dict(row.get("resolution") or {})
            story_debug = dict(resolution.get("story_debug") or row.get("story_debug") or {})
            scene_question = dict(story_debug.get("scene_question_state") or {})
            if scene_question:
                scene_question_tracked_turns += 1
                if str(scene_question.get("status") or "") == "resolved":
                    scene_question_resolved_turns += 1
            callback_status = dict(story_debug.get("callback_status") or {})
            if callback_status:
                if int(callback_status.get("matured_count", 0) or 0) > 0:
                    callback_due_turns += 1
                if int(callback_status.get("consumed_count", 0) or 0) > 0:
                    callback_trigger_turns += 1
            control_resolution = dict(state_feedback.get("last_turn_control_resolution") or {})
            action_type = str(control_resolution.get("action_type") or "none")
            if action_type != "none":
                control_attempts += 1
                if bool(control_resolution.get("applied")):
                    control_success += 1

        trigger_kind_diversity = len(triggered_kind_counter)
        control_success_ratio = (control_success / control_attempts) if control_attempts > 0 else 0.0
        consequence_coverage_ratio = consequence_turns / turn_count

        strategic_tension_curve = _clamp_score(
            round(
                0.5 * avg_pressure_exchange
                + 0.3 * avg_consequence_impact
                + 0.2 * min(5, 1 + triggered_count)
                + (1 if foreshadow_count > 0 and triggered_count > 0 else 0)
            )
        )
        if turn_count >= 6 and triggered_count == 0:
            strategic_tension_curve = max(1, strategic_tension_curve - 1)

        consequence_legibility = _clamp_score(
            round(
                0.45 * avg_consequence_impact
                + 0.3 * avg_foreshadow_clarity
                + 0.25 * avg_intent_binding
                + (1 if consequence_coverage_ratio >= 0.6 else 0)
            )
        )

        payoff_realization = _clamp_score(
            round(
                avg_trigger_conversion
                + (1 if triggered_count + detonate_count >= 2 else 0)
                + (1 if ending_reached else 0)
                + min(1, ending_strength)
                - (1 if _safe_int(flag_counts.get("爆点没落地")) > max(1, turn_count // 3) else 0)
            )
        )

        npc_interest_divergence = _clamp_score(
            round(
                0.45 * avg_intent_binding
                + 0.3 * avg_npc_agency_reversal
                + 0.25 * min(5, 1 + unique_targets)
            )
        )
        if unique_targets <= 1 and avg_intent_binding <= 3:
            npc_interest_divergence = max(1, npc_interest_divergence - 1)

        if control_attempts == 0:
            control_tradeoff_quality = _clamp_score(round((avg_control_effectiveness + avg_pressure_exchange) / 2))
        else:
            control_tradeoff_quality = _clamp_score(
                round(
                    0.6 * avg_control_effectiveness
                    + 0.2 * avg_pressure_exchange
                    + 0.2 * (1 + 4 * control_success_ratio)
                )
            )

        shell_system_activation = _clamp_score(
            round(
                0.6 * avg_shell_fidelity
                + 0.2 * min(5, 1 + trigger_kind_diversity)
                + 0.2 * min(5, 1 + triggered_count)
            )
        )
        if key_segment_anchor_hit_rate >= 0.85:
            shell_system_activation = min(5, shell_system_activation + 1)
        elif key_segment_anchor_hit_rate < 0.5:
            shell_system_activation = max(1, shell_system_activation - 1)

        ending_cost_integrity = _clamp_score(
            round(
                2
                + (1 if ending_reached else 0)
                + min(2, ending_strength)
                + (1 if avg_consequence_impact >= 4 and payoff_realization >= 4 else 0)
                - (1 if ending_reached and avg_trigger_conversion <= 2 else 0)
            )
        )

        lane_dominance = max((_safe_int(count) for count in lane_counts.values()), default=0)
        replay_variance = _clamp_score(
            round(
                1
                + min(2, unique_lanes)
                + (1 if unique_targets >= 2 else 0)
                + (1 if trigger_kind_diversity >= 2 else 0)
                + (1 if control_attempts >= 2 else 0)
            )
        )
        if turn_count >= 6 and lane_dominance >= max(4, int(turn_count * 0.8)):
            replay_variance = max(1, replay_variance - 1)

        top_issues: list[str] = []
        if payoff_realization <= 2:
            top_issues.append("爆点没落地，触发链没有形成持续回咬。")
        if npc_interest_divergence <= 3:
            top_issues.append("角色反应太泛，利益分化不够清楚。")
        if control_tradeoff_quality <= 2:
            top_issues.append("控雷失效，压转拆没有稳定产生代价交换。")
        if shell_system_activation <= 3:
            top_issues.append("壳子系统未激活，场域信号不足。")
        if strategic_tension_curve <= 3:
            top_issues.append("发酵停滞，中段升温不连续。")
        top_issues = top_issues[:5]

        top_strengths: list[str] = []
        if strategic_tension_curve >= 4:
            top_strengths.append("张力曲线连续，局势有明显升温与落锤。")
        if npc_interest_divergence >= 4:
            top_strengths.append("NPC 利益反应有分化，不再只做同质围观。")
        if control_tradeoff_quality >= 4:
            top_strengths.append("控雷动作有效，玩家能主动管理风险。")
        if shell_system_activation >= 4:
            top_strengths.append("壳子机制被激活，场域反馈可感。")
        if payoff_realization >= 4:
            top_strengths.append("关键爆点兑现，后果链可追踪。")
        if not top_strengths:
            top_strengths.append("play 信号链路可读，评估可稳定复现。")
        top_strengths = top_strengths[:5]

        scored_turns: list[tuple[int, int]] = []
        for row in turn_logs:
            turn_play_eval = row.get("turn_play_eval")
            if not isinstance(turn_play_eval, dict):
                continue
            scores = dict(turn_play_eval.get("scores") or {})
            if not scores:
                continue
            score_sum = sum(
                _score_1_to_5(
                    scores.get(metric),
                    default=3,
                )
                for metric in (
                    "consequence_impact",
                    "intent_binding",
                    "pressure_exchange",
                    "control_effectiveness",
                    "trigger_conversion",
                    "foreshadow_clarity",
                    "shell_signal_fidelity",
                    "npc_agency_reversal",
                )
            )
            scored_turns.append((_safe_int(row.get("turn_index"), 1), score_sum))
        best_turn = max(scored_turns, key=lambda item: item[1])[0] if scored_turns else None
        worst_turn = min(scored_turns, key=lambda item: item[1])[0] if scored_turns else None

        best_moment = (
            f"第{best_turn}回合完成了风险转化，局势从前兆进入可见后果。"
            if best_turn is not None
            else "关键回合完成了有效的风险转化。"
        )
        worst_moment = (
            f"第{worst_turn}回合交换强度不足，发酵信号没有继续抬升。"
            if worst_turn is not None
            else "中段存在交换强度不足的问题。"
        )
        one_sentence_verdict = (
            f"本局张力曲线 {strategic_tension_curve}/5，爆点兑现 {payoff_realization}/5，"
            f"控雷质量 {control_tradeoff_quality}/5。"
        )[:240]
        scene_question_resolution_rate = (
            round(scene_question_resolved_turns / scene_question_tracked_turns, 4)
            if scene_question_tracked_turns > 0
            else 0.0
        )
        callback_payoff_hit_rate = (
            round(callback_trigger_turns / callback_due_turns, 4)
            if callback_due_turns > 0
            else 0.0
        )

        return SessionPlayEvalReport(
            case_id=case_id,
            persona_id=persona_id,
            play_eval_status="completed",
            scores=SessionPlayEvalScores(
                strategic_tension_curve=strategic_tension_curve,
                consequence_legibility=consequence_legibility,
                payoff_realization=payoff_realization,
                npc_interest_divergence=npc_interest_divergence,
                control_tradeoff_quality=control_tradeoff_quality,
                shell_system_activation=shell_system_activation,
                ending_cost_integrity=ending_cost_integrity,
                replay_variance=replay_variance,
            ),
            best_moment=best_moment,
            worst_moment=worst_moment,
            one_sentence_verdict=one_sentence_verdict,
            top_issues=top_issues,
            top_strengths=top_strengths,
            extended_metrics={
                "scene_question_resolution_rate": scene_question_resolution_rate,
                "callback_payoff_hit_rate": callback_payoff_hit_rate,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return SessionPlayEvalReport(
            case_id=case_id,
            persona_id=persona_id,
            play_eval_status="failed",
            play_eval_error=str(exc)[:240],
        )
