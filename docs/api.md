# API

## Health
- `GET /health` -> `{"status":"ok"}`

## Auth
- `GET /auth/google/login`
  - Returns JSON: `{ "auth_url": "..." }`
  - Includes signed `state` token and standard OAuth query params.

- `GET /auth/google/callback?code=...&state=...`
  - Validates state token (`STATE_EXPIRED` for expired token, `INVALID_STATE` for invalid token).
  - Exchanges code for Google tokens.
  - Verifies `id_token` claims.
  - Upserts user by `google_sub`.
  - Returns JWT: `{ "access_token": "...", "token_type": "bearer", "user": {...} }`.
  - If Google returns callback error (`?error=...`), returns `400` with `{ "code": "GOOGLE_OAUTH_ERROR", ... }` and writes audit log.

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

### `POST /sessions`
- Request body:
  - `story_id: string` (required)
  - `version: int | null` (optional)
- Missing `story_id` is schema error (`422`).
- Session state includes deterministic base stats plus optional quest runtime state:
  - `state_json.quest_state.active_quests`
  - `state_json.quest_state.completed_quests`
  - `state_json.quest_state.quests`
  - `state_json.quest_state.quests[quest_id].current_stage_id`
  - `state_json.quest_state.quests[quest_id].current_stage_index`
  - `state_json.quest_state.quests[quest_id].stages`
  - `state_json.quest_state.recent_events`
  - `state_json.quest_state.event_seq`

### Story-mode step behavior (`POST /sessions/{id}/step`)
- Request body accepts only:
  - `choice_id: string | null`
  - `player_input: string | null`
- Unknown fields are rejected (`422`).
- Sending both `choice_id` and `player_input` is rejected (`422`, `detail.code=INPUT_CONFLICT`).
- Sending neither field is valid and enters Pass0 `NO_INPUT` fallback (`200`).
- Runtime keeps accept-all semantics for mapping/gating/input issues and returns `200` for non-inactive sessions.
- Only inactive story sessions return `409` with `detail.code == "SESSION_NOT_ACTIVE"`.
- `StepResponse` shape is unchanged.
- Story telemetry fields stay available:
  - `attempted_choice_id`
  - `executed_choice_id`
  - `resolved_choice_id`
  - `fallback_used`
  - `fallback_reason`
  - `mapping_confidence`
- Outward `fallback_reason` uses neutral values:
  - `NO_INPUT`, `BLOCKED`, `FALLBACK`, or `null` (non-fallback path).

### Replay payload contract (`GET /sessions/{id}/replay`)
- Replay response keeps `missed_routes` and `what_if` keys for contract stability.
- In current story-only runtime they are present as empty lists.
