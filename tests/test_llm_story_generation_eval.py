from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.domain.linter import LintReport
from app.eval.story_quality_schema import StoryQualityJudgeResult
from app.generator.service import GeneratorBuildError


def _load_eval_module():
    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(scripts_dir))
    script_path = scripts_dir / "evaluate_llm_story_generation.py"
    spec = importlib.util.spec_from_file_location("evaluate_llm_story_generation", script_path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("failed to load evaluate_llm_story_generation module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eval_story = _load_eval_module()


def test_gate_pass_when_all_thresholds_met() -> None:
    metrics = {
        "generation_success_rate": 1.0,
        "pack_lint_success_rate": 1.0,
        "completion_rate": 1.0,
        "avg_steps": 14.5,
        "meaningful_accept_rate": 0.95,
        "fallback_with_progress_rate": 1.0,
        "fallback_error_rate": 0.01,
        "fallback_low_confidence_rate": 0.04,
        "judge_overall_avg": 8.0,
        "judge_prompt_fidelity_avg": 7.8,
        "case_overall_score_min": 6.2,
        "judge_sample_count": 72.0,
        "expected_judge_sample_count": 72.0,
    }
    gate = eval_story._compute_gate(metrics)
    assert gate["passed"] is True
    assert gate["evaluation_status"] == "passed"
    assert gate["fail_reasons"] == []


def test_gate_fail_when_generation_success_rate_below_1() -> None:
    metrics = {
        "generation_success_rate": 0.95,
        "pack_lint_success_rate": 1.0,
        "completion_rate": 1.0,
        "avg_steps": 15.0,
        "meaningful_accept_rate": 0.95,
        "fallback_with_progress_rate": 1.0,
        "fallback_error_rate": 0.01,
        "fallback_low_confidence_rate": 0.02,
        "judge_overall_avg": 8.1,
        "judge_prompt_fidelity_avg": 7.7,
        "case_overall_score_min": 6.5,
        "judge_sample_count": 70.0,
        "expected_judge_sample_count": 72.0,
    }
    gate = eval_story._compute_gate(metrics)
    assert gate["passed"] is False
    assert gate["evaluation_status"] == "failed"
    assert any("generation_success_rate" in reason for reason in gate["fail_reasons"])


def test_gate_fail_when_judge_score_below_threshold() -> None:
    metrics = {
        "generation_success_rate": 1.0,
        "pack_lint_success_rate": 1.0,
        "completion_rate": 1.0,
        "avg_steps": 15.0,
        "meaningful_accept_rate": 0.95,
        "fallback_with_progress_rate": 1.0,
        "fallback_error_rate": 0.01,
        "fallback_low_confidence_rate": 0.02,
        "judge_overall_avg": 7.1,
        "judge_prompt_fidelity_avg": 6.8,
        "case_overall_score_min": 5.9,
        "judge_sample_count": 72.0,
        "expected_judge_sample_count": 72.0,
    }
    gate = eval_story._compute_gate(metrics)
    assert gate["passed"] is False
    assert any("judge_overall_avg" in reason for reason in gate["fail_reasons"])
    assert any("judge_prompt_fidelity_avg" in reason for reason in gate["fail_reasons"])
    assert any("case_overall_score_min" in reason for reason in gate["fail_reasons"])


def test_precheck_classifies_dns_error() -> None:
    exc = socket.gaierror(8, "nodename nor servname provided")
    assert eval_story._classify_precheck_error(exc) == "dns_unreachable"


def test_precheck_classifies_auth_error() -> None:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(401, request=request, text='{"error":"unauthorized"}')
    exc = httpx.HTTPStatusError("unauthorized", request=request, response=response)
    assert eval_story._classify_precheck_error(exc) == "auth_error"


def test_precheck_classifies_wrapped_auth_error() -> None:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(401, request=request, text='{"error":"unauthorized"}')
    inner = httpx.HTTPStatusError("unauthorized", request=request, response=response)
    try:
        raise eval_story.PromptCompileError(
            error_code="prompt_compile_failed",
            errors=["unauthorized"],
            notes=[],
        ) from inner
    except eval_story.PromptCompileError as wrapped:
        assert eval_story._classify_precheck_error(wrapped) == "auth_error"


def test_eval_report_shape_with_mocks(tmp_path, monkeypatch) -> None:
    suite = eval_story.PromptSuite.model_validate(
        {
            "id": "suite-test",
            "version": "test",
            "cases": [
                {
                    "id": "case-1",
                    "prompt_text": "Generate a compact emergency story.",
                    "target_minutes": 10,
                    "npc_count": 4,
                    "style": "tense",
                    "tags": ["test"],
                    "expected_tone": "urgent",
                }
            ],
        }
    )

    repo_root = Path(__file__).resolve().parents[1]
    sample_pack = json.loads((repo_root / "sample_data/story_pack_v1.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(
        eval_story,
        "_run_precheck",
        lambda: {
            "status": "ok",
            "error_type": None,
            "error": None,
            "base_url": "https://example.com/compatible-mode",
            "host": "example.com",
            "compiler_model": "judge-model",
            "compiler_attempts": 1,
            "spec_hash": "f" * 64,
        },
    )

    class _FakeGeneratorService:
        def generate_pack(self, **kwargs):  # noqa: ANN003, ANN201
            return SimpleNamespace(
                pack=sample_pack,
                pack_hash="a" * 64,
                generator_version="v3.1",
                variant_seed=kwargs.get("variant_seed"),
                palette_policy="random",
                generation_attempts=1,
                regenerate_count=0,
                spec_hash="b" * 64,
                lint_report=SimpleNamespace(ok=True, errors=[], warnings=[]),
            )

    class _FakeJudge:
        def __init__(self, *, model_override=None) -> None:
            self.model = model_override or "judge-model"

        def evaluate(self, **_kwargs):  # noqa: ANN003, ANN201
            return SimpleNamespace(
                result=StoryQualityJudgeResult.model_validate(
                    {
                        "overall_score": 8.0,
                        "playability_score": 8.0,
                        "coherence_score": 8.0,
                        "tension_curve_score": 7.8,
                        "choice_impact_score": 7.9,
                        "prompt_fidelity_score": 7.8,
                        "major_issues": [],
                        "strengths": ["consistent progression"],
                        "verdict": "pass",
                    }
                ),
                model=self.model,
                attempts=1,
                notes=[],
            )

    def _simulate(_pack, **_kwargs):  # noqa: ANN001
        return {
            "strategy": _kwargs["strategy"],
            "provider": "fake",
            "steps": 14,
            "ended": True,
            "meaningful_steps": 14,
            "fallback_steps": 1,
            "fallback_with_progress_steps": 1,
            "text_input_steps": 10,
            "llm_route_steps": 0,
            "fallback_error_steps": 0,
            "fallback_low_confidence_steps": 1,
            "transcript": [
                {
                    "step": 1,
                    "action_input": {"type": "text"},
                    "route_source": "fallback_low_confidence",
                    "scene_id": "sc1",
                    "recognized": {"move_id": "global.help_me_progress"},
                    "resolution": {"result": "partial"},
                    "meaningful_change": True,
                    "fallback_with_progress": True,
                },
                {
                    "step": 14,
                    "action_input": {"type": "text"},
                    "route_source": "fallback_low_confidence",
                    "scene_id": "sc15",
                    "recognized": {"move_id": "global.help_me_progress"},
                    "resolution": {"result": "success"},
                    "meaningful_change": True,
                    "fallback_with_progress": True,
                },
            ],
        }

    monkeypatch.setattr(eval_story, "GeneratorService", _FakeGeneratorService)
    monkeypatch.setattr(eval_story, "StoryQualityJudge", _FakeJudge)
    monkeypatch.setattr(eval_story, "simulate_pack_playthrough", _simulate)

    report = eval_story.evaluate_llm_story_generation(
        suite=suite,
        runs_per_prompt=1,
        strategies=["mixed", "text_noise", "button_random"],
        max_steps=20,
        packs_dir=tmp_path / "packs",
        artifacts_dir=tmp_path / "artifacts",
        judge_model="judge-model",
    )

    assert report["gate"]["passed"] is True
    assert report["metrics"]["generation_success_rate"] == 1.0
    assert report["metrics"]["completion_rate"] == 1.0
    assert report["metrics"]["generation_failure_breakdown"] == {}
    assert report["metrics"]["prompt_spec_invalid_field_counts"] == {}
    run_entry = report["cases"][0]["runs"][0]
    assert Path(run_entry["pack_path"]).exists()
    assert run_entry["judge"]["status"] == "ok"
    first_play = run_entry["playthroughs"][0]
    assert Path(first_play["artifact_path"]).exists()
    assert eval_story._determine_exit_code(strict=True, gate=report["gate"]) == 0


def test_strict_exit_code_failed_gate() -> None:
    gate = {"passed": False}
    assert eval_story._determine_exit_code(strict=True, gate=gate) == 1
    assert eval_story._determine_exit_code(strict=False, gate=gate) == 0


def test_eval_collects_generation_failure_breakdown_and_prompt_fields(tmp_path, monkeypatch) -> None:
    suite = eval_story.PromptSuite.model_validate(
        {
            "id": "suite-failure-test",
            "version": "test",
            "cases": [
                {
                    "id": "case-1",
                    "prompt_text": "Generate a compact emergency story.",
                    "target_minutes": 10,
                    "npc_count": 4,
                    "style": "tense",
                    "tags": ["test"],
                    "expected_tone": "urgent",
                }
            ],
        }
    )

    repo_root = Path(__file__).resolve().parents[1]
    sample_pack = json.loads((repo_root / "sample_data/story_pack_v1.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(
        eval_story,
        "_run_precheck",
        lambda: {
            "status": "ok",
            "error_type": None,
            "error": None,
            "base_url": "https://example.com/compatible-mode",
            "host": "example.com",
            "compiler_model": "judge-model",
            "compiler_attempts": 1,
            "spec_hash": "f" * 64,
        },
    )

    class _FlakyGeneratorService:
        def __init__(self) -> None:
            self.calls = 0

        def generate_pack(self, **kwargs):  # noqa: ANN003, ANN201
            self.calls += 1
            if self.calls == 1:
                raise GeneratorBuildError(
                    lint_report=LintReport(
                        errors=[
                            "1 validation error for StorySpec\npremise\n  String should have at most 400 characters"
                        ],
                        warnings=[],
                    ),
                    generation_attempts=1,
                    regenerate_count=0,
                    notes=["forced invalid spec"],
                    generator_version="v3.1",
                    variant_seed=kwargs.get("variant_seed"),
                    palette_policy="random",
                    error_code="prompt_spec_invalid",
                )
            return SimpleNamespace(
                pack=sample_pack,
                pack_hash="a" * 64,
                generator_version="v3.1",
                variant_seed=kwargs.get("variant_seed"),
                palette_policy="random",
                generation_attempts=1,
                regenerate_count=0,
                spec_hash="b" * 64,
                lint_report=SimpleNamespace(ok=True, errors=[], warnings=[]),
            )

    class _FakeJudge:
        def __init__(self, *, model_override=None) -> None:
            self.model = model_override or "judge-model"

        def evaluate(self, **_kwargs):  # noqa: ANN003, ANN201
            return SimpleNamespace(
                result=StoryQualityJudgeResult.model_validate(
                    {
                        "overall_score": 8.0,
                        "playability_score": 8.0,
                        "coherence_score": 8.0,
                        "tension_curve_score": 8.0,
                        "choice_impact_score": 8.0,
                        "prompt_fidelity_score": 8.0,
                        "major_issues": [],
                        "strengths": ["good pacing"],
                        "verdict": "pass",
                    }
                ),
                model=self.model,
                attempts=1,
                notes=[],
            )

    monkeypatch.setattr(eval_story, "GeneratorService", _FlakyGeneratorService)
    monkeypatch.setattr(eval_story, "StoryQualityJudge", _FakeJudge)
    monkeypatch.setattr(
        eval_story,
        "simulate_pack_playthrough",
        lambda _pack, **_kwargs: {
            "strategy": _kwargs["strategy"],
            "provider": "fake",
            "steps": 14,
            "ended": True,
            "meaningful_steps": 14,
            "fallback_steps": 0,
            "fallback_with_progress_steps": 0,
            "text_input_steps": 10,
            "llm_route_steps": 0,
            "fallback_error_steps": 0,
            "fallback_low_confidence_steps": 0,
            "transcript": [{"step": 1, "action_input": {"type": "text"}}],
        },
    )

    report = eval_story.evaluate_llm_story_generation(
        suite=suite,
        runs_per_prompt=2,
        strategies=["mixed"],
        max_steps=20,
        packs_dir=tmp_path / "packs",
        artifacts_dir=tmp_path / "artifacts",
        judge_model="judge-model",
    )

    assert report["gate"]["passed"] is False
    assert report["metrics"]["generation_success_rate"] == 0.5
    assert report["metrics"]["generation_failure_breakdown"]["prompt_spec_invalid"] == 1
    assert report["metrics"]["prompt_spec_invalid_field_counts"]["premise"] >= 1
    assert any("generation_success_rate" in reason for reason in report["gate"]["fail_reasons"])
    assert any("top_generation_failure=prompt_spec_invalid:1" in reason for reason in report["gate"]["fail_reasons"])
