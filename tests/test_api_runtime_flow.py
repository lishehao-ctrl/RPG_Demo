from __future__ import annotations

import itertools
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ActionLog, SessionStepIdempotency
from app.db.session import SessionLocal
from app.main import app
from app.modules.llm_boundary.errors import LLMUnavailableError
from app.modules.runtime.schemas import StepRequest
from app.modules.runtime.service import StreamAbortedError, run_step_with_replay_flag

_STEP_KEY_COUNTER = itertools.count(1)


def _pack() -> dict:
    with open("examples/storypacks/campus_week_v1.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _publish_story(client: TestClient) -> None:
    pack = _pack()
    v = client.post("/api/v1/stories/validate", json={"pack": pack})
    assert v.status_code == 200
    assert v.json()["ok"] is True

    created = client.post(
        "/api/v1/stories",
        json={"story_id": pack["story_id"], "title": pack["title"], "pack": pack},
    )
    assert created.status_code == 201
    version = created.json()["version"]

    published = client.post(f"/api/v1/stories/{pack['story_id']}/publish", json={"version": version})
    assert published.status_code == 200


def _step(client: TestClient, sid: str, payload: dict, *, key: str | None = None):
    idem_key = key or f"step-{next(_STEP_KEY_COUNTER)}"
    return client.post(
        f"/api/v1/sessions/{sid}/step",
        json=payload,
        headers={"X-Idempotency-Key": idem_key},
    )


def _parse_sse_events(raw: str) -> list[dict]:
    events: list[dict] = []
    blocks = [item for item in raw.split("\n\n") if item.strip()]
    for block in blocks:
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if not line:
                continue
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip() or "message"
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        payload: dict = {}
        joined = "\n".join(data_lines)
        if joined:
            try:
                payload = json.loads(joined)
            except json.JSONDecodeError:
                payload = {"raw": joined}
        events.append({"event": event_name, "payload": payload})
    return events


def test_runtime_happy_path_choice_step() -> None:
    client = TestClient(app)
    _publish_story(client)

    created = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"})
    assert created.status_code == 201
    sid = created.json()["session_id"]

    step = _step(client, sid, {"choice_id": "c_study"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is False
    assert body["executed_choice_id"] == "c_study"
    assert body["story_node_id"] == "n_library"
    assert isinstance(body["narrative_text"], str)
    assert all("available" in item for item in body["choices"])


def test_session_create_response_contains_current_node() -> None:
    client = TestClient(app)
    _publish_story(client)

    created = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"})
    assert created.status_code == 201
    body = created.json()

    assert body["story_id"] == "campus_week_v1"
    assert isinstance(body["story_version"], int)
    assert body["status"] == "active"
    assert isinstance(body["current_node"], dict)
    assert body["current_node"]["id"] == body["story_node_id"]
    assert isinstance(body["current_node"]["choices"], list)


def test_step_response_contains_current_node_and_session_status() -> None:
    client = TestClient(app)
    _publish_story(client)

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    step = _step(client, sid, {"choice_id": "c_study"})
    assert step.status_code == 200
    body = step.json()

    assert body["session_status"] in {"active", "ended"}
    assert isinstance(body["current_node"], dict)
    assert body["current_node"]["id"] == body["story_node_id"]
    assert body["current_node"]["choices"] == body["choices"]


def test_session_state_choices_include_locked_items() -> None:
    client = TestClient(app)
    _publish_story(client)

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    state = client.get(f"/api/v1/sessions/{sid}").json()
    choices = {item["id"]: item for item in state["current_node"]["choices"]}

    assert choices["c_confess"]["available"] is False
    assert isinstance(choices["c_confess"]["locked_reason"], dict)
    assert isinstance(state["created_at"], str) and state["created_at"].endswith("Z")
    assert isinstance(state["updated_at"], str) and state["updated_at"].endswith("Z")


def test_runtime_accept_all_free_input_fallback_progresses() -> None:
    client = TestClient(app)
    _publish_story(client)

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    step = _step(client, sid, {"player_input": "我想原地唱歌"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["executed_choice_id"].startswith("fallback:")
    assert body["story_node_id"] == "n_hub"


def test_step_idempotency_replay_and_mismatch() -> None:
    client = TestClient(app)
    _publish_story(client)

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    first = _step(client, sid, {"choice_id": "c_study"}, key="idem-1")
    second = _step(client, sid, {"choice_id": "c_study"}, key="idem-1")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    mismatch = _step(client, sid, {"choice_id": "c_work"}, key="idem-1")
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"

    with SessionLocal() as db:
        logs = db.execute(select(ActionLog).where(ActionLog.session_id == sid)).scalars().all()
        assert len(logs) == 1


def test_llm_unavailable_rolls_back_state(monkeypatch) -> None:
    client = TestClient(app)
    _publish_story(client)

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    before = client.get(f"/api/v1/sessions/{sid}").json()

    class _BrokenLLM:
        def narrative(self, *, system_prompt: str, user_prompt: str):
            del system_prompt, user_prompt
            raise LLMUnavailableError("forced failure")

    monkeypatch.setattr("app.modules.runtime.router.get_llm_boundary", lambda: _BrokenLLM())
    failed = _step(client, sid, {"choice_id": "c_study"})
    assert failed.status_code == 503
    assert failed.json()["detail"]["code"] == "LLM_UNAVAILABLE"

    after = client.get(f"/api/v1/sessions/{sid}").json()
    assert after["story_node_id"] == before["story_node_id"]
    assert after["state_json"] == before["state_json"]


def test_step_requires_idempotency_header() -> None:
    client = TestClient(app)
    _publish_story(client)

    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    missing = client.post(f"/api/v1/sessions/{sid}/step", json={"choice_id": "c_study"})
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "MISSING_IDEMPOTENCY_KEY"


def test_step_stream_requires_idempotency_header() -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]

    missing = client.post(f"/api/v1/sessions/{sid}/step/stream", json={"choice_id": "c_study"})
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "MISSING_IDEMPOTENCY_KEY"


def test_step_stream_choice_emits_meta_phase_final_done() -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]

    with client.stream(
        "POST",
        f"/api/v1/sessions/{sid}/step/stream",
        json={"choice_id": "c_study"},
        headers={"X-Idempotency-Key": "stream-choice-1"},
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())

    events = _parse_sse_events(raw)
    names = [item["event"] for item in events]
    assert "meta" in names
    assert "phase" in names
    assert "final" in names
    assert names[-1] == "done"

    final_payload = next(item["payload"] for item in events if item["event"] == "final")
    assert final_payload["executed_choice_id"] == "c_study"
    assert final_payload["session_status"] in {"active", "ended"}


def test_step_stream_free_input_emits_narrative_delta() -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]

    with client.stream(
        "POST",
        f"/api/v1/sessions/{sid}/step/stream",
        json={"player_input": "off_topic sing"},
        headers={"X-Idempotency-Key": "stream-free-1"},
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())

    events = _parse_sse_events(raw)
    delta_events = [item for item in events if item["event"] == "narrative_delta"]
    assert len(delta_events) >= 1

    final_payload = next(item["payload"] for item in events if item["event"] == "final")
    assert isinstance(final_payload["narrative_text"], str)
    assert final_payload["narrative_text"].strip() != ""


def test_step_stream_replay_returns_replay_then_final() -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]

    # first request creates the idempotency success record
    first = _step(client, sid, {"choice_id": "c_study"}, key="stream-replay-1")
    assert first.status_code == 200

    with client.stream(
        "POST",
        f"/api/v1/sessions/{sid}/step/stream",
        json={"choice_id": "c_study"},
        headers={"X-Idempotency-Key": "stream-replay-1"},
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())

    events = _parse_sse_events(raw)
    names = [item["event"] for item in events]
    assert "replay" in names
    assert "final" in names
    assert names[-1] == "done"


def test_step_stream_marks_failed_on_llm_unavailable(monkeypatch) -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    before = client.get(f"/api/v1/sessions/{sid}").json()

    class _BrokenLLM:
        def narrative(self, **kwargs):
            del kwargs
            raise LLMUnavailableError("forced unavailable stream")

    monkeypatch.setattr("app.modules.runtime.router.get_llm_boundary", lambda: _BrokenLLM())

    with client.stream(
        "POST",
        f"/api/v1/sessions/{sid}/step/stream",
        json={"choice_id": "c_study"},
        headers={"X-Idempotency-Key": "stream-llm-fail-1"},
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())

    events = _parse_sse_events(raw)
    error_payload = next(item["payload"] for item in events if item["event"] == "error")
    assert error_payload["code"] == "LLM_UNAVAILABLE"

    after = client.get(f"/api/v1/sessions/{sid}").json()
    assert after["story_node_id"] == before["story_node_id"]
    assert after["state_json"] == before["state_json"]


def test_step_stream_marks_failed_when_abort_check_trips() -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    before = client.get(f"/api/v1/sessions/{sid}").json()

    abort_state = {"abort": False}

    class _AbortableLLM:
        def narrative(self, **kwargs):
            on_delta = kwargs.get("on_delta")
            if callable(on_delta):
                on_delta("alpha ")
            abort_state["abort"] = True
            if callable(on_delta):
                on_delta("beta ")

            class _Narrative:
                narrative_text = "alpha beta"

            return _Narrative()

    with SessionLocal() as db:
        with pytest.raises(StreamAbortedError):
            run_step_with_replay_flag(
                db,
                session_id=sid,
                payload=StepRequest(choice_id="c_study"),
                idempotency_key="stream-abort-1",
                llm_boundary=_AbortableLLM(),
                abort_check=lambda: bool(abort_state["abort"]),
                on_narrative_delta=lambda _: None,
            )

    row = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        with SessionLocal() as db:
            row = db.execute(
                select(SessionStepIdempotency).where(
                    SessionStepIdempotency.session_id == sid,
                    SessionStepIdempotency.idempotency_key == "stream-abort-1",
                )
            ).scalar_one_or_none()
            if row is not None and row.status != "in_progress":
                break
        time.sleep(0.05)

    assert row is not None
    assert row.status == "failed"
    assert row.error_code == "STREAM_ABORTED"

    after = client.get(f"/api/v1/sessions/{sid}").json()
    assert after["story_node_id"] == before["story_node_id"]
    assert after["state_json"] == before["state_json"]

    with SessionLocal() as db:
        logs = db.execute(select(ActionLog).where(ActionLog.session_id == sid)).scalars().all()
        assert len(logs) == 0


def test_step_stream_ending_is_non_stream_but_returns_final() -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]

    with client.stream(
        "POST",
        f"/api/v1/sessions/{sid}/step/stream",
        json={"choice_id": "c_join_enemy"},
        headers={"X-Idempotency-Key": "stream-ending-1"},
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())

    events = _parse_sse_events(raw)
    names = [item["event"] for item in events]
    assert "final" in names
    assert "narrative_delta" not in names

    final_payload = next(item["payload"] for item in events if item["event"] == "final")
    assert final_payload["run_ended"] is True
    assert isinstance(final_payload["ending_id"], str)


