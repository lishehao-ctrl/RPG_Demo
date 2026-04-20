from __future__ import annotations

from types import SimpleNamespace

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.play_v2.contracts import HookState, NarrationEventEntry, NarrationSegmentSummary, UrbanWorldState
from rpg_backend.play_v2.narration_memory import build_narration_memory_context


def _make_hook_state(
    *,
    status: str,
    leverage_value: float,
    holder_id: str,
    target_id: str,
    source_secret_id: str,
    leverage_type: str = "pressure",
) -> HookState:
    hook_id = f"{holder_id}__{target_id}__{source_secret_id}"
    return HookState(
        hook_id=hook_id,
        holder_id=holder_id,
        target_id=target_id,
        source_secret_id=source_secret_id,
        leverage_type=leverage_type,
        status=status,  # type: ignore[arg-type]
        leverage_value=leverage_value,
    )


def test_relationship_trajectory_happy_path() -> None:
    state = UrbanWorldState.model_construct(
        narration_event_log=[
            SimpleNamespace(
                fingerprint="fp_1",
                pattern_fingerprint="pat_1",
                phrase="line one",
                relationship_deltas={
                    "npc_a": {"affection": 0.6, "trust": -0.2},
                    "npc_b": {"suspicion": -0.3},
                },
            ),
            SimpleNamespace(
                fingerprint="fp_2",
                pattern_fingerprint="pat_2",
                phrase="line two",
                relationship_deltas={
                    "npc_a": {"affection": 0.2, "trust": -0.5},
                    "npc_b": {"suspicion": 0.1},
                },
            ),
            SimpleNamespace(
                fingerprint="fp_3",
                pattern_fingerprint="pat_3",
                phrase="line three",
                relationship_deltas={
                    "npc_a": {"tension": -0.6},
                    "npc_b": {"suspicion": 0.0},
                },
            ),
        ]
    )

    context = build_narration_memory_context(state)

    assert context["relationship_trajectory"] == {
        "npc_a": {"affection": "rising", "trust": "falling", "tension": "falling"},
        "npc_b": {"suspicion": "stable"},
    }


def test_active_hook_summary_filters_and_sorts_descending() -> None:
    suspected = _make_hook_state(
        status="suspected",
        leverage_value=0.42,
        holder_id="holder_c",
        target_id="target_c",
        source_secret_id="sec_c",
    )
    active = _make_hook_state(
        status="active",
        leverage_value=0.81,
        holder_id="holder_a",
        target_id="target_a",
        source_secret_id="sec_a",
        leverage_type="blackmail",
    )
    leveraged = _make_hook_state(
        status="leveraged",
        leverage_value=0.66,
        holder_id="holder_b",
        target_id="target_b",
        source_secret_id="sec_b",
        leverage_type="complicity",
    )
    dormant = _make_hook_state(
        status="dormant",
        leverage_value=0.95,
        holder_id="holder_d",
        target_id="target_d",
        source_secret_id="sec_d",
    )
    detonated = _make_hook_state(
        status="detonated",
        leverage_value=0.99,
        holder_id="holder_e",
        target_id="target_e",
        source_secret_id="sec_e",
    )
    state = UrbanWorldState.model_construct(
        hook_states={
            suspected.hook_id: suspected,
            active.hook_id: active,
            leveraged.hook_id: leveraged,
            dormant.hook_id: dormant,
            detonated.hook_id: detonated,
        }
    )

    context = build_narration_memory_context(state)

    assert context["active_hook_summary"] == [
        {
            "hook_id": active.hook_id,
            "holder_id": "holder_a",
            "target_id": "target_a",
            "leverage_type": "blackmail",
            "status": "active",
            "leverage_value": 0.81,
        },
        {
            "hook_id": leveraged.hook_id,
            "holder_id": "holder_b",
            "target_id": "target_b",
            "leverage_type": "complicity",
            "status": "leveraged",
            "leverage_value": 0.66,
        },
        {
            "hook_id": suspected.hook_id,
            "holder_id": "holder_c",
            "target_id": "target_c",
            "leverage_type": "pressure",
            "status": "suspected",
            "leverage_value": 0.42,
        },
    ]


