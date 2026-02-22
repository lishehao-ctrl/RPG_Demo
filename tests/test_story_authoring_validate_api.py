from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.support.db_runtime import prepare_sqlite_db


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "author_validate.db")


def _valid_author_payload_v4() -> dict:
    return {
        "format_version": 4,
        "entry_mode": "spark",
        "source_text": None,
        "meta": {
            "story_id": "author_validate_v4",
            "version": 1,
            "title": "Author Validate",
            "locale": "en",
        },
        "world": {
            "era": "Contemporary semester",
            "location": "Campus",
            "boundaries": "No magic.",
            "social_rules": "Schedules and relationships matter.",
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
            "intent_module": {"author_input": "world", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "characters": {
            "protagonist": {"name": "You", "role": "student", "traits": [], "resources": {}},
            "npcs": [],
            "relationship_axes": {},
            "intent_module": {"author_input": "chars", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "plot": {
            "mainline_acts": [],
            "sideline_threads": [],
            "mainline_goal": None,
            "intent_module": {"author_input": "plot", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "flow": {
            "scenes": [
                {
                    "scene_key": "start",
                    "title": "Start",
                    "setup": "A simple start.",
                    "options": [
                        {"option_key": "study", "label": "Study", "action_type": "study", "go_to": "end"},
                        {"option_key": "rest", "label": "Rest", "action_type": "rest", "go_to": "end"},
                    ],
                    "intent_module": {"author_input": "scene start", "intent_tags": [], "parse_notes": None, "aliases": []},
                },
                {
                    "scene_key": "end",
                    "title": "End",
                    "setup": "A simple end.",
                    "is_end": True,
                    "options": [
                        {"option_key": "work", "label": "Work", "action_type": "work"},
                        {"option_key": "date", "label": "Date", "action_type": "date"},
                    ],
                    "intent_module": {"author_input": "scene end", "intent_tags": [], "parse_notes": None, "aliases": []},
                },
            ],
            "intent_module": {"author_input": "flow", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "action": {
            "action_catalog": [],
            "input_mapping_policy": "intent_alias_only_visible_choice",
            "intent_module": {"author_input": "action", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "consequence": {
            "state_axes": ["energy", "money", "knowledge", "affection", "day", "slot"],
            "quest_progression_rules": [],
            "event_rules": [],
            "intent_module": {"author_input": "consequence", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "ending": {
            "ending_rules": [
                {
                    "ending_key": "week_close",
                    "title": "Week Close",
                    "priority": 100,
                    "outcome": "neutral",
                    "trigger": {"scene_key_is": "end"},
                    "epilogue": "You close the current arc and carry one clear thread forward.",
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


def _v2_style_payload() -> dict:
    return {
        "format_version": 2,
        "meta": {"story_id": "legacy_author_validate", "version": 1, "title": "Legacy Validate"},
    }


def test_validate_author_success_returns_compiled_preview(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    payload = _valid_author_payload_v4()

    resp = client.post("/stories/validate-author", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["errors"] == []
    assert isinstance(body.get("compiled_preview"), dict)
    assert body["compiled_preview"]["story_id"] == "author_validate_v4"
    assert body["compiled_preview"]["start_node_id"] == "n_start"
    assert isinstance(body.get("playability"), dict)
    assert isinstance(body["playability"].get("metrics"), dict)


def test_validate_author_rejects_pre_v4_payload_with_explicit_code(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    resp = client.post("/stories/validate-author", json=_v2_style_payload())
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "AUTHOR_V4_REQUIRED"
    assert "format_version=4" in detail["message"]


def test_validate_author_schema_error_is_friendly(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    payload = {
        "format_version": 4,
        "entry_mode": "spark",
        "source_text": None,
        "meta": {"story_id": "broken_author", "version": 1, "title": "Broken"},
        "world": {
            "era": "Now",
            "location": "Campus",
            "boundaries": "No magic",
            "global_state": {},
            "intent_module": {"author_input": "world", "intent_tags": [], "parse_notes": None, "aliases": []},
        },
        "writer_journal": [],
        "playability_policy": {},
    }

    resp = client.post("/stories/validate-author", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["compiled_preview"] is None
    assert any(item.get("code") == "AUTHOR_SCHEMA_ERROR" for item in (body.get("errors") or []))


def test_validate_author_reports_unknown_option_reference(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    payload = _valid_author_payload_v4()
    payload["consequence"]["quest_progression_rules"] = [
        {
            "quest_key": "q1",
            "title": "Q1",
            "stages": [
                {
                    "stage_key": "s1",
                    "title": "S1",
                    "milestones": [
                        {
                            "milestone_key": "m1",
                            "title": "M1",
                            "when": {"option_ref_is": "start.missing_opt"},
                        }
                    ],
                }
            ],
        }
    ]

    resp = client.post("/stories/validate-author", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert any(item.get("code") == "AUTHOR_UNKNOWN_OPTION_REF" for item in (body.get("errors") or []))
