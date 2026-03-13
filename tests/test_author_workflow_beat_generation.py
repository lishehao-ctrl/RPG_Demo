from __future__ import annotations

import asyncio

import pytest

from rpg_backend.config.settings import Settings
from rpg_backend.domain.constants import GLOBAL_CLARIFY_MOVE_ID, GLOBAL_HELP_ME_PROGRESS_MOVE_ID, GLOBAL_LOOK_MOVE_ID
from rpg_backend.domain.linter import lint_story_pack
from rpg_backend.generator.author_workflow_assembler import assemble_story_pack
from rpg_backend.generator.author_workflow_chains import BeatGenerationChain, StoryOverviewChain
from rpg_backend.generator.author_workflow_errors import PromptCompileError
from rpg_backend.generator.author_workflow_models import BeatBlueprint, BeatOutlineLLM, StoryOverview
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy, get_author_workflow_policy
from rpg_backend.generator.author_workflow_normalizer import materialize_beat_outline, select_story_move_template_ids
from rpg_backend.generator.author_workflow_planner import plan_beat_blueprints_from_overview
from rpg_backend.generator.author_workflow_validators import (
    build_author_memory,
    build_structured_prefix_summary,
    project_overview_for_beat_generation,
)
from rpg_backend.generator.outcome_materialization import PALETTE_IDS_BY_RESULT, build_outcome_from_palette_id


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


