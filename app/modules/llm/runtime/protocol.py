from __future__ import annotations

from app.modules.llm.prompts import PromptEnvelope


def protocol_messages(envelope: PromptEnvelope | None) -> list[dict] | None:
    if not isinstance(envelope, PromptEnvelope):
        return None
    return envelope.to_messages()
