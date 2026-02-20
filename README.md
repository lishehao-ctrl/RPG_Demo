# RPG Demo - Run Server

## Prerequisites

- Python `>=3.11`
- `pip`

## Quick Start (Recommended)

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e "./client[pretty]"
./scripts/dev.sh
```

`./scripts/dev.sh` will:
- set `ENV=dev`
- run `alembic upgrade head`
- run `python scripts/seed.py` by default
- start server with reload enabled

Server URL:
- `http://127.0.0.1:8000`

Demo URLs:
- `http://127.0.0.1:8000/demo/play`
- `http://127.0.0.1:8000/demo/dev`
- `/demo/dev` now includes an **LLM Debug Trace** panel for diagnosing `LLM_UNAVAILABLE`.

## Manual Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e "./client[pretty]"
ENV=dev DATABASE_URL=sqlite:///./dev.db python -m alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload
```
