from __future__ import annotations

import pytest

from app.modules.llm_boundary.schemas import SelectionMappingOutputV3
from app.modules.runtime.service import _SelectionResolutionError, _resolve_selection_decision_v3
from app.modules.story_domain.schemas import GlobalFallbackV2


def _fallback(*, fallback_id: str, reason_code: str | None) -> GlobalFallbackV2:
    return GlobalFallbackV2.model_validate(
        {
            "fallback_id": fallback_id,
            "text": "fallback",
            "reason_code": reason_code,
            "range_effects": [
                {
                    "target_type": "player",
                    "metric": "energy",
                    "center": 0,
                    "intensity": 1,
                }
            ],
        }
    )


def test_selection_v3_schema_accepts_valid_payload() -> None:
    out = SelectionMappingOutputV3.model_validate(
        {
            "schema_version": "3.0",
            "decision_code": "SELECT_CHOICE",
            "target_type": "choice",
            "target_id": "c_study",
            "confidence": 0.91,
            "intensity_tier": 1,
            "fallback_reason_code": None,
            "reason": "intent-match",
            "top_candidates": [
                {"target_type": "choice", "target_id": "c_study", "confidence": 0.91},
                {"target_type": "fallback", "target_id": "fb_no_match", "confidence": 0.2},
            ],
        }
    )
    assert out.schema_version == "3.0"
    assert out.decision_code == "SELECT_CHOICE"
    assert out.target_type == "choice"


def test_selection_v3_schema_rejects_inconsistent_decision_target_type() -> None:
    mapping = SelectionMappingOutputV3.model_validate(
        {
            "schema_version": "3.0",
            "decision_code": "SELECT_CHOICE",
            "target_type": "fallback",
            "target_id": "fb_no_match",
            "confidence": 0.7,
            "intensity_tier": 0,
            "fallback_reason_code": "NO_MATCH",
            "reason": None,
            "top_candidates": [{"target_type": "fallback", "target_id": "fb_no_match", "confidence": 0.7}],
        }
    )

    choice_by_id = {"c_study": {"choice_id": "c_study", "next_node_id": "n1"}}
    fallback_by_id = {"fb_no_match": _fallback(fallback_id="fb_no_match", reason_code="NO_MATCH")}
    with pytest.raises(_SelectionResolutionError) as exc:
        _resolve_selection_decision_v3(
            llm_mapping=mapping,
            choice_by_id=choice_by_id,
            fallback_by_id=fallback_by_id,
            input_policy_flag=False,
            confidence_high=0.65,
            confidence_low=0.45,
        )
    assert exc.value.code == "SCHEMA_INCONSISTENT"
