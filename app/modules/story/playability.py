from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.narrative.state_engine import normalize_state

_ACTION_BASE_DELTA = {
    "study": {"energy": -10, "knowledge": 2},
    "work": {"energy": -15, "money": 20},
    "rest": {"energy": 20},
    "date": {"energy": -12, "money": -5, "affection": 3},
    "gift": {"money": -15, "affection": 4},
}
_NUMERIC_KEYS = ("energy", "money", "knowledge", "affection")
_STATE_MAX = {"energy": 100, "money": 999999, "knowledge": 999, "affection": 100, "day": 999}


def _diag(
    *,
    code: str,
    path: str | None,
    message: str,
    suggestion: str | None = None,
) -> dict[str, str | None]:
    return {
        "code": code,
        "path": path,
        "message": message,
        "suggestion": suggestion,
    }


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return int(default)


def _normalize_policy(policy: dict | None, run_config: dict | None) -> dict[str, Any]:
    raw = policy if isinstance(policy, dict) else {}
    cfg = run_config if isinstance(run_config, dict) else {}
    run_max_steps = _safe_int(cfg.get("max_steps"), 24)
    if run_max_steps < 1:
        run_max_steps = 24
    step_cap = _safe_int(raw.get("rollout_step_cap"), run_max_steps)
    step_cap = max(8, min(step_cap, 120))
    return {
        "ending_reach_rate_min": max(0.20, min(float(raw.get("ending_reach_rate_min", 0.60)), 0.95)),
        "stuck_turn_rate_max": max(0.0, min(float(raw.get("stuck_turn_rate_max", 0.05)), 0.50)),
        "no_progress_rate_max": max(0.0, min(float(raw.get("no_progress_rate_max", 0.25)), 0.80)),
        "branch_coverage_warn_below": max(0.0, min(float(raw.get("branch_coverage_warn_below", 0.30)), 0.90)),
        "choice_contrast_warn_below": max(0.0, min(float(raw.get("choice_contrast_warn_below", 0.45)), 0.95)),
        "dominant_strategy_warn_above": max(0.20, min(float(raw.get("dominant_strategy_warn_above", 0.75)), 0.99)),
        "recovery_window_warn_below": max(0.0, min(float(raw.get("recovery_window_warn_below", 0.55)), 0.95)),
        "tension_loop_warn_below": max(0.0, min(float(raw.get("tension_loop_warn_below", 0.50)), 0.95)),
        "dominant_strategy_block_above": max(0.30, min(float(raw.get("dominant_strategy_block_above", 0.90)), 0.995)),
        "low_branch_with_dominant_block_below": max(
            0.0,
            min(float(raw.get("low_branch_with_dominant_block_below", 0.20)), 0.90),
        ),
        "recovery_window_block_below": max(0.0, min(float(raw.get("recovery_window_block_below", 0.25)), 0.90)),
        "rollout_strategies": max(1, min(_safe_int(raw.get("rollout_strategies"), 3), 5)),
        "rollout_runs_per_strategy": max(1, min(_safe_int(raw.get("rollout_runs_per_strategy"), 80), 200)),
        "rollout_step_cap": step_cap,
        "max_abs_single_step_delta": max(20, min(_safe_int(raw.get("max_abs_single_step_delta"), 120), 300)),
    }


