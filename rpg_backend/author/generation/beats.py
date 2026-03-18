from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rpg_backend.author.compiler.routes import normalize_affordance_tag
from rpg_backend.author.compiler.router import plan_story_theme
from rpg_backend.author.generation.context import build_author_context_from_story
from rpg_backend.author.normalize import coerce_int, trim_text, unique_preserve
from rpg_backend.author.contracts import (
    BeatDraftSpec,
    BeatPlanDraft,
    BeatPlanSkeletonDraft,
    BeatSkeletonSpec,
    CastDraft,
    FocusedBrief,
    StoryFrameDraft,
)

if TYPE_CHECKING:
    from rpg_backend.author.gateway import AuthorLLMGateway


def _beat_plan_semantics_output_tokens(gateway: "AuthorLLMGateway") -> int:
    budget = gateway.max_output_tokens_beat_plan
    if budget is None:
        return 1800
    return max(int(budget), 1800)


def _invoke_json_with_prompt_retries(
    gateway: "AuthorLLMGateway",
    *,
    payload: dict[str, Any],
    prompts: tuple[str, ...],
    previous_response_id: str | None,
    max_output_tokens: int,
    parse_fn,
):
    from rpg_backend.author.gateway import AuthorGatewayError, GatewayStructuredResponse

    retryable_codes = {"llm_invalid_json", "llm_schema_invalid"}
    attempt_prev = previous_response_id
    last_error: Exception | None = None
    for index, prompt in enumerate(prompts):
        try:
            raw = gateway._invoke_json(
                system_prompt=prompt,
                user_payload=payload,
                max_output_tokens=max_output_tokens,
                previous_response_id=attempt_prev,
                operation_name="beat_plan_generate",
            )
        except AuthorGatewayError as exc:
            last_error = exc
            if exc.code not in retryable_codes or index == len(prompts) - 1:
                raise
            continue
        try:
            value = parse_fn(raw.payload)
        except Exception as exc:  # noqa: BLE001
            last_error = AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            )
            attempt_prev = raw.response_id or attempt_prev
            if index == len(prompts) - 1:
                raise last_error from exc
            continue
        return GatewayStructuredResponse(
            value=value,
            response_id=raw.response_id or attempt_prev,
        )
    if isinstance(last_error, AuthorGatewayError):
        raise last_error
    raise AuthorGatewayError(
        code="llm_schema_invalid",
        message=str(last_error or "beat plan generation failed"),
        status_code=502,
    )


def _target_beat_count(
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
) -> int:
    lowered = " ".join([story_frame.title, story_frame.premise, story_frame.stakes, *story_frame.world_rules]).casefold()
    if len(story_frame.state_axis_choices) >= 3 and len(cast_draft.cast) >= 3 and len(story_frame.truths) >= 2:
        return 3
    if any(keyword in lowered for keyword in ("blackout", "succession", "election", "harbor", "port", "trade", "quarantine", "archive", "ledger", "record")):
        return 3
    return 2


def _beat_theme_guidance(primary_theme: str) -> str:
    mapping = {
        "legitimacy_crisis": "Emphasize coalition legitimacy, public mandate, procedural pressure, and visible settlement stakes.",
        "logistics_quarantine_crisis": "Emphasize chokepoints, quarantine pressure, inspections, scarcity, and operational leverage.",
        "truth_record_crisis": "Emphasize records, testimony, evidence control, procedural proof, and public truth.",
        "public_order_crisis": "Emphasize panic control, emergency authority, and visible order under pressure.",
        "generic_civic_crisis": "Emphasize civic pressure, institutional conflict, and public consequence.",
    }
    return mapping.get(primary_theme, mapping["generic_civic_crisis"])


