#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.config.settings import get_settings
from app.domain.constants import GLOBAL_MOVE_IDS
from app.domain.pack_schema import StoryPack
from app.generator.versioning import compute_pack_hash
from app.llm.base import LLMProviderConfigError
from app.llm.factory import get_llm_provider
from app.runtime.service import RuntimeService

DEFAULT_STRATEGIES = (
    "text_help",
    "text_noise",
    "button_first",
    "button_random",
    "mixed",
)
NOISE_TEXTS = (
    "",
    "???",
    "asdf qwer zxcv",
    "### random input ###",
    "nonsense token stream",
)


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        message = body or exc.reason
        raise RuntimeError(f"HTTP {exc.code} on {method} {url}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error on {method} {url}: {exc.reason}") from exc


def _create_session(base_url: str, story_id: str, version: int) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{base_url}/sessions",
        {"story_id": story_id, "version": version},
    )


def _step_session(base_url: str, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _request_json("POST", f"{base_url}/sessions/{session_id}/step", payload)


def _get_session(base_url: str, session_id: str, dev_mode: bool) -> dict[str, Any]:
    query = urllib.parse.urlencode({"dev_mode": str(dev_mode).lower()})
    return _request_json("GET", f"{base_url}/sessions/{session_id}?{query}")


def _build_action_input(
    strategy: str,
    step_index: int,
    ui_moves: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:
    if strategy == "text_help":
        return {"type": "text", "text": "help me progress"}
    if strategy == "text_noise":
        return {"type": "text", "text": NOISE_TEXTS[rng.randrange(0, len(NOISE_TEXTS))]}
    if strategy == "button_first":
        if ui_moves:
            return {"type": "button", "move_id": ui_moves[0]["move_id"]}
        return {"type": "text", "text": "help me progress"}
    if strategy == "button_random":
        if ui_moves:
            return {"type": "button", "move_id": ui_moves[rng.randrange(0, len(ui_moves))]["move_id"]}
        return {"type": "text", "text": "help me progress"}
    if strategy == "mixed":
        if step_index % 2 == 1:
            return {"type": "text", "text": "help me progress"}
        if ui_moves:
            return {"type": "button", "move_id": ui_moves[rng.randrange(0, len(ui_moves))]["move_id"]}
        return {"type": "text", "text": NOISE_TEXTS[rng.randrange(0, len(NOISE_TEXTS))]}
    return {"type": "text", "text": "help me progress"}


def _is_meaningful_change(
    previous_scene_id: str,
    new_scene_id: str,
    previous_beat_progress: dict[str, int],
    new_beat_progress: dict[str, int],
    resolution: dict[str, Any],
) -> bool:
    if resolution.get("costs_summary") != "none":
        return True
    if resolution.get("consequences_summary") != "none":
        return True
    if previous_scene_id != new_scene_id:
        return True
    if previous_beat_progress != new_beat_progress:
        return True
    return False


def simulate_pack_playthrough(
    pack_json: dict[str, Any],
    *,
    strategy: str = "text_help",
    provider_name: str = "fake",
    max_steps: int = 20,
    strategy_seed: int | None = None,
    metadata: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    working_rng = rng or random.Random(strategy_seed)
    metadata_payload = metadata or {}
    pack_hash = metadata_payload.get("pack_hash") or compute_pack_hash(pack_json)
    generator_version = metadata_payload.get("generator_version")
    variant_seed = metadata_payload.get("variant_seed")

    pack = StoryPack.model_validate(pack_json)
    try:
        runtime = RuntimeService(get_llm_provider(provider_name))
    except LLMProviderConfigError as exc:
        raise RuntimeError(f"failed to initialize provider '{provider_name}': {exc}") from exc
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)
    ui_moves = runtime.list_ui_moves(pack, scene_id)
    threshold = get_settings().routing_confidence_threshold

    transcript: list[dict[str, Any]] = []
    meaningful_steps = 0
    fallback_steps = 0
    fallback_with_progress_steps = 0
    text_input_steps = 0
    llm_route_steps = 0
    fallback_error_steps = 0
    fallback_low_confidence_steps = 0
    ended = False

    for step_index in range(1, max_steps + 1):
        previous_scene_id = scene_id
        previous_progress = dict(beat_progress)
        action_input = _build_action_input(strategy, step_index, ui_moves, working_rng)
        is_text_input = action_input.get("type") == "text"
        if is_text_input:
            text_input_steps += 1

        result = runtime.process_step(
            pack=pack,
            current_scene_id=scene_id,
            beat_index=beat_index,
            state=state,
            beat_progress=beat_progress,
            action_input=action_input,
            dev_mode=True,
        )

        scene_id = result["scene_id"]
        beat_index = result["beat_index"]
        ended = bool(result["ended"])
        ui_moves = result["ui"]["moves"]

        meaningful = _is_meaningful_change(
            previous_scene_id=previous_scene_id,
            new_scene_id=scene_id,
            previous_beat_progress=previous_progress,
            new_beat_progress=dict(beat_progress),
            resolution=result["resolution"],
        )
        if meaningful:
            meaningful_steps += 1

        recognized = result["recognized"]
        route_source = recognized.get("route_source", "unknown")
        if is_text_input:
            if route_source == "llm":
                llm_route_steps += 1
            elif route_source == "fallback_error":
                fallback_error_steps += 1
            elif route_source in {"fallback_low_confidence", "fallback_invalid_move"}:
                fallback_low_confidence_steps += 1
        fallback = (
            action_input.get("type") == "text"
            and recognized.get("move_id") in GLOBAL_MOVE_IDS
            and float(recognized.get("confidence", 0.0)) < threshold
        )
        if fallback:
            fallback_steps += 1
            if meaningful:
                fallback_with_progress_steps += 1

        transcript.append(
            {
                "step": step_index,
                "action_input": action_input,
                "pack_hash": pack_hash,
                "generator_version": generator_version,
                "variant_seed": variant_seed,
                "strategy_seed": strategy_seed,
                "provider": provider_name,
                "route_source": route_source,
                "scene_id": scene_id,
                "recognized": recognized,
                "resolution": result["resolution"],
                "narration_text": result["narration_text"],
                "ended": ended,
                "beat_progress": dict(beat_progress),
                "meaningful_change": meaningful,
                "fallback_with_progress": fallback and meaningful,
            }
        )

        if ended:
            break

    return {
        "mode": "pack",
        "strategy": strategy,
        "pack_hash": pack_hash,
        "generator_version": generator_version,
        "variant_seed": variant_seed,
        "strategy_seed": strategy_seed,
        "provider": provider_name,
        "steps": len(transcript),
        "ended": ended,
        "meaningful_steps": meaningful_steps,
        "fallback_steps": fallback_steps,
        "fallback_with_progress_steps": fallback_with_progress_steps,
        "text_input_steps": text_input_steps,
        "llm_route_steps": llm_route_steps,
        "fallback_error_steps": fallback_error_steps,
        "fallback_low_confidence_steps": fallback_low_confidence_steps,
        "transcript": transcript,
    }


def run_simulation(
    *,
    base_url: str,
    story_id: str,
    version: int,
    max_steps: int,
    strategy: str,
    strategy_seed: int | None = None,
    metadata: dict[str, Any] | None = None,
    dev_mode: bool,
) -> dict[str, Any]:
    rng = random.Random(strategy_seed)
    metadata_payload = metadata or {}
    pack_hash = metadata_payload.get("pack_hash")
    generator_version = metadata_payload.get("generator_version")
    variant_seed = metadata_payload.get("variant_seed")
    created = _create_session(base_url, story_id, version)
    session_id = created["session_id"]
    transcript: list[dict[str, Any]] = []
    ui_moves: list[dict[str, Any]] = []

    for step_index in range(1, max_steps + 1):
        action = _build_action_input(strategy, step_index, ui_moves, rng)
        payload = {
            "client_action_id": f"simulate-{step_index}",
            "input": action,
            "dev_mode": dev_mode,
        }
        step = _step_session(base_url, session_id, payload)
        ui_moves = step.get("ui", {}).get("moves", [])
        session = _get_session(base_url, session_id, dev_mode=True)
        transcript.append(
            {
                "step": step_index,
                "action_input": action,
                "pack_hash": pack_hash,
                "generator_version": generator_version,
                "variant_seed": variant_seed,
                "strategy_seed": strategy_seed,
                "scene_id": step["scene_id"],
                "recognized": step["recognized"],
                "resolution": step["resolution"],
                "narration_text": step["narration_text"],
                "ended": session["ended"],
                "beat_progress": session["beat_progress"],
            }
        )
        if session["ended"]:
            break

    final_state = _get_session(base_url, session_id, dev_mode=True)
    return {
        "mode": "api",
        "strategy": strategy,
        "pack_hash": pack_hash,
        "generator_version": generator_version,
        "variant_seed": variant_seed,
        "strategy_seed": strategy_seed,
        "session_id": session_id,
        "story_id": story_id,
        "version": version,
        "steps": len(transcript),
        "ended": final_state["ended"],
        "transcript": transcript,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate playthroughs for story versions or raw packs.")
    parser.add_argument("--story-id", help="Story ID to simulate with API mode")
    parser.add_argument("--version", type=int, help="Published story version for API mode")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--max-steps", default=20, type=int, help="Maximum simulated steps")
    parser.add_argument("--strategy", default="text_help", choices=DEFAULT_STRATEGIES, help="Simulation strategy")
    parser.add_argument("--strategy-seed", type=int, help="Optional fixed seed for strategy randomness")
    parser.add_argument(
        "--provider",
        default="fake",
        choices=["fake", "openai"],
        help="Provider for local pack simulation mode",
    )
    parser.add_argument("--dev-mode", action="store_true", help="Send dev_mode=true on each /step")
    parser.add_argument("--output", help="Optional output path for transcript JSON")
    parser.add_argument("--pack-file", help="Optional raw pack JSON path for local pack mode")
    parser.add_argument("--pack-hash", help="Optional metadata override for pack hash")
    parser.add_argument("--generator-version", help="Optional metadata override for generator version")
    parser.add_argument("--variant-seed", help="Optional metadata override for variant seed")
    args = parser.parse_args()
    metadata = {
        "pack_hash": args.pack_hash,
        "generator_version": args.generator_version,
        "variant_seed": args.variant_seed,
    }

    try:
        if args.pack_file:
            with open(args.pack_file, "r", encoding="utf-8") as f:
                pack_json = json.load(f)
            report = simulate_pack_playthrough(
                pack_json=pack_json,
                strategy=args.strategy,
                provider_name=args.provider,
                max_steps=args.max_steps,
                strategy_seed=args.strategy_seed,
                metadata=metadata,
            )
        else:
            if not args.story_id or not args.version:
                raise RuntimeError("story-id and version are required when pack-file is not provided")
            report = run_simulation(
                base_url=args.base_url.rstrip("/"),
                story_id=args.story_id,
                version=args.version,
                max_steps=args.max_steps,
                strategy=args.strategy,
                strategy_seed=args.strategy_seed,
                metadata=metadata,
                dev_mode=args.dev_mode,
            )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    serialized = json.dumps(report, ensure_ascii=True, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(serialized)
        print(f"transcript saved to {args.output}")
    else:
        print(serialized)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
