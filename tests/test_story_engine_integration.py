import uuid
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.db import session as db_session
from app.db.models import ActionLog, Story
from app.main import app
from app.modules.llm.adapter import LLMRuntime
from app.modules.llm.schemas import NarrativeOutput
from tests.support.db_runtime import prepare_sqlite_db
from tests.support.story_narrative_assertions import (
    assert_no_internal_story_tokens,
    assert_no_system_error_style_phrases,
)
from tests.support.story_seed import seed_story_pack

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    prepare_sqlite_db(tmp_path, "story_engine.db")


def _seed_story_pack_raw(story_id: str, version: int, pack: dict, is_published: bool = True) -> None:
    with db_session.SessionLocal() as db:
        with db.begin():
            db.add(
                Story(
                    story_id=story_id,
                    version=version,
                    is_published=is_published,
                    pack_json=pack,
                    created_at=datetime.now(timezone.utc),
                )
            )


def _make_pack(
    story_id: str = "s1",
    version: int = 1,
    *,
    blocked_choice_requires: dict | None = None,
    node_fallback_choice_id: str | None = None,
    node_fallback_choice_requires: dict | None = None,
    include_global_executor: bool = False,
    node_intents: list[dict] | None = None,
    quests: list[dict] | None = None,
    events: list[dict] | None = None,
    endings: list[dict] | None = None,
    run_config: dict | None = None,
) -> dict:
    n1, n2, n3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    choice_c1 = {
        "choice_id": "c1",
        "display_text": "Study",
        "action": {"action_id": "study", "params": {}},
        "next_node_id": n2,
        "is_key_decision": False,
    }
    if blocked_choice_requires is not None:
        choice_c1["requires"] = blocked_choice_requires

    choice_c2 = {
        "choice_id": "c2",
        "display_text": "Rest",
        "action": {"action_id": "rest", "params": {}},
        "next_node_id": n2,
        "is_key_decision": False,
    }
    if node_fallback_choice_requires is not None:
        choice_c2["requires"] = node_fallback_choice_requires

    pack: dict = {
        "story_id": story_id,
        "version": version,
        "title": "Tiny Story",
        "start_node_id": n1,
        "characters": [{"id": "alice", "name": "Alice"}],
        "initial_state": {"flags": {}},
        "nodes": [
            {
                "node_id": n1,
                "scene_brief": "Start",
                "is_end": False,
                "choices": [choice_c1, choice_c2],
                "intents": node_intents or [],
                "fallback": {
                    "id": "fb_n1",
                    "action": {"action_id": "rest", "params": {}},
                    "next_node_id_policy": "explicit_next",
                    "next_node_id": n2,
                    "text_variants": {
                        "NO_INPUT": "You hesitate and lose your timing.",
                        "BLOCKED": "That path is blocked for now, so you steady yourself.",
                        "FALLBACK": "Your intent is unclear, so you hold position.",
                        "DEFAULT": "You pause to reassess.",
                    },
                },
                "node_fallback_choice_id": node_fallback_choice_id,
            },
            {
                "node_id": n2,
                "scene_brief": "Middle",
                "is_end": False,
                "choices": [
                    {
                        "choice_id": "c3",
                        "display_text": "Work",
                        "action": {"action_id": "work", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c4",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                ],
                "fallback": {
                    "id": "fb_n2",
                    "action": {"action_id": "rest", "params": {}},
                    "next_node_id_policy": "explicit_next",
                    "next_node_id": n3,
                    "text_variants": {"DEFAULT": "You pause."},
                },
            },
            {
                "node_id": n3,
                "scene_brief": "End",
                "is_end": True,
                "choices": [
                    {
                        "choice_id": "c5",
                        "display_text": "Rest",
                        "action": {"action_id": "rest", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                    {
                        "choice_id": "c6",
                        "display_text": "Work",
                        "action": {"action_id": "work", "params": {}},
                        "next_node_id": n3,
                        "is_key_decision": False,
                    },
                ],
            },
        ],
    }
    if include_global_executor:
        pack["fallback_executors"] = [
            {
                "id": "fb_global",
                "action_id": "rest",
                "action_params": {},
                "effects": {"energy": 1},
                "prereq": {"min_energy": 999},
                "next_node_id": n2,
                "narration": {"skeleton": "You slow down and regroup."},
            }
        ]
        pack["global_fallback_choice_id"] = "fb_global"
    if quests is not None:
        pack["quests"] = quests
    if events is not None:
        pack["events"] = events
    if endings is not None:
        pack["endings"] = endings
    if run_config is not None:
        pack["run_config"] = run_config
    return pack


def _publish_pack(client: TestClient, pack: dict) -> None:
    _ = client
    seed_story_pack(pack=pack, is_published=True)


def _load_example_story_pack(filename: str) -> dict:
    path = ROOT / "examples" / "storypacks" / filename
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_action_log(session_id: str | uuid.UUID) -> ActionLog:
    sid = uuid.UUID(str(session_id))
    with db_session.SessionLocal() as db:
        log = db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == sid)
            .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
        ).scalars().first()
        assert log is not None
        return log


def test_story_session_advances_nodes_by_choice_id(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_adv", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_adv"}).json()["id"]
    state0 = client.get(f"/sessions/{sid}").json()
    assert state0["current_node_id"] == pack["start_node_id"]

    step1 = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step1.status_code == 200
    body = step1.json()
    assert body["executed_choice_id"] == "c1"
    assert body["resolved_choice_id"] == "c1"
    assert body["fallback_used"] is False
    assert body["fallback_reason"] is None
    assert "affection_delta" not in body
    assert "cost" not in body

    state1 = client.get(f"/sessions/{sid}").json()
    assert state1["current_node_id"] == pack["nodes"][1]["node_id"]


def test_story_step_invalid_choice_soft_falls_back_with_200(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_invalid", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_invalid"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"choice_id": "bad"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["attempted_choice_id"] == "bad"
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "FALLBACK"
    assert_no_internal_story_tokens(body["narrative_text"])
    assert_no_system_error_style_phrases(body["narrative_text"])


def test_story_step_player_input_no_match_falls_back_with_200(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_no_match", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_no_match"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "LLM_UNAVAILABLE"


def test_story_step_free_input_fallback_reads_as_acknowledge_plus_redirect(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_ack_redirect", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_ack_redirect"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"player_input": "Play RPG game with Alice"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "LLM_UNAVAILABLE"


def test_story_step_free_input_fallback_paraphrases_chickfila_without_quote(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_chickfila_paraphrase", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_chickfila_paraphrase"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"player_input": "Having a Chick-fila"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "LLM_UNAVAILABLE"


def test_story_step_player_input_intent_alias_executes_visible_choice(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_intent_alias",
        1,
        node_intents=[
            {
                "intent_id": "INTENT_ASK_INFO",
                "alias_choice_id": "c1",
                "description": "Gather information before committing.",
                "patterns": ["ask around", "gather intel"],
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_intent_alias"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"player_input": "i want to gather intel first"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "LLM_UNAVAILABLE"


def test_story_step_campus_week_free_input_can_progress_without_constant_fallback(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _load_example_story_pack("campus_week_v1.json")
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "campus_week_v1"}).json()["id"]

    state_before_first = client.get(f"/sessions/{sid}").json()
    visible_first = {item["id"] for item in (state_before_first.get("current_node") or {}).get("choices", [])}
    first = client.post(f"/sessions/{sid}/step", json={"player_input": "study"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["fallback_used"] is False
    assert first_body["executed_choice_id"] in visible_first

    state_before_second = client.get(f"/sessions/{sid}").json()
    visible_second = {item["id"] for item in (state_before_second.get("current_node") or {}).get("choices", [])}
    second = client.post(f"/sessions/{sid}/step", json={"player_input": "library"})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["fallback_used"] is False
    assert second_body["executed_choice_id"] in visible_second

    state_before_third = client.get(f"/sessions/{sid}").json()
    visible_third = {item["id"] for item in (state_before_third.get("current_node") or {}).get("choices", [])}
    third = client.post(f"/sessions/{sid}/step", json={"player_input": "push final"})
    assert third.status_code == 200
    third_body = third.json()
    assert third_body["fallback_used"] is False
    assert third_body["executed_choice_id"] in visible_third


def test_story_step_free_input_prompt_alignment_and_compact_context(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_prompt_alignment", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _PromptAwareProvider:
        def __init__(self):
            self.narrative_prompt = ""

        @staticmethod
        def _usage(model: str) -> dict:
            return {
                "model": model,
                "prompt_tokens": 42,
                "completion_tokens": 12,
                "latency_ms": 1,
                "status": "success",
                "error_message": None,
            }

        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            prompt_text = str(prompt or "")
            prompt_lower = prompt_text.lower()
            if "story selection task" in prompt_lower:
                return (
                    {
                        "choice_id": "c1",
                        "use_fallback": False,
                        "confidence": 0.9,
                        "intent_id": None,
                        "notes": "selector_match",
                    },
                    self._usage(model),
                )
            if "story narration task" in prompt_lower:
                self.narrative_prompt = prompt_text
                raw_ctx = prompt_text.split("Context:", 1)[1].strip()
                ctx = json.loads(raw_ctx)
                player_input = str(ctx.get("player_input_raw") or "").strip()
                selection = ctx.get("selection_resolution") or {}
                action_id = str(selection.get("selected_action_id") or "action")
                impacts = ", ".join(str(item) for item in (ctx.get("impact_brief") or []))
                text = f"You commit to '{player_input}'. It resolves as a {action_id} action."
                if impacts:
                    text = f"{text} Impact: {impacts}."
                return ({"narrative_text": text}, self._usage(model))
            return ({"narrative_text": "[llm] ok"}, self._usage(model))

    runtime = LLMRuntime()
    provider = _PromptAwareProvider()
    runtime.providers["fake"] = provider

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_prompt_alignment"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"player_input": "study hard tonight"})
        assert step.status_code == 200
        body = step.json()
        assert body["fallback_used"] is False
        assert body["executed_choice_id"] == "c1"
        assert "study hard tonight" in body["narrative_text"]
        assert "study action" in body["narrative_text"]

        assert provider.narrative_prompt
        assert '"input_mode":"free_input"' in provider.narrative_prompt
        assert '"impact_brief"' in provider.narrative_prompt
        assert '"state_before"' not in provider.narrative_prompt
        assert '"state_after"' not in provider.narrative_prompt

        prompt_ctx = json.loads(provider.narrative_prompt.split("Context:", 1)[1].strip())
        selection_ctx = prompt_ctx.get("selection_resolution") or {}
        assert selection_ctx.get("selected_choice_label")
        assert selection_ctx.get("selected_action_id") == "study"
        quest_nudge_ctx = prompt_ctx.get("quest_nudge") or {}
        assert quest_nudge_ctx.get("enabled") is False
        assert quest_nudge_ctx.get("mode") == "off"
    finally:
        pass


def test_story_step_free_input_quest_nudge_event_driven_in_prompt_context(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_prompt_quest_nudge_event",
        1,
        quests=[
            {
                "quest_id": "q_weekly_plan",
                "title": "Weekly Plan",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "stage_foundation",
                        "title": "Foundation",
                        "milestones": [
                            {
                                "milestone_id": "m_start_study",
                                "title": "Start with study",
                                "when": {"executed_choice_id_is": "c1"},
                            },
                            {
                                "milestone_id": "m_keep_open",
                                "title": "Keep momentum",
                                "when": {"executed_choice_id_is": "c2"},
                            },
                        ],
                    }
                ],
            }
        ],
    )
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _QuestNudgePromptProvider:
        def __init__(self):
            self.narrative_contexts: list[dict] = []

        @staticmethod
        def _usage(model: str) -> dict:
            return {
                "model": model,
                "prompt_tokens": 32,
                "completion_tokens": 10,
                "latency_ms": 1,
                "status": "success",
                "error_message": None,
            }

        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            prompt_text = str(prompt or "")
            prompt_lower = prompt_text.lower()
            if "story selection task" in prompt_lower:
                return (
                    {
                        "choice_id": "c1",
                        "use_fallback": False,
                        "confidence": 0.92,
                        "intent_id": None,
                        "notes": "selector_match",
                    },
                    self._usage(model),
                )
            if "story narration task" in prompt_lower:
                raw_ctx = prompt_text.split("Context:", 1)[1].strip()
                self.narrative_contexts.append(json.loads(raw_ctx))
                return ({"narrative_text": "You push ahead and keep your momentum."}, self._usage(model))
            return ({"narrative_text": "[llm] ok"}, self._usage(model))

    runtime = LLMRuntime()
    provider = _QuestNudgePromptProvider()
    runtime.providers["fake"] = provider

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_prompt_quest_nudge_event"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"player_input": "study now"})
        assert step.status_code == 200
        assert provider.narrative_contexts
        ctx = provider.narrative_contexts[-1]
        quest_nudge = ctx.get("quest_nudge") or {}
        assert quest_nudge.get("enabled") is True
        assert quest_nudge.get("mode") == "event_driven"
        assert quest_nudge.get("mainline_hint")
        if quest_nudge.get("sideline_hint"):
            assert "quest_id" not in str(quest_nudge.get("sideline_hint")).lower()
        for blocked in ("main quest", "side quest", "objective", "stage", "milestone"):
            assert blocked not in str(quest_nudge.get("mainline_hint") or "").lower()
            assert blocked not in str(quest_nudge.get("sideline_hint") or "").lower()
    finally:
        pass


def test_story_step_free_input_quest_nudge_cadence_hits_every_third_step(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_prompt_quest_nudge_cadence",
        1,
        quests=[
            {
                "quest_id": "q_weekly_plan",
                "title": "Weekly Plan",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "stage_foundation",
                        "title": "Foundation",
                        "milestones": [
                            {
                                "milestone_id": "m_never_hit",
                                "title": "Hidden check",
                                "when": {"executed_choice_id_is": "c2"},
                            }
                        ],
                    }
                ],
            }
        ],
    )
    start_node_id = str(pack["start_node_id"])
    for choice in (pack["nodes"][0].get("choices") or []):
        if isinstance(choice, dict):
            choice["next_node_id"] = start_node_id
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _CadencePromptProvider:
        def __init__(self):
            self.quest_nudges: list[dict] = []

        @staticmethod
        def _usage(model: str) -> dict:
            return {
                "model": model,
                "prompt_tokens": 28,
                "completion_tokens": 8,
                "latency_ms": 1,
                "status": "success",
                "error_message": None,
            }

        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            prompt_text = str(prompt or "")
            if "story selection task" in prompt_text.lower():
                return (
                    {
                        "choice_id": "c1",
                        "use_fallback": False,
                        "confidence": 0.9,
                        "intent_id": None,
                        "notes": "selector_match",
                    },
                    self._usage(model),
                )
            if "story narration task" in prompt_text.lower():
                ctx = json.loads(prompt_text.split("Context:", 1)[1].strip())
                self.quest_nudges.append(dict(ctx.get("quest_nudge") or {}))
                return ({"narrative_text": "You keep moving through the day."}, self._usage(model))
            return ({"narrative_text": "[llm] ok"}, self._usage(model))

    runtime = LLMRuntime()
    provider = _CadencePromptProvider()
    runtime.providers["fake"] = provider

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_prompt_quest_nudge_cadence"}).json()["id"]
        for _ in range(3):
            step = client.post(f"/sessions/{sid}/step", json={"player_input": "study"})
            assert step.status_code == 200

        assert len(provider.quest_nudges) == 3
        assert provider.quest_nudges[0].get("enabled") is False
        assert provider.quest_nudges[1].get("enabled") is False
        assert provider.quest_nudges[2].get("enabled") is True
        assert provider.quest_nudges[2].get("mode") == "cadence"
    finally:
        pass


def test_story_step_free_input_narrative_removes_system_jargon(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_free_input_naturalized", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _JargonNarrativeProvider:
        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            if "story selection task" in str(prompt).lower():
                return (
                    {
                        "choice_id": "c1",
                        "use_fallback": False,
                        "confidence": 0.92,
                        "intent_id": "INTENT_STUDY",
                        "notes": "selector_match",
                    },
                    {
                        "model": model,
                        "prompt_tokens": 12,
                        "completion_tokens": 6,
                        "latency_ms": 1,
                        "status": "success",
                        "error_message": None,
                    },
                )
            return (
                {
                    "narrative_text": (
                        "You decided to do math problems, which mapped to heading to class and studying. "
                        "Your intent was clear and confidence was high."
                    )
                },
                {
                    "model": model,
                    "prompt_tokens": 12,
                    "completion_tokens": 6,
                    "latency_ms": 1,
                    "status": "success",
                    "error_message": None,
                },
            )

    runtime = LLMRuntime()
    runtime.providers["fake"] = _JargonNarrativeProvider()

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_free_input_naturalized"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"player_input": "do math problems"})
        assert step.status_code == 200
        body = step.json()
        assert body["fallback_used"] is False
        text = str(body["narrative_text"]).lower()
        assert "mapped to" not in text
        assert "mapping" not in text
        assert "intent" not in text
        assert "choice_id" not in text
        assert "selected_action_id" not in text
        assert "confidence" not in text
        for blocked in ("for this turn", "the scene", "story keeps moving"):
            assert blocked not in text
    finally:
        pass


def test_story_step_button_path_narrative_soft_avoids_system_like_phrases(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_button_narrative_soft_avoid", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _ButtonPhraseProvider:
        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            return (
                {
                    "narrative_text": "For this turn, the scene responds and the story keeps moving.",
                },
                {
                    "model": model,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "latency_ms": 1,
                    "status": "success",
                    "error_message": None,
                },
            )

    runtime = LLMRuntime()
    runtime.providers["fake"] = _ButtonPhraseProvider()

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_button_narrative_soft_avoid"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
        assert step.status_code == 200
        text = str(step.json()["narrative_text"]).lower()
        for blocked in ("for this turn", "the scene", "story keeps moving"):
            assert blocked not in text
    finally:
        pass


def test_story_step_free_input_fallback_path_keeps_existing_narration_channel(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_free_input_fallback_guard", 1)
    _publish_pack(client, pack)

    original_flag = settings.story_fallback_llm_enabled
    settings.story_fallback_llm_enabled = False
    try:
        sid = client.post("/sessions", json={"story_id": "s_free_input_fallback_guard"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"player_input": "??? ???"})
        assert step.status_code == 503
        assert step.json()["detail"]["code"] == "LLM_UNAVAILABLE"
    finally:
        settings.story_fallback_llm_enabled = original_flag


def test_story_step_free_input_fallback_can_include_subtle_quest_nudge(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_free_input_fallback_quest_nudge",
        1,
        quests=[
            {
                "quest_id": "q_weekly_plan",
                "title": "Weekly Plan",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "stage_foundation",
                        "title": "Foundation",
                        "milestones": [
                            {
                                "milestone_id": "m_fallback_once",
                                "title": "Regain footing",
                                "when": {"fallback_used_is": True},
                            },
                            {
                                "milestone_id": "m_still_open",
                                "title": "Follow the weekly rhythm",
                                "when": {"executed_choice_id_is": "c1"},
                            },
                        ],
                    }
                ],
            }
        ],
    )
    _publish_pack(client, pack)

    original_flag = settings.story_fallback_llm_enabled
    settings.story_fallback_llm_enabled = False
    try:
        sid = client.post("/sessions", json={"story_id": "s_free_input_fallback_quest_nudge"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"player_input": "???"})
        assert step.status_code == 503
        assert step.json()["detail"]["code"] == "LLM_UNAVAILABLE"
    finally:
        settings.story_fallback_llm_enabled = original_flag


def test_story_pack_campus_week_fallback_variant_avoids_fuzzy_phrase() -> None:
    pack = _load_example_story_pack("campus_week_v1.json")
    text = str(((pack.get("default_fallback") or {}).get("text_variants") or {}).get("FALLBACK") or "")
    assert "your intention is fuzzy" not in text.lower()


def test_story_step_campus_week_noise_input_still_falls_back(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _load_example_story_pack("campus_week_v1.json")
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "campus_week_v1"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "LLM_UNAVAILABLE"


def test_story_step_campus_week_runtime_events_trigger_on_play_path(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _load_example_story_pack("campus_week_v1.json")
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "campus_week_v1"}).json()["id"]
    # Stay on the weekly loop to reach day/slot windows where runtime events should fire.
    path = ["c_study", "c_library", "c_sleep", "c_study", "c_library", "c_sleep"]

    observed_event_ids: list[str] = []
    for choice_id in path:
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": choice_id})
        assert step.status_code == 200
        state = client.get(f"/sessions/{sid}").json()
        run_state = (state.get("state_json") or {}).get("run_state") or {}
        observed_event_ids = [str(item) for item in (run_state.get("triggered_event_ids") or []) if str(item)]
        if observed_event_ids:
            break

    assert observed_event_ids, "expected at least one runtime event in campus_week_v1 play path"
    assert any(
        event_id in {"ev_pop_quiz", "ev_side_job", "ev_recover_focus"} for event_id in observed_event_ids
    )


def test_story_step_llm_unavailable_has_no_progress(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_usage_ops", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_usage_ops"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert step.status_code == 503

    with db_session.SessionLocal() as db:
        action_count = db.execute(
            select(func.count()).select_from(ActionLog).where(ActionLog.session_id == uuid.UUID(sid))
        ).scalar_one()
    assert action_count == 0


def test_story_step_idempotency_replay_does_not_duplicate_progress(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_idem_replay", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_idem_replay"}).json()["id"]
    headers = {"X-Idempotency-Key": "story-idem-1"}
    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers=headers)
    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()

    with db_session.SessionLocal() as db:
        logs = db.execute(
            select(ActionLog)
            .where(ActionLog.session_id == uuid.UUID(sid))
            .order_by(ActionLog.created_at.asc(), ActionLog.id.asc())
        ).scalars().all()
    assert len(logs) == 1


def test_story_step_llm_network_retry_can_recover(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_llm_retry_recover", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _FlakyProvider:
        def __init__(self):
            self.calls = 0

        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("forced connect error", request=httpx.Request("POST", "https://example.com"))
            return (
                {
                    "narrative_text": "[llm] retry recovered narration",
                    "choices": [
                        {"id": "c1", "text": "Reply", "type": "dialog"},
                        {"id": "c2", "text": "Wait", "type": "action"},
                    ],
                },
                {
                    "model": model,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "latency_ms": 1,
                    "status": "success",
                    "error_message": None,
                },
            )

    runtime = LLMRuntime()
    flaky = _FlakyProvider()
    runtime.providers["fake"] = flaky

    original_network_retries = settings.llm_retry_attempts_network
    original_llm_retries = settings.llm_max_retries
    original_deadline = settings.llm_total_deadline_s
    settings.llm_retry_attempts_network = 2
    settings.llm_max_retries = 1
    settings.llm_total_deadline_s = 10.0
    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_llm_retry_recover"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
        assert step.status_code == 200
        body = step.json()
        assert body["narrative_text"] == "[llm] retry recovered narration"
        assert flaky.calls >= 2
    finally:
        settings.llm_retry_attempts_network = original_network_retries
        settings.llm_max_retries = original_llm_retries
        settings.llm_total_deadline_s = original_deadline


def test_story_step_llm_network_retry_exhausted_returns_503_without_progress(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_llm_retry_fallback", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _AlwaysTimeoutProvider:
        def __init__(self):
            self.calls = 0

        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            self.calls += 1
            raise httpx.ReadTimeout("forced read timeout", request=httpx.Request("POST", "https://example.com"))

    runtime = LLMRuntime()
    provider = _AlwaysTimeoutProvider()
    runtime.providers["fake"] = provider

    original_network_retries = settings.llm_retry_attempts_network
    original_llm_retries = settings.llm_max_retries
    original_deadline = settings.llm_total_deadline_s
    settings.llm_retry_attempts_network = 2
    settings.llm_max_retries = 1
    settings.llm_total_deadline_s = 1.0
    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_llm_retry_fallback"}).json()["id"]
        before = client.get(f"/sessions/{sid}").json()
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
        assert step.status_code == 503
        assert step.json()["detail"]["code"] == "LLM_UNAVAILABLE"
        after = client.get(f"/sessions/{sid}").json()
        assert after["current_node_id"] == before["current_node_id"]
        assert after["state_json"] == before["state_json"]
        assert provider.calls >= 1
    finally:
        settings.llm_retry_attempts_network = original_network_retries
        settings.llm_max_retries = original_llm_retries
        settings.llm_total_deadline_s = original_deadline


def test_story_step_narrative_non_json_repair_can_recover(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_narrative_parse_repair", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _NarrativeRepairProvider:
        def __init__(self):
            self.calls = 0
            self.repair_calls = 0

        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            self.calls += 1
            if "narrative repair task" in str(prompt).lower():
                self.repair_calls += 1
                return (
                    {"narrative_text": "[llm] repaired narrative text"},
                    {
                        "model": model,
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "latency_ms": 1,
                        "status": "success",
                        "error_message": None,
                    },
                )
            return (
                "non-json narrative payload",
                {
                    "model": model,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "latency_ms": 1,
                    "status": "success",
                    "error_message": None,
                },
            )

    runtime = LLMRuntime()
    provider = _NarrativeRepairProvider()
    runtime.providers["fake"] = provider

    original_network_retries = settings.llm_retry_attempts_network
    original_llm_retries = settings.llm_max_retries
    original_deadline = settings.llm_total_deadline_s
    settings.llm_retry_attempts_network = 1
    settings.llm_max_retries = 1
    settings.llm_total_deadline_s = 10.0
    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_narrative_parse_repair"}).json()["id"]
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
        assert step.status_code == 503
        assert step.json()["detail"]["code"] == "LLM_UNAVAILABLE"
        assert provider.repair_calls == 0
    finally:
        settings.llm_retry_attempts_network = original_network_retries
        settings.llm_max_retries = original_llm_retries
        settings.llm_total_deadline_s = original_deadline


def test_story_step_narrative_parse_failure_returns_503_without_progress(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_narrative_parse_fail", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _NarrativeParseFailProvider:
        async def generate(
            self,
            prompt: str,
            *,
            request_id: str,
            timeout_s: float,
            model: str,
            connect_timeout_s: float | None = None,
            read_timeout_s: float | None = None,
            write_timeout_s: float | None = None,
            pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
        ):
            return (
                "non-json narrative payload forever",
                {
                    "model": model,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "latency_ms": 1,
                    "status": "success",
                    "error_message": None,
                },
            )

    runtime = LLMRuntime()
    runtime.providers["fake"] = _NarrativeParseFailProvider()

    original_network_retries = settings.llm_retry_attempts_network
    original_llm_retries = settings.llm_max_retries
    original_deadline = settings.llm_total_deadline_s
    settings.llm_retry_attempts_network = 1
    settings.llm_max_retries = 1
    settings.llm_total_deadline_s = 10.0
    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)
    try:
        sid = client.post("/sessions", json={"story_id": "s_narrative_parse_fail"}).json()["id"]
        before = client.get(f"/sessions/{sid}").json()
        step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
        assert step.status_code == 503
        assert step.json()["detail"]["code"] == "LLM_UNAVAILABLE"
        after = client.get(f"/sessions/{sid}").json()
        assert after["current_node_id"] == before["current_node_id"]
        assert after["state_json"] == before["state_json"]
    finally:
        settings.llm_retry_attempts_network = original_network_retries
        settings.llm_max_retries = original_llm_retries
        settings.llm_total_deadline_s = original_deadline


def test_story_step_no_input_maps_to_fallback_with_200(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_no_input", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_no_input"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "NO_INPUT"
    assert_no_internal_story_tokens(body["narrative_text"])


def test_story_step_parse_error_maps_to_fallback(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_parse_error", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _Runtime:
        def select_story_choice_with_fallback(self, *_args, **_kwargs):
            raise ValueError("forced parse error")

        def narrative_with_fallback(self, _db, *, prompt: str, session_id, step_id=None):
            return (
                NarrativeOutput(
                    narrative_text="[fallback] The scene advances quietly. Choose the next move.",
                ),
                True,
            )

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: _Runtime())

    sid = client.post("/sessions", json={"story_id": "s_parse_error"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
    assert step.status_code == 503
    assert step.json()["detail"]["code"] == "LLM_UNAVAILABLE"


def test_story_step_prereq_blocked_prefers_node_fallback_choice(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_blocked_pref",
        1,
        blocked_choice_requires={"min_money": 999},
        node_fallback_choice_id="c2",
        include_global_executor=True,
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_blocked_pref"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "BLOCKED"
    assert body["executed_choice_id"] == "c2"


def test_story_step_rerouted_target_prereq_fail_degrades_without_second_reroute(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_blocked_degraded",
        1,
        blocked_choice_requires={"min_money": 999},
        node_fallback_choice_id="c2",
        node_fallback_choice_requires={"min_energy": 999},
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_blocked_degraded"}).json()["id"]
    state_before = client.get(f"/sessions/{sid}").json()

    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200
    body = step.json()
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "BLOCKED"

    state_after = client.get(f"/sessions/{sid}").json()
    for key in ("energy", "money", "knowledge", "affection", "day", "slot"):
        assert state_after["state_json"][key] == state_before["state_json"][key]
    assert (state_after["state_json"].get("run_state") or {}).get("fallback_count") == 1
    assert state_after["current_node_id"] == state_before["current_node_id"]

    log = _latest_action_log(sid)
    markers = list(log.fallback_reasons or [])
    assert "REROUTE_LIMIT_REACHED_DEGRADED" in markers
    assert "REROUTED_TARGET_PREREQ_BLOCKED_DEGRADED" in markers


def test_story_step_updates_quest_progress_and_rewards_once(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_quest_progress",
        1,
        quests=[
            {
                "quest_id": "q_first_study",
                "title": "First Study",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "Opening",
                        "milestones": [
                            {
                                "milestone_id": "m_c1",
                                "title": "Choose Study",
                                "when": {"executed_choice_id_is": "c1"},
                                "rewards": {"money": 4},
                            }
                        ],
                        "stage_rewards": {"knowledge": 2},
                    },
                    {
                        "stage_id": "s2",
                        "title": "Work Follow-up",
                        "milestones": [
                            {
                                "milestone_id": "m_c3",
                                "title": "Choose Work",
                                "when": {"executed_choice_id_is": "c3"},
                                "rewards": {"money": 1},
                            }
                        ],
                        "stage_rewards": {"affection": 1},
                    },
                ],
                "completion_rewards": {"money": 2},
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_quest_progress"}).json()["id"]
    state_before = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_before["money"] == 50
    assert state_before["knowledge"] == 0

    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert first.status_code == 200
    assert first.json()["fallback_used"] is False
    state_after_first = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_first["money"] == 54
    assert state_after_first["knowledge"] == 4

    quest_state = state_after_first.get("quest_state") or {}
    assert "q_first_study" in (quest_state.get("active_quests") or [])
    assert "q_first_study" not in (quest_state.get("completed_quests") or [])
    q1_state = (quest_state.get("quests") or {}).get("q_first_study") or {}
    assert q1_state.get("current_stage_id") == "s2"
    recent_event_types = [str(item.get("type")) for item in (quest_state.get("recent_events") or [])]
    assert "milestone_completed" in recent_event_types
    assert "stage_completed" in recent_event_types
    assert "stage_activated" in recent_event_types

    log = _latest_action_log(sid)
    quest_rules = [item for item in (log.matched_rules or []) if isinstance(item, dict) and item.get("type") == "quest_progress"]
    assert quest_rules

    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert second.status_code == 200
    state_after_second = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_second["money"] == 77
    assert state_after_second["knowledge"] == 4
    assert state_after_second["affection"] == 1
    quest_state_second = state_after_second.get("quest_state") or {}
    assert "q_first_study" in (quest_state_second.get("completed_quests") or [])

    third = client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"})
    assert third.status_code == 200
    state_after_third = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_third["money"] == 77


def test_story_fallback_step_can_advance_quest_from_fallback_flag(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_quest_fallback",
        1,
        quests=[
            {
                "quest_id": "q_fallback",
                "title": "Recover Composure",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "Fallback Stage",
                        "milestones": [
                            {
                                "milestone_id": "m_fallback_once",
                                "title": "Trigger one fallback",
                                "when": {"fallback_used_is": True},
                                "rewards": {"affection": 2},
                            }
                        ],
                    }
                ],
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_quest_fallback"}).json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={})
    assert resp.status_code == 200
    assert resp.json()["fallback_used"] is True
    assert resp.json()["fallback_reason"] == "NO_INPUT"

    state_after = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after["affection"] == 2
    quest_state = state_after.get("quest_state") or {}
    assert "q_fallback" in (quest_state.get("completed_quests") or [])


def test_story_later_stage_trigger_does_not_fire_early(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_stage_order_guard",
        1,
        quests=[
            {
                "quest_id": "q_stage_guard",
                "title": "Order Matters",
                "auto_activate": True,
                "stages": [
                    {
                        "stage_id": "s1",
                        "title": "Open",
                        "milestones": [
                            {
                                "milestone_id": "m_open",
                                "title": "Choose c1 first",
                                "when": {"executed_choice_id_is": "c1"},
                            }
                        ],
                    },
                    {
                        "stage_id": "s2",
                        "title": "Then Work",
                        "milestones": [
                            {
                                "milestone_id": "m_work",
                                "title": "Choose c3",
                                "when": {"executed_choice_id_is": "c3"},
                            }
                        ],
                    },
                ],
            }
        ],
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_stage_order_guard"}).json()["id"]
    first = client.post(f"/sessions/{sid}/step", json={"choice_id": "c2"})
    assert first.status_code == 200
    second = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert second.status_code == 200

    quest_state = client.get(f"/sessions/{sid}").json()["state_json"].get("quest_state") or {}
    q_state = (quest_state.get("quests") or {}).get("q_stage_guard") or {}
    assert q_state.get("current_stage_id") == "s1"
    s2 = ((q_state.get("stages") or {}).get("s2") or {})
    m_work = ((s2.get("milestones") or {}).get("m_work") or {})
    assert m_work.get("done") is False
    assert "q_stage_guard" not in (quest_state.get("completed_quests") or [])


def test_story_fallback_narrative_leak_guard(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_leak_guard", 1)
    _publish_pack(client, pack)

    from app.modules.session import service as session_service

    class _Runtime:
        def narrative_with_fallback(self, _db, *, prompt: str, session_id, step_id=None):
            if "fallback rewrite" in prompt.lower():
                return (
                    NarrativeOutput(
                        narrative_text="This leaks NO_MATCH and next_node_id.",
                    ),
                    True,
                )
            return (
                NarrativeOutput(
                    narrative_text="[llm] baseline",
                ),
                True,
            )

    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: _Runtime())

    original_flag = settings.story_fallback_llm_enabled
    settings.story_fallback_llm_enabled = True
    try:
        sid = client.post("/sessions", json={"story_id": "s_leak_guard"}).json()["id"]
        resp = client.post(f"/sessions/{sid}/step", json={"player_input": "nonsense ???"})
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "LLM_UNAVAILABLE"
    finally:
        settings.story_fallback_llm_enabled = original_flag


def test_story_step_inactive_session_returns_409_session_not_active(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_inactive_story", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_inactive_story"}).json()["id"]
    assert client.post(f"/sessions/{sid}/end").status_code == 200

    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 409
    assert step.json()["detail"]["code"] == "SESSION_NOT_ACTIVE"


def test_story_runtime_event_once_per_run_applies_only_once(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_event_once",
        1,
        events=[
            {
                "event_id": "ev_once",
                "title": "One-time encounter",
                "weight": 1,
                "once_per_run": True,
                "cooldown_steps": 0,
                "trigger": {"node_id_is": None},
                "effects": {"affection": 2},
            }
        ],
        run_config={"max_days": 30, "max_steps": 40, "default_timeout_outcome": "neutral"},
    )
    # Trigger only at node n3 where repeated loops are possible.
    pack["events"][0]["trigger"]["node_id_is"] = pack["nodes"][2]["node_id"]
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_event_once"}).json()["id"]
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}).status_code == 200
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"}).status_code == 200
    third = client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"})
    fourth = client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"})
    assert third.status_code == 200
    assert fourth.status_code == 200

    state = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state["affection"] == 2
    run_state = state.get("run_state") or {}
    triggered = [item for item in (run_state.get("triggered_event_ids") or []) if item == "ev_once"]
    assert len(triggered) == 1


def test_story_runtime_event_cooldown_blocks_immediate_retrigger(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_event_cooldown",
        1,
        events=[
            {
                "event_id": "ev_cd",
                "title": "Repeatable encounter",
                "weight": 1,
                "once_per_run": False,
                "cooldown_steps": 2,
                "trigger": {"node_id_is": None},
                "effects": {"money": 3},
            }
        ],
        run_config={"max_days": 30, "max_steps": 40, "default_timeout_outcome": "neutral"},
    )
    pack["events"][0]["trigger"]["node_id_is"] = pack["nodes"][2]["node_id"]
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_event_cooldown"}).json()["id"]
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}).status_code == 200
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"}).status_code == 200
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"}).status_code == 200
    state_after_first_hit = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_first_hit["money"] == 73
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"}).status_code == 200
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"}).status_code == 200
    state_after_cooldown = client.get(f"/sessions/{sid}").json()["state_json"]
    assert state_after_cooldown["money"] == 73
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c5"}).status_code == 200
    final_state = client.get(f"/sessions/{sid}").json()["state_json"]
    assert final_state["money"] == 76


def test_story_ending_priority_and_step_response_fields(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_ending_priority",
        1,
        endings=[
            {
                "ending_id": "ending_neutral",
                "title": "Neutral Close",
                "priority": 20,
                "outcome": "neutral",
                "trigger": {"node_id_is": None},
                "epilogue": "A calm close.",
            },
            {
                "ending_id": "ending_success",
                "title": "Success Close",
                "priority": 10,
                "outcome": "success",
                "trigger": {"node_id_is": None},
                "epilogue": "A bright finish.",
            },
        ],
        run_config={"max_days": 30, "max_steps": 40, "default_timeout_outcome": "neutral"},
    )
    pack["endings"][0]["trigger"]["node_id_is"] = pack["nodes"][1]["node_id"]
    pack["endings"][1]["trigger"]["node_id_is"] = pack["nodes"][1]["node_id"]
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_ending_priority"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200
    body = step.json()
    assert body["run_ended"] is True
    assert body["ending_id"] == "ending_success"
    assert body["ending_outcome"] == "success"

    blocked = client.post(f"/sessions/{sid}/step", json={"choice_id": "c3"})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "SESSION_NOT_ACTIVE"


def test_story_timeout_ending_from_run_config(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack(
        "s_timeout_ending",
        1,
        run_config={"max_days": 30, "max_steps": 1, "default_timeout_outcome": "fail"},
    )
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_timeout_ending"}).json()["id"]
    step = client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"})
    assert step.status_code == 200
    body = step.json()
    assert body["run_ended"] is True
    assert body["ending_id"] == "__timeout__"
    assert body["ending_outcome"] == "fail"


def test_get_story_returns_raw_pack_json_wrapper_unchanged(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)

    raw_pack = _make_pack("s_raw", 1)
    raw_pack["nodes"][0]["fallback"]["text_variants"]["FALLBACK"] = {
        "en": "Fallback EN",
        "zh": "Fallback ZH",
    }
    _seed_story_pack_raw("s_raw", 1, raw_pack, is_published=True)

    got = client.get("/stories/s_raw", params={"version": 1})
    assert got.status_code == 200
    assert got.json()["pack"] == raw_pack


def test_replay_story_only_payload_contract(tmp_path: Path) -> None:
    _prepare_db(tmp_path)
    client = TestClient(app)
    pack = _make_pack("s_replay_contract", 1)
    _publish_pack(client, pack)

    sid = client.post("/sessions", json={"story_id": "s_replay_contract"}).json()["id"]
    assert client.post(f"/sessions/{sid}/step", json={"choice_id": "c1"}).status_code == 200
    assert client.post(f"/sessions/{sid}/end").status_code == 200

    replay = client.get(f"/sessions/{sid}/replay")
    assert replay.status_code == 200
    body = replay.json()
    assert body["session_id"] == str(sid)
    assert "total_steps" in body
    assert "key_decisions" in body
    assert "fallback_summary" in body
    assert "story_path" in body
    assert "state_timeline" in body
    assert "run_summary" in body
    run_summary = body["run_summary"]
    assert isinstance(run_summary, dict)
    assert "ending_id" in run_summary
    assert "ending_outcome" in run_summary
    assert "total_steps" in run_summary
    assert "triggered_events_count" in run_summary
    assert "fallback_rate" in run_summary
    assert "route_type" not in body
    assert "decision_points" not in body
    assert "affection_timeline" not in body
    assert "affection_attribution" not in body
    assert "missed_routes" not in body
    assert "what_if" not in body
