from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.modules.llm.adapter import LLMTimeoutProfile, LLMUnavailableError
from app.modules.llm.runtime.progress import emit_stage
from tests.support.db_runtime import prepare_sqlite_db


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "author_assist.db")


def _base_context() -> dict:
    return {
        "format_version": 4,
        "global_brief": "A student balances classes, side work, and relationships over one week.",
        "layer": "world",
        "operation": "append",
        "target_scope": "scene",
        "target_scene_key": "scene_intro",
        "target_option_key": "focus_class",
        "preserve_existing": True,
        "story_id": "assist_story",
        "title": "Assist Story",
        "mainline_goal": "Reach the weekend with momentum.",
        "scene_key": "scene_intro",
        "scene_title": "Morning Setup",
        "option_label": "Focus on study",
        "action_type": "study",
        "seed_text": "Your roommate may have copied your project and your scholarship deadline is one week away.",
    }


def _parse_sse_events(payload: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for raw_block in str(payload or "").replace("\r\n", "\n").split("\n\n"):
        block = raw_block.strip()
        if not block:
            continue
        event_name = "message"
        data_parts: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip() or "message"
            elif line.startswith("data:"):
                data_parts.append(line[len("data:"):].strip())
        data_text = "\n".join(data_parts).strip()
        if not data_text:
            data = {}
        else:
            data = json.loads(data_text)
        events.append((event_name, data))
    return events


class _RuntimeStub:
    def __init__(self, payload_by_task: dict[str, dict]):
        self._payload_by_task = payload_by_task
        self.calls: list[dict] = []

    def _task_from_prompt(self, prompt: str) -> str:
        marker = '"task":"'
        start = prompt.find(marker)
        if start < 0:
            return "seed_expand"
        start += len(marker)
        end = prompt.find('"', start)
        if end < 0:
            return "seed_expand"
        return prompt[start:end]

    def author_assist_with_fallback(
        self,
        db,
        *,
        prompt: str,
        prompt_envelope=None,
        session_id=None,
        step_id=None,
        timeout_profile=None,
        max_tokens_override=None,
    ):  # noqa: ANN001
        _ = prompt_envelope
        task = self._task_from_prompt(prompt)
        self.calls.append(
            {
                "mode": "single_stage",
                "task": task,
                "timeout_profile": timeout_profile,
                "max_tokens_override": max_tokens_override,
            }
        )
        payload = self._payload_by_task.get(task) or self._payload_by_task.get("*") or {
            "suggestions": {},
            "patch_preview": [],
            "warnings": [],
        }
        return payload, True

    def author_assist_two_stage_with_fallback(
        self,
        db,
        *,
        task: str,
        locale: str,
        context: dict,
        session_id=None,
        step_id=None,
        timeout_profile=None,
        expand_max_tokens_override=None,
        build_max_tokens_override=None,
        repair_max_tokens_override=None,
        expand_temperature_override=None,
        build_temperature_override=None,
        repair_temperature_override=None,
    ):  # noqa: ANN001
        self.calls.append(
            {
                "mode": "two_stage",
                "task": str(task),
                "timeout_profile": timeout_profile,
                "expand_max_tokens_override": expand_max_tokens_override,
                "build_max_tokens_override": build_max_tokens_override,
                "repair_max_tokens_override": repair_max_tokens_override,
                "expand_temperature_override": expand_temperature_override,
                "build_temperature_override": build_temperature_override,
                "repair_temperature_override": repair_temperature_override,
            }
        )
        payload = self._payload_by_task.get(str(task)) or self._payload_by_task.get("*") or {
            "suggestions": {},
            "patch_preview": [],
            "warnings": [],
        }
        return payload, True


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, payload_by_task: dict[str, dict]) -> _RuntimeStub:
    from app.modules.story import author_assist

    runtime = _RuntimeStub(payload_by_task)
    monkeypatch.setattr(author_assist, "get_llm_runtime", lambda: runtime)
    return runtime


