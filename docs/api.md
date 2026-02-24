# API

## Health
- `GET /health` -> `{"status":"ok"}`

## Demo Pages
- `GET /demo` -> redirects to `/demo/play`.
- `GET /demo/play` -> player-facing demo UI.
- `GET /demo/dev` -> developer debugging demo UI.
- `GET /demo/author` -> ASF v4 authoring wizard.
- `GET /demo/bootstrap` -> shared frontend bootstrap config.

## Story
- `POST /stories/validate`
- `POST /stories/validate-author`
- `POST /stories/compile-author`
- `POST /stories/author-assist`
- `POST /stories`
- `GET /stories`
- `GET /stories/{story_id}`
- `POST /stories/{story_id}/publish?version=...`

### `POST /stories/validate-author`
- Purpose:
  - validate `Author Story Format (ASF) v4` payload and run runtime + playability checks on compiled preview.
- Request body:
  - ASF v4 JSON payload (`format_version=4`, layered top-level schema).
- Response:
  - `valid: bool`
  - `errors: [{code, path, message, suggestion}]`
  - `warnings: [{code, path, message, suggestion}]`
  - `compiled_preview: StoryPack v10 | null`
  - `playability: {pass, blocking_errors, warnings, metrics}`
    - `metrics` includes:
      - `ending_reach_rate`
      - `stuck_turn_rate`
      - `no_progress_rate`
      - `branch_coverage`
      - `choice_contrast_score`
      - `dominant_strategy_rate`
      - `recovery_window_rate`
      - `tension_loop_score`
- Behavior:
  - if any author/runtime validation errors exist: `valid=false`, `compiled_preview=null`.
  - warnings never change status code.
  - pre-v4 payload is rejected with `422`:
    - `detail.code = "AUTHOR_V4_REQUIRED"`
    - `detail.message` includes minimal migration hints.

### `POST /stories/compile-author`
- Purpose:
  - deterministically compile ASF v4 payload to runtime `StoryPack v10`.
- Request body:
  - ASF v4 JSON payload.
- Success response (`200`):
  - `pack: StoryPack v10`
    - includes optional `author_source_v4` metadata for author/debug traceability.
  - `diagnostics`:
    - `errors: []`
    - `warnings: [{code, path, message, suggestion}]`
    - `mappings`:
      - `scenes`: `scene_key -> node_id`
      - `options`: `<scene_key>.<option_key> -> choice_id`
      - `quests`: `quest_key -> quest_id`
- Failure response (`400`):
  - `detail.code = "AUTHOR_COMPILE_FAILED"`
  - `detail.valid = false`
  - `detail.errors`: author/runtime diagnostics
  - `detail.warnings`: non-blocking diagnostics
- Failure response (`422`):
  - `detail.code = "AUTHOR_V4_REQUIRED"` for pre-v4 payloads.

### Runtime Pack Hard-Cut (v10 strict only)
- Startup now scans all stored packs in `stories.pack_json`.
- Any legacy/non-strict pack blocks startup with:
  - `LEGACY_STORYPACKS_BLOCK_STARTUP`
- Runtime session load no longer applies legacy projection/compat reading.
- If an invalid stored pack is loaded at runtime, APIs return:
  - `detail.code = "RUNTIME_PACK_V10_REQUIRED"`
  - `detail.errors = [...]` (strict schema/structural diagnostics)
- Troubleshooting:
  - startup failure: inspect logged `story_id/version` pairs from strict scan and repair/remove those rows.
  - runtime failure: call `POST /stories/compile-author` on the source ASF v4 payload to regenerate strict v10 pack.

### `POST /stories/author-assist`
- Purpose:
  - return optional authoring suggestions for the wizard without mutating stored stories.
- Request body:
  - `task`: one of
    - `story_ingest`
    - `seed_expand`
    - `beat_to_scene`
    - `scene_deepen`
    - `option_weave`
    - `consequence_balance`
    - `ending_design`
    - `consistency_check`
    - `continue_write`
    - `trim_content`
    - `spice_branch`
    - `tension_rebalance`
  - `locale`: target story content language code (default `en`)
  - `context`: object with current wizard fields (including `format_version=4`)
    - optional controls:
      - `operation: append | trim | rewrite`
      - `target_scope: global | layer | scene | option`
      - `target_scene_key: string | null`
      - `target_option_key: string | null`
      - `preserve_existing: bool`
- Response (`200`):
  - `suggestions: object`
  - `patch_preview: [{id, path, label, value}]`
  - `warnings: [string]`
  - `model: string`
