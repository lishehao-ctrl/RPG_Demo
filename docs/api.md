# API

## Health
- `GET /health` -> `{"status":"ok"}`

## Demo Pages
- `GET /demo` -> redirects to `/demo/play`.
- `GET /demo/play` -> user-facing demo with story selection then gameplay.
- `GET /demo/dev` -> full developer debugging demo UI.
- `GET /demo/bootstrap` -> shared frontend bootstrap config:
  - `default_story_id`
  - `default_story_version`
  - `step_retry_max_attempts`
  - `step_retry_backoff_ms`
- `GET /stories` -> story list for picker UI (default: published + playable only).

### User Demo Consumption Guidance
- `/demo/play` should render player-facing summaries rather than raw backend payload blocks.
- Recommended:
  - hide debug fields (`phase`, `session_id`, token totals),
  - render `choices` with friendly type badges and disabled locked states,
  - map `unavailable_reason` to user-readable copy,
  - show replay in collapsed summary mode, not raw JSON.

## Story
- `POST /stories/validate`
- `POST /stories`
- `GET /stories`
- `GET /stories/{story_id}`
- `POST /stories/{story_id}/publish?version=...`

### `GET /stories`
- Query:
  - `published_only: bool` (default `true`)
  - `playable_only: bool` (default `true`)
- Response:
  - `stories: [{story_id, version, title, is_published, is_playable, summary}]`

### `POST /stories/{story_id}/publish`
- Publish is blocked when pack is structurally invalid.
- Failure response:
  - `400` with `detail.code = "STORY_INVALID_FOR_PUBLISH"`
  - `detail.errors` includes validation details.

## Session
- `POST /sessions`
- `GET /sessions/{id}`
- `POST /sessions/{id}/step`
- `POST /sessions/{id}/snapshot`
- `POST /sessions/{id}/rollback?snapshot_id=...`
- `POST /sessions/{id}/end`
- `GET /sessions/{id}/replay`

Session endpoints are anonymous in single-tenant mode:
- no auth headers are required,
- legacy auth headers are ignored by API runtime.

### `POST /sessions`
- Request body:
  - `story_id: string` (required)
  - `version: int | null` (optional)
- Missing `story_id` is schema error (`422`).
- `GET /sessions/{id}` response no longer includes `user_id`.
- Session state includes deterministic base stats plus optional quest runtime state:
  - `state_json.quest_state.active_quests`
  - `state_json.quest_state.completed_quests`
  - `state_json.quest_state.quests`
  - `state_json.quest_state.quests[quest_id].current_stage_id`
  - `state_json.quest_state.quests[quest_id].current_stage_index`
  - `state_json.quest_state.quests[quest_id].stages`
  - `state_json.quest_state.recent_events`
  - `state_json.quest_state.event_seq`
- Session state also includes run lifecycle state:
  - `state_json.run_state.step_index`
  - `state_json.run_state.triggered_event_ids`
  - `state_json.run_state.event_cooldowns`
  - `state_json.run_state.ending_id`
  - `state_json.run_state.ending_outcome`
  - `state_json.run_state.ended_at_step`
  - `state_json.run_state.fallback_count`
- Session node pointer contract (`GET /sessions/{id}`):
  - `current_node_id` is a StoryPack node id string.
  - `current_node.id` is the same story node id string.
  - `current_node.parent_node_id` is string or null.

### Story-mode step behavior (`POST /sessions/{id}/step`)
- Optional request header:
  - `X-Idempotency-Key: string`
  - Recommended for all production clients.
- Idempotency semantics when header is present:
  - same `session_id` + same key + same payload -> returns cached success response (no duplicate state advance).
  - same `session_id` + same key + different payload -> `409`, `detail.code=IDEMPOTENCY_KEY_REUSED`.
  - same key still being processed -> `409`, `detail.code=REQUEST_IN_PROGRESS`.
- If the header is omitted, runtime keeps backward-compatible non-idempotent behavior.
- Request body accepts only:
  - `choice_id: string | null`
  - `player_input: string | null`
- Unknown fields are rejected (`422`).
- Sending both `choice_id` and `player_input` is rejected (`422`, `detail.code=INPUT_CONFLICT`).
- Sending neither field is valid and enters Pass0 `NO_INPUT` fallback (`200`).
- Free-input selection uses conservative rescue semantics:
  - if LLM selector returns `use_fallback=true`, runtime still attempts deterministic intent/rule mapping before fallback.
  - deterministic mapping only applies when confidence is at least `story_map_min_confidence` (default `0.60`).
  - low-confidence or ambiguous mapping keeps fallback behavior to guide the run.
- Runtime keeps accept-all semantics for mapping/gating/input issues and returns `200` for non-inactive sessions.
- Only inactive story sessions return `409` with `detail.code == "SESSION_NOT_ACTIVE"`.
- Narrative provider-chain exhaustion returns `503` with `detail.code == "LLM_UNAVAILABLE"`.
- `LLM_UNAVAILABLE` failure does not advance node/state.
- `StepResponse` keeps existing fields and adds:
  - `run_ended: bool`
  - `ending_id: string | null`
  - `ending_outcome: "success" | "neutral" | "fail" | null`
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
- Replay response is story-runtime focused and includes:
  - `session_id`
  - `total_steps`
  - `key_decisions`
  - `fallback_summary`
  - `story_path`
  - `state_timeline`
- Replay response adds:
  - `run_summary.ending_id`
  - `run_summary.ending_outcome`
  - `run_summary.total_steps`
  - `run_summary.triggered_events_count`
  - `run_summary.fallback_rate`
- Replay no longer includes branch/affection route-analysis keys.
