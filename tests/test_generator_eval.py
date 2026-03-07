from __future__ import annotations

import os

import pytest
import json
from pathlib import Path


RUN_EVAL = bool(os.getenv("RUN_GENERATOR_EVAL"))


@pytest.mark.skipif(not RUN_EVAL, reason="set RUN_GENERATOR_EVAL=1 to run evaluation tests")
def test_generator_eval_report_shape() -> None:
    from scripts.eval.evaluate_generator import evaluate_generator

    report = evaluate_generator(
        seed_text="eval quality gate",
        runs=10,
        strategy_count=5,
        target_minutes=10,
        npc_count=4,
    )

    metrics = report["metrics"]
    assert 0.0 <= metrics["completion_rate"] <= 1.0
    assert 14 <= metrics["avg_steps"] <= 16
    assert 0.0 <= metrics["meaningful_accept_rate"] <= 1.0
    assert metrics["palette_diversity"]["unique_palette_count"] >= 5

    run_entry = report["runs_detail"][0]
    assert run_entry["pack_hash"]
    assert run_entry["generator_version"]
    assert run_entry["variant_seed"]
    assert run_entry["palette_policy"] in {"random", "balanced", "fixed"}
    assert run_entry["pack_path"]
    assert isinstance(run_entry["generation_attempts"], int)
    assert isinstance(run_entry["regenerate_count"], int)
    strategy_entry = run_entry["strategies"][0]
    assert strategy_entry["pack_hash"] == run_entry["pack_hash"]
    assert isinstance(strategy_entry["strategy_seed"], int)
    assert strategy_entry["transcript_digest"]


@pytest.mark.skipif(not RUN_EVAL, reason="set RUN_GENERATOR_EVAL=1 to run evaluation tests")
def test_replay_matches_digest(tmp_path: Path) -> None:
    from scripts.eval.evaluate_generator import evaluate_generator
    from scripts.eval.simulate_playthrough import simulate_pack_playthrough
    from rpg_backend.generator.versioning import compute_transcript_digest

    report = evaluate_generator(
        seed_text="eval replay gate",
        runs=1,
        strategy_count=2,
        target_minutes=10,
        npc_count=4,
        variant_seed="replay-base",
        palette_policy="random",
        packs_dir=tmp_path / "packs",
    )
    run_entry = report["runs_detail"][0]
    strategy_entry = run_entry["strategies"][0]

    pack_path = Path(strategy_entry["pack_path"])
    with pack_path.open("r", encoding="utf-8") as f:
        pack_json = json.load(f)

    replay = simulate_pack_playthrough(
        pack_json,
        strategy=strategy_entry["strategy"],
        max_steps=20,
        strategy_seed=strategy_entry["strategy_seed"],
        metadata={
            "pack_hash": run_entry["pack_hash"],
            "generator_version": run_entry["generator_version"],
            "variant_seed": run_entry["variant_seed"],
        },
    )
    replay_digest = compute_transcript_digest(replay["transcript"])
    assert replay_digest == strategy_entry["transcript_digest"]
