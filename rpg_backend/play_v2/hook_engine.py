from __future__ import annotations

from dataclasses import dataclass

from rpg_backend.author.normalize import trim_text
from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.play_v2.contracts import CallbackQueueItem, HookState, UrbanWorldState


@dataclass(slots=True)
class HookContext:
    target_has_active_hook: bool
    target_has_leveraged_hook: bool
    max_leverage_on_target: float
    actor_is_hook_holder: bool


_STATUS_ORDER: dict[str, int] = {
    "dormant": 0,
    "suspected": 1,
    "active": 2,
    "leveraged": 3,
    "detonated": 4,
}
_AGGRESSIVE_MOVE_FAMILIES = {"accuse", "betray", "public_reveal"}
_ACTIVE_EFFECT_TYPES = {"betrayal", "confrontation"}
_LEVERAGE_EFFECT_TYPES = {"secret_reveal", "public_exposure"}
_LEVERAGE_BASE_VALUES = {
    "blackmail": 0.7,
    "debt": 0.5,
    "knowledge": 0.4,
}
_ACTIVE_HOOK_CONTEXT_STATUSES = {"suspected", "active", "leveraged"}
_CALLBACK_QUEUE_CAP = 8
_HOOK_CALLBACK_ID_PREFIX = "hookcb_"
_HOOK_CALLBACK_KIND_BY_STATUS = {
    "suspected": "hook_probe_callback",
    "active": "hook_pressure_callback",
    "leveraged": "hook_leverage_cash_callback",
    "detonated": "hook_aftermath_callback",
}
_HOOK_CALLBACK_DUE_OFFSET = {
    "hook_probe_callback": 3,
    "hook_pressure_callback": 2,
    "hook_leverage_cash_callback": 2,
    "hook_aftermath_callback": 1,
}
_HOOK_CALLBACK_LATENT_KIND = {
    "hook_probe_callback": "secret_pressure",
    "hook_pressure_callback": "npc_action",
    "hook_leverage_cash_callback": "relationship_debt",
    "hook_aftermath_callback": "public_wave",
}
_HOOK_CALLBACK_SOURCE_MOVE = {
    "hook_probe_callback": "probe_secret",
    "hook_pressure_callback": "accuse",
    "hook_leverage_cash_callback": "betray",
    "hook_aftermath_callback": "public_reveal",
}


@dataclass(slots=True)
class HookTurnEvents:
    actor_id: str
    target_id: str | None
    move_family: str
    effect_types: list[str]
    exposed_secret_ids: list[str]
    is_public_context: bool


def is_hook_callback_item(callback: CallbackQueueItem | None) -> bool:
    if callback is None:
        return False
    return str(getattr(callback, "payoff_kind", "") or "").startswith("hook_")


def get_hook_callback_hook_id(callback: CallbackQueueItem | None) -> str | None:
    if callback is None or not is_hook_callback_item(callback):
        return None
    callback_kind = str(getattr(callback, "payoff_kind", "") or "")
    callback_id = str(getattr(callback, "callback_id", "") or "")
    prefix = f"{_HOOK_CALLBACK_ID_PREFIX}{callback_kind}_"
    if not callback_id.startswith(prefix):
        return None
    hook_id = callback_id[len(prefix):].strip()
    return hook_id or None


def build_hook_callback_question(callback: CallbackQueueItem | None) -> str:
    holder_id = str(getattr(callback, "actor_character_id", None) or "对方").strip() or "对方"
    return trim_text(f"你该怎么面对 {holder_id} 手里的把柄？", 220)


