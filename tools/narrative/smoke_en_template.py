"""Smoke test: end-to-end EN narrative pipeline.

Generates an opening + advances one turn against the configured LLM
endpoint with `language="en"`, and verifies the output is CJK-free in
all free-form fields (title, narration, option labels, npc_pulse state
and reason, role labels). The single legitimate Chinese token allowed
through is `ending_label`, but this script never reaches a finalize
call so it doesn't need to handle that case.

Usage:
    python tools/narrative/smoke_en_template.py

Reads `.env` from the repo root. Requires the same `APP_RESPONSES_PLAY_*`
vars as a normal `uvicorn` run.

Exit codes:
    0 — pass (no CJK in any free-form field)
    1 — at least one field leaked Chinese characters
    2 — gateway not configured
"""
from __future__ import annotations

import os
import pathlib
import re
import sys


_REPO = pathlib.Path(__file__).resolve().parents[2]
_ENV = _REPO / ".env"
if _ENV.exists():
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from rpg_backend.narrative import engine
from rpg_backend.narrative.gateway import get_narrative_gateway

_CJK_RE = re.compile(r"[一-鿿]")


def _has_cjk(text: str | None) -> bool:
    return bool(text and _CJK_RE.search(text))


def _check_opening(op) -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    if _has_cjk(op.title):
        bad.append(("title", op.title))
    if _has_cjk(op.opening_message.content):
        bad.append(("opening_passage", op.opening_message.content[:120]))
    for c in op.cast:
        if _has_cjk(c.display_name):
            bad.append((f"cast[{c.character_id}].display_name", c.display_name))
        if _has_cjk(c.role):
            bad.append((f"cast[{c.character_id}].role", c.role))
    for o in op.opening_message.options:
        if _has_cjk(o.label):
            bad.append(("option.label", o.label))
    for r in op.player_role_options:
        if _has_cjk(r.label):
            bad.append((f"role[{r.role_id}].label", r.label))
    return bad


def _check_turn(result) -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    n = result.narrator_message
    if _has_cjk(n.content):
        bad.append(("narration", n.content[:120]))
    for o in n.options:
        if _has_cjk(o.label):
            bad.append(("option.label", o.label))
    for p in n.npc_pulse:
        if _has_cjk(p.state):
            bad.append(("pulse.state", p.state))
        if _has_cjk(p.reason):
            bad.append(("pulse.reason", p.reason or ""))
    return bad


def main() -> int:
    gw = get_narrative_gateway()
    if gw is None:
        print("ABORT: narrative gateway not configured (APP_RESPONSES_PLAY_*)")
        return 2
    print(f"model: {gw.model}")
    seed = (
        "Lunar New Year dinner at the in-laws — your wife has been smiling "
        "a little too much."
    )
    print(f"seed: {seed!r}")
    op = engine.generate_opening(gateway=gw, seed=seed, language="en")
    print(f"opening title: {op.title!r}")
    print(f"cast: {len(op.cast)}, roles: {len(op.player_role_options)}")
    bad = _check_opening(op)
    if bad:
        print(f"FAIL on opening: {len(bad)} CJK leaks")
        for f, s in bad[:6]:
            print(f"  - {f}: {s!r}")
        return 1
    print("opening passes; advancing one turn...")

    role = op.player_role_options[0] if op.player_role_options else None
    history = [op.opening_message]
    action = (
        op.opening_message.options[0].label
        if op.opening_message.options
        else "Stand up and excuse yourself."
    )
    result = engine.advance_turn(
        gateway=gw,
        seed=seed,
        title=op.title,
        cast=op.cast,
        history=history,
        player_action=action,
        next_ord=2,
        turn_index=1,
        turn_budget=12,
        difficulty="story",
        player_role=role,
        current_inventory=role.starting_assets if role else None,
        language="en",
    )
    bad = _check_turn(result)
    if bad:
        print(f"FAIL on turn: {len(bad)} CJK leaks")
        for f, s in bad[:6]:
            print(f"  - {f}: {s!r}")
        return 1
    print("PASS — opening + turn output fully English")
    return 0


if __name__ == "__main__":
    sys.exit(main())
