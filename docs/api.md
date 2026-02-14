# API

## Health
- `GET /health` -> `{"status":"ok"}`

## Session (Milestone 4)
- `POST /sessions`
  - Create session with deterministic token budget initialization.
  - Creates at least one default `session_character_state`.
- `GET /sessions/{id}`
  - Return structured session state, character states, and current node.
- `POST /sessions/{id}/step`
  - Body: `{ "input_text"?: string, "choice_id"?: string }` (at least one required)
  - Deterministic classifier stub extracts behavior tags from text.
  - AffectionEngine updates per-character score/vector/drift.
  - BranchEngine evaluates branch DSL against stable context and records chosen branch.
  - Persists `dialogue_nodes` + `action_logs` + updated character states in one transaction.
- `POST /sessions/{id}/snapshot`
  - Creates snapshot storing full state payload + cutoff timestamp.
- `POST /sessions/{id}/rollback?snapshot_id=...`
  - Restores session and character states from snapshot and prunes nodes/logs newer than cutoff.
- `POST /sessions/{id}/end`
  - Sets session status to `ended`.
- `GET /sessions/{id}/replay`
  - Placeholder, returns `501`.

## Dev auth
- Current user is resolved by header `X-User-Id` (UUID).
- If omitted, fallback fixed UUID is used for local development/tests.
