from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptProfile:
    profile_id: str
    system_template: str
    user_template: str


PROFILES: dict[str, PromptProfile] = {
    "selection_mapping_v3": PromptProfile(
        profile_id="selection_mapping_v3",
        system_template=(
            "You are a strict RPG free-input selector. Return STRICT JSON only following the provided schema. "
            "You may select only IDs that exist in visible_choices_json or available_fallbacks_json. "
            "When uncertain, prefer fallback over speculative choice. "
            "When input_policy_flag=true, prefer FALLBACK_INPUT_POLICY."
        ),
        user_template=(
            "Map one player input to a decision. "
            "Context: scene_brief={scene_brief}; player_input={player_input}; "
            "input_policy_flag={input_policy_flag}; "
            "confidence_policy={confidence_policy_json}; "
            "visible_choices={visible_choices_json}; "
            "available_fallbacks={available_fallbacks_json}; "
            "retry_context={retry_context_json}."
        ),
    ),
    "fallback_default_v1": PromptProfile(
        profile_id="fallback_default_v1",
        system_template=(
            "You are an RPG narration engine. Write plain narrative text only. "
            "No JSON, no markdown, no meta terms."
        ),
        user_template=(
            "Write concise second-person narration in {language}. Keep immersion. "
            "Context: scene_from={scene_from}; scene_to={scene_to}; fallback_reason={fallback_reason}; "
            "state_delta={state_delta_brief}; player_input={player_input_excerpt}; "
            "nudge_tier={nudge_tier}; tone={tone}. "
            "Style rule: soft=gentle hint, neutral=clear redirect, firm=decisive correction. "
            "You must naturally include this mainline nudge in-world: {mainline_nudge}."
        ),
    ),
    "ending_default_v1": PromptProfile(
        profile_id="ending_default_v1",
        system_template=(
            "You are an RPG ending narrator. Return STRICT JSON only with schema "
            '{"narrative_text":"string"}. No markdown. No meta terms.'
        ),
        user_template=(
            "Write an ending paragraph in English. Context: ending_id={ending_id}; outcome={ending_outcome}; "
            "epilogue={epilogue}; scene_from={scene_from}; scene_to={scene_to}; "
            "fallback_count={fallback_count}. Keep it final and in-world."
        ),
    ),
    "ending_default_v2": PromptProfile(
        profile_id="ending_default_v2",
        system_template=(
            "You are an RPG ending narrator and chronicler. Return STRICT JSON only with schema "
            '{"narrative_text":"string","ending_report":{"title":"string","one_liner":"string",'
            '"life_summary":"string","highlights":[{"title":"string","detail":"string"}],'
            '"stats":{"total_steps":0,"fallback_count":0,"fallback_rate":0,'
            '"explicit_count":0,"rule_count":0,"llm_count":0,"fallback_source_count":0,'
            '"energy_delta":0,"money_delta":0,"knowledge_delta":0,"affection_delta":0},'
            '"persona_tags":["string"]}}. No markdown. No meta terms.'
        ),
        user_template=(
            "Language={language}. Write a final in-world ending with a concise narrative and a player life report. "
            "Context: ending_id={ending_id}; outcome={ending_outcome}; tone={tone}; epilogue={epilogue}; "
            "session_stats={session_stats_json}; recent_action_beats={recent_action_beats_json}. "
            "The report must align with the provided stats and recent beats."
        ),
    ),
}

_DEFAULT_SLOT_LIMIT = 280
_SLOT_LIMITS = {
    "session_stats_json": 1600,
    "recent_action_beats_json": 4000,
    "visible_choices_json": 2400,
    "available_fallbacks_json": 1200,
    "confidence_policy_json": 200,
    "retry_context_json": 1200,
}


def render_prompt(profile_id: str, *, slots: dict[str, object]) -> tuple[str, str]:
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise ValueError(f"unknown prompt profile: {profile_id}")

    safe_slots = {}
    for key, value in slots.items():
        limit = _SLOT_LIMITS.get(key, _DEFAULT_SLOT_LIMIT)
        safe_slots[key] = " ".join(str(value or "").split())[:limit]
    system_prompt = profile.system_template
    try:
        user_prompt = profile.user_template.format(**safe_slots)
    except KeyError as exc:
        missing = str(exc).strip("'")
        raise ValueError(f"missing prompt slot: {missing}") from exc
    return system_prompt, user_prompt
