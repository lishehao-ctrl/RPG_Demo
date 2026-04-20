from __future__ import annotations

from random import Random

from rpg_backend.config import Settings
from tools.play_benchmarks import live_api_playtest
from tools.play_benchmarks.story_seed_factory import build_story_seed_batch


def test_story_seed_factory_returns_five_unique_bucketed_seeds() -> None:
    seeds = build_story_seed_batch(rng=Random(7))

    assert len(seeds) == 5
    assert len({item.seed for item in seeds}) == 5
    assert len({item.bucket_id for item in seeds}) == 5


def test_story_seed_factory_can_sample_three_unique_buckets() -> None:
    seeds = build_story_seed_batch(rng=Random(3), story_count=3)

    assert len(seeds) == 3
    assert len({item.bucket_id for item in seeds}) == 3
    assert len({item.seed for item in seeds}) == 3


def test_story_seed_factory_returns_ten_unique_bucketed_seeds_when_requested() -> None:
    seeds = build_story_seed_batch(rng=Random(17), story_count=10)

    assert len(seeds) == 10
    assert len({item.seed for item in seeds}) == 10
    assert {item.bucket_id for item in seeds} == {
        "legitimacy_warning",
        "ration_infrastructure",
        "blackout_panic",
        "harbor_quarantine",
        "archive_vote_record",
        "charter_oath_breach",
        "checkpoint_corridor_access",
        "customs_clearance_standoff",
        "shelter_capacity_surge",
        "testimony_release_timing",
    }


def test_story_seed_factory_supports_chinese_generation() -> None:
    seeds = build_story_seed_batch(rng=Random(19), story_count=2, language="zh")

    assert len(seeds) == 2
    assert any(any(ord(char) > 127 for char in seed.seed) for seed in seeds)


