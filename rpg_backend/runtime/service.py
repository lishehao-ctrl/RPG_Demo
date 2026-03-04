from __future__ import annotations

from typing import Any

from rpg_backend.domain.pack_schema import Move, NPCProfile, Scene, StoryPack
from rpg_backend.llm.base import LLMProvider
from rpg_backend.runtime.effects import apply_effects
from rpg_backend.runtime.narration import render_echo_commit_hook
from rpg_backend.runtime.resolver import choose_outcome, resolve_next_scene
from rpg_backend.runtime.router import route_player_action

_STRATEGY_RISK_HINTS = {
    "fast_dirty": "fast but dirty: raises noise and trust risk",
    "steady_slow": "steady but slow: lowers noise but spends time",
    "political_safe_resource_heavy": "politically safe: spends resources to preserve trust",
}
_STYLE_CONFLICT_TAG: dict[str, str] = {
    "fast_dirty": "anti_noise",
    "steady_slow": "anti_speed",
    "political_safe_resource_heavy": "anti_resource_burn",
}


class RuntimeService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    @staticmethod
    def _scene_map(pack: StoryPack) -> dict[str, Scene]:
        return {scene.id: scene for scene in pack.scenes}

    @staticmethod
    def _move_map(pack: StoryPack) -> dict[str, Move]:
        return {move.id: move for move in pack.moves}

    @staticmethod
    def _beat_index_by_id(pack: StoryPack) -> dict[str, int]:
        return {beat.id: idx for idx, beat in enumerate(pack.beats)}

    @staticmethod
    def _npc_profile_map(pack: StoryPack) -> dict[str, NPCProfile]:
        return {profile.name: profile for profile in pack.npc_profiles}

    @staticmethod
    def _classify_stance(trust_value: int) -> str:
        if trust_value >= 2:
            return "support"
        if trust_value <= -2:
            return "oppose"
        return "contested"

    @staticmethod
    def _style_conflicts_profile(strategy_style: str, conflict_tags: list[str]) -> bool:
        required_tag = _STYLE_CONFLICT_TAG.get(strategy_style)
        if not required_tag:
            return False
        return required_tag in set(conflict_tags)

    def _apply_npc_stance_effects(
        self,
        *,
        state: dict[str, Any],
        present_npcs: list[str],
        strategy_style: str,
        npc_profiles: dict[str, NPCProfile],
    ) -> dict[str, Any]:
        state.setdefault("values", {})
        state.setdefault("events", [])
        values = state["values"]

        support: list[str] = []
        oppose: list[str] = []
        contested: list[str] = []
        red_line_hits: list[str] = []

        for npc_name in present_npcs:
            profile = npc_profiles.get(npc_name)
            if profile is None:
                continue
            trust_key = f"npc_trust::{npc_name}"
            current = int(values.get(trust_key, 0))
            conflict = self._style_conflicts_profile(strategy_style, list(profile.conflict_tags))
            delta = -2 if conflict else 1
            values[trust_key] = current + delta
            if conflict:
                red_line_hits.append(npc_name)
                event_key = f"redline_hit::{npc_name}"
                if event_key not in state["events"]:
                    state["events"].append(event_key)

            stance = self._classify_stance(int(values[trust_key]))
            if stance == "support":
                support.append(npc_name)
            elif stance == "oppose":
                oppose.append(npc_name)
            else:
                contested.append(npc_name)

        return {
            "support": support,
            "oppose": oppose,
            "contested": contested,
            "red_line_hits": red_line_hits,
        }

    def _build_stance_summary(self, stance_snapshot: dict[str, Any]) -> str:
        support = stance_snapshot.get("support", [])
        oppose = stance_snapshot.get("oppose", [])
        red_line_hits = stance_snapshot.get("red_line_hits", [])

        support_text = ", ".join(support[:2]) if support else "none"
        oppose_text = ", ".join(oppose[:2]) if oppose else "none"
        redline_text = ", ".join(red_line_hits[:2]) if red_line_hits else "none"
        return (
            f"Stance update: supporters={support_text}; opponents={oppose_text}; "
            f"red-line pressure={redline_text}."
        )

    def _apply_pressure_recoil(
        self,
        *,
        pack: StoryPack,
        beat_index: int,
        state: dict[str, Any],
        costs: list[str],
        consequences: list[str],
    ) -> bool:
        if beat_index < max(len(pack.beats) - 2, 0):
            return False

        values = state.setdefault("values", {})
        events = state.setdefault("events", [])
        turn = int(values.get("runtime_turn", 0))
        triggered = False

        recoil_specs = (
            (
                "public_trust",
                lambda val: int(val) <= -3,
                "pressure_recoil.public_trust",
                "Pressure recoil: public trust backlash limits your maneuvering room.",
            ),
            (
                "resource_stress",
                lambda val: int(val) >= 4,
                "pressure_recoil.resource_stress",
                "Pressure recoil: resource stress forces emergency rationing.",
            ),
            (
                "coordination_noise",
                lambda val: int(val) >= 4,
                "pressure_recoil.coordination_noise",
                "Pressure recoil: coordination noise creates command drift.",
            ),
        )

        for track_key, predicate, event_key, message in recoil_specs:
            current_val = int(values.get(track_key, 0))
            if not predicate(current_val):
                continue

            cooldown_key = f"recoil_last_turn::{track_key}"
            last_turn = int(values.get(cooldown_key, -999))
            if turn - last_turn < 2:
                continue

            values[cooldown_key] = turn
            if event_key not in events:
                events.append(event_key)
            values["cost_total"] = int(values.get("cost_total", 0)) + 1
            costs.append("Pressure recoil +1")
            consequences.append(message)
            triggered = True

        return triggered

    def initialize_session_state(self, pack: StoryPack) -> tuple[str, int, dict[str, Any], dict[str, int]]:
        first_beat = pack.beats[0]
        beat_progress = {beat.id: 0 for beat in pack.beats}
        state = {
            "events": [],
            "inventory": [],
            "flags": {},
            "values": {
                "cost_total": 0,
                "public_trust": 0,
                "resource_stress": 0,
                "coordination_noise": 0,
                "time_spent": 0,
                "runtime_turn": 0,
            },
        }
        for profile in pack.npc_profiles:
            state["values"][f"npc_trust::{profile.name}"] = 0
        return first_beat.entry_scene_id, 0, state, beat_progress

    def list_ui_moves(self, pack: StoryPack, scene_id: str) -> list[dict[str, Any]]:
        scene_map = self._scene_map(pack)
        move_map = self._move_map(pack)
        scene = scene_map[scene_id]
        move_ids = list(dict.fromkeys(scene.enabled_moves + scene.always_available_moves))
        ui_moves = []
        for move_id in move_ids:
            move = move_map.get(move_id)
            if move is None:
                continue
            ui_moves.append(
                {
                    "move_id": move.id,
                    "label": move.label,
                    "risk_hint": _STRATEGY_RISK_HINTS.get(move.strategy_style, "has fail-forward consequences"),
                }
            )
        return ui_moves

    def process_step(
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
        scene_map = self._scene_map(pack)
        move_map = self._move_map(pack)
        beat_index_by_id = self._beat_index_by_id(pack)
        npc_profiles = self._npc_profile_map(pack)

        scene = scene_map[current_scene_id]
        current_beat = pack.beats[beat_index] if 0 <= beat_index < len(pack.beats) else None
        recognized = route_player_action(
            self.provider,
            scene,
            move_map,
            action_input,
            state=state,
            beat_progress=beat_progress,
            beat=current_beat,
            beat_index=beat_index,
        )
        chosen_move = move_map[recognized["move_id"]]

        state.setdefault("values", {})
        state["values"]["last_move"] = chosen_move.id
        state["values"]["runtime_turn"] = int(state["values"].get("runtime_turn", 0)) + 1
        runtime_turn = int(state["values"]["runtime_turn"])

        current_beat_id = scene.beat_id
        outcome = choose_outcome(chosen_move, state, beat_progress, current_beat_id)
        costs, consequences, _ = apply_effects(outcome.effects, state, beat_progress, current_beat_id)

        stance_snapshot = self._apply_npc_stance_effects(
            state=state,
            present_npcs=list(scene.present_npcs),
            strategy_style=chosen_move.strategy_style,
            npc_profiles=npc_profiles,
        )
        pressure_recoil_triggered = self._apply_pressure_recoil(
            pack=pack,
            beat_index=beat_index,
            state=state,
            costs=costs,
            consequences=consequences,
        )

        next_scene_id, ended = resolve_next_scene(scene, outcome, state, beat_progress, current_beat_id)
        if next_scene_id is not None:
            current_scene_id = next_scene_id

        next_scene = scene_map[current_scene_id]
        beat_index = beat_index_by_id[next_scene.beat_id]

        stance_summary = self._build_stance_summary(stance_snapshot) if runtime_turn % 2 == 0 else None
        narration_text = render_echo_commit_hook(
            self.provider,
            outcome.narration_slots,
            recognized["interpreted_intent"],
            outcome.result,
            pack.style_guard,
            strategy_style=chosen_move.strategy_style,
            stance_summary=stance_summary,
        )

        response = {
            "scene_id": current_scene_id,
            "beat_index": beat_index,
            "ended": ended,
            "narration_text": narration_text,
            "recognized": recognized,
            "resolution": {
                "result": outcome.result,
                "costs_summary": "; ".join(costs) if costs else "none",
                "consequences_summary": "; ".join(consequences) if consequences else "none",
            },
            "ui": {
                "moves": self.list_ui_moves(pack, current_scene_id),
                "input_hint": pack.input_hint,
            },
        }

        if dev_mode:
            response["debug"] = {
                "selected_move": chosen_move.id,
                "selected_outcome": outcome.id,
                "selected_strategy_style": chosen_move.strategy_style,
                "pressure_recoil_triggered": pressure_recoil_triggered,
                "stance_snapshot": stance_snapshot,
                "state": state,
                "beat_progress": beat_progress,
            }

        return response
