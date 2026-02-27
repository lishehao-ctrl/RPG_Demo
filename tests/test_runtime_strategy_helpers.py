from __future__ import annotations

import uuid

from app.db.models import ActionLog, Session as GameSession, User
from app.db.session import SessionLocal
from app.modules.runtime.service import _build_ending_report_brief, _resolve_nudge_tier
from app.modules.runtime.state import default_state


def test_resolve_nudge_tier_boundaries() -> None:
    assert _resolve_nudge_tier(fallback_reason="NO_MATCH", consecutive_fallback_count=1) == "soft"
    assert _resolve_nudge_tier(fallback_reason="OFF_TOPIC", consecutive_fallback_count=1) == "soft"
    assert _resolve_nudge_tier(fallback_reason="LOW_CONF", consecutive_fallback_count=1) == "neutral"
    assert _resolve_nudge_tier(fallback_reason="NO_MATCH", consecutive_fallback_count=2) == "neutral"
    assert _resolve_nudge_tier(fallback_reason="INPUT_POLICY", consecutive_fallback_count=1) == "firm"
    assert _resolve_nudge_tier(fallback_reason="LOW_CONF", consecutive_fallback_count=3) == "firm"


def test_build_ending_report_brief_uses_global_stats_and_recent_12() -> None:
    with SessionLocal() as db:
        with db.begin():
            user = User(id=str(uuid.uuid4()), external_ref="u1", display_name="u1")
            db.add(user)
            sess = GameSession(
                id=str(uuid.uuid4()),
                user_id=user.id,
                story_id="story_x",
                story_version=1,
                status="active",
                story_node_id="n1",
                state_json=default_state(),
            )
            db.add(sess)

            source_cycle = ["explicit", "rule", "llm", "fallback"]
            for idx in range(1, 16):
                source = source_cycle[(idx - 1) % len(source_cycle)]
                fallback_reason = "NO_MATCH" if source == "fallback" else None
                db.add(
                    ActionLog(
                        session_id=sess.id,
                        step_index=idx,
                        request_payload_json={"player_input": f"step {idx}"},
                        selection_result_json={
                            "attempted_choice_id": None,
                            "executed_choice_id": f"c_{idx}",
                            "fallback_used": source == "fallback",
                            "fallback_reason": fallback_reason,
                            "selection_mode": "free_input",
                            "selection_source": source,
                            "mapping_confidence": 0.5,
                        },
                        state_before=default_state(),
                        state_delta={"energy": -1 if source == "fallback" else 0},
                        state_after=default_state(),
                        llm_trace_json={"provider": "fake", "schemas": ["story_narrative_v1"]},
                        classification_json={"selection_source": source},
                    )
                )

        state_after = default_state()
        state_after["energy"] = 72
        state_after["money"] = 55
        state_after["knowledge"] = 7
        state_after["affection"] = 2
        run_state = state_after["run_state"]
        run_state["step_index"] = 16
        run_state["fallback_count"] = 4

        brief = _build_ending_report_brief(
            db,
            session_id=sess.id,
            state_after=state_after,
            current_step_index=16,
            current_executed_choice_id="fallback:fb_low_conf",
            current_fallback_reason="LOW_CONF",
            current_selection_source="fallback",
            current_state_delta={"energy": -1},
            recent_window=12,
        )

        stats = brief["session_stats"]
        assert stats["total_steps"] == 16
        assert stats["fallback_count"] == 4
        assert stats["fallback_source_count"] == 4
        assert stats["explicit_count"] == 4
        assert stats["rule_count"] == 4
        assert stats["llm_count"] == 4

        beats = brief["recent_action_beats"]
        assert len(beats) == 12
        assert beats[0]["step_index"] == 5
        assert beats[-1]["step_index"] == 16
        assert beats[-1]["selection_source"] == "fallback"
