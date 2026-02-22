from app.modules.story.playability import analyze_story_playability


def _base_pack() -> dict:
    return {
        "story_id": "playability_gate_story",
        "version": 1,
        "title": "Playability Gate Story",
        "start_node_id": "n_start",
        "nodes": [
            {
                "node_id": "n_start",
                "scene_brief": "Start",
                "is_end": False,
                "choices": [
                    {
                        "choice_id": "c_start_1",
                        "display_text": "Study",
                        "action": {"action_id": "study", "params": {}},
                        "next_node_id": "n_end",
                    },
                    {
                        "choice_id": "c_start_2",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
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


def test_playability_gate_blocks_dangling_and_unreachable_paths() -> None:
    pack = _base_pack()
    pack["nodes"][0]["choices"][0]["next_node_id"] = "n_missing"
    pack["nodes"].append(
        {
            "node_id": "n_orphan",
            "scene_brief": "Orphan",
            "is_end": False,
            "choices": [
                {
                    "choice_id": "c_orphan_1",
                    "display_text": "Loop",
                    "action": {"action_id": "study", "params": {}},
                    "next_node_id": "n_orphan",
                },
                {
                    "choice_id": "c_orphan_2",
                    "display_text": "Loop2",
                    "action": {"action_id": "work", "params": {}},
                    "next_node_id": "n_orphan",
                },
            ],
        }
    )

    report = analyze_story_playability(pack=pack, playability_policy={"rollout_runs_per_strategy": 5})
    assert report["pass"] is False
    codes = {item.get("code") for item in (report.get("blocking_errors") or [])}
    assert "PLAYABILITY_DANGLING_NEXT_SCENE" in codes
    assert "PLAYABILITY_UNREACHABLE_SCENES" in codes


def test_playability_gate_blocks_impossible_requirement() -> None:
    pack = _base_pack()
    pack["nodes"][0]["choices"][0]["requires"] = {"min_energy": 999}
    report = analyze_story_playability(pack=pack, playability_policy={"rollout_runs_per_strategy": 5})
    assert report["pass"] is False
    codes = {item.get("code") for item in (report.get("blocking_errors") or [])}
    assert "PLAYABILITY_IMPOSSIBLE_REQUIREMENT" in codes


def test_playability_gate_warns_low_branch_coverage_without_blocking() -> None:
    pack = _base_pack()
    pack["nodes"][0]["choices"][1]["requires"] = {"min_money": 60}
    report = analyze_story_playability(
        pack=pack,
        playability_policy={
            "rollout_runs_per_strategy": 5,
            "branch_coverage_warn_below": 0.95,
            "ending_reach_rate_min": 0.4,
            "stuck_turn_rate_max": 0.4,
            "no_progress_rate_max": 0.8,
        },
    )
    assert isinstance(report.get("metrics"), dict)
    warning_codes = {item.get("code") for item in (report.get("warnings") or [])}
    assert "PLAYABILITY_BRANCH_COVERAGE_LOW" in warning_codes
