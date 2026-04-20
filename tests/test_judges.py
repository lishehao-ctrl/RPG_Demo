from __future__ import annotations

from tools.urban_author_play_benchmarks import play_eval as play_eval_tools


def test_play_eval_turn_metrics_from_latent_and_control_signals() -> None:
    record = play_eval_tools.evaluate_turn(
        {
            "case_id": "case_a",
            "persona_id": "baodian",
            "turn_index": 3,
            "story_shell_id": "entertainment_scandal",
            "segment_role": "reveal",
            "selected_suggestion": {
                "lane_id": "burst",
                "move_family": "public_reveal",
                "target_id": "lin",
            },
            "narration": "这拍镜头已经咬住她，热搜的口子被当场撕开。",
            "feedback": {
                "last_turn_global_deltas": {"scene_heat": 2, "public_image": -2, "secret_exposure": 2},
                "last_turn_relationship_deltas": {"lin": {"trust": -2, "tension": 2}},
                "last_turn_reaction_causes": {"lin": ["intent_loss_triggered", "opportunity_window"]},
                "last_turn_consequences": ["镜头已经把这一拍锁死。"],
                "consequence_tags": [
                    "latent:public_wave:foreshadowed",
                    "latent:public_wave:detonate",
                    "latent:public_wave:triggered",
                    "latent:npc_action:triggered",
                ],
                "control_resolution": {
                    "action_type": "detonate",
                    "applied": True,
                    "summary": "你提前引爆，代价当场兑现。",
                },
            },
        }
    )

    assert record.play_eval_status == "completed"
    assert record.scores is not None
    assert record.scores.consequence_impact >= 4
    assert record.scores.control_effectiveness >= 4
    assert record.scores.trigger_conversion >= 4
    assert record.scores.npc_agency_reversal >= 4
    assert record.key_segment_shell_anchor_hit is True


def test_play_eval_session_metrics_from_turn_trajectory() -> None:
    report = play_eval_tools.evaluate_session(
        {
            "case_id": "case_a",
            "persona_id": "baodian",
            "run_summary": {
                "turn_count": 6,
                "ending_reached": True,
                "ending_strength": 2,
                "lane_counts": {"relationship": 2, "side": 2, "burst": 2},
            },
            "turn_play_eval_summary": {
                "avg_scores": {
                    "consequence_impact": 4,
                    "intent_binding": 4,
                    "pressure_exchange": 4,
                    "control_effectiveness": 4,
                    "trigger_conversion": 4,
                    "foreshadow_clarity": 4,
                    "shell_signal_fidelity": 4,
                    "npc_agency_reversal": 4,
                },
                "flag_counts": {},
            },
            "turn_logs": [
                {
                    "turn_index": 1,
                    "selected_target_id": "a",
                    "consequence_tags": ["latent:relationship_debt:foreshadowed"],
                    "state_feedback": {
                        "last_turn_consequences": ["台下记住了这一拍。"],
                        "last_turn_control_resolution": {"action_type": "press", "applied": True},
                    },
                    "turn_play_eval": {
                        "scores": {
                            "consequence_impact": 4,
                            "intent_binding": 4,
                            "pressure_exchange": 4,
                            "control_effectiveness": 4,
                            "trigger_conversion": 3,
                            "foreshadow_clarity": 4,
                            "shell_signal_fidelity": 4,
                            "npc_agency_reversal": 3,
                        }
                    },
                },
                {
                    "turn_index": 2,
                    "selected_target_id": "b",
                    "consequence_tags": ["latent:public_wave:triggered", "latent:public_wave:detonate"],
                    "state_feedback": {
                        "last_turn_consequences": ["外面风向开始反咬。"],
                        "last_turn_control_resolution": {"action_type": "detonate", "applied": True},
                    },
                    "turn_play_eval": {
                        "scores": {
                            "consequence_impact": 5,
                            "intent_binding": 4,
                            "pressure_exchange": 5,
                            "control_effectiveness": 5,
                            "trigger_conversion": 5,
                            "foreshadow_clarity": 4,
                            "shell_signal_fidelity": 4,
                            "npc_agency_reversal": 4,
                        }
                    },
                },
            ],
        }
    )

    assert report.play_eval_status == "completed"
    assert report.scores is not None
    assert report.scores.strategic_tension_curve >= 4
    assert report.scores.payoff_realization >= 4
    assert report.scores.control_tradeoff_quality >= 4


