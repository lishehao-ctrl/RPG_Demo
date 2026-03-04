from __future__ import annotations

import pytest

from rpg_backend.domain.constants import GLOBAL_MOVE_IDS
from rpg_backend.domain.linter import LintReport, lint_story_pack
from rpg_backend.domain.move_library import MOVE_LIBRARY
from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.generator.errors import GeneratorBuildError
from rpg_backend.generator.pipeline import GeneratorPipeline
from rpg_backend.generator.prompt_compiler import PromptCompileError, PromptCompileResult
from rpg_backend.generator.spec_schema import StorySpec
from rpg_backend.generator.versioning import GENERATOR_VERSION
from rpg_backend.runtime.service import RuntimeService
from tests.helpers.providers import DeterministicProvider


def _sample_story_spec() -> StorySpec:
    return StorySpec.model_validate(
        {
            "title": "Signal Rift Protocol",
            "premise": "A city control signal fractures during peak load, forcing an improvised response team into a contested core.",
            "tone": "tense but pragmatic techno-thriller",
            "stakes": "If containment fails, the district grid collapses before dawn.",
            "beats": [
                {
                    "title": "Fault Ignition",
                    "objective": "Identify the true source of the signal split",
                    "conflict": "Conflicting telemetry and political interference",
                    "required_event": "b1.root_cause_locked",
                },
                {
                    "title": "Checkpoint Friction",
                    "objective": "Cross secured corridors to reach the control spine",
                    "conflict": "Security lockdown and public panic",
                    "required_event": "b2.lockdown_rerouted",
                },
                {
                    "title": "Core Arbitration",
                    "objective": "Reconcile rival control plans in the core chamber",
                    "conflict": "Competing priorities split the team",
                    "required_event": "b3.command_resolution",
                },
                {
                    "title": "Dawn Commit",
                    "objective": "Execute irreversible stabilization sequence",
                    "conflict": "Resource depletion and shrinking time window",
                    "required_event": "b4.final_commit",
                },
            ],
            "npcs": [
                {
                    "name": "Mara",
                    "role": "field engineer",
                    "motivation": "prevent systemic collapse",
                    "red_line": "Never cut power to hospitals to protect industrial sectors.",
                    "conflict_tags": ["anti_noise"],
                },
                {
                    "name": "Rook",
                    "role": "security lead",
                    "motivation": "protect civilians",
                    "red_line": "No plan may strand evacuees behind checkpoints.",
                    "conflict_tags": ["anti_speed"],
                },
                {
                    "name": "Sera",
                    "role": "operations analyst",
                    "motivation": "preserve evidence",
                    "red_line": "No destruction of telemetry logs under political pressure.",
                    "conflict_tags": ["anti_noise"],
                },
                {
                    "name": "Director Vale",
                    "role": "command authority",
                    "motivation": "retain control",
                    "red_line": "Public command legitimacy cannot collapse on my watch.",
                    "conflict_tags": ["anti_resource_burn"],
                },
            ],
            "scene_constraints": [
                "Open with concrete damage and immediate objective framing.",
                "Escalate pressure with checkpoints and contradictory orders.",
                "Force a costly compromise to retain momentum.",
                "Converge to final resolution with one decisive tradeoff.",
            ],
            "move_bias": ["technical", "investigate", "social"],
            "ending_shape": "pyrrhic",
        }
    )


def test_generate_pack_passes_linter() -> None:
    result = GeneratorPipeline().run(
        seed_text="A fractured city signal",
        target_minutes=10,
        npc_count=4,
        style=None,
    )
    assert result.lint_report.ok, result.lint_report.errors
    pack = result.pack
    assert 14 <= len(pack["scenes"]) <= 16
    for scene in pack["scenes"]:
        assert 4 <= len(scene["enabled_moves"]) <= 5
        assert 2 <= len(scene["always_available_moves"]) <= 3
        assert set(scene["always_available_moves"]).issubset(GLOBAL_MOVE_IDS)
        move_style_map = {move["id"]: move["strategy_style"] for move in pack["moves"]}
        scene_styles = {
            move_style_map[move_id]
            for move_id in scene["enabled_moves"]
            if move_id in move_style_map and not move_id.startswith("global.")
        }
        assert {
            "fast_dirty",
            "steady_slow",
            "political_safe_resource_heavy",
        }.issubset(scene_styles)

    for move in pack["moves"]:
        assert any(outcome["result"] == "fail_forward" for outcome in move["outcomes"])
        assert move["strategy_style"] in {
            "fast_dirty",
            "steady_slow",
            "political_safe_resource_heavy",
        }
    assert len(pack["npc_profiles"]) == len(pack["npcs"])
    for profile in pack["npc_profiles"]:
        assert profile["name"] in pack["npcs"]
        assert isinstance(profile["red_line"], str)
        assert profile["red_line"].strip()
        assert isinstance(profile["conflict_tags"], list)
        assert profile["conflict_tags"]
    assert result.pack_hash
    assert result.generator_version == GENERATOR_VERSION
    assert result.variant_seed
    assert result.palette_policy == "random"