def _default_beat_blueprints(
    gateway: "AuthorLLMGateway",
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
) -> list[dict[str, Any]]:
    cast_names = [item.name for item in cast_draft.cast]
    truth_texts = [item.text for item in story_frame.truths]
    axis_ids = [item.template_id for item in story_frame.state_axis_choices]
    first_axis = axis_ids[0] if axis_ids else None
    second_axis = axis_ids[1] if len(axis_ids) > 1 else first_axis
    third_axis = axis_ids[2] if len(axis_ids) > 2 else second_axis or first_axis
    opening_pair = cast_names[:2] or ["The Mediator", "Civic Authority"]
    alliance_pair = cast_names[1:3] if len(cast_names) >= 3 else cast_names[:2] or ["Civic Authority", "Opposition Broker"]
    settlement_pair = [cast_names[0], cast_names[2]] if len(cast_names) >= 3 else alliance_pair[:2]
    lowered = " ".join([story_frame.title, story_frame.premise, story_frame.stakes, *story_frame.world_rules]).casefold()
    if "blackout" in lowered and any(keyword in lowered for keyword in ("succession", "election", "heir", "crown")):
        return [
            {
                "title_seed": "The First Nightfall",
                "goal_seed": "Stabilize emergency coordination long enough to learn who benefits from the blackout.",
                "focus_names": opening_pair[:3],
                "conflict_pair": opening_pair[:2],
                "pressure_axis_id": first_axis,
                "milestone_kind": "reveal",
                "route_pivot_tag": "reveal_truth",
                "required_truth_texts": [truth_texts[0] if truth_texts else story_frame.premise],
                "detour_budget": 1,
                "progress_required": 2,
                "affordance_tags": ["reveal_truth", "contain_chaos", "build_trust"],
                "blocked_affordances": [],
            },
            {
                "title_seed": "The Public Ledger",
                "goal_seed": "Turn improvised relief into a civic process rival factions cannot dismiss as a power grab.",
                "focus_names": alliance_pair[:3],
                "conflict_pair": alliance_pair[:2],
                "pressure_axis_id": second_axis,
                "milestone_kind": "containment",
                "route_pivot_tag": "build_trust",
                "required_truth_texts": [truth_texts[1] if len(truth_texts) > 1 else truth_texts[0] if truth_texts else story_frame.stakes],
                "detour_budget": 1,
                "progress_required": 2,
                "affordance_tags": ["build_trust", "contain_chaos", "secure_resources"],
                "blocked_affordances": [],
            },
            {
                "title_seed": "The Dawn Bargain",
                "goal_seed": "Force a visible settlement before the succession vacuum hardens into a new political order.",
                "focus_names": settlement_pair[:3],
                "conflict_pair": settlement_pair[:2],
                "pressure_axis_id": third_axis,
                "milestone_kind": "commitment",
                "route_pivot_tag": "shift_public_narrative",
                "required_truth_texts": [truth_texts[-1] if truth_texts else story_frame.stakes],
                "detour_budget": 0,
                "progress_required": 3,
                "affordance_tags": ["shift_public_narrative", "build_trust", "pay_cost"],
                "blocked_affordances": [],
            },
        ]
    if any(keyword in lowered for keyword in ("harbor", "port", "trade", "quarantine")):
        return [
            {
                "title_seed": "The Quarantine Line",
                "goal_seed": "Stabilize the harbor perimeter before panic turns quarantine into factional seizure.",
                "focus_names": opening_pair[:3],
                "conflict_pair": opening_pair[:2],
                "pressure_axis_id": first_axis,
                "milestone_kind": "reveal",
                "route_pivot_tag": "contain_chaos",
                "required_truth_texts": [truth_texts[0] if truth_texts else story_frame.premise],
                "detour_budget": 1,
                "progress_required": 2,
                "affordance_tags": ["contain_chaos", "secure_resources", "reveal_truth"],
                "blocked_affordances": [],
            },
            {
                "title_seed": "The Dockside Audit",
                "goal_seed": "Expose which faction profits from scarcity before emergency trade powers become permanent leverage.",
                "focus_names": alliance_pair[:3],
                "conflict_pair": alliance_pair[:2],
                "pressure_axis_id": second_axis,
                "milestone_kind": "fracture",
                "route_pivot_tag": "reveal_truth",
                "required_truth_texts": [truth_texts[1] if len(truth_texts) > 1 else truth_texts[0] if truth_texts else story_frame.stakes],
                "detour_budget": 1,
                "progress_required": 2,
                "affordance_tags": ["reveal_truth", "shift_public_narrative", "build_trust"],
                "blocked_affordances": [],
            },
            {
                "title_seed": "The Harbor Compact",
                "goal_seed": "Lock the city into a recovery bargain before private leverage replaces public authority.",
                "focus_names": settlement_pair[:3],
                "conflict_pair": settlement_pair[:2],
                "pressure_axis_id": third_axis,
                "milestone_kind": "commitment",
                "route_pivot_tag": "build_trust",
                "required_truth_texts": [truth_texts[-1] if truth_texts else story_frame.stakes],
                "detour_budget": 0,
                "progress_required": 3,
                "affordance_tags": ["build_trust", "secure_resources", "pay_cost"],
                "blocked_affordances": [],
            },
        ]
    if any(keyword in lowered for keyword in ("archive", "ledger", "record", "witness")):
        return [
            {
                "title_seed": "The Missing Ledger",
                "goal_seed": "Trace which civic record was altered before procedure itself becomes the weapon.",
                "focus_names": opening_pair[:3],
                "conflict_pair": opening_pair[:2],
                "pressure_axis_id": first_axis,
                "milestone_kind": "reveal",
                "route_pivot_tag": "reveal_truth",
                "required_truth_texts": [truth_texts[0] if truth_texts else story_frame.premise],
                "detour_budget": 1,
                "progress_required": 2,
                "affordance_tags": ["reveal_truth", "build_trust", "contain_chaos"],
                "blocked_affordances": [],
            },
            {
                "title_seed": "The Witness Queue",
                "goal_seed": "Turn private testimony into a public process before rumor replaces the archive.",
                "focus_names": alliance_pair[:3],
                "conflict_pair": alliance_pair[:2],
                "pressure_axis_id": second_axis,
                "milestone_kind": "containment",
                "route_pivot_tag": "build_trust",
                "required_truth_texts": [truth_texts[1] if len(truth_texts) > 1 else truth_texts[0] if truth_texts else story_frame.stakes],
                "detour_budget": 1,
                "progress_required": 2,
                "affordance_tags": ["build_trust", "shift_public_narrative", "contain_chaos"],
                "blocked_affordances": [],
            },
            {
                "title_seed": "The Dawn Record",
                "goal_seed": "Publish a binding civic account before the surviving factions invent incompatible truths.",
                "focus_names": settlement_pair[:3],
                "conflict_pair": settlement_pair[:2],
                "pressure_axis_id": third_axis,
                "milestone_kind": "commitment",
                "route_pivot_tag": "shift_public_narrative",
                "required_truth_texts": [truth_texts[-1] if truth_texts else story_frame.stakes],
                "detour_budget": 0,
                "progress_required": 3,
                "affordance_tags": ["shift_public_narrative", "build_trust", "pay_cost"],
                "blocked_affordances": [],
            },
        ]
    return [
        {
            "title_seed": "Emergency Council",
            "goal_seed": "Understand what is breaking and who is steering the crisis toward fracture.",
            "focus_names": opening_pair[:3],
            "conflict_pair": opening_pair[:2],
            "pressure_axis_id": first_axis,
            "milestone_kind": "reveal",
            "route_pivot_tag": "reveal_truth",
            "required_truth_texts": [truth_texts[0] if truth_texts else story_frame.premise],
            "detour_budget": 1,
            "progress_required": 2,
            "affordance_tags": ["reveal_truth", "contain_chaos", "build_trust"],
            "blocked_affordances": [],
        },
        {
            "title_seed": "Public Strain",
            "goal_seed": "Keep the coalition functional long enough to prove the crisis can still be governed in public.",
            "focus_names": alliance_pair[:3],
            "conflict_pair": alliance_pair[:2],
            "pressure_axis_id": second_axis,
            "milestone_kind": "containment",
            "route_pivot_tag": "build_trust",
            "required_truth_texts": [truth_texts[1] if len(truth_texts) > 1 else truth_texts[0] if truth_texts else story_frame.stakes],
            "detour_budget": 1,
            "progress_required": 2,
            "affordance_tags": ["build_trust", "contain_chaos", "shift_public_narrative"],
            "blocked_affordances": [],
        },
        {
            "title_seed": "Final Settlement",
            "goal_seed": "Force the crisis into a public settlement before pressure hardens into a new balance of power.",
            "focus_names": settlement_pair[:3],
            "conflict_pair": settlement_pair[:2],
            "pressure_axis_id": third_axis,
            "milestone_kind": "commitment",
            "route_pivot_tag": "shift_public_narrative",
            "required_truth_texts": [truth_texts[-1] if truth_texts else story_frame.stakes],
            "detour_budget": 0,
            "progress_required": 3,
            "affordance_tags": ["shift_public_narrative", "build_trust", "pay_cost"],
            "blocked_affordances": [],
        },
    ]


