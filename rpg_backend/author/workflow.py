from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from rpg_backend.author.checkpointer import get_author_checkpointer, graph_config
from rpg_backend.author.contracts import (
    AxisTemplateId,
    AffordanceEffectProfile,
    AffordanceWeight,
    AuthorBundleRequest,
    AuthorBundleResponse,
    BeatPlanDraft,
    BeatDraftSpec,
    BeatSpec,
    CastDraft,
    CastOverviewDraft,
    CastMember,
    DesignBundle,
    EndingRulesDraft,
    EndingItem,
    EndingRule,
    FocusedBrief,
    OverviewAxisDraft,
    OverviewCastDraft,
    OverviewFlagDraft,
    CastOverviewSlotDraft,
    OverviewTruthDraft,
    RouteOpportunityPlanDraft,
    RouteAffordancePackDraft,
    RouteUnlockRule,
    RulePack,
    StateSchema,
    StoryBible,
    StoryFrameDraft,
    StoryOverviewDraft,
    TruthItem,
)
from rpg_backend.author.gateway import AuthorGatewayError, AuthorLLMGateway, get_author_llm_gateway


class AuthorState(TypedDict, total=False):
    run_id: str
    raw_brief: str
    focused_brief: FocusedBrief
    author_session_response_id: str
    story_frame_draft: StoryFrameDraft
    cast_overview_draft: CastOverviewDraft
    cast_member_drafts: list[OverviewCastDraft]
    cast_draft: CastDraft
    beat_plan_draft: BeatPlanDraft
    story_bible: StoryBible
    state_schema: StateSchema
    beat_spine: list[BeatSpec]
    route_opportunity_plan_draft: RouteOpportunityPlanDraft
    route_affordance_pack_draft: RouteAffordancePackDraft
    ending_rules_draft: EndingRulesDraft
    rule_pack: RulePack
    design_bundle: DesignBundle


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().split())


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", (value or "").casefold())
    return normalized.strip("_") or "item"


def _trim(value: str, limit: int) -> str:
    text = _normalize(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


AFFORDANCE_CATALOG: tuple[str, ...] = (
    "reveal_truth",
    "build_trust",
    "contain_chaos",
    "shift_public_narrative",
    "protect_civilians",
    "secure_resources",
    "unlock_ally",
    "pay_cost",
)


def _normalize_affordance_tag(value: str) -> str:
    normalized = _slug(value)
    mapping = {
        "reveal": "reveal_truth",
        "investigate": "reveal_truth",
        "build_trust": "build_trust",
        "trust": "build_trust",
        "ally": "unlock_ally",
        "unlock_ally": "unlock_ally",
        "panic_control": "contain_chaos",
        "contain_chaos": "contain_chaos",
        "protect": "protect_civilians",
        "protect_civilians": "protect_civilians",
        "authority": "shift_public_narrative",
        "pressure_authority": "shift_public_narrative",
        "resources": "secure_resources",
        "secure_resources": "secure_resources",
        "narrative_shift": "shift_public_narrative",
        "shift_public_narrative": "shift_public_narrative",
        "cost": "pay_cost",
        "pay_cost": "pay_cost",
    }
    result = mapping.get(normalized, normalized)
    if result not in AFFORDANCE_CATALOG:
        return "build_trust"
    return result


def _default_story_function_for_tag(tag: str) -> str:
    normalized = _normalize_affordance_tag(tag)
    if "reveal" in normalized or "investigate" in normalized:
        return "reveal"
    if "chaos" in normalized or "protect" in normalized:
        return "stabilize"
    if "cost" in normalized:
        return "pay_cost"
    return "advance"


AXIS_TEMPLATE_CATALOG: dict[str, dict[str, str | int]] = {
    "external_pressure": {"label": "External Pressure", "kind": "pressure", "min_value": 0, "max_value": 5},
    "public_panic": {"label": "Public Panic", "kind": "pressure", "min_value": 0, "max_value": 5},
    "political_leverage": {"label": "Political Leverage", "kind": "relationship", "min_value": 0, "max_value": 5},
    "resource_strain": {"label": "Resource Strain", "kind": "resource", "min_value": 0, "max_value": 5},
    "system_integrity": {"label": "System Integrity", "kind": "pressure", "min_value": 0, "max_value": 5},
    "ally_trust": {"label": "Ally Trust", "kind": "relationship", "min_value": 0, "max_value": 5},
    "exposure_risk": {"label": "Exposure Risk", "kind": "exposure", "min_value": 0, "max_value": 5},
    "time_window": {"label": "Time Window", "kind": "time", "min_value": 0, "max_value": 5},
}

DEFAULT_AXIS_ORDER: tuple[AxisTemplateId, ...] = (
    "external_pressure",
    "public_panic",
    "political_leverage",
)

CAST_ARCHETYPE_LIBRARY: dict[str, dict[str, str]] = {
    "civic_mediator": {
        "slot_label": "Mediator Anchor",
        "public_role": "Mediator",
        "agenda_anchor": "Keep the emergency process legitimate long enough to stop the city from splintering.",
        "red_line_anchor": "Will not let emergency pressure erase public consent.",
        "pressure_vector": "Starts bridging hostile sides before every guarantee is secured.",
        "counter_trait": "idealistic in public, quietly controlling in execution",
        "pressure_tell": "Speaks faster, narrows the options, and starts counting who is still willing to stay in the room.",
        "name_bucket": "protagonist",
    },
    "harbor_inspector": {
        "slot_label": "Mediator Anchor",
        "public_role": "Harbor inspector",
        "agenda_anchor": "Keep the quarantine process enforceable without letting trade politics tear the harbor apart.",
        "red_line_anchor": "Will not let emergency decrees turn into unaccountable seizure.",
        "pressure_vector": "Treats every procedural gap as a point where panic and smuggling can rush in together.",
        "counter_trait": "methodical in public, personally restless under delay",
        "pressure_tell": "Starts inspecting details out loud and turning vague claims into hard checkpoints.",
        "name_bucket": "protagonist",
    },
    "archive_guardian": {
        "slot_label": "Institutional Guardian",
        "public_role": "Archive authority",
        "agenda_anchor": "Preserve the institutions and procedures that still make the city governable.",
        "red_line_anchor": "Will not surrender formal authority without a visible procedural reason.",
        "pressure_vector": "Tightens procedure whenever panic, blame, or uncertainty starts to spread.",
        "counter_trait": "severe in public, privately protective of what would be lost",
        "pressure_tell": "Repeats the rules more precisely as the room gets louder and closes off informal exits.",
        "name_bucket": "guardian",
    },
    "port_guardian": {
        "slot_label": "Institutional Guardian",
        "public_role": "Port authority",
        "agenda_anchor": "Keep the harbor operating under rules that still look legitimate to frightened citizens and traders.",
        "red_line_anchor": "Will not let emergency traffic control become private leverage for one faction.",
        "pressure_vector": "Locks movement, paperwork, and access down tighter every time panic jumps a level.",
        "counter_trait": "rigid in public, quietly terrified of systemic collapse",
        "pressure_tell": "Starts reciting manifests, quotas, and access thresholds like a shield against chaos.",
        "name_bucket": "guardian",
    },
    "leverage_broker": {
        "slot_label": "Leverage Broker",
        "public_role": "Political rival",
        "agenda_anchor": "Turn the crisis into leverage over who controls the settlement that comes after it.",
        "red_line_anchor": "Will not accept exclusion from the final settlement.",
        "pressure_vector": "Treats every emergency as proof that someone else should lose authority.",
        "counter_trait": "calculating in public, needy about irrelevance underneath",
        "pressure_tell": "Reframes every setback as evidence that the balance of power must change immediately.",
        "name_bucket": "rival",
    },
    "trade_bloc_rival": {
        "slot_label": "Leverage Broker",
        "public_role": "Trade bloc rival",
        "agenda_anchor": "Convert quarantine chaos into bargaining power over who controls shipping, credit, and recovery.",
        "red_line_anchor": "Will not let the harbor reopen on terms that leave their bloc weakened.",
        "pressure_vector": "Turns every supply shock into a negotiation over power rather than relief.",
        "counter_trait": "polished in public, vengeful about being sidelined",
        "pressure_tell": "Starts offering practical help that always arrives tied to a new concession.",
        "name_bucket": "rival",
    },
    "public_witness": {
        "slot_label": "Civic Witness",
        "public_role": "Public advocate",
        "agenda_anchor": "Force the crisis response to remain publicly accountable while pressure keeps rising.",
        "red_line_anchor": "Will not let elite procedure erase the public record of what happened.",
        "pressure_vector": "Turns ambiguity, secrecy, or procedural drift into public scrutiny.",
        "counter_trait": "morally direct in public, emotionally stubborn in private",
        "pressure_tell": "Stops accepting closed-room assurances and demands that someone say the cost aloud.",
        "name_bucket": "witness",
    },
    "dock_delegate": {
        "slot_label": "Civic Witness",
        "public_role": "Dock delegate",
        "agenda_anchor": "Keep working crews and neighborhood residents from paying for elite quarantine bargains they never approved.",
        "red_line_anchor": "Will not let emergency port rules bury who benefited and who got stranded.",
        "pressure_vector": "Turns private deals into dockside rumors and then into organized pressure.",
        "counter_trait": "plainspoken in public, deeply strategic about crowd mood",
        "pressure_tell": "Starts naming names, losses, and delays until the room can no longer hide behind abstractions.",
        "name_bucket": "witness",
    },
}

CAST_RELATIONSHIP_DYNAMIC_LIBRARY: dict[str, str] = {
    "protagonist_bears_public_weight": "The protagonist stands inside the crisis rather than above it, so every compromise lands as a public burden they personally own.",
    "improvisation_vs_procedure": "This figure needs the protagonist's flexibility but distrusts improvisation once legitimacy is already under strain.",
    "settlement_vs_leverage": "This figure tests whether the protagonist can stabilize the crisis without conceding who gets power after it.",
    "public_record_vs_private_bargain": "This figure turns private bargains into public accountability whenever the room starts deciding too much in secret.",
}


def _strip_leading_article(value: str) -> str:
    text = _normalize(value)
    for prefix in ("a ", "an ", "the "):
        if text.casefold().startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _extract_tail_after_about(text: str) -> str:
    match = re.search(r"\babout\b\s+(.*)", text, flags=re.IGNORECASE)
    if match:
        return _normalize(match.group(1))
    return text


def _split_at_first_marker(text: str, markers: tuple[str, ...]) -> tuple[str, str | None]:
    lowered = text.casefold()
    found: tuple[int, str] | None = None
    for marker in markers:
        index = lowered.find(f" {marker} ")
        if index >= 0 and (found is None or index < found[0]):
            found = (index, marker)
    if found is None:
        return text, None
    index, marker = found
    head = text[:index].strip(" ,.;:")
    tail = text[index + len(marker) + 2 :].strip(" ,.;:")
    return head, f"{marker} {tail}" if tail else marker


def _extract_location_phrase(text: str) -> str:
    tokens = re.findall(r"[a-zA-Z0-9-]+", text)
    if not tokens:
        return _normalize(text)
    location_nouns = {
        "city",
        "kingdom",
        "archive",
        "archives",
        "district",
        "station",
        "temple",
        "capital",
        "monastery",
        "harbor",
        "fortress",
        "republic",
    }
    stop_tokens = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "young",
        "mediator",
        "keeper",
        "envoy",
        "engineer",
        "detective",
        "pilot",
        "keeping",
        "preventing",
        "saving",
        "holding",
        "during",
        "while",
        "without",
        "before",
        "after",
    }
    for index, token in enumerate(tokens):
        lowered = token.casefold()
        if lowered not in location_nouns:
            continue
        start = index
        while start > 0 and tokens[start - 1].casefold() not in stop_tokens:
            start -= 1
        end = index
        while end + 1 < len(tokens) and tokens[end + 1].casefold() in location_nouns:
            end += 1
        phrase = " ".join(tokens[start : end + 1]).strip()
        temporal = re.search(r"\b(during|amid|under)\b\s+([^,.!?;]+)", text, flags=re.IGNORECASE)
        if temporal:
            phrase = f"{phrase} {temporal.group(1)} {temporal.group(2).strip()}"
        return _normalize(phrase)
    return _normalize(text)