@pytest.mark.parametrize(
    "task",
    [
        "story_ingest",
        "seed_expand",
        "beat_to_scene",
        "scene_deepen",
        "option_weave",
        "consequence_balance",
        "ending_design",
        "consistency_check",
        "continue_write",
        "trim_content",
        "spice_branch",
        "tension_rebalance",
    ],
)
def test_author_assist_tasks_return_stable_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task: str) -> None:
    _prepare_db(tmp_path)
    _patch_runtime(
        monkeypatch,
        payload_by_task={
            "*": {
                "suggestions": {"ok": True},
                "patch_preview": [
                    {
                        "id": "patch_ok",
                        "path": "meta.summary",
                        "label": "Set summary",
                        "value": "summary",
                    }
                ],
                "warnings": [],
            }
        },
    )
    client = TestClient(app)

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": task,
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    assert isinstance(body.get("suggestions"), dict)
    assert isinstance(body.get("patch_preview"), list)
    assert isinstance(body.get("warnings"), list)
    assert isinstance(body.get("model"), str) and body["model"]
    assert body["model"] == str(settings.llm_model_generate)

    for patch in body["patch_preview"]:
        assert isinstance(patch, dict)
        assert isinstance(patch.get("id"), str) and patch["id"]
        assert isinstance(patch.get("path"), str) and patch["path"]
        assert isinstance(patch.get("label"), str) and patch["label"]
        assert "value" in patch


