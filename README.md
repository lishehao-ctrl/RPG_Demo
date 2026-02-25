# RPG Demo

## Run Server (Dev)
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e "./client[pretty]"
./scripts/dev.sh
```

Server:
- `http://127.0.0.1:8000`

Demo pages:
- `http://127.0.0.1:8000/demo/play`
- `http://127.0.0.1:8000/demo/dev`

`/demo/author` has been removed in the hard-cut cleanup.

## Story API Surface (Read-only + Validate)
- `POST /stories/validate`
- `GET /stories`
- `GET /stories/{story_id}`

Removed endpoints:
- `POST /stories`
- `POST /stories/{story_id}/publish`
- all `author-*` endpoints (`validate-author`, `compile-author`, `author-assist`, stream/upload variants)

## Session API Surface
- `POST /sessions`
- `GET /sessions/{id}`
- `POST /sessions/{id}/step`
- `POST /sessions/{id}/step/stream`
- `GET /sessions/{id}/debug/*` (dev only)

## Seed Story Packs Offline
Story pack write/publish is now an offline operation.

```bash
python scripts/seed.py --story-file examples/storypacks/campus_week_v1.json --publish
```

This writes directly to DB and marks the version as published.

## LLM Runtime Config
Set these in `.env` before starting the server:

```bash
LLM_MODEL_GENERATE=codex
LLM_DOUBAO_API_KEY=<your-api-key>
```

Notes:
- `ENV=test` uses fake provider; non-test uses proxy provider.
- Runtime narration path remains fail-fast (`LLM_UNAVAILABLE` blocks step apply).

## Verification
Core:
```bash
python -m compileall app scripts tests
pytest -q
python -m pytest -q client/tests
```

Route/UI smoke:
```bash
pytest -q tests/test_demo_routes.py
python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local
```

## Docs Index
- `docs/INDEX.md`