def _outline_draft() -> BeatOutlineLLM:
    return BeatOutlineLLM.model_validate(
        {
            "present_npcs": ["Mara", "Rook"],
            "events_produced": ["b1.signal_locked"],
            "scene_plans": [
                {
                    "scene_seed": "Open in the shaking control room.",
                    "present_npcs": ["Mara", "Rook"],
                    "is_terminal": False,
                },
                {
                    "scene_seed": "Shift to a narrower technical corridor.",
                    "present_npcs": ["Mara", "Sera"],
                    "is_terminal": False,
                },
            ],
            "move_surfaces": [
                {
                    "label": "Force a fast response",
                    "intents": ["rush the breach"],
                    "synonyms": ["rush", "force it"],
                    "roleplay_examples": [
                        "I cut the feeder and force the relay live right now.",
                        "I override the lockout and reroute power by hand.",
                    ],
                },
                {
                    "label": "Hold the line carefully",
                    "intents": ["stabilize the room"],
                    "synonyms": ["steady", "careful"],
                    "roleplay_examples": [
                        "I check each relay in order and keep the team calm.",
                        "I stabilize the panel step by step before we touch anything else.",
                    ],
                },
                {
                    "label": "Use the official safe path",
                    "intents": ["take the careful official route"],
                    "synonyms": ["official", "safe path"],
                    "roleplay_examples": [
                        "I follow protocol and reserve power for the hospital grid.",
                        "I call the safe route and document every tradeoff aloud.",
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
    calls = {"count": 0, "timeout_seconds": None, "user_payload": None}

    async def _fake_invoke_chain(self, *, system_prompt: str, user_payload: dict[str, object], timeout_seconds: float | None = None):  # noqa: ANN001, ANN202
        del system_prompt
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
    assert chain.max_retries == 1


def test_materialize_beat_outline_injects_strategy_triangle() -> None:
    draft = materialize_beat_outline(
        overview_context=project_overview_for_beat_generation(_overview()),
        blueprint=_blueprint(),
        outline=_outline_draft(),
    )
    scene_move_ids = set(draft.scenes[0].enabled_moves)
    move_styles = {move.strategy_style for move in draft.moves if move.id in scene_move_ids}
    assert move_styles == {
        "fast_dirty",
        "steady_slow",
        "political_safe_resource_heavy",
    }


def test_materialize_beat_outline_injects_fixed_global_moves() -> None:
    draft = materialize_beat_outline(
        overview_context=project_overview_for_beat_generation(_overview()),
        blueprint=_blueprint(),
        outline=_outline_draft(),
    )
    assert draft.scenes[0].always_available_moves == [
        GLOBAL_CLARIFY_MOVE_ID,
        GLOBAL_LOOK_MOVE_ID,
        GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
    ]


def test_materialize_beat_outline_uses_llm_move_surface_text() -> None:
    draft = materialize_beat_outline(
        overview_context=project_overview_for_beat_generation(_overview()),
        blueprint=_blueprint(),
        outline=_outline_draft(),
    )

    assert [move.label for move in draft.moves] == [
        "Force a fast response",
        "Hold the line carefully",
        "Use the official safe path",
    ]
    assert "rush the breach" in draft.moves[0].intents
    assert "safe path" in draft.moves[2].synonyms
    assert "I cut the feeder and force the relay live right now." in draft.moves[0].intents
    assert "I follow protocol and reserve power for the hospital grid." in draft.moves[2].synonyms


def test_outline_move_surface_rejects_placeholder_labels() -> None:
    payload = _outline_draft().model_dump(mode="json")
    payload["move_surfaces"][0]["label"] = "Fast Dirty Surface"

    with pytest.raises(ValueError, match="concrete action"):
        BeatOutlineLLM.model_validate(payload)


def test_materialize_beat_outline_adds_progression_exit_conditions() -> None:
    draft = materialize_beat_outline(
        overview_context=project_overview_for_beat_generation(_overview()),
        blueprint=_blueprint(),
        outline=_outline_draft(),
    )
    assert [condition.model_dump(mode="json") for condition in draft.scenes[0].exit_conditions] == [
        {
            "id": "b1.sc1.progress",
            "condition_kind": "beat_progress_gte",
            "key": "b1",
            "value": 1,
            "next_scene_id": "b1.sc2",
            "end_story": False,
        }
    ]
    assert draft.scenes[1].exit_conditions == []


def test_assembled_outline_pack_preserves_scene_reachability() -> None:
    overview = _overview()
    overview_context = project_overview_for_beat_generation(overview)
    blueprints = plan_beat_blueprints_from_overview(overview)
    roster = [npc.name for npc in overview.npc_roster]

    drafts = [
        materialize_beat_outline(
            overview_context=overview_context,
            blueprint=blueprint,
            outline=BeatOutlineLLM.model_validate(
                {
                    "present_npcs": [
                        roster[index % len(roster)],
                        roster[(index + 1) % len(roster)],
                    ],
                    "events_produced": [blueprint.required_event],
                    "move_surfaces": [
                        {
                            "label": f"{blueprint.title} fast push",
                            "intents": ["force momentum"],
                            "synonyms": ["rush"],
                            "roleplay_examples": [
                                "I force momentum before the grid slips any further.",
                                "I rush the unstable lane and push through the risk.",
                            ],
                        },
                        {
                            "label": f"{blueprint.title} careful hold",
                            "intents": ["stabilize carefully"],
                            "synonyms": ["steady"],
                            "roleplay_examples": [
                                "I steady the line and check each failure point in order.",
                                "I slow the room down and stabilize it carefully.",
                            ],
                        },
                        {
                            "label": f"{blueprint.title} safe official route",
                            "intents": ["protect legitimacy"],
                            "synonyms": ["official"],
                            "roleplay_examples": [
                                "I keep the public side calm and protect the official route.",
                                "I spend the reserves where they preserve legitimacy.",
                            ],
                        },
                    ],
                    "scene_plans": [
                        {
                            "scene_seed": f"{blueprint.scene_intent} Opening frame.",
                            "present_npcs": [
                                roster[index % len(roster)],
                                roster[(index + 1) % len(roster)],
                            ],
                            "is_terminal": False,
                        },
                        {
                            "scene_seed": f"{blueprint.scene_intent} Consequence frame.",
                            "present_npcs": [
                                roster[index % len(roster)],
                                roster[(index + 1) % len(roster)],
                            ],
                            "is_terminal": False,
                        },
                    ],
                }
            ),
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


def test_outline_template_selection_is_deterministic_and_style_complete() -> None:
    template_ids = select_story_move_template_ids(
        overview_context=project_overview_for_beat_generation(_overview()),
        blueprint=_blueprint(),
        outline=_outline_draft(),
    )

    assert len(template_ids) == 3
    assert len(set(template_ids)) == 3


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


def test_beat_generation_chain_makes_single_gateway_call_per_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    invalid_payload = {"present_npcs": ["Mara"], "events_produced": [], "scene_plans": [], "move_surfaces": []}
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
            chain.compile_outline(
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


def test_beat_generation_chain_payload_uses_last_accepted_beat_and_structured_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_invoke_chain(self, *, system_prompt: str, user_payload: dict[str, object], timeout_seconds: float | None = None):  # noqa: ANN001, ANN202
        captured["system_prompt"] = system_prompt
        captured["user_payload"] = dict(user_payload)
        captured["timeout_seconds"] = timeout_seconds
        return type("R", (), {"payload": _outline_draft().model_dump(mode="json"), "attempts": 1})()

    monkeypatch.setattr(BeatGenerationChain, "_invoke_chain", _fake_invoke_chain)
    chain = BeatGenerationChain(policy=AuthorWorkflowPolicy(max_attempts=3, timeout_seconds=7.0))
    prior = materialize_beat_outline(
        overview_context=project_overview_for_beat_generation(_overview()),
        blueprint=_blueprint(),
        outline=_outline_draft(),
    )
    _ = asyncio.run(
        chain.compile_outline(
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
    assert "author_memory" in payload
    assert "last_accepted_beat" in payload
    assert payload["last_accepted_beat"]["beat_id"] == "b1"
    assert "scenes" not in payload["last_accepted_beat"]
    assert "moves" not in payload["last_accepted_beat"]
    assert "scene_plans" in payload["output_schema"]["properties"]
    assert "move_surfaces" in payload["output_schema"]["properties"]
    assert "prior_beats" not in payload
