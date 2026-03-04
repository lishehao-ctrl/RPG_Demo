from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from rpg_backend.domain.linter import LintReport, lint_story_pack
from rpg_backend.generator.builder import build_pack
from rpg_backend.generator.versioning import (
    GENERATOR_VERSION,
    PalettePolicy,
    build_seed_material,
    derive_rng,
)


@dataclass(frozen=True)
class CandidateBuildResult:
    candidate_index: int
    candidate_seed: str
    pack: dict[str, Any]
    lint_report: LintReport


@dataclass(frozen=True)
class CandidateExecutionResult:
    candidates: list[CandidateBuildResult]
    winner: CandidateBuildResult | None
    best_candidate: CandidateBuildResult
    candidate_count: int


def derive_candidate_seed(attempt_seed: str, candidate_index: int) -> str:
    if candidate_index == 0:
        return attempt_seed
    return f"{attempt_seed}#cand{candidate_index}"


def build_candidate(
    *,
    seed_material_text: str,
    target_minutes: int,
    npc_count: int,
    style: str | None,
    candidate_seed: str,
    plan: Any,
    palette_policy: PalettePolicy,
    generator_version: str = GENERATOR_VERSION,
) -> CandidateBuildResult:
    seed_material = build_seed_material(
        seed_text=seed_material_text,
        target_minutes=target_minutes,
        npc_count=npc_count,
        style=style,
        variant_seed=candidate_seed,
        generator_version=generator_version,
        palette_policy=palette_policy,
    )
    runtime_rng = derive_rng(seed_material)
    pack = build_pack(plan, style=style, rng=runtime_rng, palette_policy=palette_policy)
    lint_report = lint_story_pack(pack)
    return CandidateBuildResult(
        candidate_index=0,
        candidate_seed=candidate_seed,
        pack=pack,
        lint_report=lint_report,
    )


def execute_candidates(
    *,
    seed_material_text: str,
    target_minutes: int,
    npc_count: int,
    style: str | None,
    attempt_seed: str,
    plan: Any,
    palette_policy: PalettePolicy,
    candidate_count: int,
    candidate_seed_resolver: Callable[[str, int], str] = derive_candidate_seed,
    build_candidate_fn: Callable[..., CandidateBuildResult] | None = None,
) -> CandidateExecutionResult:
    if build_candidate_fn is None:
        build_candidate_fn = build_candidate

    bounded_candidate_count = max(1, int(candidate_count))
    candidates: list[CandidateBuildResult] = []
    winner: CandidateBuildResult | None = None

    if bounded_candidate_count <= 1:
        candidate = build_candidate_fn(
            seed_material_text=seed_material_text,
            target_minutes=target_minutes,
            npc_count=npc_count,
            style=style,
            candidate_seed=attempt_seed,
            plan=plan,
            palette_policy=palette_policy,
        )
        materialized = CandidateBuildResult(
            candidate_index=0,
            candidate_seed=attempt_seed,
            pack=candidate.pack,
            lint_report=candidate.lint_report,
        )
        candidates.append(materialized)
        if materialized.lint_report.ok:
            winner = materialized
    else:
        with ThreadPoolExecutor(max_workers=bounded_candidate_count) as pool:
            future_map = {}
            for candidate_index in range(bounded_candidate_count):
                candidate_seed = candidate_seed_resolver(attempt_seed, candidate_index)
                future = pool.submit(
                    build_candidate_fn,
                    seed_material_text=seed_material_text,
                    target_minutes=target_minutes,
                    npc_count=npc_count,
                    style=style,
                    candidate_seed=candidate_seed,
                    plan=plan,
                    palette_policy=palette_policy,
                )
                future_map[future] = (candidate_index, candidate_seed)

            for future in as_completed(future_map):
                candidate_index, candidate_seed = future_map[future]
                try:
                    candidate = future.result()
                    materialized = CandidateBuildResult(
                        candidate_index=candidate_index,
                        candidate_seed=candidate_seed,
                        pack=candidate.pack,
                        lint_report=candidate.lint_report,
                    )
                except Exception as exc:  # noqa: BLE001
                    materialized = CandidateBuildResult(
                        candidate_index=candidate_index,
                        candidate_seed=candidate_seed,
                        pack={},
                        lint_report=LintReport(
                            errors=[f"candidate_build_exception: {type(exc).__name__}: {exc}"],
                            warnings=[],
                        ),
                    )
                candidates.append(materialized)
                if winner is None and materialized.lint_report.ok:
                    winner = materialized

    best_candidate = min(
        candidates,
        key=lambda item: (len(item.lint_report.errors), item.candidate_index),
    )
    return CandidateExecutionResult(
        candidates=candidates,
        winner=winner,
        best_candidate=best_candidate,
        candidate_count=bounded_candidate_count,
    )
