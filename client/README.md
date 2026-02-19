# RPG CLI Client

Minimal Typer-based CLI for the FastAPI backend.

## Requirements
- Python **>= 3.11** (recommended: `3.11.9`)
- Backend running (default `http://127.0.0.1:8000`)

## Install

From repo root (canonical command):

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e "./client[pretty]"
```

Or inside `client/` only:

```bash
cd client
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[pretty]"
```

## Environment
- `BACKEND_URL` (default: `http://127.0.0.1:8000`)
- `AUTH_TOKEN` (optional; if set, CLI sends `Authorization: Bearer <token>`)
- `X_USER_ID` (default: `00000000-0000-0000-0000-000000000001`, used only when `AUTH_TOKEN` is not set)

CLI persists lightweight state to `client/.state.json`:
- `session_id`
- `snapshot_id`

## Commands

```bash
rpg ping
rpg session create --story-id campus_life
rpg session get [SESSION_ID]
rpg step --text "hello"
rpg step --choice-id "c1"
rpg snapshot --name "manual"
rpg rollback --snapshot-id "..."
rpg end
rpg replay
```

If `session_id`/`snapshot_id` are omitted, the CLI uses values from `client/.state.json`.

## Demo flow

```bash
rpg ping
rpg session create --story-id campus_life
rpg step --text "hello"
rpg snapshot --name "manual"
rpg step --text "another input"
rpg rollback
rpg end
rpg replay
```

## Tests

```bash
pytest -q client/tests
```


### OAuth/JWT example

```bash
# after completing /auth/google/callback and getting access_token
export AUTH_TOKEN="<jwt>"
rpg session create --story-id campus_life
```
