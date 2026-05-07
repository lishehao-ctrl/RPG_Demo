# Tiny Stories

<p align="center">
  <img src="./docs/images/hero.jpg" alt="Tiny Stories — interactive drama hero" width="100%" />
</p>

<p align="center">
  <strong>An LLM-driven 12-turn interactive drama engine</strong>
</p>

<p align="center">
  3 selectable player roles · NPCs holding leverage on each other · 15 shareable endings · MIT licensed
</p>

<p align="center">
  <a href="./README.md">中文</a> · <strong>English</strong> ·
  <a href="./ARCHITECTURE.en.md">Architecture deep-dive</a> ·
  <a href="./CONTRIBUTING.en.md">Contributing</a> ·
  <a href="./docs/devlog/2026-05-tiny-stories-9-mechanisms.en.md">Design devlog</a> ·
  <a href="./docs/GOOD_FIRST_ISSUES.en.md">Good first issues</a>
</p>

<p align="center">
  <img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg" />
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11+-blue.svg" />
  <img alt="React 19" src="https://img.shields.io/badge/react-19-61dafb.svg" />
  <img alt="Status: Alpha" src="https://img.shields.io/badge/status-alpha-orange.svg" />
</p>

---

## TL;DR

You write a story opening. The AI scaffolds a **complete 12-turn drama** —
several NPCs with secrets, a political network where they hold leverage
over each other, and a few selectable player identities (each playing
out a different story). You play 15 minutes, walk away with a
**screenshotable ending label**, and see the 2-3 paths you didn't take.

> Not a chatbot. Not an infinite simulator. A **structured, finite,
> shareable** short-form drama engine.

```
hook → pressure → reversal (forced inflection) → climax → pre_finale
   ↓ each turn ↓
   your choice + NPCs pushing their agenda + inventory accumulation +
   optional advisor oracle
   ↓ end ↓
   15 ending labels · 5-card highlight reel · 2-3 "paths you didn't take"
```

**This is a study showcase for people building LLM-driven products**,
not a SaaS for end users. The mechanism stack is complete, the docs
are thorough, and it's MIT licensed. Reading this repo gives you a
working pattern for: **structured prompt design + scheduler-driven LLM
control + cross-layer contracts**.

---

## What it is

You write a one-line story seed (e.g. *Lunar New Year dinner at the
in-laws / the moment before the awards red carpet / a phone call the
night before the wedding*). The AI builds a 12-turn drama scaffold:

- 3-5 NPCs, each with a `hidden_objective` and something they hold
  over the player
- A political network where NPCs hold leverage on each other (≥4 edges
  per 3-NPC cast)
- 3-5 selectable player roles, each with their own
  `hidden_objective`, counter-leverage cards, and starting items

You pick a role and play. Each turn: pick an option, write a free-form
action, optionally write inner monologue. The system weaves the story
through 9 layers of mechanics:

- NPCs actively push their agenda (not just reacting to you)
- Your choices echo causally (LLM is told what just happened + what
  pulse trends look like)
- Inventory accumulates (sticky state, walk-on-read)
- Advisor oracle costs 1 turn for a privileged hint
- Reversal stage forces a structural plot turn (not just escalation)
- Endings split into victory / compromised / collapsed × 15 labels

After the run, get a 5-card highlight reel + 2-3 "paths you didn't
take" cards. One-click share link.

> **Status:** alpha / open-source preview. Mechanism layer is mature,
> **0 verified human-test data points** so far. If you fork it and
> play a session, feedback is the highest-leverage contribution.

---

## 60-second Quickstart

Requires: Python 3.11+ / Node 18+ / any OpenAI-compatible API key
(DashScope / OpenAI / local Ollama all work).

```bash
# 1. Backend deps
pip install -e ".[dev]"

# 2. Configure LLM endpoint
cp .env.example .env
# Edit .env, fill at least:
#   APP_RESPONSES_PLAY_BASE_URL=...
#   APP_RESPONSES_PLAY_API_KEY=sk-...
#   APP_RESPONSES_PLAY_MODEL=...

# 3. Start backend (port 8000)
uvicorn rpg_backend.main:app --reload

# 4. Start frontend in a new terminal (port 5173, auto-proxies to 8000)
cd frontend2
npm install
npm run dev
```

Open `http://localhost:5173`. Register a username → create a story →
pick a role → play.

> **First template generation** triggers an LLM call to produce
> opening + cast + roles + failure conditions + inter-NPC leverage
> network — about 12-20s on qwen-flash-class models. Each turn
> advance is ~5-8s.

---

## Architecture / 9 mechanisms

Full details in [ARCHITECTURE.en.md](./ARCHITECTURE.en.md). Condensed:

```
Opening phase:
  generate_opening
  → cast (with hidden_objective + leverage_over_player + leverages_over_other_npcs)
  → 3-5 PlayerRole cards (with hidden_objective + leverages_over_npcs + starting_assets)
  → player_goals + failure_conditions

Per-turn advance_turn:
  ① _pick_npc_agenda      (gauntlet: schedule which NPC pushes their agenda)
  ② _pick_twist_directive (reversal forces a turn: leverage exposed / betrayal /
                           persona crack / new arrival / external event)
  ③ compute_current_inventory (walk-on-read, starting_assets + Σdeltas)
  ④ _summarize_recent_consequences (last_player_action + npc_pulse_trend +
                                    unused_leverage)
  ⑤ LLM composes 200-400 char passage + 3 [intent-tag] options
  ⑥ Output: passage / options / npc_pulse[shift+reason] / inventory_delta

Per-turn judge_failure (gauntlet only):
  → triggered → synthesize_early_ending (collapsed tier)

Finalize:
  ⑦ synthesize_ending      (15-label closed pool)
  ⑧ synthesize_highlights  (5 pivotal beats)
  ⑨ synthesize_branches    (2-3 "you didn't take" paths + alternate ending label)
```

Plus the visual layer: 3-tier ending splash / peak close-up rotation /
stage progression bar / pulse legend / oracle vignette.

---

## Project layout

```
rpg_backend/             FastAPI + Pydantic + SQLite — core
  narrative/             ← all 9 mechanisms here
    contracts.py         All Pydantic types (single source of truth)
    engine.py            LLM prompts + scheduler + parser (~2200 lines)
    repository.py        SQLite + idempotent migrations
    service.py           HTTP-side business flow
    gateway.py           OpenAI-compatible LLM client wrapper
  main.py                FastAPI app + routes
  auth/                  Cookie session
  config.py              pydantic-settings, all APP_ env vars

frontend2/               React 19 + TypeScript + Vite, primary frontend
  src/api/contracts.ts   TS mirror of backend contracts
  src/pages/play/        play-page.tsx (~2400 lines, all turn UI here)
  src/shared/ui/         StageProgressBar / LoadingShim / EmptyState
  src/shared/lib/        webtoon-assets, motion-presets
  public/webtoons/       AI-generated visuals (10 shells / 20 avatars / 5 peaks / etc)

frontend/                Legacy frontend (no longer maintained, kept for reference)
specs/                   Product / design docs
deploy/aws_ubuntu/       Single-machine deploy example (nginx + systemd)
tests/                   pytest (mostly covers legacy author module; narrative
                         module relies on LLM smoke)
```

---

## Mechanism smoke test

After backend is up, no frontend needed — verify LLM smoke:

```bash
# Generate one full opening (cast + roles + leverage network all populated)
python -c "
from rpg_backend.narrative import engine
from rpg_backend.narrative.gateway import get_narrative_gateway
gw = get_narrative_gateway()
op = engine.generate_opening(gateway=gw, seed='Returning to the family estate for Lunar New Year, the wife has been smiling too much')
print(f'Title: {op.title}')
print(f'NPCs: {len(op.cast)} | Roles: {len(op.player_role_options)} | Inter-NPC edges: {sum(len(c.leverages_over_other_npcs) for c in op.cast)}')
"
```

---

## Configuration

All tunable parameters live in `rpg_backend/config.py`, overridable
via `APP_`-prefixed env vars. Minimum required: see `.env.example`.

The LLM endpoint is the only required field — any OpenAI-compatible
API works, including local Ollama / vLLM / SGLang.

---

## Development

```bash
# Backend type-check + tests
pytest -q

# Frontend type + production build
cd frontend2
npm run check        # tsc --noEmit
npm run build        # vite build
```

No ruff / eslint / prettier — quality gates are TypeScript strict +
pytest.

If LLM-generated narration looks off, look at the prompts in
`rpg_backend/narrative/engine.py` (`_TURN_SYSTEM_PROMPT` /
`_OPENING_SYSTEM_PROMPT` etc) first. Prompt edits are more common than
code edits.

---

## Roadmap

Short-term (open-source preview):
- [ ] CI runs pytest + frontend type-check
- [ ] 5-10 real-human playtest sessions, watch share-intent data
- [ ] Decide third polish round based on real feedback

Mid-term:
- [ ] Streaming narration (typewriter effect)
- [ ] Persistent in-game HUD (player can see leverage map any time)
- [ ] Multi-LLM provider mixed scheduling (route sensitive prompts to
  cheaper models)

Long-term:
- [ ] Async multiplayer (player A finishes a session, player B takes
  over the opposing NPC)
- [ ] Player-customizable ending pool

---

## License

MIT — see [LICENSE](./LICENSE). Visual assets are also under MIT
(AI-generated, no third-party copyright).

---

## Contributing

PRs welcome. For structural changes, please open an issue first.
Especially welcome:
- New LLM provider adapters (Gemini-compat / Claude-compat etc)
- Real-player playthrough feedback (open an issue describing what
  happened in your session + how it felt)
- Prompt tuning (when you find a prompt's output unstable in practice)