- Failure (`503`):
  - `detail.code = "ASSIST_LLM_UNAVAILABLE"` when model call fails/unavailable.
  - `detail.code = "ASSIST_INVALID_OUTPUT"` when model output is not valid assist JSON.
  - `detail.message` is retry-first and code-aligned.
  - `detail.retryable = true`
  - `detail.hint` provides a short operator-friendly recovery hint.
- Notes:
  - response is suggestion-only; no server-side write is performed.
  - server no longer returns deterministic assist fallback payloads on model failures.
  - backend LLM transport is fixed to OpenAI-compatible chat completions proxy:
    - `POST https://api.xiaocaseai.cloud/v1/chat/completions`
    - system message is always injected:
      - `Return STRICT JSON. No markdown. No explanation.`
    - `temperature` is always forced to `0`.
    - fail-fast retries: max 2 retries (`0.5s`, `1s`) then raises.
    - no `/v1/responses`, no `response_format`, no `json_schema` request payload.
  - current `/demo/author` applies patch rows automatically in frontend as a UX policy.
  - auto-apply is UI behavior only; API contract remains unchanged.
  - `seed_expand` is post-processed server-side to enforce a 4-node tension loop scaffold
    (`pressure_open`, `pressure_escalation`, `recovery_window`, `decision_gate`) and
    compile-safe scene/option connectivity.
  - unknown legacy tasks return `422 ASSIST_TASK_V4_REQUIRED`.

### `GET /stories`
- Query:
  - `published_only: bool` (default `true`)
  - `playable_only: bool` (default `true`)
- Response:
  - `stories: [{story_id, version, title, is_published, is_playable, summary}]`

## Session
- `POST /sessions`
- `GET /sessions/{id}`
- `GET /sessions/{id}/debug/layer-inspector` (dev only)
- `POST /sessions/{id}/step`
- `POST /sessions/{id}/snapshot`
- `POST /sessions/{id}/rollback?snapshot_id=...`
- `POST /sessions/{id}/end`
- `GET /sessions/{id}/replay`

Removed in hard-cut:
- `GET /sessions/{id}/debug/llm-trace`

Session endpoints are anonymous in single-tenant mode.

### `GET /sessions/{id}/debug/layer-inspector` (Developer Debug)
- Purpose:
  - inspect each runtime step through 7 conceptual layers:
    - `world_layer`
    - `characters_layer`
    - `plot_layer`
    - `scene_layer`
    - `action_layer`
    - `consequence_layer`
    - `ending_layer`
- Availability:
  - only when `ENV=dev`.
  - if `ENV!=dev`, returns `404` with `detail.code="DEBUG_DISABLED"`.
- Query:
  - `limit: int` (optional, default `20`, bounded by backend).
- Response shape:
  - `session_id`
  - `env`
  - `steps[]`
    - `step_index`
    - layer snapshots listed above
    - `raw_refs` (`action_log_id`, timestamps)
  - `summary`
    - `fallback_rate`
    - `mismatch_count`
    - `event_turns`
    - `guard_all_blocked_turns`
    - `guard_stall_turns`
    - `dominant_route_alerts`
    - `low_recovery_turns`
    - `ending_state`

### Story-mode step behavior (`POST /sessions/{id}/step`)
- Request body accepts only:
  - `choice_id: string | null`
  - `player_input: string | null`
- Sending both is rejected (`422`, `detail.code=INPUT_CONFLICT`).
- Sending neither is valid and enters `NO_INPUT` fallback path.
- `LLM_UNAVAILABLE` returns `503`; step is not applied.
- Current Step response key fields:
  - `story_node_id`
  - `attempted_choice_id`
  - `executed_choice_id`
  - `resolved_choice_id`
  - `fallback_used`
  - `fallback_reason`
  - `mapping_confidence`
  - `narrative_text`
  - `choices`
  - `run_ended`
  - `ending_id`
  - `ending_outcome`

## Architecture Guardrails (for API-compatible refactors)
1. Keep all listed routes and response shapes stable.
2. Keep runtime hard-cut policy:
- no compatibility projection for legacy story pack payloads.
3. Keep compile/validate deterministic:
- `validate-author` and `compile-author` must not depend on live LLM calls.
4. Keep author-assist suggestion-only:
- no implicit write side effects from `POST /stories/author-assist`.
5. Before merging architecture changes, run:
- `docs/verification.md` -> `Architecture PR Minimum Gate`.
