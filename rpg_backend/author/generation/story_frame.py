from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rpg_backend.author.compiler.router import plan_brief_theme
from rpg_backend.author.compiler.story import compile_story_frame
from rpg_backend.author.contracts import FocusedBrief, StoryFrameDraft, StoryFrameScaffoldDraft
from rpg_backend.author.normalize import coerce_int, trim_text, unique_preserve

if TYPE_CHECKING:
    from rpg_backend.author.gateway import AuthorLLMGateway, GatewayStructuredResponse


def _story_frame_semantics_output_tokens(gateway: "AuthorLLMGateway", strategy: str) -> int | None:
    budget = gateway.max_output_tokens_overview
    if budget is None:
        return 1100 if strategy == "legitimacy_story" else 800
    floor = 800
    if strategy == "legitimacy_story":
        floor = 1100
    return max(int(budget), floor)


def _normalize_story_frame_semantics_payload(
    gateway: "AuthorLLMGateway",
    payload: dict[str, Any],
    *,
    fallback_truths: list[str],
) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["tone"] = trim_text(normalized.get("tone") or "hopeful civic fantasy", 120)
    world_rules = [
        trim_text(item, 180)
        for item in list(normalized.get("world_rules") or [])[:5]
        if isinstance(item, str) and trim_text(item, 180)
    ]
    world_rules = unique_preserve(world_rules)
    fallback_world_rules = [
        "Power and public legitimacy move together.",
        "The main plot advances through fixed beats even if local tactics vary.",
    ]
    while len(world_rules) < 2:
        world_rules.append(fallback_world_rules[len(world_rules)])
    normalized["world_rules"] = world_rules[:5]
    truths = []
    for item in list(normalized.get("truths") or [])[:6]:
        if not isinstance(item, dict):
            continue
        text = trim_text(item.get("text"), 220)
        if not text:
            continue
        truths.append(
            {
                "text": text,
                "importance": item.get("importance") or "core",
            }
        )
    truths = unique_preserve([json.dumps(item, ensure_ascii=False, sort_keys=True) for item in truths])
    normalized_truths = [json.loads(item) for item in truths]
    if len(normalized_truths) < 2:
        truth_defaults = [
            {"text": trim_text(text, 220), "importance": "core"}
            for text in fallback_truths
            if trim_text(text, 220)
        ]
        normalized_truths.extend(truth_defaults[len(normalized_truths) :])
    normalized["truths"] = normalized_truths[:6]
    axis_choices = []
    raw_axis_items = list(normalized.get("state_axis_choices") or normalized.get("axes") or [])[:5]
    for item in raw_axis_items:
        if not isinstance(item, dict):
            continue
        label_text = trim_text(item.get("story_label") or item.get("label") or "State Axis", 80)
        axis_choices.append(
            {
                "template_id": item.get("template_id") or "external_pressure",
                "story_label": label_text,
                "starting_value": max(0, min(3, coerce_int(item.get("starting_value", 0), 0))),
            }
        )
    axis_defaults = [
        {"template_id": "external_pressure", "story_label": "Civic Pressure", "starting_value": 1},
        {"template_id": "public_panic", "story_label": "Public Panic", "starting_value": 0},
        {"template_id": "political_leverage", "story_label": "Political Leverage", "starting_value": 2},
    ]
    seen_templates = {item["template_id"] for item in axis_choices if item.get("template_id")}
    for item in axis_defaults:
        if len(axis_choices) >= 5:
            break
        if item["template_id"] in seen_templates:
            continue
        axis_choices.append(item)
        seen_templates.add(item["template_id"])
        if len(axis_choices) >= 3:
            break
    normalized["state_axis_choices"] = axis_choices[:5]
    normalized.pop("axes", None)
    flags = []
    for item in list(normalized.get("flags") or [])[:4]:
        if not isinstance(item, dict):
            continue
        label = trim_text(item.get("label"), 80)
        if not label:
            continue
        flags.append(
            {
                "label": label,
                "starting_value": bool(item.get("starting_value", False)),
            }
        )
    normalized["flags"] = flags
    return normalized