def _extract_tone_signal(text: str) -> str:
    match = re.search(
        r"^(?:a|an|the)?\s*((?:hopeful|tense|grim|warm|political|civic|mystery|thriller|fantasy|science[- ]fiction|romantic|adventure|melancholic|optimistic|paranoid|urgent)(?:\s+(?:hopeful|tense|grim|warm|political|civic|mystery|thriller|fantasy|science[- ]fiction|romantic|adventure|melancholic|optimistic|paranoid|urgent))*)\s+about\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return _normalize(match.group(1))
    fallback_terms: list[str] = []
    for term in ("hopeful", "political", "civic", "mystery", "thriller", "fantasy", "urgent", "tense"):
        if term in text.casefold():
            fallback_terms.append(term)
    if fallback_terms:
        return " ".join(dict.fromkeys(fallback_terms))
    return _trim(text, 120)


def _split_protagonist_and_mission(text: str) -> tuple[str, str]:
    normalized = _normalize(text)
    if not normalized:
        return "", ""
    match = re.match(
        r"^((?:a|an|the)\s+(?:[a-z0-9-]+\s+){0,4}(?:mediator|envoy|engineer|captain|detective|pilot|archivist|keeper|priest|councilor|guard|messenger|scholar|mayor|agent|negotiator))\s+(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if match:
        return _normalize(match.group(1)), _normalize(match.group(2))
    return "", normalized


def _to_infinitive(phrase: str) -> str:
    normalized = _normalize(phrase)
    if not normalized:
        return normalized
    parts = normalized.split(" ", 1)
    first = parts[0].casefold()
    rest = parts[1] if len(parts) > 1 else ""
    rewrites = {
        "keeping": "keep",
        "holding": "hold",
        "saving": "save",
        "protecting": "protect",
        "stabilizing": "stabilize",
        "preventing": "prevent",
        "brokering": "broker",
        "guiding": "guide",
        "maintaining": "maintain",
        "preserving": "preserve",
        "uncovering": "uncover",
        "exposing": "expose",
        "stopping": "stop",
    }
    rewritten = rewrites.get(first, parts[0])
    return _normalize(f"{rewritten} {rest}".strip())


def _extract_constraint_marker_phrase(text: str) -> tuple[str | None, str | None]:
    for marker in ("without", "during", "while", "before", "after", "amid"):
        match = re.search(rf"\b{marker}\b\s+([^,.!?;]+)", text, flags=re.IGNORECASE)
        if match:
            return marker, _normalize(match.group(1))
    return None, None


def _infer_pressure_phrase(*, setting_signal: str, constraint_marker: str | None, constraint_tail: str | None) -> str:
    if constraint_tail:
        if constraint_marker in {"during", "while", "amid"}:
            return _normalize(f"while {constraint_tail} strains civic order")
        if constraint_marker == "without":
            return _normalize(f"without {constraint_tail}")
        if constraint_marker == "before":
            return _normalize(f"before {constraint_tail} triggers open fracture")
        if constraint_marker == "after":
            return _normalize(f"after {constraint_tail} reshapes the balance of power")

    lowered = setting_signal.casefold()
    fragments: list[str] = []
    if "election" in lowered or "vote" in lowered:
        fragments.append("civic legitimacy starts to fracture")
    if "blackout" in lowered:
        fragments.append("coordination breaks down")
    if "flood" in lowered or "storm" in lowered:
        fragments.append("system pressure keeps rising")
    if "archive" in lowered or "record" in lowered:
        fragments.append("collective memory is at risk")
    if not fragments:
        return "while public order grows more fragile"
    if len(fragments) == 1:
        return f"while {fragments[0]}"
    return f"while {fragments[0]} and {fragments[1]}"


def focus_brief(raw_brief: str) -> FocusedBrief:
    normalized = _normalize(raw_brief)
    tail = _extract_tail_after_about(normalized)
    kernel_head, kernel_tail = _split_at_first_marker(tail, ("during", "while", "without", "before", "after", "amid"))
    story_kernel = _normalize(kernel_head or tail)
    setting_signal = _extract_location_phrase(tail if tail else normalized)
    protagonist, mission_phrase = _split_protagonist_and_mission(story_kernel)
    mission_core = _to_infinitive(mission_phrase or story_kernel)
    constraint_marker, constraint_tail = _extract_constraint_marker_phrase(normalized)
    pressure_phrase = _infer_pressure_phrase(
        setting_signal=setting_signal,
        constraint_marker=constraint_marker,
        constraint_tail=constraint_tail,
    )
    core_conflict = _normalize(f"{mission_core} {pressure_phrase}".strip())
    tone_signal = _extract_tone_signal(normalized)
    hard_constraints = []
    for marker in ("without", "before", "while", "during", "after"):
        match = re.search(rf"\b{marker}\b\s+([^,.!?;]+)", normalized, flags=re.IGNORECASE)
        if match:
            hard_constraints.append(_normalize(f"{marker} {match.group(1)}"))
    unique_constraints = []
    for item in hard_constraints:
        if item and item.casefold() not in {existing.casefold() for existing in unique_constraints}:
            unique_constraints.append(item)
    return FocusedBrief(
        story_kernel=_trim(story_kernel, 220),
        setting_signal=_trim(setting_signal, 220),
        core_conflict=_trim(core_conflict, 220),
        tone_signal=_trim(tone_signal, 120),
        hard_constraints=[_trim(item, 160) for item in unique_constraints[:4]],
        forbidden_tones=["graphic cruelty", "sadistic evil"],
    )


def _npc_id(name: str) -> str:
    return _slug(name)


def _default_story_frame_premise(focused_brief: FocusedBrief) -> str:
    return _trim(
        f"In {focused_brief.setting_signal}, {focused_brief.story_kernel} while {focused_brief.core_conflict}.",
        320,
    )


def _default_story_frame_stakes(focused_brief: FocusedBrief) -> str:
    return _trim(
        f"If civic legitimacy breaks before the protagonist stabilizes the crisis, {focused_brief.setting_signal.casefold()} falls into open fracture and the mission fails in public view.",
        240,
    )


def _default_story_frame_truths(focused_brief: FocusedBrief) -> list[OverviewTruthDraft]:
    return [
        OverviewTruthDraft(text=_trim(focused_brief.core_conflict, 220), importance="core"),
        OverviewTruthDraft(
            text=_trim(
                f"The crisis is shaped by conditions inside {focused_brief.setting_signal}.",
                220,
            ),
            importance="core",
        ),
    ]


def build_design_bundle(
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
    beat_plan_draft: BeatPlanDraft,
    focused_brief: FocusedBrief,
) -> DesignBundle:
    cast = [
        CastMember(
            npc_id=_npc_id(item.name),
            name=_trim(item.name, 80),
            role=_trim(item.role, 120),
            agenda=_trim(item.agenda, 220),
            red_line=_trim(item.red_line, 220),
            pressure_signature=_trim(item.pressure_signature, 220),
        )
        for item in cast_draft.cast
    ]

    truths = [
        TruthItem(
            truth_id=f"truth_{index}",
            text=_trim(item.text, 220),
            importance=item.importance,
        )
        for index, item in enumerate(story_frame.truths, start=1)
    ]
    truth_id_by_text = {item.text: truth.truth_id for item, truth in zip(story_frame.truths, truths, strict=False)}

    axis_rows: list[dict[str, object]] = []
    seen_axis_ids: set[str] = set()
    for axis in story_frame.state_axis_choices:
        template = AXIS_TEMPLATE_CATALOG[axis.template_id]
        if axis.template_id in seen_axis_ids:
            continue
        seen_axis_ids.add(axis.template_id)
        axis_rows.append(
            {
                "axis_id": axis.template_id,
                "label": _trim(axis.story_label or str(template["label"]), 80),
                "kind": template["kind"],
                "min_value": int(template["min_value"]),
                "max_value": int(template["max_value"]),
                "starting_value": max(0, min(int(template["max_value"]), axis.starting_value)),
            }
        )
    for axis_id in DEFAULT_AXIS_ORDER:
        if axis_id in seen_axis_ids:
            continue
        template = AXIS_TEMPLATE_CATALOG[axis_id]
        axis_rows.append(
            {
                "axis_id": axis_id,
                "label": str(template["label"]),
                "kind": template["kind"],
                "min_value": int(template["min_value"]),
                "max_value": int(template["max_value"]),
                "starting_value": 0 if axis_id != "external_pressure" else 1,
            }
        )
        seen_axis_ids.add(axis_id)
        if len(axis_rows) >= 3:
            break

    state_schema = StateSchema.model_validate(
        {
            "axes": axis_rows[:6],
            "stances": [
                {
                    "stance_id": f"{_npc_id(item.name)}_stance",
                    "npc_id": _npc_id(item.name),
                    "label": f"{_trim(item.name, 60)} Stance",
                    "min_value": -2,
                    "max_value": 3,
                    "starting_value": 0,
                }
                for item in cast_draft.cast
            ],
            "flags": [
                {
                    "flag_id": _slug(flag.label),
                    "label": _trim(flag.label, 80),
                    "starting_value": bool(flag.starting_value),
                }
                for flag in story_frame.flags
            ],
        }
    )

    bible = StoryBible(
        title=_trim(story_frame.title, 120),
        premise=_trim(story_frame.premise, 320),
        tone=_trim(story_frame.tone, 120),
        stakes=_trim(story_frame.stakes, 240),
        style_guard=_trim(story_frame.style_guard, 220),
        cast=cast,
        world_rules=[_trim(item, 180) for item in story_frame.world_rules],
        truth_catalog=truths,
        ending_catalog=[
            EndingItem(ending_id="mixed", label="Mixed Outcome", summary="The city survives, but trust and stability remain damaged."),
            EndingItem(ending_id="pyrrhic", label="Pyrrhic Outcome", summary="Success arrives only through a steep civic or personal cost."),
            EndingItem(ending_id="collapse", label="Collapse", summary="The crisis outruns coordination and the city pays the price."),
        ],
    )

    cast_names = {item.name for item in cast_draft.cast}
    cast_id_by_name = {item.name: _npc_id(item.name) for item in cast_draft.cast}
    beat_spine: list[BeatSpec] = []
    for index, beat in enumerate(beat_plan_draft.beats, start=1):
        focus_npcs = [cast_id_by_name[name] for name in beat.focus_names if name in cast_names][:3]
        affordance_tags = [_normalize_affordance_tag(tag) for tag in beat.affordance_tags]
        blocked = [_normalize_affordance_tag(tag) for tag in beat.blocked_affordances]
        beat_spine.append(
            BeatSpec(
                beat_id=f"b{index}",
                title=_trim(beat.title, 120),
                goal=_trim(beat.goal, 220),
                focus_npcs=focus_npcs,
                required_truths=[truth_id_by_text[text] for text in beat.required_truth_texts if text in truth_id_by_text][:4],
                required_events=[f"b{index}.milestone"],
                detour_budget=beat.detour_budget,
                progress_required=beat.progress_required,
                return_hooks=[_trim(item, 180) for item in beat.return_hooks[:3]],
                affordances=[AffordanceWeight(tag=tag, weight=1 + (offset == 0)) for offset, tag in enumerate(affordance_tags[:6])],
                blocked_affordances=blocked[:4],
            )
        )

    return DesignBundle(
        focused_brief=focused_brief,
        story_bible=bible,
        state_schema=state_schema,
        beat_spine=beat_spine,
        rule_pack=RulePack(
            route_unlock_rules=[],
            ending_rules=[EndingRule(ending_id="mixed", priority=100, conditions={})],
            affordance_effect_profiles=[
                AffordanceEffectProfile(
                    affordance_tag="reveal_truth",
                    default_story_function="reveal",
                    axis_deltas={},
                    stance_deltas={},
                    can_add_truth=True,
                    can_add_event=False,
                ),
                AffordanceEffectProfile(
                    affordance_tag="build_trust",
                    default_story_function="advance",
                    axis_deltas={},
                    stance_deltas={},
                    can_add_truth=False,
                    can_add_event=True,
                ),
            ],
        ),
    )


def build_default_story_frame_draft(focused_brief: FocusedBrief) -> StoryFrameDraft:
    return StoryFrameDraft(
        title=_trim(focused_brief.story_kernel.split(",")[0].title(), 120) or "Untitled Crisis",
        premise=_default_story_frame_premise(focused_brief),
        tone=_trim(focused_brief.tone_signal, 120),
        stakes=_default_story_frame_stakes(focused_brief),
        style_guard="Keep the story tense, readable, and grounded in public consequences rather than dark spectacle.",
        world_rules=[
            _trim(f"Visible order in {focused_brief.setting_signal} depends on public legitimacy.", 180),
            "The main plot advances in fixed beats even when local tactics vary.",
        ],
        truths=_default_story_frame_truths(focused_brief),
        state_axis_choices=[
            OverviewAxisDraft(template_id="external_pressure", story_label="System Pressure", starting_value=1),
            OverviewAxisDraft(template_id="public_panic", story_label="Public Panic", starting_value=0),
            OverviewAxisDraft(template_id="political_leverage", story_label="Political Leverage", starting_value=2),
        ],
        flags=[
            OverviewFlagDraft(label="Public Cover", starting_value=False),
        ],
    )


def _build_cast_slot_from_archetype(
    archetype_id: str,
    relationship_dynamic_id: str,
) -> CastOverviewSlotDraft:
    archetype = CAST_ARCHETYPE_LIBRARY[archetype_id]
    return CastOverviewSlotDraft(
        slot_label=archetype["slot_label"],
        public_role=archetype["public_role"],
        relationship_to_protagonist=CAST_RELATIONSHIP_DYNAMIC_LIBRARY[relationship_dynamic_id],
        agenda_anchor=archetype["agenda_anchor"],
        red_line_anchor=archetype["red_line_anchor"],
        pressure_vector=archetype["pressure_vector"],
        archetype_id=archetype_id,
        relationship_dynamic_id=relationship_dynamic_id,
        counter_trait=archetype["counter_trait"],
        pressure_tell=archetype["pressure_tell"],
    )


def build_default_cast_overview_draft(focused_brief: FocusedBrief) -> CastOverviewDraft:
    del focused_brief
    return CastOverviewDraft(
        cast_slots=[
            _build_cast_slot_from_archetype("civic_mediator", "protagonist_bears_public_weight"),
            _build_cast_slot_from_archetype("archive_guardian", "improvisation_vs_procedure"),
            _build_cast_slot_from_archetype("leverage_broker", "settlement_vs_leverage"),
        ],
        relationship_summary=[
            CAST_RELATIONSHIP_DYNAMIC_LIBRARY["improvisation_vs_procedure"],
            CAST_RELATIONSHIP_DYNAMIC_LIBRARY["settlement_vs_leverage"],
        ],
    )


def derive_cast_overview_draft(
    focused_brief: FocusedBrief,
    story_frame: StoryFrameDraft,
) -> CastOverviewDraft:
    premise = story_frame.premise.casefold()
    title = story_frame.title.casefold()

    protagonist_archetype_id = "civic_mediator"
    if any(keyword in premise for keyword in ("inspector", "harbor inspector")):
        protagonist_archetype_id = "harbor_inspector"

    guardian_archetype_id = "archive_guardian"
    if any(keyword in premise for keyword in ("archive", "ledger", "archives")):
        guardian_archetype_id = "archive_guardian"
    elif any(keyword in premise for keyword in ("harbor", "port", "trade")):
        guardian_archetype_id = "port_guardian"

    rival_archetype_id = "leverage_broker"
    if any(keyword in title for keyword in ("quarantine", "accord")):
        rival_archetype_id = "trade_bloc_rival"

    cast_slots = [
        _build_cast_slot_from_archetype(protagonist_archetype_id, "protagonist_bears_public_weight"),
        _build_cast_slot_from_archetype(guardian_archetype_id, "improvisation_vs_procedure"),
        _build_cast_slot_from_archetype(rival_archetype_id, "settlement_vs_leverage"),
    ]
    relationship_summary = [
        CAST_RELATIONSHIP_DYNAMIC_LIBRARY["improvisation_vs_procedure"],
        CAST_RELATIONSHIP_DYNAMIC_LIBRARY["settlement_vs_leverage"],
    ]

    if story_frame.flags:
        cast_slots.append(
            _build_cast_slot_from_archetype(
                "dock_delegate" if any(keyword in premise for keyword in ("harbor", "port", "trade", "quarantine")) else "public_witness",
                "public_record_vs_private_bargain",
            )
        )
        relationship_summary.append(
            CAST_RELATIONSHIP_DYNAMIC_LIBRARY["public_record_vs_private_bargain"]
        )

    return CastOverviewDraft(
        cast_slots=cast_slots[:5],
        relationship_summary=relationship_summary[:6],
    )


def _name_palette_for_brief(focused_brief: FocusedBrief) -> dict[str, list[str]]:
    setting = focused_brief.setting_signal.casefold()
    if any(keyword in setting for keyword in ("archive", "archives", "ledger", "record", "script", "library")):
        return {
            "protagonist": ["Elara Vance", "Iri Vale", "Nera Quill", "Tarin Sloane"],
            "guardian": ["Kaelen Thorne", "Sen Ardin", "Pell Ivar", "Sera Nhal"],
            "rival": ["Mira Solis", "Tal Reth", "Dain Voss", "Cass Vey"],
            "civic": ["Lio Maren", "Risa Vale", "Joren Pell", "Tavi Sern"],
            "witness": ["Ona Pell", "Lio Maren", "Risa Vale", "Tavi Sern"],
        }
    if any(keyword in setting for keyword in ("harbor", "port", "trade", "quarantine", "republic", "dock")):
        return {
            "protagonist": ["Corin Hale", "Mara Vey", "Tessa Vale", "Ilan Dorr"],
            "guardian": ["Jun Pell", "Soren Vale", "Neris Dane", "Hadrin Voss"],
            "rival": ["Tal Reth", "Cass Voren", "Mira Solis", "Dain Vey"],
            "civic": ["Edda Marr", "Korin Pell", "Rhea Doss", "Sel Varan"],
            "witness": ["Edda Marr", "Sel Varan", "Brin Vale", "Rhea Doss"],
        }
    return {
        "protagonist": ["Elara Vance", "Corin Hale", "Mira Vale", "Iri Vale"],
        "guardian": ["Kaelen Thorne", "Sera Pell", "Jun Ardin", "Pell Ivar"],
        "rival": ["Tal Reth", "Mira Solis", "Dain Voss", "Cass Vey"],
        "civic": ["Risa Vale", "Lio Maren", "Tavi Sern", "Neris Dane"],
        "witness": ["Lio Maren", "Ona Pell", "Risa Vale", "Tavi Sern"],
    }


def _cast_slot_bucket(slot: CastOverviewSlotDraft) -> str:
    if slot.archetype_id in {"public_witness", "dock_delegate"}:
        return "witness"
    text = f"{slot.slot_label} {slot.public_role}".casefold()
    if any(keyword in text for keyword in ("mediator", "anchor", "player", "envoy", "inspector", "protagonist")):
        return "protagonist"
    if any(keyword in text for keyword in ("institution", "guardian", "authority", "curator", "scribe", "warden")):
        return "guardian"
    if any(keyword in text for keyword in ("broker", "rival", "opposition", "leverage", "faction", "merchant")):
        return "rival"
    return "civic"


def _generated_name_for_slot(
    slot: CastOverviewSlotDraft,
    focused_brief: FocusedBrief,
    slot_index: int,
    used_names: set[str],
) -> str:
    palette = _name_palette_for_brief(focused_brief)
    bucket = _cast_slot_bucket(slot)
    options = palette[bucket]
    seed = f"{focused_brief.story_kernel}|{focused_brief.setting_signal}|{slot.slot_label}|{slot_index}"
    start = sum(ord(ch) for ch in seed) % len(options)
    for offset in range(len(options)):
        candidate = options[(start + offset) % len(options)]
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
    fallback = f"{options[start]} {slot_index + 1}"
    used_names.add(fallback)
    return fallback


def build_cast_draft_from_overview(
    cast_overview: CastOverviewDraft,
    focused_brief: FocusedBrief,
) -> CastDraft:
    used_names: set[str] = set()
    return CastDraft(
        cast=[
            OverviewCastDraft(
                name=_generated_name_for_slot(slot, focused_brief, index, used_names),
                role=_trim(slot.public_role, 120),
                agenda=_trim(slot.agenda_anchor, 220),
                red_line=_trim(slot.red_line_anchor, 220),
                pressure_signature=_trim(slot.pressure_vector, 220),
            )
            for index, slot in enumerate(cast_overview.cast_slots)
        ]
    )


def build_cast_member_from_slot(
    slot: CastOverviewSlotDraft,
    focused_brief: FocusedBrief,
    slot_index: int,
    existing_names: set[str],
) -> OverviewCastDraft:
    return OverviewCastDraft(
        name=_generated_name_for_slot(slot, focused_brief, slot_index, existing_names),
        role=_trim(slot.public_role, 120),
        agenda=_trim(slot.agenda_anchor, 220),
        red_line=_trim(slot.red_line_anchor, 220),
        pressure_signature=_trim(slot.pressure_vector, 220),
    )


def build_default_cast_draft(_: FocusedBrief) -> CastDraft:
    return CastDraft(
        cast=[
            OverviewCastDraft(
                name="The Mediator",
                role="Player anchor",
                agenda="Hold the city together long enough to expose the truth.",
                red_line="Will not deliberately sacrifice civilians for speed.",
                pressure_signature="Feels every compromise as a public burden.",
            ),
            OverviewCastDraft(
                name="Civic Authority",
                role="Institutional power",
                agenda="Preserve order and legitimacy.",
                red_line="Will not publicly yield without visible cause.",
                pressure_signature="Turns every crisis into a test of control.",
            ),
            OverviewCastDraft(
                name="Opposition Broker",
                role="Political rival",
                agenda="Exploit the crisis to reshape power.",
                red_line="Will not accept irrelevance.",
                pressure_signature="Smiles while pressure spreads through the room.",
            ),
        ]
    )


def build_default_beat_plan_draft(
    focused_brief: FocusedBrief,
    *,
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
) -> BeatPlanDraft:
    cast_names = [item.name for item in cast_draft.cast]
    return BeatPlanDraft(
        beats=[
            BeatDraftSpec(
                title="Opening Pressure",
                goal="Understand what is breaking and who is steering the crisis.",
                focus_names=cast_names[:2] or ["The Mediator", "Civic Authority"],
                required_truth_texts=[_trim(story_frame.truths[0].text if story_frame.truths else focused_brief.core_conflict, 220)],
                detour_budget=1,
                progress_required=2,
                return_hooks=["A visible public consequence forces the issue."],
                affordance_tags=["reveal_truth", "contain_chaos", "build_trust"],
                blocked_affordances=[],
            ),
            BeatDraftSpec(
                title="Alliance Stress",
                goal="Keep the coalition together long enough to expose the real fault line.",
                focus_names=cast_names[1:3] if len(cast_names) >= 3 else cast_names[:2] or ["Civic Authority", "Opposition Broker"],
                required_truth_texts=[
                    _trim(
                        story_frame.truths[1].text if len(story_frame.truths) > 1 else focused_brief.setting_signal,
                        220,
                    )
                ],
                detour_budget=1,
                progress_required=2,
                return_hooks=["A new fracture in the alliance makes delay impossible."],
                affordance_tags=["build_trust", "shift_public_narrative", "pay_cost"],
                blocked_affordances=[],
            ),
        ]
    )


def assemble_story_overview(
    story_frame: StoryFrameDraft,
    cast_draft: CastDraft,
    beat_plan_draft: BeatPlanDraft,
) -> StoryOverviewDraft:
    return StoryOverviewDraft(
        title=story_frame.title,
        premise=story_frame.premise,
        tone=story_frame.tone,
        stakes=story_frame.stakes,
        style_guard=story_frame.style_guard,
        cast=cast_draft.cast,
        world_rules=story_frame.world_rules,
        truths=story_frame.truths,
        state_axis_choices=story_frame.state_axis_choices,
        flags=story_frame.flags,
        beats=beat_plan_draft.beats,
    )


def build_default_overview_draft(focused_brief: FocusedBrief) -> StoryOverviewDraft:
    story_frame = build_default_story_frame_draft(focused_brief)
    cast_draft = build_cast_draft_from_overview(
        build_default_cast_overview_draft(focused_brief),
        focused_brief,
    )
    beat_plan_draft = build_default_beat_plan_draft(
        focused_brief,
        story_frame=story_frame,
        cast_draft=cast_draft,
    )
    return assemble_story_overview(story_frame, cast_draft, beat_plan_draft)


def _bundle_affordance_tags(bundle: DesignBundle) -> list[str]:
    affordance_tags = sorted({weight.tag for beat in bundle.beat_spine for weight in beat.affordances})
    if len(affordance_tags) < 2:
        for fallback_tag in ("reveal_truth", "build_trust"):
            if fallback_tag not in affordance_tags:
                affordance_tags.append(fallback_tag)
            if len(affordance_tags) >= 2:
                break
    return affordance_tags


def normalize_route_affordance_pack(
    route_affordance_pack: RouteAffordancePackDraft,
    bundle: DesignBundle,
) -> RouteAffordancePackDraft:
    beat_ids = {beat.beat_id for beat in bundle.beat_spine}
    affordance_tags = set(_bundle_affordance_tags(bundle))
    axis_ids = {axis.axis_id for axis in bundle.state_schema.axes}
    stance_ids = {stance.stance_id for stance in bundle.state_schema.stances}
    flag_ids = {flag.flag_id for flag in bundle.state_schema.flags}
    truth_ids = {truth.truth_id for truth in bundle.story_bible.truth_catalog}
    event_ids = {event for beat in bundle.beat_spine for event in beat.required_events}

    normalized_routes = []
    for rule in route_affordance_pack.route_unlock_rules:
        if rule.beat_id not in beat_ids or rule.unlock_affordance_tag not in affordance_tags:
            continue
        if any(key not in axis_ids for key in (*rule.conditions.min_axes.keys(), *rule.conditions.max_axes.keys())):
            continue
        if any(key not in stance_ids for key in rule.conditions.min_stances.keys()):
            continue
        if any(item not in truth_ids for item in rule.conditions.required_truths):
            continue
        if any(item not in event_ids for item in rule.conditions.required_events):
            continue
        if any(item not in flag_ids for item in rule.conditions.required_flags):
            continue
        normalized_routes.append(rule)

    profile_by_tag = {profile.affordance_tag: profile for profile in route_affordance_pack.affordance_effect_profiles}
    normalized_profiles = []
    for tag in sorted(affordance_tags):
        if tag in profile_by_tag:
            normalized_profiles.append(profile_by_tag[tag])
            continue
        default_story_function = "advance"
        if "reveal" in tag or "investigate" in tag:
            default_story_function = "reveal"
        elif "chaos" in tag or "protect" in tag:
            default_story_function = "stabilize"
        elif "cost" in tag:
            default_story_function = "pay_cost"
        normalized_profiles.append(
            AffordanceEffectProfile(
                affordance_tag=tag,
                default_story_function=default_story_function,  # type: ignore[arg-type]
                axis_deltas={},
                stance_deltas={},
                can_add_truth=default_story_function == "reveal",
                can_add_event=default_story_function in {"advance", "pay_cost"},
            )
        )

    return RouteAffordancePackDraft(
        route_unlock_rules=normalized_routes,
        affordance_effect_profiles=normalized_profiles,
    )


def normalize_ending_rules_draft(
    ending_rules_draft: EndingRulesDraft,
    bundle: DesignBundle,
) -> EndingRulesDraft:
    ending_ids = {item.ending_id for item in bundle.story_bible.ending_catalog}
    normalized_endings = [rule for rule in ending_rules_draft.ending_rules if rule.ending_id in ending_ids]
    if not normalized_endings:
        normalized_endings = [EndingRule(ending_id="mixed", priority=100, conditions={})]
    return EndingRulesDraft(
        ending_rules=sorted(normalized_endings, key=lambda item: item.priority),
    )


def merge_rule_pack(
    route_affordance_pack: RouteAffordancePackDraft,
    ending_rules_draft: EndingRulesDraft,
) -> RulePack:
    return RulePack(
        route_unlock_rules=route_affordance_pack.route_unlock_rules,
        ending_rules=ending_rules_draft.ending_rules,
        affordance_effect_profiles=route_affordance_pack.affordance_effect_profiles,
    )


def normalize_rule_pack(rule_pack: RulePack, bundle: DesignBundle) -> RulePack:
    normalized_route_affordance_pack = normalize_route_affordance_pack(
        RouteAffordancePackDraft(
            route_unlock_rules=rule_pack.route_unlock_rules,
            affordance_effect_profiles=rule_pack.affordance_effect_profiles,
        ),
        bundle,
    )
    normalized_ending_rules = normalize_ending_rules_draft(
        EndingRulesDraft(ending_rules=rule_pack.ending_rules),
        bundle,
    )
    return merge_rule_pack(normalized_route_affordance_pack, normalized_ending_rules)


def build_deterministic_affordance_profiles(bundle: DesignBundle) -> list[AffordanceEffectProfile]:
    affordance_tags = _bundle_affordance_tags(bundle)
    axes_by_id = {axis.axis_id: axis for axis in bundle.state_schema.axes}
    pressure_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "pressure"), bundle.state_schema.axes[0].axis_id)
    relationship_axis = next(
        (
            axis.axis_id
            for axis in bundle.state_schema.axes
            if axis.kind == "relationship" and axis.axis_id != pressure_axis
        ),
        pressure_axis,
    )
    resource_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "resource"), relationship_axis)
    exposure_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "exposure"), pressure_axis)
    panic_axis = "public_panic" if "public_panic" in axes_by_id else pressure_axis
    leverage_axis = "political_leverage" if "political_leverage" in axes_by_id else relationship_axis
    ally_axis = "ally_trust" if "ally_trust" in axes_by_id else relationship_axis
    first_stance_id = bundle.state_schema.stances[0].stance_id if bundle.state_schema.stances else None

    profiles = []
    for tag in affordance_tags:
        default_story_function = _default_story_function_for_tag(tag)
        axis_deltas: dict[str, int] = {}
        stance_deltas: dict[str, int] = {}
        if tag == "reveal_truth":
            axis_deltas = {exposure_axis: 1}
        elif tag == "build_trust":
            axis_deltas = {ally_axis: 1}
        elif tag == "contain_chaos":
            axis_deltas = {panic_axis: -1}
        elif tag == "shift_public_narrative":
            axis_deltas = {leverage_axis: 1}
            if panic_axis != leverage_axis:
                axis_deltas[panic_axis] = -1
        elif tag == "protect_civilians":
            axis_deltas = {pressure_axis: -1}
        elif tag == "secure_resources":
            axis_deltas = {resource_axis: -1}
        elif tag == "unlock_ally":
            if first_stance_id:
                stance_deltas = {first_stance_id: 1}
            else:
                axis_deltas = {ally_axis: 1}
        elif tag == "pay_cost":
            axis_deltas = {pressure_axis: 1}
        profiles.append(
            AffordanceEffectProfile(
                affordance_tag=tag,
                default_story_function=default_story_function,  # type: ignore[arg-type]
                axis_deltas=axis_deltas,
                stance_deltas=stance_deltas,
                can_add_truth=default_story_function == "reveal",
                can_add_event=default_story_function in {"advance", "pay_cost"},
            )
        )
    return profiles


