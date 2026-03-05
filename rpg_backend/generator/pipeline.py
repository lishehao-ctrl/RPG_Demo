from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Callable

from rpg_backend.config.settings import get_settings
from rpg_backend.domain.linter import LintReport
from rpg_backend.generator.candidate_executor import (
    CandidateExecutionResult,
    derive_candidate_seed,
    execute_candidates,
)
from rpg_backend.generator.errors import (
    GeneratorBuildError,
    build_input_error,
    build_prompt_compile_error,
    build_terminal_generation_error,
)
from rpg_backend.generator.planner import plan_beats, plan_beats_from_spec
from rpg_backend.generator.prompt_compiler import PromptCompileError, PromptCompiler
from rpg_backend.generator.result_builder import (
    GeneratorBuildResult,
    append_attempt_notes,
    build_attempt_history_record,
    build_success_result,
)
from rpg_backend.generator.versioning import (
    GENERATOR_VERSION,
    PalettePolicy,
    compute_pack_hash,
    normalize_variant_seed,
)

MAX_REGENERATE_RETRIES = 3
MAX_GENERATION_ATTEMPTS = MAX_REGENERATE_RETRIES + 1
MIN_CANDIDATE_PARALLELISM = 1
MAX_CANDIDATE_PARALLELISM = 8


@dataclass(frozen=True)
class GenerationContext:
    generation_mode: str
    seed_material_text: str
    normalized_prompt: str
    base_variant_seed: str
    effective_candidate_parallelism: int


@dataclass(frozen=True)
class PlannedAttempt:
    plan: Any
    spec_hash: str | None
    spec_summary: dict[str, Any] | None
    compile_notes: list[str]


