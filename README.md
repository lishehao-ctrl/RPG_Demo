# RPG Demo Backend Scaffold

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

## Requirements
- Python **>= 3.11** (recommended: `3.11.9`, see `.python-version`)

## Run locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e "./client[pretty]"
uvicorn app.main:app --reload
```

## Local Dev Quickstart

```bash
./scripts/dev.sh
```

This sets `ENV=dev`, defaults `DATABASE_URL` to `sqlite:///./dev.db` when unset, runs `alembic upgrade head`, and starts the server with `--reload`.
By default it also seeds `examples/storypacks/campus_week_v1.json` (set `SKIP_SEED=1` to skip seeding).

Demo UIs:

```bash
open http://localhost:8000/demo/play
open http://localhost:8000/demo/dev
```

- `/demo/play` is the user mode. It starts with a story selection screen and only lists published + playable stories.
- `/demo/play` is intentionally player-facing: it hides debug-heavy backend fields and shows summarized gameplay UI.
- `/demo/dev` is the full debugging surface (manual story/version, timeline, snapshots, rollback, raw replay).

Manual seed:

```bash
python scripts/seed.py
```

Or via Makefile:

```bash
make venv
make install
make migrate
make test
```

Health:

```bash
curl http://localhost:8000/health
```

## Docker

```bash
docker-compose up --build
```

## Migration

```bash
DATABASE_URL=sqlite:///./app.db alembic upgrade head
```

## Database Rebase (local)

When DB schema changes (especially baseline hard-cut updates), rebuild local DB from migrations:

```bash
# rebase dev.db
rm -f dev.db
ENV=dev DATABASE_URL=sqlite:///./dev.db python -m alembic upgrade head
python scripts/seed.py
```

```bash
# rebase app.db (if you use app.db locally)
rm -f app.db
DATABASE_URL=sqlite:///./app.db python -m alembic upgrade head
```

Or run:

```bash
./scripts/dev.sh
```

Auth hard-cut note:
- This baseline removed legacy auth tables/columns.
- Recreate old local DB files before upgrading (for example, delete `dev.db` / `app.db` and run migration again).

## Test

```bash
python -m pytest -q
python -m pytest client/tests -q
```

## Documentation

- Entry point: `docs/INDEX.md`

## Sample StoryPack + Simulation

Sample pack:
- `examples/storypacks/campus_week_v1.json`
- `examples/storypacks/quick_demo_v1.json`

Load and publish it:

```bash
curl -X POST http://127.0.0.1:8000/stories \
  -H "Content-Type: application/json" \
  --data @examples/storypacks/campus_week_v1.json

curl -X POST "http://127.0.0.1:8000/stories/campus_week_v1/publish?version=1"
```

Run deterministic balance simulation:

```bash
python scripts/simulate_runs.py --story-id campus_week_v1 --runs 200 --policy balanced --seed 42
```

Distribution acceptance gates (`playable_v1` profile):

```bash
python scripts/simulate_runs.py --story-id campus_week_v1 --runs 200 --policy balanced --seed 42 --assert-profile playable_v1
python scripts/simulate_runs.py --story-id campus_week_v1 --runs 300 --policy random --seed 42 --assert-profile playable_v1 --assert-runs-min 200
```

`playable_v1` checks:
- balanced: success `0.40-0.55`, neutral `0.30-0.45`, fail `0.10-0.20`, timeout `<=0.05`, average steps `14-22`, events/run `>=0.50`
- random: timeout `<=0.12`, success `>=0.08`, fail `>=0.15`, average steps `10-22`, events/run `>=0.40`

Quick import to DB with one curl command:

```bash
curl -X POST http://127.0.0.1:8000/stories -H "Content-Type: application/json" --data @examples/storypacks/quick_demo_v1.json
```