def build_default_route_opportunity_plan(bundle: DesignBundle) -> RouteOpportunityPlanDraft:
    pressure_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "pressure"), bundle.state_schema.axes[0].axis_id)
    opportunities = []
    for index, beat in enumerate(bundle.beat_spine):
        if beat.required_truths:
            trigger = {"kind": "truth", "target_id": beat.required_truths[0]}
        elif index > 0:
            trigger = {"kind": "event", "target_id": bundle.beat_spine[index - 1].required_events[0]}
        elif bundle.state_schema.flags:
            trigger = {"kind": "flag", "target_id": bundle.state_schema.flags[0].flag_id}
        elif bundle.state_schema.stances:
            trigger = {"kind": "stance", "target_id": bundle.state_schema.stances[0].stance_id, "min_value": 1}
        else:
            trigger = {"kind": "axis", "target_id": pressure_axis, "min_value": 2}
        opportunities.append(
            {
                "beat_id": beat.beat_id,
                "unlock_route_id": f"{beat.beat_id}_{beat.affordances[0].tag}_route",
                "unlock_affordance_tag": beat.affordances[0].tag,
                "triggers": [trigger],
            }
        )
    return RouteOpportunityPlanDraft.model_validate({"opportunities": opportunities[:8]})


def compile_route_opportunity_plan(
    route_opportunity_plan: RouteOpportunityPlanDraft,
    bundle: DesignBundle,
) -> RouteAffordancePackDraft:
    beat_ids = {beat.beat_id for beat in bundle.beat_spine}
    affordance_tags = set(_bundle_affordance_tags(bundle))
    axis_ids = {axis.axis_id for axis in bundle.state_schema.axes}
    stance_ids = {stance.stance_id for stance in bundle.state_schema.stances}
    flag_ids = {flag.flag_id for flag in bundle.state_schema.flags}
    truth_ids = {truth.truth_id for truth in bundle.story_bible.truth_catalog}
    event_ids = {event for beat in bundle.beat_spine for event in beat.required_events}
    signatures: set[tuple[str, str, str, tuple[tuple[str, str, int | None], ...]]] = set()
    route_unlock_rules = []

    for opportunity in route_opportunity_plan.opportunities:
        if opportunity.beat_id not in beat_ids or opportunity.unlock_affordance_tag not in affordance_tags:
            continue
        min_axes: dict[str, int] = {}
        min_stances: dict[str, int] = {}
        required_truths: list[str] = []
        required_flags: list[str] = []
        required_events: list[str] = []
        trigger_signature: list[tuple[str, str, int | None]] = []
        for trigger in opportunity.triggers:
            if trigger.kind == "truth" and trigger.target_id in truth_ids:
                required_truths.append(trigger.target_id)
                trigger_signature.append(("truth", trigger.target_id, None))
            elif trigger.kind == "axis" and trigger.target_id in axis_ids:
                threshold = max(1, min(5, trigger.min_value or 2))
                min_axes[trigger.target_id] = threshold
                trigger_signature.append(("axis", trigger.target_id, threshold))
            elif trigger.kind == "stance" and trigger.target_id in stance_ids:
                threshold = max(1, min(3, trigger.min_value or 1))
                min_stances[trigger.target_id] = threshold
                trigger_signature.append(("stance", trigger.target_id, threshold))
            elif trigger.kind == "flag" and trigger.target_id in flag_ids:
                required_flags.append(trigger.target_id)
                trigger_signature.append(("flag", trigger.target_id, None))
            elif trigger.kind == "event" and trigger.target_id in event_ids:
                required_events.append(trigger.target_id)
                trigger_signature.append(("event", trigger.target_id, None))
        if not trigger_signature:
            continue
        signature = (
            opportunity.beat_id,
            opportunity.unlock_route_id,
            opportunity.unlock_affordance_tag,
            tuple(sorted(trigger_signature)),
        )
        if signature in signatures:
            continue
        signatures.add(signature)
        route_unlock_rules.append(
            RouteUnlockRule(
                rule_id=_slug(f"{opportunity.beat_id}_{opportunity.unlock_route_id}"),
                beat_id=opportunity.beat_id,
                conditions={
                    "min_axes": min_axes,
                    "max_axes": {},
                    "min_stances": min_stances,
                    "required_truths": sorted(set(required_truths)),
                    "required_events": sorted(set(required_events)),
                    "required_flags": sorted(set(required_flags)),
                },
                unlock_route_id=opportunity.unlock_route_id,
                unlock_affordance_tag=opportunity.unlock_affordance_tag,
            )
        )

    return RouteAffordancePackDraft(
        route_unlock_rules=route_unlock_rules,
        affordance_effect_profiles=build_deterministic_affordance_profiles(bundle),
    )


