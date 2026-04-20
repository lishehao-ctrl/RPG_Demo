from __future__ import annotations

from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.play_v2.contracts import UrbanTurnIntent
from rpg_backend.play_v2.director import EventDirector
from rpg_backend.play_v2.runtime import build_initial_world_state


def _play_plan():
    preview, _ = run_preview_blueprint_graph("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。")
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan


def test_director_prefers_public_reveal_in_reveal_segment() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    segment = next(item for item in plan.segments if item.segment_role == "reveal")
    state.segment_index = plan.segments.index(segment)
    state.secret_exposure = 2
    target_id = (segment.rival_target_ids or segment.focus_target_ids)[0]

    preferred = EventDirector.preferred_burst_move(
        plan=plan,
        segment=segment,
        state=state,
        target_id=target_id,
        candidates=["probe_secret", "public_reveal", "accuse"],
    )

    assert preferred == "public_reveal"


def test_director_forces_public_event_and_costs_on_reveal_burst() -> None:
    plan = _play_plan()
    state = build_initial_world_state(plan)
    segment = next(item for item in plan.segments if item.segment_role == "reveal")
    state.segment_index = plan.segments.index(segment)
    state.scene_frame = "public"
    state.secret_exposure = 2
    target_id = (segment.rival_target_ids or segment.focus_target_ids)[0]

    outcome = EventDirector.direct_turn_outcome(
        plan=plan,
        segment=segment,
        intent=UrbanTurnIntent(
            input_text="我要现在就翻牌。",
            lane_id="burst",
            move_family="public_reveal",
            target_id=target_id,
            scene_frame="public",
            confidence="high",
        ),
        state=state,
    )

    assert outcome.forced_public_event is True
    assert outcome.public_event_text is not None
    assert outcome.no_return_text is not None
    assert outcome.collateral_global_deltas["public_image"] <= -2
    assert outcome.collateral_global_deltas["secret_exposure"] >= 1
