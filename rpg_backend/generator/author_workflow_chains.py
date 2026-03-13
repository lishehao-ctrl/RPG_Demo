from __future__ import annotations

import inspect
from typing import Any

from pydantic import ValidationError

from rpg_backend.domain.conflict_tags import NPC_CONFLICT_TAG_CATALOG
from rpg_backend.generator.author_workflow_errors import PromptCompileError
from rpg_backend.generator.author_workflow_models import (
    AuthorMemory,
    BeatOutlineLLM,
    BeatOverviewContext,
    BeatPrefixSummary,
    StoryOverview,
)
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy, get_author_workflow_policy
from rpg_backend.llm.agents import AuthorAgent
from rpg_backend.llm.factory import get_author_agent


def _compact_last_accepted_beat(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    compact: dict[str, Any] = {}
    for key in ("beat_id", "title", "objective", "present_npcs", "events_produced", "closing_hook"):
        value = payload.get(key)
        if value is not None:
            compact[key] = value

    scenes = payload.get("scenes")
    if "closing_hook" not in compact and isinstance(scenes, list) and scenes:
        last_scene = scenes[-1]
        if isinstance(last_scene, dict) and isinstance(last_scene.get("scene_seed"), str):
            compact["closing_hook"] = last_scene["scene_seed"]

    return compact or None


def _compact_overview_context_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}

    for key in ("premise", "stakes", "tone", "ending_shape"):
        value = payload.get(key)
        if value is not None:
            compact[key] = value

    move_bias = payload.get("move_bias")
    if isinstance(move_bias, list):
        compact["move_bias"] = list(move_bias)[:3]

    scene_constraints = payload.get("scene_constraints")
    if isinstance(scene_constraints, list):
        compact["scene_constraints"] = list(scene_constraints)[:2]

    npc_roster = payload.get("npc_roster")
    if isinstance(npc_roster, list):
        compact["npc_roster"] = [
            {
                key: npc.get(key)
                for key in ("name", "role", "red_line", "conflict_tags")
                if key in npc
            }
            for npc in npc_roster
            if isinstance(npc, dict)
        ]

    return compact


class _JsonSchemaChain:
    def __init__(
        self,
        *,
        policy: AuthorWorkflowPolicy | None = None,
        author_agent: AuthorAgent | None = None,
    ) -> None:
        self.policy = policy or get_author_workflow_policy()
        self._author_agent = author_agent
        self.model = getattr(author_agent, "model", "unknown")
        self.timeout_seconds = float(self.policy.timeout_seconds)
        self.max_retries = int(self.policy.llm_call_max_retries)

    @property
    def author_agent(self) -> AuthorAgent:
        if self._author_agent is None:
            self._author_agent = get_author_agent()
            self.model = getattr(self._author_agent, "model", self.model)
        return self._author_agent

    @staticmethod
    def _build_validation_feedback(exc: Exception) -> list[str]:
        if isinstance(exc, ValidationError):
            feedback: list[str] = []
            seen_paths: set[str] = set()
            for issue in exc.errors():
                path = ".".join(str(part) for part in issue.get("loc", ())) or "<root>"
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                feedback.append(f"{path}: {issue.get('msg', 'invalid value')}")
            return feedback or [str(exc)]
        return [str(exc)]

    @staticmethod
    def _accepts_kwarg(func: Any, name: str) -> bool:
        signature = inspect.signature(func)
        if name in signature.parameters:
            return True
        return any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
        )