def _normalize_story_frame_scaffold_payload(
    gateway: "AuthorLLMGateway",
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_story_frame_semantics_payload(
        gateway,
        payload,
        fallback_truths=[
            str(payload.get("opposition_force") or payload.get("setting_frame") or "The crisis has internal causes."),
            str(payload.get("stakes_core") or payload.get("protagonist_mandate") or "Public legitimacy is fragile."),
        ],
    )
    normalized["title_seed"] = trim_text(
        normalized.get("title_seed") or payload.get("title") or "Lantern Accord",
        80,
    )
    normalized["setting_frame"] = trim_text(
        normalized.get("setting_frame") or "a city under civic pressure",
        180,
    )
    normalized["protagonist_mandate"] = trim_text(
        normalized.get("protagonist_mandate") or "a mediator must keep the coalition intact",
        220,
    )
    normalized["opposition_force"] = trim_text(
        normalized.get("opposition_force") or "institutional fracture and political opportunism push the city toward collapse",
        220,
    )
    normalized["stakes_core"] = trim_text(
        normalized.get("stakes_core") or "the city loses both legitimacy and continuity in public view",
        220,
    )
    return normalized


def _normalize_story_frame_payload(
    gateway: "AuthorLLMGateway",
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_story_frame_semantics_payload(
        gateway,
        payload,
        fallback_truths=[
            str(payload.get("premise") or "A city under pressure must decide what still holds it together."),
            str(payload.get("stakes") or "If the coalition fails, the city loses both legitimacy and continuity."),
        ],
    )
    normalized["title"] = trim_text(normalized.get("title") or "Untitled Crisis", 120)
    normalized["premise"] = trim_text(
        normalized.get("premise") or "A city under pressure must decide what still holds it together.",
        320,
    )
    normalized["stakes"] = trim_text(
        normalized.get("stakes") or "If the coalition fails, the city loses both legitimacy and continuity.",
        240,
    )
    normalized["style_guard"] = trim_text(
        normalized.get("style_guard")
        or "Keep the story tense, readable, and grounded in civic consequence rather than spectacle.",
        220,
    )
    return normalized


def _story_frame_theme_guidance(strategy: str) -> str:
    mapping = {
        "legitimacy_story": "Emphasize public legitimacy, coalition bargaining, mandates, and visible settlement pressure.",
        "logistics_story": "Emphasize supply lines, quarantine boundaries, inspections, scarcity, and operational chokepoints.",
        "truth_record_story": "Emphasize records, testimony, evidence integrity, procedural proof, and the public record.",
        "public_order_story": "Emphasize panic control, visible order, emergency authority, and crowd-facing consequence.",
        "generic_civic_story": "Emphasize civic pressure, public consequence, and procedural conflict.",
    }
    return mapping.get(strategy, mapping["generic_civic_story"])


def _story_frame_text_matches(value: str, reference: str) -> bool:
    normalized_value = " ".join(str(value or "").strip().split()).casefold()
    normalized_reference = " ".join(str(reference or "").strip().split()).casefold()
    if not normalized_value or not normalized_reference:
        return not normalized_value
    return (
        normalized_value == normalized_reference
        or normalized_value in normalized_reference
        or normalized_reference in normalized_value
    )


def _default_story_frame_title_seed(focused_brief: FocusedBrief) -> str:
    lowered = f"{focused_brief.setting_signal} {focused_brief.core_conflict} {focused_brief.story_kernel}".casefold()
    if "blackout" in lowered and any(keyword in lowered for keyword in ("succession", "election")):
        return "The Dimmed Accord"
    if "blackout" in lowered:
        return "The Dimmed City"
    if any(keyword in lowered for keyword in ("harbor", "port", "trade", "quarantine")):
        return "The Harbor Compact"
    if any(keyword in lowered for keyword in ("archive", "ledger", "record")):
        return "The Archive Accord"
    return "The Civic Accord"


def _default_story_frame_setting_frame(focused_brief: FocusedBrief) -> str:
    lowered = focused_brief.setting_signal.casefold()
    if "blackout" in lowered and any(keyword in lowered for keyword in ("succession", "election")):
        return "a city plunged into darkness and political limbo"
    if "blackout" in lowered:
        return "a city struggling through blackout and public uncertainty"
    if any(keyword in lowered for keyword in ("harbor", "port", "trade", "quarantine")):
        return "a harbor city strained by quarantine politics and supply fear"
    if any(keyword in lowered for keyword in ("archive", "ledger", "record")):
        return "a city of archives where civic order depends on trusted records"
    return focused_brief.setting_signal


def _default_story_frame_protagonist_mandate(focused_brief: FocusedBrief) -> str:
    lowered = focused_brief.story_kernel.casefold()
    if "mediator" in lowered:
        return "a neutral mediator must coordinate rival factions to keep essential services running"
    if "envoy" in lowered:
        return "an envoy must keep rival institutions negotiating long enough to stop the public breakdown"
    if "inspector" in lowered:
        return "an inspector must keep emergency authority legitimate while the city edges toward fracture"
    return focused_brief.story_kernel


def _default_story_frame_opposition_force(focused_brief: FocusedBrief) -> str:
    lowered = f"{focused_brief.setting_signal} {focused_brief.core_conflict}".casefold()
    if "blackout" in lowered and any(keyword in lowered for keyword in ("succession", "election")):
        return "succession politics and institutional panic turn every delay into leverage"
    if "blackout" in lowered:
        return "fear, scarcity, and procedural drift turn every delay into public fracture"
    if any(keyword in lowered for keyword in ("harbor", "port", "trade", "quarantine")):
        return "trade pressure and quarantine politics keep turning relief into factional leverage"
    return focused_brief.core_conflict


def _default_story_frame_stakes_core(focused_brief: FocusedBrief) -> str:
    lowered = f"{focused_brief.setting_signal} {focused_brief.core_conflict}".casefold()
    if "blackout" in lowered and any(keyword in lowered for keyword in ("succession", "election")):
        return "the city fractures in public and emergency authority hardens into a new order"
    if any(keyword in lowered for keyword in ("archive", "ledger", "record")):
        return "the city loses both legitimacy and the records that make its institutions governable"
    return "the city loses both legitimacy and continuity in public view"


def _stabilize_story_frame_scaffold(
    focused_brief: FocusedBrief,
    scaffold: StoryFrameScaffoldDraft,
) -> StoryFrameScaffoldDraft:
    updates: dict[str, str] = {}
    if _story_frame_text_matches(scaffold.title_seed, focused_brief.story_kernel):
        updates["title_seed"] = _default_story_frame_title_seed(focused_brief)
    if _story_frame_text_matches(scaffold.setting_frame, focused_brief.setting_signal):
        updates["setting_frame"] = _default_story_frame_setting_frame(focused_brief)
    if _story_frame_text_matches(scaffold.protagonist_mandate, focused_brief.story_kernel):
        updates["protagonist_mandate"] = _default_story_frame_protagonist_mandate(focused_brief)
    if (
        _story_frame_text_matches(scaffold.opposition_force, focused_brief.core_conflict)
        or _story_frame_text_matches(scaffold.opposition_force, scaffold.protagonist_mandate)
    ):
        updates["opposition_force"] = _default_story_frame_opposition_force(focused_brief)
    if _story_frame_text_matches(scaffold.stakes_core, focused_brief.core_conflict):
        updates["stakes_core"] = _default_story_frame_stakes_core(focused_brief)
    if not updates:
        return scaffold
    return scaffold.model_copy(update=updates)


def _invoke_story_frame_semantics_with_retries(
    gateway: "AuthorLLMGateway",
    *,
    primary_payload: dict[str, Any],
    final_retry_payload: dict[str, Any],
    prompts: tuple[str, ...],
    previous_response_id: str | None,
    max_output_tokens: int | None,
):
    from rpg_backend.author.gateway import AuthorGatewayError, GatewayStructuredResponse

    retryable_codes = {"llm_invalid_json", "llm_schema_invalid"}
    attempt_prev = previous_response_id
    last_error: Exception | None = None
    for index, prompt in enumerate(prompts):
        payload = primary_payload if index < len(prompts) - 1 else final_retry_payload
        try:
            raw = gateway._invoke_json(
                system_prompt=prompt,
                user_payload=payload,
                max_output_tokens=max_output_tokens,
                previous_response_id=attempt_prev,
                operation_name="story_frame_semantics",
            )
        except AuthorGatewayError as exc:
            last_error = exc
            if exc.code not in retryable_codes or index == len(prompts) - 1:
                raise
            continue
        try:
            scaffold = StoryFrameScaffoldDraft.model_validate(
                _normalize_story_frame_scaffold_payload(gateway, raw.payload)
            )
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
        return GatewayStructuredResponse(value=scaffold, response_id=raw.response_id or attempt_prev)
    if isinstance(last_error, AuthorGatewayError):
        raise last_error
    raise AuthorGatewayError(
        code="llm_schema_invalid",
        message=str(last_error or "story frame semantics generation failed"),
        status_code=502,
    )


def generate_story_frame_semantics(
    gateway: "AuthorLLMGateway",
    focused_brief: FocusedBrief,
    *,
    previous_response_id: str | None = None,
    story_frame_strategy: str | None = None,
):
    from rpg_backend.author.gateway import AuthorGatewayError, GatewayStructuredResponse

    theme_decision = plan_brief_theme(focused_brief)
    resolved_strategy = story_frame_strategy or theme_decision.story_frame_strategy
    payload = {
        "focused_brief": focused_brief.model_dump(mode="json"),
        "theme_hint": {
            "primary_theme": theme_decision.primary_theme,
            "modifiers": list(theme_decision.modifiers),
        },
    }
    final_retry_payload = {
        "focused_brief": focused_brief.model_dump(mode="json"),
        "theme_hint": {
            "primary_theme": theme_decision.primary_theme,
        },
    }
    scaffold_prompt = (
        "You are the Story Frame semantic scaffold generator. Return one strict JSON object matching StoryFrameScaffoldDraft. "
        "Do not output markdown. Keep the world non-graphic and non-sadistic. "
        "Focus on semantic anchors instead of polished prose. "
        "Interpret the focused_brief fields precisely: story_kernel is the protagonist plus immediate mission; "
        "setting_signal is the place, system, and civic situation; core_conflict is the main blocker; "
        "tone_signal is mood and genre only. "
        "Return only: title_seed, setting_frame, protagonist_mandate, opposition_force, stakes_core, tone, world_rules, truths, state_axis_choices, flags. "
        "Use state_axis_choices instead of freeform axes. Allowed template_id values are: "
        "external_pressure, public_panic, political_leverage, resource_strain, system_integrity, ally_trust, exposure_risk, time_window. "
        "Keep title_seed to 2-4 words and keep the other semantic fields concrete and compact. "
        f"{_story_frame_theme_guidance(resolved_strategy)}"
    )
    retry_prompt = (
        "Return only one JSON object matching StoryFrameScaffoldDraft. "
        "No markdown, no explanation, no extra keys. "
        "Use only: title_seed, setting_frame, protagonist_mandate, opposition_force, stakes_core, tone, world_rules, truths, state_axis_choices, flags."
    )
    final_retry_prompt = (
        "Output raw JSON only. Exactly one object matching StoryFrameScaffoldDraft. "
        "Keep all fields short. No prose outside JSON. No code fences. No extra keys."
    )
    scaffold_result = _invoke_story_frame_semantics_with_retries(
        gateway,
        primary_payload=payload,
        final_retry_payload=final_retry_payload,
        prompts=(scaffold_prompt, retry_prompt, final_retry_prompt),
        previous_response_id=previous_response_id,
        max_output_tokens=_story_frame_semantics_output_tokens(gateway, resolved_strategy),
    )
    scaffold = _stabilize_story_frame_scaffold(focused_brief, scaffold_result.value)
    return GatewayStructuredResponse(value=scaffold, response_id=scaffold_result.response_id)


def generate_story_frame(
    gateway: "AuthorLLMGateway",
    focused_brief: FocusedBrief,
    *,
    previous_response_id: str | None = None,
    story_frame_strategy: str | None = None,
):
    from rpg_backend.author.gateway import GatewayStructuredResponse

    semantics = generate_story_frame_semantics(
        gateway,
        focused_brief,
        previous_response_id=previous_response_id,
        story_frame_strategy=story_frame_strategy,
    )
    return GatewayStructuredResponse(
        value=compile_story_frame(focused_brief, semantics.value),
        response_id=semantics.response_id,
    )


def glean_story_frame(
    gateway: "AuthorLLMGateway",
    focused_brief: FocusedBrief,
    partial_story_frame: StoryFrameDraft,
    *,
    previous_response_id: str | None = None,
):
    from rpg_backend.author.gateway import AuthorGatewayError, GatewayStructuredResponse

    payload: dict[str, Any] = {
        "partial_story_frame": partial_story_frame.model_dump(mode="json"),
    }
    if not (gateway.use_session_cache and previous_response_id):
        payload["focused_brief"] = focused_brief.model_dump(mode="json")
    system_prompt = (
        "You are the Story Frame repair generator. Return one strict JSON object matching StoryFrameDraft. "
        "Improve partial_story_frame instead of replacing it wholesale. "
        "Keep any title, premise, or world rule that already fits the story. "
        "Repair generic or repetitive stakes, truths, and world rules so the frame becomes more specific and civic-facing. "
        "Fix malformed punctuation or broken sentence structure when present. "
        "Return a complete StoryFrameDraft."
    )
    raw = gateway._invoke_json(
        system_prompt=system_prompt,
        user_payload=payload,
        max_output_tokens=gateway.max_output_tokens_overview,
        previous_response_id=previous_response_id,
        operation_name="story_frame_glean",
    )
    try:
        return GatewayStructuredResponse(
            value=StoryFrameDraft.model_validate(_normalize_story_frame_payload(gateway, raw.payload)),
            response_id=raw.response_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthorGatewayError(
            code="llm_schema_invalid",
            message=str(exc),
            status_code=502,
        ) from exc
