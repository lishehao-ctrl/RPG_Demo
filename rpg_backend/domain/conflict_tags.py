from __future__ import annotations

from typing import Literal

NPCConflictTag = Literal[
    "anti_noise",
    "anti_speed",
    "anti_resource_burn",
]

NPC_CONFLICT_TAGS: tuple[NPCConflictTag, ...] = (
    "anti_noise",
    "anti_speed",
    "anti_resource_burn",
)

NPC_CONFLICT_TAG_CATALOG: dict[NPCConflictTag, str] = {
    "anti_noise": "Rejects noisy, trust-eroding shortcuts and messy escalation.",
    "anti_speed": "Rejects slow pacing that burns decision windows and urgency.",
    "anti_resource_burn": "Rejects heavy resource burn and reserve depletion.",
}
