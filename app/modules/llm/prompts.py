import json

def build_repair_prompt(raw_text: str) -> str:
    return (
        "Fix JSON to match schema exactly: {narrative_text:string, choices:[{id,text,type(dialog|action)}]}. "
        "No extra keys. Return JSON only. Source:\n"
        + raw_text
    )


def build_fallback_polish_prompt(ctx: dict, skeleton_text: str) -> str:
    reason = str((ctx or {}).get("fallback_reason") or "")
    locale = str((ctx or {}).get("locale") or "en")
    choice_labels = [
        str(item.get("label") or "")
        for item in ((ctx or {}).get("visible_choices") or [])
        if isinstance(item, dict) and item.get("label")
    ]
    end_rule = (
        "End with exactly one clarifying question."
        if reason in {"FALLBACK"}
        else "End with a gentle nudge that references available options by label only."
    )
    payload = {
        "locale": locale,
        "fallback_reason": reason,
        "node_id": (ctx or {}).get("node_id"),
        "player_input": (ctx or {}).get("player_input", ""),
        "mapping_note": (ctx or {}).get("mapping_note", ""),
        "attempted_choice_id": (ctx or {}).get("attempted_choice_id"),
        "attempted_choice_label": (ctx or {}).get("attempted_choice_label"),
        "visible_choice_labels": choice_labels,
        "state_snippet": (ctx or {}).get("state_snippet", {}),
        "short_recent_summary": (ctx or {}).get("short_recent_summary", []),
    }
    return (
        "Fallback rewrite task. Return JSON only with schema: "
        "{narrative_text:string, choices:[{id,text,type(dialog|action)}]} and 2-4 choices. "
        "Rewrite the provided skeleton text into natural in-world wording. Preserve meaning and outcome exactly. "
        "Do NOT add new facts, events, entities, items, rules, or state changes. "
        "Do NOT advance the story. "
        "Do NOT output internal tokens/codes/ids including NO_INPUT, BLOCKED, FALLBACK, "
        "INVALID_CHOICE_ID, NO_MATCH, LLM_PARSE_ERROR, PREREQ_BLOCKED, next_node_id, __fallback__, "
        "choice_id, intent_id, confidence, delta_scale. "
        "Keep key terms from the skeleton text present; do not replace those key terms with synonyms. "
        f"Write narrative_text in locale '{locale}'. {end_rule} "
        "Use visible choice labels only, never choice ids. "
        "Context JSON: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + " Skeleton: "
        + skeleton_text
    )


def build_story_selection_prompt(
    *,
    player_input: str,
    valid_choice_ids: list[str],
    visible_choices: list[dict],
    intents: list[dict] | None = None,
    state_snippet: dict | None = None,
) -> str:
    payload = {
        "player_input": player_input,
        "valid_choice_ids": sorted({str(cid) for cid in valid_choice_ids if str(cid)}),
        "visible_choices": [
            {
                "choice_id": str(choice.get("choice_id") or ""),
                "display_text": str(choice.get("display_text") or ""),
            }
            for choice in (visible_choices or [])
            if isinstance(choice, dict)
        ],
        "intents": [
            {
                "intent_id": str(intent.get("intent_id") or ""),
                "alias_choice_id": str(intent.get("alias_choice_id") or ""),
                "description": str(intent.get("description") or ""),
                "patterns": [
                    str(pattern)
                    for pattern in (intent.get("patterns") or [])
                    if str(pattern).strip()
                ],
            }
            for intent in (intents or [])
            if isinstance(intent, dict)
        ],
        "state": state_snippet or {},
    }
    return (
        "Story selection task. Return JSON only with schema: "
        "{choice_id:string|null,use_fallback:boolean,confidence:number,intent_id:string|null,notes:string|null}. "
        "Use intents only for mapping and always output a visible choice_id from valid_choice_ids when not falling back. "
        "If selection is uncertain or none fits, set use_fallback=true and choice_id=null. "
        "choice_id must be from valid_choice_ids only. Context: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def build_story_narration_prompt(payload: dict) -> str:
    return "Story node transition narration only. " + json.dumps(payload, ensure_ascii=False)