def _is_generic_beat_title_seed(value: str, index: int) -> bool:
    normalized = " ".join(str(value or "").strip().split()).casefold()
    if not normalized:
        return True
    if normalized.startswith("beat "):
        return True
    return normalized in {
        f"beat {index}",
        "opening pressure",
        "alliance stress",
        "public strain",
        "emergency council",
        "final settlement",
    }


def _is_generic_beat_goal_seed(value: str) -> bool:
    normalized = " ".join(str(value or "").strip().split()).casefold()
    if not normalized:
        return True
    generic_fragments = (
        "push the story toward a decisive civic turning point",
        "keep the civic crisis moving toward a decisive resolution",
        "understand what is breaking and who is steering the crisis",
        "figure out what is breaking and who is pushing the city toward fracture",
        "keep the coalition intact long enough to expose the real conspiracy",
        "keep the coalition together long enough to expose the real fault line",
        "keep the coalition functional long enough to prove the crisis can still be governed in public",
        "force the crisis into a public settlement before pressure hardens into a new balance of power",
    )
    return any(fragment in normalized for fragment in generic_fragments)


def _stabilize_beat_plan_semantics(
    gateway: "AuthorLLMGateway",
    beats: list[dict[str, Any]],
    *,
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
    primary_theme: str,
) -> list[dict[str, Any]]:
    blueprints = _default_beat_blueprints(gateway, story_frame, cast_draft)
    target_count = min(_target_beat_count(story_frame, cast_draft), len(blueprints))
    stabilized = [dict(item) for item in beats[:4]]
    for index in range(target_count):
        blueprint = dict(blueprints[index])
        if index >= len(stabilized):
            stabilized.append(blueprint)
            continue
        beat = dict(stabilized[index])
        title_is_generic = _is_generic_beat_title_seed(str(beat.get("title_seed") or ""), index + 1)
        goal_is_generic = _is_generic_beat_goal_seed(str(beat.get("goal_seed") or ""))
        if title_is_generic:
            beat["title_seed"] = blueprint["title_seed"]
        if goal_is_generic:
            beat["goal_seed"] = blueprint["goal_seed"]
        if title_is_generic and goal_is_generic:
            beat["pressure_axis_id"] = blueprint["pressure_axis_id"]
            beat["milestone_kind"] = blueprint["milestone_kind"]
            beat["route_pivot_tag"] = blueprint["route_pivot_tag"]
            beat["required_truth_texts"] = blueprint["required_truth_texts"]
            beat["affordance_tags"] = blueprint["affordance_tags"]
            beat["blocked_affordances"] = blueprint["blocked_affordances"]
        if not list(beat.get("focus_names") or []) and blueprint["focus_names"]:
            beat["focus_names"] = blueprint["focus_names"]
        if len(list(beat.get("conflict_pair") or [])) < min(2, len(blueprint["conflict_pair"])):
            beat["conflict_pair"] = blueprint["conflict_pair"]
        if not beat.get("pressure_axis_id") and blueprint.get("pressure_axis_id"):
            beat["pressure_axis_id"] = blueprint["pressure_axis_id"]
        if not beat.get("route_pivot_tag") and blueprint.get("route_pivot_tag"):
            beat["route_pivot_tag"] = blueprint["route_pivot_tag"]
        if not list(beat.get("required_truth_texts") or []) and blueprint["required_truth_texts"]:
            beat["required_truth_texts"] = blueprint["required_truth_texts"]
        if len(list(beat.get("affordance_tags") or [])) < 2:
            beat["affordance_tags"] = blueprint["affordance_tags"]
        if " ".join(str(beat.get("title_seed") or "").strip().split()).casefold() == " ".join(str(beat.get("goal_seed") or "").strip().split()).casefold():
            beat["title_seed"] = blueprint["title_seed"]
        stabilized[index] = beat
    while len(stabilized) < 2 and blueprints:
        stabilized.append(dict(blueprints[min(len(stabilized), len(blueprints) - 1)]))
    if primary_theme == "legitimacy_crisis":
        milestone_set = {item.get("milestone_kind") for item in stabilized if item.get("milestone_kind")}
        route_set = {item.get("route_pivot_tag") for item in stabilized if item.get("route_pivot_tag")}
        if len(milestone_set) < min(3, len(stabilized)) or len(route_set) < min(2, len(stabilized)):
            for index, blueprint in enumerate(blueprints[: len(stabilized)]):
                stabilized[index]["milestone_kind"] = blueprint["milestone_kind"]
                stabilized[index]["route_pivot_tag"] = blueprint["route_pivot_tag"]
                stabilized[index]["pressure_axis_id"] = blueprint["pressure_axis_id"]
                stabilized[index]["required_truth_texts"] = blueprint["required_truth_texts"]
                stabilized[index]["affordance_tags"] = blueprint["affordance_tags"]
    return stabilized[:4]


