from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rpg_backend.application.author_runs.service import AuthorWorkflowService
from rpg_backend.application.author_runs.workflow_graph import build_author_workflow_graph
from rpg_backend.application.author_runs.workflow_topology import (
    WORKFLOW_CONDITIONAL_ROUTES,
    WORKFLOW_LINEAR_EDGES,
)
from rpg_backend.application.author_runs.workflow_state import build_initial_author_workflow_state
from rpg_backend.application.author_runs.workflow_vocabulary import (
    AUTHOR_WORKFLOW_NODE_ALL,
    AuthorWorkflowErrorCode,
    AuthorWorkflowEventType,
    AuthorWorkflowNode,
    AuthorWorkflowStatus,
)
from rpg_backend.domain.constants import (
    GLOBAL_CLARIFY_MOVE_ID,
    GLOBAL_HELP_ME_PROGRESS_MOVE_ID,
    GLOBAL_LOOK_MOVE_ID,
)
from rpg_backend.generator.author_workflow_errors import PromptCompileError
from rpg_backend.generator.author_workflow_models import BeatDraft, StoryOverview
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy, get_author_workflow_policy


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
FRONTEND_ROOT = REPO_ROOT / "frontend"


ACTIVE_DOC_FORBIDDEN_MARKERS = {
    "-> repair_pack",
    "repair_pack ->",
    "schema-feedback retry",
    "schema feedback retry",
    "author_workflow_node_timeout_seconds",
    "author_workflow_node_retry_count",
    "llm_openai_pack_repair_timeout_seconds",
    "Regenerate loop (strict mode)",
    "generation.{attempts,regenerate_count,candidate_parallelism,attempt_history}",
    "prompt_text?, seed_text?, target_minutes, npc_count, style?, publish?",
}


def _sample_overview() -> StoryOverview:
    return StoryOverview.model_validate(
        {
            "title": "Signal Rift Protocol",
            "premise": "A city control signal fractures during peak load, forcing an improvised response team into a contested core.",
            "tone": "tense but pragmatic techno-thriller",
            "stakes": "If containment fails, the district grid collapses before dawn.",
            "target_minutes": 10,
            "npc_count": 4,
            "ending_shape": "pyrrhic",
            "ending_shape_note": "The district gets through the crisis, but authority and infrastructure come out visibly damaged.",
            "npc_roster": [
                {"name": "Mara", "role": "engineer", "motivation": "stabilize", "red_line": "No false telemetry.", "conflict_tags": ["anti_noise"], "pressure_signature": "Demands exactness and turns biting when people round off bad data."},
                {"name": "Rook", "role": "security", "motivation": "protect", "red_line": "No civilian abandonment.", "conflict_tags": ["anti_speed"], "pressure_signature": "Pushes back hard whenever speed threatens orderly evacuation."},
                {"name": "Sera", "role": "analyst", "motivation": "preserve evidence", "red_line": "No telemetry wipe.", "conflict_tags": ["anti_noise"], "pressure_signature": "Treats evidence loss as a moral failure, not just an operational one."},
                {"name": "Vale", "role": "director", "motivation": "retain control", "red_line": "No legitimacy collapse.", "conflict_tags": ["anti_resource_burn"], "pressure_signature": "Sees every emergency expense as a political weakness someone else will exploit."},
            ],
            "move_bias": ["technical", "investigate", "social"],
            "move_bias_note": "The core motion should come from diagnosis, inquiry, and negotiated cooperation under stress.",
            "scene_constraints": ["One", "Two", "Three", "Four"],
        }
    )


class _RetryingOverviewChain:
    attempts = 0

    async def compile(self, *, raw_brief: str, timeout_seconds: float | None = None) -> StoryOverview:
        del raw_brief, timeout_seconds
        _RetryingOverviewChain.attempts += 1
        if _RetryingOverviewChain.attempts == 1:
            raise PromptCompileError(
                error_code=AuthorWorkflowErrorCode.PROMPT_COMPILE_FAILED,
                errors=["temporary gateway failure"],
                notes=["retry in graph"],
            )
        return _sample_overview()


