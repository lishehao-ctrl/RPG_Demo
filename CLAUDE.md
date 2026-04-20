# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Full-stack interactive narrative (relationship drama RPG) demo. Backend generates stories via LLM, frontend lets users create and play them.

- **Backend**: FastAPI + Pydantic + LangGraph + SQLite (`rpg_backend/`)
- **Frontend**: React 19 + TypeScript + Vite 7 + Motion.js (`frontend/`)
- **Production**: https://rpg.shehao.app (single EC2 + nginx + SQLite)

## Commands

```bash
# Backend
pip install -e ".[dev]"                # install with dev deps (Python >=3.11)
uvicorn rpg_backend.main:app --reload  # dev server at :8000

# Frontend
cd frontend && npm install
npm run dev                            # vite dev server at :5173 (proxies API to :8000)
npm run build                          # tsc --noEmit + vite build → dist/
npm run check                          # type-check only (no build artifact)

# Tests
pytest -q                              # all backend tests (tests/)
pytest tests/test_play_service.py -q   # single test file
pytest tests/test_play_service.py::test_create_session -q  # single test function

# Smoke test
python tools/http_product_smoke.py --base-url http://127.0.0.1:8000
```

No linting tools (no ruff, eslint, prettier). Quality gates are TypeScript strict mode and pytest only.

## Architecture

### Backend Domains

| Domain | Path | Purpose |
|--------|------|---------|
| Auth | `rpg_backend/auth/` | Cookie-session auth, SQLite user store |
| Author v1 | `rpg_backend/author/` | Public API contracts, gateway, metrics, display utilities |
| Author v2 | `rpg_backend/author_v2/` | Story generation implementation: LangGraph workflow, templates, IP library |
| Library | `rpg_backend/library/` | Story persistence, querying, visibility |
| Play v1 | `rpg_backend/play/` | Play session service, public contracts, turn processing |
| Play v2 | `rpg_backend/play_v2/` | Runtime engine: director, narration, causal contracts, escalation |
| Benchmark | `rpg_backend/benchmark/` | Internal diagnostics (behind `enable_benchmark_api` flag) |

**v1/v2 relationship**: v1 modules own the public API contracts and service interfaces. v2 modules provide the implementation. For example, `main.py` imports contracts from `author/contracts.py` (v1) but instantiates `ProductAuthorJobService` from `author_v2/`. Same pattern applies to play: `PlaySessionService` (v1) delegates to v2 runtime handlers.

Entry point: `rpg_backend/main.py` — instantiates all services at startup, registers routes.

Config: `rpg_backend/config.py` — `pydantic-settings` with `APP_` env prefix. Supports per-domain LLM config overrides (`APP_RESPONSES_AUTHOR_*`, `APP_RESPONSES_PLAY_*`) and helper slots (`APP_HELPER_SLOT_1_*`, etc.).

### Frontend Structure

Follows a layered architecture: `pages/ → widgets/ → entities/ → shared/ui/`

- **Routing**: Hash-based (`#/create-story`, `#/stories`, `#/play/sessions/{id}`) via `app/routes.ts`
- **API layer**: `api/contracts.ts` (types), `api/http-client.ts` (fetch), `api/route-map.ts` (URLs)
- **Providers**: `AuthProvider` (session), `ApiClientProvider` (HTTP client)
- **Styling**: Plain CSS files (`styles.css`, `storyline-theme.css`, `editorial-live.css`)

Vite proxies `/health`, `/me`, `/auth`, `/author`, `/stories`, `/play`, `/benchmark` to the backend. Proxy target configurable via `VITE_BACKEND_PROXY_TARGET`.

### Contract Governance

**Backend Pydantic contracts are the canonical source of truth.** Frontend TypeScript types are a maintained mirror (may be narrower, must not invent fields).

Canonical contracts:
- `rpg_backend/author/contracts.py` — public author API payloads
- `rpg_backend/library/contracts.py` — story library types
- `rpg_backend/play/contracts.py` — play session types
- `rpg_backend/author_v2/contracts.py` — internal pipeline types (not exposed via API)
- `rpg_backend/play_v2/contracts.py` — internal runtime types (not exposed via API)

Frontend mirrors:
- `frontend/src/api/contracts.ts`, `frontend/src/api/route-map.ts`

**Change order** (all six steps required for interface-completeness):
1. Update backend contract definitions
2. Update route handlers and service output
3. Add/adjust backend tests
4. Mirror type changes into `frontend/src/api/contracts.ts`
5. Update frontend client/UI usage
6. Update spec docs if product contract changed

See `specs/interface_governance_20260319.md` for full rules and `specs/interface_stability_matrix_20260319.md` for field-level versioning.

### Persistence

