# RPG Demo Backend Scaffold

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
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
alembic upgrade head
```

## Test

```bash
pytest -q
```