def register_hook_callbacks(state: UrbanWorldState, changed_hook_ids: list[str], turn_index: int | None) -> None:
    if turn_index is None:
        return
    hook_states = getattr(state, "hook_states", None) or {}
    if not hook_states or not changed_hook_ids:
        return
    queue = [item.model_copy(deep=True) for item in (getattr(state, "callback_queue", None) or [])]
    segment_id = str(getattr(state, "segment_id", None) or "").strip()
    scene_question_states = getattr(state, "scene_question_states", None) or {}
    linked_scene_question_id = segment_id or next(iter(scene_question_states), None)
    source_segment_id = segment_id or "hook_callbacks"
    pending = [item for item in queue if str(getattr(item, "status", "pending") or "pending") not in {"consumed", "expired"}]
    new_items: list[CallbackQueueItem] = []
    for hook_id in changed_hook_ids:
        hook = hook_states.get(hook_id)
        if hook is None:
            continue
        callback_kind = _HOOK_CALLBACK_KIND_BY_STATUS.get(str(hook.status or "").strip())
        if callback_kind is None:
            continue
        if any(
            str(item.payoff_kind or "") == callback_kind and get_hook_callback_hook_id(item) == hook_id
            for item in [*pending, *new_items]
        ):
            continue
        due_turn = max(int(turn_index), 0) + _HOOK_CALLBACK_DUE_OFFSET[callback_kind]
        if callback_kind == "hook_probe_callback":
            cue_text = trim_text(
                f"{hook.holder_id} 手里那条关于 {hook.source_secret_id} 的线开始浮上来了。",
                220,
            )
        elif callback_kind == "hook_pressure_callback":
            cue_text = trim_text(f"{hook.holder_id} 看起来快要拿这张牌出手了。", 220)
        elif callback_kind == "hook_leverage_cash_callback":
            cue_text = trim_text(f"{hook.holder_id} 正在把这张牌兑现成现实压力。", 220)
        else:
            cue_text = trim_text(f"{hook.holder_id} 手里的事已经炸开，余波开始扩散。", 220)
        new_items.append(
            CallbackQueueItem(
                callback_id=f"{_HOOK_CALLBACK_ID_PREFIX}{callback_kind}_{hook_id}",
                status="pending",
                source_turn_index=max(int(turn_index), 0),
                source_segment_id=source_segment_id,
                source_move_family=_HOOK_CALLBACK_SOURCE_MOVE[callback_kind],  # type: ignore[arg-type]
                linked_shell_edge_id=None,
                linked_scene_question_id=linked_scene_question_id,
                due_turn_min=due_turn,
                due_turn_max=due_turn,
                kind=_HOOK_CALLBACK_LATENT_KIND[callback_kind],  # type: ignore[arg-type]
                payoff_kind=callback_kind,
                stake_character_ids=[item for item in [hook.holder_id, hook.target_id] if item][:3],
                target_character_ids=[item for item in [hook.target_id] if item][:3],
                actor_character_id=hook.holder_id,
                cue_text=cue_text,
                detonation_text=trim_text(f"你该怎么面对 {hook.holder_id} 手里的把柄？", 220),
                global_deltas={},
                relationship_deltas={},
            )
        )
    if not new_items:
        return
    queue.extend(new_items)
    overflow = max(len(queue) - _CALLBACK_QUEUE_CAP, 0)
    if overflow > 0:
        removable_indexes = sorted(
            range(len(queue)),
            key=lambda idx: (
                int(getattr(queue[idx], "due_turn_min", 0)),
                int(getattr(queue[idx], "due_turn_max", 0)),
                idx,
            ),
        )
        dropped = set(removable_indexes[:overflow])
        queue = [item for idx, item in enumerate(queue) if idx not in dropped]
    state.callback_queue = queue[:_CALLBACK_QUEUE_CAP]


def build_hook_context(state: UrbanWorldState, actor_id: str, target_id: str | None) -> HookContext:
    hook_states = getattr(state, "hook_states", None) or {}
    actor_is_hook_holder = any(hook.holder_id == actor_id for hook in hook_states.values())
    if target_id is None:
        return HookContext(
            target_has_active_hook=False,
            target_has_leveraged_hook=False,
            max_leverage_on_target=0.0,
            actor_is_hook_holder=actor_is_hook_holder,
        )

    target_has_active_hook = False
    target_has_leveraged_hook = False
    max_leverage_on_target = 0.0
    for hook in hook_states.values():
        if hook.target_id != target_id:
            continue
        max_leverage_on_target = max(max_leverage_on_target, float(hook.leverage_value))
        status = str(hook.status or "dormant")
        if status == "leveraged":
            target_has_leveraged_hook = True
            target_has_active_hook = True
            continue
        if status in _ACTIVE_HOOK_CONTEXT_STATUSES:
            target_has_active_hook = True
    return HookContext(
        target_has_active_hook=target_has_active_hook,
        target_has_leveraged_hook=target_has_leveraged_hook,
        max_leverage_on_target=max_leverage_on_target,
        actor_is_hook_holder=actor_is_hook_holder,
    )