def test_move_library_size_and_fail_forward_palette_coverage() -> None:
    assert 15 <= len(MOVE_LIBRARY) <= 20
    for template in MOVE_LIBRARY:
        assert len(template.outcome_palette_ids["success"]) >= 2
        assert len(template.outcome_palette_ids["fail_forward"]) >= 2
        assert isinstance(template.args_schema, dict)


def test_generate_pack_pacing_reaches_terminal_14_16() -> None:
    generated = GeneratorPipeline().run(
        seed_text="Contain the reactor breach",
        target_minutes=10,
        npc_count=4,
    )
    pack = StoryPack.model_validate(generated.pack)
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    steps = 0
    ended = False
    while steps < 30:
        steps += 1
        result = runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "forward"},
        )
        scene_id = result["scene_id"]
        beat_index = result["beat_index"]
        ended = bool(result["ended"])
        if ended:
            break

    assert ended
    assert 14 <= steps <= 16


def test_lint_first_pass_success_has_no_regenerate() -> None:
    result = GeneratorPipeline().run(
        seed_text="first pass should lint",
        target_minutes=10,
        npc_count=4,
        variant_seed="regen-base-seed",
    )
    assert result.lint_report.ok
    assert result.generation_attempts == 1
    assert result.regenerate_count == 0
    assert result.variant_seed == "regen-base-seed"


def test_first_lint_fail_then_second_attempt_succeeds(monkeypatch) -> None:
    import rpg_backend.generator.candidate_executor as candidate_module

    original_lint = candidate_module.lint_story_pack
    calls = {"count": 0}

    def _lint_once_then_pass(pack: dict) -> LintReport:
        calls["count"] += 1
        if calls["count"] == 1:
            return LintReport(errors=["forced lint fail"], warnings=[])
        return original_lint(pack)

    monkeypatch.setattr(candidate_module, "lint_story_pack", _lint_once_then_pass)

    result = GeneratorPipeline().run(
        seed_text="force second attempt",
        target_minutes=10,
        npc_count=4,
        variant_seed="regen-seed",
    )
    assert result.lint_report.ok
    assert result.generation_attempts == 2
    assert result.regenerate_count == 1
    assert result.variant_seed == "regen-seed#regen1"
    assert calls["count"] >= 2


def test_all_regenerates_fail_returns_last_lint_report(monkeypatch) -> None:
    import rpg_backend.generator.candidate_executor as candidate_module

    monkeypatch.setattr(
        candidate_module,
        "lint_story_pack",
        lambda _: LintReport(errors=["always bad"], warnings=["forced warning"]),
    )
    with pytest.raises(GeneratorBuildError) as exc_info:
        GeneratorPipeline().run(
            seed_text="always fail lint",
            target_minutes=10,
            npc_count=4,
            variant_seed="regen-loop",
        )
    exc = exc_info.value
    assert exc.error_code == "generation_failed_after_regenerates"
    assert exc.generation_attempts == 4
    assert exc.regenerate_count == 3
    assert exc.variant_seed == "regen-loop#regen3"
    assert exc.lint_report.errors == ["always bad"]
    assert exc.lint_report.warnings == ["forced warning"]


def test_prompt_mode_lint_fail_recompiles_each_attempt_with_derived_seed(monkeypatch) -> None:
    import rpg_backend.generator.candidate_executor as candidate_module

    sample_spec = _sample_story_spec()
    seen: list[tuple[int, str | None]] = []

    def _fake_compile(*args, **kwargs) -> PromptCompileResult:
        seen.append((kwargs.get("attempt_index"), kwargs.get("attempt_seed")))
        attempt_index = int(kwargs.get("attempt_index") or 0)
        return PromptCompileResult(
            spec=sample_spec,
            spec_hash=f"{attempt_index + 1:064x}",
            model="test-generator-model",
            attempts=1,
            notes=["prompt compiler mocked"],
        )

    monkeypatch.setattr("rpg_backend.generator.pipeline.PromptCompiler.compile", _fake_compile)
    monkeypatch.setattr(
        candidate_module,
        "lint_story_pack",
        lambda _: LintReport(errors=["forced prompt lint fail"], warnings=[]),
    )

    with pytest.raises(GeneratorBuildError) as exc_info:
        GeneratorPipeline().run(
            prompt_text="force prompt regenerate",
            target_minutes=10,
            npc_count=4,
            variant_seed="prompt-base",
        )
    exc = exc_info.value
    assert exc.error_code == "generation_failed_after_regenerates"
    assert exc.generation_attempts == 4
    assert exc.regenerate_count == 3
    assert seen == [
        (0, "prompt-base"),
        (1, "prompt-base#regen1"),
        (2, "prompt-base#regen2"),
        (3, "prompt-base#regen3"),
    ]


