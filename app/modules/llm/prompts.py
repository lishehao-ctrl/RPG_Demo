import json

from app.modules.affection.rules import RULE_MAP


def build_classification_prompt(text: str) -> str:
    allowed_tags = sorted(RULE_MAP.keys())
    return (
        "You are a strict JSON classifier. Output JSON only. "
        "Schema: {intent,tone,behavior_tags,risk_tags,confidence}. "
        "intent in [neutral,romantic,hostile,friendly]; tone in [calm,warm,harsh,serious]. "
        f"behavior_tags must be subset of {allowed_tags}. "
        f"Input: {text}"
    )


def build_narrative_prompt(
    *,
    memory_summary: str,
    branch_result: dict,
    character_compact: list[dict],
    player_input: str,
    classification: dict,
    behavior_policy: dict | None = None,
    emotion_state: dict | None = None,
) -> str:
    payload = {
        "memory_summary": memory_summary,
        "branch_result": branch_result,
        "characters": character_compact,
        "player_input": player_input,
        "classification": classification,
        "behavior_policy": behavior_policy or {},
        "emotion_state": emotion_state or {},
    }
    return (
        "Return JSON only with schema: {narrative_text:string, choices:[{id,text,type(dialog|action)}]}"
        " with 2-4 choices. Keep safe tone. If unsafe, provide safe narrative and generic choices. "
        + json.dumps(payload, ensure_ascii=False)
    )


def build_repair_prompt(raw_text: str) -> str:
    return (
        "Fix JSON to match schema exactly: {narrative_text:string, choices:[{id,text,type(dialog|action)}]}. "
        "No extra keys. Return JSON only. Source:\n"
        + raw_text
    )
