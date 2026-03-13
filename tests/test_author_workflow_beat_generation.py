from __future__ import annotations

import asyncio

import pytest

from rpg_backend.config.settings import Settings
from rpg_backend.domain.constants import (
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
)
from rpg_backend.domain.linter import lint_story_pack
from rpg_backend.generator.author_workflow_assembler import assemble_story_pack
from rpg_backend.generator.author_workflow_chains import BeatGenerationChain, StoryOverviewChain
from rpg_backend.generator.author_workflow_errors import PromptCompileError
from rpg_backend.generator.author_workflow_models import BeatBlueprint, BeatDraft, StoryOverview
from rpg_backend.generator.author_workflow_planner import plan_beat_blueprints_from_overview
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy, get_author_workflow_policy
from rpg_backend.generator.author_workflow_validators import (
    build_author_memory,
    build_structured_prefix_summary,
    lint_beat_draft,
    project_overview_for_beat_generation,
)
from rpg_backend.generator.outcome_materialization import PALETTE_IDS_BY_RESULT, build_outcome_from_palette_id


_FIXED_GLOBAL_MOVES = [
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
]


def _overview() -> StoryOverview:
    return StoryOverview.model_validate(
        {
            "title": "Signal Rift Protocol",
            "premise": "A city control signal fractures during peak load, forcing an improvised response team into a contested core.",
            "tone": "tense but pragmatic techno-thriller",
            "stakes": "If containment fails, the district grid collapses before dawn.",
            "target_minutes": 10,
            "npc_count": 4,
            "ending_shape": "pyrrhic",
            "npc_roster": [
                {"name": "Mara", "role": "engineer", "motivation": "stabilize", "red_line": "No false telemetry.", "conflict_tags": ["anti_noise"]},
                {"name": "Rook", "role": "security", "motivation": "protect", "red_line": "No civilian abandonment.", "conflict_tags": ["anti_speed"]},
                {"name": "Sera", "role": "analyst", "motivation": "preserve evidence", "red_line": "No telemetry wipe.", "conflict_tags": ["anti_noise"]},
                {"name": "Vale", "role": "director", "motivation": "retain control", "red_line": "No legitimacy collapse.", "conflict_tags": ["anti_resource_burn"]},
            ],
            "move_bias": ["technical", "investigate", "social"],
            "scene_constraints": ["One", "Two", "Three", "Four"],
        }
    )


def _blueprint() -> BeatBlueprint:
    return BeatBlueprint.model_validate(
        {
            "beat_id": "b1",
            "title": "Opening Pressure",
            "objective": "Advance opening pressure",
            "conflict": "Conflicting telemetry and public pressure.",
            "required_event": "b1.milestone",
            "step_budget": 4,
            "npc_quota": 2,
            "entry_scene_id": "b1.sc1",
            "scene_intent": "Stress the control room under rising uncertainty.",
        }
    )


