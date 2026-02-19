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
    node_ids = {n.node_id for n in pack.nodes}
    fallback_executor_ids = {item.id for item in (pack.fallback_executors or [])}
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

    if pack.default_fallback is not None:
        _validate_fallback(pack.default_fallback, "__default__")
        _track_fallback_id(pack.default_fallback)
        _validate_reserved_id(pack.default_fallback.id, "default_fallback.id")

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

    return sorted(set(errors))
