# API

## Health
- `GET /health` -> `{"status":"ok"}`

## Auth
- `GET /auth/google/login`
  - Returns JSON: `{ "auth_url": "..." }`
  - Includes signed `state` token and standard OAuth query params.

- `GET /auth/google/callback?code=...&state=...`
  - Validates state token.
  - Exchanges code for Google tokens.
  - Verifies `id_token` claims.
  - Upserts user by `google_sub`.
  - Returns JWT: `{ "access_token": "...", "token_type": "bearer", "user": {...} }`.

- `GET /auth/me`
  - Returns authenticated user profile based on Bearer JWT.
  - In `env=dev`, supports fallback `X-User-Id` if Authorization header missing.

## Session
- `POST /sessions`
- `GET /sessions/{id}`
- `POST /sessions/{id}/step`
- `POST /sessions/{id}/snapshot`
- `POST /sessions/{id}/rollback?snapshot_id=...`
- `POST /sessions/{id}/end`
- `GET /sessions/{id}/replay`

Session endpoints require authenticated user identity:
- Production/non-dev: `Authorization: Bearer <jwt>` is required.
- Dev mode: Bearer token preferred, `X-User-Id` fallback supported.
