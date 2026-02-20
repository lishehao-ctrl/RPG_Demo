import json
import hashlib
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    ActionLog,
    Character,
    DialogueNode,
    LLMUsageLog,
    Session as StorySession,
    SessionStepIdempotency,
    SessionCharacterState,
    SessionSnapshot,
    Story,
)
from app.modules.llm.adapter import LLMUnavailableError, get_llm_runtime
from app.modules.llm.prompts import build_story_selection_prompt
from app.modules.llm.schemas import StorySelectionOutput
from app.modules.narrative.ending_engine import resolve_run_ending
from app.modules.narrative.event_engine import advance_runtime_events
from app.modules.narrative.quest_engine import advance_quest_state, init_quest_state, summarize_quest_for_narration
from app.modules.narrative.state_engine import default_initial_state, normalize_run_state, normalize_state
from app.modules.replay.engine import ReplayEngine, upsert_replay_report
from app.modules.session.schemas import ChoiceOut, SessionStateOut
from app.modules.session.story_choice_gating import evaluate_choice_availability
from app.modules.session.story_runtime.models import SelectionInputSource, SelectionResult
from app.modules.session.story_runtime.pipeline import StoryRuntimePipelineDeps, run_story_runtime_pipeline
from app.modules.story.constants import RESERVED_CHOICE_ID_PREFIX
from app.modules.story.fallback_narration import select_fallback_skeleton_text
from app.modules.story.mapping import RuleBasedMappingAdapter

replay_engine = ReplayEngine()
story_mapping_adapter = RuleBasedMappingAdapter()
_STORY_FALLBACK_BUILTIN_TEXT = "[fallback] The scene advances quietly. Choose the next move."
_IDEMPOTENCY_STATUS_IN_PROGRESS = "in_progress"
_IDEMPOTENCY_STATUS_SUCCEEDED = "succeeded"
_IDEMPOTENCY_STATUS_FAILED = "failed"
_STORY_NODE_UUID_NAMESPACE = uuid.UUID("baf5a739-412b-4fca-a96b-72bcd7dff1b9")


def _get_or_create_default_character(db: Session) -> Character:
    char = db.execute(select(Character).where(Character.name == "Default Heroine")).scalar_one_or_none()
    if char:
        return char
    char = Character(
        name="Default Heroine",
        base_personality={"kind": 0.7},
        initial_relation_vector={"trust": 0.5, "respect": 0.5, "fear": 0.1, "attraction": 0.2},
        initial_visible_score=50,
    )
    db.add(char)
    db.flush()
    return char


def _require_session(db: Session, session_id: uuid.UUID) -> StorySession:
    sess = db.get(StorySession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


def _resolve_story_node_id(sess: StorySession) -> str | None:
    story_node_id = str(sess.story_node_id or "").strip()
    if story_node_id:
        return story_node_id
    route_flags = sess.route_flags if isinstance(sess.route_flags, dict) else {}
    route_story_node_id = str(route_flags.get("story_node_id") or "").strip()
    if route_story_node_id:
        return route_story_node_id
    if sess.current_node_id:
        # Best effort for historical sessions where node ids were UUID strings.
        return str(sess.current_node_id)
    return None


def _serialize_state(db: Session, sess: StorySession) -> SessionStateOut:
    char_states = db.execute(
        select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
    ).scalars().all()

    normalized_state = normalize_state(sess.state_json)
    story_node_id = _resolve_story_node_id(sess)
    route_flags = dict(sess.route_flags or {})
    if story_node_id:
        route_flags["story_node_id"] = story_node_id
    current_node = None
    if sess.story_id and story_node_id:
        if sess.story_version is not None:
            story_row = db.execute(
                select(Story).where(
                    Story.story_id == sess.story_id,
                    Story.version == sess.story_version,
                )
            ).scalar_one_or_none()
        else:
            story_row = db.execute(
                select(Story)
                .where(Story.story_id == sess.story_id, Story.is_published.is_(True))
                .order_by(Story.version.desc())
            ).scalars().first()
        if story_row is not None:
            runtime_pack = normalize_pack_for_runtime(story_row.pack_json or {})
            node = _story_node(runtime_pack, story_node_id)
            if node:
                response_choices = _story_choices_for_response(node, normalized_state)
                scene_text = str(node.get("scene_brief") or "").strip() or "(no current node narrative)"
                current_node = {
                    "id": story_node_id,
                    "parent_node_id": None,
                    "narrative_text": scene_text,
                    "choices": [ChoiceOut(**c) for c in response_choices],
                    "created_at": sess.updated_at,
                }
    if current_node is None and sess.current_node_id:
        # Backstop for legacy snapshots that still rely on dialogue_nodes.
        node = db.get(DialogueNode, sess.current_node_id)
        if node:
            current_node = {
                "id": str(node.id),
                "parent_node_id": str(node.parent_node_id) if node.parent_node_id else None,
                "narrative_text": node.narrative_text,
                "choices": [ChoiceOut(**c) for c in (node.choices or [])],
                "created_at": node.created_at,
            }

    return SessionStateOut(
        id=sess.id,
        status=sess.status,
        current_node_id=story_node_id,
        story_id=sess.story_id,
        story_version=sess.story_version,
        global_flags=sess.global_flags,
        route_flags=route_flags,
        active_characters=sess.active_characters,
        state_json=normalized_state,
        memory_summary=sess.memory_summary,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        character_states=[
            {
                "id": cs.id,
                "character_id": cs.character_id,
                "score_visible": cs.score_visible,
                "relation_vector": cs.relation_vector,
                "personality_drift": cs.personality_drift,
                "updated_at": cs.updated_at,
            }
            for cs in char_states
        ],
        current_node=current_node,
    )


def _load_story_pack(db: Session, story_id: str, version: int | None = None) -> Story:
    if version is not None:
        row = db.execute(select(Story).where(Story.story_id == story_id, Story.version == version)).scalar_one_or_none()
    else:
        row = db.execute(
            select(Story)
            .where(Story.story_id == story_id, Story.is_published.is_(True))
            .order_by(Story.version.desc())
        ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "STORY_NOT_FOUND"})
    return row


