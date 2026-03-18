from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rpg_backend.author.compiler.router import plan_bundle_theme
from rpg_backend.author.compiler.endings import (
    build_ending_skeleton,
)
from rpg_backend.author.contracts import DesignBundle, EndingAnchorSuggestionDraft
from rpg_backend.author.generation.context import build_author_context_from_bundle
from rpg_backend.author.normalize import normalize_id_list

if TYPE_CHECKING:
    from rpg_backend.author.gateway import AuthorLLMGateway


def _ending_anchor_output_tokens(gateway: "AuthorLLMGateway", primary_theme: str) -> int:
    budget = gateway.max_output_tokens_rulepack
    if budget is None:
        return 980 if primary_theme == "legitimacy_crisis" else 760
    floor = 760
    if primary_theme == "legitimacy_crisis":
        floor = 980
    return max(int(budget), floor)


def _ending_theme_guidance(primary_theme: str) -> str:
    mapping = {
        "legitimacy_crisis": "Bias collapse toward legitimacy failure and public fracture; bias pyrrhic toward visible settlement achieved at civic cost.",
        "logistics_quarantine_crisis": "Bias collapse toward supply rupture and quarantine breach; bias pyrrhic toward restored flow at public cost.",
        "truth_record_crisis": "Bias collapse toward corrupted records and incompatible truths; bias pyrrhic toward proof restored at procedural cost.",
        "public_order_crisis": "Bias collapse toward panic and coercive breakdown; bias pyrrhic toward restored order at visible civic cost.",
        "generic_civic_crisis": "Bias endings toward civic failure versus partial public recovery.",
    }
    return mapping.get(primary_theme, mapping["generic_civic_crisis"])


