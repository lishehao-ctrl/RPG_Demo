from __future__ import annotations

import re
from typing import Any

from app.domain.constants import GLOBAL_HELP_ME_PROGRESS_MOVE_ID
from app.llm.base import LLMProvider, RouteIntentResult


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))


class FakeProvider(LLMProvider):
    @property
    def runtime_failfast_on_route_error(self) -> bool:
        return False

    @property
    def runtime_failfast_on_narration_error(self) -> bool:
        return False

    def route_intent(self, scene_context: dict[str, Any], text: str) -> RouteIntentResult:
        move_contexts = scene_context.get("moves", [])
        fallback = scene_context.get("fallback_move", GLOBAL_HELP_ME_PROGRESS_MOVE_ID)

        stripped = (text or "").strip()
        if not stripped:
            return RouteIntentResult(
                move_id=fallback,
                args={},
                confidence=0.2,
                interpreted_intent="unclear intent",
            )

        query_tokens = _tokenize(stripped)
        best_move = None
        best_score = 0

        for move in move_contexts:
            terms = {move.get("id", "").lower(), move.get("label", "").lower()}
            terms.update(item.lower() for item in move.get("intents", []))
            terms.update(item.lower() for item in move.get("synonyms", []))
            normalized_terms: set[str] = set()
            for term in terms:
                normalized_terms.update(_tokenize(term))

            score = len(query_tokens & normalized_terms)
            if score > best_score:
                best_score = score
                best_move = move

        if best_move is None or best_score == 0:
            return RouteIntentResult(
                move_id=fallback,
                args={},
                confidence=0.3,
                interpreted_intent=stripped,
            )

        confidence = min(0.95, 0.55 + 0.12 * best_score)
        return RouteIntentResult(
            move_id=best_move["id"],
            args={},
            confidence=confidence,
            interpreted_intent=stripped,
        )

    def render_narration(self, slots: dict[str, Any], style_guard: str) -> str:
        echo = slots.get("echo", "You act decisively.")
        commit = slots.get("commit", "The world shifts in response.")
        hook = slots.get("hook", "A new choice opens.")
        return f"{echo} {commit} {hook}".strip()