class _FakeBeatChain:
    async def compile_beat(
        self,
        *,
        story_id: str,
        overview_context: dict | object,
        blueprint: dict,
        last_accepted_beat: dict | None,
        prefix_summary: dict | object,
        author_memory: dict | object | None = None,
        lint_feedback: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> BeatDraft:
        del story_id, overview_context, last_accepted_beat, prefix_summary, author_memory, lint_feedback, timeout_seconds
        move_ids = [
            f"{blueprint['beat_id']}.m1",
            f"{blueprint['beat_id']}.m2",
            f"{blueprint['beat_id']}.m3",
        ]
        return BeatDraft.model_validate(
            {
                "beat_id": blueprint["beat_id"],
                "title": blueprint["title"],
                "objective": blueprint["objective"],
                "conflict": blueprint["conflict"],
                "required_event": blueprint["required_event"],
                "entry_scene_id": blueprint["entry_scene_id"],
                "present_npcs": ["Mara", "Rook"],
                "events_produced": [blueprint["required_event"]],
                "scenes": [
                    {
                        "id": blueprint["entry_scene_id"],
                        "beat_id": blueprint["beat_id"],
                        "scene_seed": blueprint["scene_intent"],
                        "present_npcs": ["Mara", "Rook"],
                        "enabled_moves": move_ids,
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
                        "id": move_ids[0],
                        "label": "Push fast through the breach",
                        "strategy_style": "fast_dirty",
                        "intents": ["rush ahead"],
                        "synonyms": ["rush"],
                        "args_schema": {},
                        "outcomes": [
                            {
                                "id": f"{move_ids[0]}.success",
                                "result": "success",
                                "preconditions": [],
                                "effects": [],
                                "next_scene_id": None,
                                "narration_slots": {
                                    "npc_reaction": "They push through the breach.",
                                    "world_shift": "The breach gives way.",
                                    "clue_delta": "You spot the weak relay.",
                                    "cost_delta": "The surge gets louder.",
                                    "next_hook": "Someone shouts from deeper in the core.",
                                },
                            },
                            {
                                "id": f"{move_ids[0]}.fail_forward",
                                "result": "fail_forward",
                                "preconditions": [],
                                "effects": [],
                                "next_scene_id": None,
                                "narration_slots": {
                                    "npc_reaction": "They flinch but follow.",
                                    "world_shift": "The room gets harsher.",
                                    "clue_delta": "You still learn where the breach leads.",
                                    "cost_delta": "You lose more margin.",
                                    "next_hook": "The next choice arrives fast.",
                                },
                            },
                        ],
                    },
                    {
                        "id": move_ids[1],
                        "label": "Stabilize the corridor carefully",
                        "strategy_style": "steady_slow",
                        "intents": ["move carefully"],
                        "synonyms": ["steady"],
                        "args_schema": {},
                        "outcomes": [
                            {
                                "id": f"{move_ids[1]}.success",
                                "result": "success",
                                "preconditions": [],
                                "effects": [],
                                "next_scene_id": None,
                                "narration_slots": {
                                    "npc_reaction": "They match your careful pace.",
                                    "world_shift": "The corridor steadies.",
                                    "clue_delta": "The failure pattern comes into focus.",
                                    "cost_delta": "Time keeps slipping.",
                                    "next_hook": "A harder tradeoff waits ahead.",
                                },
                            },
                            {
                                "id": f"{move_ids[1]}.fail_forward",
                                "result": "fail_forward",
                                "preconditions": [],
                                "effects": [],
                                "next_scene_id": None,
                                "narration_slots": {
                                    "npc_reaction": "They hesitate, then commit.",
                                    "world_shift": "The corridor remains unstable.",
                                    "clue_delta": "You get a partial readout.",
                                    "cost_delta": "Pressure builds on the team.",
                                    "next_hook": "You still have to choose a side.",
                                },
                            },
                        ],
                    },
                    {
                        "id": move_ids[2],
                        "label": "Take the official safe route",
                        "strategy_style": "political_safe_resource_heavy",
                        "intents": ["take the careful official route"],
                        "synonyms": ["official"],
                        "args_schema": {},
                        "outcomes": [
                            {
                                "id": f"{move_ids[2]}.success",
                                "result": "success",
                                "preconditions": [],
                                "effects": [],
                                "next_scene_id": None,
                                "narration_slots": {
                                    "npc_reaction": "They accept the official cover.",
                                    "world_shift": "Resources shift into the corridor.",
                                    "clue_delta": "The command picture sharpens.",
                                    "cost_delta": "The reserves thin out.",
                                    "next_hook": "The official path creates a new debt.",
                                },
                            },
                            {
                                "id": f"{move_ids[2]}.fail_forward",
                                "result": "fail_forward",
                                "preconditions": [],
                                "effects": [],
                                "next_scene_id": None,
                                "narration_slots": {
                                    "npc_reaction": "They wince at the political price.",
                                    "world_shift": "The system absorbs a costly delay.",
                                    "clue_delta": "You keep legitimacy but lose slack.",
                                    "cost_delta": "The resource burn is obvious.",
                                    "next_hook": "The next beat inherits the bill.",
                                },
                            },
                        ],
                    },
                ],
            }
        )


def test_topology_excludes_repair_pack_and_final_lint_targets_are_terminal_only() -> None:
    routed_nodes = set().union(*WORKFLOW_CONDITIONAL_ROUTES.values())
    all_known_nodes = set(AUTHOR_WORKFLOW_NODE_ALL) | routed_nodes

    assert "repair_pack" not in all_known_nodes
    assert WORKFLOW_CONDITIONAL_ROUTES[AuthorWorkflowNode.FINAL_LINT] == {
        AuthorWorkflowNode.REVIEW_READY,
        AuthorWorkflowNode.WORKFLOW_FAILED,
    }
    assert (AuthorWorkflowNode.ASSEMBLE_STORY_PACK, AuthorWorkflowNode.NORMALIZE_STORY_PACK) in WORKFLOW_LINEAR_EDGES


def test_author_workflow_service_uses_single_policy_factory_source() -> None:
    service = AuthorWorkflowService()
    assert service.policy_factory is get_author_workflow_policy


def test_graph_assembly_module_is_thin_and_uses_split_modules() -> None:
    source = (REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "workflow_graph.py").read_text(encoding="utf-8")

    assert "from rpg_backend.application.author_runs.workflow_nodes import build_workflow_nodes" in source
    assert "from rpg_backend.application.author_runs.workflow_routes import build_workflow_routes" in source
    assert "from rpg_backend.application.author_runs.workflow_retry import" in source
    assert "workflow_topology import" in source

    forbidden_markers = {
        "def route_after_",
        "def plan_beats(",
        "def beat_lint(",
        "def generate_story_overview(",
        "asyncio.wait_for(",
    }
    for marker in forbidden_markers:
        assert marker not in source, f"workflow_graph.py should stay assembly-only; found marker: {marker}"


def test_workflow_split_modules_exist() -> None:
    expected = {
        REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "workflow_nodes.py",
        REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "workflow_routes.py",
        REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "workflow_retry.py",
        REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "workflow_topology.py",
        REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "workflow_artifacts.py",
        REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "beat_context_builder.py",
    }
    missing = [path for path in expected if not path.exists()]
    assert not missing, "missing required workflow split modules:\n" + "\n".join(
        sorted(path.relative_to(REPO_ROOT).as_posix() for path in missing)
    )


def test_legacy_outline_normalizer_module_is_removed_from_active_backend() -> None:
    assert not (REPO_ROOT / "rpg_backend" / "generator" / "author_workflow_normalizer.py").exists()


def test_active_backend_runtime_has_no_outline_materialize_imports() -> None:
    scan_paths = [
        REPO_ROOT / "rpg_backend" / "application" / "author_runs" / "workflow_nodes.py",
        REPO_ROOT / "rpg_backend" / "generator" / "author_workflow_models.py",
        REPO_ROOT / "rpg_backend" / "generator" / "author_workflow_chains.py",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "runtime_status.md",
    ]
    forbidden_markers = {
        "BeatOutline",
        "materialize_beat_outline",
        "compile_outline",
        "outline -> materialize",
        "overview/outline",
    }
    violations: list[str] = []
    for path in scan_paths:
        content = path.read_text(encoding="utf-8")
        for marker in forbidden_markers:
            if marker in content:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: '{marker}'")

    assert not violations, "outline/materialize legacy markers found in active backend runtime paths:\n" + "\n".join(
        sorted(violations)
    )


def test_retry_events_are_owned_by_graph_wrapper() -> None:
    _RetryingOverviewChain.attempts = 0
    recorded_events: list[tuple[str, str, dict]] = []

    async def _mark_started(run_id: str, node_name: str, payload_json: dict | None) -> None:
        del run_id
        recorded_events.append((AuthorWorkflowEventType.NODE_STARTED, node_name, dict(payload_json or {})))

    async def _record_event(run_id: str, node_name: str, event_type: str, payload_json: dict | None) -> None:
        del run_id
        recorded_events.append((event_type, node_name, dict(payload_json or {})))

    async def _run() -> dict:
        graph = build_author_workflow_graph(
            overview_chain_factory=_RetryingOverviewChain,
            beat_chain_factory=_FakeBeatChain,
            policy=AuthorWorkflowPolicy(max_attempts=3, timeout_seconds=20.0),
            mark_run_node_started=_mark_started,
            record_run_node_event=_record_event,
        )
        initial_state = build_initial_author_workflow_state(story_id="story-1", run_id="run-1", raw_brief="brief")
        final_state = initial_state
        async for mode, payload in graph.astream(initial_state, stream_mode=["updates", "values"]):
            if mode == "values":
                final_state = payload
        return final_state

    final_state = asyncio.run(_run())

    retry_events = [event for event in recorded_events if event[0] == AuthorWorkflowEventType.NODE_RETRY]
    assert final_state["status"] == AuthorWorkflowStatus.REVIEW_READY
    assert _RetryingOverviewChain.attempts == 2
    assert len(retry_events) == 1
    assert retry_events[0][1] == AuthorWorkflowNode.GENERATE_STORY_OVERVIEW
    assert retry_events[0][2]["reason"] == AuthorWorkflowErrorCode.PROMPT_COMPILE_FAILED


def test_active_docs_do_not_drift_to_legacy_author_workflow_semantics() -> None:
    scan_paths = [REPO_ROOT / "README.md", *sorted(DOCS_ROOT.glob("*.md"))]
    violations: list[str] = []

    for path in scan_paths:
        content = path.read_text(encoding="utf-8")
        for marker in ACTIVE_DOC_FORBIDDEN_MARKERS:
            if marker in content:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: '{marker}'")

    assert not violations, "legacy author workflow semantics detected in active docs:\n" + "\n".join(sorted(violations))


def test_release_stability_suite_uses_raw_brief_contract_only() -> None:
    suite_path = REPO_ROOT / "eval_data" / "author_play_stability_suite_v1.json"
    suite_payload = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = list(suite_payload.get("cases") or [])

    assert cases, "stability suite must include at least one case"
    for case in cases:
        assert isinstance(case.get("raw_brief"), str) and case["raw_brief"].strip()
        assert "prompt_text" not in case
        assert "seed_text" not in case
        assert "kind" not in case
        assert "style" not in case
        assert "target_minutes" not in case
        assert "npc_count" not in case


def test_release_runners_do_not_keep_prompt_seed_compat_layer() -> None:
    check_paths = [
        REPO_ROOT / "scripts" / "release" / "run_author_play_stability.py",
        REPO_ROOT / "frontend" / "scripts" / "author_play_release_gate.mjs",
    ]
    forbidden_patterns = {
        "case.prompt_text",
        "case.seed_text",
        "testCase.kind",
        "testCase.prompt_text",
        "testCase.seed_text",
    }
    violations: list[str] = []

    for path in check_paths:
        content = path.read_text(encoding="utf-8")
        for marker in forbidden_patterns:
            if marker in content:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: '{marker}'")

    assert not violations, "release runners still contain prompt/seed compatibility markers:\n" + "\n".join(sorted(violations))


def test_frontend_readme_uses_raw_brief_author_input_language() -> None:
    content = (FRONTEND_ROOT / "README.md").read_text(encoding="utf-8")
    assert "raw_brief" in content
    assert "prompt_text" not in content
    assert "seed_text" not in content


def test_frontend_agent_contract_matches_author_run_raw_brief_contract() -> None:
    content = (REPO_ROOT / "frontend_agent_contract.md").read_text(encoding="utf-8")
    assert "`POST /author/runs`" in content
    assert "raw_brief" in content
    assert "prompt_text" not in content
    assert "seed_text" not in content


def test_frontend_author_status_literals_are_centralized() -> None:
    allowed_paths = {
        FRONTEND_ROOT / "src" / "features" / "author-review" / "lib" / "authorStatus.ts",
        FRONTEND_ROOT / "src" / "shared" / "api" / "types.ts",
    }
    scan_paths = [
        *sorted((FRONTEND_ROOT / "src" / "pages" / "author").glob("*.tsx")),
        FRONTEND_ROOT / "src" / "features" / "author-review" / "lib" / "authorViewModel.ts",
    ]
    forbidden_literals = {"'pending'", "'running'", "'review_ready'", "'failed'"}
    violations: list[str] = []

    for path in scan_paths:
        if path in allowed_paths:
            continue
        content = path.read_text(encoding="utf-8")
        for marker in forbidden_literals:
            if marker in content:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {marker}")

    assert not violations, "frontend author status literals should be centralized:\n" + "\n".join(sorted(violations))
