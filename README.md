# RPG Demo Backend Scaffold

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

## Requirements
- Python **>= 3.11** (recommended: `3.11.9`, see `.python-version`)
- In production (`ENV != dev`), `JWT_SECRET` must be set to a non-default value (startup fails fast otherwise).

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

Demo UI:

```bash
open http://localhost:8000/demo
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

## Test

```bash
python -m pytest -q
python -m pytest client/tests -q
```

## Documentation

- Entry point: `docs/INDEX.md`