def _normalize_beat_plan_semantics_payload(
    gateway: "AuthorLLMGateway",
    payload: dict[str, Any],
    *,
    focused_brief: FocusedBrief,
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
) -> dict[str, Any]:
    theme_decision = plan_story_theme(focused_brief, story_frame)
    cast_names = [item.name for item in cast_draft.cast]
    truth_texts = [item.text for item in story_frame.truths]
    axis_ids = [item.template_id for item in story_frame.state_axis_choices]
    axis_id_set = set(axis_ids)
    default_tags = ["reveal_truth", "build_trust", "contain_chaos", "shift_public_narrative", "pay_cost"]
    valid_milestones = {"reveal", "exposure", "fracture", "concession", "containment", "commitment"}
    beats = []
    for index, item in enumerate(list(payload.get("beats") or [])[:4], start=1):
        if not isinstance(item, dict):
            continue
        focus_names = [trim_text(name, 80) for name in list(item.get("focus_names") or [])[:3]]
        focus_names = [name for name in focus_names if name in cast_names]
        conflict_pair = [trim_text(name, 80) for name in list(item.get("conflict_pair") or item.get("conflict_names") or [])[:2]]
        conflict_pair = [name for name in conflict_pair if name in cast_names]
        if not focus_names and conflict_pair:
            focus_names = conflict_pair[:]
        if not focus_names and cast_names:
            focus_names = [cast_names[min(index - 1, len(cast_names) - 1)]]
        if not conflict_pair and len(focus_names) >= 2:
            conflict_pair = focus_names[:2]
        required_truths = [
            trim_text(text, 220)
            for text in list(item.get("required_truth_texts") or [])[:3]
            if trim_text(text, 220) in truth_texts
        ]
        if not required_truths and truth_texts:
            required_truths = [truth_texts[min(index - 1, len(truth_texts) - 1)]]
        pressure_axis_id = str(item.get("pressure_axis_id") or item.get("pressure_axis") or item.get("axis_id") or "").strip()
        if pressure_axis_id not in axis_id_set:
            pressure_axis_id = axis_ids[min(index - 1, len(axis_ids) - 1)] if axis_ids else None
        milestone_kind = str(item.get("milestone_kind") or item.get("milestone") or "reveal").strip().casefold()
        if milestone_kind not in valid_milestones:
            milestone_kind = "reveal" if index == 1 else "fracture"
        route_pivot_tag = normalize_affordance_tag(
            item.get("route_pivot_tag") or item.get("pivot_affordance") or item.get("pivot_tag") or "build_trust"
        )
        affordance_tags = unique_preserve(
            [normalize_affordance_tag(tag) for tag in list(item.get("affordance_tags") or [])[:6]]
        )
        derived_tags = [route_pivot_tag]
        if milestone_kind in {"reveal", "exposure"}:
            derived_tags.append("reveal_truth")
        if milestone_kind in {"containment"}:
            derived_tags.append("contain_chaos")
        if milestone_kind in {"fracture"}:
            derived_tags.append("shift_public_narrative")
        if milestone_kind in {"concession"}:
            derived_tags.append("pay_cost")
        if milestone_kind in {"commitment"}:
            derived_tags.append("unlock_ally")
        if pressure_axis_id in {"external_pressure", "public_panic", "time_window"}:
            derived_tags.append("contain_chaos")
        derived_tags.append("build_trust")
        affordance_tags = unique_preserve(derived_tags + affordance_tags)
        for fallback_tag in default_tags:
            if len(affordance_tags) >= 2:
                break
            if fallback_tag not in affordance_tags:
                affordance_tags.append(fallback_tag)
        blocked_affordances = unique_preserve(
            [normalize_affordance_tag(tag) for tag in list(item.get("blocked_affordances") or [])[:4]]
        )
        blocked_affordances = [tag for tag in blocked_affordances if tag not in affordance_tags]
        beats.append(
            {
                "title_seed": trim_text(item.get("title_seed") or item.get("title") or f"Beat {index}", 80),
                "goal_seed": trim_text(item.get("goal_seed") or item.get("goal") or "Push the story toward a decisive civic turning point.", 180),
                "focus_names": focus_names[:3],
                "conflict_pair": conflict_pair[:2],
                "pressure_axis_id": pressure_axis_id,
                "milestone_kind": milestone_kind,
                "route_pivot_tag": route_pivot_tag,
                "required_truth_texts": required_truths[:3],
                "detour_budget": max(0, min(2, coerce_int(item.get("detour_budget", 1), 1))),
                "progress_required": max(1, min(3, coerce_int(item.get("progress_required", 2), 2))),
                "affordance_tags": affordance_tags[:6],
                "blocked_affordances": blocked_affordances[:4],
            }
        )
    if theme_decision is None:
        theme_decision = plan_story_theme(
            FocusedBrief(
                story_kernel=story_frame.title,
                setting_signal=story_frame.premise,
                core_conflict=story_frame.stakes,
                tone_signal=story_frame.tone,
                hard_constraints=[],
                forbidden_tones=[],
            ),
            story_frame,
        )
    beats = _stabilize_beat_plan_semantics(
        gateway,
        beats,
        story_frame=story_frame,
        cast_draft=cast_draft,
        primary_theme=theme_decision.primary_theme,
    )
    return {"beats": beats[:4]}


