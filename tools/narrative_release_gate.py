from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from rpg_backend.config import get_settings
from rpg_backend.narrative.contracts import (
    AdvanceTurnRequest,
    AdvisorAskRequest,
    CreateTemplateRequest,
)
from rpg_backend.narrative.gateway import get_narrative_gateway
from rpg_backend.narrative.repository import NarrativeRepository
from rpg_backend.narrative.service import NarrativeService
from rpg_backend.responses_transport import ResponsesJSONResponse


DEFAULT_SEED = (
    "A scholarship finalist returns to the academy that expelled her brother and discovers "
    "the selection committee is hiding the original witness ledger."
)
DEFAULT_FIRST_TURN_INPUT = (
    "I ask the dean to read the ledger timestamp aloud before anyone can move the files."
)


@dataclass(frozen=True)
class NarrativeReleaseGateConfig:
    mode: Literal["fake", "live"]
    db_path: Path | None
    seed: str
    first_turn_input: str
    output_path: Path | None


class FakeNarrativeGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def invoke_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        operation_name: str,
        max_output_tokens: int | None = 1500,
    ) -> ResponsesJSONResponse:
        del system_prompt, max_output_tokens
        with self._lock:
            self.calls.append(
                {
                    "operation_name": operation_name,
                    "user_payload": user_payload,
                }
            )
            call_index = len(self.calls)
        return ResponsesJSONResponse(
            payload=self._payload_for(operation_name, user_payload),
            response_id=f"fake_narrative_{call_index}",
            usage={"input_tokens": 100, "output_tokens": 80, "total_tokens": 180},
            input_characters=len(json.dumps(user_payload, ensure_ascii=False)),
        )

    def _payload_for(self, operation_name: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        if operation_name == "narrative.opening":
            return _fake_opening_payload()
        if operation_name == "narrative.advance_turn":
            return _fake_turn_payload(user_payload)
        if operation_name == "narrative.advisor":
            return {
                "reply": (
                    "I am reading the room through what you told me: the dean is stalling, "
                    "not searching. Keep the ledger visible and make someone else confirm the time."
                )
            }
        if operation_name == "narrative.ending":
            return {
                "ending_passage": (
                    "The committee room does not explode; it empties. One by one, the adults who "
                    "hid behind procedure look down at the ledger and understand that the old story "
                    "will not survive daylight. You leave without raising your voice. Behind you, the "
                    "recorder keeps running, catching the dean's apology before he can polish it into "
                    "a statement."
                ),
                "ending_label": "自由",
                "ending_subtitle": "I walked out with the truth.",
            }
        if operation_name == "narrative.highlights":
            return {
                "highlights": [
                    {
                        "beat_ord": 0,
                        "headline": "The ledger appears",
                        "body_excerpt": "The archive room smells of rain and old varnish.",
                        "why_pivotal": "The run starts with concrete evidence already in play.",
                    },
                    {
                        "beat_ord": 2,
                        "headline": "The dean stalls",
                        "body_excerpt": "The dean folds his hand over the folder without touching it.",
                        "why_pivotal": "The first choice turns hesitation into public pressure.",
                    },
                    {
                        "beat_ord": 4,
                        "headline": "Mara looks up",
                        "body_excerpt": "Mara's pen stops moving when you name the timestamp.",
                        "why_pivotal": "A witness shifts from passive observer to possible ally.",
                    },
                    {
                        "beat_ord": 6,
                        "headline": "The seal breaks",
                        "body_excerpt": "The torn seal leaves a red crescent on the table.",
                        "why_pivotal": "The hidden record becomes impossible to bury again.",
                    },
                    {
                        "beat_ord": 8,
                        "headline": "Procedure fails",
                        "body_excerpt": "No one reaches for the door when the recorder light turns red.",
                        "why_pivotal": "The ending is earned by forcing accountability into the room.",
                    },
                ]
            }
        if operation_name == "narrative.branches":
            return {
                "branches": [
                    {
                        "pivot_beat_ord": 2,
                        "chosen_path_summary": "Kept the ledger public",
                        "alternate_path_summary": "Handed it to Mara privately",
                        "alternate_ending_label": "同谋",
                        "rationale": "That path likely trades public truth for a quiet alliance.",
                    },
                    {
                        "pivot_beat_ord": 4,
                        "chosen_path_summary": "Pressed the timestamp",
                        "alternate_path_summary": "Let the dean adjourn",
                        "alternate_ending_label": "决裂",
                        "rationale": "Delay would let the committee close ranks and isolate you.",
                    },
                ]
            }
        raise AssertionError(f"unexpected fake narrative operation: {operation_name}")


def _fake_opening_payload() -> dict[str, Any]:
    return {
        "title": "The Ledger Room",
        "advisor_persona": (
            "June Park, your former debate partner, is in a train station cafe reviewing grant "
            "notes; she texts quickly, notices evasions, and keeps you grounded from outside the room."
        ),
        "cast": [
            {
                "character_id": "dean_hale",
                "display_name": "Dean Hale",
                "role": "Academy dean",
                "relation_to_protagonist": "He chaired the hearing that expelled your brother.",
                "hidden_objective": "Keep the scholarship board from reopening the old witness record.",
                "leverage_over_player": "He can delay your finalist interview until the award closes.",
                "leverages_over_other_npcs": [
                    {
                        "target_npc_id": "mara_voss",
                        "leverage": "He knows she signed the wrong archive checkout sheet.",
                    },
                    {
                        "target_npc_id": "jonas_reed",
                        "leverage": "He can expose Jonas's private donor memo.",
                    },
                ],
            },
            {
                "character_id": "mara_voss",
                "display_name": "Mara Voss",
                "role": "Records officer",
                "relation_to_protagonist": "She handled your brother's file on the night it vanished.",
                "hidden_objective": "Survive the audit without admitting she copied the ledger.",
                "leverage_over_player": "She knows your application omitted one disciplinary note.",
                "leverages_over_other_npcs": [
                    {
                        "target_npc_id": "dean_hale",
                        "leverage": "She kept a photo of Hale entering the archive after hours.",
                    },
                    {
                        "target_npc_id": "jonas_reed",
                        "leverage": "She has Jonas's message asking her to backdate a form.",
                    },
                ],
            },
            {
                "character_id": "jonas_reed",
                "display_name": "Jonas Reed",
                "role": "Scholarship donor liaison",
                "relation_to_protagonist": "He needs your public gratitude for tomorrow's ceremony.",
                "hidden_objective": "Protect the donor's son from being named in the original complaint.",
                "leverage_over_player": "He can leak that your family accepted emergency tuition aid.",
                "leverages_over_other_npcs": [
                    {
                        "target_npc_id": "dean_hale",
                        "leverage": "He has the dean's signed request to suppress the appeal.",
                    },
                    {
                        "target_npc_id": "mara_voss",
                        "leverage": "He knows Mara stored a duplicate ledger at home.",
                    },
                ],
            },
        ],
        "player_goals": [
            {
                "goal": "Force the committee to read the original ledger",
                "stakes": "Your brother's expulsion remains official if the record stays buried.",
            },
            {
                "goal": "Keep your finalist interview alive",
                "stakes": "Losing the award would end your chance to return on your own terms.",
            },
        ],
        "failure_conditions": [
            {
                "label": "Destroy Evidence",
                "description": "The player gives up or destroys the only ledger copy before it is witnessed.",
            },
            {
                "label": "Public Threat",
                "description": "The player threatens violence in front of the full scholarship committee.",
            },
            {
                "label": "False Confession",
                "description": "The player publicly accepts blame for altering the witness record.",
            },
        ],
        "player_role_options": [
            {
                "role_id": "returning_finalist",
                "label": "Returning Finalist",
                "public_persona": "You are a brilliant finalist who looks composed enough to make adults relax.",
                "hidden_objective": "Clear your brother without losing the scholarship board's vote.",
                "leverages_over_npcs": [
                    {
                        "npc_id": "dean_hale",
                        "leverage": "You have a recording of Hale calling the ledger inconvenient.",
                    }
                ],
                "starting_assets": ["sealed ledger copy", "phone recorder"],
            },
            {
                "role_id": "quiet_witness",
                "label": "Quiet Witness",
                "public_persona": "You look like the least powerful person in the room, invited only to listen.",
                "hidden_objective": "Make Mara admit who ordered the archive swap.",
                "leverages_over_npcs": [
                    {
                        "npc_id": "mara_voss",
                        "leverage": "You saw Mara photograph the checkout sheet.",
                    }
                ],
                "starting_assets": ["archive keycard"],
            },
            {
                "role_id": "donor_proxy",
                "label": "Donor Proxy",
                "public_persona": "You are treated as a grateful scholarship candidate aligned with Jonas.",
                "hidden_objective": "Turn Jonas's donor network against the cover-up.",
                "leverages_over_npcs": [
                    {
                        "npc_id": "jonas_reed",
                        "leverage": "You have Jonas's backdated donor email.",
                    }
                ],
                "starting_assets": ["printed donor memo"],
            },
        ],
        "opening_passage": (
            "The archive room smells of rain and old varnish. Dean Hale stands between you and the "
            "long table, his smile fixed so carefully it looks borrowed. Mara Voss keeps her pen moving "
            "even after the meeting has begun, while Jonas Reed watches the sealed folder in your hand "
            "as if it might start speaking first. The scholarship clock on the wall clicks toward noon. "
            "Everyone is waiting for you to make the first mistake."
        ),
        "options": [
            {
                "label": "Place the sealed ledger on the table",
                "hint": "Open with evidence, not accusation.",
                "handle": "place ledger",
            },
            {
                "label": "Ask Mara who checked out the file",
                "hint": "Pull the quietest person into the center.",
                "handle": "ask Mara",
            },
            {
                "label": "Let Jonas speak before you answer",
                "hint": "Give the room a chance to reveal its plan.",
                "handle": "let Jonas",
            },
        ],
    }


def _fake_turn_payload(user_payload: dict[str, Any]) -> dict[str, Any]:
    turn_index = int(user_payload.get("turn_index") or 0)
    cast = list(user_payload.get("cast") or [])
    pulses = [
        {
            "npc_id": str(member.get("character_id")),
            "state": "measuring the damage",
            "shift": "wary" if index != 1 else "warmer",
            "reason": "Your last move made the ledger harder to hide.",
        }
        for index, member in enumerate(cast[:3])
        if isinstance(member, dict)
    ]
    return {
        "passage": (
            f"Turn {turn_index}: your move lands with a small, audible consequence. Dean Hale's "
            "hand stops above the folder, Mara finally looks up from her notes, and Jonas checks "
            "the hallway before answering. The room is still polite, but the old choreography has "
            "lost a step."
        ),
        "options": [
            {
                "label": "[Counter] Play the recording aloud",
                "hint": "Use a real card before they reset the room.",
                "handle": "play tape",
            },
            {
                "label": "[Provoke] Ask Mara why Jonas is nervous",
                "hint": "Turn their private tension into public friction.",
                "handle": "press Mara",
            },
            {
                "label": "[Yield] Let Hale define the next procedure",
                "hint": "Safer tone, worse leverage.",
                "handle": "let Hale",
            },
        ],
        "npc_pulse": pulses,
        "inventory_delta": {
            "added": ["committee recorder transcript"] if turn_index == 2 else [],
            "removed": [],
            "reason": "Mara leaves the recorder running while everyone argues.",
        }
        if turn_index == 2
        else None,
    }


def parse_args(argv: list[str] | None = None) -> NarrativeReleaseGateConfig:
    parser = argparse.ArgumentParser(
        description="Run the current narrative core release gate."
    )
    parser.add_argument("--mode", choices=("fake", "live"), default="fake")
    parser.add_argument("--db-path")
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--first-turn-input", default=DEFAULT_FIRST_TURN_INPUT)
    parser.add_argument("--output-path")
    args = parser.parse_args(argv)
    return NarrativeReleaseGateConfig(
        mode=args.mode,
        db_path=Path(args.db_path).expanduser().resolve() if args.db_path else None,
        seed=str(args.seed),
        first_turn_input=str(args.first_turn_input),
        output_path=Path(args.output_path).expanduser().resolve() if args.output_path else None,
    )


def _timed_step(summary: dict[str, Any], name: str, fn):
    started_at = time.perf_counter()
    result = fn()
    summary["steps"][name] = {"elapsed_seconds": round(time.perf_counter() - started_at, 3)}
    return result


def _build_service(config: NarrativeReleaseGateConfig, db_path: Path) -> tuple[NarrativeService, Any]:
    repo = NarrativeRepository(str(db_path))
    if config.mode == "fake":
        gateway = FakeNarrativeGateway()
    else:
        gateway = get_narrative_gateway(get_settings())
        if gateway is None:
            raise RuntimeError(
                "live mode requires APP_RESPONSES_PLAY_BASE_URL, APP_RESPONSES_PLAY_API_KEY, "
                "and APP_RESPONSES_PLAY_MODEL"
            )
    return NarrativeService(repository=repo, gateway=gateway), gateway


def run_release_gate(config: NarrativeReleaseGateConfig) -> dict[str, Any]:
    if config.db_path is None:
        with tempfile.TemporaryDirectory(prefix="tiny-stories-release-gate-") as tmpdir:
            return _run_release_gate_with_db(config, Path(tmpdir) / "narrative.sqlite3")
    return _run_release_gate_with_db(config, config.db_path)


def _run_release_gate_with_db(config: NarrativeReleaseGateConfig, db_path: Path) -> dict[str, Any]:
    service, gateway = _build_service(config, db_path)
    summary: dict[str, Any] = {
        "ok": False,
        "mode": config.mode,
        "db_path": str(db_path),
        "seed": config.seed,
        "steps": {},
        "ids": {},
        "contracts": {},
        "replay": {},
        "distribution": {},
        "llm_operations": [],
    }

    create_response = _timed_step(
        summary,
        "create_template",
        lambda: service.create_template(
            CreateTemplateRequest(
                seed=config.seed,
                visibility="public",
                turn_budget=4,
                difficulty="story",
                language="en",
            ),
            owner_user_id="release_owner",
        ),
    )
    template_id = create_response.template.template_id
    summary["ids"]["template_id"] = template_id
    summary["ids"]["owner_session_id"] = create_response.session.session_id
    summary["contracts"]["template_language_en"] = create_response.template.language == "en"
    summary["contracts"]["opening_has_three_options"] = len(create_response.opening.options) >= 3
    summary["contracts"]["role_cards_available"] = len(create_response.template.player_role_options) >= 3
    summary["contracts"]["public_template"] = create_response.template.visibility == "public"

    fork_response = _timed_step(
        summary,
        "start_fork_session",
        lambda: service.start_session(
            template_id,
            player_user_id="release_player",
            turn_budget=4,
            difficulty="story",
            player_role_index=1,
        ),
    )
    session_id = fork_response.session.session_id
    summary["ids"]["session_id"] = session_id
    summary["contracts"]["fork_keeps_template_id"] = fork_response.session.template_id == template_id
    summary["contracts"]["fork_session_is_distinct"] = session_id != create_response.session.session_id
    summary["contracts"]["fork_role_selected"] = fork_response.session.player_role is not None

    first_history = _timed_step(
        summary,
        "get_initial_history",
        lambda: service.get_story_history(session_id, player_user_id="release_player"),
    )
    summary["contracts"]["history_starts_with_opening"] = (
        len(first_history.messages) == 1 and first_history.messages[0].role == "narrator"
    )

    turn_requests = [
        AdvanceTurnRequest(free_input=config.first_turn_input, diary="Stay calm; make them read it."),
        AdvanceTurnRequest(chosen_option_index=1),
        AdvanceTurnRequest(chosen_option_index=0),
        AdvanceTurnRequest(free_input="I keep the recorder visible and ask each member to confirm the timestamp."),
    ]
    final_turn = None
    for index, request in enumerate(turn_requests, start=1):
        final_turn = _timed_step(
            summary,
            f"advance_turn_{index}",
            lambda request=request: service.advance(
                session_id,
                request,
                player_user_id="release_player",
            ),
        )
        if index == 2:
            advisor = _timed_step(
                summary,
                "ask_advisor",
                lambda: service.ask_advisor(
                    session_id,
                    AdvisorAskRequest(question="Is Hale stalling or looking for a way out?"),
                    player_user_id="release_player",
                ),
            )
            summary["contracts"]["advisor_replied"] = bool(advisor.advisor_message.content)
    assert final_turn is not None
    summary["contracts"]["final_turn_completed"] = final_turn.is_complete
    summary["contracts"]["final_turn_has_ending"] = final_turn.ending is not None

    ending = _timed_step(
        summary,
        "get_ending",
        lambda: service.get_session_ending(session_id, player_user_id="release_player"),
    )
    summary["contracts"]["ending_persisted"] = ending is not None
    if ending is not None:
        summary["contracts"]["ending_has_highlights"] = len(ending.highlights) >= 2
        summary["contracts"]["ending_has_branches"] = len(ending.branches) >= 2

    replay = _timed_step(summary, "get_public_replay", lambda: service.get_public_replay(session_id))
    summary["replay"] = {
        "completed": replay.completed,
        "message_count": len(replay.messages),
        "advisor_message_count": len(replay.advisor_messages),
        "ending_label": replay.ending.label if replay.ending else None,
        "highlight_count": len(replay.ending.highlights) if replay.ending else 0,
        "branch_count": len(replay.ending.branches) if replay.ending else 0,
    }
    summary["contracts"]["replay_has_template_id"] = replay.template_id == template_id
    summary["contracts"]["replay_completed"] = replay.completed
    summary["contracts"]["replay_has_story_and_advisor"] = (
        len(replay.messages) >= 9 and len(replay.advisor_messages) == 2
    )

    distribution = _timed_step(
        summary,
        "get_ending_distribution",
        lambda: service.get_ending_distribution(template_id, viewer_user_id="release_player"),
    )
    summary["distribution"] = {
        "total_completed": distribution.total_completed,
        "entries": [entry.model_dump() for entry in distribution.entries],
    }
    summary["contracts"]["distribution_counts_completed_run"] = distribution.total_completed == 1

    if hasattr(gateway, "calls"):
        summary["llm_operations"] = [str(call["operation_name"]) for call in gateway.calls]

    failed = [name for name, ok in summary["contracts"].items() if not ok]
    if failed:
        summary["failed_contracts"] = failed
        raise RuntimeError(f"narrative release gate failed contracts: {', '.join(failed)}")
    summary["ok"] = True
    return summary


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    payload = run_release_gate(config)
    if config.output_path is not None:
        write_output(config.output_path, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