def build_default_route_affordance_pack(bundle: DesignBundle) -> RouteAffordancePackDraft:
    return compile_route_opportunity_plan(build_default_route_opportunity_plan(bundle), bundle)


def _ending_story_specific_hints(bundle: DesignBundle) -> dict[str, list[str] | str | None]:
    truth_ids = [item.truth_id for item in bundle.story_bible.truth_catalog]
    event_ids = [event for beat in bundle.beat_spine for event in beat.required_events]
    flag_ids = [item.flag_id for item in bundle.state_schema.flags]
    return {
        "primary_truth_id": truth_ids[0] if truth_ids else None,
        "secondary_truth_id": truth_ids[1] if len(truth_ids) > 1 else (truth_ids[0] if truth_ids else None),
        "final_event_id": event_ids[-1] if event_ids else None,
        "opening_event_id": event_ids[0] if event_ids else None,
        "primary_flag_id": flag_ids[0] if flag_ids else None,
    }


def build_default_ending_rules(bundle: DesignBundle) -> EndingRulesDraft:
    pressure_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.kind == "pressure"), bundle.state_schema.axes[0].axis_id)
    secondary_axis = next((axis.axis_id for axis in bundle.state_schema.axes if axis.axis_id != pressure_axis), pressure_axis)
    hints = _ending_story_specific_hints(bundle)

    collapse_conditions: dict[str, object] = {
        "min_axes": {pressure_axis: 5},
    }
    if hints["primary_truth_id"]:
        collapse_conditions["required_truths"] = [hints["primary_truth_id"]]

    pyrrhic_conditions: dict[str, object] = {
        "min_axes": {secondary_axis: 5},
    }
    if hints["final_event_id"]:
        pyrrhic_conditions["required_events"] = [hints["final_event_id"]]
    if hints["primary_flag_id"]:
        pyrrhic_conditions["required_flags"] = [hints["primary_flag_id"]]
    elif hints["secondary_truth_id"]:
        pyrrhic_conditions["required_truths"] = [hints["secondary_truth_id"]]

    return EndingRulesDraft(
        ending_rules=[
            EndingRule(ending_id="collapse", priority=1, conditions=collapse_conditions),
            EndingRule(ending_id="pyrrhic", priority=2, conditions=pyrrhic_conditions),
            EndingRule(ending_id="mixed", priority=10, conditions={}),
        ],
    )