def _node_map(pack: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for node in (pack.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id") or "").strip()
        if not node_id:
            continue
        out[node_id] = node
    return out


def _choice_list(node: dict) -> list[dict]:
    out: list[dict] = []
    for choice in (node.get("choices") or []):
        if isinstance(choice, dict):
            out.append(choice)
    return out


def _action_effect(choice: dict) -> dict[str, int]:
    action = choice.get("action") if isinstance(choice.get("action"), dict) else {}
    action_id = str(action.get("action_id") or "").strip()
    effect: dict[str, int] = {k: int(v) for k, v in (_ACTION_BASE_DELTA.get(action_id) or {}).items()}
    for key, raw in ((choice.get("effects") or {}) if isinstance(choice.get("effects"), dict) else {}).items():
        if key not in _NUMERIC_KEYS:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        effect[key] = int(effect.get(key, 0) + int(raw))
    return effect


def _requires_blocking(requires: dict, *, run_max_days: int) -> str | None:
    limits = {
        "min_energy": 100,
        "min_money": 999999,
        "min_affection": 100,
        "day_at_least": run_max_days,
    }
    for key, max_allowed in limits.items():
        value = requires.get(key)
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if int(value) > int(max_allowed):
            return key
    return None


def _available(choice: dict, state: dict) -> bool:
    requires = choice.get("requires") if isinstance(choice.get("requires"), dict) else {}
    if not requires:
        return True
    if "min_energy" in requires and int(state.get("energy", 0)) < int(requires.get("min_energy", 0)):
        return False
    if "min_money" in requires and int(state.get("money", 0)) < int(requires.get("min_money", 0)):
        return False
    if "min_affection" in requires and int(state.get("affection", 0)) < int(requires.get("min_affection", 0)):
        return False
    if "day_at_least" in requires and int(state.get("day", 1)) < int(requires.get("day_at_least", 1)):
        return False
    slot_in = requires.get("slot_in")
    if isinstance(slot_in, list) and slot_in and str(state.get("slot")) not in {str(s) for s in slot_in}:
        return False
    return True


def _score_choice(choice: dict, *, strategy: str, run_offset: int) -> tuple[float, float]:
    effect = _action_effect(choice)
    energy = float(effect.get("energy", 0))
    money = float(effect.get("money", 0))
    knowledge = float(effect.get("knowledge", 0))
    affection = float(effect.get("affection", 0))
    index_bias = float(run_offset % 3) * 0.01
    if strategy == "cautious":
        primary = energy + 0.5 * knowledge
    elif strategy == "greedy":
        primary = money + 0.7 * knowledge - 0.2 * max(-energy, 0)
    else:
        primary = affection + 0.2 * money + 0.1 * knowledge
    return (primary + index_bias, energy)


def _apply_choice(state: dict, choice: dict) -> dict:
    out = dict(state or {})
    for key, delta in _action_effect(choice).items():
        if key not in _NUMERIC_KEYS:
            continue
        out[key] = int(out.get(key, 0)) + int(delta)
    return normalize_state(out)


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _choice_contrast_score_for_node(node: dict) -> float:
    choices = _choice_list(node)
    if len(choices) < 2:
        return 0.0
    pair_scores: list[float] = []
    for left_idx in range(len(choices)):
        for right_idx in range(left_idx + 1, len(choices)):
            left = choices[left_idx]
            right = choices[right_idx]
            score = 0.0
            left_action = str(((left.get("action") or {}).get("action_id")) if isinstance(left.get("action"), dict) else "")
            right_action = str(((right.get("action") or {}).get("action_id")) if isinstance(right.get("action"), dict) else "")
            if left_action != right_action:
                score += 0.40
            left_next = str(left.get("next_node_id") or "")
            right_next = str(right.get("next_node_id") or "")
            if left_next and right_next and left_next != right_next:
                score += 0.25
            left_effect = _action_effect(left)
            right_effect = _action_effect(right)
            effect_distance = sum(abs(int(left_effect.get(key, 0)) - int(right_effect.get(key, 0))) for key in _NUMERIC_KEYS)
            score += min(effect_distance / 60.0, 0.35)
            pair_scores.append(_clamp01(score))
    if not pair_scores:
        return 0.0
    return _clamp01(sum(pair_scores) / len(pair_scores))


@dataclass(slots=True)
class _RunResult:
    reached_ending: bool
    stuck: bool
    no_progress: bool
    turns: int
    visited_choice_ids: set[str]
    selected_choice_ids: list[str]
    recovery_offered_turns: int
    tension_cycles: int


def _simulate_single_run(
    *,
    node_map: dict[str, dict],
    start_node_id: str,
    step_cap: int,
    strategy: str,
    run_offset: int,
) -> _RunResult:
    current_node_id = start_node_id
    state = normalize_state({})
    turns = 0
    progress_turns = 0
    visited_choice_ids: set[str] = set()
    selected_choice_ids: list[str] = []
    recovery_offered_turns = 0
    tension_cycles = 0
    tension_phase = 0

    for _ in range(step_cap):
        node = node_map.get(current_node_id)
        if not node:
            return _RunResult(
                False,
                True,
                progress_turns == 0,
                turns,
                visited_choice_ids,
                selected_choice_ids,
                recovery_offered_turns,
                tension_cycles,
            )
        if bool(node.get("is_end")):
            return _RunResult(
                True,
                False,
                progress_turns == 0,
                turns,
                visited_choice_ids,
                selected_choice_ids,
                recovery_offered_turns,
                tension_cycles,
            )

        available = [choice for choice in _choice_list(node) if _available(choice, state)]
        if not available:
            return _RunResult(
                False,
                True,
                progress_turns == 0,
                turns,
                visited_choice_ids,
                selected_choice_ids,
                recovery_offered_turns,
                tension_cycles,
            )

        if any(int(_action_effect(item).get("energy", 0)) > 0 for item in available):
            recovery_offered_turns += 1

        ranked = sorted(
            enumerate(available),
            key=lambda item: _score_choice(item[1], strategy=strategy, run_offset=run_offset + item[0]),
            reverse=True,
        )
        selected = available[ranked[0][0]]
        before = dict(state)
        state = _apply_choice(state, selected)
        turns += 1
        if any(int(state.get(k, 0)) != int(before.get(k, 0)) for k in _NUMERIC_KEYS):
            progress_turns += 1

        choice_id = str(selected.get("choice_id") or "").strip()
        if choice_id:
            visited_choice_ids.add(choice_id)
            selected_choice_ids.append(choice_id)

        selected_effect = _action_effect(selected)
        energy_delta = int(selected_effect.get("energy", 0))
        has_forward_progress = bool(
            int(selected_effect.get("knowledge", 0)) > 0
            or int(selected_effect.get("money", 0)) > 0
            or int(selected_effect.get("affection", 0)) > 0
        )
        if tension_phase == 0 and energy_delta <= -10:
            tension_phase = 1
        elif tension_phase == 1 and energy_delta >= 8:
            tension_phase = 2
        elif tension_phase == 2 and has_forward_progress:
            tension_cycles += 1
            tension_phase = 0
        elif tension_phase == 2 and energy_delta <= -10:
            # Restart a new pressure cycle if the run jumps back to pressure.
            tension_phase = 1

        next_node_id = str(selected.get("next_node_id") or current_node_id).strip() or current_node_id
        current_node_id = next_node_id

    return _RunResult(
        False,
        False,
        progress_turns <= 1,
        turns,
        visited_choice_ids,
        selected_choice_ids,
        recovery_offered_turns,
        tension_cycles,
    )


def _graph_reachability(node_map: dict[str, dict], start_node_id: str) -> tuple[set[str], dict[str, set[str]]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_map}
    for node_id, node in node_map.items():
        for choice in _choice_list(node):
            next_node_id = str(choice.get("next_node_id") or "").strip()
            if next_node_id:
                adjacency[node_id].add(next_node_id)

    visited: set[str] = set()
    stack = [start_node_id]
    while stack:
        node_id = stack.pop()
        if node_id in visited or node_id not in node_map:
            continue
        visited.add(node_id)
        for next_node_id in adjacency.get(node_id, set()):
            if next_node_id not in visited:
                stack.append(next_node_id)
    return visited, adjacency


def _can_reach_any_ending(node_map: dict[str, dict], adjacency: dict[str, set[str]]) -> set[str]:
    ending_nodes = {node_id for node_id, node in node_map.items() if bool(node.get("is_end"))}
    if not ending_nodes:
        return set()
    reverse: dict[str, set[str]] = {node_id: set() for node_id in node_map}
    for node_id, next_nodes in adjacency.items():
        for next_node_id in next_nodes:
            if next_node_id in reverse:
                reverse[next_node_id].add(node_id)
    can_reach = set(ending_nodes)
    stack = list(ending_nodes)
    while stack:
        node_id = stack.pop()
        for prev in reverse.get(node_id, set()):
            if prev not in can_reach:
                can_reach.add(prev)
                stack.append(prev)
    return can_reach


def analyze_story_playability(
    *,
    pack: dict | None,
    playability_policy: dict | None,
) -> dict:
    blocking_errors: list[dict[str, str | None]] = []
    warnings: list[dict[str, str | None]] = []
    metrics = {
        "ending_reach_rate": 0.0,
        "stuck_turn_rate": 0.0,
        "no_progress_rate": 0.0,
        "branch_coverage": 0.0,
        "choice_contrast_score": 0.0,
        "dominant_strategy_rate": 0.0,
        "recovery_window_rate": 0.0,
        "tension_loop_score": 0.0,
    }
    if not isinstance(pack, dict):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_PACK_MISSING",
                path=None,
                message="Compiled pack is missing; playability analysis cannot run.",
                suggestion="Fix compile diagnostics first.",
            )
        )
        return {"pass": False, "blocking_errors": blocking_errors, "warnings": warnings, "metrics": metrics}

    node_map = _node_map(pack)
    start_node_id = str(pack.get("start_node_id") or "").strip()
    run_config = pack.get("run_config") if isinstance(pack.get("run_config"), dict) else {}
    policy = _normalize_policy(playability_policy, run_config)

    if not start_node_id or start_node_id not in node_map:
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_START_SCENE_MISSING",
                path="flow.start_scene_key",
                message="Start scene is missing or unresolved.",
                suggestion="Set a valid start scene and recompile.",
            )
        )
    if not (pack.get("endings") or []):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_ENDINGS_MISSING",
                path="ending.ending_rules",
                message="No ending rules found.",
                suggestion="Add at least one ending rule with a reachable trigger.",
            )
        )

    run_max_days = _safe_int(run_config.get("max_days"), 7)
    if run_max_days < 1:
        run_max_days = 7

    has_positive_energy_route = False
    total_choice_count = 0
    non_end_scene_contrast_scores: list[float] = []
    for node_id, node in node_map.items():
        choices = _choice_list(node)
        total_choice_count += len(choices)
        is_end = bool(node.get("is_end"))
        if not is_end and choices:
            non_end_scene_contrast_scores.append(_choice_contrast_score_for_node(node))
        if is_end and len(choices) > 4:
            blocking_errors.append(
                _diag(
                    code="PLAYABILITY_END_SCENE_OPTION_OVERFLOW",
                    path=f"nodes[{node_id}].choices",
                    message="End scenes may define at most 4 options.",
                    suggestion="Trim end-scene options to keep decision load reasonable.",
                )
            )
        if not is_end and not (2 <= len(choices) <= 4):
            blocking_errors.append(
                _diag(
                    code="PLAYABILITY_SCENE_OPTION_COUNT",
                    path=f"nodes[{node_id}].choices",
                    message="Non-end scenes must expose 2-4 options.",
                    suggestion="Add or remove options in this scene.",
                )
            )
        for choice in choices:
            next_node_id = str(choice.get("next_node_id") or "").strip()
            if next_node_id and next_node_id not in node_map:
                blocking_errors.append(
                    _diag(
                        code="PLAYABILITY_DANGLING_NEXT_SCENE",
                        path=f"nodes[{node_id}].choices",
                        message=f"Choice points to missing scene '{next_node_id}'.",
                        suggestion="Repair go_to references in this scene.",
                    )
                )
            requires = choice.get("requires") if isinstance(choice.get("requires"), dict) else {}
            impossible_key = _requires_blocking(requires, run_max_days=run_max_days)
            if impossible_key:
                blocking_errors.append(
                    _diag(
                        code="PLAYABILITY_IMPOSSIBLE_REQUIREMENT",
                        path=f"nodes[{node_id}].choices",
                        message=f"Requirement '{impossible_key}' exceeds achievable bounds.",
                        suggestion="Lower requirement thresholds or add recovery routes.",
                    )
                )
            effect = _action_effect(choice)
            if int(effect.get("energy", 0)) > 0:
                has_positive_energy_route = True
            for key in _NUMERIC_KEYS:
                value = int(effect.get(key, 0))
                if abs(value) > int(policy["max_abs_single_step_delta"]):
                    blocking_errors.append(
                        _diag(
                            code="PLAYABILITY_DELTA_EXTREME",
                            path=f"nodes[{node_id}].choices",
                            message=f"Single-step {key} delta ({value}) exceeds safe threshold.",
                            suggestion="Reduce this effect magnitude to keep progression stable.",
                        )
                    )

    if not has_positive_energy_route:
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_NO_ENERGY_RECOVERY",
                path="flow.scenes.options",
                message="No reachable option restores energy.",
                suggestion="Add at least one rest/recovery path to avoid soft deadlocks.",
            )
        )

    visited_nodes, adjacency = _graph_reachability(node_map, start_node_id)
    if start_node_id and start_node_id in node_map:
        unreachable = [node_id for node_id in node_map if node_id not in visited_nodes]
        if unreachable:
            sample = ", ".join(unreachable[:3])
            blocking_errors.append(
                _diag(
                    code="PLAYABILITY_UNREACHABLE_SCENES",
                    path="flow.scenes",
                    message=f"{len(unreachable)} scene(s) are unreachable from start (e.g. {sample}).",
                    suggestion="Reconnect disconnected scenes from reachable flow.",
                )
            )

    can_reach_ending = _can_reach_any_ending(node_map, adjacency)
    if visited_nodes and not (visited_nodes & can_reach_ending):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_NO_ENDING_PATH",
                path="ending.ending_rules",
                message="No reachable path from start can reach an ending node.",
                suggestion="Link flow to at least one ending-capable scene.",
            )
        )
    else:
        dead_end_nodes = [
            node_id
            for node_id in visited_nodes
            if node_id not in can_reach_ending and not bool((node_map.get(node_id) or {}).get("is_end"))
        ]
        if dead_end_nodes:
            sample = ", ".join(sorted(dead_end_nodes)[:3])
            blocking_errors.append(
                _diag(
                    code="PLAYABILITY_DEAD_END_PATH",
                    path="flow.scenes",
                    message=f"Detected reachable dead-end scene(s) that cannot finish (e.g. {sample}).",
                    suggestion="Ensure each reachable branch can eventually reach an ending.",
                )
            )

    strategies = ["cautious", "greedy", "social"][: int(policy["rollout_strategies"])]
    total_runs = int(policy["rollout_runs_per_strategy"]) * len(strategies)
    total_turns = 0
    reached_runs = 0
    stuck_runs = 0
    no_progress_runs = 0
    visited_choices: set[str] = set()
    selected_choice_counter: dict[str, int] = {}
    recovery_offered_turns = 0
    runs_with_tension_cycle = 0
    if start_node_id in node_map and total_runs > 0:
        for strategy_index, strategy in enumerate(strategies):
            for run_index in range(int(policy["rollout_runs_per_strategy"])):
                result = _simulate_single_run(
                    node_map=node_map,
                    start_node_id=start_node_id,
                    step_cap=int(policy["rollout_step_cap"]),
                    strategy=strategy,
                    run_offset=(strategy_index * 997) + run_index,
                )
                total_turns += int(result.turns)
                if result.reached_ending:
                    reached_runs += 1
                if result.stuck:
                    stuck_runs += 1
                if result.no_progress:
                    no_progress_runs += 1
                visited_choices.update(result.visited_choice_ids)
                recovery_offered_turns += int(result.recovery_offered_turns)
                if int(result.tension_cycles) > 0:
                    runs_with_tension_cycle += 1
                for selected_choice_id in result.selected_choice_ids:
                    selected_choice_counter[selected_choice_id] = int(selected_choice_counter.get(selected_choice_id, 0)) + 1

    metrics["ending_reach_rate"] = (float(reached_runs) / float(total_runs)) if total_runs else 0.0
    metrics["stuck_turn_rate"] = (float(stuck_runs) / float(total_runs)) if total_runs else 0.0
    metrics["no_progress_rate"] = (float(no_progress_runs) / float(total_runs)) if total_runs else 0.0
    metrics["branch_coverage"] = (float(len(visited_choices)) / float(total_choice_count)) if total_choice_count else 0.0
    metrics["choice_contrast_score"] = (
        float(sum(non_end_scene_contrast_scores)) / float(len(non_end_scene_contrast_scores))
        if non_end_scene_contrast_scores
        else 0.0
    )
    dominant_picks = max(selected_choice_counter.values()) if selected_choice_counter else 0
    total_selected_picks = sum(selected_choice_counter.values())
    metrics["dominant_strategy_rate"] = (
        float(dominant_picks) / float(total_selected_picks)
        if total_selected_picks
        else 0.0
    )
    metrics["recovery_window_rate"] = (
        float(recovery_offered_turns) / float(total_turns)
        if total_turns
        else 0.0
    )
    metrics["tension_loop_score"] = (
        float(runs_with_tension_cycle) / float(total_runs)
        if total_runs
        else 0.0
    )

    for metric_key in (
        "choice_contrast_score",
        "dominant_strategy_rate",
        "recovery_window_rate",
        "tension_loop_score",
    ):
        metrics[metric_key] = _clamp01(float(metrics.get(metric_key) or 0.0))

    if metrics["ending_reach_rate"] < float(policy["ending_reach_rate_min"]):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_ENDING_REACH_RATE_LOW",
                path="flow",
                message=(
                    f"ending_reach_rate={metrics['ending_reach_rate']:.2f} below threshold "
                    f"{float(policy['ending_reach_rate_min']):.2f}."
                ),
                suggestion="Increase ending reachability with clearer route continuity and fewer hard blocks.",
            )
        )
    if metrics["stuck_turn_rate"] > float(policy["stuck_turn_rate_max"]):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_STUCK_RATE_HIGH",
                path="flow",
                message=(
                    f"stuck_turn_rate={metrics['stuck_turn_rate']:.2f} above threshold "
                    f"{float(policy['stuck_turn_rate_max']):.2f}."
                ),
                suggestion="Add recovery options and relax strict requirements on critical branches.",
            )
        )
    if metrics["no_progress_rate"] > float(policy["no_progress_rate_max"]):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_NO_PROGRESS_RATE_HIGH",
                path="consequence",
                message=(
                    f"no_progress_rate={metrics['no_progress_rate']:.2f} above threshold "
                    f"{float(policy['no_progress_rate_max']):.2f}."
                ),
                suggestion="Increase meaningful state changes in early and mid-path choices.",
            )
        )
    if (
        metrics["dominant_strategy_rate"] > float(policy["dominant_strategy_block_above"])
        and metrics["branch_coverage"] < float(policy["low_branch_with_dominant_block_below"])
    ):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_DOMINANT_ROUTE_LOCK",
                path="flow.scenes",
                message=(
                    f"dominant_strategy_rate={metrics['dominant_strategy_rate']:.2f} with "
                    f"branch_coverage={metrics['branch_coverage']:.2f} indicates route lock."
                ),
                suggestion="Increase branch contrast and reduce one-route dominance in early scenes.",
            )
        )
    if metrics["recovery_window_rate"] < float(policy["recovery_window_block_below"]):
        blocking_errors.append(
            _diag(
                code="PLAYABILITY_RECOVERY_WINDOW_TOO_LOW",
                path="flow.scenes.options",
                message=(
                    f"recovery_window_rate={metrics['recovery_window_rate']:.2f} below blocking threshold "
                    f"{float(policy['recovery_window_block_below']):.2f}."
                ),
                suggestion="Ensure most turns present at least one viable recovery option.",
            )
        )
    if metrics["branch_coverage"] < float(policy["branch_coverage_warn_below"]):
        warnings.append(
            _diag(
                code="PLAYABILITY_BRANCH_COVERAGE_LOW",
                path="flow.scenes",
                message=(
                    f"branch_coverage={metrics['branch_coverage']:.2f} below warning threshold "
                    f"{float(policy['branch_coverage_warn_below']):.2f}."
                ),
                suggestion="Differentiate option outcomes so multiple branches stay meaningful.",
            )
        )
    if metrics["choice_contrast_score"] < float(policy["choice_contrast_warn_below"]):
        warnings.append(
            _diag(
                code="PLAYABILITY_CHOICE_CONTRAST_LOW",
                path="flow.scenes.options",
                message=(
                    f"choice_contrast_score={metrics['choice_contrast_score']:.2f} below warning threshold "
                    f"{float(policy['choice_contrast_warn_below']):.2f}."
                ),
                suggestion="Increase option contrast through action type, route target, or effects.",
            )
        )
    if metrics["dominant_strategy_rate"] > float(policy["dominant_strategy_warn_above"]):
        warnings.append(
            _diag(
                code="PLAYABILITY_DOMINANT_STRATEGY_HIGH",
                path="flow.scenes",
                message=(
                    f"dominant_strategy_rate={metrics['dominant_strategy_rate']:.2f} above warning threshold "
                    f"{float(policy['dominant_strategy_warn_above']):.2f}."
                ),
                suggestion="Add competitive alternatives so one strategy is not always optimal.",
            )
        )
    if metrics["recovery_window_rate"] < float(policy["recovery_window_warn_below"]):
        warnings.append(
            _diag(
                code="PLAYABILITY_RECOVERY_WINDOW_LOW",
                path="flow.scenes.options",
                message=(
                    f"recovery_window_rate={metrics['recovery_window_rate']:.2f} below warning threshold "
                    f"{float(policy['recovery_window_warn_below']):.2f}."
                ),
                suggestion="Offer recovery options more consistently across scenes.",
            )
        )
    if metrics["tension_loop_score"] < float(policy["tension_loop_warn_below"]):
        warnings.append(
            _diag(
                code="PLAYABILITY_TENSION_LOOP_WEAK",
                path="consequence",
                message=(
                    f"tension_loop_score={metrics['tension_loop_score']:.2f} below warning threshold "
                    f"{float(policy['tension_loop_warn_below']):.2f}."
                ),
                suggestion="Design pressure -> recovery -> progress cycles in nearby scenes.",
            )
        )

    return {
        "pass": len(blocking_errors) == 0,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "metrics": metrics,
    }