def _beat_draft(*, blueprint: BeatBlueprint | None = None, first_npc: str = "Mara", second_npc: str = "Rook") -> BeatDraft:
    selected_blueprint = blueprint or _blueprint()
    move_ids = [
        f"{selected_blueprint.beat_id}.m1",
        f"{selected_blueprint.beat_id}.m2",
        f"{selected_blueprint.beat_id}.m3",
    ]
    scene_ids = [selected_blueprint.entry_scene_id, f"{selected_blueprint.beat_id}.sc2"]
    present_npcs = [first_npc, second_npc]
    return BeatDraft.model_validate(
        {
            "beat_id": selected_blueprint.beat_id,
            "title": selected_blueprint.title,
            "objective": selected_blueprint.objective,
            "conflict": selected_blueprint.conflict,
            "required_event": selected_blueprint.required_event,
            "entry_scene_id": selected_blueprint.entry_scene_id,
            "present_npcs": present_npcs,
            "events_produced": [selected_blueprint.required_event],
            "scenes": [
                {
                    "id": scene_ids[0],
                    "beat_id": selected_blueprint.beat_id,
                    "scene_seed": f"{selected_blueprint.scene_intent} Opening frame.",
                    "present_npcs": present_npcs,
                    "enabled_moves": move_ids,
                    "always_available_moves": list(_FIXED_GLOBAL_MOVES),
                    "exit_conditions": [
                        {
                            "id": f"{scene_ids[0]}.progress",
                            "condition_kind": "beat_progress_gte",
                            "key": selected_blueprint.beat_id,
                            "value": 1,
                            "next_scene_id": scene_ids[1],
                            "end_story": False,
                        }
                    ],
                    "is_terminal": False,
                },
                {
                    "id": scene_ids[1],
                    "beat_id": selected_blueprint.beat_id,
                    "scene_seed": f"{selected_blueprint.scene_intent} Consequence frame.",
                    "present_npcs": present_npcs,
                    "enabled_moves": move_ids,
                    "always_available_moves": list(_FIXED_GLOBAL_MOVES),
                    "exit_conditions": [],
                    "is_terminal": False,
                },
            ],
            "moves": [
                {
                    "id": move_ids[0],
                    "label": "Force a fast response",
                    "strategy_style": "fast_dirty",
                    "intents": ["rush the breach"],
                    "synonyms": ["rush"],
                    "args_schema": {},
                    "resolution_policy": "prefer_success",
                    "outcomes": [
                        {
                            "id": f"{move_ids[0]}.success",
                            "result": "success",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They flinch, then surge with you.",
                                "world_shift": "The control room jolts forward.",
                                "clue_delta": "You expose the unstable feeder path.",
                                "cost_delta": "The noise floor spikes.",
                                "next_hook": "A narrower corridor opens up.",
                            },
                        },
                        {
                            "id": f"{move_ids[0]}.partial",
                            "result": "partial",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They follow, but with visible doubt.",
                                "world_shift": "The room moves, unevenly.",
                                "clue_delta": "You learn just enough to keep going.",
                                "cost_delta": "The system takes a rough hit.",
                                "next_hook": "The corridor ahead is already compromised.",
                            },
                        },
                        {
                            "id": f"{move_ids[0]}.fail_forward",
                            "result": "fail_forward",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They resist, then scramble after you.",
                                "world_shift": "The room gets harsher anyway.",
                                "clue_delta": "You still identify the failure lane.",
                                "cost_delta": "Trust slips as the surge worsens.",
                                "next_hook": "You have to stabilize deeper in the core.",
                            },
                        },
                    ],
                },
                {
                    "id": move_ids[1],
                    "label": "Hold the line carefully",
                    "strategy_style": "steady_slow",
                    "intents": ["stabilize the room"],
                    "synonyms": ["steady"],
                    "args_schema": {},
                    "resolution_policy": "prefer_success",
                    "outcomes": [
                        {
                            "id": f"{move_ids[1]}.success",
                            "result": "success",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They match your pace and focus.",
                                "world_shift": "The line steadies under pressure.",
                                "clue_delta": "The pattern becomes legible.",
                                "cost_delta": "Time pressure grows.",
                                "next_hook": "A harder compromise waits ahead.",
                            },
                        },
                        {
                            "id": f"{move_ids[1]}.partial",
                            "result": "partial",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They nod, but keep glancing at the clock.",
                                "world_shift": "The room steadies only in patches.",
                                "clue_delta": "You isolate part of the cause.",
                                "cost_delta": "Momentum leaks away.",
                                "next_hook": "Someone higher up starts issuing orders.",
                            },
                        },
                        {
                            "id": f"{move_ids[1]}.fail_forward",
                            "result": "fail_forward",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They hesitate but stay with you.",
                                "world_shift": "The room stays unstable.",
                                "clue_delta": "You get a partial technical read.",
                                "cost_delta": "The delay costs you slack.",
                                "next_hook": "The next scene inherits the instability.",
                            },
                        },
                    ],
                },
                {
                    "id": move_ids[2],
                    "label": "Use the official safe path",
                    "strategy_style": "political_safe_resource_heavy",
                    "intents": ["protect legitimacy"],
                    "synonyms": ["official"],
                    "args_schema": {},
                    "resolution_policy": "prefer_success",
                    "outcomes": [
                        {
                            "id": f"{move_ids[2]}.success",
                            "result": "success",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They accept the official cover.",
                                "world_shift": "Resources reroute to buy safety.",
                                "clue_delta": "You gain institutional leverage.",
                                "cost_delta": "The reserves start to thin.",
                                "next_hook": "The safe path creates a new debt.",
                            },
                        },
                        {
                            "id": f"{move_ids[2]}.partial",
                            "result": "partial",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They comply, reluctantly.",
                                "world_shift": "The room calms, but only on paper.",
                                "clue_delta": "You preserve some cover and some clarity.",
                                "cost_delta": "The budget line starts to hurt.",
                                "next_hook": "The next decision will expose the price.",
                            },
                        },
                        {
                            "id": f"{move_ids[2]}.fail_forward",
                            "result": "fail_forward",
                            "preconditions": [],
                            "effects": [],
                            "next_scene_id": scene_ids[1],
                            "narration_slots": {
                                "npc_reaction": "They wince at the political bill.",
                                "world_shift": "The system absorbs a costly delay.",
                                "clue_delta": "You keep legitimacy but lose slack.",
                                "cost_delta": "Resources burn to hold the line.",
                                "next_hook": "The next beat inherits the compromise.",
                            },
                        },
                    ],
                },
            ],
        }
    )