def test_same_seed_10_generations_quality_target() -> None:
    pipeline = GeneratorPipeline()
    steps: list[int] = []
    palette_ids: set[str] = set()

    for _ in range(10):
        generated = pipeline.run(
            seed_text="same-seed-quality-check",
            target_minutes=10,
            npc_count=4,
        )
        report = lint_story_pack(generated.pack)
        assert report.ok, report.errors

        for move in generated.pack["moves"]:
            for outcome in move["outcomes"]:
                parts = outcome["id"].split(".")
                if len(parts) >= 3:
                    palette_ids.add(parts[-1])

        pack = StoryPack.model_validate(generated.pack)
        runtime = RuntimeService(DeterministicProvider())
        scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)
        ended = False
        step_count = 0
        while step_count < 30:
            step_count += 1
            result = runtime.process_step(
                pack,
                current_scene_id=scene_id,
                beat_index=beat_index,
                state=state,
                beat_progress=beat_progress,
                action_input={"type": "text", "text": "help me progress"},
            )
            scene_id = result["scene_id"]
            beat_index = result["beat_index"]
            ended = bool(result["ended"])
            if ended:
                break

        assert ended
        steps.append(step_count)

    assert len(steps) == 10
    assert all(14 <= count <= 16 for count in steps)
    assert 14 <= (sum(steps) / len(steps)) <= 16
    assert len(palette_ids) >= 5


def test_pack_hash_stability_for_same_seed_variant() -> None:
    pipeline = GeneratorPipeline()
    kwargs = {
        "seed_text": "reproducible hash",
        "target_minutes": 10,
        "npc_count": 4,
        "style": "fast",
        "variant_seed": "stable-42",
        "palette_policy": "random",
    }
    first = pipeline.run(**kwargs)
    second = pipeline.run(**kwargs)
    assert first.pack_hash == second.pack_hash
    assert first.pack == second.pack
    assert first.generator_version == second.generator_version == GENERATOR_VERSION
    assert first.variant_seed == second.variant_seed == "stable-42"


def test_palette_policy_fixed_vs_balanced_changes_distribution() -> None:
    pipeline = GeneratorPipeline()
    fixed = pipeline.run(
        seed_text="palette policy compare",
        target_minutes=10,
        npc_count=4,
        variant_seed="policy-seed",
        palette_policy="fixed",
    )
    balanced = pipeline.run(
        seed_text="palette policy compare",
        target_minutes=10,
        npc_count=4,
        variant_seed="policy-seed",
        palette_policy="balanced",
    )
    assert fixed.pack_hash != balanced.pack_hash

    def _palette_counts(pack: dict) -> dict[str, int]:
        counts: dict[str, int] = {}
        for move in pack["moves"]:
            for outcome in move["outcomes"]:
                parts = outcome["id"].split(".")
                if len(parts) >= 3:
                    pid = parts[-1]
                    counts[pid] = counts.get(pid, 0) + 1
        return counts

    fixed_counts = _palette_counts(fixed.pack)
    balanced_counts = _palette_counts(balanced.pack)
    assert fixed_counts != balanced_counts


def test_prompt_mode_generates_lint_ok_pack(monkeypatch) -> None:
    sample_spec = _sample_story_spec()
    monkeypatch.setattr(
        "rpg_backend.generator.pipeline.PromptCompiler.compile",
        lambda *args, **kwargs: PromptCompileResult(
            spec=sample_spec,
            spec_hash="abc123" * 10 + "abcd",
            model="test-generator-model",
            attempts=1,
            notes=["prompt compiler mocked"],
        ),
    )

    result = GeneratorPipeline().run(
        prompt_text="Generate a tense reactor incident story",
        target_minutes=10,
        npc_count=4,
        style=None,
    )
    assert result.generation_mode == "prompt"
    assert result.spec_hash
    assert result.spec_summary
    assert result.lint_report.ok, result.lint_report.errors


