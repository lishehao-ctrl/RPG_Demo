from __future__ import annotations

from typing import Any

from app.config import settings
from app.modules.story.constants import RESERVED_CHOICE_ID_PREFIX


def validate_story_pack_structural(
    pack: Any,
    *,
    enforce_packwide_fallback_id_unique: bool | None = None,
) -> list[str]:
    errors: list[str] = []
    allowed_equipment_slots = {"weapon", "armor", "accessory"}
    node_ids = {n.node_id for n in pack.nodes}
    fallback_executor_ids = {item.id for item in (pack.fallback_executors or [])}
    item_ids = {item.item_id for item in (pack.item_defs or [])}
    item_kind_by_id = {item.item_id: str(item.kind or "").strip() for item in (pack.item_defs or [])}
    npc_ids = {item.npc_id for item in (pack.npc_defs or [])}
    status_ids = {item.status_id for item in (pack.status_defs or [])}
    status_target_by_id = {item.status_id: str(item.target or "player").strip().lower() for item in (pack.status_defs or [])}
    seen_fallback_ids: set[str] = set()
    enforce_packwide_unique = (
        settings.story_fallback_id_unique_packwide
        if enforce_packwide_fallback_id_unique is None
        else bool(enforce_packwide_fallback_id_unique)
    )

    if pack.start_node_id not in node_ids:
        errors.append(f"MISSING_START_NODE:{pack.start_node_id}")

    if pack.global_fallback_choice_id is not None:
        global_fallback_id = str(pack.global_fallback_choice_id)
        if global_fallback_id not in fallback_executor_ids:
            errors.append(f"MISSING_GLOBAL_FALLBACK_EXECUTOR:{global_fallback_id}")

    seen_item_ids: set[str] = set()
    for item_def in (pack.item_defs or []):
        item_id = str(item_def.item_id or "").strip()
        if item_id in seen_item_ids:
            errors.append(f"DUPLICATE_ITEM_ID:{item_id}")
        seen_item_ids.add(item_id)

    seen_npc_ids: set[str] = set()
    for npc_def in (pack.npc_defs or []):
        npc_id = str(npc_def.npc_id or "").strip()
        if npc_id in seen_npc_ids:
            errors.append(f"DUPLICATE_NPC_ID:{npc_id}")
        seen_npc_ids.add(npc_id)

    seen_status_ids: set[str] = set()
    for status_def in (pack.status_defs or []):
        status_id = str(status_def.status_id or "").strip()
        if status_id in seen_status_ids:
            errors.append(f"DUPLICATE_STATUS_ID:{status_id}")
        seen_status_ids.add(status_id)

    def _validate_effect_references(scope: str, effects: Any | None) -> None:
        if effects is None:
            return
        inventory_ops = getattr(effects, "inventory_ops", None) or []
        for op in inventory_ops:
            item_id = str(getattr(op, "item_id", "") or "").strip()
            op_name = str(getattr(op, "op", "") or "").strip()
            slot = str(getattr(op, "slot", "") or "").strip().lower()
            if item_ids and item_id and item_id not in item_ids:
                errors.append(f"DANGLING_INVENTORY_OP_ITEM:{scope}:{item_id}")
            if op_name == "add_instance" and item_id and item_kind_by_id.get(item_id) == "stack":
                errors.append(f"INVALID_INVENTORY_OP_ITEM_KIND:{scope}:{item_id}:stack")
            if op_name in {"equip", "unequip"} and slot and slot not in allowed_equipment_slots:
                errors.append(f"INVALID_INVENTORY_SLOT:{scope}:{slot}")

        npc_ops = getattr(effects, "npc_ops", None) or []
        for op in npc_ops:
            npc_id = str(getattr(op, "npc_id", "") or "").strip()
            if npc_ids and npc_id not in npc_ids:
                errors.append(f"DANGLING_NPC_OP_TARGET:{scope}:{npc_id}")

        status_ops = getattr(effects, "status_ops", None) or []
        for op in status_ops:
            status_id = str(getattr(op, "status_id", "") or "").strip()
            target = str(getattr(op, "target", "player") or "player").strip().lower()
            npc_id = str(getattr(op, "npc_id", "") or "").strip()
            if status_ids and status_id not in status_ids:
                errors.append(f"DANGLING_STATUS_OP_ID:{scope}:{status_id}")
            if target == "npc" and npc_ids and npc_id and npc_id not in npc_ids:
                errors.append(f"DANGLING_STATUS_OP_NPC:{scope}:{npc_id}")
            status_target = status_target_by_id.get(status_id)
            if status_target in {"player", "npc"} and target != status_target:
                errors.append(
                    f"STATUS_TARGET_MISMATCH:{scope}:{status_id}:{target}!={status_target}"
                )

        world_flag_ops = getattr(effects, "world_flag_ops", None) or []
        for op in world_flag_ops:
            key = str(getattr(op, "key", "") or "").strip()
            if not key:
                errors.append(f"INVALID_WORLD_FLAG_OP_KEY:{scope}")

    def _validate_fallback(fallback: Any, scope: str) -> None:
        policy = str(fallback.next_node_id_policy or "")
        if policy not in {"stay", "explicit_next"}:
            errors.append(f"INVALID_FALLBACK_POLICY:{scope}")
            return

        if policy == "stay":
            if fallback.next_node_id is not None:
                errors.append(f"FALLBACK_NEXT_NODE_FORBIDDEN_ON_STAY:{scope}")
            return

        next_node_id = str(fallback.next_node_id or "")
        if not next_node_id:
            errors.append(f"MISSING_FALLBACK_NEXT_NODE:{scope}")
            return
        if next_node_id not in node_ids:
            errors.append(f"DANGLING_FALLBACK_NEXT_NODE:{scope}->{next_node_id}")

    def _track_fallback_id(fallback: Any | None) -> None:
        if not fallback or not fallback.id:
            return
        if enforce_packwide_unique:
            if fallback.id in seen_fallback_ids:
                errors.append(f"DUPLICATE_FALLBACK_ID:{fallback.id}")
            seen_fallback_ids.add(fallback.id)

    def _validate_reserved_id(identifier: str | None, field_path: str) -> None:
        if not identifier:
            return
        if str(identifier).startswith(RESERVED_CHOICE_ID_PREFIX):
            errors.append(f"RESERVED_ID_PREFIX:{field_path}:{identifier}")

    for executor in (pack.fallback_executors or []):
        _validate_reserved_id(executor.id, "fallback_executor.id")
        next_node_id = str(executor.next_node_id or "")
        if next_node_id and next_node_id not in node_ids:
            errors.append(f"DANGLING_FALLBACK_EXECUTOR_NEXT_NODE:{executor.id}->{next_node_id}")
        _validate_effect_references(f"fallback_executor:{executor.id}", executor.effects)

    if pack.default_fallback is not None:
        _validate_fallback(pack.default_fallback, "__default__")
        _track_fallback_id(pack.default_fallback)
        _validate_reserved_id(pack.default_fallback.id, "default_fallback.id")
        _validate_effect_references("__default__", pack.default_fallback.effects)

    seen_choice_ids: set[str] = set()
    all_visible_choice_ids: set[str] = set()
    for node in pack.nodes:
        if not node.is_end and not (2 <= len(node.choices) <= 4):
            errors.append(f"INVALID_VISIBLE_CHOICE_COUNT:{node.node_id}")

        choice_ids = {c.choice_id for c in node.choices}

        if node.node_fallback_choice_id is not None:
            if str(node.node_fallback_choice_id) not in choice_ids:
                errors.append(f"MISSING_NODE_FALLBACK_CHOICE:{node.node_id}:{node.node_fallback_choice_id}")

        for intent in (node.intents or []):
            if intent.alias_choice_id not in choice_ids:
                errors.append(f"INTENT_ALIAS_MISSING_VISIBLE_CHOICE:{node.node_id}:{intent.intent_id}:{intent.alias_choice_id}")

        if node.fallback is not None:
            _validate_fallback(node.fallback, node.node_id)
            _track_fallback_id(node.fallback)
            if node.fallback.id and node.fallback.id in choice_ids:
                errors.append(f"FALLBACK_ID_COLLIDES_WITH_CHOICE_ID:{node.node_id}:{node.fallback.id}")
            _validate_reserved_id(node.fallback.id, f"node:{node.node_id}:fallback.id")
            _validate_effect_references(f"node_fallback:{node.node_id}", node.fallback.effects)
        elif not node.is_end and pack.default_fallback is None and pack.global_fallback_choice_id is None:
            errors.append(f"MISSING_NODE_FALLBACK:{node.node_id}")

        for choice in node.choices:
            _validate_reserved_id(choice.choice_id, f"node:{node.node_id}:choice_id")
            if choice.next_node_id not in node_ids:
                errors.append(f"DANGLING_NEXT_NODE:{choice.choice_id}->{choice.next_node_id}")
            if choice.choice_id in seen_choice_ids:
                errors.append(f"DUPLICATE_CHOICE_ID:{choice.choice_id}")
            seen_choice_ids.add(choice.choice_id)
            all_visible_choice_ids.add(choice.choice_id)
            choice_scope = f"node:{node.node_id}:choice:{choice.choice_id}:effects"
            _validate_effect_references(choice_scope, choice.effects)
            choice_v2_scope = f"node:{node.node_id}:choice:{choice.choice_id}:action_effects_v2"
            _validate_effect_references(choice_v2_scope, choice.action_effects_v2)

    seen_quest_ids: set[str] = set()
    for quest in (pack.quests or []):
        quest_id = str(quest.quest_id)
        if quest_id in seen_quest_ids:
            errors.append(f"DUPLICATE_QUEST_ID:{quest_id}")
        seen_quest_ids.add(quest_id)

        seen_stage_ids: set[str] = set()
        for stage in (quest.stages or []):
            stage_id = str(stage.stage_id)
            if stage_id in seen_stage_ids:
                errors.append(f"DUPLICATE_QUEST_STAGE_ID:{quest_id}:{stage_id}")
            seen_stage_ids.add(stage_id)

            seen_milestone_ids: set[str] = set()
            for milestone in (stage.milestones or []):
                milestone_id = str(milestone.milestone_id)
                if milestone_id in seen_milestone_ids:
                    errors.append(
                        f"DUPLICATE_QUEST_STAGE_MILESTONE_ID:{quest_id}:{stage_id}:{milestone_id}"
                    )
                seen_milestone_ids.add(milestone_id)

                trigger = milestone.when
                if trigger.node_id_is is not None and str(trigger.node_id_is) not in node_ids:
                    errors.append(
                        f"DANGLING_QUEST_TRIGGER_NODE:{quest_id}:{stage_id}:{milestone_id}:{trigger.node_id_is}"
                    )
                if trigger.next_node_id_is is not None and str(trigger.next_node_id_is) not in node_ids:
                    errors.append(
                        "DANGLING_QUEST_TRIGGER_NEXT_NODE:"
                        f"{quest_id}:{stage_id}:{milestone_id}:{trigger.next_node_id_is}"
                    )
                if (
                    trigger.executed_choice_id_is is not None
                    and str(trigger.executed_choice_id_is) not in all_visible_choice_ids
                ):
                    errors.append(
                        "DANGLING_QUEST_TRIGGER_EXECUTED_CHOICE:"
                        f"{quest_id}:{stage_id}:{milestone_id}:{trigger.executed_choice_id_is}"
                    )

    seen_event_ids: set[str] = set()
    for event in (pack.events or []):
        event_id = str(event.event_id)
        if event_id in seen_event_ids:
            errors.append(f"DUPLICATE_EVENT_ID:{event_id}")
        seen_event_ids.add(event_id)
        trigger = event.trigger
        if trigger.node_id_is is not None and str(trigger.node_id_is) not in node_ids:
            errors.append(f"DANGLING_EVENT_TRIGGER_NODE:{event_id}:{trigger.node_id_is}")

    seen_ending_ids: set[str] = set()
    for ending in (pack.endings or []):
        ending_id = str(ending.ending_id)
        if ending_id in seen_ending_ids:
            errors.append(f"DUPLICATE_ENDING_ID:{ending_id}")
        seen_ending_ids.add(ending_id)
        trigger = ending.trigger
        if trigger.node_id_is is not None and str(trigger.node_id_is) not in node_ids:
            errors.append(f"DANGLING_ENDING_TRIGGER_NODE:{ending_id}:{trigger.node_id_is}")

    return sorted(set(errors))
