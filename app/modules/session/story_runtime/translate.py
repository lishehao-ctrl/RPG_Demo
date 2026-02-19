from __future__ import annotations


def build_choice_resolution_matched_rules(
    *,
    attempted_choice_id: str | None,
    executed_choice_id: str,
    resolved_choice_id: str,
    fallback_reason_code: str | None,
    mapping_confidence: float | None,
    mapping_note: str | None,
) -> list[dict]:
    return [
        {
            "type": "choice_resolution",
            "attempted": attempted_choice_id,
            "executed": executed_choice_id,
            "resolved": resolved_choice_id,
            "reason": fallback_reason_code,
            "confidence": mapping_confidence,
            "mapping_note": mapping_note,
        }
    ]


def build_story_step_response_payload(
    *,
    story_node_id: str,
    attempted_choice_id: str | None,
    executed_choice_id: str,
    resolved_choice_id: str,
    fallback_used: bool,
    fallback_reason: str | None,
    mapping_confidence: float | None,
    narrative_text: str,
    choices: list[dict],
    tokens_in: int,
    tokens_out: int,
    provider_name: str,
) -> dict:
    return {
        "story_node_id": story_node_id,
        "attempted_choice_id": attempted_choice_id,
        "executed_choice_id": executed_choice_id,
        "resolved_choice_id": resolved_choice_id,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "mapping_confidence": mapping_confidence,
        "narrative_text": narrative_text,
        "choices": choices,
        "cost": {"tokens_in": tokens_in, "tokens_out": tokens_out, "provider": provider_name},
    }
