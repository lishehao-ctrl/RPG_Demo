from __future__ import annotations

DEFAULT_ENDINGS: list[dict] = [
    {
        "ending_id": "ending_forced_fail",
        "title": "Drifted Off Course",
        "outcome": "fail",
        "camp": "world",
        "epilogue": "You lost the thread of the mission, and the opportunity closed before you could recover.",
        "prompt_profile_id": "ending_default_v2",
    },
    {
        "ending_id": "ending_neutral_default",
        "title": "Quiet Exit",
        "outcome": "neutral",
        "camp": "world",
        "epilogue": "You made it through, but left with unfinished questions and modest gains.",
        "prompt_profile_id": "ending_default_v2",
    },
    {
        "ending_id": "ending_success_default",
        "title": "Mainline Secured",
        "outcome": "success",
        "camp": "world",
        "epilogue": "You held to the key thread and turned your choices into a decisive win.",
        "prompt_profile_id": "ending_default_v2",
    },
]