def test_existing_step_endpoint_unchanged() -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]
    step = _step(client, sid, {"choice_id": "c_study"}, key="legacy-step-1")
    assert step.status_code == 200
    body = step.json()
    assert "narrative_text" in body
    assert "current_node" in body
    assert body["executed_choice_id"] == "c_study"


def test_concurrent_steps_one_conflict_one_success(monkeypatch) -> None:
    client = TestClient(app)
    _publish_story(client)
    sid = client.post("/api/v1/sessions", json={"story_id": "campus_week_v1"}).json()["session_id"]

    class _SlowLLM:
        def narrative(self, *, system_prompt: str, user_prompt: str):
            del system_prompt, user_prompt
            time.sleep(0.08)

            class _Narrative:
                narrative_text = "slow narrative"

            return _Narrative()

    monkeypatch.setattr("app.modules.runtime.router.get_llm_boundary", lambda: _SlowLLM())

    results: list[tuple[int, dict]] = []
    worker_errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def _worker(key: str) -> None:
        try:
            barrier.wait()
            with TestClient(app) as thread_client:
                response = _step(thread_client, sid, {"choice_id": "c_study"}, key=key)
            results.append((response.status_code, response.json()))
        except Exception as exc:  # pragma: no cover - assertion handled below
            worker_errors.append(exc)

    t1 = threading.Thread(target=_worker, args=("concurrency-a",))
    t2 = threading.Thread(target=_worker, args=("concurrency-b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert worker_errors == []
    statuses = sorted(code for code, _ in results)
    assert statuses == [200, 409]
    conflict = next(payload for code, payload in results if code == 409)
    assert conflict["detail"]["code"] == "SESSION_STEP_CONFLICT"

    state = client.get(f"/api/v1/sessions/{sid}").json()
    assert int(state["state_json"]["run_state"]["step_index"]) == 1

    with SessionLocal() as db:
        logs = db.execute(select(ActionLog).where(ActionLog.session_id == sid)).scalars().all()
        assert len(logs) == 1
        assert int(logs[0].step_index) == 1