def test_author_workflow_policy_defaults_are_converged() -> None:
    policy = get_author_workflow_policy()
    assert policy.max_attempts == 3
    assert policy.timeout_seconds == 20.0
    assert policy.llm_call_max_retries == 1
    assert "author_workflow_node_timeout_seconds" not in Settings.model_fields
    assert "author_workflow_node_retry_count" not in Settings.model_fields
    assert "llm_openai_generator_timeout_seconds" not in Settings.model_fields
    assert "llm_openai_pack_repair_timeout_seconds" not in Settings.model_fields
    assert "generator_candidate_parallelism" not in Settings.model_fields


def test_story_overview_chain_makes_single_gateway_call_per_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid = _overview().model_dump(mode="json")
    invalid["npc_roster"][1]["conflict_tags"] = ["technical"]
    calls = {"count": 0, "timeout_seconds": None, "user_payload": None, "system_prompt": None}

    async def _fake_invoke_chain(self, *, system_prompt: str, user_payload: dict[str, object], timeout_seconds: float | None = None):  # noqa: ANN001, ANN202
        calls["system_prompt"] = system_prompt
        calls["count"] += 1
        calls["timeout_seconds"] = timeout_seconds
        calls["user_payload"] = dict(user_payload)
        return type("R", (), {"payload": invalid, "attempts": 1})()

    monkeypatch.setattr(StoryOverviewChain, "_invoke_chain", _fake_invoke_chain)
    chain = StoryOverviewChain(policy=AuthorWorkflowPolicy(max_attempts=3, timeout_seconds=12.5))
    with pytest.raises(PromptCompileError) as exc_info:
        asyncio.run(chain.compile(raw_brief="reactor brief"))
    assert exc_info.value.error_code == "overview_invalid"
    assert calls["count"] == 1
    assert calls["timeout_seconds"] == 12.5
    assert "validation_feedback" not in calls["user_payload"]
    assert "# Soft Goals" in calls["system_prompt"]
    assert "recur across multiple beats" in calls["system_prompt"]
    assert chain.max_retries == 1


def test_direct_beat_generation_chain_makes_single_gateway_call_per_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid_payload = {"beat_id": "b1", "title": "bad", "objective": "bad", "conflict": "bad"}
    calls = {"count": 0, "timeout_seconds": None, "user_payload": None}

    async def _fake_invoke_chain(self, *, system_prompt: str, user_payload: dict[str, object], timeout_seconds: float | None = None):  # noqa: ANN001, ANN202
        del system_prompt
        calls["count"] += 1
        calls["timeout_seconds"] = timeout_seconds
        calls["user_payload"] = dict(user_payload)
        return type("R", (), {"payload": invalid_payload, "attempts": 1})()

    monkeypatch.setattr(BeatGenerationChain, "_invoke_chain", _fake_invoke_chain)
    chain = BeatGenerationChain(policy=AuthorWorkflowPolicy(max_attempts=3, timeout_seconds=9.5))
    with pytest.raises(PromptCompileError) as exc_info:
        asyncio.run(
            chain.compile_beat(
                story_id="story-1",
                overview_context=project_overview_for_beat_generation(_overview()),
                blueprint=_blueprint().model_dump(mode="json"),
                last_accepted_beat=None,
                prefix_summary=build_structured_prefix_summary([]),
                lint_feedback=[],
            )
        )
    assert exc_info.value.error_code == "beat_invalid"
    assert calls["count"] == 1
    assert calls["timeout_seconds"] == 9.5
    assert "validation_feedback" not in calls["user_payload"]
    assert chain.max_retries == 1