def _default_return_hook_for_skeleton(beat: BeatSkeletonSpec, index: int) -> str:
    milestone = beat.milestone_kind
    if milestone in {"reveal", "exposure"}:
        return "A visible contradiction forces the next move."
    if milestone == "containment":
        return "The public expects proof that order can still hold."
    if milestone == "fracture":
        return "A coalition fracture makes delay impossible."
    if milestone == "concession":
        return "A concession redraws the cost of the next move."
    if milestone == "commitment":
        return "A public commitment closes off the safer route."
    return "A visible public consequence forces the next move." if index == 1 else "Delay stops being politically survivable."


def _compose_beat_plan_from_skeleton(
    gateway: "AuthorLLMGateway",
    skeleton: BeatPlanSkeletonDraft,
) -> BeatPlanDraft:
    beats = []
    for index, skeleton_beat in enumerate(skeleton.beats, start=1):
        beats.append(
            BeatDraftSpec(
                title=trim_text(skeleton_beat.title_seed or f"Beat {index}", 120),
                goal=trim_text(
                    skeleton_beat.goal_seed or "Push the story toward a decisive civic turning point.",
                    220,
                ),
                focus_names=skeleton_beat.focus_names,
                conflict_pair=skeleton_beat.conflict_pair,
                pressure_axis_id=skeleton_beat.pressure_axis_id,
                milestone_kind=skeleton_beat.milestone_kind,
                route_pivot_tag=skeleton_beat.route_pivot_tag,
                required_truth_texts=skeleton_beat.required_truth_texts,
                detour_budget=skeleton_beat.detour_budget,
                progress_required=skeleton_beat.progress_required,
                return_hooks=[_default_return_hook_for_skeleton(skeleton_beat, index)],
                affordance_tags=skeleton_beat.affordance_tags,
                blocked_affordances=skeleton_beat.blocked_affordances,
            )
        )
    return BeatPlanDraft(beats=beats)


