from app.modules.story.playability import analyze_story_playability


def _fun_pack() -> dict:
    return {
        "story_id": "playability_fun_story",
        "version": 1,
        "title": "Playability Fun Story",
        "start_node_id": "n_start",
        "nodes": [
            {
                "node_id": "n_start",
                "scene_brief": "Start",
                "is_end": False,
                "choices": [
                    {
                        "choice_id": "c_start_push",
                        "display_text": "Push hard",
                        "action": {"action_id": "study", "params": {}},
                        "next_node_id": "n_end",
                    },
                    {
                        "choice_id": "c_start_alt",
                        "display_text": "Alternative route",
                        "action": {"action_id": "study", "params": {}},
                        "next_node_id": "n_end",
                    },
                ],
            },
            {
                "node_id": "n_end",
                "scene_brief": "End",
                "is_end": True,
                "choices": [],
            },
        ],
        "endings": [
            {
                "ending_id": "ending_ok",
                "title": "OK",
                "priority": 100,
                "outcome": "neutral",
                "trigger": {"node_id_is": "n_end"},
                "epilogue": "Done.",
            }
        ],
        "run_config": {"max_steps": 24, "max_days": 7},
    }


def test_fun_metrics_emit_choice_contrast_warning() -> None:
    pack = _fun_pack()
    report = analyze_story_playability(
        pack=pack,
        playability_policy={
            "rollout_runs_per_strategy": 5,
            "choice_contrast_warn_below": 0.95,
            "dominant_strategy_warn_above": 0.99,
            "recovery_window_warn_below": 0.0,
            "tension_loop_warn_below": 0.0,
            "ending_reach_rate_min": 0.4,
            "stuck_turn_rate_max": 0.5,
            "no_progress_rate_max": 0.9,
        },
    )
    warning_codes = {item.get("code") for item in (report.get("warnings") or [])}
    assert "PLAYABILITY_CHOICE_CONTRAST_LOW" in warning_codes
    metrics = report.get("metrics") or {}
    assert "choice_contrast_score" in metrics


def test_fun_metrics_block_when_dominant_route_locks_low_coverage() -> None:
    pack = _fun_pack()
    pack["nodes"][0]["choices"][1]["requires"] = {"min_money": 9999}
    report = analyze_story_playability(
        pack=pack,
        playability_policy={
            "rollout_runs_per_strategy": 5,
            "dominant_strategy_block_above": 0.80,
            "low_branch_with_dominant_block_below": 0.60,
            "ending_reach_rate_min": 0.4,
            "stuck_turn_rate_max": 0.5,
            "no_progress_rate_max": 0.9,
        },
    )
    codes = {item.get("code") for item in (report.get("blocking_errors") or [])}
    assert "PLAYABILITY_DOMINANT_ROUTE_LOCK" in codes
    metrics = report.get("metrics") or {}
    assert "dominant_strategy_rate" in metrics


def test_fun_metrics_block_when_recovery_window_too_low() -> None:
    pack = _fun_pack()
    # Remove all positive-energy options to keep recovery availability near zero.
    pack["nodes"][0]["choices"][0]["action"] = {"action_id": "study", "params": {}}
    pack["nodes"][0]["choices"][1]["action"] = {"action_id": "work", "params": {}}
    report = analyze_story_playability(
        pack=pack,
        playability_policy={
            "rollout_runs_per_strategy": 5,
            "recovery_window_block_below": 0.30,
            "ending_reach_rate_min": 0.4,
            "stuck_turn_rate_max": 0.5,
            "no_progress_rate_max": 0.9,
        },
    )
    codes = {item.get("code") for item in (report.get("blocking_errors") or [])}
    assert "PLAYABILITY_RECOVERY_WINDOW_TOO_LOW" in codes
    metrics = report.get("metrics") or {}
    assert "recovery_window_rate" in metrics
