from __future__ import annotations

import asyncio
import pytest

from rpg_backend.domain.linter import LintReport
from rpg_backend.generator.errors import GeneratorBuildError
from rpg_backend.generator.pipeline import GeneratorPipeline
from rpg_backend.generator.prompt_compiler import PromptCompileError


def test_pipeline_rejects_missing_seed_and_prompt() -> None:
    pipeline = GeneratorPipeline()
    with pytest.raises(GeneratorBuildError) as exc_info:
        asyncio.run(
            pipeline.run(
                seed_text="   ",
                prompt_text="   ",
                target_minutes=10,
                npc_count=4,
            )
        )

    assert exc_info.value.error_code == "generator_input_invalid"
    assert exc_info.value.lint_report.errors == ["either seed_text or prompt_text must be provided"]


def test_pipeline_prompt_compile_failfast_does_not_use_seed_planner(monkeypatch) -> None:
    monkeypatch.setattr(
        "rpg_backend.generator.pipeline.PromptCompiler.compile",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PromptCompileError(
                error_code="prompt_compile_failed",
                errors=["upstream timeout"],
                notes=["prompt compiler failed after retries"],
            )
        ),
    )

    seed_planner_called = {"value": False}

    def _seed_planner(*args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        seed_planner_called["value"] = True
        raise AssertionError("seed planner should not run when prompt compile fails")

    pipeline = GeneratorPipeline(seed_planner=_seed_planner)
    with pytest.raises(GeneratorBuildError) as exc_info:
        asyncio.run(
            pipeline.run(
                prompt_text="compile from prompt",
                target_minutes=10,
                npc_count=4,
            )
        )

    assert exc_info.value.error_code == "prompt_compile_failed"
    assert seed_planner_called["value"] is False


def test_pipeline_terminal_regenerate_failure_payload(monkeypatch) -> None:
    import rpg_backend.generator.candidate_executor as candidate_module

    monkeypatch.setattr(
        candidate_module,
        "lint_story_pack",
        lambda _: LintReport(errors=["always bad"], warnings=["forced warning"]),
    )

    pipeline = GeneratorPipeline()
    with pytest.raises(GeneratorBuildError) as exc_info:
        asyncio.run(
            pipeline.run(
                seed_text="always fail lint",
                target_minutes=10,
                npc_count=4,
                variant_seed="regen-loop",
            )
        )

    exc = exc_info.value
    assert exc.error_code == "generation_failed_after_regenerates"
    assert exc.generation_attempts == 4
    assert exc.regenerate_count == 3
    assert exc.variant_seed == "regen-loop#regen3"
    assert exc.lint_report.errors == ["always bad"]
    assert exc.lint_report.warnings == ["forced warning"]