def test_prompt_mode_pacing_reaches_terminal_14_16(monkeypatch) -> None:
    sample_spec = _sample_story_spec()
    monkeypatch.setattr(
        "rpg_backend.generator.pipeline.PromptCompiler.compile",
        lambda *args, **kwargs: PromptCompileResult(
            spec=sample_spec,
            spec_hash="def456" * 10 + "def4",
            model="test-generator-model",
            attempts=1,
            notes=["prompt compiler mocked"],
        ),
    )

    generated = GeneratorPipeline().run(
        prompt_text="Generate a techno-thriller with hard tradeoffs",
        target_minutes=10,
        npc_count=4,
    )
    pack = StoryPack.model_validate(generated.pack)
    runtime = RuntimeService(DeterministicProvider())
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)

    steps = 0
    ended = False
    while steps < 30:
        steps += 1
        result = runtime.process_step(
            pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input={"type": "text", "text": "help me progress"},
        )
        scene_id = result["scene_id"]
        beat_index = result["beat_index"]
        ended = bool(result["ended"])
        if ended:
            break

    assert ended
    assert 14 <= steps <= 16


def test_prompt_compile_failure_returns_generator_error(monkeypatch) -> None:
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

    try:
        GeneratorPipeline().run(
            prompt_text="Create a story from this prompt",
            target_minutes=10,
            npc_count=4,
        )
    except GeneratorBuildError as exc:
        assert getattr(exc, "error_code") == "prompt_compile_failed"
        assert getattr(exc, "lint_report").errors == ["upstream timeout"]
    else:
        raise AssertionError("expected GeneratorBuildError for prompt compile failure")


def test_prompt_compile_failure_does_not_fallback_to_seed_planner(monkeypatch) -> None:
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
    monkeypatch.setattr(
        "rpg_backend.generator.pipeline.plan_beats",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("seed planner should not be used when prompt compile fails")
        ),
    )

    with pytest.raises(GeneratorBuildError) as exc_info:
        GeneratorPipeline().run(
            prompt_text="Create a story from this prompt",
            target_minutes=10,
            npc_count=4,
        )
    assert exc_info.value.error_code == "prompt_compile_failed"


def test_prompt_spec_invalid_returns_generator_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "rpg_backend.generator.pipeline.PromptCompiler.compile",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PromptCompileError(
                error_code="prompt_spec_invalid",
                errors=["beats must contain 3-5 items"],
                notes=["prompt compiler schema validation failed"],
            )
        ),
    )

    try:
        GeneratorPipeline().run(
            prompt_text="A very short malformed prompt",
            target_minutes=10,
            npc_count=4,
        )
    except GeneratorBuildError as exc:
        assert getattr(exc, "error_code") == "prompt_spec_invalid"
        assert getattr(exc, "lint_report").errors == ["beats must contain 3-5 items"]
    else:
        raise AssertionError("expected GeneratorBuildError for invalid prompt spec")


def test_candidate_parallelism_can_select_non_primary_candidate(monkeypatch) -> None:
    import rpg_backend.generator.candidate_executor as candidate_module

    sample_spec = _sample_story_spec()
    monkeypatch.setattr(
        "rpg_backend.generator.pipeline.PromptCompiler.compile",
        lambda *args, **kwargs: PromptCompileResult(
            spec=sample_spec,
            spec_hash="c" * 64,
            model="test-generator-model",
            attempts=1,
            notes=["prompt compiler mocked"],
        ),
    )

    original_build_candidate = candidate_module.build_candidate

    def _fake_build_candidate(**kwargs):  # noqa: ANN003, ANN201
        candidate_seed = kwargs["candidate_seed"]
        built = original_build_candidate(**kwargs)
        ok = candidate_seed.endswith("#cand1")
        lint = LintReport(errors=[] if ok else ["forced candidate lint fail"], warnings=[])
        return candidate_module.CandidateBuildResult(
            candidate_index=0,
            candidate_seed=candidate_seed,
            pack=built.pack,
            lint_report=lint,
        )

    monkeypatch.setattr(
        candidate_module,
        "build_candidate",
        _fake_build_candidate,
    )

    result = GeneratorPipeline().run(
        prompt_text="Generate in candidate parallel mode",
        target_minutes=10,
        npc_count=4,
        variant_seed="parallel-seed",
        candidate_parallelism=3,
    )
    assert result.lint_report.ok
    assert result.generation_attempts == 1
    assert result.regenerate_count == 0
    assert result.variant_seed.endswith("#cand1")
