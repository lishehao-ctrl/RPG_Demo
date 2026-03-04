from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from rpg_backend.config.settings import get_settings
from rpg_backend.domain.conflict_tags import NPC_CONFLICT_TAG_CATALOG
from rpg_backend.generator.spec_outline_schema import StorySpecOutline
from rpg_backend.generator.spec_schema import StorySpec
from rpg_backend.generator.versioning import compute_payload_hash
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import resolve_openai_models
from rpg_backend.llm.json_gateway import JsonGateway, JsonGatewayError
from rpg_backend.llm.worker_client import WorkerClientError, get_worker_client


@dataclass
class PromptCompileResult:
    spec: StorySpec
    spec_hash: str
    model: str
    attempts: int
    notes: list[str] = field(default_factory=list)


class PromptCompileError(RuntimeError):
    def __init__(self, *, error_code: str, errors: list[str], notes: list[str] | None = None):
        super().__init__("prompt compile failed")
        self.error_code = error_code
        self.errors = errors
        self.notes = notes or []


class PromptCompiler:
    _OUTLINE_FIELD_LIMITS: dict[str, str] = {
        "title": "<=90 chars",
        "premise_core": "<=240 chars",
        "tone": "<=100 chars",
        "stakes_core": "<=220 chars",
        "beats": "exactly 4 items with unique titles",
        "npcs": "exactly 4 items; each NPC must include red_line <=160 chars and conflict_tags 1..3",
        "scene_constraints": "exactly 4 items",
        "move_bias": "2..5 items",
    }
    _SPEC_FIELD_LIMITS: dict[str, str] = {
        "title": "<=120 chars",
        "premise": "<=400 chars",
        "tone": "<=120 chars",
        "stakes": "<=300 chars",
        "beats": "3..5 items",
        "npcs": "3..5 items; each NPC must include conflict_tags 1..3",
        "scene_constraints": "3..5 items",
        "move_bias": "1..6 items",
    }
    _MAX_VALIDATION_FEEDBACK_ITEMS = 12
    _OUTLINE_STYLE_TARGETS: dict[str, str] = {
        "premise_core": "Write 1-2 sentences, concise and concrete.",
        "beats.*.required_event": "Use snake_case tag style, 3-5 words, no full sentence.",
        "beats.*.conflict": "Write one short sentence, 8-14 words.",
        "npcs.*.conflict_tags": "Choose 1-3 tags from {anti_noise, anti_speed, anti_resource_burn}.",
    }
    _NPC_CONFLICT_TAG_CATALOG: dict[str, str] = dict(NPC_CONFLICT_TAG_CATALOG)

    def __init__(self) -> None:
        settings = get_settings()
        self.gateway_mode = str(getattr(settings, "llm_gateway_mode", "local") or "local").strip().lower()
        self.base_url = (settings.llm_openai_base_url or "").strip()
        self.api_key = (settings.llm_openai_api_key or "").strip()
        self.model = self._resolve_model(settings)
        self.timeout_seconds = settings.llm_openai_timeout_seconds
        self.temperature = settings.llm_openai_generator_temperature
        self.max_retries = settings.llm_openai_generator_max_retries
        worker_client = None
        if self.gateway_mode == "worker":
            try:
                worker_client = get_worker_client()
            except WorkerClientError as exc:
                raise LLMProviderConfigError(
                    f"llm worker misconfigured for prompt compiler: {exc.error_code}: {exc.message}"
                ) from exc
        self._json_gateway = JsonGateway(
            gateway_mode=self.gateway_mode,
            base_url=self.base_url,
            api_key=self.api_key,
            default_timeout_seconds=float(self.timeout_seconds),
            connect_timeout_seconds=5.0,
            max_connections=100,
            max_keepalive_connections=20,
            http2_enabled=False,
            worker_client=worker_client,
        )

    @staticmethod
    def _resolve_model(settings) -> str:
        explicit = (settings.llm_openai_generator_model or "").strip()
        if explicit:
            return explicit
        route_model, _ = resolve_openai_models(
            settings.llm_openai_route_model,
            settings.llm_openai_narration_model,
            settings.llm_openai_model,
        )
        return route_model

    @staticmethod
    def _build_validation_feedback(exc: ValidationError) -> list[str]:
        feedback: list[str] = []
        seen_paths: set[str] = set()
        for issue in exc.errors():
            path = ".".join(str(part) for part in issue.get("loc", ())) or "<root>"
            if path in seen_paths:
                continue
            seen_paths.add(path)
            error_type = str(issue.get("type", "validation_error"))
            message = str(issue.get("msg", "invalid value"))
            ctx = issue.get("ctx") or {}
            constraints: list[str] = []
            if isinstance(ctx, dict):
                for key in ("max_length", "min_length", "max_items", "min_items", "ge", "gt", "le", "lt"):
                    if key in ctx:
                        constraints.append(f"{key}={ctx[key]}")
            constraint_text = f" ({', '.join(constraints)})" if constraints else ""
            target = PromptCompiler._target_style_for_path(path)
            target_text = f" | target: {target}" if target else ""
            feedback.append(f"{path}: {error_type}{constraint_text} - {message}{target_text}")
            if len(feedback) >= PromptCompiler._MAX_VALIDATION_FEEDBACK_ITEMS:
                break
        return feedback or ["schema validation failed: unknown constraint violation"]

    @staticmethod
    def _target_style_for_path(path: str) -> str | None:
        if path == "premise_core":
            return PromptCompiler._OUTLINE_STYLE_TARGETS["premise_core"]
        if re.fullmatch(r"beats\.\d+\.required_event", path):
            return PromptCompiler._OUTLINE_STYLE_TARGETS["beats.*.required_event"]
        if re.fullmatch(r"beats\.\d+\.conflict", path):
            return PromptCompiler._OUTLINE_STYLE_TARGETS["beats.*.conflict"]
        if re.fullmatch(r"npcs\.\d+\.conflict_tags(?:\.\d+)?", path):
            return PromptCompiler._OUTLINE_STYLE_TARGETS["npcs.*.conflict_tags"]
        return None

    def _call_json_object(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        user_prompt = json.dumps(payload, ensure_ascii=False)
        try:
            result = self._json_gateway.call_json_object(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model,
                temperature=self.temperature,
                max_retries=self.max_retries,
                timeout_seconds=self.timeout_seconds,
            )
        except JsonGatewayError as exc:
            raise RuntimeError(f"{exc.error_code}: {exc.message}") from exc
        return result.payload

    def compile(
        self,
        *,
        prompt_text: str,
        target_minutes: int,
        npc_count: int,
        style: str | None = None,
        attempt_index: int = 0,
        attempt_seed: str | None = None,
    ) -> PromptCompileResult:
        prompt_value = (prompt_text or "").strip()
        if not prompt_value:
            raise PromptCompileError(
                error_code="prompt_compile_failed",
                errors=["prompt_text must not be blank"],
                notes=["prompt compiler input validation failed"],
            )
        if not self.model:
            raise PromptCompileError(
                error_code="prompt_compile_failed",
                errors=["openai generator config missing model"],
                notes=["check APP_LLM_OPENAI_GENERATOR_MODEL / APP_LLM_OPENAI_ROUTE_MODEL / APP_LLM_OPENAI_MODEL"],
            )
        if self.gateway_mode != "worker" and (not self.base_url or not self.api_key):
            raise PromptCompileError(
                error_code="prompt_compile_failed",
                errors=["openai generator config missing base_url/api_key"],
                notes=["check APP_LLM_OPENAI_BASE_URL and APP_LLM_OPENAI_API_KEY"],
            )

        required_move_bias_tags = [
            "social",
            "stealth",
            "technical",
            "investigate",
            "support",
            "resource",
            "conflict",
            "mobility",
        ]
        common_payload: dict[str, Any] = {
            "prompt_text": prompt_value,
            "target_minutes": target_minutes,
            "npc_count": npc_count,
            "style": style or "",
            "attempt_index": attempt_index,
            "attempt_seed": attempt_seed or "",
            "required_move_bias_tags": required_move_bias_tags,
            "required_ending_shapes": ["triumph", "pyrrhic", "uncertain", "sacrifice"],
        }

        outline_prompt = (
            "You are a story architect for an interactive narrative game runtime. "
            "Step 1/2: produce a compact outline JSON only. "
            "Hard constraints: title<=90, premise_core<=240, tone<=100, stakes_core<=220, "
            "beats exactly 4 with unique titles, npcs exactly 4 each with a concrete non-negotiable red_line, "
            "each NPC must include conflict_tags (1..3) from {anti_noise, anti_speed, anti_resource_burn}, "
            "scene_constraints exactly 4, move_bias 2..5. "
            "Writing targets: premise_core should be 1-2 concise sentences; each beats.required_event should be a "
            "snake_case tag style phrase of 3-5 words (not full prose); each beats.conflict should be a short "
            "8-14 word sentence; NPC conflict_tags should align with each red_line semantics. "
            "Design beats so each scene can offer strategy triangle choices (fast_dirty / steady_slow / political_safe_resource_heavy). "
            "Ensure the last two beats can naturally collect debt from earlier risky choices. "
            "Self-check all limits before returning."
        )
        outline_payload = {
            "task": "compile_story_outline",
            **common_payload,
            "field_limits": dict(self._OUTLINE_FIELD_LIMITS),
            "style_targets": dict(self._OUTLINE_STYLE_TARGETS),
            "npc_conflict_tag_catalog": dict(self._NPC_CONFLICT_TAG_CATALOG),
            "output_schema": StorySpecOutline.model_json_schema(),
        }

        try:
            outline_obj = self._call_json_object(system_prompt=outline_prompt, payload=outline_payload)
            outline = StorySpecOutline.model_validate(outline_obj)
        except ValidationError as exc:
            feedback = self._build_validation_feedback(exc)
            raise PromptCompileError(
                error_code="prompt_outline_invalid",
                errors=[str(exc)],
                notes=[
                    "outline schema validation failed in stage 1",
                    *(f"outline_feedback: {item}" for item in feedback),
                ],
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise PromptCompileError(
                error_code="prompt_compile_failed",
                errors=[str(exc)],
                notes=["outline generation failed in stage 1"],
            ) from exc

        spec_prompt = (
            "You are a story architect for an interactive narrative game runtime. "
            "Step 2/2: expand the provided outline into a full StorySpec JSON only. "
            "Hard limits: title<=120, premise<=400, tone<=120, stakes<=300, beats 3..5, npcs 3..5, "
            "scene_constraints 3..5, move_bias 1..6. Preserve grounded realism and avoid fantasy drift. "
            "Every NPC must include red_line plus conflict_tags (1..3) from {anti_noise, anti_speed, anti_resource_burn}. "
            "red_line text and conflict_tags must semantically align and conflict with at least one strategy style. "
            "Ensure early risky shortcuts can be paid back in the final two beats via delayed consequences. "
            "Self-check all limits before returning."
        )
        spec_payload = {
            "task": "compile_story_spec_from_outline",
            **common_payload,
            "outline": outline.model_dump(mode="json"),
            "field_limits": dict(self._SPEC_FIELD_LIMITS),
            "npc_conflict_tag_catalog": dict(self._NPC_CONFLICT_TAG_CATALOG),
            "output_schema": StorySpec.model_json_schema(),
        }

        validation_feedback: list[str] = []
        last_validation_error: ValidationError | None = None
        for call_number in (2, 3):
            per_call_payload = dict(spec_payload)
            per_call_payload["compile_call"] = call_number
            per_call_payload["validation_feedback"] = list(validation_feedback)
            if validation_feedback:
                per_call_payload["retry_instruction"] = (
                    "Previous full spec failed validation. Regenerate the complete JSON and fix all violations."
                )
            try:
                spec_obj = self._call_json_object(system_prompt=spec_prompt, payload=per_call_payload)
                spec = StorySpec.model_validate(spec_obj)
                spec_hash = compute_payload_hash(spec.model_dump())
                return PromptCompileResult(
                    spec=spec,
                    spec_hash=spec_hash,
                    model=self.model,
                    attempts=call_number,
                    notes=[
                        "prompt_compiler_mode=two_stage",
                        f"prompt_compiler_model={self.model}",
                        f"prompt_compiler_attempts={call_number}",
                        f"prompt_compile_attempt_index={attempt_index}",
                        f"prompt_compile_attempt_seed={attempt_seed or ''}",
                    ],
                )
            except ValidationError as exc:
                last_validation_error = exc
                if call_number == 2:
                    validation_feedback = self._build_validation_feedback(exc)
                    continue
                raise PromptCompileError(
                    error_code="prompt_spec_invalid",
                    errors=[str(exc)],
                    notes=["full spec schema validation failed after stage-2 feedback retry"],
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise PromptCompileError(
                    error_code="prompt_compile_failed",
                    errors=[str(exc)],
                    notes=[f"full spec generation failed on call {call_number}"],
                ) from exc

        raise PromptCompileError(
            error_code="prompt_spec_invalid",
            errors=[str(last_validation_error) if last_validation_error else "unknown spec validation failure"],
            notes=["full spec schema validation failed after stage-2 calls"],
        )