class GeneratorPipeline:
    def __init__(
        self,
        *,
        prompt_compiler_factory: Callable[[], PromptCompiler] | None = None,
        seed_planner: Callable[[str, int, int], Any] | None = None,
        spec_planner: Callable[..., Any] | None = None,
        candidate_executor: Callable[..., CandidateExecutionResult] | None = None,
        settings_getter: Callable[[], Any] | None = None,
    ) -> None:
        self.prompt_compiler_factory = prompt_compiler_factory or PromptCompiler
        self.seed_planner = seed_planner or plan_beats
        self.spec_planner = spec_planner or plan_beats_from_spec
        self.candidate_executor = candidate_executor or execute_candidates
        self.settings_getter = settings_getter or get_settings

    @staticmethod
    def _attempt_variant_seed(base_variant_seed: str, attempt_index: int) -> str:
        if attempt_index == 0:
            return base_variant_seed
        return f"{base_variant_seed}#regen{attempt_index}"

    def _resolve_candidate_parallelism(self, requested: int | None) -> int:
        if requested is not None:
            return max(MIN_CANDIDATE_PARALLELISM, min(MAX_CANDIDATE_PARALLELISM, int(requested)))
        settings = self.settings_getter()
        configured = int(getattr(settings, "generator_candidate_parallelism", 1))
        return max(MIN_CANDIDATE_PARALLELISM, min(MAX_CANDIDATE_PARALLELISM, configured))

    def validate_request(
        self,
        *,
        seed_text: str | None,
        prompt_text: str | None,
        palette_policy: PalettePolicy,
        variant_seed: str | int | None,
        generator_version: str | None,
    ) -> tuple[str, str]:
        normalized_seed = (seed_text or "").strip()
        normalized_prompt = (prompt_text or "").strip()
        if not normalized_seed and not normalized_prompt:
            raise build_input_error(
                lint_errors=["either seed_text or prompt_text must be provided"],
                notes=["generator input validation failed"],
                error_code="generator_input_invalid",
                palette_policy=palette_policy,
                variant_seed=None,
            )

        if palette_policy not in {"random", "balanced", "fixed"}:
            raise build_input_error(
                lint_errors=[f"unsupported_palette_policy: '{palette_policy}'"],
                notes=["invalid palette policy"],
                error_code="unsupported_palette_policy",
                palette_policy=palette_policy,
                variant_seed=normalize_variant_seed(variant_seed),
            )

        if generator_version and generator_version != GENERATOR_VERSION:
            raise build_input_error(
                lint_errors=[
                    (
                        "unsupported_generator_version: "
                        f"requested='{generator_version}' expected='{GENERATOR_VERSION}'"
                    )
                ],
                notes=["generator version mismatch"],
                error_code="unsupported_generator_version",
                palette_policy=palette_policy,
                variant_seed=normalize_variant_seed(variant_seed),
            )
        return normalized_seed, normalized_prompt

    def resolve_generation_context(
        self,
        *,
        normalized_seed: str,
        normalized_prompt: str,
        variant_seed: str | int | None,
        candidate_parallelism: int | None,
    ) -> GenerationContext:
        generation_mode = "prompt" if normalized_prompt else "seed"
        seed_material_text = normalized_seed or normalized_prompt
        base_variant_seed = normalize_variant_seed(variant_seed) or secrets.token_hex(8)
        effective_candidate_parallelism = self._resolve_candidate_parallelism(candidate_parallelism)
        return GenerationContext(
            generation_mode=generation_mode,
            seed_material_text=seed_material_text,
            normalized_prompt=normalized_prompt,
            base_variant_seed=base_variant_seed,
            effective_candidate_parallelism=effective_candidate_parallelism,
        )

    async def compile_or_plan(
        self,
        *,
        generation_context: GenerationContext,
        target_minutes: int,
        npc_count: int,
        style: str | None,
        attempt_index: int,
        attempt_seed: str,
    ) -> PlannedAttempt:
        if generation_context.generation_mode == "seed":
            plan = self.seed_planner(
                seed_text=generation_context.seed_material_text,
                target_minutes=target_minutes,
                npc_count=npc_count,
            )
            return PlannedAttempt(plan=plan, spec_hash=None, spec_summary=None, compile_notes=[])

        compiled = await self.prompt_compiler_factory().compile(
            prompt_text=generation_context.normalized_prompt,
            target_minutes=target_minutes,
            npc_count=npc_count,
            style=style,
            attempt_index=attempt_index,
            attempt_seed=attempt_seed,
        )
        plan = self.spec_planner(
            spec=compiled.spec,
            seed_text=generation_context.seed_material_text,
            target_minutes=target_minutes,
            npc_count=npc_count,
        )
        return PlannedAttempt(
            plan=plan,
            spec_hash=compiled.spec_hash,
            spec_summary=compiled.spec.compact_summary(),
            compile_notes=list(compiled.notes),
        )

    async def run(
        self,
        *,
        seed_text: str | None = None,
        prompt_text: str | None = None,
        target_minutes: int,
        npc_count: int,
        style: str | None = None,
        variant_seed: str | int | None = None,
        candidate_parallelism: int | None = None,
        generator_version: str | None = None,
        palette_policy: PalettePolicy = "random",
    ) -> GeneratorBuildResult:
        normalized_seed, normalized_prompt = self.validate_request(
            seed_text=seed_text,
            prompt_text=prompt_text,
            palette_policy=palette_policy,
            variant_seed=variant_seed,
            generator_version=generator_version,
        )
        generation_context = self.resolve_generation_context(
            normalized_seed=normalized_seed,
            normalized_prompt=normalized_prompt,
            variant_seed=variant_seed,
            candidate_parallelism=candidate_parallelism,
        )

        notes = [
            "generator pipeline used",
            "regenerate strategy enabled",
            f"generation_mode={generation_context.generation_mode}",
            f"generator_version={GENERATOR_VERSION}",
            f"base_variant_seed={generation_context.base_variant_seed}",
            f"palette_policy={palette_policy}",
            f"max_regenerate_retries={MAX_REGENERATE_RETRIES}",
            f"candidate_parallelism={generation_context.effective_candidate_parallelism}",
        ]
        attempt_history: list[dict[str, Any]] = []
        last_lint_report = LintReport(errors=["generation did not start"], warnings=[])
        last_attempt_seed = generation_context.base_variant_seed

        for attempt_index in range(MAX_GENERATION_ATTEMPTS):
            generation_attempts = attempt_index + 1
            regenerate_count = attempt_index
            attempt_seed = self._attempt_variant_seed(generation_context.base_variant_seed, attempt_index)
            last_attempt_seed = attempt_seed
            append_attempt_notes(
                notes=notes,
                generation_attempts=generation_attempts,
                regenerate_count=regenerate_count,
                attempt_seed=attempt_seed,
            )

            try:
                planned_attempt = await self.compile_or_plan(
                    generation_context=generation_context,
                    target_minutes=target_minutes,
                    npc_count=npc_count,
                    style=style,
                    attempt_index=attempt_index,
                    attempt_seed=attempt_seed,
                )
            except PromptCompileError as exc:
                attempt_history.append(
                    build_attempt_history_record(
                        attempt_index=generation_attempts,
                        variant_seed=attempt_seed,
                        winner_candidate_index=None,
                        winner_candidate_seed=None,
                        best_candidate_index=None,
                        best_candidate_seed=None,
                        lint_ok=False,
                        candidate_count=generation_context.effective_candidate_parallelism,
                    )
                )
                raise build_prompt_compile_error(
                    errors=exc.errors,
                    error_code=exc.error_code,
                    generation_attempts=generation_attempts,
                    regenerate_count=regenerate_count,
                    notes=notes + exc.notes,
                    variant_seed=attempt_seed,
                    palette_policy=palette_policy,
                    candidate_parallelism=generation_context.effective_candidate_parallelism,
                    attempt_history=attempt_history,
                ) from exc

            notes.extend(planned_attempt.compile_notes)
            if planned_attempt.spec_hash is not None:
                notes.append(f"spec_hash_attempt_{generation_attempts}={planned_attempt.spec_hash}")

            candidates = self.candidate_executor(
                seed_material_text=generation_context.seed_material_text,
                target_minutes=target_minutes,
                npc_count=npc_count,
                style=style,
                attempt_seed=attempt_seed,
                plan=planned_attempt.plan,
                palette_policy=palette_policy,
                candidate_count=generation_context.effective_candidate_parallelism,
                candidate_seed_resolver=derive_candidate_seed,
            )

            if candidates.winner is not None:
                winner = candidates.winner
                last_lint_report = winner.lint_report
                last_attempt_seed = winner.candidate_seed
                attempt_history.append(
                    build_attempt_history_record(
                        attempt_index=generation_attempts,
                        variant_seed=attempt_seed,
                        winner_candidate_index=winner.candidate_index,
                        winner_candidate_seed=winner.candidate_seed,
                        best_candidate_index=winner.candidate_index,
                        best_candidate_seed=winner.candidate_seed,
                        lint_ok=True,
                        candidate_count=candidates.candidate_count,
                    )
                )
                notes.append(f"lint_ok_attempt_{generation_attempts}=True")
                notes.append(
                    f"attempt_{generation_attempts}_winner="
                    f"candidate_{winner.candidate_index}:{winner.candidate_seed}"
                )
                pack_hash = compute_pack_hash(winner.pack)
                notes.extend(
                    [
                        f"target_steps={planned_attempt.plan.target_steps}",
                        f"npc_count={len(planned_attempt.plan.npc_names)}",
                        f"variant_seed={winner.candidate_seed}",
                        f"pack_hash={pack_hash}",
                    ]
                )
                return build_success_result(
                    pack=winner.pack,
                    pack_hash=pack_hash,
                    generator_version=GENERATOR_VERSION,
                    variant_seed=winner.candidate_seed,
                    palette_policy=palette_policy,
                    generation_mode=generation_context.generation_mode,
                    lint_report=winner.lint_report,
                    generation_attempts=generation_attempts,
                    regenerate_count=regenerate_count,
                    candidate_parallelism=generation_context.effective_candidate_parallelism,
                    attempt_history=attempt_history,
                    spec_hash=planned_attempt.spec_hash,
                    spec_summary=planned_attempt.spec_summary,
                )

            best_candidate = candidates.best_candidate
            attempt_history.append(
                build_attempt_history_record(
                    attempt_index=generation_attempts,
                    variant_seed=attempt_seed,
                    winner_candidate_index=None,
                    winner_candidate_seed=None,
                    best_candidate_index=best_candidate.candidate_index,
                    best_candidate_seed=best_candidate.candidate_seed,
                    lint_ok=False,
                    candidate_count=candidates.candidate_count,
                )
            )
            last_lint_report = best_candidate.lint_report
            last_attempt_seed = best_candidate.candidate_seed
            notes.append(f"lint_ok_attempt_{generation_attempts}=False")
            notes.append(
                f"attempt_{generation_attempts}_best_candidate="
                f"candidate_{best_candidate.candidate_index}:{best_candidate.candidate_seed}"
            )
            if regenerate_count < MAX_REGENERATE_RETRIES:
                notes.append(f"regenerate_triggered_after_attempt_{generation_attempts}")

        notes.append("generation_failed_after_regenerates")
        raise build_terminal_generation_error(
            lint_report=last_lint_report,
            notes=notes,
            variant_seed=last_attempt_seed,
            palette_policy=palette_policy,
            candidate_parallelism=generation_context.effective_candidate_parallelism,
            attempt_history=attempt_history,
            generation_attempts=MAX_GENERATION_ATTEMPTS,
            regenerate_count=MAX_REGENERATE_RETRIES,
        )