SQLite databases in `artifacts/`:
- `story_library.sqlite3` — published stories
- `runtime_state.sqlite3` — author jobs, checkpoints, play sessions

Single-process constraint: SQLite concurrency limits mean one uvicorn worker only.

### Public API Surface

- **Auth**: `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/session`, `GET /me`
- **Author**: `POST /author/story-previews`, `POST /author/jobs`, `GET /author/jobs/{id}`, `GET /author/jobs/{id}/events` (SSE), `GET /author/jobs/{id}/result`, `POST /author/jobs/{id}/publish`
- **Library**: `GET /stories`, `GET /stories/{id}`, `PATCH /stories/{id}/visibility`, `DELETE /stories/{id}`
- **Play**: `POST /play/sessions`, `GET /play/sessions/{id}`, `GET /play/sessions/{id}/history`, `POST /play/sessions/{id}/draft-intent`, `POST /play/sessions/{id}/turns`

Benchmark routes (`/benchmark/...`) are internal-only — frontend must not depend on them.

### Play v2 Runtime — Turn Processing Pipeline

The play runtime (`rpg_backend/play_v2/runtime.py`) processes each player turn through 4 stages:

```
Player Input → ① Intent Stage → ② State Resolution → ③ Narration → ④ Finalize
```

**① Intent Stage** (`run_intent_stage()` → `parse_turn_intent()`):
- Player text → keyword matching (`MOVE_KEYWORDS` dict, line ~86) → `move_family` (one of 10: flirt, probe_secret, comfort, deflect, accuse, ally_with, betray, public_reveal, private_confession, jealousy_trigger)
- LLM intent compilation gated by `_should_invoke_intent_llm()` (line ~356) — only triggers under high-risk conditions
- Optional NPC micro-sim (`_run_npc_micro_sim()`) predicts NPC reactions

**② State Resolution** (`apply_turn_resolution()`, line ~4329):
- `MOVE_DELTAS[move_family]` → static delta lookup (line ~187)
- Applied in order: move deltas → EventDirector → PayoffPlanner → LatentEventEngine
- Relationship deltas via `_apply_relationship_delta()` (clamped [-3, 6] or [0, 6])
- NPC mind deltas via `_apply_npc_mind_delta()` — **known bug**: mind state gets overwritten by relationship sync at line ~3930

**③ Narration** (`_render_narration()` → `_render_narration_npc_texture_v2()`):
- Builds seed/beat/style hints → LLM compose (or deterministic fallback)
- Optional pass 2 dramatic rewrite for key moments
- Anti-repetition: 4-turn fingerprint window with soft deweight (0.75)

**④ Finalize**: segment advancement (progress threshold + turn floor), ending check (`judge_ending()`), suggested actions

**LLM calls per turn**: 0-4 (intent compile, micro-sim, narration pass 1, narration pass 2). Most turns: 1 call (narration only).

**Key data types**:
- `UrbanPlayPlan` — compiled story plan with segments, cast, secrets, arc template
- `UrbanWorldState` — mutable game state (turn_index, relationships, pressures, segment_progress, etc.)
- `UrbanTurnIntent` — parsed player intent (move_family, target_id, scene_frame, control_action)
- `UrbanTurnResult` — turn output (narration, story_actions, control_actions, diagnostics)

### Codex Collaboration

When Claude Code delegates backend work to Codex:

**Division of labor**:
- Claude Code: product design, frontend UI, visual aesthetics, creative decisions, user experience, orchestration & supervision
- Codex: backend logic, rigorous code implementation, logic verification, algorithm reasoning

**Delegation guidelines**:
- Backend business logic, API implementation → delegate to Codex
- Code requiring logical rigor verification → have Codex review
- Frontend UI / interaction / product decisions → Claude Code handles directly
- After code completion, Codex can do logic-level review

**Codex invocation**: always use `--model gpt-5.3-codex --effort xhigh`

**Context Codex needs for play_v2 work**:
- Entry point: `rpg_backend/play_v2/runtime.py` — main runtime (~7000 lines)
- Contracts: `rpg_backend/play_v2/contracts.py` — internal types (UrbanPlayPlan, UrbanWorldState, etc.)
- Narration: `rpg_backend/play_v2/narration_surface.py` + narration variant files
- Service layer: `rpg_backend/play/service.py` — public API handlers
- Tests: `tests/test_play_service.py`, `tests/test_play_runtime.py`
- Config: `rpg_backend/config.py` — feature flags and LLM config

### Specs

Design documents and governance rules live in `specs/`:
- `interface_governance_20260319.md` — allowed/disallowed contract changes
- `interface_stability_matrix_20260319.md` — field-level stability tiers
- `relationship_drama_pivot_strategy_20260328.md` — current product direction
- `backend/`, `frontend/` subdirs — domain-specific refactor specs
