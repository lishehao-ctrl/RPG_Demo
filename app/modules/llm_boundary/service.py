from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.config import settings
from app.modules.llm_boundary.client import (
    LLMCallError,
    call_chat_completions,
    call_chat_completions_stream_text,
)
from app.modules.llm_boundary.errors import GrammarCheckError, LLMUnavailableError
from app.modules.llm_boundary.grammarcheck import validate_structured_output
from app.modules.llm_boundary.prompt_profiles import render_prompt
from app.modules.llm_boundary.schemas import (
    ENDING_BUNDLE_SCHEMA,
    ENDING_BUNDLE_SCHEMA_NAME,
    EndingBundleOutput,
    EndingHighlightOut,
    EndingReportOut,
    EndingStatsOut,
    NARRATIVE_SCHEMA,
    NARRATIVE_SCHEMA_NAME,
    NarrativeOutput,
    SELECTION_MAPPING_SCHEMA_V3,
    SELECTION_MAPPING_SCHEMA_V3_NAME,
    SelectionCandidate,
    SelectionCandidateV3,
    SelectionMappingOutput,
    SelectionMappingOutputV3,
)


@dataclass(frozen=True)
class _LLMChannelConfig:
    api_key: str
    base_url: str
    path: str
    model: str
    timeout_s: float


CHAT_COMPLETIONS_PATH = "/chat/completions"
SELECTION_TIMEOUT_S = 8.0
NARRATION_TIMEOUT_S = 30.0
ENDING_TIMEOUT_S = 30.0
SELECTION_SCHEMA_STRICT = True
NARRATION_IGNORE_REASONING = True
NARRATION_MAX_CHARS = 1200