def test_play_eval_flags_are_mechanism_based_not_text_style() -> None:
    record = play_eval_tools.evaluate_turn(
        {
            "case_id": "case_b",
            "persona_id": "wenjian",
            "turn_index": 2,
            "story_shell_id": "campus_romance",
            "segment_role": "reveal",
            "selected_suggestion": {
                "lane_id": "relationship",
                "move_family": "comfort",
                "target_id": "",
            },
            "feedback": {
                "last_turn_global_deltas": {},
                "last_turn_relationship_deltas": {},
                "last_turn_reaction_causes": {},
                "last_turn_consequences": ["场面暂时稳住。"],
                "consequence_tags": ["latent:relationship_debt:foreshadowed"],
                "control_resolution": {"action_type": "redirect", "applied": False},
            },
        }
    )

    assert record.play_eval_status == "completed"
    assert "模板味" not in record.flags
    assert "不够像中文" not in record.flags
    assert "文风太客观" not in record.flags
    assert any(flag in record.flags for flag in ("控雷失效", "爆点没落地", "发酵停滞", "角色反应太泛"))


def test_no_network_or_gateway_dependency_in_play_eval_path() -> None:
    record = play_eval_tools.evaluate_turn(
        {
            "case_id": "case_c",
            "persona_id": "qinggan",
            "turn_index": 1,
            "story_shell_id": "office_power",
            "segment_role": "opening",
            "selected_suggestion": {"lane_id": "relationship", "move_family": "comfort", "target_id": "x"},
            "feedback": {},
        }
    )
    report = play_eval_tools.evaluate_session(
        {
            "case_id": "case_c",
            "persona_id": "qinggan",
            "run_summary": {"turn_count": 1, "lane_counts": {"relationship": 1}},
            "turn_logs": [],
        }
    )

    assert record.play_eval_status == "completed"
    assert report.play_eval_status == "completed"


def test_play_eval_session_boosts_shell_activation_with_high_key_segment_anchor_hit_rate() -> None:
    payload = {
        "case_id": "case_shell_anchor",
        "persona_id": "baodian",
        "run_summary": {
            "turn_count": 4,
            "ending_reached": True,
            "ending_strength": 2,
            "lane_counts": {"burst": 2, "side": 1, "relationship": 1},
        },
        "turn_play_eval_summary": {
            "avg_scores": {
                "consequence_impact": 4,
                "intent_binding": 4,
                "pressure_exchange": 4,
                "control_effectiveness": 4,
                "trigger_conversion": 4,
                "foreshadow_clarity": 4,
                "shell_signal_fidelity": 3,
                "npc_agency_reversal": 4,
            },
            "flag_counts": {},
        },
        "turn_logs": [],
    }
    report_without_hit = play_eval_tools.evaluate_session(payload)
    payload_with_hit = {
        **payload,
        "turn_play_eval_summary": {
            **payload["turn_play_eval_summary"],
            "key_segment_shell_anchor_hit_rate": 1.0,
        },
    }
    report_with_hit = play_eval_tools.evaluate_session(payload_with_hit)

    assert report_without_hit.play_eval_status == "completed"
    assert report_with_hit.play_eval_status == "completed"
    assert report_without_hit.scores is not None
    assert report_with_hit.scores is not None
    assert report_with_hit.scores.shell_system_activation >= report_without_hit.scores.shell_system_activation