def build_initial_hook_states(plan: CompiledPlayPlan) -> dict[str, HookState]:
    raw_hooks = getattr(plan, "hooks", None) or []
    if not raw_hooks:
        return {}
    hook_states: dict[str, HookState] = {}
    for raw_hook in raw_hooks:
        if not isinstance(raw_hook, dict):
            continue
        holder_id = str(raw_hook.get("holder_id") or "").strip()
        target_id = str(raw_hook.get("target_id") or "").strip()
        source_secret_id = str(raw_hook.get("source_secret_id") or "").strip()
        leverage_type = str(raw_hook.get("leverage_type") or "other").strip() or "other"
        if not holder_id or not target_id or not source_secret_id:
            continue
        hook_id = f"{holder_id}__{target_id}__{source_secret_id}"
        hook_states[hook_id] = HookState(
            hook_id=hook_id,
            holder_id=holder_id,
            target_id=target_id,
            source_secret_id=source_secret_id,
            leverage_type=leverage_type,
            status="dormant",
            leverage_value=_LEVERAGE_BASE_VALUES.get(leverage_type.casefold(), 0.3),
        )
    return hook_states


def update_hook_states(state: UrbanWorldState, turn_events: HookTurnEvents, turn_index: int | None = None) -> list[str]:
    hook_states = getattr(state, "hook_states", None) or {}
    if not hook_states:
        return []
    effect_types = {str(effect_type).strip().casefold() for effect_type in turn_events.effect_types if str(effect_type).strip()}
    exposed_secret_ids = {
        str(secret_id).strip()
        for secret_id in turn_events.exposed_secret_ids
        if str(secret_id).strip()
    }
    changed_hook_ids: list[str] = []
    for hook_id, hook in list(hook_states.items()):
        current_status = str(hook.status or "dormant")
        next_status = current_status
        next_leverage_value = float(hook.leverage_value)
        if hook.source_secret_id in exposed_secret_ids and turn_events.is_public_context:
            next_status = "detonated"
            next_leverage_value = 0.0
        elif current_status == "dormant":
            if turn_events.move_family == "probe_secret" and hook.target_id == turn_events.target_id:
                next_status = "suspected"
                next_leverage_value = min(float(hook.leverage_value) + 0.1, 1.0)
        elif current_status == "suspected":
            if (
                (hook.holder_id == turn_events.actor_id and turn_events.move_family in _AGGRESSIVE_MOVE_FAMILIES)
                or bool(_ACTIVE_EFFECT_TYPES & effect_types)
            ):
                next_status = "active"
                next_leverage_value = min(float(hook.leverage_value) + 0.15, 1.0)
        elif current_status == "active":
            if hook.source_secret_id in exposed_secret_ids and bool(_LEVERAGE_EFFECT_TYPES & effect_types):
                next_status = "leveraged"
                next_leverage_value = min(float(hook.leverage_value) + 0.2, 1.0)
        elif current_status == "leveraged":
            if hook.source_secret_id in exposed_secret_ids and turn_events.is_public_context:
                next_status = "detonated"
                next_leverage_value = 0.0
        if _STATUS_ORDER.get(next_status, 0) <= _STATUS_ORDER.get(current_status, 0):
            continue
        hook_states[hook_id] = hook.model_copy(
            update={
                "status": next_status,
                "leverage_value": next_leverage_value,
            }
        )
        changed_hook_ids.append(hook_id)
    state.hook_states = hook_states
    resolved_turn_index = turn_index
    if resolved_turn_index is None:
        try:
            resolved_turn_index = int(getattr(state, "turn_index"))
        except Exception:  # noqa: BLE001
            resolved_turn_index = None
    if changed_hook_ids:
        register_hook_callbacks(state, changed_hook_ids, resolved_turn_index)
    return changed_hook_ids
