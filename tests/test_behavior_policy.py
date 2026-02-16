import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session as db_session
from app.db.models import SessionCharacterState
from app.main import app
from app.modules.llm.schemas import NarrativeOutput, PlayerInputClassification
from app.modules.narrative.behavior_policy import BehaviorPolicy, CharacterProfile, derive_behavior_policy

ROOT = Path(__file__).resolve().parents[1]


def _prepare_db(tmp_path: Path) -> None:
    db_path = tmp_path / "behavior_policy.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    db_session.rebind_engine(f"sqlite+pysqlite:///{db_path}")


def _extract_prompt_payload(prompt: str) -> dict:
    marker = '{"memory_summary"'
    idx = prompt.rfind(marker)
    assert idx >= 0, "prompt payload json marker not found"
    return json.loads(prompt[idx:])


def test_behavior_policy_tier_mapping_is_deterministic() -> None:
    profile = CharacterProfile(character_id="npc_a", archetype="default")
    expected_by_trust = {
        0: {"disclosure_level": "closed", "helpfulness": 10, "aggression": 70},
        24: {"disclosure_level": "closed", "helpfulness": 10, "aggression": 70},
        25: {"disclosure_level": "guarded", "helpfulness": 30, "aggression": 50},
        49: {"disclosure_level": "guarded", "helpfulness": 30, "aggression": 50},
        50: {"disclosure_level": "balanced", "helpfulness": 50, "aggression": 30},
        74: {"disclosure_level": "balanced", "helpfulness": 50, "aggression": 30},
        75: {"disclosure_level": "open", "helpfulness": 75, "aggression": 15},
        100: {"disclosure_level": "transparent", "helpfulness": 95, "aggression": 5},
    }

    for trust, expected in expected_by_trust.items():
        p1 = derive_behavior_policy(profile, trust)
        p2 = derive_behavior_policy(profile, trust)
        assert p1.model_dump() == expected
        assert p2.model_dump() == expected


class _CaptureRuntime:
    def __init__(self) -> None:
        self.prompt: str | None = None

    def classify_with_fallback(self, db, *, text: str, session_id, step_id=None):
        return (
            PlayerInputClassification(
                intent="friendly",
                tone="calm",
                behavior_tags=["kind"],
                risk_tags=[],
                confidence=0.9,
            ),
            True,
        )

    def narrative_with_fallback(self, db, *, prompt: str, session_id, step_id=None):
        self.prompt = prompt
        return (
            NarrativeOutput(
                narrative_text="ok",
                choices=[
                    {"id": "c1", "text": "A", "type": "dialog"},
                    {"id": "c2", "text": "B", "type": "action"},
                ],
            ),
            True,
        )


def test_step_prompt_includes_behavior_policy_json(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    from app.modules.session import service as session_service

    runtime = _CaptureRuntime()
    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)

    client = TestClient(app)
    sid = uuid.UUID(client.post("/sessions").json()["id"])
    with db_session.SessionLocal() as db:
        state = db.execute(select(SessionCharacterState).where(SessionCharacterState.session_id == sid)).scalars().first()
        assert state is not None
        state.score_visible = 73
        state.relation_vector = {"trust": 0.73, "respect": 0.4, "fear": 0.1, "attraction": 0.2}
        db.commit()

    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert resp.status_code == 200
    assert runtime.prompt is not None

    payload = _extract_prompt_payload(runtime.prompt)
    assert "behavior_policy" in payload
    policy = payload["behavior_policy"]
    assert policy["disclosure_level"]
    assert policy["helpfulness"] >= 0
    assert policy["aggression"] >= 0


def test_policy_contract_is_valid_json(tmp_path: Path, monkeypatch) -> None:
    _prepare_db(tmp_path)
    from app.modules.session import service as session_service

    runtime = _CaptureRuntime()
    monkeypatch.setattr(session_service, "get_llm_runtime", lambda: runtime)

    client = TestClient(app)
    sid = client.post("/sessions").json()["id"]
    resp = client.post(f"/sessions/{sid}/step", json={"input_text": "hello"})
    assert resp.status_code == 200
    assert runtime.prompt is not None

    payload = _extract_prompt_payload(runtime.prompt)
    policy_blob = json.dumps(payload["behavior_policy"], ensure_ascii=False)
    parsed = BehaviorPolicy.model_validate_json(policy_blob)
    assert parsed.model_dump().keys() == {"disclosure_level", "helpfulness", "aggression"}