def _story_node(pack: dict, node_id: str) -> dict | None:
    for node in (pack.get("nodes") or []):
        if str(node.get("node_id")) == str(node_id):
            return node
    return None


def _story_node_runtime_uuid(*, story_id: str | None, story_version: int | None, node_id: str) -> uuid.UUID:
    value = str(node_id or "").strip()
    if not value:
        raise ValueError("empty story node id")
    try:
        return uuid.UUID(value)
    except Exception:  # noqa: BLE001
        # Keep DB GUID type while allowing arbitrary string node ids in StoryPack.
        namespace_key = f"{story_id or ''}:{story_version if story_version is not None else ''}:{value}"
        return uuid.uuid5(_STORY_NODE_UUID_NAMESPACE, namespace_key)


def _normalize_story_choice(choice: dict) -> dict:
    return dict(choice or {})


def _implicit_fallback_spec() -> dict:
    return {
        "id": None,
        "action": {"action_id": "clarify", "params": {}},
        "next_node_id_policy": "stay",
    }


def _coerce_effect_value_to_point(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _normalize_effects_to_point(effects: dict | None) -> dict:
    if not isinstance(effects, dict):
        return {}
    normalized: dict[str, int] = {}
    for key in ("energy", "money", "knowledge", "affection"):
        point = _coerce_effect_value_to_point(effects.get(key))
        if point is not None:
            normalized[key] = int(point)
    return normalized


def _normalize_numeric_threshold_map(values: dict | None) -> dict:
    if not isinstance(values, dict):
        return {}
    normalized: dict[str, int] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        if raw_value is None or isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, (int, float)):
            normalized[key] = int(raw_value)
    return normalized


def _normalize_trigger_for_runtime(trigger: dict | None) -> dict:
    if not isinstance(trigger, dict):
        return {}
    normalized: dict[str, object] = {}
    if trigger.get("node_id_is") is not None:
        normalized["node_id_is"] = str(trigger.get("node_id_is"))
    if trigger.get("next_node_id_is") is not None:
        normalized["next_node_id_is"] = str(trigger.get("next_node_id_is"))
    if trigger.get("executed_choice_id_is") is not None:
        normalized["executed_choice_id_is"] = str(trigger.get("executed_choice_id_is"))
    if trigger.get("action_id_is") is not None:
        normalized["action_id_is"] = str(trigger.get("action_id_is"))
    if trigger.get("fallback_used_is") is not None:
        normalized["fallback_used_is"] = bool(trigger.get("fallback_used_is"))
    if isinstance(trigger.get("state_at_least"), dict):
        normalized["state_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_at_least"))
    if isinstance(trigger.get("state_delta_at_least"), dict):
        normalized["state_delta_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_delta_at_least"))
    return normalized


def _normalize_event_trigger_for_runtime(trigger: dict | None) -> dict:
    if not isinstance(trigger, dict):
        return {}
    normalized: dict[str, object] = {}
    if trigger.get("node_id_is") is not None:
        normalized["node_id_is"] = str(trigger.get("node_id_is"))
    day_in = trigger.get("day_in")
    if isinstance(day_in, list):
        normalized_day_in: list[int] = []
        for value in day_in:
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                day = int(value)
                if day >= 1:
                    normalized_day_in.append(day)
        if normalized_day_in:
            normalized["day_in"] = normalized_day_in
    slot_in = trigger.get("slot_in")
    if isinstance(slot_in, list):
        normalized_slot_in = [
            str(value)
            for value in slot_in
            if str(value) in {"morning", "afternoon", "night"}
        ]
        if normalized_slot_in:
            normalized["slot_in"] = normalized_slot_in
    if trigger.get("fallback_used_is") is not None:
        normalized["fallback_used_is"] = bool(trigger.get("fallback_used_is"))
    if isinstance(trigger.get("state_at_least"), dict):
        normalized["state_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_at_least"))
    if isinstance(trigger.get("state_delta_at_least"), dict):
        normalized["state_delta_at_least"] = _normalize_numeric_threshold_map(trigger.get("state_delta_at_least"))
    return normalized


