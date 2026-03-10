from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.llm.base import LLMProvider


class RouteChoiceLLM(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_key: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    interpreted_intent: str = Field(min_length=1)


class NarrationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narration_text: str = Field(min_length=1)


class _JsonSchemaPlayChain:
    def __init__(self, *, provider: LLMProvider) -> None:
        self.provider = provider

    @staticmethod
    def _stringify_message_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(part for part in parts if part)
        return str(content)

    async def _invoke_chain_via_provider(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        model: str,
        temperature: float,
        max_retries: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.runnables import RunnableLambda

        async def _call(prompt_value: Any) -> dict[str, Any]:
            messages = list(prompt_value.messages if hasattr(prompt_value, "messages") else prompt_value.to_messages())
            if len(messages) < 2:
                raise RuntimeError("langchain prompt did not produce system and user messages")
            result = await self.provider.invoke_json_object(
                system_prompt=self._stringify_message_content(messages[0].content),
                user_prompt=self._stringify_message_content(messages[1].content),
                model=model,
                temperature=temperature,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
            )
            payload = dict(result.payload)
            payload["_duration_ms"] = result.duration_ms
            return payload

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_prompt}"),
                ("human", "{user_prompt}"),
            ]
        )
        chain = prompt | RunnableLambda(_call)
        return await chain.ainvoke(
            {
                "system_prompt": system_prompt,
                "user_prompt": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
            }
        )


class RouteIntentChain(_JsonSchemaPlayChain):
    async def choose(
        self,
        *,
        scene_context: dict[str, Any],
        route_candidates: list[dict[str, Any]],
        text: str,
    ) -> tuple[RouteChoiceLLM, int | None, str]:
        gateway_mode = str(getattr(self.provider, "gateway_mode", "unknown") or "unknown")
        system_prompt = (
            "# Role & Intent\n"
            "Choose exactly one route candidate key for the player's free-text intent.\n"
            "Return strict JSON only.\n\n"
            "# Hard Constraints\n"
            "- selected_key must be one of the provided candidate keys like m0, m1, m2.\n"
            "- Do not return move ids.\n"
            "- Confidence must be between 0 and 1.\n"
        )
        payload = await self._invoke_chain_via_provider(
            system_prompt=system_prompt,
            user_payload={
                "task": "select_route_candidate",
                "player_text": text,
                "scene_context": {
                    "scene_seed": scene_context.get("scene_seed"),
                    "allow_global_help": scene_context.get("allow_global_help"),
                    "fallback_key": next((item["key"] for item in route_candidates if item["move_id"] == scene_context.get("fallback_move")), None),
                    "scene_snapshot": scene_context.get("scene_snapshot"),
                    "state_snapshot": scene_context.get("state_snapshot"),
                    "moves": [
                        {
                            "key": item["key"],
                            "label": item["label"],
                            "intents": item["intents"],
                            "synonyms": item["synonyms"],
                            "is_global": item["is_global"],
                        }
                        for item in route_candidates
                    ],
                },
                "output_schema": RouteChoiceLLM.model_json_schema(),
            },
            model=self.provider.route_model,
            temperature=self.provider.route_temperature,
            max_retries=self.provider.route_max_retries,
            timeout_seconds=self.provider.timeout_seconds,
        )
        choice = RouteChoiceLLM.model_validate(
            {
                "selected_key": payload.get("selected_key"),
                "confidence": payload.get("confidence"),
                "interpreted_intent": payload.get("interpreted_intent"),
            }
        )
        return choice, int(payload.get("_duration_ms") or 0), gateway_mode


class NarrationChain(_JsonSchemaPlayChain):
    async def render(
        self,
        *,
        narration_context: dict[str, Any],
        prompt_slots: dict[str, Any],
        style_guard: str,
    ) -> tuple[str, int | None, str]:
        gateway_mode = str(getattr(self.provider, "gateway_mode", "unknown") or "unknown")
        system_prompt = (
            "# Role & Intent\n"
            "Write concise player-facing narration from a fully determined runtime outcome.\n"
            "Return strict JSON only.\n\n"
            "# Hard Constraints\n"
            "- narration_text must be non-empty.\n"
            "- Do not invent new state changes or results.\n"
        )
        payload = await self._invoke_chain_via_provider(
            system_prompt=system_prompt,
            user_payload={
                "task": "render_runtime_narration",
                "style_guard": style_guard,
                "narration_context": narration_context,
                "prompt_slots": prompt_slots,
                "output_schema": NarrationOutput.model_json_schema(),
            },
            model=self.provider.narration_model,
            temperature=self.provider.narration_temperature,
            max_retries=self.provider.narration_max_retries,
            timeout_seconds=self.provider.timeout_seconds,
        )
        rendered = NarrationOutput.model_validate({"narration_text": payload.get("narration_text")})
        return rendered.narration_text.strip(), int(payload.get("_duration_ms") or 0), gateway_mode