def test_author_assist_rejects_unknown_task(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": "unknown_task",
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "ASSIST_TASK_V4_REQUIRED"


def test_author_assist_returns_503_when_llm_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    from app.modules.story import author_assist

    class _UnavailableRuntime:
        def author_assist_with_fallback(
            self,
            db,
            *,
            prompt: str,
            prompt_envelope=None,
            session_id=None,
            step_id=None,
            timeout_profile=None,
            max_tokens_override=None,
        ):  # noqa: ANN001
            _ = prompt_envelope
            raise LLMUnavailableError("narrative provider chain exhausted | kind=NARRATIVE_NETWORK")

        def author_assist_two_stage_with_fallback(
            self,
            db,
            *,
            task: str,
            locale: str,
            context: dict,
            session_id=None,
            step_id=None,
            timeout_profile=None,
            expand_max_tokens_override=None,
            build_max_tokens_override=None,
            repair_max_tokens_override=None,
            expand_temperature_override=None,
            build_temperature_override=None,
            repair_temperature_override=None,
        ):  # noqa: ANN001
            raise LLMUnavailableError("author assist provider chain exhausted | kind=ASSIST_NETWORK")

    monkeypatch.setattr(author_assist, "get_llm_runtime", lambda: _UnavailableRuntime())

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": "seed_expand",
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert resp.status_code == 503
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "ASSIST_LLM_UNAVAILABLE"
    assert detail.get("message") == "LLM unavailable, please retry."
    assert detail.get("retryable") is True
    assert isinstance(detail.get("hint"), str) and detail.get("hint")


def test_author_assist_returns_503_on_invalid_llm_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    from app.modules.story import author_assist

    class _InvalidPayloadRuntime:
        def author_assist_with_fallback(
            self,
            db,
            *,
            prompt: str,
            prompt_envelope=None,
            session_id=None,
            step_id=None,
            timeout_profile=None,
            max_tokens_override=None,
        ):  # noqa: ANN001
            _ = prompt_envelope
            return {"foo": "bar"}, True

        def author_assist_two_stage_with_fallback(
            self,
            db,
            *,
            task: str,
            locale: str,
            context: dict,
            session_id=None,
            step_id=None,
            timeout_profile=None,
            expand_max_tokens_override=None,
            build_max_tokens_override=None,
            repair_max_tokens_override=None,
            expand_temperature_override=None,
            build_temperature_override=None,
            repair_temperature_override=None,
        ):  # noqa: ANN001
            return {"foo": "bar"}, True

    monkeypatch.setattr(author_assist, "get_llm_runtime", lambda: _InvalidPayloadRuntime())

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": "seed_expand",
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert resp.status_code == 503
    detail = resp.json().get("detail") or {}
    assert detail.get("code") == "ASSIST_INVALID_OUTPUT"
    assert detail.get("message") == "Assist output was invalid. Please retry."
    assert detail.get("retryable") is True


def test_author_assist_long_wait_tasks_pass_timeout_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_db(tmp_path)
    runtime = _patch_runtime(
        monkeypatch,
        payload_by_task={
            "*": {
                "suggestions": {"ok": True},
                "patch_preview": [],
                "warnings": [],
            }
        },
    )
    client = TestClient(app)
    context = _base_context()

    for task in ["seed_expand", "story_ingest", "continue_write", "consistency_check"]:
        response = client.post(
            "/stories/author-assist",
            json={
                "task": task,
                "locale": "en",
                "context": context,
            },
        )
        assert response.status_code == 200

    profile_by_task = {entry["task"]: entry["timeout_profile"] for entry in runtime.calls}
    for task in ("seed_expand", "story_ingest", "continue_write"):
        profile = profile_by_task.get(task)
        assert isinstance(profile, LLMTimeoutProfile)
        assert profile.disable_total_deadline is True
        assert profile.call_timeout_s is None
        assert profile.read_timeout_s is None
        assert isinstance(profile.connect_timeout_s, float) and profile.connect_timeout_s > 0
        call = next(entry for entry in runtime.calls if entry["task"] == task)
        assert call["mode"] == "two_stage"
        assert call["expand_max_tokens_override"] == 1400
        assert call["build_max_tokens_override"] == 2048
        assert call["repair_max_tokens_override"] == 900
        assert call["expand_temperature_override"] == pytest.approx(0.0)
        assert call["build_temperature_override"] == pytest.approx(0.0)
        assert call["repair_temperature_override"] == pytest.approx(0.0)

    assert profile_by_task.get("consistency_check") is None
    consistency_call = next(entry for entry in runtime.calls if entry["task"] == "consistency_check")
    assert consistency_call["mode"] == "single_stage"
    assert consistency_call["max_tokens_override"] == 2048


def test_seed_expand_is_normalized_to_four_node_tension_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_db(tmp_path)
    _patch_runtime(
        monkeypatch,
        payload_by_task={
            "seed_expand": {
                "suggestions": {
                    "meta": {
                        "story_id": "assist_story",
                        "version": 1,
                        "title": "Assist Story",
                        "locale": "zh",
                    },
                    "flow": {
                        "start_scene_key": "scene_intro",
                        "scenes": [
                            {
                                "scene_key": "scene_intro",
                                "title": "Morning Pressure",
                                "setup": "Generic setup",
                                "options": [
                                    {
                                        "option_key": "opt_a",
                                        "label": "Take action",
                                        "action_type": "study",
                                        "go_to": "scene_afternoon",
                                    },
                                    {
                                        "option_key": "opt_b",
                                        "label": "Take another action",
                                        "action_type": "work",
                                        "go_to": "scene_afternoon",
                                    },
                                ],
                            },
                            {
                                "scene_key": "scene_afternoon",
                                "title": "Afternoon",
                                "setup": "Generic close",
                                "is_end": True,
                                "options": [
                                    {"option_key": "end_a", "label": "Finish", "action_type": "study"},
                                    {"option_key": "end_b", "label": "Finish softly", "action_type": "date"},
                                ],
                            },
                        ],
                    },
                },
                "patch_preview": [],
                "warnings": [],
            }
        },
    )
    client = TestClient(app)
    context = _base_context()
    context["seed_text"] = "你发现室友抄袭你的项目，一周内奖学金将决定你的去留。"

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": "seed_expand",
            "locale": "zh",
            "context": context,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    flow = (body.get("suggestions") or {}).get("flow") or {}
    scenes = flow.get("scenes") or []
    assert len(scenes) == 4
    assert [scene.get("scene_key") for scene in scenes] == [
        "pressure_open",
        "pressure_escalation",
        "recovery_window",
        "decision_gate",
    ]
    assert flow.get("start_scene_key") == "pressure_open"
    first_labels = [str(item.get("label") or "") for item in (scenes[0].get("options") or [])]
    assert any(("室友" in label or "奖学金" in label) for label in first_labels)
    patch_paths = {str(item.get("path") or "") for item in (body.get("patch_preview") or [])}
    assert "flow" in patch_paths
    assert "format_version" in patch_paths
    assert "entry_mode" in patch_paths
    warning_text = " ".join(str(item) for item in (body.get("warnings") or []))
    assert "4-node tension loop" in warning_text or "tension loop" in warning_text
    assert "pipeline_trace: two_stage/seed_expand expand->build" in warning_text


def test_seed_expand_syncs_ending_rules_to_existing_scene_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_db(tmp_path)
    _patch_runtime(
        monkeypatch,
        payload_by_task={
            "seed_expand": {
                "suggestions": {
                    "flow": {
                        "start_scene_key": "pressure_open",
                        "scenes": [
                            {"scene_key": "pressure_open", "title": "Open", "setup": "open", "options": [{"option_key": "o1", "label": "Push", "action_type": "study"}]},
                            {"scene_key": "pressure_escalation", "title": "Escalate", "setup": "escalate", "options": [{"option_key": "o2", "label": "Escalate", "action_type": "study"}]},
                            {"scene_key": "recovery_window", "title": "Recover", "setup": "recover", "options": [{"option_key": "o3", "label": "Recover", "action_type": "rest"}]},
                            {"scene_key": "decision_gate", "title": "Decide", "setup": "decide", "is_end": True, "options": [{"option_key": "o4", "label": "Decide", "action_type": "study"}]},
                        ],
                    }
                },
                "patch_preview": [],
                "warnings": [],
            }
        },
    )
    client = TestClient(app)
    context = _base_context()
    context["draft"] = {
        "flow": {
            "start_scene_key": "scene_intro",
            "scenes": [{"scene_key": "scene_intro"}, {"scene_key": "scene_afternoon"}],
        },
        "ending": {
            "ending_rules": [
                {
                    "ending_key": "legacy_end",
                    "title": "Legacy End",
                    "priority": 80,
                    "outcome": "mixed",
                    "trigger": {"scene_key_is": "scene_intro"},
                    "epilogue": "legacy",
                }
            ]
        },
    }

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": "seed_expand",
            "locale": "en",
            "context": context,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    ending_patch = next(
        (item for item in (body.get("patch_preview") or []) if str(item.get("path") or "") == "ending.ending_rules"),
        None,
    )
    assert isinstance(ending_patch, dict)
    ending_rules = ending_patch.get("value") or []
    assert isinstance(ending_rules, list) and ending_rules
    trigger_scene = (((ending_rules[0] or {}).get("trigger") or {}).get("scene_key_is"))
    assert trigger_scene == "decision_gate"


def test_seed_expand_supplements_npc_roster_and_preserves_existing_npc(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    context = _base_context()
    context["draft"] = {
        "characters": {
            "npcs": [{"name": "Kai", "role": "support friend", "traits": ["loyal"]}],
        }
    }

    resp = client.post(
        "/stories/author-assist",
        json={
            "task": "seed_expand",
            "locale": "en",
            "context": context,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    suggestions = body.get("suggestions") if isinstance(body.get("suggestions"), dict) else {}
    characters = suggestions.get("characters") if isinstance(suggestions.get("characters"), dict) else {}
    npcs = characters.get("npcs") if isinstance(characters.get("npcs"), list) else []
    assert 3 <= len(npcs) <= 6
    assert any(isinstance(item, dict) and str(item.get("name") or "").strip() == "Kai" for item in npcs)

    roster_patch = next(
        (item for item in (body.get("patch_preview") or []) if str(item.get("path") or "").strip() == "characters.npcs"),
        None,
    )
    assert isinstance(roster_patch, dict)
    patched_npcs = roster_patch.get("value") if isinstance(roster_patch.get("value"), list) else []
    assert 3 <= len(patched_npcs) <= 6


def test_author_assist_stream_continue_write_emits_stage_then_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    from app.modules.story import author_assist

    class _StreamRuntime:
        def author_assist_two_stage_with_fallback(
            self,
            db,
            *,
            task: str,
            locale: str,
            context: dict,
            session_id=None,
            step_id=None,
            timeout_profile=None,
            expand_max_tokens_override=None,
            build_max_tokens_override=None,
            repair_max_tokens_override=None,
            expand_temperature_override=None,
            build_temperature_override=None,
            repair_temperature_override=None,
            stage_emitter=None,
        ):  # noqa: ANN001
            _ = (
                db,
                context,
                session_id,
                step_id,
                timeout_profile,
                expand_max_tokens_override,
                build_max_tokens_override,
                repair_max_tokens_override,
                expand_temperature_override,
                build_temperature_override,
                repair_temperature_override,
            )
            emit_stage(stage_emitter, stage_code="author.expand.start", locale=locale, task=task)
            emit_stage(stage_emitter, stage_code="author.cast.start", locale=locale, task=task)
            emit_stage(
                stage_emitter,
                stage_code="author.build.start",
                locale=locale,
                task=task,
                overview_source="author_idea_blueprint_v1",
                overview_rows=[
                    {"label": "Core Conflict", "value": "student vs roommate | deadline one week"},
                    {"label": "Tension Loop", "value": "pressure_open -> pressure_escalation -> recovery_window -> decision_gate"},
                    {"label": "Branch Contrast", "value": "high-risk push vs recovery stabilize"},
                    {"label": "Lexical Anchors", "value": "must include roommate, scholarship"},
                    {"label": "Task Focus", "value": "Append a follow-up beat while preserving conflict contrast."},
                ],
            )
            return (
                {
                    "suggestions": {"outline": "ok"},
                    "patch_preview": [{"id": "p1", "path": "flow", "label": "Update flow", "value": {}}],
                    "warnings": [],
                },
                True,
            )

        def author_assist_with_fallback(self, *args, **kwargs):  # noqa: ANN001
            raise AssertionError("unexpected single-stage call in continue_write test")

    monkeypatch.setattr(author_assist, "get_llm_runtime", lambda: _StreamRuntime())

    response = client.post(
        "/stories/author-assist/stream",
        json={
            "task": "continue_write",
            "locale": "zh",
            "context": _base_context(),
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    events = _parse_sse_events(response.text)
    assert events

    stage_codes = [payload.get("stage_code") for event, payload in events if event == "stage"]
    assert stage_codes[:3] == ["author.expand.start", "author.cast.start", "author.build.start"]

    stage_labels = [payload.get("label") for event, payload in events if event == "stage"]
    assert "正在发送第一次续写请求..." in stage_labels
    assert "正在发送角色架构请求..." in stage_labels
    assert "正在发送完整架构请求..." in stage_labels

    build_stage = next(
        payload
        for event, payload in events
        if event == "stage" and payload.get("stage_code") == "author.build.start"
    )
    assert build_stage.get("overview_source") == "author_idea_blueprint_v1"
    overview_rows = build_stage.get("overview_rows")
    assert isinstance(overview_rows, list) and overview_rows
    assert any(isinstance(row, dict) and row.get("label") == "Core Conflict" for row in overview_rows)

    result_events = [payload for event, payload in events if event == "result"]
    assert len(result_events) == 1
    result = result_events[0]
    assert isinstance(result.get("suggestions"), dict)
    assert isinstance(result.get("patch_preview"), list)
    assert isinstance(result.get("warnings"), list)
    assert isinstance(result.get("model"), str) and result["model"]


@pytest.mark.parametrize("task", ["seed_expand", "story_ingest"])
def test_author_assist_stream_parse_all_tasks_include_overview_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task: str,
) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    from app.modules.story import author_assist

    class _StreamRuntime:
        def author_assist_two_stage_with_fallback(
            self,
            db,
            *,
            task: str,
            locale: str,
            context: dict,
            session_id=None,
            step_id=None,
            timeout_profile=None,
            expand_max_tokens_override=None,
            build_max_tokens_override=None,
            repair_max_tokens_override=None,
            expand_temperature_override=None,
            build_temperature_override=None,
            repair_temperature_override=None,
            stage_emitter=None,
        ):  # noqa: ANN001
            _ = (
                db,
                context,
                session_id,
                step_id,
                timeout_profile,
                expand_max_tokens_override,
                build_max_tokens_override,
                repair_max_tokens_override,
                expand_temperature_override,
                build_temperature_override,
                repair_temperature_override,
            )
            emit_stage(stage_emitter, stage_code="author.expand.start", locale=locale, task=task)
            emit_stage(stage_emitter, stage_code="author.cast.start", locale=locale, task=task)
            emit_stage(
                stage_emitter,
                stage_code="author.build.start",
                locale=locale,
                task=task,
                overview_source="author_idea_blueprint_v1",
                overview_rows=[
                    {"label": "Core Conflict", "value": "A vs B under a hard deadline"},
                    {"label": "Tension Loop", "value": "open -> escalate -> recover -> decide"},
                    {"label": "Branch Contrast", "value": "push vs stabilize"},
                    {"label": "Lexical Anchors", "value": "must include domain terms"},
                    {"label": "Task Focus", "value": "Preserve branch contrast"},
                ],
            )
            return (
                {
                    "suggestions": {"outline": "ok"},
                    "patch_preview": [{"id": "p1", "path": "flow", "label": "Update flow", "value": {}}],
                    "warnings": [],
                },
                True,
            )

        def author_assist_with_fallback(self, *args, **kwargs):  # noqa: ANN001
            raise AssertionError("unexpected single-stage call in parse-all task stream test")

    monkeypatch.setattr(author_assist, "get_llm_runtime", lambda: _StreamRuntime())

    response = client.post(
        "/stories/author-assist/stream",
        json={
            "task": task,
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    build_stage = next(
        payload
        for event, payload in events
        if event == "stage" and payload.get("stage_code") == "author.build.start"
    )
    stage_codes = [payload.get("stage_code") for event, payload in events if event == "stage"]
    assert stage_codes[:3] == ["author.expand.start", "author.cast.start", "author.build.start"]
    assert build_stage.get("overview_source") == "author_idea_blueprint_v1"
    assert isinstance(build_stage.get("overview_rows"), list) and build_stage["overview_rows"]


def test_author_assist_stream_skips_cast_stage_when_existing_cast_is_sufficient(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    context = _base_context()
    context["draft"] = {
        "characters": {
            "npcs": [
                {"name": "Alice", "role": "support friend", "traits": ["warm"]},
                {"name": "Reed", "role": "rival competitor", "traits": ["sharp"]},
                {"name": "Professor Lin", "role": "gatekeeper advisor", "traits": ["strict"]},
            ]
        }
    }

    response = client.post(
        "/stories/author-assist/stream",
        json={
            "task": "continue_write",
            "locale": "en",
            "context": context,
        },
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    stage_codes = [payload.get("stage_code") for event, payload in events if event == "stage"]
    assert "author.expand.start" in stage_codes
    assert "author.build.start" in stage_codes
    assert "author.cast.start" not in stage_codes


def test_author_assist_stream_rejects_unknown_task_with_error_event(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/stories/author-assist/stream",
        json={
            "task": "bad_task",
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert len(events) == 1
    event_name, payload = events[0]
    assert event_name == "error"
    assert payload.get("status") == 422
    detail = payload.get("detail") or {}
    assert detail.get("code") == "ASSIST_TASK_V4_REQUIRED"


def test_author_assist_stream_llm_failure_emits_error_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    from app.modules.story import author_assist

    class _FailRuntime:
        def author_assist_two_stage_with_fallback(self, *args, **kwargs):  # noqa: ANN001
            raise LLMUnavailableError("author assist provider chain exhausted | kind=ASSIST_NETWORK")

        def author_assist_with_fallback(self, *args, **kwargs):  # noqa: ANN001
            raise LLMUnavailableError("narrative provider chain exhausted | kind=NARRATIVE_NETWORK")

    monkeypatch.setattr(author_assist, "get_llm_runtime", lambda: _FailRuntime())

    response = client.post(
        "/stories/author-assist/stream",
        json={
            "task": "seed_expand",
            "locale": "en",
            "context": _base_context(),
        },
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events
    event_name, payload = events[-1]
    assert event_name == "error"
    assert payload.get("status") == 503
    detail = payload.get("detail") or {}
    assert detail.get("code") == "ASSIST_LLM_UNAVAILABLE"