class StoryOverviewChain(_JsonSchemaChain):
    async def _invoke_chain(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        timeout_seconds: float | None = None,
        run_id: str | None = None,
    ):
        return await self.author_agent.generate_overview(
            run_id=run_id or "author_overview_stateless",
            raw_brief=system_prompt,
            output_schema=dict(user_payload.get("output_schema") or StoryOverview.model_json_schema()),
            timeout_seconds=timeout_seconds,
        )

    async def compile(
        self,
        *,
        raw_brief: str,
        timeout_seconds: float | None = None,
        run_id: str | None = None,
    ) -> StoryOverview:
        effective_timeout_seconds = float(timeout_seconds or self.timeout_seconds)
        catalog_markdown = "\n".join(
            f"- `{key}`: {value}" for key, value in dict(NPC_CONFLICT_TAG_CATALOG).items()
        )
        if not self.model:
            raise PromptCompileError(
                error_code="prompt_compile_failed",
                errors=["responses config missing model"],
                notes=["check APP_RESPONSES_MODEL"],
            )

        system_prompt = (
            "# Role & Intent\n"
            "You transform a raw author brief into one strict StoryOverview JSON object.\n"
            "Do NOT output any text outside JSON.\n\n"
            "# Hard Constraints\n"
            "- target_minutes must be between 8 and 12 inclusive.\n"
            "- npc_count must be between 3 and 5 inclusive.\n"
            "- npc_roster length must equal npc_count.\n"
            "- ending_shape must be one of triumph, pyrrhic, uncertain, sacrifice.\n"
            "- move_bias values must come from the move_bias enum only.\n"
            "- npc_roster[*].conflict_tags must use only the npc conflict tag enum values below.\n"
            "- npc conflict tags are NOT move_bias values. Never use social, technical, stealth, investigate, support, resource, conflict, or mobility in npc_roster[*].conflict_tags.\n\n"
            "# NPC Conflict Tags\n"
            f"{catalog_markdown}\n\n"
            "# Raw Brief\n"
            f"{raw_brief}"
        )
        invoke_kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "user_payload": {
                "output_schema": StoryOverview.model_json_schema(),
            },
            "timeout_seconds": effective_timeout_seconds,
        }
        if self._accepts_kwarg(self._invoke_chain, "run_id"):
            invoke_kwargs["run_id"] = run_id
        try:
            result = await self._invoke_chain(**invoke_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise PromptCompileError(
                error_code="prompt_compile_failed",
                errors=[str(exc)],
                notes=["story overview responses execution failed"],
            ) from exc

        try:
            return StoryOverview.model_validate(result.payload)
        except ValidationError as exc:
            raise PromptCompileError(
                error_code="overview_invalid",
                errors=self._build_validation_feedback(exc),
                notes=["story overview schema validation failed"],
            ) from exc


class BeatGenerationChain(_JsonSchemaChain):
    def __init__(
        self,
        *,
        policy: AuthorWorkflowPolicy | None = None,
        author_agent: AuthorAgent | None = None,
    ) -> None:
        super().__init__(policy=policy, author_agent=author_agent)
        self.last_beat_outline_llm: BeatOutlineLLM | None = None

    async def compile_outline(
        self,
        *,
        story_id: str,
        overview_context: BeatOverviewContext,
        blueprint: dict[str, Any],
        last_accepted_beat: dict[str, Any] | None,
        prefix_summary: BeatPrefixSummary,
        author_memory: AuthorMemory | None = None,
        lint_feedback: list[str] | None = None,
        timeout_seconds: float | None = None,
        run_id: str | None = None,
    ) -> BeatOutlineLLM:
        effective_timeout_seconds = float(timeout_seconds or self.timeout_seconds)
        system_prompt = (
            "# Role & Intent\n"
            "Generate one strict BeatOutlineLLM JSON object for the current beat blueprint.\n"
            "Read the projected overview, the current beat blueprint, the lightweight last accepted beat summary if present, and the structured prefix summary for completed beat order.\n"
            "Use the structured author_memory as the primary continuity source of truth for recent beats, active NPCs, and unresolved threads.\n"
            "Treat last_accepted_beat as a small recent-detail hint only, not as the full serialized prior beat.\n"
            "The new beat must continue those exact details; do not contradict prior beats.\n"
            "Do NOT output any text outside JSON.\n\n"
            "# Hard Constraints\n"
            "- Do NOT output beat_id, title, objective, conflict, required_event, entry_scene_id, scene ids, move ids, outcome ids, args_schema, exit_conditions, move templates, or strategy-slot choices.\n"
            "- Output only scene_plans, move_surfaces, present_npcs, and events_produced.\n"
            "- move_surfaces must contain exactly 3 entries in this order: [fast_dirty surface, steady_slow surface, political_safe_resource_heavy surface].\n"
            "- Each move_surfaces entry may only define label, intents, synonyms, and roleplay_examples. The backend will inject one executable move for each style deterministically.\n"
            "- roleplay_examples must be short first-person things a player might actually type, such as 'I cut the feeder and reroute it by hand.'\n"
            "- Labels must be concrete action choices a player would click. Bad labels: 'Fast Dirty Surface', 'Steady Slow Surface'. Good labels: 'Cut the feeder and reroute it', 'Stabilize the relay step by step'.\n"
            "- Keep the beat compact but not brittle: usually 2 scenes, allow 1-3 when needed."
        )
        payload = {
            "story_id": story_id,
            "overview_context": _compact_overview_context_payload(overview_context.model_dump(mode="json")),
            "blueprint": blueprint,
            "last_accepted_beat": _compact_last_accepted_beat(last_accepted_beat),
            "prefix_summary": prefix_summary.model_dump(mode="json"),
            "author_memory": author_memory.model_dump(mode="json") if author_memory is not None else None,
            "lint_feedback": list(lint_feedback or []),
            "output_schema": BeatOutlineLLM.model_json_schema(),
        }

        invoke_kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "user_payload": payload,
            "timeout_seconds": effective_timeout_seconds,
        }
        if self._accepts_kwarg(self._invoke_chain, "run_id"):
            invoke_kwargs["run_id"] = run_id
        try:
            result = await self._invoke_chain(**invoke_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise PromptCompileError(
                error_code="prompt_compile_failed",
                errors=[str(exc)],
                notes=["beat outline responses execution failed"],
            ) from exc

        try:
            outline = BeatOutlineLLM.model_validate(result.payload)
            self.last_beat_outline_llm = outline
            return outline
        except Exception as exc:  # noqa: BLE001
            raise PromptCompileError(
                error_code="beat_invalid",
                errors=self._build_validation_feedback(exc),
                notes=["beat outline schema validation failed"],
            ) from exc

    async def _invoke_chain(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        timeout_seconds: float | None = None,
        run_id: str | None = None,
    ):
        payload = dict(user_payload)
        payload["instructions"] = system_prompt
        story_id = str(payload.get("story_id") or "story")
        return await self.author_agent.generate_outline(
            run_id=run_id or f"author_outline_stateless:{story_id}",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
