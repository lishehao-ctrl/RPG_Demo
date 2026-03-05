#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rpg_backend.generator.pipeline import GeneratorPipeline
from rpg_backend.generator.versioning import PalettePolicy, compute_transcript_digest

try:
    from scripts.simulate_playthrough import DEFAULT_STRATEGIES, simulate_pack_playthrough
except ModuleNotFoundError:
    from simulate_playthrough import DEFAULT_STRATEGIES, simulate_pack_playthrough


def _extract_palette_ids(pack_json: dict[str, Any]) -> list[str]:
    palette_ids: list[str] = []
    for move in pack_json.get("moves", []):
        for outcome in move.get("outcomes", []):
            outcome_id = outcome.get("id", "")
            parts = outcome_id.split(".")
            if len(parts) >= 3:
                palette_ids.append(parts[-1])
    return palette_ids


def evaluate_generator(
    *,
    seed_text: str,
    runs: int,
    strategy_count: int,
    target_minutes: int,
    npc_count: int,
    variant_seed: str | None = None,
    palette_policy: PalettePolicy = "random",
    packs_dir: Path | None = None,
) -> dict[str, Any]:
    pipeline = GeneratorPipeline()
    selected_strategies = list(DEFAULT_STRATEGIES[: max(1, min(strategy_count, len(DEFAULT_STRATEGIES)))])
    output_packs_dir = packs_dir or Path("reports/packs")
    os.makedirs(output_packs_dir, exist_ok=True)

    total_playthroughs = 0
    completion_count = 0
    completed_steps: list[int] = []
    total_steps = 0
    meaningful_steps = 0
    palette_distribution: dict[str, int] = {}
    run_summaries: list[dict[str, Any]] = []

    for run_idx in range(1, runs + 1):
        run_variant_seed = f"{variant_seed}:{run_idx}" if variant_seed else None
        generated = asyncio.run(
            pipeline.run(
                seed_text=seed_text,
                target_minutes=target_minutes,
                npc_count=npc_count,
                style=None,
                variant_seed=run_variant_seed,
                palette_policy=palette_policy,
            )
        )
        pack = generated.pack
        pack_hash = generated.pack_hash
        strategy_base_seed = secrets.randbelow(2**31 - 1)
        pack_path = output_packs_dir / f"{pack_hash}.json"
        pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

        for palette_id in _extract_palette_ids(pack):
            palette_distribution[palette_id] = palette_distribution.get(palette_id, 0) + 1

        strategy_reports: list[dict[str, Any]] = []
        for strategy in selected_strategies:
            strategy_material = f"{pack_hash}|{strategy}|{run_idx}|{strategy_base_seed}"
            strategy_seed = int(hashlib.sha256(strategy_material.encode("utf-8")).hexdigest()[:8], 16)
            report = simulate_pack_playthrough(
                pack,
                strategy=strategy,
                max_steps=20,
                strategy_seed=strategy_seed,
                metadata={
                    "pack_hash": generated.pack_hash,
                    "generator_version": generated.generator_version,
                    "variant_seed": generated.variant_seed,
                },
            )
            transcript_digest = compute_transcript_digest(report["transcript"])
            total_playthroughs += 1
            total_steps += report["steps"]
            meaningful_steps += report["meaningful_steps"]

            if report["ended"]:
                completion_count += 1
                completed_steps.append(report["steps"])

            strategy_reports.append(
                {
                    "strategy": strategy,
                    "ended": report["ended"],
                    "steps": report["steps"],
                    "meaningful_steps": report["meaningful_steps"],
                    "pack_hash": generated.pack_hash,
                    "generator_version": generated.generator_version,
                    "variant_seed": generated.variant_seed,
                    "palette_policy": generated.palette_policy,
                    "pack_path": str(pack_path),
                    "strategy_seed": strategy_seed,
                    "transcript_digest": transcript_digest,
                }
            )

        run_summaries.append(
            {
                "run": run_idx,
                "story_id": pack.get("story_id"),
                "pack_hash": generated.pack_hash,
                "generator_version": generated.generator_version,
                "variant_seed": generated.variant_seed,
                "palette_policy": generated.palette_policy,
                "pack_path": str(pack_path),
                "lint_errors": generated.lint_report.errors,
                "generation_attempts": generated.generation_attempts,
                "regenerate_count": generated.regenerate_count,
                "strategies": strategy_reports,
            }
        )

    completion_rate = completion_count / total_playthroughs if total_playthroughs else 0.0
    avg_steps = sum(completed_steps) / len(completed_steps) if completed_steps else 0.0
    meaningful_accept_rate = meaningful_steps / total_steps if total_steps else 0.0

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed_text": seed_text,
        "runs": runs,
        "palette_policy": palette_policy,
        "variant_seed": variant_seed,
        "strategies": selected_strategies,
        "metrics": {
            "completion_rate": completion_rate,
            "avg_steps": avg_steps,
            "meaningful_accept_rate": meaningful_accept_rate,
            "palette_diversity": {
                "unique_palette_count": len(palette_distribution),
                "palette_distribution": palette_distribution,
            },
        },
        "totals": {
            "total_playthroughs": total_playthroughs,
            "completion_count": completion_count,
            "total_steps": total_steps,
            "meaningful_steps": meaningful_steps,
        },
        "runs_detail": run_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate generator quality with repeated playthrough simulations.")
    parser.add_argument("--seed-text", required=True, help="Seed text used for repeated generation")
    parser.add_argument("--runs", type=int, default=10, help="Number of generated packs to evaluate")
    parser.add_argument("--strategies", type=int, default=5, help="Number of strategies to run per pack")
    parser.add_argument("--target-minutes", type=int, default=10, help="Target minutes for generation")
    parser.add_argument("--npc-count", type=int, default=4, help="NPC count for generation")
    parser.add_argument("--variant-seed", help="Optional base variant seed; run index is appended when provided")
    parser.add_argument(
        "--palette-policy",
        default="random",
        choices=["random", "balanced", "fixed"],
        help="Palette selection policy",
    )
    parser.add_argument("--output", default="reports/generator_eval.json", help="Output report path")
    args = parser.parse_args()

    output_path = Path(args.output)
    packs_dir = output_path.parent / "packs"
    report = evaluate_generator(
        seed_text=args.seed_text,
        runs=max(1, args.runs),
        strategy_count=max(1, args.strategies),
        target_minutes=args.target_minutes,
        npc_count=args.npc_count,
        variant_seed=args.variant_seed,
        palette_policy=args.palette_policy,
        packs_dir=packs_dir,
    )

    os.makedirs(output_path.parent, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
