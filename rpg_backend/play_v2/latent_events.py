from __future__ import annotations

from dataclasses import dataclass, field

from rpg_backend.author.normalize import trim_text, unique_preserve
from rpg_backend.author_v2.contracts import CompiledPlayPlan, CompiledSegment
from rpg_backend.play_v2.shell_propagation import pick_shell_edge
from rpg_backend.play_v2.contracts import (
    CallbackQueueItem,
    CallbackTurnStatusRecord,
    LatentEvent,
    LatentEventControl,
    LatentEventKind,
    LatentRadarTrend,
    NpcMindState,
    TurnEscalationRecord,
    UnresolvedCostRecord,
    UrbanControlResolution,
    UrbanLatentRadarItem,
    UrbanTurnIntent,
    UrbanWorldState,
)


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class LatentTurnOutcome:
    triggered_record: TurnEscalationRecord | None = None
    latent_feedback: tuple[str, ...] = ()
    latent_ops: tuple[str, ...] = ()
    control_resolution: UrbanControlResolution = field(
        default_factory=lambda: UrbanControlResolution(
            action_type="none",
            applied=False,
            summary="未执行控雷操作。",
            tags=[],
        )
    )
    latent_radar: tuple[UrbanLatentRadarItem, ...] = ()
    callback_status: CallbackTurnStatusRecord = field(default_factory=CallbackTurnStatusRecord)
    key_segment_conversion: bool = False
    top_event_id: str | None = None
    top_event_kind: LatentEventKind | None = None
    top_event_transition: str = "none"


@dataclass(frozen=True)
class _LatentUpsert:
    kind: LatentEventKind
    stake_family: str
    stake_character_ids: tuple[str, ...]
    target_character_ids: tuple[str, ...]
    actor_character_id: str | None
    pressure: int
    maturity: int
    trigger_threshold: int