def test_direct_beat_generation_chain_payload_uses_last_accepted_beat_and_structured_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_invoke_chain(self, *, system_prompt: str, user_payload: dict[str, object], timeout_seconds: float | None = None):  # noqa: ANN001, ANN202
        captured["system_prompt"] = system_prompt
        captured["user_payload"] = dict(user_payload)
        captured["timeout_seconds"] = timeout_seconds
        return type("R", (), {"payload": _beat_draft().model_dump(mode="json"), "attempts": 1})()

    monkeypatch.setattr(BeatGenerationChain, "_invoke_chain", _fake_invoke_chain)
    chain = BeatGenerationChain(policy=AuthorWorkflowPolicy(max_attempts=3, timeout_seconds=7.0))
    prior = _beat_draft()
    _ = asyncio.run(
        chain.compile_beat(
            story_id="story-1",
            overview_context=project_overview_for_beat_generation(_overview()),
            blueprint=_blueprint().model_dump(mode="json"),
            last_accepted_beat=prior.model_dump(mode="json"),
            prefix_summary=build_structured_prefix_summary([prior]),
            author_memory=build_author_memory([prior]),
            lint_feedback=[],
        )
    )

    payload = captured["user_payload"]
    assert captured["timeout_seconds"] == 7.0
    assert "overview_context" in payload
    assert set(payload["overview_context"].keys()) == {
        "premise",
        "stakes",
        "tone",
        "ending_shape",
        "move_bias",
        "npc_roster",
        "scene_constraints",
    }
    assert "title" not in payload["overview_context"]
    assert "validation_feedback" not in payload
    assert "prefix_summary" in payload
    assert list(payload["prefix_summary"].keys()) == ["completed_beats"]
    assert payload["fixed_global_moves"] == _FIXED_GLOBAL_MOVES
    assert payload["id_rules"]["entry_scene_id"] == "b1.sc1"
    assert payload["id_rules"]["move_ids"] == ["b1.m1", "b1.m2", "b1.m3"]
    assert "author_memory" in payload
    assert "last_accepted_beat" in payload
    assert payload["last_accepted_beat"]["beat_id"] == "b1"
    assert "scenes" not in payload["last_accepted_beat"]
    assert "moves" not in payload["last_accepted_beat"]
    assert "scenes" in payload["output_schema"]["properties"]
    assert "moves" in payload["output_schema"]["properties"]
    assert "# Hard Constraints" in captured["system_prompt"]
    assert "always_available_moves exactly as" in captured["system_prompt"]
    assert "Use exactly three local moves" in captured["system_prompt"]


def test_direct_beat_lint_rejects_wrong_global_move_set() -> None:
    payload = _beat_draft().model_dump(mode="json")
    payload["scenes"][0]["always_available_moves"] = [GLOBAL_CLARIFY_MOVE_ID, GLOBAL_LOOK_MOVE_ID]
    draft = BeatDraft.model_validate(payload)

    report = lint_beat_draft(
        overview=_overview(),
        blueprint=_blueprint(),
        draft=draft,
        prior_beats=[],
    )

    assert not report.ok
    assert "fixed global always_available_moves" in report.errors[0]


def test_assembled_direct_pack_preserves_scene_reachability() -> None:
    overview = _overview()
    blueprints = plan_beat_blueprints_from_overview(overview)
    roster = [npc.name for npc in overview.npc_roster]

    drafts = [
        _beat_draft(
            blueprint=blueprint,
            first_npc=roster[index % len(roster)],
            second_npc=roster[(index + 1) % len(roster)],
        )
        for index, blueprint in enumerate(blueprints)
    ]

    pack = assemble_story_pack(
        story_id="story-1",
        overview=overview,
        beat_blueprints=blueprints,
        beat_drafts=drafts,
    )
    report = lint_story_pack(pack)

    assert not any("unreachable scenes from entry" in err for err in report.errors), report.errors


def test_outcome_builder_matches_shared_palette_logic() -> None:
    built = build_outcome_from_palette_id(
        move_id="b1.m1",
        outcome_index=0,
        result="success",
        palette_id=PALETTE_IDS_BY_RESULT["success"][0],
        strategy_style="fast_dirty",
        next_scene_id=None,
    )
    assert built["effects"]
    assert built["narration_slots"]["cost_delta"]
