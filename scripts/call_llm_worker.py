#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from rpg_backend.config.settings import get_settings
from rpg_backend.llm.worker_client import WorkerClientError, get_worker_client


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2))


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    model = (
        args.model
        or settings.llm_openai_generator_model
        or settings.llm_openai_route_model
        or settings.llm_openai_narration_model
        or settings.llm_openai_model
    )
    if args.task != "probe" and not (model or "").strip():
        raise RuntimeError("model is required for non-probe tasks")

    try:
        client = get_worker_client()
        if args.task == "probe":
            status_code, payload = await client.probe_ready(refresh=args.refresh)
            _print({"status_code": status_code, "payload": payload})
            return 0 if status_code < 400 else 1

        timeout_seconds = float(args.timeout_seconds or settings.llm_worker_timeout_seconds)

        if args.task == "route-intent":
            scene_context = json.loads(args.scene_context)
            response = await client.route_intent(
                scene_context=scene_context,
                text=args.text,
                model=str(model),
                temperature=float(args.temperature),
                max_retries=max(1, min(int(args.max_retries), 3)),
                timeout_seconds=timeout_seconds,
            )
            _print(response)
            return 0

        if args.task == "render-narration":
            slots = json.loads(args.slots)
            response = await client.render_narration(
                slots=slots,
                style_guard=args.style_guard,
                model=str(model),
                temperature=float(args.temperature),
                max_retries=max(1, min(int(args.max_retries), 3)),
                timeout_seconds=timeout_seconds,
            )
            _print(response)
            return 0

        response = await client.json_object(
            system_prompt=args.system_prompt,
            user_prompt=args.user_prompt,
            model=str(model),
            temperature=float(args.temperature),
            max_retries=max(1, min(int(args.max_retries), 3)),
            timeout_seconds=timeout_seconds,
        )
        _print(response)
        return 0
    except WorkerClientError as exc:
        _print(
            {
                "error_code": exc.error_code,
                "message": exc.message,
                "retryable": exc.retryable,
                "status_code": exc.status_code,
                "model": exc.model,
                "attempts": exc.attempts,
            }
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Call RPG LLM Worker tasks directly")
    parser.add_argument("--task", choices=("route-intent", "render-narration", "json-object", "probe"), required=True)
    parser.add_argument("--text", default="")
    parser.add_argument("--scene-context", default="{}", help="JSON object")
    parser.add_argument("--slots", default="{}", help="JSON object")
    parser.add_argument("--style-guard", default="neutral")
    parser.add_argument("--system-prompt", default="Return JSON only with key ok.")
    parser.add_argument("--user-prompt", default='Return exactly {"ok":true}')
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
