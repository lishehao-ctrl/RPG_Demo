from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from openai import OpenAI

from rpg_backend.author.contracts import (
    AuthorContextPacket,
    BeatPlanDraft,
    CastDraft,
    CastOverviewDraft,
    ContextAxisSummary,
    ContextBeatSummary,
    ContextCastSummary,
    ContextTruthSummary,
    DesignBundle,
    EndingRulesDraft,
    FocusedBrief,
    RouteOpportunityPlanDraft,
    RouteAffordancePackDraft,
    RulePack,
    StoryFrameDraft,
    StoryOverviewDraft,
)
from rpg_backend.config import Settings, get_settings

ALLOWED_AFFORDANCE_TAGS = {
    "reveal_truth",
    "build_trust",
    "contain_chaos",
    "shift_public_narrative",
    "protect_civilians",
    "secure_resources",
    "unlock_ally",
    "pay_cost",
}
VALID_STORY_FUNCTIONS = {
    "advance",
    "reveal",
    "stabilize",
    "detour",
    "pay_cost",
}
T = TypeVar("T")


class AuthorGatewayError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class GatewayJSONResponse:
    payload: dict[str, Any]
    response_id: str | None


@dataclass(frozen=True)
class GatewayStructuredResponse(Generic[T]):
    value: T
    response_id: str | None


