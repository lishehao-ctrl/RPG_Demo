# API

## Health
- `GET /health` -> `{"status":"ok"}`

## Session (Milestone 6)
- `POST /sessions`
  - Create session with deterministic token budget initialization.
  - Creates at least one default `session_character_state`.

- `GET /sessions/{id}`
  - Return structured session state, character states, and current node.

- `POST /sessions/{id}/step`
  - Body: `{ "input_text"?: string, "choice_id"?: string }` (at least one required).
  - LLM classify pipeline:
    - primary provider retry (`llm_max_retries`)
    - schema validation (`PlayerInputClassification`)
    - provider fallback chain
    - deterministic keyword stub fallback if all fail
  - LLM narrative pipeline:
    - prompt built from session summary/branch/character state/player input/classification
    - schema validation (`NarrativeOutput`)
    - one repair attempt for invalid JSON/schema
    - fallback providers
    - deterministic template fallback if all fail
  - Every provider attempt logs to `llm_usage_logs` (success or error).
  - Token budget uses actual logged tokens when available; otherwise conservative deterministic estimate.
  - Hard limit error: `409 {"detail":{"code":"TOKEN_BUDGET_EXCEEDED"}}`.

- `POST /sessions/{id}/snapshot`
  - Creates snapshot storing full state payload + cutoff timestamp.

- `POST /sessions/{id}/rollback?snapshot_id=...`
  - Restores session and character states from snapshot and prunes nodes/logs newer than cutoff.

- `POST /sessions/{id}/end`
  - In one transaction: marks session ended, builds deterministic replay report, upserts `replay_reports`.

- `GET /sessions/{id}/replay`
  - Returns stored deterministic replay JSON report.
  - Returns `404` with `{"detail":{"code":"REPLAY_NOT_READY"}}` if report does not exist.

## Dev auth
- Current user is resolved by header `X-User-Id` (UUID).
- If omitted, fallback fixed UUID is used for local development/tests.
