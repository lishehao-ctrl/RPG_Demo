from __future__ import annotations

from rpg_backend.domain.constants import (
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
)
from rpg_backend.generator.author_workflow_models import AuthorMemory, BeatDraft, BeatOverviewContext, BeatPrefixSummary, StoryOverview
from rpg_backend.generator.author_workflow_planner import check_beat_blueprints, plan_beat_blueprints_from_overview
from rpg_backend.generator.author_workflow_validators import (
    build_author_memory,
    build_structured_prefix_summary,
    check_story_overview,
    lint_beat_draft,
    project_overview_for_beat_generation,
)


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


def _valid_beat_draft(blueprint) -> BeatDraft:
    return BeatDraft.model_validate(
        {
            "beat_id": blueprint.beat_id,
            "title": blueprint.title,
            "objective": blueprint.objective,
            "conflict": blueprint.conflict,
            "required_event": blueprint.required_event,
            "entry_scene_id": blueprint.entry_scene_id,
            "present_npcs": ["Mara", "Rook"],
            "events_produced": [blueprint.required_event],
            "scenes": [
                {
                    "id": blueprint.entry_scene_id,
                    "beat_id": blueprint.beat_id,
                    "scene_seed": blueprint.scene_intent,
                    "present_npcs": ["Mara", "Rook"],
                    "enabled_moves": [f"{blueprint.beat_id}.a", f"{blueprint.beat_id}.b", f"{blueprint.beat_id}.c"],
                    "always_available_moves": [
                        GLOBAL_CLARIFY_MOVE_ID,
                        GLOBAL_LOOK_MOVE_ID,
                        GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
                    ],
                    "exit_conditions": [],
                    "is_terminal": False,
                }
            ],
            "moves": [
                {
                    "id": f"{blueprint.beat_id}.a",
                    "label": "A",
                    "strategy_style": "fast_dirty",
                    "intents": ["a"],
                    "synonyms": [],
                    "args_schema": {},
                    "resolution_policy": "prefer_success",
                    "outcomes": [
                        {"id": f"{blueprint.beat_id}.a.s", "result": "success", "preconditions": [], "effects": [], "next_scene_id": None, "narration_slots": {"npc_reaction": "x", "world_shift": "x", "clue_delta": "x", "cost_delta": "x", "next_hook": "x"}},
                        {"id": f"{blueprint.beat_id}.a.f", "result": "fail_forward", "preconditions": [], "effects": [], "next_scene_id": None, "narration_slots": {"npc_reaction": "x", "world_shift": "x", "clue_delta": "x", "cost_delta": "x", "next_hook": "x"}},
                    ],
                },
                {
                    "id": f"{blueprint.beat_id}.b",
                    "label": "B",
                    "strategy_style": "steady_slow",
                    "intents": ["b"],
                    "synonyms": [],
                    "args_schema": {},
                    "resolution_policy": "prefer_success",
                    "outcomes": [
                        {"id": f"{blueprint.beat_id}.b.s", "result": "success", "preconditions": [], "effects": [], "next_scene_id": None, "narration_slots": {"npc_reaction": "x", "world_shift": "x", "clue_delta": "x", "cost_delta": "x", "next_hook": "x"}},
                        {"id": f"{blueprint.beat_id}.b.f", "result": "fail_forward", "preconditions": [], "effects": [], "next_scene_id": None, "narration_slots": {"npc_reaction": "x", "world_shift": "x", "clue_delta": "x", "cost_delta": "x", "next_hook": "x"}},
                    ],
                },
                {
                    "id": f"{blueprint.beat_id}.c",
                    "label": "C",
                    "strategy_style": "political_safe_resource_heavy",
                    "intents": ["c"],
                    "synonyms": [],
                    "args_schema": {},
                    "resolution_policy": "prefer_success",
                    "outcomes": [
                        {"id": f"{blueprint.beat_id}.c.s", "result": "success", "preconditions": [], "effects": [], "next_scene_id": None, "narration_slots": {"npc_reaction": "x", "world_shift": "x", "clue_delta": "x", "cost_delta": "x", "next_hook": "x"}},
                        {"id": f"{blueprint.beat_id}.c.f", "result": "fail_forward", "preconditions": [], "effects": [], "next_scene_id": None, "narration_slots": {"npc_reaction": "x", "world_shift": "x", "clue_delta": "x", "cost_delta": "x", "next_hook": "x"}},
                    ],
                },
            ],
        }
    )


def test_check_story_overview_accepts_valid_overview() -> None:
    assert check_story_overview(_overview()) == []


def test_plan_beat_blueprints_are_deterministic_and_valid() -> None:
    blueprints = plan_beat_blueprints_from_overview(_overview())
    assert len(blueprints) == 4
    assert check_beat_blueprints(blueprints) == []


def test_lint_beat_draft_rejects_missing_fail_forward() -> None:
    overview = _overview()
    blueprint = plan_beat_blueprints_from_overview(overview)[0]
    draft = _valid_beat_draft(blueprint)
    draft.moves[0].outcomes = draft.moves[0].outcomes[:1]
    report = lint_beat_draft(overview=overview, blueprint=blueprint, draft=draft, prior_beats=[])
    assert report.ok is False
    assert any("fail_forward" in err for err in report.errors)


def test_lint_beat_draft_ignores_missing_strategy_styles_as_soft_constraint() -> None:
    overview = _overview()
    blueprint = plan_beat_blueprints_from_overview(overview)[0]
    draft = _valid_beat_draft(blueprint)
    draft.moves[2].strategy_style = "steady_slow"

    report = lint_beat_draft(overview=overview, blueprint=blueprint, draft=draft, prior_beats=[])

    assert report.ok is True
    assert report.errors == []
    assert report.warnings == []


def test_project_overview_for_beat_generation_trims_fields() -> None:
    projected = project_overview_for_beat_generation(_overview())
    assert isinstance(projected, BeatOverviewContext)
    payload = projected.model_dump(mode="json")
    assert "target_minutes" not in payload
    assert "npc_count" not in payload
    assert all("motivation" not in item for item in payload["npc_roster"])


def test_build_structured_prefix_summary_mentions_prior_ids() -> None:
    overview = _overview()
    blueprints = plan_beat_blueprints_from_overview(overview)
    summary = build_structured_prefix_summary([_valid_beat_draft(blueprints[0]), _valid_beat_draft(blueprints[1])])
    assert isinstance(summary, BeatPrefixSummary)
    assert [item.beat_id for item in summary.completed_beats] == ["b1", "b2"]


def test_build_author_memory_summarizes_recent_beats() -> None:
    overview = _overview()
    blueprints = plan_beat_blueprints_from_overview(overview)
    memory = build_author_memory([_valid_beat_draft(blueprints[0]), _valid_beat_draft(blueprints[1])])
    assert isinstance(memory, AuthorMemory)
    assert memory.beat_count == 2
    assert [item.beat_id for item in memory.recent_beats] == ["b1", "b2"]
    assert "Mara" in memory.active_npcs
    assert "b1.milestone" in memory.unresolved_threads
