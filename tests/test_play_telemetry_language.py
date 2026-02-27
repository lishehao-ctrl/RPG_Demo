from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.modules.llm_boundary.errors import LLMUnavailableError


def _pack() -> dict:
    with open("examples/storypacks/campus_week_v1.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _publish_story(client: TestClient) -> None:
    pack = _pack()
    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = int(created.json()["version"])
    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 200


def _step(client: TestClient, sid: str, payload: dict, key: str) -> dict:
    res = client.post(
        f"/api/v1/sessions/{sid}/step",
        json=payload,
        headers={"X-Idempotency-Key": key},
    )
    assert res.status_code == 200
    return res.json()


def test_play_page_available() -> None:
    client = TestClient(app)
    res = client.get("/play")
    assert res.status_code == 200
    assert "Choose Story" in res.text
    assert "story-select-screen" in res.text
    assert "Start Story" in res.text
    assert "change-story-btn" in res.text
    assert "Advanced details" in res.text
    assert "Free Input" in res.text
    assert "narrative-line" in res.text
    assert "Generating narration..." in res.text
    assert "step/stream" not in res.text
    assert "X-Player-Token (optional)" not in res.text
    assert "Story Version" not in res.text
    assert "Refresh" not in res.text
    assert "Activity" not in res.text


def test_play_dev_page_available() -> None:
    client = TestClient(app)
    res = client.get("/play-dev")
    assert res.status_code == 200
    assert "Story Debug Console" in res.text
    assert "Sync" in res.text
    assert "Start Session" in res.text
    assert "Step Choice" in res.text
    assert "Step Free Input" in res.text
    assert "Live Stream" not in res.text
    assert "dev-live-status" not in res.text
    assert "dev-live-text" not in res.text
    assert "step/stream" not in res.text
    assert "Inspector" in res.text
    assert "dev-overview-btn" not in res.text
    assert "dev-timeline-btn" not in res.text
    assert "dev-telemetry-btn" not in res.text
    assert "dev-versions-btn" not in res.text


def test_runtime_telemetry_summary_tracks_steps() -> None:
    client = TestClient(app)
    _publish_story(client)

    created = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"})
    sid = created.json()["session_id"]

    _step(client, sid, {"choice_id": "c_study"}, "tm-1")
    _step(client, sid, {"player_input": "off_topic sing"}, "tm-2")

    telemetry = client.get("/api/v1/telemetry/runtime")
    assert telemetry.status_code == 200
    body = telemetry.json()
    assert body["total_step_requests"] == 2
    assert body["successful_steps"] == 2
    assert body["fallback_rate"] > 0
    assert body["avg_step_latency_ms"] >= 0
    assert body["p95_step_latency_ms"] >= 0


def test_runtime_telemetry_tracks_llm_unavailable_ratio(monkeypatch) -> None:
    client = TestClient(app)
    _publish_story(client)

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]

    class _BrokenLLM:
        def narrative(self, **kwargs):
            del kwargs
            raise LLMUnavailableError("forced unavailable")

    monkeypatch.setattr("app.modules.runtime.router.get_llm_boundary", lambda: _BrokenLLM())

    failed = client.post(
        f"/api/v1/sessions/{sid}/step",
        json={"choice_id": "c_study"},
        headers={"X-Idempotency-Key": "tm-err-1"},
    )
    assert failed.status_code == 503

    telemetry = client.get("/api/v1/telemetry/runtime")
    assert telemetry.status_code == 200
    body = telemetry.json()
    assert body["total_step_requests"] == 1
    assert body["llm_unavailable_errors"] == 1
    assert body["llm_unavailable_ratio"] == 1.0


def test_story_narration_language_applies_to_narrative_prompt(monkeypatch) -> None:
    settings.story_narration_language = "Chinese"
    client = TestClient(app)
    _publish_story(client)

    captured: dict[str, str] = {}

    class _CaptureLLM:
        def narrative(self, *, system_prompt: str, user_prompt: str):
            captured["system_prompt"] = system_prompt
            captured["user_prompt"] = user_prompt

            class _Narrative:
                narrative_text = "narrative-ok"

            return _Narrative()

    monkeypatch.setattr("app.modules.runtime.router.get_llm_boundary", lambda: _CaptureLLM())

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    step = client.post(
        f"/api/v1/sessions/{sid}/step",
        json={"choice_id": "c_study"},
        headers={"X-Idempotency-Key": "lang-1"},
    )
    assert step.status_code == 200
    assert "Chinese" in captured["system_prompt"]
    assert "Chinese" in captured["user_prompt"]


def test_story_narration_language_applies_to_ending_bundle(monkeypatch) -> None:
    settings.story_narration_language = "Chinese"
    client = TestClient(app)
    _publish_story(client)

    captured_slots: dict[str, object] = {}

    class _EndingCaptureLLM:
        def narrative(self, **kwargs):
            del kwargs

            class _Narrative:
                narrative_text = "narrative-ok"

            return _Narrative()

        def ending_bundle(self, *, prompt_profile_id: str, slots: dict):
            captured_slots["prompt_profile_id"] = prompt_profile_id
            captured_slots["slots"] = dict(slots)

            class _Bundle:
                narrative_text = "ending-text"

                class _Report:
                    @staticmethod
                    def model_dump() -> dict:
                        return {
                            "title": "Life Report",
                            "one_liner": "Done",
                            "life_summary": "Done",
                            "highlights": [{"title": "h", "detail": "d"}],
                            "stats": {
                                "total_steps": 1,
                                "fallback_count": 0,
                                "fallback_rate": 0,
                                "explicit_count": 1,
                                "rule_count": 0,
                                "llm_count": 0,
                                "fallback_source_count": 0,
                                "energy_delta": 0,
                                "money_delta": 0,
                                "knowledge_delta": 0,
                                "affection_delta": 0,
                            },
                            "persona_tags": ["steady"],
                        }

                ending_report = _Report()

            return _Bundle()

    monkeypatch.setattr("app.modules.runtime.router.get_llm_boundary", lambda: _EndingCaptureLLM())

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    step = client.post(
        f"/api/v1/sessions/{sid}/step",
        json={"choice_id": "c_join_enemy"},
        headers={"X-Idempotency-Key": "lang-2"},
    )
    assert step.status_code == 200
    assert step.json()["run_ended"] is True
    slots = captured_slots["slots"]
    assert slots["language"] == "Chinese"