def build_default_rule_pack(bundle: DesignBundle) -> RulePack:
    return merge_rule_pack(
        build_default_route_affordance_pack(bundle),
        build_default_ending_rules(bundle),
    )


def _resolved_session_response_id(
    prior_response_id: str | None,
    next_response_id: str | None,
) -> str | None:
    return next_response_id or prior_response_id


def _is_placeholder_cast(cast_draft: CastDraft) -> bool:
    return all(item.name.startswith("Civic Figure ") for item in cast_draft.cast)


def _is_generic_cast_overview_text(value: str) -> bool:
    lowered = _normalize(value).casefold()
    generic_fragments = (
        "complicates or supports the protagonist under pressure",
        "protect their institutional stake while the crisis unfolds",
        "will not accept being cut out of the settlement",
        "pushes harder for leverage as public pressure rises",
        "civic role",
        "stakeholder",
    )
    return any(fragment in lowered for fragment in generic_fragments)


def _is_low_quality_cast_overview(cast_overview: CastOverviewDraft) -> bool:
    unique_roles = {slot.public_role.casefold() for slot in cast_overview.cast_slots}
    generic_markers = 0
    total_markers = 0
    for slot in cast_overview.cast_slots:
        for value in (
            slot.slot_label,
            slot.relationship_to_protagonist,
            slot.agenda_anchor,
            slot.red_line_anchor,
            slot.pressure_vector,
        ):
            total_markers += 1
            if _is_generic_cast_overview_text(value):
                generic_markers += 1
    return len(unique_roles) < min(2, len(cast_overview.cast_slots)) or generic_markers >= max(4, total_markers // 2)


def _is_generic_cast_text(value: str) -> bool:
    lowered = _normalize(value).casefold()
    generic_fragments = (
        "tries to preserve their role in the crisis",
        "will not lose public legitimacy without resistance",
        "reacts sharply when pressure threatens public order",
        "protect their corner of the city during the crisis",
        "will not accept total collapse without resistance",
        "pushes for quick action whenever the public mood worsens",
        "placeholder agenda",
        "placeholder red line",
        "placeholder pressure signature",
    )
    return any(fragment in lowered for fragment in generic_fragments)


def _repair_cast_draft(
    cast_draft: CastDraft,
    focused_brief: FocusedBrief,
    cast_overview: CastOverviewDraft | None = None,
) -> CastDraft:
    role_templates = (
        (
            ("mediator", "envoy", "inspector", "player", "anchor", "negotiator"),
            {
                "agenda": _trim(f"Keep the civic process intact long enough to resolve {focused_brief.core_conflict}.", 220),
                "red_line": "Will not let emergency pressure erase public consent.",
                "pressure_signature": "Reads every compromise in terms of what the public will have to live with next.",
            },
        ),
        (
            ("authority", "curator", "official", "institution", "guardian"),
            {
                "agenda": _trim(f"Preserve institutional continuity inside {focused_brief.setting_signal}.", 220),
                "red_line": "Will not yield formal authority without a visible procedural reason.",
                "pressure_signature": "Tightens procedure whenever panic, blame, or uncertainty starts to spread.",
            },
        ),
        (
            ("broker", "rival", "faction", "opposition", "merchant", "leader"),
            {
                "agenda": _trim(f"Exploit {focused_brief.core_conflict} to reshape who holds leverage after the crisis.", 220),
                "red_line": "Will not accept exclusion from the final settlement.",
                "pressure_signature": "Treats every emergency as proof that someone else should lose authority.",
            },
        ),
    )

    slot_templates = list(cast_overview.cast_slots) if cast_overview else []
    repaired = []
    for index, member in enumerate(cast_draft.cast):
        matching_slot = None
        if slot_templates:
            member_role = member.role.casefold()
            member_name = member.name.casefold()
            for slot in slot_templates:
                if slot.slot_label.casefold() in member_name or slot.public_role.casefold() in member_role or any(
                    keyword in member_role
                    for keyword in slot.public_role.casefold().split()
                    if len(keyword) > 3
                ):
                    matching_slot = slot
                    break
            if matching_slot is None and index < len(slot_templates):
                matching_slot = slot_templates[index]
        role_text = member.role.casefold()
        template = None
        for keywords, candidate in role_templates:
            if any(keyword in role_text for keyword in keywords):
                template = candidate
                break
        if matching_slot is not None:
            template = {
                "agenda": _trim(matching_slot.agenda_anchor, 220),
                "red_line": _trim(matching_slot.red_line_anchor, 220),
                "pressure_signature": _trim(matching_slot.pressure_vector, 220),
            }
        elif template is None:
            template = (
                role_templates[min(index, len(role_templates) - 1)][1]
                if index < len(role_templates)
                else {
                    "agenda": _trim(f"Protect their stake in {focused_brief.setting_signal} while the crisis unfolds.", 220),
                    "red_line": "Will not accept being made irrelevant by emergency decree.",
                    "pressure_signature": "Pushes harder for advantage whenever the public mood turns brittle.",
                }
            )
        repaired.append(
            OverviewCastDraft(
                name=member.name,
                role=member.role,
                agenda=template["agenda"] if _is_generic_cast_text(member.agenda) else member.agenda,
                red_line=template["red_line"] if _is_generic_cast_text(member.red_line) else member.red_line,
                pressure_signature=template["pressure_signature"] if _is_generic_cast_text(member.pressure_signature) else member.pressure_signature,
            )
        )
    return CastDraft(cast=repaired)


def _is_placeholder_cast_member(member: OverviewCastDraft) -> bool:
    return member.name.startswith("Civic Figure ") or member.name.casefold() in {
        "mediator anchor",
        "institutional guardian",
        "leverage broker",
        "archive guardian",
        "coalition rival",
        "civic witness",
        "public advocate",
    }


def _looks_like_role_label_name(
    member_name: str,
    slot: CastOverviewSlotDraft,
) -> bool:
    normalized_name = _normalize(member_name).casefold()
    if normalized_name in {
        _normalize(slot.slot_label).casefold(),
        _normalize(slot.public_role).casefold(),
    }:
        return True
    generic_tokens = {
        "mediator",
        "anchor",
        "guardian",
        "broker",
        "witness",
        "rival",
        "authority",
        "advocate",
        "public",
        "civic",
        "institutional",
        "archive",
        "coalition",
        "trade",
        "bloc",
        "player",
        "power",
        "figure",
        "delegate",
    }
    tokens = [token for token in normalized_name.replace("-", " ").split() if token]
    if len(tokens) < 2:
        return True
    nongeneric_tokens = [token for token in tokens if token not in generic_tokens]
    return len(nongeneric_tokens) < 1


def _repair_cast_member(
    member: OverviewCastDraft,
    focused_brief: FocusedBrief,
    slot: CastOverviewSlotDraft,
) -> OverviewCastDraft:
    role_text = (member.role or slot.public_role).casefold()
    agenda = member.agenda
    red_line = member.red_line
    pressure_signature = member.pressure_signature

    if _is_generic_cast_text(agenda):
        agenda = slot.agenda_anchor
    if _is_generic_cast_text(red_line):
        red_line = slot.red_line_anchor
    if _is_generic_cast_text(pressure_signature):
        pressure_signature = slot.pressure_vector

    if "mediator" in role_text or "inspector" in role_text or "anchor" in role_text:
        agenda = slot.agenda_anchor if _is_generic_cast_text(member.agenda) else agenda
    elif any(keyword in role_text for keyword in ("guardian", "authority", "institution", "curator", "scribe")):
        agenda = slot.agenda_anchor if _is_generic_cast_text(member.agenda) else agenda
    elif any(keyword in role_text for keyword in ("broker", "rival", "opposition", "merchant", "trade bloc")):
        agenda = slot.agenda_anchor if _is_generic_cast_text(member.agenda) else agenda

    return OverviewCastDraft(
        name=member.name,
        role=_trim(member.role or slot.public_role, 120),
        agenda=_trim(agenda, 220),
        red_line=_trim(red_line, 220),
        pressure_signature=_trim(pressure_signature, 220),
    )


def _is_low_quality_cast_member(
    member: OverviewCastDraft,
    existing_names: set[str],
    slot: CastOverviewSlotDraft,
) -> bool:
    if _is_placeholder_cast_member(member):
        return True
    if _looks_like_role_label_name(member.name, slot):
        return True
    if member.name in existing_names:
        return True
    generic_fields = sum(
        1
        for value in (member.agenda, member.red_line, member.pressure_signature)
        if _is_generic_cast_text(value)
    )
    return generic_fields >= 2


def _is_low_quality_cast(cast_draft: CastDraft) -> bool:
    generic_fields = 0
    total_fields = 0
    for member in cast_draft.cast:
        for value in (member.agenda, member.red_line, member.pressure_signature):
            total_fields += 1
            if _is_generic_cast_text(value):
                generic_fields += 1
    unique_roles = {member.role.casefold() for member in cast_draft.cast}
    return generic_fields >= max(3, total_fields // 2) or len(unique_roles) < min(2, len(cast_draft.cast))


def _finalize_cast_overview_candidate(
    cast_overview: CastOverviewDraft,
    focused_brief: FocusedBrief,
) -> CastOverviewDraft | None:
    del focused_brief
    if _is_low_quality_cast_overview(cast_overview):
        return None
    return cast_overview


def _finalize_cast_candidate(
    cast_draft: CastDraft,
    focused_brief: FocusedBrief,
    cast_overview: CastOverviewDraft,
) -> CastDraft | None:
    if _is_placeholder_cast(cast_draft):
        return None
    repaired = _repair_cast_draft(
        cast_draft,
        focused_brief,
        cast_overview,
    )
    if _is_low_quality_cast(repaired):
        return None
    return repaired


def _finalize_cast_member_candidate(
    member: OverviewCastDraft,
    focused_brief: FocusedBrief,
    slot: CastOverviewSlotDraft,
    existing_names: set[str],
) -> OverviewCastDraft | None:
    repaired = _repair_cast_member(member, focused_brief, slot)
    if _is_low_quality_cast_member(repaired, existing_names, slot):
        return None
    return repaired


def _is_low_quality_story_frame(
    story_frame: StoryFrameDraft,
    focused_brief: FocusedBrief,
) -> bool:
    markers = 0
    if _normalize(story_frame.premise).casefold() == _normalize(focused_brief.story_kernel).casefold():
        markers += 1
    if story_frame.stakes.casefold().startswith("if the player fails"):
        markers += 1
    if any(_normalize(rule).casefold() == _normalize(focused_brief.setting_signal).casefold() for rule in story_frame.world_rules):
        markers += 1
    truth_texts = {_normalize(item.text).casefold() for item in story_frame.truths}
    if truth_texts <= {
        _normalize(focused_brief.core_conflict).casefold(),
        _normalize(focused_brief.setting_signal).casefold(),
    }:
        markers += 1
    if _normalize(story_frame.title).casefold() in {"untitled crisis", _normalize(focused_brief.story_kernel).casefold()}:
        markers += 1
    return markers >= 3


def _has_condition_content(conditions) -> bool:  # noqa: ANN001
    return any(
        getattr(conditions, key)
        for key in (
            "min_axes",
            "max_axes",
            "min_stances",
            "required_truths",
            "required_events",
            "required_flags",
        )
    )


def _has_story_specific_condition(conditions) -> bool:  # noqa: ANN001
    return bool(
        conditions.min_stances
        or conditions.required_truths
        or conditions.required_events
        or conditions.required_flags
    )


def _is_low_quality_ending_rules(ending_rules_draft: EndingRulesDraft) -> bool:
    rules_by_id = {item.ending_id: item for item in ending_rules_draft.ending_rules}
    if "mixed" not in rules_by_id:
        return True
    if len(rules_by_id) < 3:
        return True
    non_mixed_rules = [item for ending_id, item in rules_by_id.items() if ending_id != "mixed"]
    if len(non_mixed_rules) < 2:
        return True
    if any(not _has_condition_content(item.conditions) for item in non_mixed_rules):
        return True
    return not any(_has_story_specific_condition(item.conditions) for item in non_mixed_rules)


def _is_low_quality_route_affordance_pack(
    route_affordance_pack: RouteAffordancePackDraft,
    bundle: DesignBundle,
) -> bool:
    if not route_affordance_pack.route_unlock_rules:
        return True
    if not any(_has_condition_content(item.conditions) for item in route_affordance_pack.route_unlock_rules):
        return True
    unique_beats = {item.beat_id for item in route_affordance_pack.route_unlock_rules}
    if len(bundle.beat_spine) > 1 and len(unique_beats) < min(2, len(bundle.beat_spine)):
        return True
    return False


def build_author_graph(*, gateway: AuthorLLMGateway | None = None, checkpointer=None):
    resolved_gateway = gateway or get_author_llm_gateway()

    def generate_story_frame_node(state: AuthorState) -> dict[str, Any]:
        prior_response_id = state.get("author_session_response_id")
        latest_response_id = prior_response_id
        try:
            generated = resolved_gateway.generate_story_frame(
                state["focused_brief"],
                previous_response_id=prior_response_id,
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            story_frame_seed = build_default_story_frame_draft(state["focused_brief"])
        else:
            story_frame_seed = generated.value
            latest_response_id = _resolved_session_response_id(prior_response_id, generated.response_id)

        story_frame_draft = story_frame_seed
        if _is_low_quality_story_frame(story_frame_seed, state["focused_brief"]):
            try:
                gleaned = resolved_gateway.glean_story_frame(
                    state["focused_brief"],
                    story_frame_seed,
                    previous_response_id=latest_response_id,
                )
                latest_response_id = _resolved_session_response_id(latest_response_id, gleaned.response_id)
                if not _is_low_quality_story_frame(gleaned.value, state["focused_brief"]):
                    story_frame_draft = gleaned.value
                else:
                    story_frame_draft = build_default_story_frame_draft(state["focused_brief"])
            except AuthorGatewayError as exc:
                if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                    raise
                story_frame_draft = build_default_story_frame_draft(state["focused_brief"])
        return {
            "story_frame_draft": story_frame_draft,
            "author_session_response_id": latest_response_id,
        }

    def derive_cast_overview_node(state: AuthorState) -> dict[str, Any]:
        return {
            "cast_overview_draft": derive_cast_overview_draft(
                state["focused_brief"],
                state["story_frame_draft"],
            )
        }

    def generate_cast_members_node(state: AuthorState) -> dict[str, Any]:
        prior_response_id = state.get("author_session_response_id")
        existing_members = list(state.get("cast_member_drafts") or [])
        latest_response_id = prior_response_id
        slots = list(state["cast_overview_draft"].cast_slots)

        for slot_index in range(len(existing_members), len(slots)):
            slot = slots[slot_index]
            existing_names = {member.name for member in existing_members}
            slot_payload = slot.model_dump(mode="json")
            existing_payload = [member.model_dump(mode="json") for member in existing_members]
            fallback_member = build_cast_member_from_slot(
                slot,
                state["focused_brief"],
                slot_index,
                set(existing_names),
            )
            try:
                generated = resolved_gateway.generate_story_cast_member(
                    state["focused_brief"],
                    state["story_frame_draft"],
                    slot_payload,
                    existing_payload,
                    previous_response_id=latest_response_id,
                )
            except AuthorGatewayError as exc:
                if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                    raise
                member_seed = fallback_member
            else:
                member_seed = generated.value
                latest_response_id = _resolved_session_response_id(latest_response_id, generated.response_id)

            finalized_member = _finalize_cast_member_candidate(
                member_seed,
                state["focused_brief"],
                slot,
                existing_names,
            )
            if finalized_member is None:
                try:
                    gleaned = resolved_gateway.glean_story_cast_member(
                        state["focused_brief"],
                        state["story_frame_draft"],
                        slot_payload,
                        existing_payload,
                        member_seed.model_dump(mode="json"),
                        previous_response_id=latest_response_id,
                    )
                    latest_response_id = _resolved_session_response_id(latest_response_id, gleaned.response_id)
                    finalized_member = _finalize_cast_member_candidate(
                        gleaned.value,
                        state["focused_brief"],
                        slot,
                        existing_names,
                    )
                except AuthorGatewayError as exc:
                    if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                        raise
            if finalized_member is None:
                finalized_member = fallback_member
            existing_members.append(finalized_member)

        return {
            "cast_member_drafts": existing_members,
            "author_session_response_id": latest_response_id,
        }

    def assemble_cast_node(state: AuthorState) -> dict[str, Any]:
        return {
            "cast_draft": CastDraft(cast=list(state.get("cast_member_drafts") or [])),
        }

    def generate_beat_plan_node(state: AuthorState) -> dict[str, Any]:
        prior_response_id = state.get("author_session_response_id")
        try:
            generated = resolved_gateway.generate_beat_plan(
                state["focused_brief"],
                state["story_frame_draft"],
                state["cast_draft"],
                previous_response_id=prior_response_id,
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            return {
                "beat_plan_draft": build_default_beat_plan_draft(
                    state["focused_brief"],
                    story_frame=state["story_frame_draft"],
                    cast_draft=state["cast_draft"],
                ),
            }
        return {
            "beat_plan_draft": generated.value,
            "author_session_response_id": _resolved_session_response_id(prior_response_id, generated.response_id),
        }

    def build_design_bundle_node(state: AuthorState) -> dict[str, Any]:
        bundle = build_design_bundle(
            state["story_frame_draft"],
            state["cast_draft"],
            state["beat_plan_draft"],
            state["focused_brief"],
        )
        return {
            "story_bible": bundle.story_bible,
            "state_schema": bundle.state_schema,
            "beat_spine": bundle.beat_spine,
            "design_bundle": bundle,
        }

    def generate_route_opportunity_plan_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        prior_response_id = state.get("author_session_response_id")
        try:
            generated = resolved_gateway.generate_route_opportunity_plan_result(
                design_bundle,
                previous_response_id=prior_response_id,
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            return {
                "route_opportunity_plan_draft": build_default_route_opportunity_plan(design_bundle),
            }
        return {
            "route_opportunity_plan_draft": generated.value,
            "author_session_response_id": _resolved_session_response_id(prior_response_id, generated.response_id),
        }

    def compile_route_affordance_pack_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        route_affordance_pack = compile_route_opportunity_plan(
            state["route_opportunity_plan_draft"],
            design_bundle,
        )
        if _is_low_quality_route_affordance_pack(route_affordance_pack, design_bundle):
            route_affordance_pack = build_default_route_affordance_pack(design_bundle)
        return {
            "route_affordance_pack_draft": route_affordance_pack,
        }

    def generate_ending_rules_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        prior_response_id = state.get("author_session_response_id")
        latest_response_id = prior_response_id
        try:
            generated = resolved_gateway.generate_ending_rules_result(
                design_bundle,
                previous_response_id=prior_response_id,
            )
        except AuthorGatewayError as exc:
            if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                raise
            normalized = normalize_ending_rules_draft(
                build_default_ending_rules(design_bundle),
                design_bundle,
            )
            return {
                "ending_rules_draft": normalized,
            }
        latest_response_id = _resolved_session_response_id(prior_response_id, generated.response_id)
        normalized = normalize_ending_rules_draft(generated.value, design_bundle)
        if _is_low_quality_ending_rules(normalized):
            try:
                gleaned = resolved_gateway.glean_ending_rules(
                    design_bundle,
                    normalized,
                    previous_response_id=latest_response_id,
                )
                latest_response_id = _resolved_session_response_id(latest_response_id, gleaned.response_id)
                normalized = normalize_ending_rules_draft(gleaned.value, design_bundle)
            except AuthorGatewayError as exc:
                if exc.code not in {"llm_invalid_json", "llm_schema_invalid"}:
                    raise
            if _is_low_quality_ending_rules(normalized):
                normalized = normalize_ending_rules_draft(
                    build_default_ending_rules(design_bundle),
                    design_bundle,
                )
        return {
            "ending_rules_draft": normalized,
            "author_session_response_id": latest_response_id,
        }

    def merge_rule_pack_node(state: AuthorState) -> dict[str, Any]:
        design_bundle = state["design_bundle"]
        rule_pack = merge_rule_pack(
            state["route_affordance_pack_draft"],
            state["ending_rules_draft"],
        )
        return {
            "rule_pack": rule_pack,
            "design_bundle": design_bundle.model_copy(update={"rule_pack": rule_pack}),
        }

    builder = StateGraph(AuthorState)
    builder.add_node("focus_brief", lambda state: {"focused_brief": focus_brief(state["raw_brief"])})
    builder.add_node("generate_story_frame", generate_story_frame_node)
    builder.add_node("derive_cast_overview", derive_cast_overview_node)
    builder.add_node("generate_cast_members", generate_cast_members_node)
    builder.add_node("assemble_cast", assemble_cast_node)
    builder.add_node("generate_beat_plan", generate_beat_plan_node)
    builder.add_node("build_design_bundle", build_design_bundle_node)
    builder.add_node("generate_route_opportunity_plan", generate_route_opportunity_plan_node)
    builder.add_node("compile_route_affordance_pack", compile_route_affordance_pack_node)
    builder.add_node("generate_ending_rules", generate_ending_rules_node)
    builder.add_node("merge_rule_pack", merge_rule_pack_node)
    builder.add_edge(START, "focus_brief")
    builder.add_edge("focus_brief", "generate_story_frame")
    builder.add_edge("generate_story_frame", "derive_cast_overview")
    builder.add_edge("derive_cast_overview", "generate_cast_members")
    builder.add_edge("generate_cast_members", "assemble_cast")
    builder.add_edge("assemble_cast", "generate_beat_plan")
    builder.add_edge("generate_beat_plan", "build_design_bundle")
    builder.add_edge("build_design_bundle", "generate_route_opportunity_plan")
    builder.add_edge("generate_route_opportunity_plan", "compile_route_affordance_pack")
    builder.add_edge("compile_route_affordance_pack", "generate_ending_rules")
    builder.add_edge("generate_ending_rules", "merge_rule_pack")
    builder.add_edge("merge_rule_pack", END)
    return builder.compile(checkpointer=checkpointer or get_author_checkpointer())


def run_author_bundle(request: AuthorBundleRequest, *, gateway: AuthorLLMGateway | None = None) -> AuthorBundle:
    run_id = str(uuid4())
    graph = build_author_graph(gateway=gateway)
    result = graph.invoke(
        {
            "run_id": run_id,
            "raw_brief": request.raw_brief,
        },
        config=graph_config(run_id=run_id),
    )
    return AuthorBundle(
        run_id=run_id,
        bundle=result["design_bundle"],
        state=result,
    )


class AuthorBundle(AuthorBundleResponse):
    state: dict[str, Any]
