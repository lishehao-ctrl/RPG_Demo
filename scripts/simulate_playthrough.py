#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from rpg_backend.domain.pack_schema import StoryPack
from rpg_backend.api.route_paths import admin_auth_login_path, session_path, session_step_path, sessions_path
from rpg_backend.generator.versioning import compute_pack_hash
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.factory import get_llm_provider
from rpg_backend.runtime.errors import RuntimeLLMError
from rpg_backend.runtime.service import RuntimeService

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
CONTEXT_TEXTS = (
    "stabilize the corridor while preserving trust",
    "what is the safest next operational move",
    "push fast and accept some political cost",
    "secure evidence before command pressure escalates",
    "reduce coordination noise and keep the team aligned",
    "protect civilians even if resources get tighter",
)


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    access_token: str | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    token = (access_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


def _create_session(base_url: str, story_id: str, version: int, *, access_token: str | None) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{base_url}{sessions_path()}",
        {"story_id": story_id, "version": version},
        access_token=access_token,
    )


def _step_session(
    base_url: str,
    session_id: str,
    payload: dict[str, Any],
    *,
    access_token: str | None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{base_url}{session_step_path(session_id)}",
        payload,
        access_token=access_token,
    )


def _get_session(base_url: str, session_id: str, dev_mode: bool, *, access_token: str | None) -> dict[str, Any]:
    query = urllib.parse.urlencode({"dev_mode": str(dev_mode).lower()})
    return _request_json("GET", f"{base_url}{session_path(session_id)}?{query}", access_token=access_token)


