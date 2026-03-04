from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

from rpg_backend.domain.linter import LintReport
from rpg_backend.eval.story_quality_schema import StoryQualityJudgeResult
from rpg_backend.generator.errors import GeneratorBuildError


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
        "llm_route_success_rate": 0.92,
        "step_error_rate": 0.0,
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
        "llm_route_success_rate": 0.95,
        "step_error_rate": 0.0,
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
        "llm_route_success_rate": 0.95,
        "step_error_rate": 0.0,
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

    class _FakeGeneratorPipeline:
        def run(self, **kwargs):  # noqa: ANN003, ANN201
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
            "provider": "openai",
            "steps": 14,
            "ended": True,
            "meaningful_steps": 14,
            "text_input_steps": 10,
            "llm_route_steps": 10,
            "global_help_route_steps": 6,
            "pressure_recoil_steps": 1,
            "npc_stance_mentions": 3,
            "runtime_error_steps": 0,
            "runtime_error": False,
            "runtime_error_code": None,
            "runtime_error_stage": None,
            "runtime_error_message": None,
            "transcript": [
                {
                    "step": 1,
                    "action_input": {"type": "text"},
                    "route_source": "llm",
                    "scene_id": "sc1",
                    "recognized": {"move_id": "global.help_me_progress"},
                    "resolution": {"result": "partial"},
                    "meaningful_change": True,
                },
                {
                    "step": 14,
                    "action_input": {"type": "text"},
                    "route_source": "llm",
                    "scene_id": "sc15",
                    "recognized": {"move_id": "global.help_me_progress"},
                    "resolution": {"result": "success"},
                    "meaningful_change": True,
                },
            ],
        }

    monkeypatch.setattr(eval_story, "GeneratorPipeline", _FakeGeneratorPipeline)
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
    assert report["metrics"]["global_help_route_rate"] == 0.6
    assert report["metrics"]["non_global_text_route_rate"] == 0.4
    assert report["metrics"]["strategy_triangle_coverage_rate"] > 0.0
    assert report["metrics"]["pressure_recoil_trigger_rate"] == 1.0
    assert report["metrics"]["npc_stance_mentions_per_run_avg"] == 3.0
    assert report["metrics"]["fun_score_avg"] > 0.0
    assert report["metrics"]["fun_score_case_min"] > 0.0
    assert report["metrics"]["judge_playability_avg"] > 0.0
    assert report["metrics"]["judge_choice_impact_avg"] > 0.0
    assert report["metrics"]["judge_tension_curve_avg"] > 0.0
    assert report["metrics"]["duplicate_beat_title_run_count"] == 0.0
    assert report["metrics"]["banned_move_hit_count"] == 0.0
    assert report["metrics"]["generation_failure_breakdown"] == {}
    assert report["metrics"]["prompt_spec_invalid_field_counts"] == {}
    assert report["fun_focus"]["formula"]["weights"] == eval_story.FUN_SCORE_WEIGHTS
    assert isinstance(report["fun_focus"]["warnings"], list)
    assert any("global_help_route_rate" in warning for warning in report["fun_focus"]["warnings"])
    assert any("non_global_text_route_rate" in warning for warning in report["fun_focus"]["warnings"])
    run_entry = report["cases"][0]["runs"][0]
    assert Path(run_entry["pack_path"]).exists()
    assert run_entry["judge"]["status"] == "ok"
    assert run_entry["judge"]["fun_score"] > 0.0
    assert report["cases"][0]["metrics"]["fun_score_avg"] > 0.0
    assert report["cases"][0]["metrics"]["playability_avg"] > 0.0
    assert report["cases"][0]["metrics"]["choice_impact_avg"] > 0.0
    assert report["cases"][0]["metrics"]["tension_curve_avg"] > 0.0
    first_play = run_entry["playthroughs"][0]
    assert Path(first_play["artifact_path"]).exists()
    assert eval_story._determine_exit_code(strict=True, gate=report["gate"]) == 0


