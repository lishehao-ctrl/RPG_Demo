from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rpg_backend.author.benchmarks import runner


def _fake_result(
    *,
    run_id: str,
    title: str,
    story_frame_source: str = "generated",
    beat_plan_source: str = "generated",
    route_affordance_source: str = "compiled",
    ending_source: str = "generated",
    cast_topology: str = "four_slot",
    reasons: list[dict] | None = None,
):
    return SimpleNamespace(
        run_id=run_id,
        bundle=SimpleNamespace(
            story_bible=SimpleNamespace(
                title=title,
                premise=f"{title} premise",
                cast=[
                    SimpleNamespace(name="A"),
                    SimpleNamespace(name="B"),
                    SimpleNamespace(name="C"),
                    SimpleNamespace(name="D"),
                ],
            ),
            beat_spine=[SimpleNamespace(), SimpleNamespace(), SimpleNamespace()],
            rule_pack=SimpleNamespace(
                route_unlock_rules=[SimpleNamespace(), SimpleNamespace()],
                ending_rules=[
                    SimpleNamespace(ending_id="collapse"),
                    SimpleNamespace(ending_id="pyrrhic"),
                    SimpleNamespace(ending_id="mixed"),
                ],
            ),
        ),
        state={
            "story_frame_source": story_frame_source,
            "beat_plan_source": beat_plan_source,
            "route_affordance_source": route_affordance_source,
            "ending_source": ending_source,
            "cast_topology": cast_topology,
            "llm_call_trace": [
                {
                    "operation": "story_frame_semantics",
                    "used_previous_response_id": False,
                    "input_characters": 120,
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                }
            ],
            "quality_trace": reasons or [],
        },
    )