def test_live_api_playtest_aggregates_story_matrix_and_scorecard(monkeypatch, tmp_path) -> None:
    seeds = build_story_seed_batch(rng=Random(11))

    def _fake_author_story(*, session, base_url, generated_seed):  # noqa: ANN001
        del session, base_url
        return {
            "bucket_id": generated_seed.bucket_id,
            "slug": generated_seed.slug,
            "seed": generated_seed.seed,
            "generated_at": generated_seed.generated_at,
            "job_id": f"{generated_seed.slug}-job",
            "preview": {"preview_id": f"{generated_seed.slug}-preview"},
            "stream": {"events": [], "stream_elapsed_seconds": 1.2, "terminal_event": {"event": "job_completed"}},
            "result": {"status": "completed"},
            "diagnostics": {
                "source_summary": {
                    "story_frame_source": "generated",
                    "beat_plan_source": "generated",
                    "route_affordance_source": "generated",
                    "ending_source": "generated",
                    "gameplay_semantics_source": "repaired",
                },
                "token_cost_estimate": {"estimated_total_cost_rmb": 0.0012},
            },
            "published_story": {
                "story_id": f"{generated_seed.slug}-story",
                "title": generated_seed.slug.replace("_", " ").title(),
            },
            "story_detail": {
                "story": {
                    "story_id": f"{generated_seed.slug}-story",
                    "title": generated_seed.slug.replace("_", " ").title(),
                    "theme": "Civic crisis",
                }
            },
            "error": None,
            "timings": {"author_total_elapsed_seconds": 3.4},
        }

    def _fake_story_playtests(*, base_url, story_detail, max_turns):  # noqa: ANN001
        del base_url, max_turns
        story_id = story_detail["story"]["story_id"]
        sessions = []
        for index, persona in enumerate(live_api_playtest.PERSONAS):
            sessions.append(
                {
                    "persona_id": persona.persona_id,
                    "persona_label": persona.label,
                    "session_id": f"{story_id}-{persona.persona_id}",
                    "create_elapsed_seconds": 1.0 + (index * 0.1),
                    "forced_stop": False,
                    "opening": "You enter the scene and everyone watches your first move.",
                    "final_snapshot": {"status": "completed", "turn_index": 4, "ending": {"ending_id": "mixed"}},
                    "turns": [
                        {"submit_elapsed_seconds": 3.1, "narration_word_count": 82},
                        {"submit_elapsed_seconds": 4.0, "narration_word_count": 88},
                    ],
                        "diagnostics": {
                            "summary": {
                                "render_fallback_turn_count": 0,
                                "heuristic_interpret_turn_count": 0,
                                "usage_totals": {"input_tokens": 120, "output_tokens": 60},
                                "interpret_source_distribution": {"llm": 1, "heuristic": 1},
                                "render_source_distribution": {"llm": 1, "llm_repair": 1},
                            },
                        "turn_traces": [
                            {
                                "interpret_source": "llm",
                                "render_source": "llm",
                                "interpret_failure_reason": None,
                                "render_failure_reason": None,
                            },
                            {
                                "interpret_source": "heuristic",
                                "render_source": "llm_repair",
                                "interpret_failure_reason": "schema_repair",
                                "render_failure_reason": "scene_plan_missing",
                            },
                        ],
                    },
                    "diagnostics_elapsed_seconds": 0.2,
                    "agent_report": {
                        "flags": [],
                        "ratings": {
                            "narration_coherence": 4,
                            "suggested_action_relevance": 4,
                            "state_feedback_credibility": 4,
                            "ending_satisfaction": 4,
                            "overall_player_feel": 4,
                            "content_richness": 4,
                            "state_feedback_distinctness": 4,
                        },
                        "best_moment": "A key confrontation landed cleanly.",
                        "verdict": "Strong, coherent session.",
                        "source": "llm_salvage_partial" if index == len(live_api_playtest.PERSONAS) - 1 else "llm",
                    },
                    "agent_cache_metrics": {},
                    "agent_cost_estimate": None,
                    "agent_call_trace": [{"operation": f"playtest_turn_{persona.persona_id}", "response_received": True}],
                    "error": None,
                }
            )
        return sessions

    monkeypatch.setattr(
        live_api_playtest,
        "build_story_seed_batch",
        lambda rng=None, story_count=5, language="en": seeds[:story_count],
    )
    monkeypatch.setattr(
        live_api_playtest,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            runtime_profile="beecode",
            responses_author_base_url="https://beecode.cc/v1",
            responses_author_api_key="author-key",
            responses_author_model="gpt-5.4-mini",
            responses_play_base_url="https://beecode.cc/v1",
            responses_play_api_key="play-key",
            responses_play_model="gpt-5.4-mini",
            helper_slot_2_base_url="https://beecode.cc/v1",
            helper_slot_2_api_key="helper-key",
            helper_slot_2_model="gpt-5.4-mini",
            helper_slot_2_role="primary",
        ),
    )
    monkeypatch.setattr(live_api_playtest, "_run_author_story", _fake_author_story)
    monkeypatch.setattr(live_api_playtest, "_run_story_playtests", _fake_story_playtests)

    payload = live_api_playtest.run_live_api_playtest(
        live_api_playtest.LiveApiPlaytestConfig(
            base_url="http://127.0.0.1:8010",
            output_dir=tmp_path,
            label="matrix-test",
            launch_server=False,
            session_ttl_seconds=3600,
            max_turns=6,
            seed=11,
            story_count=3,
            phase_id="stage1",
            seed_set_id="seed-set-a",
            arm="candidate",
            baseline_artifact=None,
        )
    )

    assert len(payload["stories"]) == 3
    assert len(payload["personas"]) == 5
    assert all(len(story["sessions"]) == len(live_api_playtest.PERSONAS) for story in payload["stories"])
    assert payload["scorecard"]["target_session_count"] == 15
    assert payload["scorecard"]["actuals"]["author_publish_success_rate"] == 1.0
    assert payload["scorecard"]["actuals"]["play_completed_sessions"] == 15
    assert payload["scorecard"]["actuals"]["render_fallback_rate"] == 0.0
    assert payload["scorecard"]["actuals"]["mean_narration_word_count_per_turn"] >= 80
    assert payload["scorecard"]["actuals"]["axis_diversity_per_session"] == 0.0
    assert payload["scorecard"]["actuals"]["state_feedback_distinctness"] == 4.0
    assert payload["scorecard"]["actuals"]["judge_nonfallback_rate"] == 1.0
    assert payload["scorecard"]["actuals"]["judge_fallback_rate"] == 0.0
    assert payload["scorecard"]["actuals"]["agent_trace_coverage_rate"] == 1.0
    assert payload["scorecard"]["actuals"]["play_trace_coverage_rate"] == 1.0
    assert payload["scorecard"]["actuals"]["trace_labeled_failure_rate"] == 1.0
    assert payload["scorecard"]["subjective_summary"]["avg_suggested_action_relevance"] == 4.0
    assert payload["scorecard"]["judge_trace_evaluation"]["trace_labeled_failure_turns"] == 15
    assert payload["scorecard"]["judge_trace_evaluation"]["trace_failure_candidate_turns"] == 15
    assert payload["scorecard"]["passed"] is True
    assert payload["phase_id"] == "stage1"
    assert payload["seed_set_id"] == "seed-set-a"
    assert payload["arm"] == "candidate"
    assert payload["runtime_profile"] == "beecode"
    assert payload["runtime_config"]["author"]["base_url"] == "https://beecode.cc/v1"
    assert payload["runtime_config"]["play"]["model"] == "gpt-5.4-mini"
    assert payload["runtime_config"]["helper"]["base_url"] == "https://beecode.cc/v1"


