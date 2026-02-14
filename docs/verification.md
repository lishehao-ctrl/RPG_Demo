# Verification

## Migration verification

```bash
DATABASE_URL=sqlite:///./manual_auth.db alembic upgrade head
```

Expected: command exits 0 and creates all required tables.

## Test suite

```bash
pytest -q
pytest -q client/tests
```

## OAuth + JWT local manual steps

Required env vars:
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `JWT_SECRET`
- `ENV=dev`

Run server:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Flow:
1. Call `/auth/google/login` and open returned `auth_url` in browser.
2. Complete Google login.
3. Google redirects to `/auth/google/callback` and backend returns JWT.
4. Use JWT as `Authorization: Bearer <token>` for `/sessions` endpoints.

## Deterministic test expectations

- No real Google network calls in tests.
- OAuth tests monkeypatch token exchange + id_token verification.
- Non-dev env rejects `X-User-Id` fallback (requires Bearer).
- Expired OAuth state returns `400` with `STATE_EXPIRED`.
- Callback `?error=...` returns structured `400` and writes `audit_logs` event.
- JWT auth accepts small clock skew leeway (60s) around `exp/iat`.

## Production guardrail

If `ENV != dev` and `JWT_SECRET` is left as default (`change-me-in-prod`), app startup fails fast.

## CI

GitHub Actions workflow: `.github/workflows/ci.yml`
- `unit-sqlite`: sqlite migration + backend pytest + client pytest
- `integration-postgres`: postgres migration + backend pytest
- CI sets `LLM_PROVIDER_PRIMARY=fake` to avoid external LLM calls