def _invoke_ending_anchor_with_retry(
    gateway: "AuthorLLMGateway",
    *,
    payload: dict[str, Any],
    prompts: tuple[str, ...],
    previous_response_id: str | None,
    max_output_tokens: int,
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
                operation_name="ending_anchor_generate",
            )
        except AuthorGatewayError as exc:
            last_error = exc
            if exc.code not in retryable_codes or index == len(prompts) - 1:
                raise
            continue
        try:
            value = EndingAnchorSuggestionDraft.model_validate(
                _normalize_ending_anchor_suggestion_payload(gateway, raw.payload)
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
        return GatewayStructuredResponse(value=value, response_id=raw.response_id or attempt_prev)
    if isinstance(last_error, AuthorGatewayError):
        raise last_error
    raise AuthorGatewayError(code="llm_schema_invalid", message=str(last_error or "ending anchor generation failed"), status_code=502)
def _normalize_ending_anchor_suggestion_payload(
    gateway: "AuthorLLMGateway",
    payload: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    seen_ids: set[str] = set()
    for item in list(payload.get("ending_anchor_suggestions") or payload.get("ending_intents") or payload.get("endings") or [])[:6]:
        if not isinstance(item, dict):
            continue
        ending_id = str(item.get("ending_id") or item.get("id") or "").strip()
        if ending_id not in {"collapse", "pyrrhic"} or ending_id in seen_ids:
            continue
        seen_ids.add(ending_id)
        rows.append(
            {
                "ending_id": ending_id,
                "axis_ids": normalize_id_list(
                    item.get("axis_ids") or item.get("axes") or item.get("preferred_axes") or [],
                    limit=2,
                ),
                "required_truth_ids": normalize_id_list(
                    item.get("required_truth_ids") or item.get("truth_ids") or item.get("truths") or [],
                    limit=2,
                ),
                "required_event_ids": normalize_id_list(
                    item.get("required_event_ids") or item.get("event_ids") or item.get("events") or [],
                    limit=2,
                ),
                "required_flag_ids": normalize_id_list(
                    item.get("required_flag_ids") or item.get("flag_ids") or item.get("flags") or [],
                    limit=2,
                ),
            }
        )
    return {"ending_anchor_suggestions": rows[:2]}


def generate_ending_anchor_suggestions(
    gateway: "AuthorLLMGateway",
    design_bundle: DesignBundle,
    *,
    previous_response_id: str | None = None,
):
    theme_decision = plan_bundle_theme(design_bundle)
    context_packet = build_author_context_from_bundle(design_bundle)
    skeleton = build_ending_skeleton(design_bundle)
    collapse = next(item for item in skeleton.ending_intents if item.ending_id == "collapse")
    pyrrhic = next(item for item in skeleton.ending_intents if item.ending_id == "pyrrhic")
    payload = {
        "author_context": context_packet,
        "ending_anchor_seed": {
            "collapse": {
                "axis_ids": collapse.axis_ids,
                "required_truth_ids": collapse.required_truth_ids,
            },
            "pyrrhic": {
                "axis_ids": pyrrhic.axis_ids,
                "required_truth_ids": pyrrhic.required_truth_ids,
                "required_event_ids": pyrrhic.required_event_ids,
                "required_flag_ids": pyrrhic.required_flag_ids,
            },
        },
    }
    system_prompt = (
        "You are the Author Ending Anchor generator. Return one strict JSON object matching EndingAnchorSuggestionDraft. "
        "Return only anchor suggestions for collapse and pyrrhic. "
        "Do not generate mixed. Do not generate thresholds or final conditions. "
        "Use only axis, truth, event, and flag ids that already exist in author_context. "
        "Required top-level key: ending_anchor_suggestions. "
        "Keep the output terse, id-based, deterministic-friendly, and non-graphic. "
        f"{_ending_theme_guidance(theme_decision.primary_theme)}"
    )
    retry_prompt = (
        "Return only one JSON object matching EndingAnchorSuggestionDraft. "
        "No markdown, no explanation, no extra keys. "
        "Only collapse and pyrrhic suggestions are allowed."
    )
    final_retry_prompt = (
        "Output raw JSON only. Exactly one object with key ending_anchor_suggestions. "
        "Each suggestion may only contain ending_id, axis_ids, required_truth_ids, required_event_ids, required_flag_ids."
    )
    return _invoke_ending_anchor_with_retry(
        gateway,
        payload=payload,
        prompts=(system_prompt, retry_prompt, final_retry_prompt),
        previous_response_id=previous_response_id,
        max_output_tokens=_ending_anchor_output_tokens(gateway, theme_decision.primary_theme),
    )


def glean_ending_anchor_suggestions(
    gateway: "AuthorLLMGateway",
    design_bundle: DesignBundle,
    partial_ending_anchor_suggestions: EndingAnchorSuggestionDraft,
    *,
    previous_response_id: str | None = None,
):
    theme_decision = plan_bundle_theme(design_bundle)
    context_packet = build_author_context_from_bundle(design_bundle)
    payload = {
        "author_context": context_packet,
        "partial_ending_anchor_suggestions": partial_ending_anchor_suggestions.model_dump(mode="json"),
    }
    system_prompt = (
        "You are the Author Ending Anchor repair generator. Return one strict JSON object matching EndingAnchorSuggestionDraft. "
        "Improve partial_ending_anchor_suggestions instead of replacing it wholesale. "
        "Keep any valid collapse/pyrrhic anchors that already fit. "
        "Only return collapse and pyrrhic anchor suggestions. "
        "Do not generate mixed and do not generate thresholds or final conditions. "
        f"{_ending_theme_guidance(theme_decision.primary_theme)}"
    )
    retry_prompt = (
        "Return only one JSON object matching EndingAnchorSuggestionDraft. "
        "No markdown, no explanation, no extra keys. "
        "Repair only collapse and pyrrhic suggestions."
    )
    final_retry_prompt = (
        "Output raw JSON only. Exactly one object with key ending_anchor_suggestions. "
        "Each suggestion may only contain ending_id, axis_ids, required_truth_ids, required_event_ids, required_flag_ids."
    )
    return _invoke_ending_anchor_with_retry(
        gateway,
        payload=payload,
        prompts=(system_prompt, retry_prompt, final_retry_prompt),
        previous_response_id=previous_response_id,
        max_output_tokens=_ending_anchor_output_tokens(gateway, theme_decision.primary_theme),
    )
