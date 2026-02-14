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
pytest -q
pytest -q client/tests
```
