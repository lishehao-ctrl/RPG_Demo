from __future__ import annotations

from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.play_v2.contracts import UrbanTurnIntent
from rpg_backend.play_v2.runtime import (
    _storylet_hint_prompt_section,
    apply_turn_resolution,
    build_initial_world_state,
)


def test_npc_mind_states_stay_non_none_after_one_turn() -> None:
    plan = run_author_v3_pipeline("office board power", run_mode="deterministic")["plan"]
    state = build_initial_world_state(plan, session_id="npc_mind_serialize")
    target_id = next(iter(state.npc_mind_states))

    state, _ = apply_turn_resolution(
        plan,
        state,
        UrbanTurnIntent(
            input_text="试着靠近他",
            move_family="flirt",
            target_id=target_id,
            scene_frame="private",
        ),
    )

    retained_ids = [
        npc_id
        for npc_id, mind in state.npc_mind_states.items()
        if mind.pressure_load is not None
        and mind.humiliation_risk is not None
        and mind.betrayal_readiness is not None
    ]

    assert retained_ids

    dumped = state.model_dump(mode="json")
    assert "npc_minds" not in dumped
    dumped_mind = dumped["npc_mind_states"][retained_ids[0]]
    assert dumped_mind["pressure_load"] is not None
    assert dumped_mind["humiliation_risk"] is not None
    assert dumped_mind["betrayal_readiness"] is not None


def test_storylet_prompt_section_uses_mandatory_language() -> None:
    section = _storylet_hint_prompt_section(
        [
            {
                "storylet_id": "storylet_required",
                "function": "hook",
                "scene_text": "董事会录音从补印稿里滑出来，黑色账本压在长桌尽头。",
                "venue_hint": "董事会议室",
                "match_score": 0.91,
                "dramatic_weight": 0.8,
                "cooldown_turns": 1,
                "matched_conditions": ["required_segment_roles"],
                "preconditions": {
                    "required_secrets_known": [],
                    "required_relationships": [],
                    "required_segment_roles": ["opening"],
                    "min_tension_score": 0.3,
                },
                "effects": {
                    "secrets_revealed": ["sec_board"],
                    "relationship_shifts": {},
                    "tension_delta": 0.2,
                    "triggers_chain": None,
                },
            }
        ]
    )

    assert "不是可选灵感" in section
    assert "\"storylet_id\":\"storylet_required\"" in section