class LatentEventEngine:
    @staticmethod
    def resolve_turn_latent_events(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        before_state: UrbanWorldState,
        state: UrbanWorldState,
        prioritized_cost: UnresolvedCostRecord | None = None,
        prefer_cost_return_primary_driver: bool = False,
        suppress_cost_return_primary_driver: bool = False,
        cost_return_retry_bias: bool = False,
        cost_return_retry_bias_steps: int = 0,
        secondary_due_cost_pressure: bool = False,
    ) -> LatentTurnOutcome:
        events = [event.model_copy(deep=True) for event in state.latent_events]
        before_events = [event.model_copy(deep=True) for event in state.latent_events]
        callback_upserts, callback_feedback, callback_tags, callback_status = LatentEventEngine.consume_due_callbacks(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
        )
        upserts = LatentEventEngine.derive_upserts(
            plan=plan,
            segment=segment,
            intent=intent,
            before_state=before_state,
            state=state,
            prioritized_cost=prioritized_cost,
            cost_return_retry_bias=cost_return_retry_bias,
            cost_return_retry_bias_steps=cost_return_retry_bias_steps,
        )
        upserts = [*callback_upserts, *upserts]
        events = LatentEventEngine.merge_and_advance(
            plan=plan,
            segment=segment,
            intent=intent,
            before_state=before_state,
            state=state,
            events=events,
            upserts=upserts,
        )
        events, op_feedback, op_tags, forced_controls, control_resolution = LatentEventEngine.apply_control_ops(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
            events=events,
        )
        triggered, retained_events, key_segment_conversion = LatentEventEngine.choose_trigger(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
            events=events,
            forced_controls=forced_controls,
            prefer_cost_return_primary_driver=prefer_cost_return_primary_driver,
            suppress_cost_return_primary_driver=suppress_cost_return_primary_driver,
        )
        if key_segment_conversion:
            op_tags = [*op_tags, "latent:key_segment:conversion"]
        foreshadows, foreshadow_tags = LatentEventEngine.render_foreshadows(
            plan=plan,
            segment=segment,
            intent=intent,
            events=retained_events,
        )
        state.latent_events = retained_events[:6]
        state.last_turn_triggered_event_id = triggered.event_id if triggered is not None else None
        top_before = LatentEventEngine._top_event(before_events)
        top_after = LatentEventEngine._top_event(state.latent_events)
        top_event_id: str | None = None
        top_event_kind: LatentEventKind | None = None
        top_event_transition = "none"
        if triggered is not None:
            top_event_id = triggered.event_id
            top_event_kind = triggered.kind
            top_event_transition = "triggered"
        elif top_after is not None:
            top_event_id = top_after.event_id
            top_event_kind = top_after.kind
            previous = next((item for item in before_events if item.event_id == top_after.event_id), None)
            if previous is None:
                top_event_transition = "rising"
            else:
                after_score = top_after.pressure + top_after.maturity
                before_score = previous.pressure + previous.maturity
                if after_score > before_score:
                    top_event_transition = "rising"
                elif after_score < before_score:
                    top_event_transition = "cooling"
                else:
                    top_event_transition = "rising" if top_after.age_turns > previous.age_turns else "cooling"
        elif top_before is not None:
            top_event_id = top_before.event_id
            top_event_kind = top_before.kind
            top_event_transition = "cooling"
        if secondary_due_cost_pressure and prioritized_cost is not None:
            op_feedback = [
                trim_text(
                    "你这回合先压了别的线，这笔到期账没消失，下一拍会更快抢回主线。",
                    220,
                ),
                *op_feedback,
            ]
            op_tags = [*op_tags, "cost_return:secondary_due_pressure"]
        if top_event_kind is not None:
            transition_tag = {
                "rising": f"latent:{top_event_kind}:rising",
                "cooling": f"latent:{top_event_kind}:cooled",
                "triggered": f"latent:{top_event_kind}:triggered",
            }.get(top_event_transition)
            if transition_tag:
                op_tags = [*op_tags, transition_tag]
        LatentEventEngine._recompute_pressure_bars(state)
        radar = LatentEventEngine._build_latent_radar(
            state=state,
            triggered=triggered,
            op_tags=[*op_tags, *foreshadow_tags],
        )
        return LatentTurnOutcome(
            triggered_record=LatentEventEngine._record_from_event(triggered, forced_controls.get(triggered.event_id, "none")) if triggered is not None else None,
            latent_feedback=tuple([*callback_feedback[:1], *foreshadows[:2], *op_feedback[:1]])[:4],
            latent_ops=tuple(unique_preserve([*callback_tags, *op_tags, *foreshadow_tags])[:6]),
            control_resolution=control_resolution,
            latent_radar=tuple(radar[:4]),
            callback_status=callback_status,
            key_segment_conversion=key_segment_conversion,
            top_event_id=top_event_id,
            top_event_kind=top_event_kind,
            top_event_transition=top_event_transition,
        )

    @staticmethod
    def derive_upserts(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        before_state: UrbanWorldState,
        state: UrbanWorldState,
        prioritized_cost: UnresolvedCostRecord | None = None,
        cost_return_retry_bias: bool = False,
        cost_return_retry_bias_steps: int = 0,
    ) -> list[_LatentUpsert]:
        target_id = intent.target_id
        stake_ids = tuple(LatentEventEngine._stake_character_ids(segment, state, target_id, None))
        upserts: list[_LatentUpsert] = []
        if prioritized_cost is not None and prioritized_cost.status == "pending":
            cost_upsert = LatentEventEngine._upsert_from_prioritized_cost(
                plan=plan,
                segment=segment,
                state=state,
                prioritized_cost=prioritized_cost,
                retry_bias=cost_return_retry_bias,
                retry_bias_steps=cost_return_retry_bias_steps,
            )
            if cost_upsert is not None:
                upserts.append(cost_upsert)
        if intent.move_family in {"comfort", "ally_with", "private_confession", "accuse", "betray", "flirt"} and (
            intent.scene_frame != "private" or state.scene_heat >= 2 or state.route_lock >= 1 or intent.move_family not in {"comfort", "flirt"}
        ):
            upserts.append(
                _LatentUpsert(
                    kind="relationship_debt",
                    stake_family=LatentEventEngine._stake_family(kind="relationship_debt", plan=plan, target_id=target_id, actor_id=None),
                    stake_character_ids=stake_ids[:3],
                    target_character_ids=tuple(item for item in [target_id] if item),
                    actor_character_id=stake_ids[0] if stake_ids else target_id,
                    pressure=4 if intent.move_family in {"betray", "ally_with"} else 3 if intent.move_family in {"private_confession", "accuse"} else 2,
                    maturity=2 if intent.move_family in {"ally_with", "private_confession", "betray"} else 1,
                    trigger_threshold=4,
                )
            )
        if (
            intent.scene_frame != "private"
            or len(state.public_event_ids) > len(before_state.public_event_ids)
            or intent.move_family in {"deflect", "public_reveal", "accuse", "betray", "ally_with"}
        ):
            upserts.append(
                _LatentUpsert(
                    kind="public_wave",
                    stake_family=LatentEventEngine._stake_family(kind="public_wave", plan=plan, target_id=target_id, actor_id=None),
                    stake_character_ids=stake_ids[:3],
                    target_character_ids=tuple(item for item in [target_id] if item),
                    actor_character_id=None,
                    pressure=4 if intent.move_family in {"public_reveal", "betray"} else 3,
                    maturity=2 if intent.scene_frame != "private" else 1,
                    trigger_threshold=4,
                )
            )
        if (
            intent.move_family in {"probe_secret", "deflect", "public_reveal", "private_confession"}
            and (
                segment.segment_role in {"pressure", "reveal", "terminal"}
                or state.secret_exposure > before_state.secret_exposure
                or intent.scene_frame != "private"
            )
        ):
            upserts.append(
                _LatentUpsert(
                    kind="secret_pressure",
                    stake_family=LatentEventEngine._stake_family(kind="secret_pressure", plan=plan, target_id=target_id, actor_id=target_id),
                    stake_character_ids=tuple(item for item in [target_id] if item),
                    target_character_ids=tuple(item for item in [target_id] if item),
                    actor_character_id=target_id,
                    pressure=4 if intent.move_family == "public_reveal" else 3,
                    maturity=2 if intent.move_family in {"public_reveal", "private_confession"} else 1,
                    trigger_threshold=4,
                )
            )
        actor_id = LatentEventEngine._npc_action_actor(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
        )
        if actor_id is not None and (
            state.scene_heat >= 2 or intent.move_family in {"betray", "accuse", "jealousy_trigger", "ally_with", "public_reveal"}
        ):
            upserts.append(
                _LatentUpsert(
                    kind="npc_action",
                    stake_family=LatentEventEngine._stake_family(kind="npc_action", plan=plan, target_id=target_id, actor_id=actor_id),
                    stake_character_ids=(actor_id,),
                    target_character_ids=tuple(item for item in [target_id] if item and item != actor_id),
                    actor_character_id=actor_id,
                    pressure=4 if intent.move_family in {"betray", "public_reveal", "jealousy_trigger"} else 3,
                    maturity=2 if intent.scene_frame != "private" else 1,
                    trigger_threshold=4,
                )
            )
        return upserts

    @staticmethod
    def _upsert_from_prioritized_cost(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
        prioritized_cost: UnresolvedCostRecord,
        retry_bias: bool = False,
        retry_bias_steps: int = 0,
    ) -> _LatentUpsert | None:
        due_gap = int(prioritized_cost.due_turn) - int(state.turn_index)
        key_segment = segment.segment_role in {"reveal", "terminal"}
        if due_gap > 1 and not key_segment:
            return None
        if prioritized_cost.scene_question_focus == "who_takes_blame":
            kind: LatentEventKind = "public_wave"
        elif prioritized_cost.scene_question_focus == "who_gets_chased":
            kind = "npc_action"
        else:
            kind = "relationship_debt"
        owner_ids = tuple(prioritized_cost.owner_character_ids[:3])
        stake_ids = owner_ids or tuple(item for item in [prioritized_cost.payer_character_id] if item)
        target_ids = tuple(
            item
            for item in [prioritized_cost.beneficiary_character_id, prioritized_cost.payer_character_id]
            if item
        )
        retry_steps = max(0, int(retry_bias_steps))
        pressure = (5 if due_gap <= 0 else 4) + (retry_steps if retry_bias else 0)
        maturity = (6 if (key_segment or due_gap <= 0) else 4) + (retry_steps if retry_bias else 0)
        threshold = 1 if (key_segment and due_gap <= 0) else 3
        if retry_bias:
            threshold = max(1, threshold - min(retry_steps, 2))
        return _LatentUpsert(
            kind=kind,
            stake_family=f"cost_return:{prioritized_cost.scene_question_focus}",
            stake_character_ids=stake_ids[:3],
            target_character_ids=target_ids[:3],
            actor_character_id=prioritized_cost.payer_character_id,
            pressure=_clamp(pressure, 0, 6),
            maturity=_clamp(maturity, 0, 6),
            trigger_threshold=max(1, threshold),
        )

    @staticmethod
    def consume_due_callbacks(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
    ) -> tuple[list[_LatentUpsert], list[str], list[str], CallbackTurnStatusRecord]:
        del intent
        pending: list[CallbackQueueItem] = []
        due_candidates: list[CallbackQueueItem] = []
        expired_count = 0
        for item in state.callback_queue:
            callback = item.model_copy(deep=True)
            if callback.status in {"consumed", "expired"}:
                continue
            if state.turn_index > callback.due_turn_max:
                callback.status = "expired"
                expired_count += 1
                continue
            pending.append(callback)
            if (
                callback.due_turn_min <= state.turn_index <= callback.due_turn_max
                and (
                    segment.segment_role in {"pressure", "reveal", "terminal"}
                    or state.scene_question_states.get(callback.linked_scene_question_id or "", None) is not None
                )
            ):
                due_candidates.append(callback)
        triggered: CallbackQueueItem | None = None
        if due_candidates:
            triggered = max(
                due_candidates,
                key=lambda item: (
                    2 if segment.segment_role in {"reveal", "terminal"} else 0,
                    item.due_turn_min,
                    item.callback_id,
                ),
            )
            pending = [item for item in pending if item.callback_id != triggered.callback_id]
        state.callback_queue = pending[:8]
        if triggered is None:
            return (
                [],
                [],
                [f"callback:expired:{expired_count}"] if expired_count > 0 else [],
                CallbackTurnStatusRecord(
                    created_count=0,
                    matured_count=0,
                    consumed_count=0,
                    pending_count=len(pending),
                    triggered_callback_id=None,
                    triggered_kind=None,
                    summary="本回合没有回调到期。",
                ),
            )
        upsert = _LatentUpsert(
            kind=triggered.kind,
            stake_family=f"callback:{triggered.payoff_kind}",
            stake_character_ids=tuple(triggered.stake_character_ids),
            target_character_ids=tuple(triggered.target_character_ids),
            actor_character_id=triggered.actor_character_id,
            pressure=4,
            maturity=6,
            trigger_threshold=1,
        )
        return (
            [upsert],
            [trim_text(triggered.cue_text, 220)],
            [f"callback:{triggered.callback_id}:due", f"latent:{triggered.kind}:callback_due"],
            CallbackTurnStatusRecord(
                created_count=0,
                matured_count=1,
                consumed_count=1,
                pending_count=len(pending),
                triggered_callback_id=triggered.callback_id,
                triggered_kind=triggered.kind,
                summary=trim_text(f"回调到期：{triggered.detonation_text}", 220),
            ),
        )

    @staticmethod
    def merge_and_advance(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        before_state: UrbanWorldState,
        state: UrbanWorldState,
        events: list[LatentEvent],
        upserts: list[_LatentUpsert],
    ) -> list[LatentEvent]:
        merged = [event.model_copy(deep=True) for event in events if event.status != "triggered"]
        for upsert in upserts:
            upsert_key = (
                upsert.kind,
                plan.story_shell_id,
                upsert.stake_family,
                tuple(sorted(set(upsert.stake_character_ids))),
                tuple(sorted(set(upsert.target_character_ids))),
            )
            match = next(
                (
                    event
                    for event in merged
                    if (
                        event.kind,
                        event.shell_id,
                        event.stake_family,
                        tuple(sorted(set(event.stake_character_ids))),
                        tuple(sorted(set(event.target_character_ids))),
                    )
                    == upsert_key
                ),
                None,
            )
            if match is None:
                merged.append(
                    LatentEventEngine._refresh_event(
                        plan=plan,
                        state=state,
                        event=LatentEvent(
                            event_id=f"latent_{state.turn_index}_{segment.segment_id}_{len(merged)}",
                            kind=upsert.kind,
                            shell_id=plan.story_shell_id,
                            source_turn_index=state.turn_index,
                            source_segment_id=segment.segment_id,
                            stake_family=upsert.stake_family,
                            stake_character_ids=sorted(set(upsert.stake_character_ids))[:3],
                            target_character_ids=sorted(set(upsert.target_character_ids))[:3],
                            actor_character_id=upsert.actor_character_id,
                            pressure=_clamp(upsert.pressure, 0, 6),
                            maturity=_clamp(upsert.maturity, 0, 6),
                            trigger_threshold=upsert.trigger_threshold,
                            age_turns=0,
                            status="latent",
                            visibility="semi_visible",
                            trigger_window_roles=LatentEventEngine._trigger_window_roles(upsert.kind),
                            trigger_window_frames=LatentEventEngine._trigger_window_frames(upsert.kind),
                            foreshadow_text="这件事还没过去。",
                            detonation_text="这件事自己炸回来了。",
                            global_deltas={},
                            relationship_deltas={},
                            reaction_cause_tags=[],
                        ),
                    )
                )
                continue
            match.pressure = _clamp(match.pressure + max(1, upsert.pressure - 1), 0, 6)
            match.maturity = _clamp(max(match.maturity, upsert.maturity), 0, 6)
            if upsert.actor_character_id and not match.actor_character_id:
                match.actor_character_id = upsert.actor_character_id
            match.stake_character_ids = sorted(set([*match.stake_character_ids, *upsert.stake_character_ids]))[:3]
            match.target_character_ids = sorted(set([*match.target_character_ids, *upsert.target_character_ids]))[:3]
            LatentEventEngine._refresh_event(plan=plan, state=state, event=match)
        for event in merged:
            maturity_gain = 1
            pressure_gain = 0
            event.age_turns = _clamp(event.age_turns + 1, 0, 12)
            if event.kind == "public_wave" and intent.scene_frame != "private":
                maturity_gain += 1
            elif event.kind == "relationship_debt" and intent.move_family in {"comfort", "ally_with", "private_confession", "betray", "accuse"}:
                maturity_gain += 1
            elif event.kind == "secret_pressure" and (state.secret_exposure > before_state.secret_exposure or intent.move_family in {"probe_secret", "public_reveal"}):
                maturity_gain += 1
            elif event.kind == "npc_action" and state.scene_heat >= 3:
                maturity_gain += 1
            if state.scene_heat >= 4:
                pressure_gain += 1
            if event.kind == "public_wave" and intent.scene_frame != "private":
                pressure_gain += 1
            if event.kind == "secret_pressure" and state.secret_exposure >= 2:
                pressure_gain += 1
            if event.kind == "relationship_debt" and state.route_lock >= 2:
                pressure_gain += 1
            maturity_gain += LatentEventEngine._delay_preference_bonus(plan=plan, event=event)
            pressure_gain += LatentEventEngine._sensitivity_pressure_bonus(plan=plan, event=event)
            event.maturity = _clamp(event.maturity + maturity_gain, 0, 6)
            event.pressure = _clamp(event.pressure + pressure_gain, 0, 6)
            event.status = "primed" if event.maturity >= max(event.trigger_threshold - 1, 1) or event.pressure + event.maturity >= event.trigger_threshold + 1 else "latent"
            LatentEventEngine._refresh_event(plan=plan, state=state, event=event)
        return LatentEventEngine._cap_events(plan=plan, state=state, events=merged)

    @staticmethod
    def apply_control_ops(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
        events: list[LatentEvent],
    ) -> tuple[list[LatentEvent], list[str], list[str], dict[str, LatentEventControl], UrbanControlResolution]:
        del segment
        feedback: list[str] = []
        tags: list[str] = []
        forced_controls: dict[str, LatentEventControl] = {}
        control = intent.control_action
        if control == "none":
            return (
                events,
                [],
                [],
                forced_controls,
                UrbanControlResolution(
                    action_type="none",
                    applied=False,
                    summary="这一回合你没有主动控雷，局势继续自然发酵。",
                    tags=[],
                ),
            )
        candidate, target_mode = LatentEventEngine._choose_control_candidate(
            plan=plan,
            intent=intent,
            control=control,
            events=events,
        )
        if candidate is None:
            return (
                events,
                [],
                [],
                forced_controls,
                UrbanControlResolution(
                    action_type=control,
                    target_mode=target_mode,
                    target_kind=intent.control_target_kind,
                    target_id=intent.control_target_id,
                    applied=False,
                    summary="当前没有可执行的控雷目标。",
                    tags=[],
                ),
            )
        if control == "redirect":
            redirect_target = LatentEventEngine._resolve_redirect_target_id(plan=plan, intent=intent, event=candidate)
            if redirect_target is None:
                return (
                    events,
                    [],
                    [],
                    forced_controls,
                    UrbanControlResolution(
                        action_type=control,
                        target_mode=target_mode,
                        target_kind=candidate.kind,
                        target_id=intent.control_target_id,
                        target_event_id=candidate.event_id,
                        applied=False,
                        summary="转移需要指定有效角色目标。",
                        tags=[],
                    ),
                )
            candidate.target_character_ids = [redirect_target]
            candidate.pressure = _clamp(candidate.pressure + 1, 0, 6)
            tag = f"latent:{candidate.kind}:redirect"
            feedback.append(LatentEventEngine._op_feedback(plan=plan, event=candidate, control=control, intent=intent))
            tags.append(tag)
            LatentEventEngine._refresh_event(plan=plan, state=state, event=candidate)
            return (
                events,
                unique_preserve(feedback)[:2],
                unique_preserve(tags)[:6],
                forced_controls,
                UrbanControlResolution(
                    action_type=control,
                    target_mode=target_mode,
                    target_kind=candidate.kind,
                    target_id=redirect_target,
                    target_event_id=candidate.event_id,
                    applied=True,
                    summary=f"你把{LatentEventEngine._kind_label(candidate.kind)}转到了{LatentEventEngine._name(plan, redirect_target)}身上，短期稳住了主线代价。",
                    tags=[tag],
                ),
            )
        if control == "press":
            pressure_drop = 0 if LatentEventEngine._pressure_resists_press(plan=plan, event=candidate) else 1
            candidate.pressure = _clamp(candidate.pressure - pressure_drop, 0, 6)
            candidate.maturity = _clamp(candidate.maturity - 1, 0, 6)
            candidate.status = "cooled" if candidate.pressure + candidate.maturity <= 1 else candidate.status
            if intent.move_family == "deflect":
                candidate.age_turns = _clamp(candidate.age_turns + 1, 0, 12)
            forced_controls[candidate.event_id] = control
            tag = f"latent:{candidate.kind}:press"
            feedback.append(LatentEventEngine._op_feedback(plan=plan, event=candidate, control=control, intent=intent))
            tags.append(tag)
            LatentEventEngine._refresh_event(plan=plan, state=state, event=candidate)
            return (
                events,
                unique_preserve(feedback)[:2],
                unique_preserve(tags)[:6],
                forced_controls,
                UrbanControlResolution(
                    action_type=control,
                    target_mode=target_mode,
                    target_kind=candidate.kind,
                    target_id=intent.control_target_id,
                    target_event_id=candidate.event_id,
                    applied=True,
                    summary=f"你先把{LatentEventEngine._kind_label(candidate.kind)}按住了，但这笔压力还在后台积压。",
                    tags=[tag],
                ),
            )
        candidate.maturity = _clamp(max(candidate.maturity, min(candidate.trigger_threshold, 6)), 0, 6)
        candidate.status = "primed"
        forced_controls[candidate.event_id] = "detonate"
        tag = f"latent:{candidate.kind}:detonate"
        feedback.append(LatentEventEngine._op_feedback(plan=plan, event=candidate, control="detonate", intent=intent))
        tags.append(tag)
        LatentEventEngine._refresh_event(plan=plan, state=state, event=candidate)
        return (
            events,
            unique_preserve(feedback)[:2],
            unique_preserve(tags)[:6],
            forced_controls,
            UrbanControlResolution(
                action_type="detonate",
                target_mode=target_mode,
                target_kind=candidate.kind,
                target_id=intent.control_target_id,
                target_event_id=candidate.event_id,
                applied=True,
                summary=f"你主动提前拆了{LatentEventEngine._kind_label(candidate.kind)}这颗雷，当回合代价更痛但不确定性下降了。",
                tags=[tag],
            ),
        )

    @staticmethod
    def _choose_control_candidate(
        *,
        plan: CompiledPlayPlan,
        intent: UrbanTurnIntent,
        control: LatentEventControl,
        events: list[LatentEvent],
    ) -> tuple[LatentEvent | None, str | None]:
        candidates = [event for event in events if event.status != "cooled"]
        if not candidates:
            return None, intent.control_target_mode
        target_mode = intent.control_target_mode
        if intent.control_target_kind is not None:
            filtered = [event for event in candidates if event.kind == intent.control_target_kind]
            if filtered:
                candidates = filtered
                if target_mode is None:
                    target_mode = "kind"
        preferred = LatentEventEngine._preferred_kinds_for_move(intent.move_family, control)
        if intent.control_target_id:
            by_event = [event for event in candidates if event.event_id == intent.control_target_id]
            if by_event:
                candidates = by_event
                target_mode = "event"
            else:
                cast_ids = {member.character_id for member in plan.cast}
                if intent.control_target_id in cast_ids:
                    by_character = [
                        event
                        for event in candidates
                        if intent.control_target_id in set(event.target_character_ids)
                        or intent.control_target_id in set(event.stake_character_ids)
                        or event.actor_character_id == intent.control_target_id
                    ]
                    if by_character:
                        candidates = by_character
                        target_mode = "character"
                    else:
                        return None, "character"
                else:
                    return None, target_mode
        if not candidates:
            return None, target_mode
        chosen = max(
            candidates,
            key=lambda item: (
                2 if item.kind in set(preferred) else 0,
                item.pressure + item.maturity,
                item.age_turns,
                item.event_id,
            ),
        )
        return chosen, target_mode

    @staticmethod
    def _resolve_redirect_target_id(
        *,
        plan: CompiledPlayPlan,
        intent: UrbanTurnIntent,
        event: LatentEvent,
    ) -> str | None:
        cast_ids = {member.character_id for member in plan.cast}
        if intent.control_target_id:
            if intent.control_target_id in cast_ids:
                return intent.control_target_id
            return None
        if intent.target_id and intent.target_id in cast_ids:
            return intent.target_id
        if event.target_character_ids:
            current = event.target_character_ids[0]
            if current in cast_ids:
                return current
        return None

    @staticmethod
    def _kind_label(kind: LatentEventKind) -> str:
        return {
            "relationship_debt": "关系旧账",
            "public_wave": "公开风向",
            "secret_pressure": "秘密压力",
            "npc_action": "人物动作",
        }[kind]

    @staticmethod
    def _preferred_kinds_for_move(move_family: str, control: LatentEventControl) -> tuple[LatentEventKind, ...]:
        if control == "detonate":
            if move_family == "public_reveal":
                return ("secret_pressure", "public_wave")
            if move_family in {"private_confession", "probe_secret"}:
                return ("secret_pressure", "relationship_debt")
            return ("secret_pressure", "public_wave", "relationship_debt", "npc_action")
        if control == "press":
            if move_family == "deflect":
                return ("public_wave", "secret_pressure")
            if move_family in {"comfort", "flirt"}:
                return ("relationship_debt",)
            return ("relationship_debt", "public_wave", "secret_pressure", "npc_action")
        if control == "redirect":
            if move_family == "ally_with":
                return ("relationship_debt", "npc_action")
            if move_family == "accuse":
                return ("public_wave", "npc_action")
            return ("public_wave", "relationship_debt", "npc_action", "secret_pressure")
        return ()

    @staticmethod
    def choose_trigger(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
        events: list[LatentEvent],
        forced_controls: dict[str, LatentEventControl],
        prefer_cost_return_primary_driver: bool = False,
        suppress_cost_return_primary_driver: bool = False,
    ) -> tuple[LatentEvent | None, list[LatentEvent], bool]:
        key_segment = segment.segment_role in {"reveal", "terminal"}
        pressed_event_ids = {event_id for event_id, control in forced_controls.items() if control == "press"}
        forced_event_ids = {event_id for event_id, control in forced_controls.items() if control == "detonate"}

        def _eligible_items(*, conversion_pass: bool) -> list[tuple[int, int, LatentEvent]]:
            eligible_items: list[tuple[int, int, LatentEvent]] = []
            off_window_margin = 1 if conversion_pass and key_segment else 2
            conversion_margin = 0 if conversion_pass and key_segment else 1
            for event in events:
                if event.event_id in pressed_event_ids:
                    continue
                if (
                    suppress_cost_return_primary_driver
                    and event.stake_family.startswith("cost_return:")
                    and event.event_id not in forced_controls
                ):
                    continue
                effective_threshold = max(1, event.trigger_threshold - LatentEventEngine._preference_threshold_bonus(plan=plan, event=event))
                in_window = segment.segment_role in set(event.trigger_window_roles) or intent.scene_frame in set(event.trigger_window_frames)
                if (
                    not in_window
                    and event.pressure + event.maturity < effective_threshold + off_window_margin
                    and event.event_id not in forced_controls
                ):
                    continue
                if (
                    event.maturity < effective_threshold
                    and event.pressure + event.maturity < effective_threshold + conversion_margin
                    and event.event_id not in forced_controls
                ):
                    continue
                if conversion_pass:
                    if event.status != "primed" and event.pressure + event.maturity < max(4, effective_threshold + 1):
                        continue
                    if event.maturity < max(1, effective_threshold - 1) and event.pressure + event.maturity < effective_threshold + 1:
                        continue
                score = (
                    event.maturity * 2
                    + event.pressure
                    + event.age_turns
                    + LatentEventEngine._scene_bonus(event=event, intent=intent)
                    + LatentEventEngine._shell_bonus(plan=plan, event=event)
                    + LatentEventEngine._preference_trigger_bonus(plan=plan, event=event)
                    + LatentEventEngine._segment_trigger_bonus(segment=segment)
                )
                shell_tie_bias = LatentEventEngine._shell_tie_bias(plan=plan, event=event)
                eligible_items.append((score, shell_tie_bias, event))
            if forced_event_ids:
                forced_eligible = [item for item in eligible_items if item[2].event_id in forced_event_ids]
                if forced_eligible:
                    return forced_eligible
            return eligible_items

        def _pick_winner(eligible_items: list[tuple[int, int, LatentEvent]]) -> LatentEvent:
            return max(
                eligible_items,
                key=lambda item: (
                    1 if (prefer_cost_return_primary_driver and item[2].stake_family.startswith("cost_return:")) else 0,
                    item[0],
                    item[1],
                    LatentEventEngine._kind_priority(item[2].kind, intent.scene_frame),
                    item[2].age_turns,
                    item[2].event_id,
                ),
            )[2]

        eligible = _eligible_items(conversion_pass=False)
        key_segment_conversion = False
        if not eligible and key_segment:
            eligible = _eligible_items(conversion_pass=True)
            key_segment_conversion = bool(eligible)
        if not eligible:
            return None, events, False
        winner = _pick_winner(eligible)
        winner.status = "triggered"
        retained = [event for event in events if event.event_id != winner.event_id]
        return winner, retained, key_segment_conversion

    @staticmethod
    def _segment_trigger_bonus(*, segment: CompiledSegment) -> int:
        return 1 if segment.segment_role in {"reveal", "terminal"} else 0

    @staticmethod
    def _shell_tie_bias(*, plan: CompiledPlayPlan, event: LatentEvent) -> int:
        if plan.story_shell_id == "entertainment_scandal" and event.kind in {"public_wave", "npc_action", "secret_pressure"}:
            return 1
        if plan.story_shell_id == "campus_romance" and event.kind in {"relationship_debt", "public_wave", "npc_action"}:
            return 1
        return 0

    @staticmethod
    def render_foreshadows(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        events: list[LatentEvent],
    ) -> tuple[list[str], list[str]]:
        del segment, intent
        ordered = sorted(
            [event for event in events if event.status != "cooled" and event.pressure + event.maturity >= 4],
            key=lambda item: (item.pressure + item.maturity, item.age_turns, item.event_id),
            reverse=True,
        )
        lines = [trim_text(event.foreshadow_text, 220) for event in ordered[:2]]
        tags = [f"latent:{event.kind}:foreshadowed" for event in ordered[:2]]
        return lines, tags

    @staticmethod
    def _cap_events(*, plan: CompiledPlayPlan, state: UrbanWorldState, events: list[LatentEvent]) -> list[LatentEvent]:
        ordered = sorted(events, key=lambda item: (item.kind, -(item.pressure + item.maturity), -item.age_turns, item.event_id))
        kept: list[LatentEvent] = []
        by_kind: dict[LatentEventKind, list[LatentEvent]] = {}
        for event in ordered:
            bucket = by_kind.setdefault(event.kind, [])
            if len(bucket) < 2:
                bucket.append(event)
                kept.append(event)
                continue
            primary = max(bucket, key=lambda item: (item.pressure + item.maturity, item.age_turns, item.event_id))
            primary.pressure = _clamp(primary.pressure + max(1, event.pressure // 2), 0, 6)
            primary.maturity = _clamp(max(primary.maturity, event.maturity), 0, 6)
            primary.age_turns = _clamp(max(primary.age_turns, event.age_turns), 0, 12)
            LatentEventEngine._refresh_event(plan=plan, state=state, event=primary)
        kept = sorted(kept, key=lambda item: (item.pressure + item.maturity, item.age_turns, item.event_id), reverse=True)
        if len(kept) <= 6:
            return kept
        overflow = kept[6:]
        kept = kept[:6]
        strongest_by_kind = {event.kind: event for event in kept}
        for event in overflow:
            primary = strongest_by_kind.get(event.kind)
            if primary is None:
                continue
            primary.pressure = _clamp(primary.pressure + max(1, event.pressure // 2), 0, 6)
            primary.maturity = _clamp(max(primary.maturity, event.maturity), 0, 6)
            LatentEventEngine._refresh_event(plan=plan, state=state, event=primary)
        return kept[:6]

    @staticmethod
    def _record_from_event(event: LatentEvent, control: LatentEventControl) -> TurnEscalationRecord:
        return TurnEscalationRecord(
            source="latent_event",
            event_id=event.event_id,
            kind=event.kind,
            control=control,
            family=LatentEventEngine._event_family(event),
            actor_character_id=event.actor_character_id,
            target_character_ids=list(event.target_character_ids),
            stake_character_ids=list(event.stake_character_ids),
            text=event.detonation_text,
            global_deltas=dict(event.global_deltas),
            relationship_deltas={key: dict(value) for key, value in event.relationship_deltas.items()},
            revealed_secret_ids=[],
        )

    @staticmethod
    def _top_event(events: list[LatentEvent]) -> LatentEvent | None:
        active = [event for event in events if event.status != "cooled"]
        if not active:
            return None
        return max(
            active,
            key=lambda event: (
                event.pressure + event.maturity,
                event.age_turns,
                int(event.status == "primed"),
                event.event_id,
            ),
        )

    @staticmethod
    def _refresh_event(*, plan: CompiledPlayPlan, state: UrbanWorldState, event: LatentEvent) -> LatentEvent:
        target_name = LatentEventEngine._name(plan, event.target_character_ids[0] if event.target_character_ids else None)
        stake_name = LatentEventEngine._name(plan, event.stake_character_ids[0] if event.stake_character_ids else None)
        actor_name = LatentEventEngine._name(plan, event.actor_character_id)
        event.foreshadow_text = trim_text(LatentEventEngine._foreshadow_text(plan=plan, event=event, target_name=target_name, stake_name=stake_name, actor_name=actor_name), 220)
        event.detonation_text = trim_text(LatentEventEngine._detonation_text(plan=plan, event=event, target_name=target_name, stake_name=stake_name, actor_name=actor_name), 220)
        event.global_deltas = LatentEventEngine._global_deltas(plan=plan, event=event, state=state)
        event.relationship_deltas = LatentEventEngine._relationship_deltas(event=event, plan=plan)
        event.reaction_cause_tags = LatentEventEngine._reaction_tags(plan=plan, event=event)
        return event

    @staticmethod
    def _recompute_pressure_bars(state: UrbanWorldState) -> None:
        def _score(kind: LatentEventKind) -> int:
            total = sum(event.pressure + event.maturity for event in state.latent_events if event.kind == kind and event.status != "cooled")
            return _clamp((total + 1) // 2, 0, 6)

        state.relationship_debt_pressure = _score("relationship_debt")
        state.public_wave_pressure = _score("public_wave")
        state.secret_pressure = _score("secret_pressure")
        state.npc_action_pressure = _score("npc_action")

    @staticmethod
    def _build_latent_radar(
        *,
        state: UrbanWorldState,
        triggered: LatentEvent | None,
        op_tags: list[str],
    ) -> list[UrbanLatentRadarItem]:
        kind_to_pressure = {
            "relationship_debt": state.relationship_debt_pressure,
            "public_wave": state.public_wave_pressure,
            "secret_pressure": state.secret_pressure,
            "npc_action": state.npc_action_pressure,
        }

        def _trend_for(kind: LatentEventKind) -> LatentRadarTrend:
            if triggered is not None and triggered.kind == kind:
                return "triggered"
            if f"latent:{kind}:press" in set(op_tags):
                return "cooling"
            if any(tag in set(op_tags) for tag in (f"latent:{kind}:redirect", f"latent:{kind}:detonate")):
                return "rising"
            return "rising" if kind_to_pressure[kind] >= 4 else "steady"

        def _note_for(kind: LatentEventKind, trend: LatentRadarTrend) -> str:
            label = LatentEventEngine._kind_label(kind)
            if trend == "triggered":
                return f"{label}本回合已引爆。"
            if trend == "cooling":
                return f"{label}暂时被压住，但没有消失。"
            if trend == "rising":
                return f"{label}正在变重，继续拖延会更危险。"
            return f"{label}目前维持在可控区间。"

        output: list[UrbanLatentRadarItem] = []
        for kind in ("relationship_debt", "public_wave", "secret_pressure", "npc_action"):
            trend = _trend_for(kind)
            output.append(
                UrbanLatentRadarItem(
                    kind=kind,  # type: ignore[arg-type]
                    pressure=kind_to_pressure[kind],  # type: ignore[arg-type]
                    trend=trend,
                    note=_note_for(kind, trend),  # type: ignore[arg-type]
                )
            )
        return output

    @staticmethod
    def _stake_character_ids(segment: CompiledSegment, state: UrbanWorldState, target_id: str | None, actor_id: str | None) -> list[str]:
        blocked = {item for item in [target_id, actor_id] if item}
        return [
            character_id
            for character_id in unique_preserve(list(segment.rival_target_ids) + list(segment.focus_target_ids) + list(state.active_character_ids))
            if character_id not in blocked
        ][:3]

    @staticmethod
    def _npc_action_actor(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
    ) -> str | None:
        candidates: list[tuple[int, str, NpcMindState]] = []
        for character_id in state.active_character_ids:
            if character_id == intent.target_id:
                continue
            mind = state.npc_mind_states.get(character_id)
            member = next((item for item in plan.cast if item.character_id == character_id), None)
            if mind is None or member is None:
                continue
            intent_frame = member.strategic_intent
            score = max(mind.control_need, mind.betrayal_readiness, mind.confession_readiness, mind.jealousy, mind.protectiveness)
            if intent_frame.public_survival_mode in {"claim_narrative", "cut_off"} and intent.scene_frame != "private":
                score += 2
            if intent.target_id in set(intent_frame.opportunism_target_ids):
                score += 2
            if intent.target_id in set(intent_frame.sacrifice_target_ids):
                score += 2
            if segment.segment_role in {"reveal", "terminal"}:
                score += 1
            if score >= 4:
                candidates.append((score, character_id, mind))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[1]

    @staticmethod
    def _event_family(event: LatentEvent) -> str:
        if event.kind == "relationship_debt":
            return "旧账回咬"
        if event.kind == "public_wave":
            return "场外风向回咬"
        if event.kind == "secret_pressure":
            return "秘密自己顶开口子"
        return "关键人物先手动作"

    @staticmethod
    def _stake_family(
        *,
        kind: LatentEventKind,
        plan: CompiledPlayPlan,
        target_id: str | None,
        actor_id: str | None,
    ) -> str:
        if kind == "relationship_debt":
            return "alignment_debt"
        if kind == "public_wave":
            return "public_narrative"
        if kind == "secret_pressure":
            return "secret_containment"
        actor = next((member for member in plan.cast if member.character_id == actor_id), None)
        target = next((member for member in plan.cast if member.character_id == target_id), None)
        if actor is not None:
            return f"npc_action:{actor.strategic_intent.primary_stake}"
        if target is not None:
            return f"npc_action:{target.strategic_intent.primary_stake}"
        return "npc_action:general"

    @staticmethod
    def _trigger_window_roles(kind: LatentEventKind) -> list[str]:
        if kind == "relationship_debt":
            return ["pressure", "reveal", "terminal"]
        if kind == "public_wave":
            return ["pressure", "reveal", "terminal"]
        if kind == "secret_pressure":
            return ["misread", "pressure", "reveal", "terminal"]
        return ["pressure", "reveal", "terminal"]

    @staticmethod
    def _trigger_window_frames(kind: LatentEventKind) -> list[str]:
        if kind in {"public_wave", "npc_action"}:
            return ["semi_public", "public"]
        if kind == "relationship_debt":
            return ["private", "semi_public", "public"]
        return ["private", "semi_public", "public"]

    @staticmethod
    def _scene_bonus(*, event: LatentEvent, intent: UrbanTurnIntent) -> int:
        return 2 if intent.scene_frame in set(event.trigger_window_frames) else 0

    @staticmethod
    def _shell_bonus(*, plan: CompiledPlayPlan, event: LatentEvent) -> int:
        if plan.story_shell_id == "entertainment_scandal" and event.kind in {"public_wave", "npc_action", "secret_pressure"}:
            return 1
        if plan.story_shell_id == "campus_romance" and event.kind in {"relationship_debt", "public_wave", "npc_action"}:
            return 1
        return 0

    @staticmethod
    def _kind_priority(kind: LatentEventKind, scene_frame: str) -> int:
        if scene_frame in {"public", "semi_public"}:
            order = {"public_wave": 4, "npc_action": 3, "secret_pressure": 2, "relationship_debt": 1}
        else:
            order = {"relationship_debt": 4, "secret_pressure": 3, "npc_action": 2, "public_wave": 1}
        return order[kind]

    @staticmethod
    def _event_members(plan: CompiledPlayPlan, event: LatentEvent) -> list:
        ids = set(
            unique_preserve(
                [
                    item
                    for item in [event.actor_character_id, *event.stake_character_ids, *event.target_character_ids]
                    if item
                ]
            )
        )
        return [member for member in plan.cast if member.character_id in ids]

    @staticmethod
    def _delay_preference_bonus(*, plan: CompiledPlayPlan, event: LatentEvent) -> int:
        if event.age_turns < 2:
            return 0
        bonus = 0
        if any(member.strategic_intent.delay_preference == "patient_burn" for member in LatentEventEngine._event_members(plan, event)):
            bonus += 1
        if any(member.strategic_intent.preferred_latent_kind == event.kind for member in LatentEventEngine._event_members(plan, event)):
            bonus += 1
        return min(bonus, 2)

    @staticmethod
    def _sensitivity_pressure_bonus(*, plan: CompiledPlayPlan, event: LatentEvent) -> int:
        if event.age_turns < 2:
            return 0
        target_members = [member for member in plan.cast if member.character_id in set(event.target_character_ids)]
        return 1 if any(member.strategic_intent.sensitive_latent_kind == event.kind for member in target_members) else 0

    @staticmethod
    def _pressure_resists_press(*, plan: CompiledPlayPlan, event: LatentEvent) -> bool:
        members = LatentEventEngine._event_members(plan, event)
        return (
            any(member.strategic_intent.delay_preference == "patient_burn" for member in members)
            and any(member.strategic_intent.sensitive_latent_kind == event.kind for member in members)
        )

    @staticmethod
    def _preference_threshold_bonus(*, plan: CompiledPlayPlan, event: LatentEvent) -> int:
        if event.age_turns < 2 and event.status != "primed":
            return 0
        bonus = 0
        target_members = [member for member in plan.cast if member.character_id in set(event.target_character_ids)]
        if any(member.strategic_intent.sensitive_latent_kind == event.kind for member in target_members):
            bonus += 1
        actor = next((member for member in plan.cast if member.character_id == event.actor_character_id), None)
        if actor is not None and actor.strategic_intent.preferred_latent_kind == event.kind and actor.strategic_intent.delay_preference == "patient_burn":
            bonus += 1
        return min(bonus, 2)

    @staticmethod
    def _preference_trigger_bonus(*, plan: CompiledPlayPlan, event: LatentEvent) -> int:
        if event.age_turns < 2 and event.status != "primed":
            return 0
        bonus = 0
        members = LatentEventEngine._event_members(plan, event)
        if any(member.strategic_intent.preferred_latent_kind == event.kind for member in members):
            bonus += 1
        if any(member.strategic_intent.delay_preference == "patient_burn" for member in members):
            bonus += 1
        return min(bonus, 2)

    @staticmethod
    def _stake_label(primary_stake: str) -> str:
        return {
            "position": "位置",
            "reputation": "名声",
            "eligibility": "名额",
            "lineage": "顺位",
            "relationship": "关系",
            "narrative_control": "版本",
            "normal_life": "正常生活",
        }.get(primary_stake, "退路")

    @staticmethod
    def _preferred_regression_payoff(*, plan: CompiledPlayPlan, event: LatentEvent) -> str:
        target = next((member for member in plan.cast if member.character_id in set(event.target_character_ids)), None)
        actor = next((member for member in plan.cast if member.character_id == event.actor_character_id), None)
        chosen = target or actor
        if chosen is None:
            return "public_shame"
        return chosen.strategic_intent.regression_payoff

    @staticmethod
    def _preference_coda(*, plan: CompiledPlayPlan, event: LatentEvent) -> str | None:
        target = next((member for member in plan.cast if member.character_id in set(event.target_character_ids)), None)
        if target is None:
            return None
        payoff = target.strategic_intent.regression_payoff
        if payoff == "status_loss":
            return f"这一口回咬得最狠的，正是{target.display_name}最不敢掉的{LatentEventEngine._stake_label(target.strategic_intent.primary_stake)}。"
        if payoff == "public_shame":
            return f"这一下不是普通翻车，咬中的就是{target.display_name}最怕被当众看穿的那层脸面。"
        if payoff == "secret_leak":
            return f"这一下最伤的不是吵起来，而是{target.display_name}最想控住的那层秘密和版本一起漏了。"
        if payoff == "social_isolation":
            return f"这口后果最狠的地方，是把{target.display_name}最想保住的关系当场往外推了一截。"
        return None

    @staticmethod
    def _name(plan: CompiledPlayPlan, character_id: str | None) -> str:
        return next((member.display_name for member in plan.cast if member.character_id == character_id), "对方")

    @staticmethod
    def _foreshadow_text(*, plan: CompiledPlayPlan, event: LatentEvent, target_name: str, stake_name: str, actor_name: str) -> str:
        if event.stake_family.startswith("callback:"):
            return f"你之前留下的后账已经接近到期窗口，{target_name}这边随时会把那笔账翻出来。"
        patient_coda = ""
        if any(member.strategic_intent.delay_preference == "patient_burn" for member in LatentEventEngine._event_members(plan, event)):
            patient_coda = "它拖得越久，越像是专门朝最疼的那一处长。"
        if event.kind == "relationship_debt":
            if plan.story_shell_id == "campus_romance":
                return f"台下和熟人圈已经把你和{target_name}刚才那一下记成一笔旧账，只是还没挑最疼的时候翻出来。{patient_coda}"
            if plan.story_shell_id == "entertainment_scandal":
                return f"旁边已经有人把你和{target_name}刚才那一下记成后面好切的版本，这笔账不会停在现场。{patient_coda}"
            return f"{stake_name}已经把你和{target_name}这一下记成旧账并开始记账了，暂时没发作，不代表这件事就过去了。{patient_coda}"
        if event.kind == "public_wave":
            edge = pick_shell_edge(
                shell_id=plan.story_shell_id,
                latent_kind=event.kind,
                turn_index=event.source_turn_index + max(event.age_turns, 0),
                segment_role="pressure",
                graph_policy=plan.semantic_strategy_pack.shell_propagation_graph,
                priority_policy=plan.semantic_strategy_pack.propagation_priority_policy,
            )
            if edge is not None:
                return f"{edge.from_node}到{edge.to_node}这条传播链还在自己发酵，{edge.anchor_token}那边只会继续把后果放大。{patient_coda}"
            if plan.story_shell_id == "campus_romance":
                return f"台下和熟人圈还在继续发酵，这事不是过去了，只是还没轮到最难看的那一拍。{patient_coda}"
            if plan.story_shell_id == "entertainment_scandal":
                return f"镜头、手机和外面风向还在继续发酵，这事不是压住了，只是还没歪到最难看的版本。{patient_coda}"
            return f"场外的风向还在自己发酵，这件事只是还没找到最疼的出口。{patient_coda}"
        if event.kind == "secret_pressure":
            return f"最不该见光的那层东西还在往外顶，关于{target_name}的真相只是还没自己拱开口子。{patient_coda}"
        return f"{actor_name}现在没抢话，不代表她真咽下去了，那股想先保自己再动手的劲还在攒。{patient_coda}"

    @staticmethod
    def _detonation_text(*, plan: CompiledPlayPlan, event: LatentEvent, target_name: str, stake_name: str, actor_name: str) -> str:
        if event.stake_family.startswith("callback:"):
            return f"你之前压着的那笔后账到期了，{target_name}这边直接把旧账翻上台面，后果当场落地。"
        if event.kind == "relationship_debt":
            if plan.story_shell_id == "campus_romance":
                text = f"你和{target_name}之前那一下被台下和熟人圈直接翻成旧账，评审和站队一起开始变冷。"
                coda = LatentEventEngine._preference_coda(plan=plan, event=event)
                return f"{text}{coda or ''}"
            if plan.story_shell_id == "entertainment_scandal":
                text = f"你和{target_name}之前留下的那笔站边旧账现在被外面认成公开版本，切割先从这边开刀。"
                coda = LatentEventEngine._preference_coda(plan=plan, event=event)
                return f"{text}{coda or ''}"
            text = f"你和{target_name}之前压下去的那笔账现在回头咬人，{stake_name}不再愿意继续装没看见。"
            coda = LatentEventEngine._preference_coda(plan=plan, event=event)
            return f"{text}{coda or ''}"
        if event.kind == "public_wave":
            edge = pick_shell_edge(
                shell_id=plan.story_shell_id,
                latent_kind=event.kind,
                turn_index=event.source_turn_index + max(event.age_turns, 0),
                segment_role="reveal",
                graph_policy=plan.semantic_strategy_pack.shell_propagation_graph,
                priority_policy=plan.semantic_strategy_pack.propagation_priority_policy,
            )
            if edge is not None:
                text = f"{edge.from_node}到{edge.to_node}的传播链在本回合直接炸开，{edge.anchor_token}把这一下钉成了公开后果。"
                coda = LatentEventEngine._preference_coda(plan=plan, event=event)
                return f"{text}{coda or ''}"
            if plan.story_shell_id == "campus_romance":
                text = "台下、熟人圈和评审席一起把这一下认成了公开事故，后面的话语权已经开始歪。"
                coda = LatentEventEngine._preference_coda(plan=plan, event=event)
                return f"{text}{coda or ''}"
            if plan.story_shell_id == "entertainment_scandal":
                text = "热搜、镜头和公关切割一起接住了这一下，场外已经把它认成了你们谁都收不回去的公开事故。"
                coda = LatentEventEngine._preference_coda(plan=plan, event=event)
                return f"{text}{coda or ''}"
            text = "场外风向自己炸开了，后面每一句都不再只是在对人说。"
            coda = LatentEventEngine._preference_coda(plan=plan, event=event)
            return f"{text}{coda or ''}"
        if event.kind == "secret_pressure":
            if plan.story_shell_id == "campus_romance":
                text = f"关于{target_name}最不该见光的那层东西自己顶开口子了，台下和评审席一下都冷了。"
                coda = LatentEventEngine._preference_coda(plan=plan, event=event)
                return f"{text}{coda or ''}"
            if plan.story_shell_id == "entertainment_scandal":
                text = f"关于{target_name}那层本来还想压住的东西自己炸开，镜头和外面版本一起咬了上来。"
                coda = LatentEventEngine._preference_coda(plan=plan, event=event)
                return f"{text}{coda or ''}"
            text = f"关于{target_name}那层最不该见光的东西自己拱开了口子，谁再想装没事都来不及。"
            coda = LatentEventEngine._preference_coda(plan=plan, event=event)
            return f"{text}{coda or ''}"
        mode = LatentEventEngine._actor_mode(plan=plan, event=event)
        if mode == "claim_narrative":
            text = f"{actor_name}抢在所有人前头把版本往自己那边拽，等于逼所有人现在就认她的说法。"
            coda = LatentEventEngine._preference_coda(plan=plan, event=event)
            return f"{text}{coda or ''}"
        if mode == "cut_off":
            text = f"{actor_name}当场把切割动作摆出来了，等于直接把{target_name}往更难看的位置推。"
            coda = LatentEventEngine._preference_coda(plan=plan, event=event)
            return f"{text}{coda or ''}"
        if mode == "align_early":
            text = f"{actor_name}先一步把边站死了，把原本还能含糊过去的退路一口气封掉。"
            coda = LatentEventEngine._preference_coda(plan=plan, event=event)
            return f"{text}{coda or ''}"
        text = f"{actor_name}先护自己，再把局势往外推了一把，场面立刻不再只按你的节奏走。"
        coda = LatentEventEngine._preference_coda(plan=plan, event=event)
        return f"{text}{coda or ''}"

    @staticmethod
    def _global_deltas(*, plan: CompiledPlayPlan, event: LatentEvent, state: UrbanWorldState) -> dict[str, int]:
        del state
        if event.kind == "relationship_debt":
            deltas = {"scene_heat": 1, "route_lock": 1}
            if plan.story_shell_id in {"campus_romance", "entertainment_scandal"}:
                deltas["public_image"] = -1
            return deltas
        if event.kind == "public_wave":
            deltas = {"scene_heat": 1, "public_image": -1}
            if plan.story_shell_id == "entertainment_scandal":
                deltas["secret_exposure"] = 1
            elif plan.story_shell_id == "campus_romance":
                deltas["route_lock"] = 1
            return deltas
        if event.kind == "secret_pressure":
            deltas = {"scene_heat": 1, "secret_exposure": 1}
            if plan.story_shell_id != "office_power":
                deltas["public_image"] = -1
            return deltas
        mode = LatentEventEngine._actor_mode(plan=plan, event=event)
        deltas = {"scene_heat": 1}
        if mode in {"self_preserve", "cut_off"}:
            deltas["public_image"] = -1
        if mode in {"align_early", "hold_face"}:
            deltas["route_lock"] = 1
        if mode == "claim_narrative":
            deltas["secret_exposure"] = 1
        payoff = LatentEventEngine._preferred_regression_payoff(plan=plan, event=event)
        if payoff == "public_shame":
            deltas["public_image"] = deltas.get("public_image", 0) - 1
        elif payoff == "status_loss":
            deltas["route_lock"] = deltas.get("route_lock", 0) + 1
        elif payoff == "secret_leak":
            deltas["secret_exposure"] = deltas.get("secret_exposure", 0) + 1
        return deltas

    @staticmethod
    def _relationship_deltas(*, event: LatentEvent, plan: CompiledPlayPlan | None = None) -> dict[str, dict[str, int]]:
        deltas: dict[str, dict[str, int]] = {}
        if event.kind == "relationship_debt":
            for character_id in event.stake_character_ids[:2]:
                deltas[character_id] = {"suspicion": 1, "tension": 1}
        elif event.kind == "public_wave":
            for character_id in event.stake_character_ids[:1]:
                deltas[character_id] = {"suspicion": 1}
        elif event.kind == "secret_pressure":
            for character_id in event.target_character_ids[:1]:
                deltas[character_id] = {"tension": 1, "suspicion": 1}
        else:
            if event.actor_character_id:
                deltas[event.actor_character_id] = {"trust": -1, "tension": 1}
            for character_id in event.stake_character_ids[:1]:
                payload = deltas.setdefault(character_id, {})
                payload["suspicion"] = payload.get("suspicion", 0) + 1
        if plan is not None and LatentEventEngine._preferred_regression_payoff(plan=plan, event=event) == "social_isolation":
            for character_id in unique_preserve([*event.target_character_ids[:1], *event.stake_character_ids[:1]]):
                payload = deltas.setdefault(character_id, {})
                payload["trust"] = payload.get("trust", 0) - 1
                payload["tension"] = payload.get("tension", 0) + 1
        return deltas

    @staticmethod
    def _reaction_tags(*, plan: CompiledPlayPlan, event: LatentEvent) -> list[str]:
        if event.kind == "relationship_debt":
            return ["kept_score", "owes_debt"]
        if event.kind == "public_wave":
            if plan.story_shell_id == "entertainment_scandal":
                return ["camera_pressure"]
            if plan.story_shell_id == "campus_romance":
                return ["campus_spread"]
            return ["crowd_pressure"]
        if event.kind == "secret_pressure":
            return ["public_hit", "at_center_of_event"]
        mode = LatentEventEngine._actor_mode(plan=plan, event=event)
        if mode == "cut_off":
            return ["cutting_others", "interrupt_touched"]
        if mode == "claim_narrative":
            return ["covering_self", "interrupt_touched"]
        if mode == "align_early":
            return ["forced_alignment", "interrupt_touched"]
        return ["covering_self", "forced_alignment"]

    @staticmethod
    def _actor_mode(*, plan: CompiledPlayPlan, event: LatentEvent) -> str:
        actor = next((member for member in plan.cast if member.character_id == event.actor_character_id), None)
        if actor is None:
            return "self_preserve"
        return actor.strategic_intent.public_survival_mode

    @staticmethod
    def _op_feedback(
        *,
        plan: CompiledPlayPlan,
        event: LatentEvent,
        control: LatentEventControl,
        intent: UrbanTurnIntent,
    ) -> str:
        target_name = LatentEventEngine._name(plan, intent.target_id)
        if control == "press":
            if event.kind == "relationship_debt":
                return f"你暂时把和{target_name}有关的那笔旧账往后压了一拍，但场上记账的人并没有忘。"
            if event.kind == "public_wave":
                return "你暂时把场外风向压住了一拍，但这只是在往后拖，不是在真的消失。"
            return "你暂时把最危险的那层东西按住了，可它还在底下继续发酵。"
        if control == "redirect":
            return f"你把这口后果往{target_name}那边推了一点，眼下轻了，可后面谁先被咬会变得更狠。"
        return "你没有继续等它自己熟，而是主动挑现在把这颗雷拆开。"