class LLMBoundary:
    def provider_trace_label(self) -> str:
        return "real_auto" if self._is_real_mode() else "fake_auto"

    def narrative(
        self,
        *,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        prompt_profile_id: str | None = None,
        slots: dict[str, object] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> NarrativeOutput:
        return self.narrative_stream(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prompt_profile_id=prompt_profile_id,
            slots=slots,
            on_delta=on_delta,
        )

    def narrative_stream(
        self,
        *,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        prompt_profile_id: str | None = None,
        slots: dict[str, object] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> NarrativeOutput:
        if prompt_profile_id:
            resolved_system, resolved_user = render_prompt(prompt_profile_id, slots=slots or {})
            system_prompt = resolved_system
            user_prompt = resolved_user

        if not system_prompt or not user_prompt:
            raise ValueError("narrative requires system_prompt+user_prompt or prompt_profile_id+slots")

        if not self._is_real_mode():
            fake_text = self._fake_narrative_text(user_prompt=user_prompt, slots=slots)
            if on_delta is not None and fake_text:
                try:
                    on_delta(fake_text)
                except Exception:
                    pass
            payload = validate_structured_output(
                {"narrative_text": fake_text},
                schema_name=NARRATIVE_SCHEMA_NAME,
                schema=NARRATIVE_SCHEMA,
            )
            return NarrativeOutput.model_validate(payload)

        channel = self._resolve_channel(timeout_s=NARRATION_TIMEOUT_S)
        try:
            raw_text = asyncio.run(
                call_chat_completions_stream_text(
                    api_key=channel.api_key,
                    base_url=channel.base_url,
                    path=channel.path,
                    model=channel.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    timeout_s=channel.timeout_s,
                    ignore_reasoning=NARRATION_IGNORE_REASONING,
                    on_delta=on_delta,
                )
            )
            return NarrativeOutput.model_validate({"narrative_text": self._normalize_narrative_text(raw_text)})
        except LLMCallError as exc:
            raise LLMUnavailableError(str(exc)) from exc

    def map_free_input(
        self,
        *,
        player_input: str,
        scene_brief: str,
        visible_choices: list[dict],
        available_fallbacks: list[dict],
        input_policy_flag: bool = False,
        retry_context: dict[str, object] | None = None,
    ) -> SelectionMappingOutput:
        out = self.map_free_input_v3(
            player_input=player_input,
            scene_brief=scene_brief,
            visible_choices=visible_choices,
            available_fallbacks=available_fallbacks,
            input_policy_flag=input_policy_flag,
            retry_context=retry_context,
        )
        return SelectionMappingOutput(
            target_type=out.target_type,
            target_id=out.target_id,
            confidence=out.confidence,
            intensity_tier=out.intensity_tier,
            reason=out.reason,
            top_candidates=[
                SelectionCandidate(
                    target_type=item.target_type,
                    target_id=item.target_id,
                    confidence=item.confidence,
                )
                for item in out.top_candidates
            ],
        )

    def map_free_input_v3(
        self,
        *,
        player_input: str,
        scene_brief: str,
        visible_choices: list[dict],
        available_fallbacks: list[dict],
        input_policy_flag: bool = False,
        retry_context: dict[str, object] | None = None,
    ) -> SelectionMappingOutputV3:
        if not self._is_real_mode():
            return self._fake_map_free_input_v3(
                player_input=player_input,
                scene_brief=scene_brief,
                visible_choices=visible_choices,
                available_fallbacks=available_fallbacks,
                input_policy_flag=input_policy_flag,
            )

        channel = self._resolve_channel(timeout_s=SELECTION_TIMEOUT_S)
        choices_payload = [
            {
                "choice_id": str(item.get("choice_id") or ""),
                "text": str(item.get("text") or ""),
                "intent_tags": [str(tag) for tag in (item.get("intent_tags") or [])],
            }
            for item in visible_choices
        ]
        fallback_payload = [
            {
                "fallback_id": str(item.get("fallback_id") or ""),
                "reason_code": str(item.get("reason_code") or ""),
            }
            for item in available_fallbacks
        ]

        confidence_high = min(1.0, max(0.0, float(settings.story_mapping_confidence_high)))
        confidence_low = min(1.0, max(0.0, float(settings.story_mapping_confidence_low)))
        if confidence_low > confidence_high:
            confidence_low, confidence_high = confidence_high, confidence_low

        slots = {
            "scene_brief": scene_brief,
            "player_input": player_input,
            "input_policy_flag": bool(input_policy_flag),
            "visible_choices_json": json.dumps(choices_payload, ensure_ascii=False, separators=(",", ":")),
            "available_fallbacks_json": json.dumps(fallback_payload, ensure_ascii=False, separators=(",", ":")),
            "confidence_policy_json": json.dumps(
                {"high": confidence_high, "low": confidence_low},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "retry_context_json": json.dumps(retry_context if isinstance(retry_context, dict) else {}, ensure_ascii=False, separators=(",", ":")),
        }
        system_prompt, user_prompt = render_prompt("selection_mapping_v3", slots=slots)

        try:
            payload = self._call_structured_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_name=SELECTION_MAPPING_SCHEMA_V3_NAME,
                schema_payload=SELECTION_MAPPING_SCHEMA_V3,
                channel=channel,
                strict=SELECTION_SCHEMA_STRICT,
                max_transport_attempts=1,
            )
            return SelectionMappingOutputV3.model_validate(payload)
        except (LLMCallError, GrammarCheckError, ValidationError, ValueError) as exc:
            raise LLMUnavailableError(str(exc)) from exc

    def ending_bundle(
        self,
        *,
        prompt_profile_id: str = "ending_default_v2",
        slots: dict[str, object],
    ) -> EndingBundleOutput:
        system_prompt, user_prompt = render_prompt(prompt_profile_id, slots=slots)

        if not self._is_real_mode():
            payload = self._fake_ending_bundle(slots=slots)
            payload = validate_structured_output(
                payload,
                schema_name=ENDING_BUNDLE_SCHEMA_NAME,
                schema=ENDING_BUNDLE_SCHEMA,
            )
            return EndingBundleOutput.model_validate(payload)

        channel = self._resolve_channel(timeout_s=ENDING_TIMEOUT_S)
        try:
            payload = self._call_structured_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_name=ENDING_BUNDLE_SCHEMA_NAME,
                schema_payload=ENDING_BUNDLE_SCHEMA,
                channel=channel,
                strict=SELECTION_SCHEMA_STRICT,
            )
            return EndingBundleOutput.model_validate(payload)
        except (LLMCallError, GrammarCheckError) as exc:
            raise LLMUnavailableError(str(exc)) from exc

    def _call_structured_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema_payload: dict,
        channel: _LLMChannelConfig,
        strict: bool,
        max_transport_attempts: int = 3,
    ) -> dict:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": schema_payload,
                "strict": strict,
            },
        }
        raw = asyncio.run(
            call_chat_completions(
                api_key=channel.api_key,
                base_url=channel.base_url,
                path=channel.path,
                model=channel.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=response_format,
                timeout_s=channel.timeout_s,
                max_attempts=max_transport_attempts,
            )
        )
        return validate_structured_output(raw, schema_name=schema_name, schema=schema_payload)

    @staticmethod
    def _clean(value: str | None) -> str:
        return str(value or "").strip()

    def _resolve_channel(self, *, timeout_s: float) -> _LLMChannelConfig:
        return _LLMChannelConfig(
            api_key=self._clean(settings.llm_api_key),
            base_url=self._clean(settings.llm_base_url),
            path=CHAT_COMPLETIONS_PATH,
            model=self._clean(settings.llm_model),
            timeout_s=float(timeout_s),
        )

    @staticmethod
    def _is_real_mode() -> bool:
        return bool(str(settings.llm_api_key or "").strip())

    @staticmethod
    def _normalize_narrative_text(raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            raise LLMCallError("empty narration text")
        max_chars = max(1, int(NARRATION_MAX_CHARS))
        if len(text) > max_chars:
            return text[:max_chars]
        return text

    @staticmethod
    def _fake_ending_bundle(*, slots: dict[str, object]) -> dict:
        outcome = " ".join(str(slots.get("ending_outcome") or "fail").split()) or "fail"
        epilogue = " ".join(str(slots.get("epilogue") or "").split()) or "The journey reached its final page."
        stats_raw = slots.get("session_stats")
        stats = stats_raw if isinstance(stats_raw, dict) else {}
        beats_raw = slots.get("recent_action_beats")
        beats = beats_raw if isinstance(beats_raw, list) else []

        def _to_int(key: str) -> int:
            value = stats.get(key, 0)
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return 0

        def _to_float(key: str, *, lower: float | None = None, upper: float | None = None) -> float:
            value = stats.get(key, 0.0)
            try:
                out = float(value)
            except (TypeError, ValueError):
                out = 0.0
            if lower is not None:
                out = max(lower, out)
            if upper is not None:
                out = min(upper, out)
            return out

        report_stats = EndingStatsOut(
            total_steps=_to_int("total_steps"),
            fallback_count=_to_int("fallback_count"),
            fallback_rate=_to_float("fallback_rate", lower=0.0, upper=1.0),
            explicit_count=_to_int("explicit_count"),
            rule_count=_to_int("rule_count"),
            llm_count=_to_int("llm_count"),
            fallback_source_count=_to_int("fallback_source_count"),
            energy_delta=_to_float("energy_delta"),
            money_delta=_to_float("money_delta"),
            knowledge_delta=_to_float("knowledge_delta"),
            affection_delta=_to_float("affection_delta"),
        )

        highlights: list[EndingHighlightOut] = []
        for beat in beats[-3:]:
            if not isinstance(beat, dict):
                continue
            step_index = beat.get("step_index")
            executed = str(beat.get("executed_choice_id") or "unknown_action")
            source = str(beat.get("selection_source") or "fallback")
            reason = str(beat.get("fallback_reason") or "").strip()
            title = f"Step {step_index}: {source}"
            detail = f"Executed {executed}."
            if reason:
                detail += f" Fallback reason: {reason}."
            highlights.append(EndingHighlightOut(title=title, detail=detail))

        if not highlights:
            highlights.append(
                EndingHighlightOut(
                    title="Journey Snapshot",
                    detail="You kept the story moving and reached a valid ending state.",
                )
            )

        persona_tags: list[str] = []
        if report_stats.fallback_rate >= 0.6:
            persona_tags.append("drifter")
        if report_stats.knowledge_delta > 0:
            persona_tags.append("learner")
        if report_stats.affection_delta > 0:
            persona_tags.append("connector")
        if report_stats.money_delta > 0:
            persona_tags.append("resourceful")
        if report_stats.energy_delta < 0:
            persona_tags.append("tenacious")
        if not persona_tags:
            persona_tags = ["steady"]

        report = EndingReportOut(
            title=f"Life Report: {outcome.title()} Route",
            one_liner=f"You finished this run with a {outcome} outcome.",
            life_summary=f"{epilogue} Total steps: {report_stats.total_steps}, fallback rate: {report_stats.fallback_rate:.2f}.",
            highlights=highlights[:5],
            stats=report_stats,
            persona_tags=persona_tags[:6],
        )
        return {
            "narrative_text": f"The run closes with a {outcome} ending. {epilogue}",
            "ending_report": report.model_dump(),
        }

    @staticmethod
    def _fake_narrative_text(*, user_prompt: str, slots: dict[str, object] | None) -> str:
        if isinstance(slots, dict) and slots.get("ending_id"):
            epilogue = " ".join(str(slots.get("epilogue") or "").split())
            outcome = str(slots.get("ending_outcome") or "fail")
            if epilogue:
                return f"The run ends with a {outcome} outcome. {epilogue}"
            return f"The run ends with a {outcome} outcome."

        if isinstance(slots, dict) and slots.get("mainline_nudge"):
            nudge = " ".join(str(slots.get("mainline_nudge") or "").split())
            tier = str(slots.get("nudge_tier") or "soft").lower()
            if tier == "firm":
                return f"The world firmly redirects your move. {nudge}"
            if tier == "neutral":
                return f"The world redirects your move with a clear course correction. {nudge}"
            return f"The world catches your move and keeps momentum. {nudge}"

        compact = " ".join(str(user_prompt or "").split())
        if len(compact) > 100:
            compact = compact[:100]
        return f"Your move lands and the world responds. {compact}"

    @staticmethod
    def _fake_map_free_input_v3(
        *,
        player_input: str,
        scene_brief: str,
        visible_choices: list[dict],
        available_fallbacks: list[dict],
        input_policy_flag: bool,
    ) -> SelectionMappingOutputV3:
        del scene_brief
        input_text = " ".join(str(player_input or "").lower().split())
        input_tokens = set(input_text.replace(",", " ").replace(".", " ").split())

        scored: list[SelectionCandidateV3] = []
        for item in visible_choices:
            choice_id = str(item.get("choice_id") or "").strip()
            if not choice_id:
                continue
            text = " ".join(str(item.get("text") or "").lower().split())
            intent_tokens: set[str] = set()
            for tag in item.get("intent_tags") or []:
                intent_tokens.update(str(tag).lower().split())
            overlap = len(input_tokens & intent_tokens)
            if text and text in input_text:
                overlap += 2
            confidence = min(0.95, 0.35 + overlap * 0.2)
            scored.append(
                SelectionCandidateV3(
                    target_type="choice",
                    target_id=choice_id,
                    confidence=confidence,
                )
            )

        scored.sort(key=lambda x: x.confidence, reverse=True)
        intensity_tier = 0
        if any(token in input_text for token in ("please", "carefully", "gently", "kindly")):
            intensity_tier = 1
        if any(token in input_text for token in ("hate", "stupid", "force", "attack")):
            intensity_tier = -1

        if input_policy_flag:
            fallback_target = ""
            for item in available_fallbacks:
                if str(item.get("reason_code") or "") == "INPUT_POLICY":
                    fallback_target = str(item.get("fallback_id") or "")
                    break
            if not fallback_target and available_fallbacks:
                fallback_target = str(available_fallbacks[0].get("fallback_id") or "")
            return SelectionMappingOutputV3(
                schema_version="3.0",
                decision_code="FALLBACK_INPUT_POLICY",
                target_type="fallback",
                target_id=fallback_target or "fb_input_policy",
                confidence=0.9,
                intensity_tier=-1,
                fallback_reason_code="INPUT_POLICY",
                reason="input_policy",
                top_candidates=[
                    SelectionCandidateV3(
                        target_type="fallback",
                        target_id=fallback_target or "fb_input_policy",
                        confidence=0.9,
                    )
                ],
            )

        if scored and scored[0].confidence >= 0.5:
            top = scored[0]
            return SelectionMappingOutputV3(
                schema_version="3.0",
                decision_code="SELECT_CHOICE",
                target_type="choice",
                target_id=top.target_id,
                confidence=top.confidence,
                intensity_tier=intensity_tier,
                fallback_reason_code=None,
                reason="heuristic_choice_match",
                top_candidates=scored[:3],
            )

        fallback_target = ""
        fallback_reason = "OFF_TOPIC"
        if "off_topic" in input_text or "sing" in input_text or "dance" in input_text:
            fallback_reason = "OFF_TOPIC"
        elif "maybe" in input_text or "idk" in input_text:
            fallback_reason = "LOW_CONF"
        elif not input_tokens:
            fallback_reason = "NO_MATCH"

        for item in available_fallbacks:
            if str(item.get("reason_code") or "") == fallback_reason:
                fallback_target = str(item.get("fallback_id") or "")
                break
        if not fallback_target and available_fallbacks:
            fallback_target = str(available_fallbacks[0].get("fallback_id") or "")

        top = scored[:2]
        top_candidates: list[SelectionCandidateV3] = list(top)
        top_candidates.append(
            SelectionCandidateV3(target_type="fallback", target_id=fallback_target or "fb_no_match", confidence=0.4)
        )
        decision_map = {
            "NO_MATCH": "FALLBACK_NO_MATCH",
            "LOW_CONF": "FALLBACK_LOW_CONF",
            "OFF_TOPIC": "FALLBACK_OFF_TOPIC",
        }

        return SelectionMappingOutputV3(
            schema_version="3.0",
            decision_code=decision_map.get(fallback_reason, "FALLBACK_NO_MATCH"),  # type: ignore[arg-type]
            target_type="fallback",
            target_id=fallback_target or "fb_no_match",
            confidence=0.4,
            intensity_tier=intensity_tier,
            fallback_reason_code=fallback_reason,  # type: ignore[arg-type]
            reason=fallback_reason.lower(),
            top_candidates=top_candidates[:3],
        )


_llm_boundary: LLMBoundary | None = None


def get_llm_boundary() -> LLMBoundary:
    global _llm_boundary
    if _llm_boundary is None:
        _llm_boundary = LLMBoundary()
    return _llm_boundary
