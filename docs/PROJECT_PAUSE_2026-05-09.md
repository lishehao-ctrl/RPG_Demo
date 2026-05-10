# Project Pause Memo: Mechanism Validated, Product Demand Unproven

Date: 2026-05-09 PDT

## Decision

Pause active product development on Tiny Stories / RPG_Demo_refactor.

This repository should be preserved as an LLM narrative-engineering
case study: structured prompt contracts, scheduler-driven LLM control,
stateful turn runtime, bounded endings, branch/highlight synthesis, and
playtest/benchmark tooling. It should not be treated as a proven
consumer entertainment product.

## Why pause

- The technical loop works, but real user demand is unproven.
- The project has 0 verified human-test data points.
- The player-agency loop remains the main unresolved product risk:
  the system can feel like it is driving a drama while the player
  triggers beats.
- The broader market is crowded with AI Dungeon-style freeform RPGs,
  AI DM/TTRPG products, character-chat apps, and playable public-domain
  book experiences.
- More UI polish, art, and mechanisms would not answer the core product
  question: whether players want to replay and share the result.

## Preserve

- `rpg_backend/narrative/`: prompt contracts, scheduler, parser,
  bounded ending/highlight/branch synthesis.
- `rpg_backend/author_v2/` and `rpg_backend/author_v3/`: seed-to-play
  planning and publication pipeline patterns.
- `rpg_backend/play_v2/`, `tools/urban_author_play_benchmarks/`, and
  `tests/`: runtime/evaluation harness ideas.
- `frontend2/`: primary React/Vite play surface and working UX shell.
- `frontend2/public/webtoons/`, `docs/images/`, and
  `docs/images/style-refs/`: reusable visual direction assets.
- `ARCHITECTURE.md`, `docs/devlog/2026-05-tiny-stories-9-mechanisms.md`,
  and specs: design rationale and known limits.

## Do not continue without new evidence

- Do not keep building this as a broad AI RPG platform.
- Do not invest more in art, homepage polish, multiplayer, streaming,
  or provider orchestration until a narrower product hook is validated.
- Do not treat memory, lore cards, long context, or UGC worlds as
  differentiators; they are table stakes in this category.
- Do not turn the legacy `frontend/` into another active surface.
- Do not use the failed benchmark artifacts as success baselines.

## Restart gate

Restart only if a narrower demo passes real-user validation:

- 5-10 human testers complete one run without explanation.
- At least 40% want to replay another role/path immediately.
- At least 30% are willing to share a result screenshot or link.
- Users can name a specific choice that changed the outcome.
- Random choices, always-first choices, and strong freeform inputs
  produce visibly different runs.
- The next prototype is deliberately small: one theme, three roles,
  six to eight turns, and one shareable result artifact.

## Current closeout state

Final stabilization scope:

- Provider compatibility: strip unsupported Beecode `enable_thinking`.
- Author v3 handoff: preserve accepted play-length preset and selected
  arc template through the pipeline.
- Template routing: mark explicit unsupported seeds as out of scope
  instead of forcing weak matches.
- Narrative parsing: normalize option intent tags to the template
  language and clip long option/NPC pulse text cleanly.
- Frontend polish: fix active-card border warnings, restore Vite dev
  port to `5173`, add public OG image, and separate player label/handle.
- Test coverage: add narrative option-language tests.

## Last closeout verification

Verified on 2026-05-09 PDT:

```bash
python -m pytest -q
cd frontend2
npm run check
npm run build
git diff --check
```

The Vite production build still reports one non-blocking chunk-size
warning around the main bundle. That is a known optimization item, not
a closeout blocker.

Run the same commands before changing or publishing this archive state.

Optional live smoke, when an LLM endpoint is configured:

```bash
uvicorn rpg_backend.main:app --host 127.0.0.1 --port 8000
cd frontend2
npm run dev -- --host 127.0.0.1 --port 5173
```

Then create a short story, pick a role, and advance at least one turn.

## Startup notes

- Backend: `uvicorn rpg_backend.main:app --reload`
- Frontend: `cd frontend2 && npm run dev`
- Default frontend port: `5173`
- Required config: copy `.env.example` to `.env` and set the
  `APP_RESPONSES_PLAY_*` LLM endpoint variables.
- Stop local services after verification; no service should be left
  running for the paused project.
