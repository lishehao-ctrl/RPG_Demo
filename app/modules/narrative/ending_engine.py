from __future__ import annotations

from app.modules.narrative.state_engine import normalize_run_state, normalize_state
from app.modules.session.story_runtime.models import EndingResolution


def _normalize_run_config(run_config: dict | None) -> dict:
    cfg = run_config if isinstance(run_config, dict) else {}

    max_days_raw = cfg.get("max_days", 7)
    max_days = int(max_days_raw) if isinstance(max_days_raw, (int, float)) and not isinstance(max_days_raw, bool) else 7
    if max_days < 1:
        max_days = 7

    max_steps_raw = cfg.get("max_steps", 24)
    max_steps = int(max_steps_raw) if isinstance(max_steps_raw, (int, float)) and not isinstance(max_steps_raw, bool) else 24
    if max_steps < 1:
        max_steps = 24

    timeout_outcome = str(cfg.get("default_timeout_outcome") or "neutral")
    if timeout_outcome not in {"neutral", "fail"}:
        timeout_outcome = "neutral"

    return {
        "max_days": max_days,
        "max_steps": max_steps,
        "default_timeout_outcome": timeout_outcome,
    }


def _normalize_endings(endings_def: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    for raw in (endings_def or []):
        if not isinstance(raw, dict):
            continue
        ending_id = str(raw.get("ending_id") or "").strip()
        if not ending_id or ending_id in seen_ids:
            continue
        seen_ids.add(ending_id)

        priority_raw = raw.get("priority")
        priority = int(priority_raw) if isinstance(priority_raw, (int, float)) and not isinstance(priority_raw, bool) else 100

        outcome = str(raw.get("outcome") or "neutral")
        if outcome not in {"success", "neutral", "fail"}:
            outcome = "neutral"

        trigger = raw.get("trigger") if isinstance(raw.get("trigger"), dict) else {}
        completed = trigger.get("completed_quests_include")
        completed_quests_include: list[str] = []
        if isinstance(completed, list):
            for item in completed:
                text = str(item or "").strip()
                if text:
                    completed_quests_include.append(text)

        normalized.append(
            {
                "ending_id": ending_id,
                "title": str(raw.get("title") or ending_id),
                "priority": priority,
                "outcome": outcome,
                "trigger": {
                    "node_id_is": (str(trigger.get("node_id_is")) if trigger.get("node_id_is") is not None else None),
                    "day_at_least": trigger.get("day_at_least"),
                    "day_at_most": trigger.get("day_at_most"),
                    "energy_at_most": trigger.get("energy_at_most"),
                    "money_at_least": trigger.get("money_at_least"),
                    "knowledge_at_least": trigger.get("knowledge_at_least"),
                    "affection_at_least": trigger.get("affection_at_least"),
                    "completed_quests_include": completed_quests_include,
                },
                "epilogue": str(raw.get("epilogue") or ""),
            }
        )
    normalized.sort(key=lambda item: (int(item.get("priority", 100)), str(item.get("ending_id"))))
    return normalized


def _as_int(value, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _matches_trigger(trigger: dict, *, next_node_id: str, state_after: dict, completed_quests: set[str]) -> bool:
    node_id_is = trigger.get("node_id_is")
    if node_id_is is not None and str(node_id_is) != str(next_node_id):
        return False

    day = int(state_after.get("day", 1))
    energy = int(state_after.get("energy", 0))
    money = int(state_after.get("money", 0))
    knowledge = int(state_after.get("knowledge", 0))
    affection = int(state_after.get("affection", 0))

    day_at_least = _as_int(trigger.get("day_at_least"))
    if day_at_least is not None and day < day_at_least:
        return False
    day_at_most = _as_int(trigger.get("day_at_most"))
    if day_at_most is not None and day > day_at_most:
        return False
    energy_at_most = _as_int(trigger.get("energy_at_most"))
    if energy_at_most is not None and energy > energy_at_most:
        return False
    money_at_least = _as_int(trigger.get("money_at_least"))
    if money_at_least is not None and money < money_at_least:
        return False
    knowledge_at_least = _as_int(trigger.get("knowledge_at_least"))
    if knowledge_at_least is not None and knowledge < knowledge_at_least:
        return False
    affection_at_least = _as_int(trigger.get("affection_at_least"))
    if affection_at_least is not None and affection < affection_at_least:
        return False

    required_quests = trigger.get("completed_quests_include")
    if isinstance(required_quests, list) and required_quests:
        required = {str(item) for item in required_quests if str(item)}
        if not required.issubset(completed_quests):
            return False

    return True


def _build_timeout_resolution(*, runtime_state: dict, timeout_outcome: str) -> EndingResolution:
    step_index = int(runtime_state.get("step_index", 0))
    runtime_state["ending_id"] = "__timeout__"
    runtime_state["ending_outcome"] = timeout_outcome
    runtime_state["ended_at_step"] = step_index
    return EndingResolution(
        run_ended=True,
        ending_id="__timeout__",
        ending_outcome=timeout_outcome,
        ending_title="Time Limit Reached",
        ending_epilogue="Time slips away before you can secure a better ending.",
        run_state=runtime_state,
        matched_rules=[
            {
                "type": "run_ending",
                "source": "timeout",
                "ending_id": "__timeout__",
                "outcome": timeout_outcome,
                "step_index": step_index,
            }
        ],
    )


def resolve_run_ending(
    *,
    endings_def: list[dict] | None,
    run_config: dict | None,
    run_state: dict | None,
    next_node_id: str,
    state_after: dict,
    quest_state: dict | None,
) -> EndingResolution:
    runtime_state = normalize_run_state(run_state)
    normalized_state = normalize_state(state_after)
    config = _normalize_run_config(run_config)
    endings = _normalize_endings(endings_def)
    completed_quests = {
        str(item)
        for item in ((quest_state or {}).get("completed_quests") or [])
        if str(item)
    }

    existing_ending_id = runtime_state.get("ending_id")
    if existing_ending_id:
        return EndingResolution(
            run_ended=True,
            ending_id=str(existing_ending_id),
            ending_outcome=runtime_state.get("ending_outcome"),
            ending_title=None,
            ending_epilogue=None,
            run_state=runtime_state,
            matched_rules=[],
        )

    for ending in endings:
        trigger = dict(ending.get("trigger") or {})
        if not _matches_trigger(
            trigger,
            next_node_id=next_node_id,
            state_after=normalized_state,
            completed_quests=completed_quests,
        ):
            continue
        runtime_state["ending_id"] = str(ending["ending_id"])
        runtime_state["ending_outcome"] = str(ending["outcome"])
        runtime_state["ended_at_step"] = int(runtime_state.get("step_index", 0))
        return EndingResolution(
            run_ended=True,
            ending_id=str(ending["ending_id"]),
            ending_outcome=str(ending["outcome"]),
            ending_title=str(ending.get("title") or ending["ending_id"]),
            ending_epilogue=str(ending.get("epilogue") or ""),
            run_state=runtime_state,
            matched_rules=[
                {
                    "type": "run_ending",
                    "source": "configured",
                    "ending_id": str(ending["ending_id"]),
                    "outcome": str(ending["outcome"]),
                    "step_index": int(runtime_state.get("step_index", 0)),
                }
            ],
        )

    day = int(normalized_state.get("day", 1))
    step_index = int(runtime_state.get("step_index", 0))
    if day > int(config["max_days"]) or step_index >= int(config["max_steps"]):
        return _build_timeout_resolution(
            runtime_state=runtime_state,
            timeout_outcome=str(config["default_timeout_outcome"]),
        )

    return EndingResolution(
        run_ended=False,
        ending_id=None,
        ending_outcome=None,
        ending_title=None,
        ending_epilogue=None,
        run_state=runtime_state,
        matched_rules=[],
    )