@dataclass(frozen=True)
class AuthorLLMGateway:
    client: OpenAI
    model: str
    timeout_seconds: float
    max_output_tokens_overview: int | None
    max_output_tokens_beat_plan: int | None
    max_output_tokens_rulepack: int | None
    use_session_cache: bool = False

    def _invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        max_output_tokens: int | None,
        previous_response_id: str | None = None,
    ) -> GatewayJSONResponse:
        user_text = json.dumps(user_payload, ensure_ascii=False, sort_keys=True)
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system_prompt,
            "input": user_text,
            "max_output_tokens": max_output_tokens,
            "timeout": self.timeout_seconds,
            "temperature": 0.2,
            "extra_body": {"enable_thinking": False},
        }
        if self.use_session_cache and previous_response_id:
            request_kwargs["previous_response_id"] = previous_response_id
        try:
            response = self.client.responses.create(**request_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_provider_failed",
                message=str(exc),
                status_code=502,
            ) from exc

        try:
            content = response.output_text
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_invalid_response",
                message="provider response did not include message content",
                status_code=502,
            ) from exc

        text = str(content or "").strip()
        if not text:
            raise AuthorGatewayError(
                code="llm_invalid_json",
                message="provider returned empty content",
                status_code=502,
            )

        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

        try:
            payload = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_invalid_json",
                message=str(exc),
                status_code=502,
            ) from exc
        if not isinstance(payload, dict):
            raise AuthorGatewayError(
                code="llm_invalid_json",
                message="provider returned a non-object JSON payload",
                status_code=502,
            )
        return GatewayJSONResponse(
            payload=payload,
            response_id=getattr(response, "id", None),
        )

    @staticmethod
    def _trim_text(value: Any, limit: int) -> Any:
        if not isinstance(value, str):
            return value
        text = " ".join(value.strip().split())
        if len(text) <= limit:
            return text
        clipped = text[: limit + 1]
        for separator in (". ", "; ", ", "):
            idx = clipped.rfind(separator)
            if idx >= max(24, limit // 3):
                return clipped[: idx + 1].strip()
        return text[:limit].rstrip(" ,;")

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value or "").strip().casefold()
        if not text:
            return default
        mappings = {
            "low": 1,
            "medium": 2,
            "moderate": 2,
            "high": 3,
            "critical": 4,
            "severe": 4,
        }
        if text in mappings:
            return mappings[text]
        try:
            return int(float(text))
        except Exception:  # noqa: BLE001
            return default

    @staticmethod
    def _unique_preserve(items: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            lowered = item.casefold()
            if not item or lowered in seen:
                continue
            seen.add(lowered)
            ordered.append(item)
        return ordered

    @staticmethod
    def _normalize_affordance_tag(value: Any) -> str:
        text = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
        mapping = {
            "reveal": "reveal_truth",
            "investigate": "reveal_truth",
            "dialogue": "build_trust",
            "trust": "build_trust",
            "community_gathering": "build_trust",
            "oral_testimony": "shift_public_narrative",
            "manual_ledger": "secure_resources",
            "calm": "contain_chaos",
            "resolution": "contain_chaos",
            "storytelling": "shift_public_narrative",
            "celebration": "build_trust",
            "hope": "build_trust",
            "resource_management": "secure_resources",
            "teamwork": "unlock_ally",
            "transparent_audit": "reveal_truth",
            "negotiated_compromise": "build_trust",
            "collective_action": "unlock_ally",
            "future_planning": "pay_cost",
        }
        normalized = mapping.get(text, text)
        if normalized not in ALLOWED_AFFORDANCE_TAGS:
            return "build_trust"
        return normalized

    @classmethod
    def _default_story_function_for_tag(cls, tag: str) -> str:
        normalized = cls._normalize_affordance_tag(tag)
        if "reveal" in normalized or "investigate" in normalized:
            return "reveal"
        if "chaos" in normalized or "protect" in normalized:
            return "stabilize"
        if "cost" in normalized:
            return "pay_cost"
        return "advance"

    @classmethod
    def _normalize_story_function(cls, value: Any, affordance_tag: str) -> str:
        text = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
        if text in VALID_STORY_FUNCTIONS:
            return text
        return cls._default_story_function_for_tag(affordance_tag)

    def _normalize_story_frame_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        normalized["title"] = self._trim_text(normalized.get("title") or "Untitled Crisis", 120)
        normalized["premise"] = self._trim_text(normalized.get("premise") or "A city under pressure must decide what still holds it together.", 320)
        normalized["tone"] = self._trim_text(normalized.get("tone") or "hopeful civic fantasy", 120)
        normalized["stakes"] = self._trim_text(normalized.get("stakes") or "If the coalition fails, the city loses both legitimacy and continuity.", 240)
        normalized["style_guard"] = self._trim_text(
            normalized.get("style_guard")
            or "Keep the story tense, readable, and grounded in civic consequence rather than spectacle.",
            220,
        )

        world_rules = [
            self._trim_text(item, 180)
            for item in list(normalized.get("world_rules") or [])[:5]
            if isinstance(item, str) and self._trim_text(item, 180)
        ]
        world_rules = self._unique_preserve(world_rules)
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
            text = self._trim_text(item.get("text"), 220)
            if not text:
                continue
            truths.append(
                {
                    "text": text,
                    "importance": item.get("importance") or "core",
                }
            )
        truths = self._unique_preserve([json.dumps(item, ensure_ascii=False, sort_keys=True) for item in truths])
        normalized_truths = [json.loads(item) for item in truths]
        if len(normalized_truths) < 2:
            normalized_truths.extend(
                [
                    {"text": self._trim_text(normalized["premise"], 220), "importance": "core"},
                    {"text": self._trim_text(normalized["stakes"], 220), "importance": "core"},
                ][len(normalized_truths) :]
            )
        normalized["truths"] = normalized_truths[:6]

        axis_choices = []
        raw_axis_items = list(normalized.get("state_axis_choices") or normalized.get("axes") or [])[:5]
        for item in raw_axis_items:
            if not isinstance(item, dict):
                continue
            label_text = self._trim_text(item.get("story_label") or item.get("label") or "State Axis", 80)
            axis_choices.append(
                {
                    "template_id": item.get("template_id") or "external_pressure",
                    "story_label": label_text,
                    "starting_value": max(0, min(3, self._coerce_int(item.get("starting_value", 0), 0))),
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
            label = self._trim_text(item.get("label"), 80)
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

    def _build_author_context_from_story(
        self,
        story_frame: StoryFrameDraft,
        cast_draft: CastDraft,
    ) -> AuthorContextPacket:
        return AuthorContextPacket(
            title=story_frame.title,
            premise=story_frame.premise,
            tone=story_frame.tone,
            stakes=story_frame.stakes,
            style_guard=story_frame.style_guard,
            world_rules=story_frame.world_rules,
            truths=[
                ContextTruthSummary(text=item.text)
                for item in story_frame.truths
            ],
            cast=[
                ContextCastSummary(
                    name=item.name,
                    role=item.role,
                    agenda=item.agenda,
                    pressure_signature=item.pressure_signature,
                )
                for item in cast_draft.cast
            ],
            axes=[
                ContextAxisSummary(
                    axis_id=item.template_id,
                    label=item.story_label,
                    kind=None,
                    starting_value=item.starting_value,
                )
                for item in story_frame.state_axis_choices
            ],
            flags=[item.label for item in story_frame.flags],
            beats=[],
        )

    def _build_author_context_from_bundle(self, design_bundle: DesignBundle) -> AuthorContextPacket:
        return AuthorContextPacket(
            title=design_bundle.story_bible.title,
            premise=design_bundle.story_bible.premise,
            tone=design_bundle.story_bible.tone,
            stakes=design_bundle.story_bible.stakes,
            style_guard=design_bundle.story_bible.style_guard,
            world_rules=design_bundle.story_bible.world_rules,
            truths=[
                ContextTruthSummary(
                    truth_id=item.truth_id,
                    text=item.text,
                )
                for item in design_bundle.story_bible.truth_catalog
            ],
            cast=[
                ContextCastSummary(
                    name=item.name,
                    role=item.role,
                    agenda=item.agenda,
                    pressure_signature=item.pressure_signature,
                )
                for item in design_bundle.story_bible.cast
            ],
            axes=[
                ContextAxisSummary(
                    axis_id=item.axis_id,
                    label=item.label,
                    kind=item.kind,
                    starting_value=item.starting_value,
                )
                for item in design_bundle.state_schema.axes
            ],
            flags=[item.flag_id for item in design_bundle.state_schema.flags],
            beats=[
                ContextBeatSummary(
                    beat_id=item.beat_id,
                    title=item.title,
                    goal=item.goal,
                    focus_names=item.focus_npcs,
                    required_truths=item.required_truths,
                    required_events=item.required_events,
                    affordance_tags=[weight.tag for weight in item.affordances],
                )
                for item in design_bundle.beat_spine
            ],
        )

    def _normalize_cast_overview_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        slot_items = []
        for item in list(normalized.get("cast_slots") or normalized.get("roles") or normalized.get("cast") or [])[:5]:
            if not isinstance(item, dict):
                continue
            slot_label = self._trim_text(item.get("slot_label") or item.get("label") or item.get("name") or "Civic Role", 80)
            public_role = self._trim_text(item.get("public_role") or item.get("role") or "Stakeholder", 120)
            slot_items.append(
                {
                    "slot_label": slot_label,
                    "public_role": public_role,
                    "relationship_to_protagonist": self._trim_text(
                        item.get("relationship_to_protagonist") or item.get("relationship") or "Complicates or supports the protagonist under pressure.",
                        180,
                    ),
                    "agenda_anchor": self._trim_text(
                        item.get("agenda_anchor") or item.get("agenda") or f"{slot_label} tries to protect their institutional stake while the crisis unfolds.",
                        220,
                    ),
                    "red_line_anchor": self._trim_text(
                        item.get("red_line_anchor") or item.get("red_line") or f"{slot_label} will not accept being cut out of the settlement.",
                        220,
                    ),
                    "pressure_vector": self._trim_text(
                        item.get("pressure_vector") or item.get("pressure_signature") or f"{slot_label} pushes harder for leverage as public pressure rises.",
                        220,
                    ),
                }
            )
        unique_slots = []
        seen_labels: set[str] = set()
        for item in slot_items:
            lowered = item["slot_label"].casefold()
            if lowered in seen_labels:
                continue
            seen_labels.add(lowered)
            unique_slots.append(item)
        while len(unique_slots) < 3:
            index = len(unique_slots) + 1
            unique_slots.append(
                {
                    "slot_label": f"Civic Role {index}",
                    "public_role": "Stakeholder",
                    "relationship_to_protagonist": "Complicates or supports the protagonist under pressure.",
                    "agenda_anchor": "Protect their institutional stake while the crisis unfolds.",
                    "red_line_anchor": "Will not accept being cut out of the settlement.",
                    "pressure_vector": "Pushes harder for leverage as public pressure rises.",
                }
            )
        relationship_summary = [
            self._trim_text(item, 180)
            for item in list(normalized.get("relationship_summary") or normalized.get("relationships") or [])[:6]
            if self._trim_text(item, 180)
        ]
        relationship_summary = self._unique_preserve(relationship_summary)
        if len(relationship_summary) < 2:
            relationship_summary = [
                f"{unique_slots[0]['slot_label']} and {unique_slots[1]['slot_label']} need each other but disagree on procedure.",
                f"{unique_slots[2]['slot_label']} gains leverage whenever public pressure rises.",
            ][: max(2, len(relationship_summary))]
        normalized["cast_slots"] = unique_slots[:5]
        normalized["relationship_summary"] = relationship_summary[:6]
        return normalized

    def _normalize_cast_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        cast_items = []
        for item in list(normalized.get("cast") or [])[:5]:
            if not isinstance(item, dict):
                continue
            name = self._trim_text(item.get("name") or "Unnamed Figure", 80)
            role = self._trim_text(item.get("role") or "Civic actor", 120)
            cast_items.append(
                {
                    "name": name,
                    "role": role,
                    "agenda": self._trim_text(item.get("agenda") or f"{name} tries to preserve their role in the crisis.", 220),
                    "red_line": self._trim_text(item.get("red_line") or f"{name} will not lose public legitimacy without resistance.", 220),
                    "pressure_signature": self._trim_text(
                        item.get("pressure_signature") or f"{name} reacts sharply when pressure threatens public order.",
                        220,
                    ),
                }
            )
        unique_cast = []
        seen_names: set[str] = set()
        for item in cast_items:
            lowered = item["name"].casefold()
            if lowered in seen_names:
                continue
            seen_names.add(lowered)
            unique_cast.append(item)
        while len(unique_cast) < 3:
            index = len(unique_cast) + 1
            unique_cast.append(
                {
                    "name": f"Civic Figure {index}",
                    "role": "Stakeholder",
                    "agenda": "Protect their corner of the city during the crisis.",
                    "red_line": "Will not accept total collapse without resistance.",
                    "pressure_signature": "Pushes for quick action whenever the public mood worsens.",
                }
            )
        return {"cast": unique_cast[:5]}

    def _normalize_cast_member_payload(
        self,
        payload: dict[str, Any],
        *,
        slot_label: str,
        public_role: str,
        agenda_anchor: str,
        red_line_anchor: str,
        pressure_vector: str,
    ) -> dict[str, Any]:
        source = payload.get("member") if isinstance(payload.get("member"), dict) else payload
        if not isinstance(source, dict):
            source = {}
        name = self._trim_text(source.get("name") or slot_label, 80)
        role = self._trim_text(source.get("role") or public_role, 120)
        return {
            "name": name,
            "role": role,
            "agenda": self._trim_text(source.get("agenda") or agenda_anchor, 220),
            "red_line": self._trim_text(source.get("red_line") or red_line_anchor, 220),
            "pressure_signature": self._trim_text(source.get("pressure_signature") or pressure_vector, 220),
        }

    def _normalize_beat_plan_payload(
        self,
        payload: dict[str, Any],
        *,
        story_frame: StoryFrameDraft,
        cast_draft: CastDraft,
    ) -> dict[str, Any]:
        normalized = dict(payload)
        cast_names = [item.name for item in cast_draft.cast]
        truth_texts = [item.text for item in story_frame.truths]
        default_tags = [
            "reveal_truth",
            "build_trust",
            "contain_chaos",
            "shift_public_narrative",
            "pay_cost",
        ]

        beats = []
        for index, item in enumerate(list(normalized.get("beats") or [])[:4], start=1):
            if not isinstance(item, dict):
                continue
            focus_names = [self._trim_text(name, 80) for name in list(item.get("focus_names") or [])[:3]]
            focus_names = [name for name in focus_names if name in cast_names]
            if not focus_names and cast_names:
                focus_names = [cast_names[min(index - 1, len(cast_names) - 1)]]

            required_truths = [
                self._trim_text(text, 220)
                for text in list(item.get("required_truth_texts") or [])[:3]
                if self._trim_text(text, 220) in truth_texts
            ]
            if not required_truths and truth_texts:
                required_truths = [truth_texts[min(index - 1, len(truth_texts) - 1)]]

            affordance_tags = self._unique_preserve(
                [self._normalize_affordance_tag(tag) for tag in list(item.get("affordance_tags") or [])[:6]]
            )
            for fallback_tag in default_tags:
                if len(affordance_tags) >= 2:
                    break
                if fallback_tag not in affordance_tags:
                    affordance_tags.append(fallback_tag)

            blocked_affordances = self._unique_preserve(
                [self._normalize_affordance_tag(tag) for tag in list(item.get("blocked_affordances") or [])[:4]]
            )
            blocked_affordances = [tag for tag in blocked_affordances if tag not in affordance_tags]

            beats.append(
                {
                    "title": self._trim_text(item.get("title") or f"Beat {index}", 120),
                    "goal": self._trim_text(
                        item.get("goal") or "Push the story toward a decisive civic turning point.",
                        220,
                    ),
                    "focus_names": focus_names[:3],
                    "required_truth_texts": required_truths[:3],
                    "detour_budget": max(0, min(2, self._coerce_int(item.get("detour_budget", 1), 1))),
                    "progress_required": max(1, min(3, self._coerce_int(item.get("progress_required", 2), 2))),
                    "return_hooks": [
                        self._trim_text(text, 180)
                        for text in list(item.get("return_hooks") or [])[:3]
                        if self._trim_text(text, 180)
                    ]
                    or ["A visible public consequence forces the next move."],
                    "affordance_tags": affordance_tags[:6],
                    "blocked_affordances": blocked_affordances[:4],
                }
            )

        while len(beats) < 2:
            index = len(beats) + 1
            focus_name = cast_names[min(index - 1, len(cast_names) - 1)] if cast_names else "The Mediator"
            truth_text = truth_texts[min(index - 1, len(truth_texts) - 1)] if truth_texts else story_frame.premise
            beats.append(
                {
                    "title": f"Beat {index}",
                    "goal": "Keep the civic crisis moving toward a decisive resolution.",
                    "focus_names": [focus_name],
                    "required_truth_texts": [truth_text],
                    "detour_budget": 1 if index == 1 else 0,
                    "progress_required": 2,
                    "return_hooks": ["A visible consequence forces the issue."],
                    "affordance_tags": ["reveal_truth", "build_trust"],
                    "blocked_affordances": [],
                }
            )
        return {"beats": beats[:4]}

    def _normalize_condition_payload(self, conditions: Any) -> dict[str, Any]:
        if not isinstance(conditions, dict):
            conditions = {}
        return {
            "required_events": [str(conditions.get("event")).strip()] if conditions.get("event") else list(conditions.get("required_events") or []),
            "required_truths": list(conditions.get("required_truths") or []),
            "required_flags": list(conditions.get("required_flags") or []),
            "min_axes": {str(k): self._coerce_int(v, 0) for k, v in dict(conditions.get("min_axes") or {}).items()},
            "max_axes": {str(k): self._coerce_int(v, 0) for k, v in dict(conditions.get("max_axes") or {}).items()},
            "min_stances": {str(k): self._coerce_int(v, 0) for k, v in dict(conditions.get("min_stances") or {}).items()},
        }

    @staticmethod
    def _bundle_affordance_tags(bundle: DesignBundle) -> list[str]:
        tags = sorted({item.tag for beat in bundle.beat_spine for item in beat.affordances})
        if len(tags) < 2:
            for fallback_tag in ("reveal_truth", "build_trust"):
                if fallback_tag not in tags:
                    tags.append(fallback_tag)
                if len(tags) >= 2:
                    break
        return tags

    def _default_route_trigger_payload(self, bundle: DesignBundle, beat_index: int) -> dict[str, Any]:
        beat = bundle.beat_spine[beat_index]
        if beat.required_truths:
            return {"kind": "truth", "target_id": beat.required_truths[0]}
        if beat_index > 0 and bundle.beat_spine[beat_index - 1].required_events:
            return {"kind": "event", "target_id": bundle.beat_spine[beat_index - 1].required_events[0]}
        if bundle.state_schema.flags:
            return {"kind": "flag", "target_id": bundle.state_schema.flags[0].flag_id}
        if bundle.state_schema.axes:
            return {"kind": "axis", "target_id": bundle.state_schema.axes[0].axis_id, "min_value": 2}
        if bundle.state_schema.stances:
            return {"kind": "stance", "target_id": bundle.state_schema.stances[0].stance_id, "min_value": 1}
        return {"kind": "event", "target_id": beat.required_events[0] if beat.required_events else f"{beat.beat_id}.milestone"}

    def _normalize_route_opportunity_plan_payload(self, payload: dict[str, Any], bundle: DesignBundle) -> dict[str, Any]:
        normalized = dict(payload)
        beats_by_id = {beat.beat_id: beat for beat in bundle.beat_spine}
        beat_order = [beat.beat_id for beat in bundle.beat_spine]
        fallback_beat_id = beat_order[0] if beat_order else "b1"
        affordance_by_beat = {
            beat.beat_id: [item.tag for item in beat.affordances]
            for beat in bundle.beat_spine
        }
        axis_ids = {axis.axis_id for axis in bundle.state_schema.axes}
        stance_ids = {stance.stance_id for stance in bundle.state_schema.stances}
        flag_ids = {flag.flag_id for flag in bundle.state_schema.flags}
        truth_ids = {truth.truth_id for truth in bundle.story_bible.truth_catalog}
        event_ids = {event for beat in bundle.beat_spine for event in beat.required_events}

        opportunities = []
        for item in list(normalized.get("opportunities") or normalized.get("route_opportunities") or [])[:8]:
            if not isinstance(item, dict):
                continue
            beat_id = str(item.get("beat_id") or item.get("target") or "").strip()
            if beat_id not in beats_by_id:
                beat_id = fallback_beat_id
            beat_index = beat_order.index(beat_id) if beat_id in beat_order else 0
            unlock_tag = self._normalize_affordance_tag(
                item.get("unlock_affordance_tag") or item.get("affordance_tag") or affordance_by_beat.get(beat_id, ["build_trust"])[0]
            )
            trigger_rows = []
            for trigger in list(item.get("triggers") or [])[:2]:
                if not isinstance(trigger, dict):
                    continue
                kind = str(trigger.get("kind") or trigger.get("type") or "").strip().casefold()
                kind = {
                    "required_truth": "truth",
                    "truth_id": "truth",
                    "min_axis": "axis",
                    "axis_id": "axis",
                    "min_stance": "stance",
                    "stance_id": "stance",
                    "required_flag": "flag",
                    "flag_id": "flag",
                    "required_event": "event",
                    "event_id": "event",
                }.get(kind, kind)
                target_id = str(trigger.get("target_id") or trigger.get("id") or trigger.get("ref") or "").strip()
                min_value = self._coerce_int(trigger.get("min_value"), 0)
                if kind == "truth" and target_id in truth_ids:
                    trigger_rows.append({"kind": "truth", "target_id": target_id})
                elif kind == "axis" and target_id in axis_ids:
                    trigger_rows.append({"kind": "axis", "target_id": target_id, "min_value": max(1, min(5, min_value or 2))})
                elif kind == "stance" and target_id in stance_ids:
                    trigger_rows.append({"kind": "stance", "target_id": target_id, "min_value": max(1, min(3, min_value or 1))})
                elif kind == "flag" and target_id in flag_ids:
                    trigger_rows.append({"kind": "flag", "target_id": target_id})
                elif kind == "event" and target_id in event_ids:
                    trigger_rows.append({"kind": "event", "target_id": target_id})
            if not trigger_rows:
                trigger_rows.append(self._default_route_trigger_payload(bundle, beat_index))
            opportunities.append(
                {
                    "beat_id": beat_id,
                    "unlock_route_id": str(item.get("unlock_route_id") or item.get("route_id") or f"{beat_id}_{unlock_tag}_route").strip(),
                    "unlock_affordance_tag": unlock_tag,
                    "triggers": trigger_rows[:2],
                }
            )
        normalized["opportunities"] = opportunities
        normalized.pop("route_opportunities", None)
        return normalized

    def _normalize_route_affordance_payload(self, payload: dict[str, Any], bundle: DesignBundle) -> dict[str, Any]:
        normalized = dict(payload)
        beat_ids = {beat.beat_id for beat in bundle.beat_spine}
        fallback_beat_id = sorted(beat_ids)[0] if beat_ids else "b1"
        affordance_tags = self._bundle_affordance_tags(bundle)
        affordance_by_beat = {beat.beat_id: [item.tag for item in beat.affordances] for beat in bundle.beat_spine}

        route_unlock_rules = []
        for item in list(normalized.get("route_unlock_rules") or [])[:8]:
            if not isinstance(item, dict):
                continue
            beat_id = str(item.get("beat_id") or item.get("target") or "").strip()
            if beat_id not in beat_ids:
                beat_id = fallback_beat_id
            unlock_tag = self._normalize_affordance_tag(
                item.get("unlock_affordance_tag") or item.get("affordance_tag") or affordance_by_beat.get(beat_id, ["build_trust"])[0]
            )
            route_unlock_rules.append(
                {
                    "rule_id": str(item.get("rule_id") or f"{beat_id}_unlock").strip(),
                    "beat_id": beat_id,
                    "conditions": self._normalize_condition_payload(item.get("conditions") or item.get("condition") or {}),
                    "unlock_route_id": str(item.get("unlock_route_id") or item.get("target") or item.get("rule_id") or beat_id).strip(),
                    "unlock_affordance_tag": unlock_tag,
                }
            )
        normalized["route_unlock_rules"] = route_unlock_rules

        profile_by_tag: dict[str, dict[str, Any]] = {}
        for item in list(normalized.get("affordance_effect_profiles") or [])[:12]:
            if not isinstance(item, dict):
                continue
            affordance_tag = self._normalize_affordance_tag(item.get("affordance_tag") or item.get("tag"))
            profile_by_tag[affordance_tag] = {
                "affordance_tag": affordance_tag,
                "default_story_function": self._normalize_story_function(
                    item.get("default_story_function") or item.get("story_function"),
                    affordance_tag,
                ),
                "axis_deltas": {str(k): self._coerce_int(v, 0) for k, v in dict(item.get("axis_deltas") or {}).items()},
                "stance_deltas": {str(k): self._coerce_int(v, 0) for k, v in dict(item.get("stance_deltas") or {}).items()},
                "can_add_truth": bool(item.get("can_add_truth", False)),
                "can_add_event": bool(item.get("can_add_event", False)),
            }
        for affordance_tag in affordance_tags:
            profile_by_tag.setdefault(
                affordance_tag,
                {
                    "affordance_tag": affordance_tag,
                    "default_story_function": self._default_story_function_for_tag(affordance_tag),
                    "axis_deltas": {},
                    "stance_deltas": {},
                    "can_add_truth": self._default_story_function_for_tag(affordance_tag) == "reveal",
                    "can_add_event": self._default_story_function_for_tag(affordance_tag) in {"advance", "pay_cost"},
                },
            )
        normalized["affordance_effect_profiles"] = [profile_by_tag[tag] for tag in affordance_tags][:12]
        return normalized

    def _normalize_ending_rules_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        ending_rules = []
        seen_ids: set[str] = set()
        for item in list(normalized.get("ending_rules") or [])[:6]:
            if not isinstance(item, dict):
                continue
            ending_id = str(item.get("ending_id") or "mixed").strip()
            if ending_id in seen_ids:
                continue
            seen_ids.add(ending_id)
            ending_rules.append(
                {
                    "ending_id": ending_id,
                    "priority": self._coerce_int(item.get("priority"), 100),
                    "conditions": self._normalize_condition_payload(item.get("conditions") or item.get("condition") or {}),
                }
            )
        if not ending_rules:
            ending_rules = [{"ending_id": "mixed", "priority": 100, "conditions": {}}]
        normalized["ending_rules"] = ending_rules
        return normalized

    def _normalize_rulepack_payload(self, payload: dict[str, Any], bundle: DesignBundle) -> dict[str, Any]:
        route_affordance_payload = self._normalize_route_affordance_payload(payload, bundle)
        ending_rules_payload = self._normalize_ending_rules_payload(payload)
        return {
            "route_unlock_rules": route_affordance_payload["route_unlock_rules"],
            "ending_rules": ending_rules_payload["ending_rules"],
            "affordance_effect_profiles": route_affordance_payload["affordance_effect_profiles"],
        }

    def generate_story_frame(
        self,
        focused_brief: FocusedBrief,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        payload = {"focused_brief": focused_brief.model_dump(mode="json")}
        system_prompt = (
            "You are the Story Frame generator. Return one strict JSON object matching StoryFrameDraft. "
            "Do not output markdown. Keep the world non-graphic and non-sadistic. "
            "Interpret the focused_brief fields precisely: story_kernel is the protagonist plus immediate mission; "
            "setting_signal is the place, system, and civic situation; core_conflict is the main blocker; "
            "tone_signal is mood and genre only. "
            "Return only: title, premise, tone, stakes, style_guard, world_rules, truths, state_axis_choices, flags. "
            "Use state_axis_choices instead of freeform axes. Allowed template_id values are: "
            "external_pressure, public_panic, political_leverage, resource_strain, system_integrity, ally_trust, exposure_risk, time_window. "
            "Write concise design language, not scene prose."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=StoryFrameDraft.model_validate(self._normalize_story_frame_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def glean_story_frame(
        self,
        focused_brief: FocusedBrief,
        partial_story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[StoryFrameDraft]:
        payload: dict[str, Any] = {
            "partial_story_frame": partial_story_frame.model_dump(mode="json"),
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the Story Frame repair generator. Return one strict JSON object matching StoryFrameDraft. "
            "Improve partial_story_frame instead of replacing it wholesale. "
            "Keep any title, premise, or world rule that already fits the story. "
            "Repair generic or repetitive stakes, truths, and world rules so the frame becomes more specific and civic-facing. "
            "Return a complete StoryFrameDraft."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=StoryFrameDraft.model_validate(self._normalize_story_frame_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_cast_overview(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastOverviewDraft]:
        payload: dict[str, Any] = {
            "story_frame": story_frame.model_dump(mode="json"),
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the Cast Overview generator. Return one strict JSON object matching CastOverviewDraft. "
            "Do not output markdown. "
            "Design 3-5 cast slots that describe the broad social and conflict structure before character specifics are written. "
            "Each cast slot must include: slot_label, public_role, relationship_to_protagonist, agenda_anchor, red_line_anchor, pressure_vector. "
            "Keep the slots distinct in function and pressure behavior. "
            "Also return 2-6 relationship_summary lines that explain the broad conflict web across the cast."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=CastOverviewDraft.model_validate(self._normalize_cast_overview_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def glean_cast_overview(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        partial_cast_overview: CastOverviewDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastOverviewDraft]:
        payload: dict[str, Any] = {
            "story_frame": story_frame.model_dump(mode="json"),
            "partial_cast_overview": partial_cast_overview.model_dump(mode="json"),
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the Cast Overview repair generator. Return one strict JSON object matching CastOverviewDraft. "
            "Improve the existing partial_cast_overview instead of replacing it wholesale. "
            "Keep any specific useful slot labels, roles, and relationship structure that already fit the story. "
            "Replace placeholder or generic slot text with sharper conflict structure. "
            "Return a complete CastOverviewDraft with 3-5 cast slots and 2-6 relationship_summary lines."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=CastOverviewDraft.model_validate(self._normalize_cast_overview_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_story_cast(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_overview: CastOverviewDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastDraft]:
        payload: dict[str, Any] = {
            "story_frame": story_frame.model_dump(mode="json"),
            "cast_overview": cast_overview.model_dump(mode="json"),
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the NPC Ensemble generator. Return one strict JSON object matching CastDraft. "
            "Do not output markdown. Design 3-5 named civic actors with distinct agendas, red lines, and pressure signatures. "
            "Use cast_overview as a binding scaffold: keep one character per cast slot and preserve each slot's conflict function. "
            "Keep them specific to the existing story frame rather than generic archetypes. "
            "Agendas should realize agenda_anchor, red_line should realize red_line_anchor, "
            "and pressure_signature should realize pressure_vector in concrete character language."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=CastDraft.model_validate(self._normalize_cast_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, Any],
        existing_cast: list[dict[str, Any]],
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[Any]:
        payload: dict[str, Any] = {
            "story_frame": story_frame.model_dump(mode="json"),
            "cast_slot": cast_slot,
            "existing_cast": existing_cast,
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the NPC generator. Return one strict JSON object matching OverviewCastDraft. "
            "Do not output markdown. Write exactly one named civic actor for the given cast_slot. "
            "The character must preserve the slot's public_role, archetype, and conflict function, but become a concrete person. "
            "The new character must differ from existing_cast in leverage source, tactic, and pressure behavior. "
            "Avoid placeholder names and generic crisis boilerplate. "
            "Do not use the slot label or public role as the character name. "
            "Use cast_slot.counter_trait and cast_slot.pressure_tell to make the person feel specific."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            from rpg_backend.author.contracts import OverviewCastDraft

            slot = cast_slot
            return GatewayStructuredResponse(
                value=OverviewCastDraft.model_validate(
                    self._normalize_cast_member_payload(
                        raw.payload,
                        slot_label=str(slot.get("slot_label") or "Civic Role"),
                        public_role=str(slot.get("public_role") or "Stakeholder"),
                        agenda_anchor=str(slot.get("agenda_anchor") or "Protect their institutional stake while the crisis unfolds."),
                        red_line_anchor=str(slot.get("red_line_anchor") or "Will not accept being cut out of the settlement."),
                        pressure_vector=str(slot.get("pressure_vector") or "Pushes harder for leverage as public pressure rises."),
                    )
                ),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def glean_story_cast_member(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_slot: dict[str, Any],
        existing_cast: list[dict[str, Any]],
        partial_member: dict[str, Any],
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[Any]:
        payload: dict[str, Any] = {
            "story_frame": story_frame.model_dump(mode="json"),
            "cast_slot": cast_slot,
            "existing_cast": existing_cast,
            "partial_member": partial_member,
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the NPC repair generator. Return one strict JSON object matching OverviewCastDraft. "
            "Improve partial_member instead of replacing it wholesale. "
            "Preserve any good name or role if they fit the cast_slot. "
            "Rewrite placeholder or generic fields so the character becomes concrete, distinct, and specific. "
            "If the name is too close to cast_slot.slot_label or cast_slot.public_role, replace it with a person-like name."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            from rpg_backend.author.contracts import OverviewCastDraft

            slot = cast_slot
            return GatewayStructuredResponse(
                value=OverviewCastDraft.model_validate(
                    self._normalize_cast_member_payload(
                        raw.payload,
                        slot_label=str(slot.get("slot_label") or "Civic Role"),
                        public_role=str(slot.get("public_role") or "Stakeholder"),
                        agenda_anchor=str(slot.get("agenda_anchor") or "Protect their institutional stake while the crisis unfolds."),
                        red_line_anchor=str(slot.get("red_line_anchor") or "Will not accept being cut out of the settlement."),
                        pressure_vector=str(slot.get("pressure_vector") or "Pushes harder for leverage as public pressure rises."),
                    )
                ),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def glean_story_cast(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_overview: CastOverviewDraft,
        partial_cast: CastDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[CastDraft]:
        payload: dict[str, Any] = {
            "story_frame": story_frame.model_dump(mode="json"),
            "cast_overview": cast_overview.model_dump(mode="json"),
            "partial_cast": partial_cast.model_dump(mode="json"),
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the NPC Ensemble repair generator. Return one strict JSON object matching CastDraft. "
            "Improve partial_cast instead of discarding it wholesale. "
            "Keep any specific useful names or roles that already fit the story. "
            "Replace placeholder names and generic agenda, red_line, or pressure_signature text with concrete character language. "
            "Use cast_overview as the binding scaffold and return a complete CastDraft."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_overview,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=CastDraft.model_validate(self._normalize_cast_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_beat_plan(
        self,
        focused_brief: FocusedBrief,
        story_frame: StoryFrameDraft,
        cast_draft: CastDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[BeatPlanDraft]:
        context_packet = self._build_author_context_from_story(story_frame, cast_draft)
        payload: dict[str, Any] = {
            "author_context": context_packet.model_dump(mode="json"),
        }
        if not (self.use_session_cache and previous_response_id):
            payload["focused_brief"] = focused_brief.model_dump(mode="json")
        system_prompt = (
            "You are the Beat Plan generator. Return one strict JSON object matching BeatPlanDraft. "
            "Do not output markdown. Design 2-4 beats for a fixed mainline story with locally flexible play. "
            "Each beat must include: title, goal, focus_names, required_truth_texts, detour_budget, progress_required, return_hooks, affordance_tags, blocked_affordances. "
            "Use cast names and truth texts that already exist in author_context. "
            "Affordance tags must come from: reveal_truth, build_trust, contain_chaos, shift_public_narrative, protect_civilians, secure_resources, unlock_ally, pay_cost."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_beat_plan,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=BeatPlanDraft.model_validate(
                    self._normalize_beat_plan_payload(
                        raw.payload,
                        story_frame=story_frame,
                        cast_draft=cast_draft,
                    )
                ),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    @staticmethod
    def _assemble_story_overview(
        story_frame: StoryFrameDraft,
        cast_draft: CastDraft,
        beat_plan: BeatPlanDraft,
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
            beats=beat_plan.beats,
        )

    def generate_story_overview(self, focused_brief: FocusedBrief) -> StoryOverviewDraft:
        frame = self.generate_story_frame(focused_brief)
        cast_overview = self.generate_cast_overview(
            focused_brief,
            frame.value,
            previous_response_id=frame.response_id,
        )
        cast = self.generate_story_cast(
            focused_brief,
            frame.value,
            cast_overview.value,
            previous_response_id=cast_overview.response_id or frame.response_id,
        )
        beats = self.generate_beat_plan(
            focused_brief,
            frame.value,
            cast.value,
            previous_response_id=cast.response_id or frame.response_id,
        )
        return self._assemble_story_overview(frame.value, cast.value, beats.value)

    def generate_route_opportunity_plan_result(
        self,
        design_bundle: DesignBundle,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[RouteOpportunityPlanDraft]:
        context_packet = self._build_author_context_from_bundle(design_bundle)
        payload = {
            "author_context": context_packet.model_dump(mode="json"),
        }
        system_prompt = (
            "You are the Author Route Opportunity generator. Return one strict JSON object matching RouteOpportunityPlanDraft. "
            "Identify 1-8 route opportunities across the beats in author_context. "
            "Do not generate affordance effect profiles or ending rules. "
            "Each opportunity must include: beat_id, unlock_route_id, unlock_affordance_tag, triggers. "
            "Each trigger must include: kind, target_id, and optional min_value. "
            "Allowed trigger kinds are: truth, axis, stance, flag, event. "
            "Use only ids that already exist in author_context. "
            "Prefer concrete unlock opportunities with 1-2 meaningful triggers over vague coverage."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_rulepack,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=RouteOpportunityPlanDraft.model_validate(
                    self._normalize_route_opportunity_plan_payload(raw.payload, design_bundle)
                ),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_route_affordance_pack_result(
        self,
        design_bundle: DesignBundle,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[RouteAffordancePackDraft]:
        context_packet = self._build_author_context_from_bundle(design_bundle)
        payload = {
            "author_context": context_packet.model_dump(mode="json"),
        }
        system_prompt = (
            "You are the Author Route and Affordance generator. Return one strict JSON object matching RouteAffordancePackDraft. "
            "Create route unlock rules and one affordance effect profile for every affordance tag used in author_context.beats. "
            "Do not generate ending rules. "
            "Use only axis, stance, truth, event, and flag ids that already exist in author_context. "
            "Treat affordance tags as runtime semantics, not literary themes. Prefer tags that imply game-state changes rather than abstract mood words. "
            "Required top-level keys: route_unlock_rules, affordance_effect_profiles. "
            "Keep rules compact, deterministic-friendly, and non-graphic."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_rulepack,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=RouteAffordancePackDraft.model_validate(
                    self._normalize_route_affordance_payload(raw.payload, design_bundle)
                ),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_ending_rules_result(
        self,
        design_bundle: DesignBundle,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[EndingRulesDraft]:
        context_packet = self._build_author_context_from_bundle(design_bundle)
        pressure_axis_id = next((axis.axis_id for axis in design_bundle.state_schema.axes if axis.kind == "pressure"), design_bundle.state_schema.axes[0].axis_id)
        secondary_axis_id = next((axis.axis_id for axis in design_bundle.state_schema.axes if axis.axis_id != pressure_axis_id), pressure_axis_id)
        truth_ids = [item.truth_id for item in design_bundle.story_bible.truth_catalog]
        event_ids = [event for beat in design_bundle.beat_spine for event in beat.required_events]
        flag_ids = [item.flag_id for item in design_bundle.state_schema.flags]
        payload = {
            "author_context": context_packet.model_dump(mode="json"),
            "ending_seed": {
                "collapse": {
                    "suggested_min_axis": pressure_axis_id,
                    "suggested_threshold": 5,
                    "suggested_truth_id": truth_ids[0] if truth_ids else None,
                },
                "pyrrhic": {
                    "suggested_min_axis": secondary_axis_id,
                    "suggested_threshold": 5,
                    "suggested_event_id": event_ids[-1] if event_ids else None,
                    "suggested_flag_id": flag_ids[0] if flag_ids else None,
                    "suggested_truth_id": truth_ids[1] if len(truth_ids) > 1 else (truth_ids[0] if truth_ids else None),
                },
                "mixed": {"suggested_as_default": True},
            },
        }
        system_prompt = (
            "You are the Author Ending Rules generator. Return one strict JSON object matching EndingRulesDraft. "
            "Create only ending rules that decide how the story resolves. "
            "Do not generate route unlock rules or affordance effect profiles. "
            "Use only axis, stance, truth, event, and flag ids that already exist in author_context. "
            "Required top-level key: ending_rules. "
            "Return exactly these ending_ids once each: collapse, pyrrhic, mixed. "
            "collapse and pyrrhic must each include at least one non-empty condition. "
            "At least one of collapse or pyrrhic must include a story-specific condition using a truth, event, flag, or stance id when such ids are available. "
            "mixed should be the lowest-priority fallback and may have empty conditions. "
            "Use ending_seed as a strong anchor when choosing axis conditions and story-specific ids. "
            "Keep the output terse, rule-like, deterministic-friendly, and non-graphic."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_rulepack,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=EndingRulesDraft.model_validate(self._normalize_ending_rules_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def glean_ending_rules(
        self,
        design_bundle: DesignBundle,
        partial_ending_rules: EndingRulesDraft,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[EndingRulesDraft]:
        context_packet = self._build_author_context_from_bundle(design_bundle)
        payload = {
            "author_context": context_packet.model_dump(mode="json"),
            "partial_ending_rules": partial_ending_rules.model_dump(mode="json"),
        }
        system_prompt = (
            "You are the Author Ending Rules repair generator. Return one strict JSON object matching EndingRulesDraft. "
            "Improve partial_ending_rules instead of replacing them wholesale. "
            "Keep any valid canonical ending ids that already fit. "
            "Return exactly one rule each for collapse, pyrrhic, and mixed. "
            "Add concrete conditions to collapse and pyrrhic if they are empty or too generic. "
            "At least one non-mixed ending should use a truth, event, flag, or stance condition if author_context provides those ids. "
            "mixed should remain the fallback outcome."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_rulepack,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=EndingRulesDraft.model_validate(self._normalize_ending_rules_payload(raw.payload)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_global_rulepack_result(
        self,
        design_bundle: DesignBundle,
        *,
        previous_response_id: str | None = None,
    ) -> GatewayStructuredResponse[RulePack]:
        context_packet = self._build_author_context_from_bundle(design_bundle)
        payload = {
            "author_context": context_packet.model_dump(mode="json"),
        }
        system_prompt = (
            "You are the Author RulePack generator. Return one strict JSON object matching RulePack. "
            "Create route unlock rules, ending rules, and one affordance effect profile for every affordance tag used in author_context.beats. "
            "Use only axis, stance, truth, event, and flag ids that already exist in author_context. "
            "Treat affordance tags as runtime semantics, not literary themes. Prefer tags that imply game-state changes rather than abstract mood words. "
            "Keep the output terse and rule-like; do not write explanation-heavy prose. "
            "Required top-level keys: route_unlock_rules, ending_rules, affordance_effect_profiles. "
            "Keep rules compact, deterministic-friendly, and non-graphic."
        )
        raw = self._invoke_json(
            system_prompt=system_prompt,
            user_payload=payload,
            max_output_tokens=self.max_output_tokens_rulepack,
            previous_response_id=previous_response_id,
        )
        try:
            return GatewayStructuredResponse(
                value=RulePack.model_validate(self._normalize_rulepack_payload(raw.payload, design_bundle)),
                response_id=raw.response_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise AuthorGatewayError(
                code="llm_schema_invalid",
                message=str(exc),
                status_code=502,
            ) from exc

    def generate_global_rulepack(self, design_bundle: DesignBundle) -> RulePack:
        return self.generate_global_rulepack_result(design_bundle).value


def get_author_llm_gateway(settings: Settings | None = None) -> AuthorLLMGateway:
    resolved = settings or get_settings()
    base_url = (resolved.responses_base_url or "").strip()
    api_key = (resolved.responses_api_key or "").strip()
    model = (resolved.responses_model or "").strip()
    if not base_url or not api_key or not model:
        raise AuthorGatewayError(
            code="llm_config_missing",
            message="APP_RESPONSES_BASE_URL, APP_RESPONSES_API_KEY, and APP_RESPONSES_MODEL are required",
            status_code=500,
        )

    use_session_cache = resolved.responses_use_session_cache
    if use_session_cache is None:
        use_session_cache = "dashscope" in base_url.casefold()

    client_kwargs: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
    }
    if use_session_cache:
        client_kwargs["default_headers"] = {
            resolved.responses_session_cache_header: resolved.responses_session_cache_value,
        }
    client = OpenAI(**client_kwargs)
    return AuthorLLMGateway(
        client=client,
        model=model,
        timeout_seconds=float(resolved.responses_timeout_seconds),
        max_output_tokens_overview=resolved.responses_max_output_tokens_author_overview,
        max_output_tokens_beat_plan=resolved.responses_max_output_tokens_author_beat_plan,
        max_output_tokens_rulepack=resolved.responses_max_output_tokens_author_rulepack,
        use_session_cache=bool(use_session_cache),
    )
