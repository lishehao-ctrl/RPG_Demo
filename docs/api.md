# API

## Health
- `GET /health` -> `{"status":"ok"}`

## Session (Milestone 5)
- `POST /sessions`
  - Create session with deterministic token budget initialization.
  - Creates at least one default `session_character_state`.

- `GET /sessions/{id}`
  - Return structured session state, character states, and current node.

- `POST /sessions/{id}/step`
  - Body: `{ "input_text"?: string, "choice_id"?: string }` (at least one required).
  - Deterministic classifier stub extracts behavior tags.
  - AffectionEngine updates per-character score/vector/drift.
  - BranchEngine evaluates all candidate branches and stores full evaluation traces in `action_logs.branch_evaluation`.
  - Stores chosen branch in `dialogue_nodes.branch_decision`.

- `POST /sessions/{id}/snapshot`
  - Creates snapshot storing full state payload + cutoff timestamp.

- `POST /sessions/{id}/rollback?snapshot_id=...`
  - Restores session and character states from snapshot and prunes nodes/logs newer than cutoff.

- `POST /sessions/{id}/end`
  - In one transaction: marks session ended, builds deterministic replay report, upserts `replay_reports`.
  - Response: `{ "ended": true, "replay_report_id": "...", "route_type": "..." }`.

- `GET /sessions/{id}/replay`
  - Returns stored deterministic replay JSON report.
  - Returns `404` with `{"detail":{"code":"REPLAY_NOT_READY"}}` if report does not exist.

## Replay report schema (top-level)
```json
{
  "session_id": "...",
  "route_type": "string",
  "decision_points": [],
  "affection_timeline": {},
  "relation_vector_final": {},
  "affection_attribution": [],
  "missed_routes": [],
  "what_if": []
}
```

## Dev auth
- Current user is resolved by header `X-User-Id` (UUID).
- If omitted, fallback fixed UUID is used for local development/tests.
