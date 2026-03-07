from __future__ import annotations

from typing import Any

from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.llm.base import LLMProvider
from rpg_backend.runtime.initializer import initialize_session_state
from rpg_backend.runtime.step_engine import process_runtime_step
from rpg_backend.runtime.ui import list_ui_moves


class RuntimeService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def initialize_session_state(self, pack: StoryPack) -> tuple[str, int, dict[str, Any], dict[str, int]]:
        return initialize_session_state(pack)

    def list_ui_moves(self, pack: StoryPack, scene_id: str) -> list[dict[str, Any]]:
        return list_ui_moves(pack, scene_id)

    async def process_step(
        self,
        pack: StoryPack,
        current_scene_id: str,
        beat_index: int,
        state: dict[str, Any],
        beat_progress: dict[str, int],
        action_input: dict[str, Any],
        *,
        dev_mode: bool = False,
    ) -> dict[str, Any]:
        result = await process_runtime_step(
            provider=self.provider,
            pack=pack,
            current_scene_id=current_scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input=action_input,
            dev_mode=dev_mode,
        )
        return result.to_payload()