def test_revealed_secret_summary_v3_populates_titles_and_excerpts() -> None:
    descriptions = {
        "sec_board": "A hidden recording captures the emergency board vote being rigged behind closed doors.",
        "sec_accounts": "Shadow ledgers show a long-running diversion of funds into a private acquisition vehicle.",
    }
    plan = CompiledPlayPlan.model_construct(
        organic_secrets=[
            {
                "secret_id": "sec_board",
                "title": "Board Recording",
                "description": descriptions["sec_board"],
            },
            {
                "secret_id": "sec_accounts",
                "title": "Shadow Accounts",
                "description": descriptions["sec_accounts"],
            },
        ]
    )
    state = UrbanWorldState.model_construct(last_turn_revealed_secret_ids=["sec_board", "sec_accounts"])

    context = build_narration_memory_context(state, plan=plan)

    assert context["revealed_secret_summary"] == [
        {
            "secret_id": "sec_board",
            "title": "Board Recording",
            "description_excerpt": descriptions["sec_board"][:60],
        },
        {
            "secret_id": "sec_accounts",
            "title": "Shadow Accounts",
            "description_excerpt": descriptions["sec_accounts"][:60],
        },
    ]


def test_revealed_secret_summary_v2_leaves_metadata_empty() -> None:
    plan = CompiledPlayPlan.model_construct(organic_secrets=None)
    state = UrbanWorldState.model_construct(last_turn_revealed_secret_ids=["sec_alpha", "sec_beta"])

    context = build_narration_memory_context(state, plan=plan)

    assert context["revealed_secret_summary"] == [
        {"secret_id": "sec_alpha", "title": None, "description_excerpt": None},
        {"secret_id": "sec_beta", "title": None, "description_excerpt": None},
    ]


def test_npc_pressure_snapshot_filters_to_current_turn_ids_and_rounds() -> None:
    state = UrbanWorldState.model_construct(
        npc_mind_states={
            "char_a": SimpleNamespace(
                pressure_load=3.26,
                humiliation_risk=1.94,
                betrayal_readiness=4.04,
            ),
            "char_b": SimpleNamespace(
                pressure_load=5.0,
                humiliation_risk=5.0,
                betrayal_readiness=5.0,
            ),
        }
    )

    context = build_narration_memory_context(state, current_turn_npc_ids=["char_a"])

    assert context["npc_pressure_snapshot"] == {
        "char_a": {
            "pressure_load": 3.3,
            "humiliation_risk": 1.9,
            "betrayal_readiness": 4.0,
        }
    }


def test_graceful_degradation_returns_empty_structures() -> None:
    state = UrbanWorldState.model_construct()

    context = build_narration_memory_context(state)

    assert context["relationship_trajectory"] == {}
    assert context["active_hook_summary"] == []
    assert context["revealed_secret_summary"] == []
    assert context["npc_pressure_snapshot"] == {}


def test_backward_compat_existing_fields_remain_present_and_correct() -> None:
    state = UrbanWorldState.model_construct(
        narration_event_log=[
            NarrationEventEntry(
                turn_index=1,
                fingerprint="fp_1",
                phrase="first phrase",
                pattern_fingerprint="pat_1",
                move_family="comfort",
                target_id="npc_a",
            ),
            NarrationEventEntry(
                turn_index=2,
                fingerprint="fp_2",
                phrase="second phrase",
                pattern_fingerprint="pat_2",
                move_family="accuse",
                target_id="npc_b",
            ),
        ],
        narration_segment_summaries=[
            NarrationSegmentSummary(
                segment_id="seg_1",
                segment_role="opening",
                summary_text="summary one",
                key_events=["event_a", "event_b"],
                turn_range_start=1,
                turn_range_end=2,
                entry_count=2,
            ),
            NarrationSegmentSummary(
                segment_id="seg_2",
                segment_role="pressure",
                summary_text="summary two",
                key_events=["event_c"],
                turn_range_start=3,
                turn_range_end=4,
                entry_count=1,
            ),
        ],
    )

    context = build_narration_memory_context(state)

    assert context["event_fingerprints"] == {"fp_1", "fp_2"}
    assert context["event_pattern_fingerprints"] == {"pat_1", "pat_2"}
    assert context["event_phrases"] == ["first phrase", "second phrase"]
    assert context["summary_texts"] == ["summary one", "summary two"]
    assert context["summary_key_events"] == ["event_a", "event_b", "event_c"]
