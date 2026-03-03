from __future__ import annotations

import json
from pathlib import Path

from rpg_backend.domain.linter import lint_story_pack
from rpg_backend.generator.prompt_compiler import PromptCompileError, PromptCompileResult
from rpg_backend.generator.spec_schema import StorySpec
from rpg_backend.generator.service import GeneratorBuildError
from rpg_backend.generator.versioning import GENERATOR_VERSION

PACK_PATH = Path("sample_data/story_pack_v1.json")


def _sample_pack() -> dict:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


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
                    "red_line": "Never cut hospital access to stabilize industry.",
                },
                {
                    "name": "Rook",
                    "role": "security lead",
                    "motivation": "protect civilians",
                    "red_line": "No civilian corridor can be abandoned for pace.",
                },
                {
                    "name": "Sera",
                    "role": "operations analyst",
                    "motivation": "preserve evidence",
                    "red_line": "No telemetry wipe even under command pressure.",
                },
                {
                    "name": "Director Vale",
                    "role": "command authority",
                    "motivation": "retain control",
                    "red_line": "Public command legitimacy cannot collapse.",
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


def test_story_create_publish_get_flow(client) -> None:
    pack = _sample_pack()

    created = client.post("/stories", json={"title": "Demo", "pack_json": pack})
    assert created.status_code == 200
    body = created.json()
    story_id = body["story_id"]
    assert body["status"] == "draft"

    published = client.post(f"/stories/{story_id}/publish", json={})
    assert published.status_code == 200
    pub_body = published.json()
    assert pub_body["version"] == 1

    fetched = client.get(f"/stories/{story_id}?version=1")
    assert fetched.status_code == 200
    get_body = fetched.json()
    assert get_body["story_id"] == story_id
    assert get_body["version"] == 1
    assert get_body["pack"] == pack


def test_publish_rejects_invalid_pack(client) -> None:
    invalid_pack = _sample_pack()
    invalid_pack["moves"][0]["outcomes"] = [
        out for out in invalid_pack["moves"][0]["outcomes"] if out["result"] != "fail_forward"
    ]

    created = client.post("/stories", json={"title": "Invalid", "pack_json": invalid_pack})
    story_id = created.json()["story_id"]

    published = client.post(f"/stories/{story_id}/publish", json={})
    assert published.status_code == 422


def test_generate_story_success_without_publish(client) -> None:
    response = client.post(
        "/stories/generate",
        json={
            "seed_text": "Signal collapse in a city reactor.",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["story_id"]
    assert body["version"] is None
    assert body["generation_mode"] == "seed"
    assert body["pack_hash"]
    assert body["generator_version"] == GENERATOR_VERSION
    assert body["variant_seed"]
    assert body["palette_policy"] == "random"
    assert "errors" in body["lint_report"]
    assert "warnings" in body["lint_report"]
    assert isinstance(body["generation_attempts"], int)
    assert isinstance(body["regenerate_count"], int)
    assert isinstance(body["notes"], list)
    assert "attempts" not in body
    assert "repair_notes" not in body
    report = lint_story_pack(body["pack"])
    assert report.ok, report.errors


def test_generate_story_success_with_publish(client) -> None:
    response = client.post(
        "/stories/generate",
        json={
            "seed_text": "Contain the reactor signal.",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["story_id"]
    assert body["version"] >= 1
    assert body["generation_mode"] == "seed"
    assert body["pack_hash"]
    assert body["generator_version"] == GENERATOR_VERSION
    assert body["variant_seed"]


def test_generate_with_variant_seed_is_reproducible(client) -> None:
    payload = {
        "seed_text": "Deterministic run",
        "target_minutes": 10,
        "npc_count": 4,
        "variant_seed": "fixed-seed-1",
        "palette_policy": "random",
        "publish": False,
    }
    first = client.post("/stories/generate", json=payload)
    second = client.post("/stories/generate", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()
    assert first_body["pack_hash"] == second_body["pack_hash"]
    assert first_body["generator_version"] == second_body["generator_version"] == GENERATOR_VERSION
    assert first_body["variant_seed"] == second_body["variant_seed"] == "fixed-seed-1"


def test_generate_without_variant_seed_returns_actual_seed(client) -> None:
    response = client.post(
        "/stories/generate",
        json={
            "seed_text": "No explicit variant",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["variant_seed"], str)
    assert body["variant_seed"]
    assert body["pack_hash"]
    assert body["generator_version"] == GENERATOR_VERSION


def test_generate_rejects_unsupported_generator_version(client) -> None:
    response = client.post(
        "/stories/generate",
        json={
            "seed_text": "version mismatch",
            "target_minutes": 10,
            "npc_count": 4,
            "generator_version": "v99.0",
            "publish": False,
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "unsupported_generator_version" in detail["errors"][0]
    assert detail["generator_version"] == GENERATOR_VERSION


def test_generate_story_unrepairable_returns_422(client, monkeypatch) -> None:
    from rpg_backend.api import stories as stories_api
    from rpg_backend.domain.linter import LintReport

    def _always_fail(*args, **kwargs):
        raise GeneratorBuildError(
            LintReport(errors=["forced failure"], warnings=[]),
            generation_attempts=4,
            regenerate_count=3,
            notes=["forced"],
            generator_version=GENERATOR_VERSION,
            variant_seed="forced-seed",
            palette_policy="random",
            error_code="generation_failed_after_regenerates",
        )

    monkeypatch.setattr(stories_api.GeneratorService, "generate_pack", _always_fail)
    response = client.post(
        "/stories/generate",
        json={
            "seed_text": "broken seed",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": False,
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "generation_failed_after_regenerates"
    assert detail["errors"] == ["forced failure"]
    assert detail["generation_attempts"] == 4
    assert detail["regenerate_count"] == 3
    assert detail["notes"] == ["forced"]
    assert "attempts" not in detail
    assert "repair_notes" not in detail
    assert detail["generator_version"] == GENERATOR_VERSION
    assert detail["variant_seed"] == "forced-seed"
    assert detail["palette_policy"] == "random"


def test_generate_story_prompt_mode_success_without_publish(client, monkeypatch) -> None:
    sample_spec = _sample_story_spec()
    monkeypatch.setattr(
        "rpg_backend.generator.service.PromptCompiler.compile",
        lambda *args, **kwargs: PromptCompileResult(
            spec=sample_spec,
            spec_hash="a" * 64,
            model="test-generator-model",
            attempts=1,
            notes=["prompt compiler mocked"],
        ),
    )

    response = client.post(
        "/stories/generate",
        json={
            "prompt_text": "Generate a reactor crisis story with a pyrrhic ending.",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["generation_mode"] == "prompt"
    assert body["version"] is None
    assert body["spec_hash"] == "a" * 64
    assert body["spec_summary"]
    report = lint_story_pack(body["pack"])
    assert report.ok, report.errors


def test_generate_story_prompt_mode_success_with_publish(client, monkeypatch) -> None:
    sample_spec = _sample_story_spec()
    monkeypatch.setattr(
        "rpg_backend.generator.service.PromptCompiler.compile",
        lambda *args, **kwargs: PromptCompileResult(
            spec=sample_spec,
            spec_hash="b" * 64,
            model="test-generator-model",
            attempts=1,
            notes=["prompt compiler mocked"],
        ),
    )

    response = client.post(
        "/stories/generate",
        json={
            "prompt_text": "Generate a fast, high-pressure containment story.",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["generation_mode"] == "prompt"
    assert body["version"] >= 1
    assert body["spec_hash"] == "b" * 64


def test_generate_story_rejects_empty_prompt_and_seed(client) -> None:
    response = client.post(
        "/stories/generate",
        json={
            "seed_text": "   ",
            "prompt_text": "   ",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": False,
        },
    )
    assert response.status_code == 422


def test_generate_story_prompt_compile_failure_422(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "rpg_backend.generator.service.PromptCompiler.compile",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PromptCompileError(
                error_code="prompt_compile_failed",
                errors=["upstream timeout"],
                notes=["prompt compiler failed after retries"],
            )
        ),
    )
    response = client.post(
        "/stories/generate",
        json={
            "prompt_text": "generate from prompt",
            "target_minutes": 10,
            "npc_count": 4,
            "publish": False,
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error_code"] == "prompt_compile_failed"
    assert detail["errors"] == ["upstream timeout"]
    assert "prompt compiler failed after retries" in detail["notes"]
    assert any(note.startswith("generation_mode=prompt") for note in detail["notes"])
