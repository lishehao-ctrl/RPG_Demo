# Verification

## Migration verification

```bash
DATABASE_URL=sqlite:///./manual_m6.db alembic upgrade head
```

Expected: command exits 0 and creates all required tables.

## Test suite

```bash
pytest -q
```

## Milestone 6 checklist

- `tests/test_llm_integration.py`
  - classify success updates tags used by AffectionEngine
  - classify provider failure falls back to deterministic stub
  - narrative generation success writes schema-valid choices
  - invalid narrative schema triggers repair attempt
  - `llm_usage_logs` rows are written on both success and failure
  - token budget decrement matches logged token usage
  - narrative falls back to deterministic template when provider fails

- Existing Milestone 5 replay tests still pass:
  - replay determinism
  - missed route (priority-lost + near-miss unlock hints)
  - `/end` idempotent upsert behavior

## Manual run (optional)

```bash
LLM_PROVIDER_PRIMARY=fake uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then call `/sessions` and `/sessions/{id}/step` to verify LLM-integrated flow without external network.

## Real provider env vars (manual only)

- `LLM_PROVIDER_PRIMARY=doubao`
- `LLM_DOUBAO_API_KEY=...`
- `LLM_DOUBAO_BASE_URL=...`
- `LLM_MODEL_CLASSIFY=...`
- `LLM_MODEL_GENERATE=...`