def _normalize_beat_plan_payload(
    gateway: "AuthorLLMGateway",
    payload: dict[str, Any],
    *,
    focused_brief: FocusedBrief,
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
) -> dict[str, Any]:
    skeleton = BeatPlanSkeletonDraft.model_validate(
        _normalize_beat_plan_semantics_payload(
            gateway,
            payload,
            focused_brief=focused_brief,
            story_frame=story_frame,
            cast_draft=cast_draft,
        )
    )
    return _compose_beat_plan_from_skeleton(gateway, skeleton).model_dump(mode="json")


def generate_beat_plan(
    gateway: "AuthorLLMGateway",
    focused_brief: FocusedBrief,
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
    *,
    previous_response_id: str | None = None,
):
    from rpg_backend.author.gateway import AuthorGatewayError, GatewayStructuredResponse

    context_packet = build_author_context_from_story(story_frame, cast_draft)
    payload: dict[str, Any] = {
        "author_context": context_packet,
    }
    if not (gateway.use_session_cache and previous_response_id):
        payload["focused_brief"] = focused_brief.model_dump(mode="json")
    theme_decision = plan_story_theme(focused_brief, story_frame)
    system_prompt = (
        "You are the Beat Plan skeleton generator. Return one strict JSON object matching BeatPlanSkeletonDraft. "
        "Do not output markdown. Design 2-4 beats for a fixed mainline story with locally flexible play. "
        "Focus on semantic structure first, not polished prose. "
        "Each beat must include: title_seed, goal_seed, focus_names, conflict_pair, pressure_axis_id, milestone_kind, route_pivot_tag, required_truth_texts, detour_budget, progress_required, affordance_tags, blocked_affordances. "
        "Use cast names and truth texts that already exist in author_context. "
        "pressure_axis_id must come from author_context.axes. "
        "milestone_kind must be one of: reveal, exposure, fracture, concession, containment, commitment. "
        "Use conflict_pair to name the two characters whose clash or alliance defines the beat when possible. "
        "Affordance tags must come from: reveal_truth, build_trust, contain_chaos, shift_public_narrative, protect_civilians, secure_resources, unlock_ally, pay_cost. "
        "Keep title_seed short and concrete. Keep goal_seed under one sentence. "
        f"{_beat_theme_guidance(theme_decision.primary_theme)}"
    )
    retry_prompt = (
        "Return only one JSON object matching BeatPlanSkeletonDraft. "
        "No markdown, no explanation, no extra keys. "
        "Use only the keys required by BeatPlanSkeletonDraft. "
        "Keep beats concrete and short."
    )
    try:
        skeleton_result = _invoke_json_with_prompt_retries(
            gateway,
            payload=payload,
            prompts=(system_prompt, retry_prompt),
            previous_response_id=previous_response_id,
            max_output_tokens=_beat_plan_semantics_output_tokens(gateway),
            parse_fn=lambda raw_payload: BeatPlanSkeletonDraft.model_validate(
                _normalize_beat_plan_semantics_payload(
                    gateway,
                    raw_payload,
                    focused_brief=focused_brief,
                    story_frame=story_frame,
                    cast_draft=cast_draft,
                )
            ),
        )
        skeleton = skeleton_result.value
    except AuthorGatewayError:
        raise
    skeleton_response_id = skeleton_result.response_id
    final_beat_plan = _compose_beat_plan_from_skeleton(gateway, skeleton)
    return GatewayStructuredResponse(
        value=final_beat_plan,
        response_id=skeleton_response_id,
    )


