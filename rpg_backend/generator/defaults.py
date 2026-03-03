from __future__ import annotations

NPC_RED_LINE_TEMPLATES: tuple[str, ...] = (
    "Do not sacrifice civilian corridors for short-term speed.",
    "Do not erase operational evidence under political pressure.",
    "Do not allow command ambiguity to paralyze response.",
    "Do not deplete critical reserves before the final push.",
    "Do not trade long-term trust for one-step convenience.",
)


def default_npc_red_line(name: str, idx: int) -> str:
    template = NPC_RED_LINE_TEMPLATES[idx % len(NPC_RED_LINE_TEMPLATES)]
    return f"{name}: {template}"
