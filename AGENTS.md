# RPG Demo Agent Guide

## Project Stack
- Backend: FastAPI + SQLAlchemy + Alembic.
- Frontend demo: static HTML/CSS/JS under `app/modules/demo/static`.
- Runtime mode: StoryPack-driven sessions only (`story_node_id` is the node pointer).

## Core Goals
- Keep story runtime deterministic and debuggable.
- Preserve endpoint contracts while iterating on gameplay UX.
- Keep tests green with `LLM_PROVIDER_PRIMARY=fake` by default.

## Non-Goals
- No broad framework migration.
- No compatibility shims for removed legacy fields in hard-cut cycles.
- No DB schema drift outside Alembic migrations.

## Working Rules
- Write tests with behavior changes.
- Keep `GET /sessions/{id}` and `POST /sessions/{id}/step` contracts aligned with `app/modules/session/schemas.py`.
- `LLM_UNAVAILABLE` remains hard-fail: step is not applied.
- Keep `/demo/play` player-focused and `/demo/dev` diagnostics-focused.

## Common Commands
- Run dev server:
  - `./scripts/dev.sh`
- Run all tests:
  - `pytest -q`
  - `python -m pytest -q client/tests`
- Route/UI smoke:
  - `pytest -q tests/test_demo_routes.py`
- Screenshot capture:
  - `pip install -r requirements-dev-ui.txt`
  - `python -m playwright install chromium`
  - `python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local`