def generate_beat_plan_conservative(
    gateway: "AuthorLLMGateway",
    focused_brief: FocusedBrief,
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
    *,
    previous_response_id: str | None = None,
):
    from rpg_backend.author.gateway import AuthorGatewayError

    context_packet = build_author_context_from_story(story_frame, cast_draft)
    payload: dict[str, Any] = {
        "author_context": context_packet,
    }
    if not (gateway.use_session_cache and previous_response_id):
        payload["focused_brief"] = focused_brief.model_dump(mode="json")
    theme_decision = plan_story_theme(focused_brief, story_frame)
    system_prompt = (
        "You are the Beat Plan generator. Return one strict JSON object matching BeatPlanDraft. "
        "Do not output markdown. Design 2-4 beats for a fixed mainline story with locally flexible play. "
        "Each beat must include: title, goal, focus_names, conflict_pair, pressure_axis_id, milestone_kind, route_pivot_tag, required_truth_texts, detour_budget, progress_required, return_hooks, affordance_tags, blocked_affordances. "
        "Use cast names and truth texts that already exist in author_context. "
        "Affordance tags must come from: reveal_truth, build_trust, contain_chaos, shift_public_narrative, protect_civilians, secure_resources, unlock_ally, pay_cost. "
        f"{_beat_theme_guidance(theme_decision.primary_theme)}"
    )
    retry_prompt = (
        "Return only one JSON object matching BeatPlanDraft. "
        "No markdown, no explanation, no extra keys. "
        "Keep each beat compact and valid."
    )
    return _invoke_json_with_prompt_retries(
        gateway,
        payload=payload,
        prompts=(system_prompt, retry_prompt),
        previous_response_id=previous_response_id,
        max_output_tokens=_beat_plan_semantics_output_tokens(gateway),
        parse_fn=lambda raw_payload: BeatPlanDraft.model_validate(
            _normalize_beat_plan_payload(
                gateway,
                raw_payload,
                focused_brief=focused_brief,
                story_frame=story_frame,
                cast_draft=cast_draft,
            )
        ),
    )


