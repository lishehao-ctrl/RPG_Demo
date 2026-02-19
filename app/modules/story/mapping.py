from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class MappingCandidate:
    choice_id: str
    score: float


@dataclass(frozen=True)
class MappingResult:
    ranked_candidates: list[MappingCandidate]
    confidence: float
    note: str | None = None


class MappingAdapter(Protocol):
    def map_input(self, player_input: str, choices: list[dict], state: dict | None = None) -> MappingResult:
        ...


class RuleBasedMappingAdapter:
    """Deterministic rule-based mapper for story choices.

    This adapter intentionally keeps mapping deterministic and side-effect free.
    It can use a compiled proposed action (if supplied in state) and label overlap
    signals to rank candidates, while leaving reason selection to the caller.
    """

    @staticmethod
    def _canonical_params(params: dict | None) -> str:
        return json.dumps((params or {}), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @classmethod
    def _tokens(cls, value: Any) -> set[str]:
        return set(_TOKEN_RE.findall(cls._normalize_text(value)))

    @classmethod
    def _label_tokens(cls, choice: dict) -> set[str]:
        tokens: set[str] = set()
        tokens |= cls._tokens(choice.get("display_text"))

        aliases = choice.get("aliases")
        if isinstance(aliases, list):
            for alias in aliases:
                tokens |= cls._tokens(alias)

        action = choice.get("action") or {}
        tokens |= cls._tokens(action.get("action_id"))
        params = action.get("params")
        if isinstance(params, dict):
            for key in sorted(params):
                tokens |= cls._tokens(key)
                tokens |= cls._tokens(params.get(key))
        return tokens

    @classmethod
    def _token_overlap_score(cls, input_tokens: set[str], choice_tokens: set[str]) -> float:
        if not input_tokens or not choice_tokens:
            return 0.0
        overlap = input_tokens & choice_tokens
        if not overlap:
            return 0.0
        return float(len(overlap)) / float(len(input_tokens))

    def map_input(self, player_input: str, choices: list[dict], state: dict | None = None) -> MappingResult:
        state = state or {}
        normalized_input = self._normalize_text(player_input)
        input_tokens = self._tokens(player_input)
        proposed_action = state.get("proposed_action") if isinstance(state, dict) else None
        if not isinstance(proposed_action, dict):
            proposed_action = None

        proposed_action_id = str((proposed_action or {}).get("action_id") or "")
        proposed_params_sig = self._canonical_params((proposed_action or {}).get("params") or {})

        ranked: list[MappingCandidate] = []

        for choice in (choices or []):
            if not isinstance(choice, dict):
                continue
            choice_id = str(choice.get("choice_id") or "")
            if not choice_id:
                continue

            choice_action = choice.get("action") or {}
            choice_action_id = str(choice_action.get("action_id") or "")
            choice_params_sig = self._canonical_params(choice_action.get("params") or {})

            action_signature_match = (
                bool(proposed_action_id)
                and choice_action_id == proposed_action_id
                and choice_params_sig == proposed_params_sig
            )

            # Preserve historical resolver semantics: when proposed_action exists,
            # only exact action-signature candidates are considered.
            if proposed_action_id and not action_signature_match:
                continue

            score = 0.0
            if action_signature_match:
                score += 1.0

            display_text = self._normalize_text(choice.get("display_text"))
            if normalized_input and display_text and normalized_input == display_text:
                score += 0.2

            overlap = self._token_overlap_score(input_tokens, self._label_tokens(choice))
            score += overlap * 0.2

            if not proposed_action_id and score <= 0.0:
                continue
            if score <= 0.0:
                continue

            ranked.append(MappingCandidate(choice_id=choice_id, score=round(score, 6)))

        ranked.sort(key=lambda c: (-c.score, c.choice_id))

        if not ranked:
            return MappingResult(ranked_candidates=[], confidence=0.0, note=None)

        note = None
        if len(ranked) > 1 and abs(ranked[0].score - ranked[1].score) <= 1e-9:
            note = "AMBIGUOUS_FIRST_MATCH"

        top_score = ranked[0].score
        confidence = max(0.0, min(1.0, float(top_score)))
        return MappingResult(ranked_candidates=ranked, confidence=confidence, note=note)