def _normalize_ending_trigger_for_runtime(trigger: dict | None) -> dict:
    if not isinstance(trigger, dict):
        return {}
    normalized: dict[str, object] = {}
    if trigger.get("node_id_is") is not None:
        normalized["node_id_is"] = str(trigger.get("node_id_is"))

    for key in (
        "day_at_least",
        "day_at_most",
        "energy_at_most",
        "money_at_least",
        "knowledge_at_least",
        "affection_at_least",
    ):
        raw = trigger.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            normalized[key] = int(raw)

    completed_quests = trigger.get("completed_quests_include")
    if isinstance(completed_quests, list):
        normalized_quests: list[str] = []
        seen: set[str] = set()
        for quest_id in completed_quests:
            text = str(quest_id or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized_quests.append(text)
        if normalized_quests:
            normalized["completed_quests_include"] = normalized_quests
    return normalized


def _normalize_events_for_runtime(events: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen_event_ids: set[str] = set()
    for raw_event in (events or []):
        if not isinstance(raw_event, dict):
            continue
        event_id = str(raw_event.get("event_id") or "").strip()
        if not event_id or event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)

        weight = raw_event.get("weight")
        weight_value = int(weight) if isinstance(weight, (int, float)) and not isinstance(weight, bool) else 1
        if weight_value < 1:
            weight_value = 1

        cooldown_raw = raw_event.get("cooldown_steps")
        cooldown_steps = (
            int(cooldown_raw)
            if isinstance(cooldown_raw, (int, float)) and not isinstance(cooldown_raw, bool)
            else 2
        )
        if cooldown_steps < 0:
            cooldown_steps = 0

        normalized.append(
            {
                "event_id": event_id,
                "title": str(raw_event.get("title") or event_id),
                "weight": weight_value,
                "once_per_run": bool(raw_event.get("once_per_run", True)),
                "cooldown_steps": cooldown_steps,
                "trigger": _normalize_event_trigger_for_runtime(raw_event.get("trigger")),
                "effects": _normalize_effects_to_point(raw_event.get("effects")),
                "narration_hint": (
                    str(raw_event.get("narration_hint"))
                    if raw_event.get("narration_hint") is not None
                    else None
                ),
            }
        )
    return normalized


def _normalize_endings_for_runtime(endings: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen_ending_ids: set[str] = set()
    for raw_ending in (endings or []):
        if not isinstance(raw_ending, dict):
            continue
        ending_id = str(raw_ending.get("ending_id") or "").strip()
        if not ending_id or ending_id in seen_ending_ids:
            continue
        seen_ending_ids.add(ending_id)

        priority_raw = raw_ending.get("priority")
        priority = int(priority_raw) if isinstance(priority_raw, (int, float)) and not isinstance(priority_raw, bool) else 100

        outcome = str(raw_ending.get("outcome") or "neutral")
        if outcome not in {"success", "neutral", "fail"}:
            outcome = "neutral"

        normalized.append(
            {
                "ending_id": ending_id,
                "title": str(raw_ending.get("title") or ending_id),
                "priority": priority,
                "outcome": outcome,
                "trigger": _normalize_ending_trigger_for_runtime(raw_ending.get("trigger")),
                "epilogue": str(raw_ending.get("epilogue") or ""),
            }
        )
    return normalized


def _normalize_run_config_for_runtime(run_config: dict | None) -> dict:
    config = run_config if isinstance(run_config, dict) else {}

    max_days_raw = config.get("max_days", 7)
    max_days = int(max_days_raw) if isinstance(max_days_raw, (int, float)) and not isinstance(max_days_raw, bool) else 7
    if max_days < 1:
        max_days = 7

    max_steps_raw = config.get("max_steps", 24)
    max_steps = int(max_steps_raw) if isinstance(max_steps_raw, (int, float)) and not isinstance(max_steps_raw, bool) else 24
    if max_steps < 1:
        max_steps = 24

    timeout_outcome = str(config.get("default_timeout_outcome") or "neutral")
    if timeout_outcome not in {"neutral", "fail"}:
        timeout_outcome = "neutral"

    return {
        "max_days": max_days,
        "max_steps": max_steps,
        "default_timeout_outcome": timeout_outcome,
    }


def _normalize_quests_for_runtime(quests: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen_quest_ids: set[str] = set()
    for raw_quest in (quests or []):
        if not isinstance(raw_quest, dict):
            continue
        quest_id = str(raw_quest.get("quest_id") or "").strip()
        if not quest_id or quest_id in seen_quest_ids:
            continue
        seen_quest_ids.add(quest_id)

        stages: list[dict] = []
        seen_stage_ids: set[str] = set()
        for raw_stage in (raw_quest.get("stages") or []):
            if not isinstance(raw_stage, dict):
                continue
            stage_id = str(raw_stage.get("stage_id") or "").strip()
            if not stage_id or stage_id in seen_stage_ids:
                continue
            seen_stage_ids.add(stage_id)

            milestones: list[dict] = []
            seen_milestone_ids: set[str] = set()
            for raw_milestone in (raw_stage.get("milestones") or []):
                if not isinstance(raw_milestone, dict):
                    continue
                milestone_id = str(raw_milestone.get("milestone_id") or "").strip()
                if not milestone_id or milestone_id in seen_milestone_ids:
                    continue
                seen_milestone_ids.add(milestone_id)
                milestones.append(
                    {
                        "milestone_id": milestone_id,
                        "title": str(raw_milestone.get("title") or milestone_id),
                        "description": (
                            str(raw_milestone.get("description"))
                            if raw_milestone.get("description") is not None
                            else None
                        ),
                        "when": _normalize_trigger_for_runtime(raw_milestone.get("when")),
                        "rewards": _normalize_effects_to_point(raw_milestone.get("rewards")),
                    }
                )

            stages.append(
                {
                    "stage_id": stage_id,
                    "title": str(raw_stage.get("title") or stage_id),
                    "description": (
                        str(raw_stage.get("description"))
                        if raw_stage.get("description") is not None
                        else None
                    ),
                    "stage_rewards": _normalize_effects_to_point(raw_stage.get("stage_rewards")),
                    "milestones": milestones,
                }
            )

        normalized.append(
            {
                "quest_id": quest_id,
                "title": str(raw_quest.get("title") or quest_id),
                "description": (
                    str(raw_quest.get("description"))
                    if raw_quest.get("description") is not None
                    else None
                ),
                "auto_activate": bool(raw_quest.get("auto_activate", True)),
                "completion_rewards": _normalize_effects_to_point(raw_quest.get("completion_rewards")),
                "stages": stages,
            }
        )
    return normalized


def normalize_pack_for_runtime(pack_json: dict | None) -> dict:
    pack = json.loads(json.dumps(pack_json or {}))
    default_fallback = pack.get("default_fallback")
    nodes = []

    fallback_executors: list[dict] = []
    for raw_executor in (pack.get("fallback_executors") or []):
        if not isinstance(raw_executor, dict):
            continue
        executor = dict(raw_executor)
        action = executor.get("action")
        if not isinstance(action, dict):
            action_id = executor.get("action_id")
            action_params = executor.get("action_params")
            if action_id is None:
                action = None
            else:
                action = {
                    "action_id": str(action_id),
                    "params": dict(action_params or {}) if isinstance(action_params, dict) else {},
                }
        executor["action"] = dict(action) if isinstance(action, dict) else None
        executor["effects"] = _normalize_effects_to_point(executor.get("effects"))
        narration = executor.get("narration")
        if not isinstance(narration, dict):
            narration = {}
        executor["narration"] = {
            "skeleton": (str(narration.get("skeleton")) if narration.get("skeleton") is not None else None)
        }
        executor["prereq"] = dict((executor.get("prereq") or {})) if isinstance(executor.get("prereq"), dict) else None
        executor["next_node_id"] = (
            str(executor.get("next_node_id"))
            if executor.get("next_node_id") is not None
            else None
        )
        fallback_executors.append(executor)

    for raw_node in (pack.get("nodes") or []):
        node = dict(raw_node or {})
        visible_choices: list[dict] = []

        for raw_choice in (node.get("choices") or []):
            choice = _normalize_story_choice(raw_choice)
            choice["effects"] = _normalize_effects_to_point(choice.get("effects"))
            visible_choices.append(choice)

        fallback = node.get("fallback")
        fallback_source = "node"
        if fallback is None and default_fallback is not None:
            fallback = dict(default_fallback)
            fallback_source = "default"
        elif fallback is None:
            fallback = _implicit_fallback_spec()
            fallback_source = "implicit"
        else:
            fallback = dict(fallback)
        fallback["effects"] = _normalize_effects_to_point(fallback.get("effects"))
        fallback["prereq"] = dict((fallback.get("prereq") or {})) if isinstance(fallback.get("prereq"), dict) else None

        node["choices"] = visible_choices
        node["intents"] = [dict(item) for item in (node.get("intents") or []) if isinstance(item, dict)]
        node["node_fallback_choice_id"] = (
            str(node.get("node_fallback_choice_id"))
            if node.get("node_fallback_choice_id") is not None
            else None
        )
        node["fallback"] = fallback
        node["_fallback_source"] = fallback_source
        nodes.append(node)

    pack["nodes"] = nodes
    pack["fallback_executors"] = fallback_executors
    pack["global_fallback_choice_id"] = (
        str(pack.get("global_fallback_choice_id"))
        if pack.get("global_fallback_choice_id") is not None
        else None
    )
    pack["quests"] = _normalize_quests_for_runtime(pack.get("quests"))
    pack["events"] = _normalize_events_for_runtime(pack.get("events"))
    pack["endings"] = _normalize_endings_for_runtime(pack.get("endings"))
    pack["run_config"] = _normalize_run_config_for_runtime(pack.get("run_config"))
    return pack


def _is_valid_story_action(action: dict | None) -> bool:
    if not isinstance(action, dict):
        return False
    action_id = str(action.get("action_id") or "")
    params = action.get("params")
    if not isinstance(params, dict):
        return False

    if action_id in {"study", "work", "rest", "clarify"}:
        return params == {}
    if action_id == "date":
        return isinstance(params.get("target"), str) and bool(str(params.get("target")))
    if action_id == "gift":
        return (
            isinstance(params.get("target"), str)
            and bool(str(params.get("target")))
            and isinstance(params.get("gift_type"), str)
            and bool(str(params.get("gift_type")))
        )
    return False


def _resolve_runtime_fallback(node: dict, current_node_id: str, node_ids: set[str]) -> tuple[dict, str, list[str]]:
    fallback = dict((node.get("fallback") or {}))
    fallback_source = str(node.get("_fallback_source") or "node")
    markers: list[str] = []
    if fallback_source == "implicit":
        markers.append("FALLBACK_CONFIG_IMPLICIT")
        markers.append("FALLBACK_CONFIG_MISSING")

    fallback_id = fallback.get("id")
    if isinstance(fallback_id, str) and fallback_id.startswith(RESERVED_CHOICE_ID_PREFIX):
        fallback["id"] = None
        markers.append("FALLBACK_CONFIG_RESERVED_ID_PREFIX")

    malformed = False
    if not _is_valid_story_action(fallback.get("action")):
        malformed = True

    policy = str(fallback.get("next_node_id_policy") or "")
    next_node_id = current_node_id
    if policy == "stay":
        next_node_id = current_node_id
    elif policy == "explicit_next":
        candidate = str(fallback.get("next_node_id") or "")
        if not candidate or candidate not in node_ids:
            malformed = True
        else:
            next_node_id = candidate
    else:
        malformed = True

    if malformed:
        fallback = _implicit_fallback_spec()
        next_node_id = current_node_id
        markers.append("FALLBACK_CONFIG_INVALID")
        if "FALLBACK_CONFIG_IMPLICIT" not in markers:
            markers.append("FALLBACK_CONFIG_IMPLICIT")

    return fallback, next_node_id, sorted(set(markers))


def _fallback_executed_choice_id(fallback: dict, current_node_id: str) -> str:
    fallback_id = fallback.get("id")
    if fallback_id and not str(fallback_id).startswith(RESERVED_CHOICE_ID_PREFIX):
        return str(fallback_id)
    return f"__fallback__:{current_node_id}"


def _select_fallback_text_variant(
    fallback: dict,
    reason_code: str | None,
    locale: str | None = None,
) -> str | None:
    return select_fallback_skeleton_text(
        text_variants=((fallback or {}).get("text_variants") if isinstance(fallback, dict) else None),
        reason=reason_code,
        locale=locale or settings.story_default_locale,
    )


def _select_story_choice(
    *,
    db: Session,
    sess: StorySession,
    player_input: str,
    visible_choices: list[dict],
    intents: list[dict] | None,
    current_story_state: dict,
) -> SelectionResult:
    raw = str(player_input or "").strip()
    if not raw:
        return SelectionResult(
            selected_visible_choice_id=None,
            attempted_choice_id=None,
            mapping_confidence=0.0,
            mapping_note=None,
            internal_reason="NO_INPUT",
            use_fallback=True,
            input_source=SelectionInputSource.EMPTY,
        )

    valid_choice_ids = [str(c.get("choice_id")) for c in visible_choices if c.get("choice_id") is not None]
    normalized_intents: list[dict] = []
    intent_aliases: dict[str, str] = {}
    for raw_intent in (intents or []):
        if not isinstance(raw_intent, dict):
            continue
        intent_id = str(raw_intent.get("intent_id") or "").strip()
        alias_choice_id = str(raw_intent.get("alias_choice_id") or "").strip()
        if not intent_id or alias_choice_id not in valid_choice_ids:
            continue
        normalized_intents.append(
            {
                "intent_id": intent_id,
                "alias_choice_id": alias_choice_id,
                "description": str(raw_intent.get("description") or ""),
                "patterns": [
                    str(pattern).strip()
                    for pattern in (raw_intent.get("patterns") or [])
                    if str(pattern).strip()
                ],
            }
        )
        intent_aliases[intent_id] = alias_choice_id

    llm_runtime = get_llm_runtime()
    selection_prompt = build_story_selection_prompt(
        player_input=raw,
        valid_choice_ids=valid_choice_ids,
        visible_choices=visible_choices,
        intents=normalized_intents,
        state_snippet=current_story_state,
    )
    min_confidence = max(0.0, min(1.0, float(settings.story_map_min_confidence)))
    llm_selection = StorySelectionOutput()
    parse_ok = True
    llm_requested_fallback = False
    llm_fallback_note: str | None = None
    llm_fallback_confidence = 0.0
    if hasattr(llm_runtime, "select_story_choice_with_fallback"):
        try:
            llm_selection, parse_ok = llm_runtime.select_story_choice_with_fallback(
                db,
                prompt=selection_prompt,
                session_id=sess.id,
            )
        except Exception:  # noqa: BLE001
            llm_selection = StorySelectionOutput()
            parse_ok = False
    if parse_ok and llm_selection.use_fallback:
        # Conservative rescue: keep fallback as a hint, then try deterministic intent/rule mapping.
        llm_requested_fallback = True
        llm_fallback_note = llm_selection.notes or "selector_fallback"
        llm_fallback_confidence = float(llm_selection.confidence)
    if parse_ok and llm_selection.choice_id and llm_selection.choice_id in valid_choice_ids and not llm_selection.use_fallback:
        return SelectionResult(
            selected_visible_choice_id=str(llm_selection.choice_id),
            attempted_choice_id=str(llm_selection.choice_id),
            mapping_confidence=float(llm_selection.confidence),
            mapping_note=llm_selection.notes,
            internal_reason=None,
            use_fallback=False,
            input_source=SelectionInputSource.TEXT,
        )
    if parse_ok and llm_selection.intent_id:
        alias_choice_id = intent_aliases.get(str(llm_selection.intent_id))
        llm_intent_confidence = float(llm_selection.confidence)
        if alias_choice_id and llm_intent_confidence >= min_confidence:
            mapping_note = llm_selection.notes or f"intent:{llm_selection.intent_id}"
            if llm_requested_fallback:
                mapping_note = f"rescued_after_llm_fallback:{mapping_note}"
            return SelectionResult(
                selected_visible_choice_id=alias_choice_id,
                attempted_choice_id=alias_choice_id,
                mapping_confidence=llm_intent_confidence,
                mapping_note=mapping_note,
                internal_reason=None,
                use_fallback=False,
                input_source=SelectionInputSource.TEXT,
            )

    normalized_input = " ".join(raw.lower().split())
    intent_hits: list[tuple[int, str, str]] = []
    for intent in normalized_intents:
        intent_id = str(intent.get("intent_id") or "")
        alias_choice_id = str(intent.get("alias_choice_id") or "")
        for pattern in (intent.get("patterns") or []):
            normalized_pattern = " ".join(str(pattern).lower().split())
            if not normalized_pattern:
                continue
            if normalized_pattern in normalized_input:
                intent_hits.append((len(normalized_pattern), intent_id, alias_choice_id))
    if intent_hits:
        intent_hits.sort(key=lambda item: (-item[0], item[1], item[2]))
        _, intent_id, alias_choice_id = intent_hits[0]
        mapping_note = f"intent_pattern:{intent_id}"
        if llm_requested_fallback:
            mapping_note = f"rescued_after_llm_fallback:{mapping_note}"
        return SelectionResult(
            selected_visible_choice_id=alias_choice_id,
            attempted_choice_id=alias_choice_id,
            mapping_confidence=0.8,
            mapping_note=mapping_note,
            internal_reason=None,
            use_fallback=False,
            input_source=SelectionInputSource.TEXT,
        )

    mapping_result = story_mapping_adapter.map_input(
        player_input=raw,
        choices=visible_choices,
        state={"route_flags": (sess.route_flags or {})},
    )
    if mapping_result.ranked_candidates:
        selected_choice_id = str(mapping_result.ranked_candidates[0].choice_id)
        mapping_confidence = float(mapping_result.confidence)
        mapping_is_ambiguous = mapping_result.note == "AMBIGUOUS_FIRST_MATCH"
        if mapping_confidence >= min_confidence and not mapping_is_ambiguous:
            mapping_note = mapping_result.note or "rule_based"
            if llm_requested_fallback:
                mapping_note = f"rescued_after_llm_fallback:{mapping_note}"
            return SelectionResult(
                selected_visible_choice_id=selected_choice_id,
                attempted_choice_id=selected_choice_id,
                mapping_confidence=mapping_confidence,
                mapping_note=mapping_note,
                internal_reason=None,
                use_fallback=False,
                input_source=SelectionInputSource.TEXT,
            )
        if llm_requested_fallback:
            reject_note = mapping_result.note or "rule_low_confidence"
            llm_fallback_note = f"{llm_fallback_note or 'selector_fallback'}|{reject_note}"
    return SelectionResult(
        selected_visible_choice_id=None,
        attempted_choice_id=None,
        mapping_confidence=(llm_fallback_confidence if llm_requested_fallback else 0.0),
        mapping_note=llm_fallback_note,
        internal_reason=("LLM_PARSE_ERROR" if not parse_ok else "NO_MATCH"),
        use_fallback=True,
        input_source=SelectionInputSource.TEXT,
    )


def _story_choices_for_response(node: dict, state_json: dict | None) -> list[dict]:
    out = []
    state = normalize_state(state_json)
    for choice in (node.get("choices") or []):
        action_id = ((choice.get("action") or {}).get("action_id") or "action")
        is_available, unavailable_reason = evaluate_choice_availability(choice, state)
        item = {
            "id": str(choice.get("choice_id")),
            "text": str(choice.get("display_text", "")),
            "type": str(action_id),
            "is_available": bool(is_available),
        }
        if not is_available and unavailable_reason:
            item["unavailable_reason"] = unavailable_reason
        out.append(item)
    return out


def _apply_choice_effects(state: dict, effects: dict | None) -> dict:
    if not effects:
        return normalize_state(state)
    out = dict(state)
    for key in ("energy", "money", "knowledge", "affection"):
        if key in effects and effects.get(key) is not None:
            out[key] = int(out.get(key, 0)) + int(effects.get(key) or 0)
    return normalize_state(out)


def _compute_state_delta(before: dict, after: dict) -> dict:
    delta: dict = {}
    for key, before_value in before.items():
        after_value = after.get(key)
        if before_value == after_value:
            continue
        if isinstance(before_value, int) and isinstance(after_value, int):
            delta[key] = after_value - before_value
        else:
            delta[key] = after_value
    return delta


def _format_effects_suffix(effects: dict | None) -> str:
    if not isinstance(effects, dict):
        return ""
    parts: list[str] = []
    for key in sorted(effects.keys(), key=lambda item: str(item)):
        value = effects.get(key)
        if value is None:
            continue
        try:
            numeric = int(value)
        except Exception:  # noqa: BLE001
            continue
        if numeric == 0:
            continue
        sign = "+" if numeric > 0 else ""
        parts.append(f"{key} {sign}{numeric}")
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def create_session(db: Session, story_id: str, version: int | None = None) -> StorySession:
    with db.begin():
        story_id_text = str(story_id or "").strip()
        if not story_id_text:
            raise HTTPException(status_code=400, detail={"code": "STORY_REQUIRED"})
        char = _get_or_create_default_character(db)
        story_row = _load_story_pack(db, story_id_text, version)
        runtime_pack = normalize_pack_for_runtime(story_row.pack_json or {})
        start_node_id = str(runtime_pack.get("start_node_id") or "").strip()
        if not start_node_id or _story_node(runtime_pack, start_node_id) is None:
            raise HTTPException(status_code=400, detail={"code": "INVALID_STORY_START_NODE"})
        try:
            start_node = _story_node_runtime_uuid(
                story_id=story_row.story_id,
                story_version=story_row.version,
                node_id=start_node_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail={"code": "INVALID_STORY_START_NODE"}) from exc

        initial_state = default_initial_state()
        initial_state["quest_state"] = init_quest_state(runtime_pack.get("quests") or [])
        initial_state["run_state"] = normalize_run_state(None)

        sess = StorySession(
            status="active",
            current_node_id=start_node,
            story_node_id=start_node_id,
            global_flags={},
            route_flags={"story_node_id": start_node_id},
            active_characters=[str(char.id)],
            state_json=normalize_state(initial_state),
            memory_summary="",
            story_id=story_row.story_id,
            story_version=story_row.version,
        )
        db.add(sess)
        db.flush()

        scs = SessionCharacterState(
            session_id=sess.id,
            character_id=char.id,
            score_visible=char.initial_visible_score,
            relation_vector=char.initial_relation_vector,
            personality_drift={},
        )
        db.add(scs)
    db.refresh(sess)
    return sess


def get_session_state(db: Session, session_id: uuid.UUID) -> SessionStateOut:
    sess = _require_session(db, session_id)
    return _serialize_state(db, sess)


def _sum_step_tokens(db: Session, session_id: uuid.UUID, step_id: uuid.UUID) -> tuple[int, int]:
    prompt_tokens = (
        db.execute(
            select(func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0)).where(
                LLMUsageLog.session_id == session_id,
                LLMUsageLog.step_id == step_id,
            )
        ).scalar_one()
        or 0
    )
    completion_tokens = (
        db.execute(
            select(func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0)).where(
                LLMUsageLog.session_id == session_id,
                LLMUsageLog.step_id == step_id,
            )
        ).scalar_one()
        or 0
    )
    return int(prompt_tokens), int(completion_tokens)


def _sum_step_usage(db: Session, session_id: uuid.UUID, step_id: uuid.UUID) -> tuple[int, int]:
    return _sum_step_tokens(db, session_id, step_id)


def _step_provider(db: Session, session_id: uuid.UUID, step_id: uuid.UUID) -> str:
    latest_usage = db.execute(
        select(LLMUsageLog)
        .where(
            LLMUsageLog.session_id == session_id,
            LLMUsageLog.step_id == step_id,
            LLMUsageLog.operation == "generate",
            LLMUsageLog.status == "success",
        )
        .order_by(LLMUsageLog.created_at.desc())
    ).scalars().first()
    return latest_usage.provider if latest_usage else "none"


def _run_story_runtime_pipeline(
    *,
    db: Session,
    sess: StorySession,
    choice_id: str | None,
    player_input: str | None,
) -> dict:
    def _bound_select_story_choice(
        *,
        player_input: str,
        visible_choices: list[dict],
        intents: list[dict] | None,
        current_story_state: dict,
    ) -> SelectionResult:
        return _select_story_choice(
            db=db,
            sess=sess,
            player_input=player_input,
            visible_choices=visible_choices,
            intents=intents,
            current_story_state=current_story_state,
        )

    deps = StoryRuntimePipelineDeps(
        load_story_pack=_load_story_pack,
        normalize_pack_for_runtime=normalize_pack_for_runtime,
        story_node=_story_node,
        resolve_runtime_fallback=_resolve_runtime_fallback,
        select_story_choice=_bound_select_story_choice,
        fallback_executed_choice_id=_fallback_executed_choice_id,
        select_fallback_text_variant=_select_fallback_text_variant,
        sum_step_usage=_sum_step_usage,
        step_provider=_step_provider,
        apply_choice_effects=_apply_choice_effects,
        compute_state_delta=_compute_state_delta,
        format_effects_suffix=_format_effects_suffix,
        story_choices_for_response=_story_choices_for_response,
        advance_quest_state=advance_quest_state,
        advance_runtime_events=advance_runtime_events,
        resolve_run_ending=resolve_run_ending,
        summarize_quest_for_narration=summarize_quest_for_narration,
        llm_runtime_getter=get_llm_runtime,
        story_node_runtime_uuid=lambda story_id, story_version, node_id: _story_node_runtime_uuid(
            story_id=story_id,
            story_version=story_version,
            node_id=node_id,
        ),
    )
    try:
        return run_story_runtime_pipeline(
            db=db,
            sess=sess,
            choice_id=choice_id,
            player_input=player_input,
            fallback_builtin_text=_STORY_FALLBACK_BUILTIN_TEXT,
            deps=deps,
        )
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": "LLM_UNAVAILABLE"}) from exc


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalized_optional_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _request_hash(*, choice_id: str | None, player_input: str | None) -> str:
    canonical = json.dumps(
        {"choice_id": choice_id, "player_input": player_input},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_response_payload(payload: dict) -> dict:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _idempotency_expiry(now: datetime | None = None) -> datetime:
    base = now or datetime.utcnow()
    ttl = max(1, int(settings.step_idempotency_ttl_s))
    return base + timedelta(seconds=ttl)


def _is_stale_in_progress(row: SessionStepIdempotency, now: datetime | None = None) -> bool:
    current = now or datetime.utcnow()
    threshold = max(1, int(settings.step_idempotency_in_progress_stale_s))
    anchor = row.updated_at or row.created_at or current
    return (current - anchor).total_seconds() > threshold


def _extract_http_error_code(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return f"HTTP_{int(exc.status_code)}"


def _require_step_preconditions(sess: StorySession) -> None:
    if sess.status != "active":
        raise HTTPException(status_code=409, detail={"code": "SESSION_NOT_ACTIVE"})
    if not sess.story_id:
        raise HTTPException(status_code=400, detail={"code": "STORY_REQUIRED"})


def _persist_idempotency_failed(
    db: Session,
    *,
    session_id: uuid.UUID,
    idempotency_key: str,
    request_hash: str,
    error_code: str,
) -> None:
    db.rollback()
    with db.begin():
        row = db.execute(
            select(SessionStepIdempotency).where(
                SessionStepIdempotency.session_id == session_id,
                SessionStepIdempotency.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        now = datetime.utcnow()
        expiry = _idempotency_expiry(now)
        if row is None:
            db.add(
                SessionStepIdempotency(
                    session_id=session_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    status=_IDEMPOTENCY_STATUS_FAILED,
                    response_json=None,
                    error_code=error_code,
                    created_at=now,
                    updated_at=now,
                    expires_at=expiry,
                )
            )
            return
        if row.request_hash != request_hash:
            return
        row.status = _IDEMPOTENCY_STATUS_FAILED
        row.error_code = error_code
        row.updated_at = now
        row.expires_at = expiry


def step_session(
    db: Session,
    session_id: uuid.UUID,
    choice_id: str | None,
    player_input: str | None = None,
    idempotency_key: str | None = None,
):
    normalized_choice_id = _normalized_optional_text(choice_id)
    normalized_player_input = _normalized_optional_text(player_input)
    normalized_idempotency_key = _normalized_optional_idempotency_key(idempotency_key)
    if normalized_choice_id and normalized_player_input:
        raise HTTPException(
            status_code=422,
            detail={"code": "INPUT_CONFLICT", "message": "Provide exactly one of choice_id or player_input."},
        )

    if not normalized_idempotency_key:
        with db.begin():
            sess = _require_session(db, session_id)
            _require_step_preconditions(sess)
            return _run_story_runtime_pipeline(
                db=db,
                sess=sess,
                choice_id=normalized_choice_id,
                player_input=normalized_player_input,
            )

    request_hash = _request_hash(choice_id=normalized_choice_id, player_input=normalized_player_input)

    replay_payload: dict | None = None
    execution_started = False
    try:
        phase1_done = False
        for _ in range(2):
            try:
                with db.begin():
                    sess = _require_session(db, session_id)
                    row = db.execute(
                        select(SessionStepIdempotency).where(
                            SessionStepIdempotency.session_id == session_id,
                            SessionStepIdempotency.idempotency_key == normalized_idempotency_key,
                        )
                    ).scalar_one_or_none()

                    now = datetime.utcnow()
                    expiry = _idempotency_expiry(now)

                    if row is None:
                        row = SessionStepIdempotency(
                            session_id=session_id,
                            idempotency_key=normalized_idempotency_key,
                            request_hash=request_hash,
                            status=_IDEMPOTENCY_STATUS_IN_PROGRESS,
                            response_json=None,
                            error_code=None,
                            created_at=now,
                            updated_at=now,
                            expires_at=expiry,
                        )
                        db.add(row)
                        db.flush()
                    elif row.request_hash != request_hash:
                        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED"})
                    elif row.status == _IDEMPOTENCY_STATUS_SUCCEEDED and isinstance(row.response_json, dict):
                        replay_payload = dict(row.response_json)
                    elif row.status == _IDEMPOTENCY_STATUS_IN_PROGRESS and not _is_stale_in_progress(row, now):
                        raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS"})
                    else:
                        row.status = _IDEMPOTENCY_STATUS_IN_PROGRESS
                        row.error_code = None
                        row.updated_at = now
                        row.expires_at = expiry
                phase1_done = True
                break
            except IntegrityError:
                db.rollback()
                continue

        if not phase1_done:
            raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS"})

        if replay_payload is not None:
            return replay_payload

        execution_started = True
        with db.begin():
            sess = _require_session(db, session_id)
            _require_step_preconditions(sess)
            response_payload = _run_story_runtime_pipeline(
                db=db,
                sess=sess,
                choice_id=normalized_choice_id,
                player_input=normalized_player_input,
            )
            safe_payload = _safe_response_payload(response_payload)
            row = db.execute(
                select(SessionStepIdempotency).where(
                    SessionStepIdempotency.session_id == session_id,
                    SessionStepIdempotency.idempotency_key == normalized_idempotency_key,
                )
            ).scalar_one_or_none()
            if row is not None and row.request_hash == request_hash:
                now = datetime.utcnow()
                row.status = _IDEMPOTENCY_STATUS_SUCCEEDED
                row.response_json = safe_payload
                row.error_code = None
                row.updated_at = now
                row.expires_at = _idempotency_expiry(now)
            return safe_payload
    except HTTPException as exc:
        if execution_started:
            _persist_idempotency_failed(
                db,
                session_id=session_id,
                idempotency_key=normalized_idempotency_key,
                request_hash=request_hash,
                error_code=_extract_http_error_code(exc),
            )
        raise
    except Exception:
        if execution_started:
            _persist_idempotency_failed(
                db,
                session_id=session_id,
                idempotency_key=normalized_idempotency_key,
                request_hash=request_hash,
                error_code="INTERNAL_ERROR",
            )
        raise


def create_snapshot(db: Session, session_id: uuid.UUID) -> SessionSnapshot:
    with db.begin():
        sess = _require_session(db, session_id)
        cutoff = datetime.utcnow()
        char_states = db.execute(
            select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
        ).scalars().all()

        node_ids = [str(v) for v in db.execute(select(DialogueNode.id).where(DialogueNode.session_id == sess.id)).scalars().all()]
        action_log_ids = [str(v) for v in db.execute(select(ActionLog.id).where(ActionLog.session_id == sess.id)).scalars().all()]

        payload = {
            "session": {
                "id": str(sess.id),
                "status": sess.status,
                "current_node_id": str(sess.current_node_id) if sess.current_node_id else None,
                "story_node_id": _resolve_story_node_id(sess),
                "global_flags": sess.global_flags,
                "route_flags": sess.route_flags,
                "active_characters": sess.active_characters,
                "state_json": normalize_state(sess.state_json),
                "memory_summary": sess.memory_summary,
            },
            "character_states": [
                {
                    "id": str(cs.id),
                    "character_id": str(cs.character_id),
                    "score_visible": cs.score_visible,
                    "relation_vector": cs.relation_vector,
                    "personality_drift": cs.personality_drift,
                    "updated_at": cs.updated_at.isoformat(),
                }
                for cs in char_states
            ],
            "cutoff_ts": cutoff.isoformat(),
            "dialogue_node_ids": node_ids,
            "action_log_ids": action_log_ids,
        }

        snapshot = SessionSnapshot(session_id=sess.id, snapshot_name="manual", state_blob=payload, created_at=cutoff)
        db.add(snapshot)
        db.flush()
    db.refresh(snapshot)
    return snapshot


def rollback_to_snapshot(db: Session, session_id: uuid.UUID, snapshot_id: uuid.UUID) -> StorySession:
    with db.begin():
        sess = _require_session(db, session_id)
        snapshot = db.get(SessionSnapshot, snapshot_id)
        if not snapshot or snapshot.session_id != sess.id:
            raise HTTPException(status_code=404, detail="snapshot not found")

        payload = snapshot.state_blob
        s = payload["session"]
        sess.status = s["status"]
        sess.current_node_id = uuid.UUID(s["current_node_id"]) if s["current_node_id"] else None
        snapshot_story_node_id = str(s.get("story_node_id") or "").strip() or None
        if not snapshot_story_node_id:
            snapshot_story_node_id = str((s.get("route_flags") or {}).get("story_node_id") or "").strip() or None
        sess.story_node_id = snapshot_story_node_id
        sess.global_flags = s["global_flags"]
        sess.route_flags = dict(s["route_flags"] or {})
        if snapshot_story_node_id:
            sess.route_flags["story_node_id"] = snapshot_story_node_id
        else:
            sess.route_flags.pop("story_node_id", None)
        sess.active_characters = s["active_characters"]
        sess.state_json = normalize_state(s.get("state_json"))
        sess.memory_summary = s["memory_summary"]
        sess.updated_at = datetime.utcnow()

        db.execute(delete(SessionCharacterState).where(SessionCharacterState.session_id == sess.id))
        for cs in payload["character_states"]:
            db.add(
                SessionCharacterState(
                    id=uuid.UUID(cs["id"]),
                    session_id=sess.id,
                    character_id=uuid.UUID(cs["character_id"]),
                    score_visible=cs["score_visible"],
                    relation_vector=cs["relation_vector"],
                    personality_drift=cs["personality_drift"],
                    updated_at=datetime.fromisoformat(cs["updated_at"]),
                )
            )

        keep_node_ids = [uuid.UUID(v) for v in payload.get("dialogue_node_ids", [])]
        keep_action_log_ids = [uuid.UUID(v) for v in payload.get("action_log_ids", [])]

        action_delete = delete(ActionLog).where(ActionLog.session_id == sess.id)
        if keep_action_log_ids:
            action_delete = action_delete.where(ActionLog.id.not_in(keep_action_log_ids))
        db.execute(action_delete)

        node_delete = delete(DialogueNode).where(DialogueNode.session_id == sess.id)
        if keep_node_ids:
            node_delete = node_delete.where(DialogueNode.id.not_in(keep_node_ids))
        db.execute(node_delete)

    return sess


def end_session(db: Session, session_id: uuid.UUID) -> dict:
    with db.begin():
        sess = _require_session(db, session_id)
        sess.status = "ended"
        sess.updated_at = datetime.utcnow()

        report = replay_engine.build_report(session_id=sess.id, db=db)
        replay_row = upsert_replay_report(db, session_id=sess.id, report=report)
        db.flush()

    return {
        "ended": True,
        "replay_report_id": str(replay_row.id),
    }


def get_replay(db: Session, session_id: uuid.UUID) -> dict:
    _require_session(db, session_id)
    from app.db.models import ReplayReport

    row = db.execute(select(ReplayReport).where(ReplayReport.session_id == session_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "REPLAY_NOT_READY"})
    return row.report_json
