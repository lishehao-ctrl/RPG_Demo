from __future__ import annotations

from app.modules.narrative.state_engine import default_initial_state, normalize_state
from app.modules.narrative.state_patch_engine import apply_effect_ops, compact_npc_memories


def test_apply_effect_ops_updates_inventory_npc_status_and_flags() -> None:
    state = normalize_state(default_initial_state())
    out, metrics = apply_effect_ops(
        state,
        {
            "inventory_ops": [
                {"op": "add_stack", "item_id": "potion_small", "qty": 2},
                {"op": "grant_currency", "currency": "gold", "amount": 5},
            ],
            "npc_ops": [
                {
                    "npc_id": "alice",
                    "relation": {"trust": 3},
                    "beliefs": {"player_reliable": 0.2},
                }
            ],
            "status_ops": [
                {
                    "target": "player",
                    "status_id": "well_rested",
                    "op": "add",
                    "stacks": 1,
                    "ttl_steps": 4,
                }
            ],
            "world_flag_ops": [
                {"key": "festival_week", "value": True},
            ],
        },
    )

    inventory = out["inventory_state"]
    assert inventory["stack_items"]["potion_small"]["qty"] == 2
    assert inventory["currency"]["gold"] >= 55

    alice = out["npc_state"]["alice"]
    assert alice["relation"]["trust"] == 3
    assert alice["beliefs"]["player_reliable"] == 0.2

    player_effects = out["external_status"]["player_effects"]
    assert any(item["status_id"] == "well_rested" for item in player_effects)
    assert out["external_status"]["world_flags"]["festival_week"] is True

    assert metrics["inventory_mutation_count"] >= 1
    assert metrics["npc_mutation_count"] >= 1
    assert metrics["status_mutation_count"] >= 1
    assert metrics["world_flag_mutation_count"] >= 1


def test_compact_npc_memories_moves_overflow_into_long_refs() -> None:
    state = normalize_state(default_initial_state())
    state["run_state"]["step_index"] = 10
    state["npc_state"] = {
        "alice": {
            "relation": {"trust": 10},
            "mood": {},
            "beliefs": {},
            "active_goals": [],
            "status_effects": [],
            "short_memory": [
                {
                    "mem_id": f"m_{idx}",
                    "type": "event",
                    "content": f"memory {idx}",
                    "importance": 0.5,
                    "created_step": idx,
                    "ttl_steps": None,
                }
                for idx in range(15)
            ],
            "long_memory_refs": [],
            "last_seen_step": 9,
        }
    }

    out, metrics = compact_npc_memories(
        state,
        short_memory_limit=6,
        long_memory_ref_limit=120,
    )
    alice = out["npc_state"]["alice"]
    assert len(alice["short_memory"]) == 6
    assert len(alice["long_memory_refs"]) == 6
    assert metrics["short_memory_compacted_count"] >= 6
