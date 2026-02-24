from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.support.db_runtime import prepare_sqlite_db


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "author_compile.db")


def _author_payload_v4() -> dict:
    return {
        "format_version": 4,
        "entry_mode": "spark",
        "source_text": None,
        "meta": {
            "story_id": "author_story_v4",
            "version": 1,
            "title": "Author Story v4",
            "summary": "Authoring compile smoke payload",
            "locale": "en",
        },
        "world": {
            "era": "Contemporary semester",
            "location": "University district",
            "boundaries": "No magic; schedule and resources limit choices.",
            "social_rules": "Consistency shapes relationships.",
            "global_state": {
                "initial_state": {
                    "energy": 80,
                    "money": 50,
                    "knowledge": 0,
                    "affection": 0,
                    "day": 1,
                    "slot": "morning",
                }
            },
            "intent_module": {"author_input": "weekly pressure", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "characters": {
            "protagonist": {"name": "You", "role": "student", "traits": ["driven"], "resources": {}},
            "npcs": [{"name": "Alice", "role": "friend", "traits": ["kind", "direct"]}],
            "relationship_axes": {"trust": "kept promises"},
            "intent_module": {"author_input": "core cast", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "plot": {
            "mainline_acts": [
                {"act_key": "act_setup", "title": "Act I", "objective": "Stabilize morning", "scene_keys": ["start"]}
            ],
            "sideline_threads": ["Keep one social beat alive"],
            "mainline_goal": "Finish the week with momentum.",
            "intent_module": {"author_input": "mainline", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "flow": {
            "start_scene_key": "start",
            "scenes": [
                {
                    "scene_key": "start",
                    "title": "Morning Start",
                    "setup": "You step onto campus with limited time before class.",
                    "free_input_hints": ["study", "rest"],
                    "options": [
                        {
                            "option_key": "study_first",
                            "label": "Head to class and study",
                            "intent_aliases": ["study", "class"],
                            "action_type": "study",
                            "go_to": "mid",
                        },
                        {
                            "option_key": "take_break",
                            "label": "Take a quick break",
                            "intent_aliases": ["rest", "recover"],
                            "action_type": "rest",
                            "go_to": "mid",
                        },
                    ],
                    "intent_module": {"author_input": "scene one", "intent_tags": [], "parse_notes": None, "aliases": []},
                },
                {
                    "scene_key": "mid",
                    "title": "Afternoon Pivot",
                    "setup": "Afternoon pressure rises and choices tighten.",
                    "is_end": True,
                    "options": [
                        {
                            "option_key": "work_shift",
                            "label": "Pick up a shift",
                            "intent_aliases": ["work", "job"],
                            "action_type": "work",
                        },
                        {
                            "option_key": "meet_alice",
                            "label": "Meet Alice",
                            "intent_aliases": ["alice", "talk"],
                            "action_type": "date",
                        },
                    ],
                    "intent_module": {"author_input": "scene two", "intent_tags": [], "parse_notes": None, "aliases": []},
                },
            ],
            "intent_module": {"author_input": "flow", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "action": {
            "action_catalog": [{"action_id": "study", "label": "Study", "defaults": {}}],
            "input_mapping_policy": "intent_alias_only_visible_choice",
            "intent_module": {"author_input": "action", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "consequence": {
            "state_axes": ["energy", "money", "knowledge", "affection", "day", "slot"],
            "quest_progression_rules": [
                {
                    "quest_key": "weekly_plan",
                    "title": "Weekly Plan",
                    "stages": [
                        {
                            "stage_key": "foundation",
                            "title": "Foundation",
                            "milestones": [
                                {
                                    "milestone_key": "study_once",
                                    "title": "Study once",
                                    "when": {"option_ref_is": "start.study_first"},
                                }
                            ],
                        }
                    ],
                }
            ],
            "event_rules": [],
            "intent_module": {"author_input": "consequence", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "ending": {
            "ending_rules": [
                {
                    "ending_key": "steady_finish",
                    "title": "Steady Finish",
                    "priority": 100,
                    "outcome": "success",
                    "trigger": {"scene_key_is": "mid"},
                    "epilogue": "You carry enough momentum to close the arc on your terms.",
                }
            ],
            "intent_module": {"author_input": "ending", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "systems": {
            "fallback_style": {"tone": "supportive", "action_type": "rest"},
            "events": [],
            "intent_module": {"author_input": "systems", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "writer_journal": [],
        "playability_policy": {
            "ending_reach_rate_min": 0.5,
            "stuck_turn_rate_max": 0.2,
            "no_progress_rate_max": 0.6,
            "branch_coverage_warn_below": 0.1,
            "rollout_runs_per_strategy": 10,
        },
    }


def _author_payload_v2_style() -> dict:
    return {
        "format_version": 2,
        "meta": {"story_id": "legacy_v2", "version": 1, "title": "Legacy v2"},
        "world": {
            "premise": "legacy",
            "tone": "grounded",
            "characters": [],
            "initial_state": {"energy": 80, "money": 50, "knowledge": 0, "affection": 0, "day": 1, "slot": "morning"},
        },
        "plot": {"acts": [], "mainline_goal": None, "sideline_threads": []},
        "flow": {
            "scenes": [
                {
                    "scene_key": "start",
                    "title": "Start",
                    "setup": "Setup",
                    "options": [
                        {"option_key": "a", "label": "Study", "action_type": "study", "go_to": "start"},
                        {"option_key": "b", "label": "Rest", "action_type": "rest", "go_to": "start"},
                    ],
                }
            ]
        },
        "systems": {"quests": [], "events": [], "endings": []},
    }


def test_compile_author_success_returns_runtime_pack_and_mappings(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    payload = _author_payload_v4()

    resp = client.post("/stories/compile-author", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    pack = body["pack"]
    diagnostics = body["diagnostics"]
    assert pack["story_id"] == "author_story_v4"
    assert pack["start_node_id"] == "n_start"
    assert pack["summary"] == "Authoring compile smoke payload"
    assert pack["locale"] == "en"
    assert len(pack["nodes"]) == 2
    assert pack["nodes"][0]["choices"][0]["choice_id"] == "c_start_1"
    assert pack["nodes"][0]["intents"]
    assert pack["default_fallback"]["text_variants"]["FALLBACK"]
    assert isinstance(pack.get("author_source_v4"), dict)
    assert diagnostics["errors"] == []
    assert diagnostics["mappings"]["scenes"]["start"] == "n_start"
    assert diagnostics["mappings"]["options"]["start.study_first"] == "c_start_1"
    milestone_when = pack["quests"][0]["stages"][0]["milestones"][0]["when"]
    assert milestone_when["executed_choice_id_is"] == "c_start_1"


def test_compile_author_does_not_depend_on_llm_runtime(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    payload = _author_payload_v4()

    def _fail_get_runtime(*_args, **_kwargs):
        raise AssertionError("compile-author must stay deterministic and not call LLM runtime")

    monkeypatch.setattr("app.modules.llm.adapter.get_llm_runtime", _fail_get_runtime)

    resp = client.post("/stories/compile-author", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pack"]["story_id"] == "author_story_v4"


def test_compile_author_rejects_pre_v4_payload_with_explicit_code(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    resp = client.post("/stories/compile-author", json=_author_payload_v2_style())
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "AUTHOR_V4_REQUIRED"
    assert "format_version=4" in detail["message"]


def test_compile_author_rejects_unknown_scene_reference(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    payload = _author_payload_v4()
    payload["flow"]["scenes"][0]["options"][0]["go_to"] = "missing_scene"

    resp = client.post("/stories/compile-author", json=payload)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "AUTHOR_COMPILE_FAILED"
    assert any(item.get("code") == "AUTHOR_UNKNOWN_SCENE_REF" for item in (detail.get("errors") or []))
