from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _player_effect(metric: str, center: int) -> dict:
    return {
        "target_type": "player",
        "metric": metric,
        "center": center,
        "intensity": 1,
    }


def _pack_cycle_with_exit(*, story_id: str) -> dict:
    return {
        "schema_version": "2.0",
        "story_id": story_id,
        "title": "Audit Story",
        "start_node_id": "n1",
        "nodes": [
            {
                "node_id": "n1",
                "title": "N1",
                "scene_brief": "node 1",
                "choices": [
                    {
                        "choice_id": "c_to_n2",
                        "text": "go to n2",
                        "intent_tags": ["go", "n2"],
                        "next_node_id": "n2",
                        "range_effects": [_player_effect("energy", -1)],
                    }
                ],
            },
            {
                "node_id": "n2",
                "title": "N2",
                "scene_brief": "node 2",
                "choices": [
                    {
                        "choice_id": "c_back",
                        "text": "go back",
                        "intent_tags": ["back"],
                        "next_node_id": "n1",
                        "range_effects": [_player_effect("knowledge", 1)],
                    },
                    {
                        "choice_id": "c_end",
                        "text": "end this route",
                        "intent_tags": ["end"],
                        "next_node_id": "n1",
                        "ending_id": "ending_neutral_default",
                        "range_effects": [_player_effect("affection", 1)],
                    },
                ],
            },
        ],
    }


def _pack_trap_cycle(*, story_id: str) -> dict:
    pack = _pack_cycle_with_exit(story_id=story_id)
    pack["nodes"][1]["choices"] = [
        {
            "choice_id": "c_back",
            "text": "go back",
            "intent_tags": ["back"],
            "next_node_id": "n1",
            "range_effects": [_player_effect("knowledge", 1)],
        }
    ]
    return pack


def test_audit_reports_unreachable_node_error() -> None:
    client = TestClient(app)
    pack = _pack_cycle_with_exit(story_id="audit_unreachable")
    pack["nodes"].append(
        {
            "node_id": "n_dead",
            "title": "Dead",
            "scene_brief": "dead end",
            "choices": [
                {
                    "choice_id": "c_dead",
                    "text": "stay",
                    "intent_tags": ["stay"],
                    "next_node_id": "n_dead",
                    "range_effects": [_player_effect("energy", -1)],
                }
            ],
        }
    )

    res = client.post("/api/v1/stories/audit", json={"pack": pack})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert any(item["code"] == "UNREACHABLE_NODE" for item in body["errors"])


def test_audit_reachability_includes_fallback_edges() -> None:
    client = TestClient(app)
    pack = _pack_cycle_with_exit(story_id="audit_fallback_reachability")
    pack["nodes"].append(
        {
            "node_id": "n_fallback_only",
            "title": "Fallback Reachable",
            "scene_brief": "only reachable through fallback",
            "choices": [
                {
                    "choice_id": "c_back_to_start",
                    "text": "go back",
                    "intent_tags": ["back"],
                    "next_node_id": "n1",
                    "range_effects": [_player_effect("energy", -1)],
                }
            ],
        }
    )
    pack["global_fallbacks"] = [
        {
            "fallback_id": "fb_to_hidden_node",
            "text": "route to hidden node",
            "target_node_id": "n_fallback_only",
            "range_effects": [_player_effect("energy", -1)],
        }
    ]

    res = client.post("/api/v1/stories/audit", json={"pack": pack})
    assert res.status_code == 200
    body = res.json()
    assert all(item["code"] != "UNREACHABLE_NODE" for item in body["errors"])


def test_audit_reports_trap_loop_error() -> None:
    client = TestClient(app)
    pack = _pack_cycle_with_exit(story_id="audit_trap")
    pack["nodes"][1]["choices"] = [
        {
            "choice_id": "c_back",
            "text": "go back",
            "intent_tags": ["back"],
            "next_node_id": "n1",
            "range_effects": [_player_effect("knowledge", 1)],
        }
    ]

    res = client.post("/api/v1/stories/audit", json={"pack": pack})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert any(item["code"] == "TRAP_LOOP" for item in body["errors"])


def test_audit_trap_loop_uses_node_fallback_ending_as_exit() -> None:
    client = TestClient(app)
    pack = _pack_trap_cycle(story_id="audit_trap_fallback_exit")
    pack["global_fallbacks"] = [
        {
            "fallback_id": "fb_node_exit",
            "text": "node scoped ending fallback",
            "range_effects": [_player_effect("energy", -1)],
            "ending_id": "ending_neutral_default",
        }
    ]
    pack["nodes"][0]["node_fallback_id"] = "fb_node_exit"

    res = client.post("/api/v1/stories/audit", json={"pack": pack})
    assert res.status_code == 200
    body = res.json()
    assert all(item["code"] != "TRAP_LOOP" for item in body["errors"])
    assert any(item["code"] == "LOOP_WITH_EXIT" for item in body["warnings"])


def test_audit_global_fallback_ending_without_node_binding_does_not_clear_trap() -> None:
    client = TestClient(app)
    pack = _pack_trap_cycle(story_id="audit_global_fallback_not_exit")
    pack["global_fallbacks"] = [
        {
            "fallback_id": "fb_global_exit",
            "text": "global ending fallback",
            "range_effects": [_player_effect("energy", -1)],
            "ending_id": "ending_neutral_default",
        }
    ]

    res = client.post("/api/v1/stories/audit", json={"pack": pack})
    assert res.status_code == 200
    body = res.json()
    assert any(item["code"] == "TRAP_LOOP" for item in body["errors"])


def test_audit_reports_loop_with_exit_warning() -> None:
    client = TestClient(app)
    pack = _pack_cycle_with_exit(story_id="audit_warning")

    res = client.post("/api/v1/stories/audit", json={"pack": pack})
    assert res.status_code == 200
    body = res.json()
    assert any(item["code"] == "LOOP_WITH_EXIT" for item in body["warnings"])


def test_publish_is_blocked_when_audit_has_errors() -> None:
    client = TestClient(app)
    pack = _pack_cycle_with_exit(story_id="audit_publish_block")
    pack["nodes"][1]["choices"] = [
        {
            "choice_id": "c_back",
            "text": "go back",
            "intent_tags": ["back"],
            "next_node_id": "n1",
            "range_effects": [_player_effect("knowledge", 1)],
        }
    ]

    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = created.json()["version"]

    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 422
    detail = published.json()["detail"]
    assert detail["code"] == "INVALID_STORY_AUDIT"
    assert any(item["code"] == "TRAP_LOOP" for item in detail["errors"])


def test_publish_allows_warnings_and_returns_them() -> None:
    client = TestClient(app)
    pack = _pack_cycle_with_exit(story_id="audit_publish_warn")

    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = created.json()["version"]

    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 200
    body = published.json()
    assert body["status"] == "published"
    assert any(item["code"] == "LOOP_WITH_EXIT" for item in body["warnings"])


def test_publish_gate_respects_updated_audit_with_fallback_edges() -> None:
    client = TestClient(app)
    pack = _pack_trap_cycle(story_id="audit_publish_fallback_exit")
    pack["global_fallbacks"] = [
        {
            "fallback_id": "fb_node_exit",
            "text": "node scoped ending fallback",
            "range_effects": [_player_effect("energy", -1)],
            "ending_id": "ending_neutral_default",
        }
    ]
    pack["nodes"][0]["node_fallback_id"] = "fb_node_exit"

    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = created.json()["version"]

    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 200
    body = published.json()
    assert any(item["code"] == "LOOP_WITH_EXIT" for item in body["warnings"])