def test_compare_benchmark_payloads_reports_phase_gates() -> None:
    baseline = {
        "label": "baseline",
        "seed_set_id": "seed-set-b",
        "scorecard": {
            "target_session_count": 6,
            "actuals": {
                "author_publish_success_rate": 1.0,
                "play_completed_sessions": 6,
                "expired_sessions": 0,
                "p95_submit_turn_seconds": 10.0,
                "heuristic_interpret_rate": 0.0,
                "render_fallback_rate": 0.2,
                "flat_state_feedback_flag_rate": 0.7,
                "axis_diversity_per_session": 1.2,
                "state_feedback_distinctness": 3.0,
                "player_identity_confusion_flag_rate": 0.0,
                "mean_narration_word_count_per_turn": 90.0,
            },
            "ending_distribution": {"collapse": 4, "pyrrhic": 2},
        },
    }
    candidate = {
        "label": "candidate",
        "seed_set_id": "seed-set-b",
        "scorecard": {
            "target_session_count": 6,
            "actuals": {
                "author_publish_success_rate": 1.0,
                "play_completed_sessions": 6,
                "expired_sessions": 0,
                "p95_submit_turn_seconds": 11.0,
                "heuristic_interpret_rate": 0.0,
                "render_fallback_rate": 0.1,
                "flat_state_feedback_flag_rate": 0.5,
                "axis_diversity_per_session": 2.2,
                "state_feedback_distinctness": 4.0,
                "player_identity_confusion_flag_rate": 0.0,
                "mean_narration_word_count_per_turn": 95.0,
            },
            "ending_distribution": {"collapse": 3, "pyrrhic": 3},
        },
    }

    compare = live_api_playtest.compare_benchmark_payloads(
        baseline_payload=baseline,
        candidate_payload=candidate,
        phase_id="stage1",
        baseline_artifact="/tmp/baseline.json",
    )

    assert compare["passed"] is True
    assert compare["delta_actuals"]["flat_state_feedback_flag_rate"] == -0.2
    assert compare["ending_distribution_shift"]["collapse"] == -1


def test_normalize_agent_report_removes_inconsistent_flat_state_flag() -> None:
    report = {
        "ending_id": "pyrrhic",
        "turn_count": 4,
        "ratings": {
            "narration_coherence": 5,
            "suggested_action_relevance": 4,
            "state_feedback_credibility": 5,
            "ending_satisfaction": 4,
            "overall_player_feel": 4,
            "protagonist_identity_clarity": 4,
            "content_richness": 4,
            "state_feedback_distinctness": 5,
        },
        "flags": ["flat_state_feedback"],
        "strongest_issue": "Test issue",
        "best_moment": "Test moment",
        "verdict": "Test verdict",
        "source": "llm",
    }
    turns = [
        {
            "feedback": {
                "last_turn_axis_deltas": {"public_panic": 2},
                "last_turn_stance_deltas": {"npc_a": -1},
                "last_turn_consequences": ["Visible public pressure rose.", "At least one relationship took damage."],
            }
        },
        {
            "feedback": {
                "last_turn_axis_deltas": {"political_leverage": 2},
                "last_turn_stance_deltas": {},
                "last_turn_consequences": ["The crisis moved closer to a binding outcome."],
            }
        },
        {
            "feedback": {
                "last_turn_axis_deltas": {"public_panic": -1},
                "last_turn_stance_deltas": {"npc_b": 1},
                "last_turn_consequences": ["Visible public pressure eased.", "A relationship shifted inside the coalition."],
            }
        },
    ]

    normalized = live_api_playtest._normalize_agent_report(report=report, turns=turns)

    assert "flat_state_feedback" not in normalized["flags"]


def test_normalize_agent_report_maps_legacy_fields_to_new_subjective_schema() -> None:
    report = {
        "ending_id": "mixed",
        "turn_count": 3,
        "ratings": {
            "narration_coherence": 4,
            "suggested_action_coherence": 2,
            "state_feedback_credibility": 3,
            "content_richness": 4,
        },
        "flags": [],
        "strongest_issue": "Legacy issue",
        "player_feel_verdict": "Legacy verdict",
        "source": "llm",
    }

    normalized = live_api_playtest._normalize_agent_report(report=report, turns=[])

    assert normalized["ratings"]["suggested_action_relevance"] == 2
    assert normalized["ratings"]["overall_player_feel"] == 3
    assert normalized["verdict"] == "Legacy verdict"