def test_parse_args_supports_suite_and_defaults(tmp_path: Path) -> None:
    config = runner.parse_args(
        [
            "--suite",
            "blackout_succession",
            "--runs",
            "3",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert config.suite == "blackout_succession"
    assert config.runs == 3
    assert config.rounds == 1
    assert config.briefs
    assert config.output_dir == tmp_path.resolve()


def test_parse_args_supports_rounds(tmp_path: Path) -> None:
    config = runner.parse_args(
        [
            "--suite",
            "blackout_succession",
            "--runs",
            "8",
            "--rounds",
            "2",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert config.runs == 8
    assert config.rounds == 2


def test_summarize_results_aggregates_trace_metrics() -> None:
    results = [
        {
            "run": 1,
            "title": "T1",
            "beat_count": 3,
            "route_count": 2,
            "duration_seconds": 10.0,
            "cast_topology": "four_slot",
            "quality_trace": [
                {"stage": "story_frame", "source": "generated", "outcome": "accepted", "reasons": []},
                {"stage": "cast_member", "source": "default", "outcome": "fallback", "reasons": ["llm_invalid_json"]},
            ],
        },
        {
            "run": 2,
            "title": "T2",
            "beat_count": 2,
            "route_count": 1,
            "duration_seconds": 20.0,
            "cast_topology": "three_slot",
            "quality_trace": [
                {"stage": "ending", "source": "generated", "outcome": "accepted", "reasons": []},
            ],
        },
    ]

    summary = runner.summarize_results(results)

    assert summary["source_distribution"]["story_frame:generated"] == 1
    assert summary["source_distribution"]["cast_member:default"] == 1
    assert summary["reason_distribution"]["cast_member:llm_invalid_json"] == 1
    assert summary["cast_topology_distribution"]["four_slot"] == 1
    assert summary["cast_topology_distribution"]["three_slot"] == 1
    assert summary["duration_summary"]["avg_seconds"] == 15.0
    assert summary["duration_summary"]["median_seconds"] == 15.0
    assert summary["llm_summary"]["total_call_count"] == 0
    assert summary["default_fallback_rate"] == round(1 / 3, 4)


def test_summarize_rounds_computes_round_trends() -> None:
    results = [
        {
            "round": 1,
            "run": 1,
            "title": "T1",
            "beat_count": 3,
            "route_count": 2,
            "duration_seconds": 10.0,
            "cast_topology": "four_slot",
            "quality_trace": [
                {"stage": "story_frame", "source": "generated", "outcome": "accepted", "reasons": []},
                {"stage": "cast_member", "source": "default", "outcome": "fallback", "reasons": ["llm_invalid_json"]},
            ],
        },
        {
            "round": 2,
            "run": 2,
            "title": "T2",
            "beat_count": 2,
            "route_count": 1,
            "duration_seconds": 20.0,
            "cast_topology": "three_slot",
            "quality_trace": [
                {"stage": "ending", "source": "generated", "outcome": "accepted", "reasons": []},
            ],
        },
    ]

    round_summaries, trend_summary = runner.summarize_rounds(results)

    assert len(round_summaries) == 2
    assert round_summaries[0]["round"] == 1
    assert round_summaries[1]["round"] == 2
    assert trend_summary["default_fallback_rate_by_round"] == [0.5, 0.0]
    assert trend_summary["default_fallback_rate_median"] == 0.25
    assert trend_summary["avg_duration_by_round"] == [10.0, 20.0]
    assert trend_summary["median_duration_median"] == 15.0


def test_run_benchmark_and_write_artifacts(monkeypatch, tmp_path: Path) -> None:
    fake_results = [
        _fake_result(
            run_id="r1",
            title="Run One",
            reasons=[
                {"stage": "story_frame", "source": "generated", "outcome": "accepted", "reasons": []},
                {"stage": "ending", "source": "generated", "outcome": "accepted", "reasons": []},
            ],
        ),
        _fake_result(
            run_id="r2",
            title="Run Two",
            reasons=[
                {"stage": "cast_member", "source": "default", "outcome": "fallback", "reasons": ["llm_invalid_json"]},
            ],
        ),
    ]

    def _fake_run_author_bundle(_request):
        return fake_results.pop(0)

    monkeypatch.setattr(runner, "run_author_bundle", _fake_run_author_bundle)
    config = runner.RunnerConfig(
        briefs=["custom brief"],
        suite=None,
        runs=2,
        rounds=1,
        label="smoke",
        baseline=None,
        output_dir=tmp_path,
    )

    summary, markdown = runner.run_benchmark(config)
    json_path, md_path = runner.write_artifacts(config, summary, markdown)

    assert summary["runs_per_brief"] == 2
    assert summary["rounds"] == 1
    assert summary["source_distribution"]["cast_member:default"] == 1
    assert summary["round_summaries"][0]["round"] == 1
    assert summary["llm_summary"]["total_call_count"] == 2
    assert summary["llm_summary"]["usage_totals"]["input_tokens"] == 20
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["results"][0]["title"] == "Run One"
    assert "## Run Summary" in md_path.read_text()


def test_run_benchmark_loads_baseline_summary(monkeypatch, tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "source_distribution": {"story_frame:default": 3},
                "outcome_distribution": {"story_frame:fallback": 3},
                "reason_distribution": {"story_frame:llm_invalid_json": 3},
                "default_fallback_rate": 0.6,
                "generated_accept_rate": 0.4,
                "duration_summary": {"avg_seconds": 50.0},
            }
        )
    )

    monkeypatch.setattr(
        runner,
        "run_author_bundle",
        lambda _request: _fake_result(
            run_id="r1",
            title="Candidate",
            reasons=[{"stage": "story_frame", "source": "generated", "outcome": "accepted", "reasons": []}],
        ),
    )

    config = runner.RunnerConfig(
        briefs=["custom brief"],
        suite=None,
        runs=1,
        rounds=1,
        label="stability-v2",
        baseline=baseline_path,
        output_dir=tmp_path,
    )

    summary, _markdown = runner.run_benchmark(config)

    assert summary["baseline_artifact"] == str(baseline_path)
    assert summary["baseline_summary"]["default_fallback_rate"] == 0.6
    assert summary["candidate_summary"]["generated_accept_rate"] == 1.0