def test_eval_parallel_max_workers_path(tmp_path, monkeypatch) -> None:
    suite = eval_story.PromptSuite.model_validate(
        {
            "id": "suite-parallel-test",
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
            "base_url": "http://worker.internal",
            "host": "worker.internal",
            "gateway_mode": "worker",
            "compiler_model": "judge-model",
            "compiler_attempts": 1,
            "spec_hash": "f" * 64,
        },
    )

    class _FakeGeneratorPipeline:
        def run(self, **kwargs):  # noqa: ANN003, ANN201
            variant_seed = kwargs.get("variant_seed") or "seed"
            pack_hash = f"{hash(variant_seed) & 0xFFFFFFFF:064x}"
            return SimpleNamespace(
                pack=sample_pack,
                pack_hash=pack_hash,
                generator_version="v3.3",
                variant_seed=variant_seed,
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

    monkeypatch.setattr(eval_story, "GeneratorPipeline", _FakeGeneratorPipeline)
    monkeypatch.setattr(eval_story, "StoryQualityJudge", _FakeJudge)
    monkeypatch.setattr(
        eval_story,
        "simulate_pack_playthrough",
        lambda _pack, **_kwargs: {
            "strategy": _kwargs["strategy"],
            "provider": "openai",
            "steps": 14,
            "ended": True,
            "meaningful_steps": 14,
            "text_input_steps": 10,
            "llm_route_steps": 10,
            "runtime_error_steps": 0,
            "runtime_error": False,
            "runtime_error_code": None,
            "runtime_error_stage": None,
            "runtime_error_message": None,
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
        max_workers=2,
    )

    assert report["config"]["max_workers"] == 2
    assert len(report["cases"]) == 1
    assert len(report["cases"][0]["runs"]) == 2
    assert report["metrics"]["generation_success_rate"] == 1.0


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

    class _FlakyGeneratorPipeline:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, **kwargs):  # noqa: ANN003, ANN201
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

    monkeypatch.setattr(eval_story, "GeneratorPipeline", _FlakyGeneratorPipeline)
    monkeypatch.setattr(eval_story, "StoryQualityJudge", _FakeJudge)
    monkeypatch.setattr(
        eval_story,
        "simulate_pack_playthrough",
        lambda _pack, **_kwargs: {
            "strategy": _kwargs["strategy"],
            "provider": "openai",
            "steps": 14,
            "ended": True,
            "meaningful_steps": 14,
            "text_input_steps": 10,
            "llm_route_steps": 10,
            "runtime_error_steps": 0,
            "runtime_error": False,
            "runtime_error_code": None,
            "runtime_error_stage": None,
            "runtime_error_message": None,
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


def test_compute_fun_score_weighted_formula() -> None:
    judge_payload = {
        "overall_score": 8.0,
        "playability_score": 7.0,
        "choice_impact_score": 9.0,
        "tension_curve_score": 6.0,
    }
    score = eval_story._compute_fun_score(judge_payload)
    assert abs(score - 7.8) < 1e-9


def test_gate_unchanged_with_low_fun_fields() -> None:
    metrics = {
        "generation_success_rate": 1.0,
        "pack_lint_success_rate": 1.0,
        "completion_rate": 1.0,
        "avg_steps": 15.0,
        "meaningful_accept_rate": 0.95,
        "llm_route_success_rate": 0.9,
        "step_error_rate": 0.0,
        "judge_overall_avg": 8.0,
        "fun_score_avg": 2.0,
        "fun_score_case_min": 1.0,
        "judge_playability_avg": 2.0,
        "judge_choice_impact_avg": 2.0,
        "judge_tension_curve_avg": 2.0,
        "judge_prompt_fidelity_avg": 7.5,
        "case_overall_score_min": 6.3,
        "judge_sample_count": 24.0,
        "expected_judge_sample_count": 24.0,
    }
    gate = eval_story._compute_gate(metrics)
    assert gate["passed"] is True


def test_fun_focus_report_includes_route_kpi_warnings() -> None:
    report = eval_story._build_fun_focus_report(
        {
            "fun_score_avg": 7.8,
            "fun_score_case_min": 6.8,
            "global_help_route_rate": 0.33,
            "non_global_text_route_rate": 0.41,
        }
    )
    warnings = report["warnings"]
    assert any("global_help_route_rate" in warning for warning in warnings)
    assert any("non_global_text_route_rate" in warning for warning in warnings)


def test_profile_fun_focus_defaults_applied() -> None:
    resolved = eval_story._resolve_profile_config(
        profile="fun_focus",
        suite_file=None,
        runs_per_prompt=None,
        strategies=None,
        max_steps=None,
        strict=None,
    )
    assert resolved["suite_file"] == eval_story.DEFAULT_FUN_FOCUS_SUITE_FILE
    assert resolved["runs_per_prompt"] == 2
    assert resolved["strategies"] == "mixed"
    assert resolved["max_steps"] == 20
    assert resolved["strict"] is True


def test_profile_fun_focus_respects_explicit_overrides() -> None:
    resolved = eval_story._resolve_profile_config(
        profile="fun_focus",
        suite_file="custom_suite.json",
        runs_per_prompt=3,
        strategies="mixed,text_noise",
        max_steps=30,
        strict=False,
    )
    assert resolved["suite_file"] == "custom_suite.json"
    assert resolved["runs_per_prompt"] == 3
    assert resolved["strategies"] == "mixed,text_noise"
    assert resolved["max_steps"] == 30
    assert resolved["strict"] is False


def test_fun_suite_file_has_12_cases_and_valid_case_ids() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    full_payload = json.loads((repo_root / "eval_data/prompt_suite_v1.json").read_text(encoding="utf-8"))
    fun_payload = json.loads((repo_root / "eval_data/prompt_suite_fun_v1.json").read_text(encoding="utf-8"))

    full_suite = eval_story.PromptSuite.model_validate(full_payload)
    fun_suite = eval_story.PromptSuite.model_validate(fun_payload)

    assert fun_suite.id == "prompt_suite_fun_v1"
    assert len(fun_suite.cases) == 12
    full_ids = {case.id for case in full_suite.cases}
    fun_ids = [case.id for case in fun_suite.cases]
    assert len(set(fun_ids)) == 12
    assert set(fun_ids).issubset(full_ids)