def glean_beat_plan(
    gateway: "AuthorLLMGateway",
    focused_brief: FocusedBrief,
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
    partial_beat_plan: BeatPlanDraft,
    *,
    previous_response_id: str | None = None,
):
    from rpg_backend.author.gateway import AuthorGatewayError, GatewayStructuredResponse

    context_packet = build_author_context_from_story(story_frame, cast_draft)
    payload: dict[str, Any] = {
        "author_context": context_packet,
        "partial_beat_plan": partial_beat_plan.model_dump(mode="json"),
    }
    if not (gateway.use_session_cache and previous_response_id):
        payload["focused_brief"] = focused_brief.model_dump(mode="json")
    system_prompt = (
        "You are the Beat Plan repair generator. Return one strict JSON object matching BeatPlanDraft. "
        "Improve partial_beat_plan instead of replacing it wholesale. "
        "Preserve useful titles and goals, but repair weak semantic fields. "
        "Every beat should identify a pressure_axis_id, a milestone_kind, a route_pivot_tag, and a conflict_pair when the cast allows it. "
        "Use only cast names, axis ids, and truth texts already present in author_context."
    )
    retry_prompt = (
        "Return only one JSON object matching BeatPlanDraft. "
        "No markdown, no explanation, no extra keys. "
        "Repair missing structure and keep only valid beat fields."
    )
    try:
        return _invoke_json_with_prompt_retries(
            gateway,
            payload=payload,
            prompts=(system_prompt, retry_prompt),
            previous_response_id=previous_response_id,
            max_output_tokens=_beat_plan_semantics_output_tokens(gateway),
            parse_fn=lambda raw_payload: BeatPlanDraft.model_validate(
                _normalize_beat_plan_payload(
                    gateway,
                    raw_payload,
                    focused_brief=focused_brief,
                    story_frame=story_frame,
                    cast_draft=cast_draft,
                )
            ),
        )
    except AuthorGatewayError:
        raise
