from __future__ import annotations

DEFAULT_FALLBACKS: list[dict] = [
    {
        "fallback_id": "fb_no_match",
        "reason_code": "NO_MATCH",
        "text": "Your action lands, but the world redirects you toward a clearer path.",
        "mainline_nudge": "Try focusing on the most concrete objective in this scene to stay on the main lead.",
        "prompt_profile_id": "fallback_default_v1",
        "range_effects": [
            {
                "target_type": "player",
                "metric": "energy",
                "center": 0,
                "intensity": 1,
            }
        ],
    },
    {
        "fallback_id": "fb_low_conf",
        "reason_code": "LOW_CONF",
        "text": "The moment responds cautiously, and momentum is preserved through a safer move.",
        "mainline_nudge": "Use one of the visible scene goals to regain stronger control of the route.",
        "prompt_profile_id": "fallback_default_v1",
        "range_effects": [
            {
                "target_type": "player",
                "metric": "knowledge",
                "center": 0,
                "intensity": 1,
            }
        ],
    },
    {
        "fallback_id": "fb_input_policy",
        "reason_code": "INPUT_POLICY",
        "text": "The world ignores the unsafe framing and keeps the scene moving.",
        "mainline_nudge": "Describe an in-world action tied to the current scene objective.",
        "prompt_profile_id": "fallback_default_v1",
        "range_effects": [
            {
                "target_type": "player",
                "metric": "energy",
                "center": -1,
                "intensity": 1,
            }
        ],
    },
    {
        "fallback_id": "fb_off_topic",
        "reason_code": "OFF_TOPIC",
        "text": "Your idea is acknowledged, but events steer back to the active thread.",
        "mainline_nudge": "Pick an action connected to the current conflict to return to the mainline.",
        "prompt_profile_id": "fallback_default_v1",
        "range_effects": [
            {
                "target_type": "player",
                "metric": "affection",
                "center": 0,
                "intensity": 1,
            }
        ],
    },
]