def _login_and_get_access_token(base_url: str, *, email: str, password: str) -> str:
    response = _request_json(
        "POST",
        f"{base_url}{admin_auth_login_path()}",
        {"email": email, "password": password},
    )
    token = str(response.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("login succeeded but access_token missing")
    return token


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
        if step_index % 3 == 1:
            return {"type": "text", "text": "help me progress"}
        if step_index % 3 == 2:
            return {"type": "text", "text": CONTEXT_TEXTS[rng.randrange(0, len(CONTEXT_TEXTS))]}
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
    provider_name: str = "openai",
    max_steps: int = 20,
    strategy_seed: int | None = None,
    metadata: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    if provider_name != "openai":
        raise RuntimeError(f"unsupported provider for local simulation: {provider_name}")
    working_rng = rng or random.Random(strategy_seed)
    metadata_payload = metadata or {}
    pack_hash = metadata_payload.get("pack_hash") or compute_pack_hash(pack_json)
    generator_version = metadata_payload.get("generator_version")
    variant_seed = metadata_payload.get("variant_seed")

    pack = StoryPack.model_validate(pack_json)
    try:
        runtime = RuntimeService(get_llm_provider())
    except LLMProviderConfigError as exc:
        raise RuntimeError(f"failed to initialize provider '{provider_name}': {exc}") from exc
    scene_id, beat_index, state, beat_progress = runtime.initialize_session_state(pack)
    ui_moves = runtime.list_ui_moves(pack, scene_id)

    transcript: list[dict[str, Any]] = []
    meaningful_steps = 0
    text_input_steps = 0
    llm_route_steps = 0
    global_help_route_steps = 0
    pressure_recoil_steps = 0
    npc_stance_mentions = 0
    runtime_error = False
    runtime_error_code: str | None = None
    runtime_error_stage: str | None = None
    runtime_error_message: str | None = None
    ended = False

    for step_index in range(1, max_steps + 1):
        previous_scene_id = scene_id
        previous_progress = dict(beat_progress)
        action_input = _build_action_input(strategy, step_index, ui_moves, working_rng)
        is_text_input = action_input.get("type") == "text"
        if is_text_input:
            text_input_steps += 1

        try:
            result = asyncio.run(
                runtime.process_step(
                    pack=pack,
                    current_scene_id=scene_id,
                    beat_index=beat_index,
                    state=state,
                    beat_progress=beat_progress,
                    action_input=action_input,
                    dev_mode=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            runtime_error = True
            if isinstance(exc, RuntimeLLMError):
                runtime_error_code = exc.error_code
                runtime_error_stage = exc.stage
                runtime_error_message = exc.message
            else:
                runtime_error_code = "runtime_step_exception"
                runtime_error_stage = "runtime"
                runtime_error_message = str(exc)
            transcript.append(
                {
                    "step": step_index,
                    "action_input": action_input,
                    "pack_hash": pack_hash,
                    "generator_version": generator_version,
                    "variant_seed": variant_seed,
                    "strategy_seed": strategy_seed,
                    "provider": provider_name,
                    "scene_id": scene_id,
                    "runtime_error": True,
                    "runtime_error_code": runtime_error_code,
                    "runtime_error_stage": runtime_error_stage,
                    "runtime_error_message": runtime_error_message,
                }
            )
            break

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
        if is_text_input and route_source == "llm":
            llm_route_steps += 1
            if recognized.get("move_id") == "global.help_me_progress":
                global_help_route_steps += 1

        if "Pressure recoil:" in str(result["resolution"].get("consequences_summary", "")):
            pressure_recoil_steps += 1
        if "Stance update:" in (result.get("narration_text") or ""):
            npc_stance_mentions += 1

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
        "text_input_steps": text_input_steps,
        "llm_route_steps": llm_route_steps,
        "global_help_route_steps": global_help_route_steps,
        "pressure_recoil_steps": pressure_recoil_steps,
        "npc_stance_mentions": npc_stance_mentions,
        "runtime_error": runtime_error,
        "runtime_error_steps": 1 if runtime_error else 0,
        "runtime_error_code": runtime_error_code,
        "runtime_error_stage": runtime_error_stage,
        "runtime_error_message": runtime_error_message,
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
    access_token: str | None,
) -> dict[str, Any]:
    rng = random.Random(strategy_seed)
    metadata_payload = metadata or {}
    pack_hash = metadata_payload.get("pack_hash")
    generator_version = metadata_payload.get("generator_version")
    variant_seed = metadata_payload.get("variant_seed")
    created = _create_session(base_url, story_id, version, access_token=access_token)
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
        step = _step_session(base_url, session_id, payload, access_token=access_token)
        ui_moves = step.get("ui", {}).get("moves", [])
        session = _get_session(base_url, session_id, dev_mode=True, access_token=access_token)
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

    final_state = _get_session(base_url, session_id, dev_mode=True, access_token=access_token)
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
        default="openai",
        choices=["openai"],
        help="Provider for local pack simulation mode",
    )
    parser.add_argument("--dev-mode", action="store_true", help="Send dev_mode=true on each /step")
    parser.add_argument("--output", help="Optional output path for transcript JSON")
    parser.add_argument("--pack-file", help="Optional raw pack JSON path for local pack mode")
    parser.add_argument("--pack-hash", help="Optional metadata override for pack hash")
    parser.add_argument("--generator-version", help="Optional metadata override for generator version")
    parser.add_argument("--variant-seed", help="Optional metadata override for variant seed")
    parser.add_argument("--access-token", help="Bearer access token for protected API routes")
    parser.add_argument("--auth-email", help="If set with --auth-password, auto-login to get access token")
    parser.add_argument("--auth-password", help="Password for --auth-email")
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
            access_token = args.access_token or os.getenv("APP_AUTH_ACCESS_TOKEN")
            if not access_token and args.auth_email and args.auth_password:
                access_token = _login_and_get_access_token(
                    args.base_url.rstrip("/"),
                    email=args.auth_email,
                    password=args.auth_password,
                )
            report = run_simulation(
                base_url=args.base_url.rstrip("/"),
                story_id=args.story_id,
                version=args.version,
                max_steps=args.max_steps,
                strategy=args.strategy,
                strategy_seed=args.strategy_seed,
                metadata=metadata,
                dev_mode=args.dev_mode,
                access_token=access_token,
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
