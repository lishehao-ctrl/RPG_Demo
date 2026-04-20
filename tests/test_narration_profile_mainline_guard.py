from __future__ import annotations

from pathlib import Path


def test_mainline_runners_do_not_expose_legacy_narration_profile_flags() -> None:
    runner_paths = (
        Path("tools/urban_author_play_benchmarks/gold_eval_mini_runner.py"),
        Path("tools/urban_author_play_benchmarks/gold_eval_full_runner.py"),
        Path("tools/urban_author_play_benchmarks/light_ab_baseline_refresh_runner.py"),
        Path("tools/urban_author_play_benchmarks/light_ab_eval_runner.py"),
        Path("tools/urban_author_play_benchmarks/play_eval_recompute_runner.py"),
    )
    forbidden_tokens = (
        "--narration-profile",
        "--baseline-profile",
        "--candidate-profile",
        "candidate_profile",
    )

    for path in runner_paths:
        text = path.read_text()
        for token in forbidden_tokens:
            assert token not in text, f"{path} unexpectedly contains legacy token: {token}"
