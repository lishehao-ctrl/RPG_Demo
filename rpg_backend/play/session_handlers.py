from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rpg_backend.play.contracts import PlaySessionSnapshot, PlayTurnRequest

if TYPE_CHECKING:
    from rpg_backend.play.service import PlaySessionService, _PlaySessionRecord


@dataclass(frozen=True)
class V2PlaySessionHandler:
    service: PlaySessionService

    def submit_turn(self, *, session_id: str, record: _PlaySessionRecord, request: PlayTurnRequest) -> PlaySessionSnapshot:
        return self.service._submit_turn_v2(session_id=session_id, record=record, request=request)


@dataclass(frozen=True)
class LegacyPlaySessionHandler:
    service: PlaySessionService

    def submit_turn(self, *, session_id: str, record: _PlaySessionRecord, request: PlayTurnRequest) -> PlaySessionSnapshot:
        return self.service._submit_turn_legacy(session_id=session_id, record=record, request=request)

