from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rpg_backend.author.normalize import unique_preserve
from rpg_backend.play_v2.contracts import HookState, UrbanTurnIntent, UrbanWorldState
from rpg_backend.play_v2.hook_engine import register_hook_callbacks

_HOOK_STATUS_ORDER: dict[str, int] = {
    "dormant": 0,
    "suspected": 1,
    "active": 2,
    "leveraged": 3,
    "detonated": 4,
}
_ACTIVE_EFFECT_TYPES = {"betrayal", "confrontation"}
_LEVERAGE_EFFECT_TYPES = {"secret_reveal", "public_exposure"}
_AGGRESSIVE_MOVE_FAMILIES = {"accuse", "betray", "public_reveal"}
_SECRET_MOVE_FAMILIES = {"probe_secret", "public_reveal", "private_confession"}
_SECRET_KNOWN_CAP = 8
_SECRET_REVEALED_CAP = 4


@dataclass(slots=True)
class HookLifecycleReducerResult:
    changed_hook_ids: list[str]
    known_secret_ids: list[str]
    revealed_secret_ids: list[str]


class HookLifecycleReducer:
    @classmethod
    def apply(
        cls,
        *,
        plan: Any,
        segment: Any,
        state: UrbanWorldState,
        intent: UrbanTurnIntent,
        semantic_result: dict[str, Any],
    ) -> HookLifecycleReducerResult:
        semantic_known_secret_ids = [
            str(item).strip()
            for item in list(semantic_result.get("known_secret_ids_to_add") or [])
            if str(item).strip()
        ]
        semantic_revealed_secret_ids = [
            str(item).strip()
            for item in list(semantic_result.get("revealed_secret_ids") or [])
            if str(item).strip()
        ]
        known_secret_ids = unique_preserve(
            [*list(getattr(state, "known_secret_ids", []) or []), *semantic_known_secret_ids]
        )[:_SECRET_KNOWN_CAP]
        revealed_secret_ids = unique_preserve(semantic_revealed_secret_ids)[:_SECRET_REVEALED_CAP]
        hooks_enabled = bool(getattr(plan, "hooks", None) or []) or bool(getattr(state, "hook_states", None) or {})
        if not hooks_enabled:
            fallback_secret_ids = cls._fallback_secret_ids(segment=segment)
            if intent.move_family in _SECRET_MOVE_FAMILIES and fallback_secret_ids:
                known_secret_ids = unique_preserve([*known_secret_ids, *fallback_secret_ids])[:_SECRET_KNOWN_CAP]
                if intent.move_family in {"probe_secret", "public_reveal"}:
                    revealed_secret_ids = unique_preserve([*revealed_secret_ids, *fallback_secret_ids])[:_SECRET_REVEALED_CAP]
            state.known_secret_ids = known_secret_ids
            state.last_turn_revealed_secret_ids = revealed_secret_ids
            return HookLifecycleReducerResult(
                changed_hook_ids=[],
                known_secret_ids=known_secret_ids,
                revealed_secret_ids=revealed_secret_ids,
            )

        original_hook_states = {
            hook_id: hook.model_copy(deep=True)
            for hook_id, hook in dict(getattr(state, "hook_states", None) or {}).items()
        }
        next_hook_states = dict(original_hook_states)
        effect_types = {
            str(effect.effect_type).strip().casefold()
            for effect in list(getattr(intent, "semantic_effects", []) or [])
            if str(getattr(effect, "effect_type", "")).strip()
        }
        public_context = intent.scene_frame in {"public", "semi_public"}
        semantic_revealed_secret_id_set = {
            str(secret_id).strip()
            for secret_id in semantic_revealed_secret_ids
            if str(secret_id).strip()
        }
        move_known_secret_ids: list[str] = []
        move_revealed_secret_ids: list[str] = []
        changed_hook_ids: list[str] = []

        def _mark_transition(hook: HookState, next_status: str) -> None:
            current = next_hook_states.get(hook.hook_id, hook)
            current_status = str(getattr(current, "status", "dormant") or "dormant")
            if current_status == next_status:
                return
            leverage_value = float(getattr(current, "leverage_value", 0.0) or 0.0)
            if next_status == "suspected":
                leverage_value = min(leverage_value + 0.1, 1.0)
            elif next_status == "active":
                leverage_value = min(leverage_value + 0.15, 1.0)
            elif next_status == "leveraged":
                leverage_value = min(leverage_value + 0.2, 1.0)
            elif next_status == "detonated":
                leverage_value = 0.0
            next_hook_states[hook.hook_id] = current.model_copy(
                update={
                    "status": next_status,
                    "leverage_value": leverage_value,
                }
            )
            changed_hook_ids.append(hook.hook_id)

        for hook in original_hook_states.values():
            hook_status = str(getattr(hook, "status", "dormant") or "dormant")
            secret_id = str(getattr(hook, "source_secret_id", "") or "").strip()
            holder_id = str(getattr(hook, "holder_id", "") or "").strip()
            target_id = str(getattr(hook, "target_id", "") or "").strip()
            if not secret_id:
                continue
            if public_context and secret_id in semantic_revealed_secret_id_set:
                _mark_transition(hook, "detonated")
                continue
            if intent.move_family == "public_reveal":
                secret_match = bool(semantic_revealed_secret_id_set) and secret_id in semantic_revealed_secret_id_set
                target_match = bool(intent.target_id) and target_id == str(intent.target_id).strip()
                holder_match = bool(intent.target_id) and holder_id == str(intent.target_id).strip()
                if secret_match or target_match or holder_match:
                    _mark_transition(hook, "detonated")
                    continue
            if intent.move_family in {"accuse", "betray"} and intent.target_id and target_id == str(intent.target_id).strip():
                if hook_status == "leveraged":
                    _mark_transition(hook, "detonated")
                    continue
            if intent.move_family == "private_confession" and intent.target_id and holder_id == str(intent.target_id).strip():
                if hook_status in {"active", "leveraged"}:
                    _mark_transition(hook, "dormant")
                    continue
            if intent.move_family == "ally_with" and intent.target_id and holder_id == str(intent.target_id).strip():
                if hook_status == "active":
                    _mark_transition(hook, "leveraged")
                    continue
            if intent.move_family == "probe_secret" and intent.target_id and holder_id == str(intent.target_id).strip():
                if hook_status == "dormant":
                    _mark_transition(hook, "suspected")
                    continue
                if hook_status == "suspected":
                    _mark_transition(hook, "active")
                    continue
            if hook_status == "suspected":
                if (
                    holder_id == "player" and intent.move_family in _AGGRESSIVE_MOVE_FAMILIES
                ) or bool(_ACTIVE_EFFECT_TYPES & effect_types):
                    _mark_transition(hook, "active")
                    continue
            if hook_status == "active" and secret_id in semantic_revealed_secret_id_set and bool(_LEVERAGE_EFFECT_TYPES & effect_types):
                _mark_transition(hook, "leveraged")

        if intent.move_family == "probe_secret" and intent.target_id:
            probe_candidates = cls._matching_hooks(original_hook_states, holder_id=intent.target_id)
            if probe_candidates:
                selected_hook = probe_candidates[0]
                move_revealed_secret_ids.append(selected_hook.source_secret_id)
                if str(selected_hook.status or "dormant") == "suspected":
                    move_known_secret_ids.append(selected_hook.source_secret_id)
        elif intent.move_family == "public_reveal":
            public_candidates = cls._matching_public_reveal_hooks(
                original_hook_states,
                target_id=intent.target_id,
                secret_ids=semantic_revealed_secret_id_set,
            )
            if public_candidates:
                selected_hook = public_candidates[0]
                move_known_secret_ids.append(selected_hook.source_secret_id)
                move_revealed_secret_ids.append(selected_hook.source_secret_id)
        elif intent.move_family == "private_confession" and intent.target_id:
            confession_candidates = cls._matching_hooks(
                original_hook_states,
                holder_id=intent.target_id,
                statuses={"active", "leveraged", "suspected"},
            )
            if confession_candidates:
                move_known_secret_ids.append(confession_candidates[0].source_secret_id)
        elif intent.move_family in {"accuse", "betray"} and intent.target_id:
            detonation_candidates = cls._matching_hooks(
                original_hook_states,
                target_id=intent.target_id,
                statuses={"leveraged"},
            )
            if detonation_candidates:
                move_known_secret_ids.append(detonation_candidates[0].source_secret_id)
                move_revealed_secret_ids.append(detonation_candidates[0].source_secret_id)

        if (
            intent.move_family in _SECRET_MOVE_FAMILIES
            and not move_known_secret_ids
            and not move_revealed_secret_ids
            and not semantic_known_secret_ids
            and not semantic_revealed_secret_ids
        ):
            fallback_secret_ids = cls._fallback_secret_ids(segment=segment)
            if fallback_secret_ids:
                move_known_secret_ids.extend(fallback_secret_ids)
                if intent.move_family in {"probe_secret", "public_reveal"}:
                    move_revealed_secret_ids.extend(fallback_secret_ids)

        known_secret_ids = unique_preserve([*known_secret_ids, *move_known_secret_ids])[:_SECRET_KNOWN_CAP]
        revealed_secret_ids = unique_preserve([*revealed_secret_ids, *move_revealed_secret_ids])[:_SECRET_REVEALED_CAP]
        state.hook_states = next_hook_states
        state.known_secret_ids = known_secret_ids
        state.last_turn_revealed_secret_ids = revealed_secret_ids

        deduped_changed_hook_ids = unique_preserve(changed_hook_ids)
        if deduped_changed_hook_ids:
            register_hook_callbacks(state, deduped_changed_hook_ids, state.turn_index)
        return HookLifecycleReducerResult(
            changed_hook_ids=deduped_changed_hook_ids,
            known_secret_ids=known_secret_ids,
            revealed_secret_ids=revealed_secret_ids,
        )

    @staticmethod
    def _fallback_secret_ids(*, segment: Any) -> list[str]:
        return [
            str(item).strip()
            for item in list(getattr(segment, "allocated_secret_ids", []) or [])[:1]
            if str(item).strip()
        ]

    @staticmethod
    def _matching_hooks(
        hook_states: dict[str, HookState],
        *,
        holder_id: str | None = None,
        target_id: str | None = None,
        statuses: set[str] | None = None,
        secret_ids: set[str] | None = None,
    ) -> list[HookState]:
        normalized_holder_id = str(holder_id or "").strip()
        normalized_target_id = str(target_id or "").strip()
        normalized_secret_ids = {
            str(secret_id).strip()
            for secret_id in set(secret_ids or set())
            if str(secret_id).strip()
        }
        matches: list[HookState] = []
        for hook in hook_states.values():
            hook_status = str(getattr(hook, "status", "dormant") or "dormant")
            if normalized_holder_id and str(getattr(hook, "holder_id", "") or "").strip() != normalized_holder_id:
                continue
            if normalized_target_id and str(getattr(hook, "target_id", "") or "").strip() != normalized_target_id:
                continue
            if statuses is not None and hook_status not in statuses:
                continue
            if normalized_secret_ids and str(getattr(hook, "source_secret_id", "") or "").strip() not in normalized_secret_ids:
                continue
            matches.append(hook)
        return sorted(
            matches,
            key=lambda hook: (
                _HOOK_STATUS_ORDER.get(str(getattr(hook, "status", "dormant") or "dormant"), 99),
                -float(getattr(hook, "leverage_value", 0.0) or 0.0),
                str(getattr(hook, "hook_id", "") or ""),
            ),
        )

    @classmethod
    def _matching_public_reveal_hooks(
        cls,
        hook_states: dict[str, HookState],
        *,
        target_id: str | None,
        secret_ids: set[str],
    ) -> list[HookState]:
        candidates: list[HookState] = []
        if target_id:
            candidates.extend(cls._matching_hooks(hook_states, target_id=target_id))
            candidates.extend(cls._matching_hooks(hook_states, holder_id=target_id))
        if secret_ids:
            candidates.extend(cls._matching_hooks(hook_states, secret_ids=secret_ids))
        seen_hook_ids: set[str] = set()
        deduped: list[HookState] = []
        for hook in candidates:
            if hook.hook_id in seen_hook_ids:
                continue
            seen_hook_ids.add(hook.hook_id)
            deduped.append(hook)
        return deduped
