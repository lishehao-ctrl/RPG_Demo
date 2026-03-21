# RPG Demo Rebuild

<p align="center">
  <a href="./README.zh.md">
    <img alt="README 中文版" src="https://img.shields.io/badge/README-%E4%B8%AD%E6%96%87-1677ff">
  </a>
  <a href="./README.en.md">
    <img alt="README English" src="https://img.shields.io/badge/README-English-111827">
  </a>
</p>

## Overview

This repository is a full-stack RPG demo kept in a single repo. The product goal is not to build a generic content platform, but to support one short-loop experience:

1. The user enters an English story seed
2. The backend generates a preview
3. The user starts an author job
4. The frontend shows author loading and generation progress
5. The result is published into the story library
6. The user chooses a story from the library and starts a play session
7. The user advances the story through natural-language turns

The implementation is no longer the original "minimal backend" scaffold. It now contains a real `author / library / play / benchmark` backend split plus a working React frontend.

The current MVP closeout notes and benchmark references are in:

- `specs/mvp_closeout_20260321.md`

## Current Architecture

### Backend

- Stack: FastAPI + Pydantic + LangGraph + OpenAI-compatible Responses transport
- Package root: `rpg_backend/`
- Identity boundary: real cookie-session auth, no longer header-reported actor identity
- Main domains:
  - `author/`
    preview generation, async author jobs, LangGraph workflow, quality checks, DesignBundle output
  - `library/`
    published story persistence, listing, keyword search, theme filtering
  - `play/`
    compiling a `PlayPlan` from a `DesignBundle` and running play sessions
  - `benchmark/`
    benchmark and diagnostics response models

### Frontend

- Stack: React 19 + TypeScript + Vite
- Directory: `frontend/`
- Current layering:
  - `app/` app entry, routing, providers, app-level config
  - `pages/` page composition
  - `features/` page behavior and data loading
  - `widgets/` composed UI blocks
  - `entities/` lower-level domain UI
  - `api/` frontend contracts, route map, HTTP client, placeholder client

## Core Data Boundaries

- `DesignBundle`
  the final output of authoring and the input boundary for play runtime
- `PublishedStory`
  the library-facing published story card and preview payload
- `PlaySession`
  the runtime snapshot for an in-progress playthrough

## Persistence and Runtime Notes

- Published stories are persisted in SQLite at `artifacts/story_library.sqlite3` by default
- Author jobs, play sessions, and author checkpoints are persisted in SQLite runtime state
- In practice this means:
  - library data survives restarts
  - author jobs can resume after backend restart
  - play sessions survive restart until they expire
  - multi-instance sharing is still not ready; deploy as a single backend process for now

## Library API

The library uses a unified `GET /stories` resource for both listing and search. There is no separate parallel search endpoint.

### Exposed Endpoints

- `GET /stories`
  - supported query params:
    - `q` keyword search
    - `theme` theme filter
    - `limit` page size
    - `cursor` cursor pagination
    - `sort=published_at_desc|relevance`
- `GET /stories/{story_id}`
- `POST /author/jobs/{job_id}/publish`

### `GET /stories` Response Shape

The response includes:

- `stories`
- `meta`
- `facets`

Where:

- `meta` includes `query / theme / sort / limit / next_cursor / has_more / total`
- `facets.themes` provides theme aggregation for frontend filters

## Repository Layout

```text
.
├── README.md
├── README.zh.md
├── README.en.md
├── pyproject.toml
├── frontend/
│   ├── package.json
│   ├── specs/
│   └── src/
├── rpg_backend/
│   ├── author/
│   ├── benchmark/
│   ├── library/
│   ├── play/
│   └── main.py
├── tests/
├── tools/
├── specs/
└── artifacts/
```

## Local Development

### Backend

1. Prepare Python 3.11+
2. Install dependencies:

```bash
pip install -e ".[dev]"
```

3. Start the server:

```bash
uvicorn rpg_backend.main:app --reload
```

### Frontend

1. Install dependencies:

```bash
cd frontend
npm install
```

2. Start the dev server:

```bash
npm run dev
```

## Configuration

The backend reads settings from `.env` with an `APP_` prefix.

Common settings include:

- `APP_STORY_LIBRARY_DB_PATH`
- `APP_RUNTIME_STATE_DB_PATH`
- `APP_PLAY_SESSION_TTL_SECONDS`
- `APP_ENABLE_BENCHMARK_API`
- `APP_AUTH_SESSION_COOKIE_SECURE`
- `APP_AUTH_SESSION_COOKIE_SAMESITE`
- `APP_RESPONSES_BASE_URL`
- `APP_RESPONSES_API_KEY`
- `APP_RESPONSES_MODEL`

`APP_RUNTIME_STATE_DB_PATH` now backs persisted author jobs, play sessions, and author checkpoints. Published stories remain in `APP_STORY_LIBRARY_DB_PATH`.

Runtime restart semantics:

- in-flight author jobs are resumed from their latest checkpoint when the service boots again
- published author results remain queryable and publishable after restart
- play sessions keep snapshot, history, and turn trace state across restart until they expire

## Validation and Tests

Backend tests:

```bash
pytest
```

Frontend type-check:

```bash
cd frontend
npm run check
```

Real HTTP product smoke:

```bash
python tools/http_product_smoke.py --base-url http://127.0.0.1:8000
```

If benchmark diagnostics are enabled on the backend, you can include stage timings and play trace summary:

```bash
python tools/http_product_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --include-benchmark-diagnostics
```

Reset local business databases with backup:

```bash
python tools/reset_local_databases.py
```

AWS Ubuntu single-host deployment:

- `deploy/aws_ubuntu/DEPLOY.md`
- `deploy/aws_ubuntu/.env.production.example`
- `deploy/aws_ubuntu/rpg-demo-backend.service`
- `deploy/aws_ubuntu/nginx-rpg-demo.conf`

Current production domain:

- `https://rpg.shehao.app`

Playwright prelaunch launch-readiness suite:

```bash
python -m tools.playwright_launch.runner \
  --app-url http://127.0.0.1:5173 \
  --layers env,core,recovery
```

For the full mixed parallel browser gate:

```bash
python -m tools.playwright_launch.runner \
  --app-url http://127.0.0.1:5173 \
  --layers env,core,recovery,parallel \
  --parallel-worker-count 10
```

## Related Docs

- `specs/interface_governance_20260319.md`
  contract governance, public-vs-internal API boundaries, and frontend-backend ownership rules
- `specs/interface_stability_matrix_20260319.md`
  field-level stable/additive/internal-like contract tiers for author, library, and play
- `frontend/README.md`
  frontend handoff notes and current frontend contract mirror rules
- `frontend/specs/FRONTEND_PRODUCT_SPEC.md`
  product goals, user mental model, page flow, and API mapping
- `specs/backend/`
  backend design and historical handoff documents
